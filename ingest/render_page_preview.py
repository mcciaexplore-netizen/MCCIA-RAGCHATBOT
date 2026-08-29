"""Renders exactly one physical PDF page to a small JPEG, for the web app's
source viewer. No OCR, no Gemini call, no DB write -- pure local rasterization
via the same pymupdf machinery extract_text.py uses for OCR, just at a lower
preview-quality DPI and a compressed format instead of lossless PNG.

Invoked as a subprocess from the Next.js API route (web/src/lib/source-preview.ts)
so the Node process never needs its own PDF-rendering library, and every
citation-click stays consistent with how the Python side already reads these
same PDFs. This script does not touch Postgres or the DB at all -- every
security check (does this edition exist, is this filename real, is this page
in range) happens in the Node route before it's ever invoked; this script
trusts its arguments completely, matching a subprocess boundary rather than a
network-exposed one.

Usage:
    python -m ingest.render_page_preview --pdf <path> --page <0-indexed> --out <path>

Exit codes: 0 success. 1 the PDF couldn't be opened. 2 the page index is out
of range for that PDF (the caller already knows the page count in that case
and shouldn't retry).
"""

import argparse
import sys
from pathlib import Path

import pymupdf

PREVIEW_DPI = 150
JPEG_QUALITY = 85


def render_page(pdf_path: Path, page_index: int, out_path: Path) -> None:
    """page_index is 0-based, straight into the physical PDF (already
    resolved from pdf_page_offset + issue-relative page by the caller).
    Writes atomically (temp file + rename) so a reader never sees a
    partially-written preview."""
    doc = pymupdf.open(pdf_path)
    try:
        if not (0 <= page_index < len(doc)):
            raise IndexError(f"page {page_index} out of range for a {len(doc)}-page PDF")
        pixmap = doc[page_index].get_pixmap(dpi=PREVIEW_DPI)
        data = pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)
    finally:
        doc.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.rename(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, help="Path to the source PDF")
    parser.add_argument("--page", required=True, type=int, help="0-indexed physical page number")
    parser.add_argument("--out", required=True, help="Path to write the rendered JPEG")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"[FAIL] source PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    try:
        render_page(pdf_path, args.page, Path(args.out))
    except IndexError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[FAIL] could not render page: {exc!r}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
