"""Direct text extraction from Sampada PDFs. No OCR -- every issue already has
a real text layer, so this is a thin wrapper around PyMuPDF.
"""
from pathlib import Path
from typing import List

import pymupdf


def extract_pages(pdf_path: Path) -> List[str]:
    """Returns extracted text for each page, in order."""
    with pymupdf.open(pdf_path) as doc:
        return [page.get_text("text") for page in doc]


def cover_text(pages: List[str], num_pages: int = 2) -> str:
    return "\n".join(pages[:num_pages])


def full_text(pages: List[str]) -> str:
    return "\n\n".join(pages)
