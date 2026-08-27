"""Retry transient Gemini API failures without hiding permanent errors."""

import time
from typing import Callable, TypeVar

from google.genai.errors import APIError

T = TypeVar("T")

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


def call_with_retry(
    operation: str,
    call: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call Gemini and retry only rate-limit or temporary server failures."""
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except APIError as exc:
            code = int(exc.code or 0)
            if code not in TRANSIENT_STATUS_CODES or attempt == max_attempts:
                raise

            delay = base_delay_seconds * (2 ** (attempt - 1))
            print(
                f"[RETRY] {operation}: Gemini returned {code}; "
                f"attempt {attempt}/{max_attempts}, retrying in {delay:g}s"
            )
            sleep(delay)

    raise AssertionError("retry loop exhausted without returning or raising")
