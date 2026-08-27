"""Retry transient API failures without hiding permanent errors."""

import time
from typing import Callable, Optional, TypeVar

from google.genai.errors import APIError

T = TypeVar("T")

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_transient_gemini_error(exc: Exception) -> bool:
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
