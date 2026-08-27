"""Central configuration for the Gemini + Neon Postgres pipeline.

All values come from environment variables (loaded from .env via
python-dotenv) so the same code runs locally and in a scheduled job.
"""

import os
from urllib.parse import urlsplit, urlunsplit


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


def migration_database_url() -> str:
    """Return a direct Neon connection for schema migrations.

    DATABASE_URL stays pooled for application traffic. Neon direct URLs are
    the same endpoint without the ``-pooler`` hostname suffix, so derive that
    form when DATABASE_URL_UNPOOLED has not been supplied explicitly.
    """
    explicit = _env("DATABASE_URL_UNPOOLED")
    if explicit:
        return explicit

    pooled = database_url()
    parts = urlsplit(pooled)
    hostname = parts.hostname
    if not hostname or "-pooler" not in hostname:
        return pooled

    direct_hostname = hostname.replace("-pooler", "", 1)
    userinfo, separator, host_and_port = parts.netloc.rpartition("@")
    direct_host_and_port = host_and_port.replace(hostname, direct_hostname, 1)
    direct_netloc = (
        f"{userinfo}{separator}{direct_host_and_port}"
        if separator
        else direct_host_and_port
    )
    return urlunsplit(parts._replace(netloc=direct_netloc))


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
