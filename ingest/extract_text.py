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

import json
from pathlib import Path
from typing import List, Optional

import pymupdf
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from db.config import gemini_api_key
from ingest.config import GEMINI_OCR_MODEL, OCR_PAGE_BATCH_SIZE, OCR_PAGE_DPI

SYSTEM_PROMPT = """You transcribe scanned pages from Sampada, an Indian \
industrial trade magazine. This is authorized digitization of MCCIA's own \
historical archive, done by MCCIA -- verbatim transcription is the intended \
task, not an unauthorized reproduction of someone else's copyrighted work. \
Each input image is one page, labeled with its page_number immediately \
after it.

Rules:
- Transcribe exactly as printed, preserving the original script (Marathi/
Devanagari, English, or a mix) -- never translate or summarize.
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


def _client() -> genai.Client:
    return genai.Client(api_key=gemini_api_key())


def render_page_images(pdf_path: Path, dpi: int = OCR_PAGE_DPI) -> List[bytes]:
    """Rasterizes every page of a PDF to PNG bytes, in order. Pure/local --
    no network -- so it's unit-testable without a Gemini client."""
    with pymupdf.open(pdf_path) as doc:
        return [page.get_pixmap(dpi=dpi).tobytes("png") for page in doc]


def _call_gemini(batch_images: List[bytes], client: genai.Client) -> Optional[str]:
    contents: List[object] = []
    for i, image_bytes in enumerate(batch_images, start=1):
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
        contents.append(f"^ that image is page_number {i}")

    response = client.models.generate_content(
        model=GEMINI_OCR_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=_PagesOut,
        ),
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


def extract_pages(pdf_path: Path, client: Optional[genai.Client] = None) -> List[str]:
    """Returns OCR'd text for each page, in order."""
    client = client or _client()
    images = render_page_images(pdf_path)

    pages: List[str] = []
    for i in range(0, len(images), OCR_PAGE_BATCH_SIZE):
        batch = images[i : i + OCR_PAGE_BATCH_SIZE]
        pages.extend(_ocr_batch(batch, client))
    return pages


def full_text(pages: List[str]) -> str:
    return "\n\n".join(pages)
