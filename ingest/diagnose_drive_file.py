"""Standalone diagnostic for one Google Drive PDF, run before assuming why a
file isn't making it into the RAG pipeline.

Independent of run_pipeline/drive_sync's batch logic -- this exercises the
same Drive API auth and download mechanics against a single file so a
download failure (permission, size, transient network) is visible on its
own, without an OCR/DB error further down the pipeline muddying the signal.

Usage:
    python -m ingest.diagnose_drive_file --file-id <drive_file_id>
    python -m ingest.diagnose_drive_file --name "1956 -April To 1957 -March Part No.12.pdf"
"""

import argparse
import io
import sys
from pathlib import Path

import pymupdf
from dotenv import load_dotenv
from googleapiclient.http import MediaIoBaseDownload

from db.config import google_drive_folder_id
from ingest.drive_sync import _is_transient_drive_error, build_drive_service, walk_pdfs
from ingest.gemini_retry import call_with_retry

TEMP_DIR = Path("/tmp/mcci-processing")
METADATA_FIELDS = "id, name, mimeType, size, modifiedTime, capabilities(canDownload)"


def find_file_id_by_name(service, name: str) -> str:
    """Walks the same configured folder tree run_pipeline uses (rather than
    a flat files().list() name query, which a service account can miss for
    files nested under a shared folder rather than shared directly) and
    matches by exact filename."""
    for f in walk_pdfs(service, google_drive_folder_id()):
        if f.name == name:
            return f.file_id
    raise SystemExit(f"No PDF named {name!r} found while walking the configured Drive folder")


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def download_with_progress(service, file_id: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(dest, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = call_with_retry(
                f"Drive download {dest.name}",
                downloader.next_chunk,
                is_transient=_is_transient_drive_error,
            )
            if status:
                print(f"  ... {status.progress() * 100:.1f}% ({_human_size(status.resumable_progress)})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file-id", help="Drive file ID to diagnose")
    group.add_argument("--name", help="Exact Drive filename to look up (searched, then diagnosed)")
    args = parser.parse_args()

    print("[1/9] Authenticating with Google Drive API...")
    service = build_drive_service()
    print("      OK")

    file_id = args.file_id
    if args.name:
        print(f"[2/9] Looking up file ID for {args.name!r}...")
        file_id = find_file_id_by_name(service, args.name)
        print(f"      found: {file_id}")
    else:
        print("[2/9] Using provided --file-id, skipping name lookup")

    print(f"[3/9] Fetching metadata for file_id={file_id}...")
    try:
        meta = call_with_retry(
            "Drive get metadata",
            lambda: service.files().get(fileId=file_id, fields=METADATA_FIELDS).execute(),
            is_transient=_is_transient_drive_error,
        )
    except Exception as exc:
        print(f"[FAIL] Could not fetch metadata: {exc!r}")
        return 1

    name = meta.get("name", "<unknown>")
    size_bytes = int(meta.get("size", 0) or 0)
    mime_type = meta.get("mimeType", "<unknown>")
    can_download = meta.get("capabilities", {}).get("canDownload")
    modified_time = meta.get("modifiedTime", "<unknown>")

    print(f"      name:          {name}")
    print(f"      size:          {_human_size(size_bytes)} ({size_bytes} bytes)")
    print(f"      mimeType:      {mime_type}")
    print(f"      modifiedTime:  {modified_time}")
    print(f"      canDownload:   {can_download}")

    if mime_type != "application/pdf":
        print(f"[FAIL] Not a PDF (mimeType={mime_type}) -- stopping here")
        return 1
    if can_download is False:
        print("[FAIL] Drive reports this account cannot download this file (permissions) -- stopping here")
        return 1

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    dest = TEMP_DIR / f"{file_id}.pdf"

    print(f"[4/9] Downloading actual PDF binary to {dest}...")
    try:
        download_with_progress(service, file_id, dest)
    except Exception as exc:
        print(f"[FAIL] Download did not complete: {exc!r}")
        if dest.exists():
            got = dest.stat().st_size
            print(f"       got {_human_size(got)} of {_human_size(size_bytes)} before failing")
            dest.unlink()
        return 1
    print(f"      OK -- {_human_size(dest.stat().st_size)} on disk")

    # Everything from here on must clean up dest (and any open doc handle) on
    # every exit path -- success, a handled [FAIL], or an unexpected
    # exception -- so the temp PDF never survives this function.
    doc = None
    try:
        print("[5/9] Verifying it's a valid, openable PDF...")
        try:
            doc = pymupdf.open(dest)
        except Exception as exc:
            print(f"[FAIL] pymupdf could not open the downloaded file: {exc!r}")
            return 1
        print("      OK -- opens cleanly")

        page_count = len(doc)
        print(f"[6/9] Page count: {page_count}")

        print("[7/9] Testing native text extraction on the first 3 pages...")
        sample_pages = min(3, page_count)
        total_chars = 0
        for i in range(sample_pages):
            text = doc[i].get_text()
            total_chars += len(text.strip())
            print(f"      page {i + 1}: {len(text.strip())} chars of native text")

        avg_chars = total_chars / sample_pages if sample_pages else 0
        print(f"[8/9] Average native text per sampled page: {avg_chars:.0f} chars")
        if avg_chars < 20:
            print("      -> effectively no usable text layer: OCR is necessary (expected for these scans)")
        else:
            print("      -> a real text layer appears present: OCR may be skippable for this file")

        print("\n=== SUCCESS ===")
        print(f"{name}: downloaded, valid PDF, {page_count} pages, OCR {'needed' if avg_chars < 20 else 'likely not needed'}.")
        return 0
    finally:
        if doc is not None:
            doc.close()
        dest.unlink(missing_ok=True)
        print(f"[9/9] Cleaned up temp file {dest}")


if __name__ == "__main__":
    load_dotenv()
    sys.exit(main())
