"""Splits a bound-volume PDF into its individual issues using Gemini.

Checked live against real Drive scans: every PDF in the archive bundles
multiple issues, not just the ones with an obvious "1996-Jan To 1996-Dec"
style filename. A 1945-labeled file can bundle two or three issues; a
"...Jan To ...Dec" file bundles a whole year. Each issue starts with its own
masthead/cover page stating its own month and year, but that cover's exact
layout has changed across 70+ years of the magazine's history -- rather than
hand-coding regexes per era, this asks Gemini to read each page's opening
text and identify where a new issue starts.

Design mirrors split_articles.py: only ask Gemini for (start_page, year,
month) per issue -- tiny output -- and only feed it a short preview of each
page (covers are short and top-loaded with the identifying info) rather than
full page bodies, so this stays cheap even for a 900-page bound volume.
"""

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from db.config import gemini_api_key
from ingest.config import GEMINI_SPLIT_MODEL
from ingest.gemini_retry import call_with_retry
from ingest.usage_tracker import log_usage

SYSTEM_PROMPT = """You split one scanned, bound PDF of Sampada (an Indian \
industrial trade magazine) into its individual monthly/bi-monthly issues. \
You are given a preview of the opening text of every page, each prefixed \
with a marker like PAGE0001, PAGE0002, etc.

Rules:
- Every issue bound in this PDF starts with its own cover/masthead page: it \
names the magazine, and states that issue's own volume/year number and \
month(s), often alongside an issue number (e.g. "Year 1] July 1945 [Issue \
1", or "SAMPADA, Vol. XI No. 6, June 2021"). That page is the issue's \
start_page.
- A date mentioned inside a regular article's body text (a deadline, an \
anniversary, a historical reference) is NOT a new issue -- only count a \
page as a start_page when it reads as that issue's own cover/masthead.
- A combined issue (e.g. "December-January 1946") is one issue; use its \
first stated month.
- List every issue you find, in page order. Most PDFs bundle more than one.
- year is a 4-digit year; month is 1-12."""


class _IssueBoundaryOut(BaseModel):
    start_page: int
    year: int
    month: int


class _IssueBoundaries(BaseModel):
    issues: List[_IssueBoundaryOut]


@dataclass
class IssueBoundary:
    start_page: int  # index into `pages`, 0-based
    year: int
    month: int


class IssueBoundaryError(Exception):
    """Gemini didn't return valid, schema-matching JSON after one retry."""


def number_page_previews(pages: List[str], preview_chars: int = 400) -> str:
    width = len(str(len(pages)))
    return "\n\n".join(
        f"PAGE{str(i).zfill(width)}:\n{text[:preview_chars]}" for i, text in enumerate(pages)
    )


def _client() -> genai.Client:
    return genai.Client(api_key=gemini_api_key())


def _call_gemini(numbered_previews: str, client: genai.Client) -> str:
    interaction = call_with_retry(
        "issue-boundary detection",
        lambda: client.interactions.create(
            model=GEMINI_SPLIT_MODEL,
            system_instruction=SYSTEM_PROMPT,
            input=numbered_previews,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _IssueBoundaries.model_json_schema(),
            },
        ),
    )
    usage = getattr(interaction, "usage", None)
    if usage is not None:
        log_usage(
            GEMINI_SPLIT_MODEL,
            "boundary",
            usage.total_input_tokens or 0,
            usage.total_output_tokens or 0,
        )
    return interaction.output_text


def parse_boundaries_json(raw_json: str, page_count: int) -> List[IssueBoundary]:
    """Pure parsing/validation, no network -- unit-testable directly.

    Raises IssueBoundaryError if `raw_json` isn't valid JSON matching the
    expected shape, or if it lists no issues, or an out-of-range page.
    """
    try:
        parsed = _IssueBoundaries.model_validate_json(raw_json)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise IssueBoundaryError(f"malformed response: {exc}") from exc

    if not parsed.issues:
        raise IssueBoundaryError("no issues found in this PDF")

    boundaries = []
    for issue in parsed.issues:
        if not (0 <= issue.start_page < page_count):
            raise IssueBoundaryError(f"start_page {issue.start_page} out of range for {page_count} pages")
        boundaries.append(IssueBoundary(start_page=issue.start_page, year=issue.year, month=issue.month))

    return sorted(boundaries, key=lambda b: b.start_page)


def request_boundaries(
    numbered_previews: str, page_count: int, client: Optional[genai.Client] = None
) -> List[IssueBoundary]:
    """Calls Gemini for strict JSON boundaries. Retries once on a malformed
    response; raises IssueBoundaryError if the retry also fails, so the
    caller can log and skip this PDF rather than write bad data."""
    client = client or _client()

    last_error: Optional[IssueBoundaryError] = None
    for _attempt in range(2):
        raw_json = _call_gemini(numbered_previews, client)
        try:
            return parse_boundaries_json(raw_json, page_count)
        except IssueBoundaryError as exc:
            last_error = exc

    raise last_error


def split_into_issues(
    pages: List[str], client: Optional[genai.Client] = None
) -> List[Tuple[IssueBoundary, List[str]]]:
    """Groups a PDF's OCR'd pages into (boundary, page_texts) per issue,
    each spanning from its cover page up to (but not including) the next
    issue's cover page."""
    numbered = number_page_previews(pages)
    boundaries = request_boundaries(numbered, len(pages), client=client)

    result = []
    for i, boundary in enumerate(boundaries):
        end = boundaries[i + 1].start_page if i + 1 < len(boundaries) else len(pages)
        result.append((boundary, pages[boundary.start_page : end]))
    return result
