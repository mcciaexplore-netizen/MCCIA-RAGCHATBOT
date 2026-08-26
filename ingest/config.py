"""Central configuration for the Gemini + Neon ingestion pipeline.

All values come from environment variables (loaded from .env via
python-dotenv). Gemini/database env accessors live in db/config.py; this
module adds the ingestion-specific ones (Drive, local staging paths, model
IDs).
"""

import os
from pathlib import Path

# Confirmed against ai.google.dev/gemini-api/docs/models on 2026-08-26 --
# re-check before bumping, Google deprecates these fast.
GEMINI_SPLIT_MODEL = "gemini-3.7-flash"
GEMINI_CLASSIFY_MODEL = "gemini-3.5-flash-lite"
GEMINI_EMBED_MODEL = "gemini-embedding-001"
GEMINI_OCR_MODEL = "gemini-3.7-flash"

# pgvector's HNSW/IVFFlat indexes cap at 2000 dims -- gemini-embedding-001
# defaults to 3072, so this must be requested explicitly (see db/schema.sql).
EMBEDDING_DIMENSIONS = 1536

CHUNK_TARGET_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 50

# Real Sampada scans have no trustworthy text layer (see extract_text.py), so
# pages are OCR'd via Gemini vision, several pages per call. Small enough
# that a retry after a malformed response doesn't waste too much OCR work.
OCR_PAGE_BATCH_SIZE = 6
OCR_PAGE_DPI = 200


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def google_service_account_file() -> str:
    return _env("GOOGLE_SERVICE_ACCOUNT_FILE", "./secrets/drive-service-account.json")


def require_for_drive() -> None:
    from db.config import google_drive_folder_id

    google_drive_folder_id()  # raises if unset
    if not Path(google_service_account_file()).exists():
        raise RuntimeError(
            f"Google service account file not found at "
            f"{google_service_account_file()}. Create a service account, "
            f"download its JSON key, and share the Drive folder with its "
            f"client_email as a Viewer. Set GOOGLE_SERVICE_ACCOUNT_FILE if "
            f"it lives somewhere other than ./secrets/drive-service-account.json."
        )


def local_staging_dir() -> Path:
    return Path(_env("LOCAL_STAGING_DIR", "./staging/raw"))


def manual_review_log() -> Path:
    return Path(_env("MANUAL_REVIEW_LOG", "./staging/manual_review.csv"))


def web_archive_base_url() -> str:
    return _env("WEB_ARCHIVE_BASE_URL", "https://www.mcciapunesampada.com")
