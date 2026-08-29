"""Local, confidential cache of successfully-OCR'd page text, keyed by Drive
file ID.

OCR (ingest/extract_text.py) is the single most expensive pipeline stage --
if a later stage (issue detection, article splitting, chunking, embedding)
fails, resuming must not re-OCR hundreds of pages. This cache makes OCR
happen at most once per (file, content) pair.

Local-only by design: staging/ is gitignored (never committed), never read
by the web app (web/ has no code path into this directory -- see the web
app's own filesystem access, which never leaves web/), and contains no
credentials. Uses only gzip + json from the standard library -- no new
dependency.

Invalidation rule: a cache is valid only if its recorded source file size
AND mtime both match the current local PDF's. This mirrors the same "is
this file still the same one" signal ingest/drive_sync.py's sync_all()
already uses to decide whether a re-download is needed (dest.stat().st_size
== f.size) -- reusing an established, already-trusted signal rather than
hashing a 500MB+ file on every resume check.
"""

import gzip
import json
from pathlib import Path
from typing import Callable, List, Optional

from ingest.config import GEMINI_OCR_MODEL, processed_cache_dir
from ingest.extract_text import extract_pages

_REQUIRED_CACHE_KEYS = {"drive_file_id", "source_file_size", "source_mtime", "pages"}


def cache_path(drive_file_id: str) -> Path:
    return processed_cache_dir() / drive_file_id / "pages.json.gz"


def _read_meta(path: Path) -> Optional[dict]:
    """Returns the cache's parsed metadata, or None if it's missing,
    corrupt, or incomplete -- a cache that can't be trusted is treated
    exactly like no cache at all, never partially reused."""
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, EOFError, gzip.BadGzipFile, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict) or not _REQUIRED_CACHE_KEYS.issubset(meta):
        return None
    return meta


def is_cache_valid(drive_file_id: str, pdf_path: Path) -> bool:
    meta = _read_meta(cache_path(drive_file_id))
    if meta is None:
        return False
    stat = pdf_path.stat()
    return meta["source_file_size"] == stat.st_size and meta["source_mtime"] == stat.st_mtime


def read_cache(drive_file_id: str, pdf_path: Path) -> Optional[List[str]]:
    """Returns cached OCR'd page text (ordered by physical page, 0-based)
    if a valid cache exists for this exact file, else None -- never
    silently returns stale data for a changed source PDF."""
    if not is_cache_valid(drive_file_id, pdf_path):
        return None
    meta = _read_meta(cache_path(drive_file_id))
    pages_by_index = {p["physical_page"]: p["text"] for p in meta["pages"]}
    return [pages_by_index[i] for i in range(len(pages_by_index))]


def write_cache(drive_file_id: str, pdf_path: Path, pages: List[str]) -> None:
    """Atomic: writes to a temp file in the same directory, then renames --
    a crash mid-write leaves only the .tmp file behind, never a pages.json.gz
    that looks complete but isn't. The temp file is cleaned up on any
    failure so it can't be mistaken for a real (if oddly-named) cache entry.
    """
    final_path = cache_path(drive_file_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")

    stat = pdf_path.stat()
    meta = {
        "drive_file_id": drive_file_id,
        "source_filename": pdf_path.name,
        "source_file_size": stat.st_size,
        "source_mtime": stat.st_mtime,
        "ocr_completed_at": None,  # set as a Unix timestamp by the caller if useful; unused for validation
        "page_count": len(pages),
        "ocr_model": GEMINI_OCR_MODEL,
        "pages": [{"physical_page": i, "text": text} for i, text in enumerate(pages)],
    }
    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as fh:
            json.dump(meta, fh)
        tmp_path.rename(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def get_or_extract_pages(
    pdf_path: Path,
    drive_file_id: str,
    client=None,
    max_workers=None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """OCRs a PDF's pages exactly once per (file, content) pair -- reuses a
    valid local cache when one exists, otherwise OCRs via extract_text and
    saves the result before returning.

    progress_cb is only ever invoked on a cache miss (see extract_pages) --
    optional, so existing callers are unaffected."""
    cached = read_cache(drive_file_id, pdf_path)
    if cached is not None:
        return cached

    pages = extract_pages(pdf_path, client=client, max_workers=max_workers, progress_cb=progress_cb)
    write_cache(drive_file_id, pdf_path, pages)
    return pages
