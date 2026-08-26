"""Orchestrates Phase 2 end to end: Drive sync -> extract -> detect date ->
split (Gemini) -> chunk+embed (Gemini) -> write to Postgres. Also Phase 6's
web-archive check (see cmd_check_web).

Usage:
    python -m ingest.run_pipeline sync              # pull PDFs from Drive
    python -m ingest.run_pipeline process            # extract+split+embed+write
    python -m ingest.run_pipeline process --force    # reprocess even if already ingested
    python -m ingest.run_pipeline check-web          # log web issues not yet ingested
    python -m ingest.run_pipeline all                # sync, process, check-web
"""

import argparse
import sys
from pathlib import Path

from db.connection import connect
from ingest.config import local_staging_dir
from ingest.db_writer import already_ingested, ingested_issue_months, write_article
from ingest.detect_issue_date import detect_issue_date
from ingest.drive_sync import load_drive_ids, sync_all
from ingest.extract_text import cover_text, extract_pages, full_text
from ingest.manual_review import log_manual_review
from ingest.split_articles import ArticleSplitError, split_issue_into_articles
from ingest.web_archive import check_for_new_issues, lookup_source_url


def process_pdf(pdf_path: Path, drive_file_id: str, conn, force: bool = False) -> bool:
    """Returns True if the PDF was processed, False if it was skipped."""
    if not force and already_ingested(conn, drive_file_id):
        print(f"[SKIP] {pdf_path.name}: already in the database (use --force to reprocess)")
        return False

    pages = extract_pages(pdf_path)
    year, month = detect_issue_date(pdf_path.name, cover_text(pages))
    if year is None:
        log_manual_review(pdf_path.name, "could not detect issue year/month from filename or cover pages")
        print(f"[SKIP] {pdf_path.name}: could not detect issue date, logged for manual review")
        return False

    text = full_text(pages)
    if len(text) > 400_000:
        print(
            f"[WARN] {pdf_path.name}: extracted text is {len(text)} chars, "
            f"unusually large for one issue -- double check article splitting quality"
        )

    issue_month = f"{year:04d}-{month:02d}"

    try:
        articles = split_issue_into_articles(text)
    except ArticleSplitError as exc:
        log_manual_review(pdf_path.name, f"Gemini returned malformed article boundaries twice: {exc}")
        print(f"[SKIP] {pdf_path.name}: article splitting failed, logged for manual review")
        return False

    if not articles:
        log_manual_review(pdf_path.name, "Gemini returned zero article boundaries")
        print(f"[SKIP] {pdf_path.name}: no articles detected, logged for manual review")
        return False

    # Supplementary cross-check, 2021+ only -- see ingest/web_archive.py.
    source_url = lookup_source_url(issue_month) if year >= 2021 else None

    if force:
        with conn.cursor() as cur:
            cur.execute("delete from articles where drive_file_id = %s", (drive_file_id,))

    for article in articles:
        write_article(
            conn,
            article,
            issue_month=issue_month,
            issue_year=year,
            source_url=source_url,
            drive_file_id=drive_file_id,
        )
    conn.commit()

    print(f"[OK] {pdf_path.name} -> {issue_month}, {len(articles)} articles")
    return True


def cmd_sync(_args) -> None:
    downloaded = sync_all()
    print(f"Downloaded {len(downloaded)} new/updated PDFs")


def cmd_process(args) -> None:
    staging_dir = local_staging_dir()
    pdfs = sorted(staging_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {staging_dir}")
        return

    drive_ids = load_drive_ids(staging_dir)
    conn = connect()
    try:
        for pdf_path in pdfs:
            drive_file_id = drive_ids.get(pdf_path.name)
            if not drive_file_id:
                log_manual_review(pdf_path.name, "no Drive file ID on record -- run `sync` first")
                print(f"[SKIP] {pdf_path.name}: no Drive file ID on record, run `sync` first")
                continue

            # One bad PDF shouldn't take down a run through 70 years of
            # issues -- roll back its half-done transaction, log it, and
            # keep going. Re-running afterward resumes cleanly either way.
            try:
                process_pdf(pdf_path, drive_file_id, conn, force=args.force)
            except Exception as exc:
                conn.rollback()
                log_manual_review(pdf_path.name, f"unexpected error: {exc}")
                print(f"[SKIP] {pdf_path.name}: unexpected error, logged for manual review: {exc}")
    finally:
        conn.close()


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
    sys.exit(main())
