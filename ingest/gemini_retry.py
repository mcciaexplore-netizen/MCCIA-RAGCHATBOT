"""Retry transient API failures without hiding permanent errors."""

import time
from typing import Callable, Optional, TypeVar

import httpx
from google import genai
from google.genai import types
from google.genai.errors import APIError

from db.config import gemini_api_key

T = TypeVar("T")

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

# Confirmed live: with no timeout set, a Gemini request can hang indefinitely
# on an established-but-idle connection (observed repeatedly during OCR of a
# real archive PDF -- ps showed 0% CPU, lsof showed an open socket to
# Google, and no progress for minutes at a stretch, across multiple restarts
# of the same file). This bounds any single request; the existing retry loop
# below (plus, for OCR specifically, extract_text.py's batch-splitting
# fallback) turns a bounded timeout into graceful degradation instead of an
# indefinite hang.
GEMINI_REQUEST_TIMEOUT_MS = 120_000


def gemini_client() -> genai.Client:
    return genai.Client(
        api_key=gemini_api_key(), http_options=types.HttpOptions(timeout=GEMINI_REQUEST_TIMEOUT_MS)
    )


def _is_transient_gemini_error(exc: Exception) -> bool:
    # A timed-out or never-established request raises a raw httpx exception,
    # not an APIError -- without this, the timeout above would just make a
    # hang fail fast on the *first* attempt instead of actually retrying.
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if not isinstance(exc, APIError):
        return False
    return int(exc.code or 0) in TRANSIENT_STATUS_CODES


def call_with_retry(
    operation: str,
    call: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    is_transient: Optional[Callable[[Exception], bool]] = None,
) -> T:
    """Call `call` and retry only failures `is_transient` recognizes.

    Defaults to Gemini's rate-limit/temporary-server-error check, so this
    stays a drop-in for existing callers. Pass a different predicate to
    reuse this same backoff loop against another API's error shape (see
    ingest/drive_sync.py for Drive's).
    """
    is_transient = is_transient or _is_transient_gemini_error
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not is_transient(exc) or attempt == max_attempts:
                raise

            delay = base_delay_seconds * (2 ** (attempt - 1))
            print(
                f"[RETRY] {operation}: {exc!r}; "
                f"attempt {attempt}/{max_attempts}, retrying in {delay:g}s"
            )
            sleep(delay)

    raise AssertionError("retry loop exhausted without returning or raising")
