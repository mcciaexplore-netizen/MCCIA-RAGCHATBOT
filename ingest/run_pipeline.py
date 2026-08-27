"""Orchestrates Phase 2 end to end: Drive sync -> extract (OCR) -> split into
issues (Gemini) -> split each issue into articles (Gemini) -> chunk+embed
(Gemini) -> write to Postgres. Also Phase 6's web-archive check (see
cmd_check_web).

Usage:
    python -m ingest.run_pipeline sync              # pull PDFs from Drive
    python -m ingest.run_pipeline process            # extract+split+embed+write
    python -m ingest.run_pipeline process --force    # reprocess even if already ingested
    python -m ingest.run_pipeline process --start-at "1949 April.PDF"
    python -m ingest.run_pipeline check-web          # log web issues not yet ingested
    python -m ingest.run_pipeline all                # sync, process, check-web
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from db.connection import connect
from ingest.config import local_staging_dir
from ingest.db_writer import already_ingested, ingested_issue_months, issue_month_source, write_article
from ingest.detect_issue_boundaries import IssueBoundary, IssueBoundaryError, split_into_issues
from ingest.drive_sync import load_drive_ids, sync_all
from ingest.extract_text import extract_pages, full_text
from ingest.manual_review import log_manual_review
from ingest.split_articles import ArticleSplitError, split_issue_into_articles
from ingest.web_archive import check_for_new_issues, lookup_source_url


def process_pdf(pdf_path: Path, drive_file_id: str, force: bool = False) -> int:
    """Returns the number of issues newly written from this PDF.

    A single PDF can bundle several issues (see extract_text.py and
    detect_issue_boundaries.py) -- this OCRs the whole file once, splits it
    into its individual issues, then processes each issue independently
    (its own resumability check, its own article-splitting call, its own
    short-lived DB connection for the write), so one bad issue doesn't take
    down the others bound in the same file.
    """
    pages = extract_pages(pdf_path)

    try:
        issues = split_into_issues(pages)
    except IssueBoundaryError as exc:
        log_manual_review(pdf_path.name, f"Gemini could not find issue boundaries: {exc}")
        print(f"[SKIP] {pdf_path.name}: issue-boundary detection failed, logged for manual review")
        return 0

    processed = sum(
        _process_one_issue(pdf_path, drive_file_id, boundary, issue_pages, force=force)
        for boundary, issue_pages in issues
    )

    print(f"[OK] {pdf_path.name} -> {len(issues)} issue(s) detected, {processed} newly processed")
    return processed


def _process_one_issue(
    pdf_path: Path, drive_file_id: str, boundary: IssueBoundary, issue_pages: list, force: bool
) -> bool:
    """Returns True if this one issue was newly written, False if skipped."""
    issue_month = f"{boundary.year:04d}-{boundary.month:02d}"
    log_prefix = f"{pdf_path.name} {issue_month}"

    conn = connect()
    try:
        if not force and already_ingested(conn, drive_file_id, issue_month):
            print(f"[SKIP] {log_prefix}: already in the database (use --force to reprocess)")
            return False

        existing_source = issue_month_source(conn, issue_month)
        if existing_source and existing_source != drive_file_id:
            log_manual_review(
                pdf_path.name,
                f"{issue_month}: already ingested from a different source PDF "
                f"(drive_file_id={existing_source}) -- likely an overlapping/duplicate scan, "
                f"skipped rather than double-writing this issue",
            )
            print(f"[SKIP] {log_prefix}: already ingested from a different source PDF, logged for manual review")
            return False
    finally:
        conn.close()

    text = full_text(issue_pages)
    if len(text) > 400_000:
        print(
            f"[WARN] {log_prefix}: extracted text is {len(text)} chars, "
            f"unusually large for one issue -- double check article splitting quality"
        )

    try:
        articles = split_issue_into_articles(text)
    except ArticleSplitError as exc:
        log_manual_review(pdf_path.name, f"{issue_month}: Gemini returned malformed article boundaries twice: {exc}")
        print(f"[SKIP] {log_prefix}: article splitting failed, logged for manual review")
        return False

    if not articles:
        log_manual_review(pdf_path.name, f"{issue_month}: Gemini returned zero article boundaries")
        print(f"[SKIP] {log_prefix}: no articles detected, logged for manual review")
        return False

    # Supplementary cross-check, 2021+ only -- see ingest/web_archive.py.
    source_url = lookup_source_url(issue_month) if boundary.year >= 2021 else None

    conn = connect()
    try:
        if force:
            with conn.cursor() as cur:
                cur.execute(
                    "delete from articles where drive_file_id = %s and issue_month = %s",
                    (drive_file_id, issue_month),
                )

        for article_index, article in enumerate(articles, start=1):
            write_article(
                conn,
                article,
                issue_year=boundary.year,
                issue_month_number=boundary.month,
                article_index=article_index,
                issue_month=issue_month,
                source_url=source_url,
                drive_file_id=drive_file_id,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[OK] {log_prefix}: {len(articles)} articles")
    return True


def cmd_sync(_args) -> None:
    downloaded = sync_all()
    print(f"Downloaded {len(downloaded)} new/updated PDFs")


def cmd_process(args) -> None:
    staging_dir = local_staging_dir()
    pdfs = sorted(staging_dir.glob("*.[pP][dD][fF]"))
    available_by_name = {pdf.name: pdf for pdf in pdfs}
    requested_files = set(getattr(args, "files", None) or [])
    if requested_files:
        missing = sorted(requested_files - available_by_name.keys())
        if missing:
            print(f"Requested PDF(s) not found in {staging_dir}: {', '.join(missing)}")
            return
        pdfs = [available_by_name[name] for name in sorted(requested_files)]

    start_at = getattr(args, "start_at", None)
    if start_at:
        if start_at not in available_by_name:
            print(f"Starting PDF not found in {staging_dir}: {start_at}")
            return
        pdfs = [pdf for pdf in pdfs if pdf.name >= start_at]

    if not pdfs:
        print(f"No PDFs found in {staging_dir}")
        return

    drive_ids = load_drive_ids(staging_dir)
    for pdf_path in pdfs:
        drive_file_id = drive_ids.get(pdf_path.name)
        if not drive_file_id:
            log_manual_review(pdf_path.name, "no Drive file ID on record -- run `sync` first")
            print(f"[SKIP] {pdf_path.name}: no Drive file ID on record, run `sync` first")
            continue

        # One bad PDF shouldn't take down a run through 70 years of issues --
        # process_pdf rolls back its own half-done write transaction; log
        # and keep going. Re-running afterward resumes cleanly either way.
        try:
            process_pdf(pdf_path, drive_file_id, force=args.force)
        except Exception as exc:
            log_manual_review(pdf_path.name, f"unexpected error: {exc}")
            print(f"[SKIP] {pdf_path.name}: unexpected error, logged for manual review: {exc}")


def cmd_check_web(_args) -> None:
    conn = connect()
    try:
        months = ingested_issue_months(conn)
    finally:
        conn.close()

    new_issues = check_for_new_issues(months)
    if not new_issues:
        print("[WEB CHECK] no issues found on the web archive that aren't already ingested")


def cmd_all(args) -> None:
    cmd_sync(args)
    cmd_process(args)
    cmd_check_web(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Pull new/updated PDFs from Google Drive")
    p_sync.set_defaults(func=cmd_sync)

    p_process = sub.add_parser("process", help="Extract, split, embed, and write articles to Postgres")
    p_process.add_argument("--force", action="store_true", help="Reprocess even if already in the database")
    p_process.add_argument(
        "--file",
        dest="files",
        action="append",
        help="Process only this exact staged PDF filename; repeat for multiple files",
    )
    p_process.add_argument(
        "--start-at",
        help="Resume the sorted archive at this exact staged PDF filename (inclusive)",
    )
    p_process.set_defaults(func=cmd_process)

    p_check_web = sub.add_parser(
        "check-web", help="Log mcciapunesampada.com issues not yet in the database"
    )
    p_check_web.set_defaults(func=cmd_check_web)

    p_all = sub.add_parser("all", help="sync, then process, then check-web")
    p_all.add_argument("--force", action="store_true")
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    load_dotenv()
    sys.exit(main())
