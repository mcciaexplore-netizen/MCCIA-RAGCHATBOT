"""Orchestrates Phase 1 end to end: Drive sync -> extract -> split -> write ->
(optional) upload.

Usage:
    python -m ingest.run_pipeline sync                 # pull PDFs from Drive
    python -m ingest.run_pipeline process               # extract+split+write, local only
    python -m ingest.run_pipeline process --upload       # also push to S3
    python -m ingest.run_pipeline process --force        # reprocess even if unchanged
    python -m ingest.run_pipeline all --upload
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from .build_index import load_index, upsert_issue, write_index
from .config import CONFIG
from .detect_issue_date import detect_issue_date
from .extract_text import cover_text, extract_pages, full_text
from .split_articles import split_issue_into_articles
from .write_processed import write_issue_articles


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _load_manifest() -> dict:
    if CONFIG.state_manifest.exists():
        return json.loads(CONFIG.state_manifest.read_text())
    return {}


def _save_manifest(manifest: dict) -> None:
    CONFIG.state_manifest.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.state_manifest.write_text(json.dumps(manifest, indent=2))


def _log_manual_review(filename: str, reason: str) -> None:
    CONFIG.manual_review_log.parent.mkdir(parents=True, exist_ok=True)
    is_new = not CONFIG.manual_review_log.exists()
    with CONFIG.manual_review_log.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["filename", "reason"])
        writer.writerow([filename, reason])


def process_pdf(pdf_path: Path, upload: bool = False) -> bool:
    """Returns True if the PDF was processed, False if it was skipped (needs
    manual review, or already processed).
    """
    pages = extract_pages(pdf_path)
    year, month = detect_issue_date(pdf_path.name, cover_text(pages))
    if year is None:
        _log_manual_review(pdf_path.name, "could not detect issue year/month from filename or cover pages")
        print(f"[SKIP] {pdf_path.name}: could not detect issue date, logged for manual review")
        return False

    text = full_text(pages)
    if len(text) > 400_000:
        print(
            f"[WARN] {pdf_path.name}: extracted text is {len(text)} chars, "
            f"unusually large for one issue -- double check article splitting quality"
        )

    articles = split_issue_into_articles(text)
    if not articles:
        _log_manual_review(pdf_path.name, "Claude returned zero article boundaries")
        print(f"[SKIP] {pdf_path.name}: no articles detected, logged for manual review")
        return False

    written = write_issue_articles(articles, year, month)
    print(f"[OK] {pdf_path.name} -> {year:04d}-{month:02d}, {len(written)} articles")

    index = load_index(CONFIG.local_index_path)
    upsert_issue(index, year, month, written, articles)
    write_index(index, CONFIG.local_index_path)

    if upload:
        from .s3_upload import upload_index, upload_processed_issue, upload_raw_pdf

        upload_raw_pdf(pdf_path, year, month)
        upload_processed_issue(CONFIG.local_processed_dir / f"{year:04d}" / f"{month:02d}")
        upload_index(CONFIG.local_index_path)
        print(f"[UPLOAD] {pdf_path.name} -> s3://{CONFIG.s3_bucket}/")

    return True


def cmd_sync(_args) -> None:
    from .drive_sync import sync_all

    downloaded = sync_all()
    print(f"Downloaded {len(downloaded)} new/updated PDFs")


def cmd_process(args) -> None:
    manifest = _load_manifest()
    pdfs = sorted(CONFIG.local_staging_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {CONFIG.local_staging_dir}")
        return

    uploaded_anything = False
    for pdf_path in pdfs:
        digest = _sha256(pdf_path)
        key = str(pdf_path)
        if not args.force and manifest.get(key) == digest:
            print(f"[SKIP] {pdf_path.name}: already processed, unchanged (use --force to redo)")
            continue

        if process_pdf(pdf_path, upload=args.upload):
            manifest[key] = digest
            _save_manifest(manifest)
            uploaded_anything = uploaded_anything or args.upload

    if uploaded_anything:
        from .kb_sync import start_ingestion_job

        # One ingestion job for the whole run, not one per PDF -- Bedrock
        # re-scans the entire data source each time regardless.
        job_id = start_ingestion_job()
        print(f"[KB SYNC] started ingestion job {job_id}")


def cmd_all(args) -> None:
    cmd_sync(args)
    cmd_process(args)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sync = sub.add_parser("sync", help="Pull new/updated PDFs from Google Drive")
    p_sync.set_defaults(func=cmd_sync)

    p_process = sub.add_parser("process", help="Extract, split, and write articles locally")
    p_process.add_argument("--upload", action="store_true", help="Also upload raw PDF + processed articles to S3")
    p_process.add_argument("--force", action="store_true", help="Reprocess even if the PDF hasn't changed")
    p_process.set_defaults(func=cmd_process)

    p_all = sub.add_parser("all", help="sync, then process")
    p_all.add_argument("--upload", action="store_true")
    p_all.add_argument("--force", action="store_true")
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
