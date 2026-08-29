"""Pull PDFs down from a Google Drive folder into local staging.

We don't assume anything about how the Drive folder is organized (by year,
flat, mixed with other files) -- this walks the whole tree under
GOOGLE_DRIVE_FOLDER_ID recursively and grabs every application/pdf file.
Year/month is figured out later, from the PDF itself (see detect_issue_date.py),
not from Drive folder structure.
"""

import io
import json
import ssl
from pathlib import Path
from typing import Callable, Iterator, NamedTuple, Optional, Tuple

import httplib2
import pymupdf
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from db.config import google_drive_folder_id
from ingest.config import google_service_account_file, local_staging_dir, require_for_drive
from ingest.gemini_retry import TRANSIENT_STATUS_CODES, call_with_retry
from ingest.manual_review import log_manual_review

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"

# Network hiccups and Drive-side hiccups (rate limit, temporary server
# error) are worth retrying; a real "file not found" or "permission denied"
# response is not -- retrying either just wastes time before failing the
# same way.
_TRANSIENT_NETWORK_ERRORS = (TimeoutError, ConnectionError, ssl.SSLError, httplib2.HttpLib2Error)


def _is_transient_drive_error(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        return exc.resp.status in TRANSIENT_STATUS_CODES
    return isinstance(exc, _TRANSIENT_NETWORK_ERRORS)


class DriveFile(NamedTuple):
    file_id: str
    name: str
    modified_time: str
    size: int


def build_drive_service():
    require_for_drive()
    creds = service_account.Credentials.from_service_account_file(
        google_service_account_file(), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _list_children(service, folder_id: str):
    page_token = None
    while True:
        resp = call_with_retry(
            f"Drive list children of {folder_id}",
            lambda: service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                pageToken=page_token,
                pageSize=200,
            )
            .execute(),
            is_transient=_is_transient_drive_error,
        )
        yield from resp.get("files", [])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def walk_pdfs(service, root_folder_id: str) -> Iterator[DriveFile]:
    stack = [root_folder_id]
    while stack:
        folder_id = stack.pop()
        for f in _list_children(service, folder_id):
            if f["mimeType"] == FOLDER_MIME:
                stack.append(f["id"])
            elif f["mimeType"] == PDF_MIME:
                yield DriveFile(
                    file_id=f["id"],
                    name=f["name"],
                    modified_time=f.get("modifiedTime", ""),
                    size=int(f.get("size", 0) or 0),
                )


def download_file(
    service,
    file_id: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    """progress_cb, if given, is called after each chunk as
    (bytes_downloaded_so_far, total_bytes) -- optional so existing callers
    (sync_all) are unaffected; see archive_downloader.py for a consumer."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with io.FileIO(tmp, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = call_with_retry(
                    f"Drive download {dest.name}",
                    downloader.next_chunk,
                    is_transient=_is_transient_drive_error,
                )
                if progress_cb is not None and status is not None:
                    progress_cb(status.resumable_progress, status.total_size)
    except Exception:
        # Don't leave a partial (possibly hundreds-of-MB) file behind on
        # disk after a failed download -- the next sync_all() run starts
        # this file fresh anyway (download_file always opens tmp in "wb"),
        # so there's nothing to preserve, only space to reclaim.
        tmp.unlink(missing_ok=True)
        raise
    tmp.rename(dest)


def validate_pdf(path: Path) -> Tuple[bool, Optional[int], Optional[str]]:
    """Opens a downloaded file with pymupdf to confirm it's actually a
    readable PDF (a byte-count match alone doesn't catch a truncated-but-
    coincidentally-sized or corrupted file). Returns (is_valid, page_count,
    error) -- error is None on success, page_count is None on failure."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        return False, None, repr(exc)
    try:
        return True, len(doc), None
    finally:
        doc.close()


DRIVE_IDS_FILENAME = ".drive_ids.json"


def _drive_ids_path(dest_dir: Path) -> Path:
    return dest_dir / DRIVE_IDS_FILENAME


def load_drive_ids(dest_dir: Optional[Path] = None) -> dict:
    """filename -> Drive file_id, for whatever's currently in dest_dir.

    sampada.source_pdf_id needs the real Drive ID (so citations can always
    trace back to the source PDF), but sync_all() downloads files by name
    only -- this sidecar is what lets process_pdf() recover the ID for a
    given local file without extra Drive API calls.
    """
    path = _drive_ids_path(dest_dir or local_staging_dir())
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_drive_ids(dest_dir: Path, ids: dict) -> None:
    """Public so other Drive-walking callers (see archive_downloader.py) can
    keep this sidecar current without duplicating its format."""
    _drive_ids_path(dest_dir).write_text(json.dumps(ids, indent=2, sort_keys=True))


def sync_all(dest_dir: Optional[Path] = None, service=None) -> list:
    """Downloads every PDF under the configured Drive folder that isn't
    already present locally at the same size. Returns the list of local
    paths for files it downloaded (skips already-present files).

    The full archive is tens of gigabytes and can take a long time to pull
    down, so .drive_ids.json is saved after every file rather than once at
    the end -- `process` reads it to resolve each local PDF's drive_file_id
    (see run_pipeline.cmd_process), and waiting for the whole sync to finish
    before any processing could start would double the total wait for no
    reason: a `process` run against whatever's downloaded so far can safely
    run concurrently with the rest of this sync.
    """
    dest_dir = dest_dir or local_staging_dir()
    service = service or build_drive_service()
    downloaded = []
    drive_ids = load_drive_ids(dest_dir)
    for f in walk_pdfs(service, google_drive_folder_id()):
        drive_ids[f.name] = f.file_id
        dest = dest_dir / f.name
        if dest.exists() and dest.stat().st_size == f.size:
            save_drive_ids(dest_dir, drive_ids)
            continue
        # One file that exhausts its retries (or hits a permanent error)
        # shouldn't take the whole archive-wide sync down with it -- log it
        # for manual review and keep walking the rest of Drive, same as
        # run_pipeline.process_pdf already does for OCR/processing failures.
        try:
            download_file(service, f.file_id, dest)
        except Exception as exc:
            log_manual_review(f.name, f"download failed: {exc!r}")
            print(f"[SKIP] {f.name}: download failed, logged for manual review: {exc!r}")
            continue
        downloaded.append(dest)
        save_drive_ids(dest_dir, drive_ids)
    return downloaded


if __name__ == "__main__":
    paths = sync_all()
    print(f"Downloaded {len(paths)} new/updated PDFs to {local_staging_dir()}")
