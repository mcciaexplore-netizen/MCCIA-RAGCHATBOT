"""Split one issue's full text into individual articles using Gemini.

Design note: we do NOT ask Gemini to re-emit article bodies. Two reasons:
  1. Even a large context/output budget can be exceeded by a full magazine
     issue's worth of body text, risking silent truncation.
  2. Citations need to be byte-exact to the source PDF -- having a model
     retype the body risks paraphrasing/typos that would make citations
     untrustworthy.

Instead, we number every line of the extracted text and ask Gemini to return
only (title, author, start_line, end_line) per article -- tiny output -- and
then slice the *original* text ourselves.
"""

import json
from dataclasses import dataclass
from typing import List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from ingest.config import GEMINI_SPLIT_MODEL
from ingest.gemini_retry import call_with_retry, gemini_client
from ingest.usage_tracker import log_usage

SYSTEM_PROMPT = """You split one issue of Sampada, an Indian industrial trade \
magazine, into its individual articles. You are given the issue's text with \
every line prefixed by a marker like L0001, L0002, etc.

Rules:
- Every distinct article (feature, column, interview, editorial) gets its own \
entry. Do not merge separate articles together.
- Skip non-article content: cover pages, table of contents, ads, subscription \
forms, back-cover matter. Don't invent an entry for them.
- title: the article's headline, exactly as printed.
- author: the byline name if one is printed (e.g. "By Jane Doe" -> "Jane \
Doe"), otherwise an empty string. Never guess an author.
- start_line/end_line: the L#### line numbers spanning that article's \
headline through its last line of body text, inclusive. Ranges should not \
overlap between articles.
- Return every article in reading order."""


class _ArticleBoundaryOut(BaseModel):
    title: str
    author: str = ""
    start_line: int
    end_line: int


class _ArticleBoundaries(BaseModel):
    articles: List[_ArticleBoundaryOut]


@dataclass
class ArticleBoundary:
    title: str
    author: str
    start_line: int
    end_line: int


@dataclass
class Article:
    title: str
    author: str
    body: str
    # Clamped line indices (into the issue's joined text) this article's body
    # came from -- defaulted so existing callers that only care about
    # title/author/body (most tests, and any future caller) don't need to
    # supply them. Populated by slice_articles(); used by run_pipeline to
    # look up issue-relative page numbers via ingest/page_mapping.py without
    # an extra Gemini call.
    start_line: int = 0
    end_line: int = 0


class ArticleSplitError(Exception):
    """Gemini didn't return valid, schema-matching JSON after one retry."""


def number_lines(text: str) -> str:
    lines = text.split("\n")
    width = len(str(len(lines)))
    return "\n".join(f"L{str(i).zfill(width)}: {line}" for i, line in enumerate(lines))


def _call_gemini(numbered_text: str, client: genai.Client) -> str:
    interaction = call_with_retry(
        "article splitting",
        lambda: client.interactions.create(
            model=GEMINI_SPLIT_MODEL,
            system_instruction=SYSTEM_PROMPT,
            input=numbered_text,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": _ArticleBoundaries.model_json_schema(),
            },
        ),
    )
    usage = getattr(interaction, "usage", None)
    if usage is not None:
        log_usage(
            GEMINI_SPLIT_MODEL,
            "split",
            usage.total_input_tokens or 0,
            usage.total_output_tokens or 0,
        )
    return interaction.output_text


def parse_boundaries_json(raw_json: str) -> List[ArticleBoundary]:
    """Pure parsing/validation, no network -- unit-testable directly.

    Raises ArticleSplitError if `raw_json` isn't valid JSON matching the
    expected shape.
    """
    try:
        parsed = _ArticleBoundaries.model_validate_json(raw_json)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ArticleSplitError(f"malformed response: {exc}") from exc

    return [
        ArticleBoundary(
            title=a.title.strip(),
            author=a.author.strip(),
            start_line=a.start_line,
            end_line=a.end_line,
        )
        for a in parsed.articles
    ]


def request_boundaries(numbered_text: str, client: Optional[genai.Client] = None) -> List[ArticleBoundary]:
    """Calls Gemini for strict JSON boundaries. Retries once on a malformed
    response; raises ArticleSplitError if the retry also fails, so the
    caller can log and skip this issue rather than write bad data.
    """
    client = client or gemini_client()

    last_error: Optional[ArticleSplitError] = None
    for _attempt in range(2):
        raw_json = _call_gemini(numbered_text, client)
        try:
            return parse_boundaries_json(raw_json)
        except ArticleSplitError as exc:
            last_error = exc

    raise last_error


def slice_articles(text: str, boundaries: List[ArticleBoundary]) -> List[Article]:
    """Pure function: slices the original (unnumbered) text using boundary
    line ranges. Kept separate from the Gemini call so it's unit-testable
    without any network access.
    """
    lines = text.split("\n")
    n = len(lines)
    articles = []
    for b in sorted(boundaries, key=lambda x: x.start_line):
        start = max(0, min(b.start_line, n - 1))
        end = max(0, min(b.end_line, n - 1))
        if end < start:
            continue
        body = "\n".join(lines[start : end + 1]).strip()
        if not body:
            continue
        articles.append(Article(title=b.title, author=b.author, body=body, start_line=start, end_line=end))
    return articles


def split_issue_into_articles(full_text: str, client: Optional[genai.Client] = None) -> List[Article]:
    numbered = number_lines(full_text)
    boundaries = request_boundaries(numbered, client=client)
    return slice_articles(full_text, boundaries)
