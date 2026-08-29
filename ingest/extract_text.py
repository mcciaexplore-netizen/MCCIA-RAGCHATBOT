"""Extracts text from Sampada PDFs via Gemini vision OCR.

The original design assumed every issue already has a real text layer, so
this was a thin PyMuPDF wrapper. That held for the synthetic test PDFs used
through Phase 5, but real Sampada scans (checked across issues from 1945 to
2011) don't have one: most have no embedded text at all, and the rest carry
a garbage legacy-OCR layer that mangles Devanagari script into Latin noise.
Gemini's vision reads the actual scanned page directly and handles the
mixed English/Marathi content and old print quality well, so each page is
rasterized and transcribed instead of reading a text layer.
"""

import itertools
import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterator, List, Optional

import pymupdf
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from ingest.config import GEMINI_OCR_MODEL, OCR_CONCURRENCY, OCR_PAGE_BATCH_SIZE, OCR_PAGE_DPI
from ingest.gemini_retry import call_with_retry, gemini_client
from ingest.usage_tracker import log_usage

SYSTEM_PROMPT = """You transcribe scanned pages from Sampada, an Indian \
industrial trade magazine. This is authorized digitization of MCCIA's own \
historical archive, done by MCCIA -- verbatim transcription is the intended \
task, not an unauthorized reproduction of someone else's copyrighted work. \
Each input image is one page, labeled with its page_number immediately \
after it.

Rules:
- Transcribe exactly as printed, preserving the original script and language
(Marathi, Hindi, English, or a mix -- Marathi and Hindi both print in
Devanagari, so transcribe the Devanagari text exactly as shown rather than
guessing which of the two it is) -- never translate or summarize.
- Preserve headlines, paragraph breaks, and reading order as they appear on
the page.
- A page that's blank, or contains only an image/ad with no real text, gets
an empty string.
- Return exactly one entry per input image, using the page_number given."""


class _PageOut(BaseModel):
    page_number: int
    text: str = ""


class _PagesOut(BaseModel):
    pages: List[_PageOut]


class OcrError(Exception):
    """Gemini didn't return valid, schema-matching JSON after one retry."""


def render_page_images(pdf_path: Path, dpi: int = OCR_PAGE_DPI) -> List[bytes]:
    """Rasterizes every page of a PDF to PNG bytes, in order. Pure/local --
    no network -- so it's unit-testable without a Gemini client."""
    with pymupdf.open(pdf_path) as doc:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def iter_page_image_batches(
    pdf_path: Path,
    *,
    dpi: int = OCR_PAGE_DPI,
    batch_size: int = OCR_PAGE_BATCH_SIZE,
) -> Iterator[List[bytes]]:
    """Rasterize one OCR batch at a time instead of holding a bound
    volume's rendered pages in memory all at once."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    with pymupdf.open(pdf_path) as doc:
        for start in range(0, len(doc), batch_size):
            end = min(start + batch_size, len(doc))
            yield [
                doc[page_number].get_pixmap(dpi=dpi).tobytes("png")
                for page_number in range(start, end)
            ]


def _call_gemini(batch_images: List[bytes], client: genai.Client) -> Optional[str]:
    contents: List[object] = []
    for i, image_bytes in enumerate(batch_images, start=1):
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
        contents.append(f"^ that image is page_number {i}")

    response = call_with_retry(
        "OCR",
        lambda: client.models.generate_content(
            model=GEMINI_OCR_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_PagesOut,
            ),
        ),
    )
    usage = getattr(response, "usage_metadata", None)
    if usage is not None:
        log_usage(
            GEMINI_OCR_MODEL,
            "ocr",
            usage.prompt_token_count or 0,
            usage.candidates_token_count or 0,
        )
    # None when Gemini stops generating without full text -- most commonly
    # finish_reason RECITATION, which can trip on dense, verbatim-looking
    # transcription of old print text even when it's legitimate. Bubbling
    # this up as "no text" (rather than raising) lets the caller retry with
    # a smaller batch instead of failing the whole issue.
    return response.text


def _parse_batch(raw_json: str, expected_count: int) -> List[str]:
    """Pure parsing/validation, no network -- unit-testable directly.

    Raises OcrError if `raw_json` isn't valid JSON matching the expected
    shape, or doesn't cover exactly page_number 1..expected_count.
    """
    try:
        parsed = _PagesOut.model_validate_json(raw_json)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise OcrError(f"malformed response: {exc}") from exc

    by_number = {p.page_number: p.text for p in parsed.pages}
    expected = set(range(1, expected_count + 1))
    if set(by_number) != expected:
        raise OcrError(f"expected page_number 1..{expected_count}, got {sorted(by_number)}")

    return [by_number[i] for i in range(1, expected_count + 1)]


def _ocr_batch(batch_images: List[bytes], client: genai.Client) -> List[str]:
    """OCRs a batch of pages, in order. Retries once on a malformed or empty
    (e.g. RECITATION-blocked) response; if that also fails and the batch has
    more than one page, splits it in half and recurses -- a smaller batch is
    less likely to trip the same block. A single page that still won't
    transcribe after a retry falls back to an empty string with a warning,
    rather than failing the whole issue over one page."""
    last_error: Optional[OcrError] = None
    for _attempt in range(2):
        raw_json = _call_gemini(batch_images, client)
        if raw_json is None:
            last_error = OcrError("Gemini returned no text (blocked or recitation-flagged response)")
            continue
        try:
            return _parse_batch(raw_json, len(batch_images))
        except OcrError as exc:
            last_error = exc

    if len(batch_images) == 1:
        print(f"[WARN] page could not be transcribed after retries ({last_error}), using empty text")
        return [""]

    mid = len(batch_images) // 2
    return _ocr_batch(batch_images[:mid], client) + _ocr_batch(batch_images[mid:], client)


def extract_pages(
    pdf_path: Path,
    client: Optional[genai.Client] = None,
    max_workers: Optional[int] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Returns OCR'd text for each page, in order.

    Batches are independent Gemini calls, so with max_workers > 1 they run
    concurrently through a sliding window (submit up to max_workers ahead,
    consume the oldest, submit the next) -- this bounds how many batches'
    rendered images sit in memory at once to roughly max_workers, rather
    than materializing a whole 900-page bound volume up front. Results are
    reassembled in submission order regardless of which batch's call
    actually completes first.

    progress_cb, if given, is called as (pages_done, total_pages) after each
    batch completes -- optional so existing callers are unaffected; see
    archive_processor.py for a consumer.
    """
    client = client or gemini_client()
    workers = OCR_CONCURRENCY if max_workers is None else max_workers
    total_pages = pymupdf.open(pdf_path).page_count if progress_cb is not None else 0

    batch_iter = iter_page_image_batches(pdf_path)
    if workers <= 1:
        pages: List[str] = []
        for batch in batch_iter:
            pages.extend(_ocr_batch(batch, client))
            if progress_cb is not None:
                progress_cb(len(pages), total_pages)
        return pages

    pages = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        window: deque = deque()
        for batch in itertools.islice(batch_iter, workers):
            window.append(pool.submit(_ocr_batch, batch, client))
        for next_batch in batch_iter:
            pages.extend(window.popleft().result())
            if progress_cb is not None:
                progress_cb(len(pages), total_pages)
            window.append(pool.submit(_ocr_batch, next_batch, client))
        while window:
            pages.extend(window.popleft().result())
            if progress_cb is not None:
                progress_cb(len(pages), total_pages)
    return pages


def full_text(pages: List[str]) -> str:
    return "\n\n".join(pages)
