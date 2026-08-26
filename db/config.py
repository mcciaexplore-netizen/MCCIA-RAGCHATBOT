"""Central configuration for the Gemini + Neon Postgres pipeline.

All values come from environment variables (loaded from .env via
python-dotenv) so the same code runs locally and in a scheduled job.
"""

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def database_url() -> str:
    value = _env("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "DATABASE_URL is not set. Create a Neon project at neon.tech, "
            "enable the pgvector extension, and put its connection string "
            "(the pooled one) in .env."
        )
    return value


def gemini_api_key() -> str:
    value = _env("GEMINI_API_KEY")
    if not value:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Create one in Google AI Studio "
            "(ai.google.dev) and put it in .env."
        )
    return value


def google_drive_folder_id() -> str:
    value = _env("GOOGLE_DRIVE_FOLDER_ID")
    if not value:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID is not set.")
    return value
