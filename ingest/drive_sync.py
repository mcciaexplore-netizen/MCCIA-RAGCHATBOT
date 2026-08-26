"""Pull PDFs down from a Google Drive folder into local staging.

We don't assume anything about how the Drive folder is organized (by year,
flat, mixed with other files) -- this walks the whole tree under
GOOGLE_DRIVE_FOLDER_ID recursively and grabs every application/pdf file.
Year/month is figured out later, from the PDF itself (see detect_issue_date.py),
not from Drive folder structure.
"""

import io
import json
from pathlib import Path
from typing import Iterator, NamedTuple, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from db.config import google_drive_folder_id
from ingest.config import google_service_account_file, local_staging_dir, require_for_drive

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"


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
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                pageToken=page_token,
                pageSize=200,
            )
            .execute()
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


def download_file(service, file_id: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with io.FileIO(tmp, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    tmp.rename(dest)


DRIVE_IDS_FILENAME = ".drive_ids.json"


def _drive_ids_path(dest_dir: Path) -> Path:
    return dest_dir / DRIVE_IDS_FILENAME


def load_drive_ids(dest_dir: Optional[Path] = None) -> dict:
    """filename -> Drive file_id, for whatever's currently in dest_dir.

    articles.drive_file_id needs the real Drive ID (so citations can always
    trace back to the source PDF), but sync_all() downloads files by name
    only -- this sidecar is what lets process_pdf() recover the ID for a
    given local file without extra Drive API calls.
    """
    path = _drive_ids_path(dest_dir or local_staging_dir())
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_drive_ids(dest_dir: Path, ids: dict) -> None:
    _drive_ids_path(dest_dir).write_text(json.dumps(ids, indent=2, sort_keys=True))


def sync_all(dest_dir: Optional[Path] = None, service=None) -> list:
    """Downloads every PDF under the configured Drive folder that isn't
    already present locally at the same size. Returns the list of local
    paths for files it downloaded (skips already-present files).
    """
    dest_dir = dest_dir or local_staging_dir()
    service = service or build_drive_service()
    downloaded = []
    drive_ids = load_drive_ids(dest_dir)
    for f in walk_pdfs(service, google_drive_folder_id()):
        drive_ids[f.name] = f.file_id
        dest = dest_dir / f.name
        if dest.exists() and dest.stat().st_size == f.size:
            continue
        download_file(service, f.file_id, dest)
        downloaded.append(dest)
    _save_drive_ids(dest_dir, drive_ids)
    return downloaded


if __name__ == "__main__":
    paths = sync_all()
    print(f"Downloaded {len(paths)} new/updated PDFs to {local_staging_dir()}")
