import json

import pymupdf
import pytest

from ingest.extract_text import (
    OcrError,
    _parse_batch,
    extract_pages,
    full_text,
    iter_page_image_batches,
    render_page_images,
)


def _make_pdf(path, num_pages):
    doc = pymupdf.open()
    for _ in range(num_pages):
        doc.new_page()
    doc.save(path)
    doc.close()


class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, outer, pages_by_call):
        self._outer = outer
        self._pages_by_call = pages_by_call

    def generate_content(self, *, model, contents, config):
        self._outer.calls.append({"model": model, "contents": contents, "config": config})
        payload = self._pages_by_call[len(self._outer.calls) - 1]
        if payload is None:
            raw_text = None
        elif isinstance(payload, str):
            raw_text = payload
        else:
            raw_text = json.dumps({"pages": payload})
        return _FakeResponse(raw_text)


class _FakeGemini:
    def __init__(self, pages_by_call):
        self.calls = []
        self._pages_by_call = pages_by_call

    @property
    def models(self):
        return _FakeModels(self, self._pages_by_call)


def test_render_page_images_returns_one_png_per_page(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=3)

    images = render_page_images(pdf_path)

    assert len(images) == 3
    for image_bytes in images:
        assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_iter_page_image_batches_limits_each_rendered_batch(tmp_path):
    pdf_path = tmp_path / "bound-volume.pdf"
    _make_pdf(pdf_path, num_pages=8)

    batches = iter_page_image_batches(pdf_path, batch_size=3)

    first = next(batches)
    assert len(first) == 3
    assert all(image[:8] == b"\x89PNG\r\n\x1a\n" for image in first)
    assert [len(batch) for batch in batches] == [3, 2]


def test_parse_batch_returns_texts_in_page_number_order():
    raw = json.dumps(
        {"pages": [{"page_number": 2, "text": "second"}, {"page_number": 1, "text": "first"}]}
    )
    assert _parse_batch(raw, expected_count=2) == ["first", "second"]


def test_parse_batch_raises_on_malformed_json():
    with pytest.raises(OcrError):
        _parse_batch("not json", expected_count=1)


def test_parse_batch_raises_when_page_numbers_dont_match_expected_count():
    raw = json.dumps({"pages": [{"page_number": 1, "text": "only one"}]})
    with pytest.raises(OcrError):
        _parse_batch(raw, expected_count=2)


def test_extract_pages_ocrs_each_page_via_gemini(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=2)
    client = _FakeGemini(
        pages_by_call=[
            [{"page_number": 1, "text": "SAMPADA June 2021"}, {"page_number": 2, "text": "Editorial"}]
        ]
    )

    pages = extract_pages(pdf_path, client=client)

    assert pages == ["SAMPADA June 2021", "Editorial"]
    assert len(client.calls) == 1


def test_extract_pages_batches_across_multiple_calls(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=8)  # > OCR_PAGE_BATCH_SIZE (6)
    client = _FakeGemini(
        pages_by_call=[
            [{"page_number": i, "text": f"page {i}"} for i in range(1, 7)],
            [{"page_number": i, "text": f"page {i + 6}"} for i in range(1, 3)],
        ]
    )

    pages = extract_pages(pdf_path, client=client)

    assert pages == [f"page {i}" for i in range(1, 9)]
    assert len(client.calls) == 2


def test_extract_pages_retries_once_on_malformed_batch(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=1)
    client = _FakeGemini(
        pages_by_call=[
            "not valid json for the first attempt",
            [{"page_number": 1, "text": "recovered on retry"}],
        ]
    )

    pages = extract_pages(pdf_path, client=client)

    assert pages == ["recovered on retry"]
    assert len(client.calls) == 2


def test_extract_pages_falls_back_to_empty_text_for_an_unrecoverable_page(tmp_path, capsys):
    # A single page that still won't transcribe after a retry (e.g. Gemini's
    # RECITATION block on dense verbatim-looking text) shouldn't take down
    # the whole issue -- it degrades to an empty string with a warning.
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=1)
    client = _FakeGemini(pages_by_call=["still not json", "still not json"])

    pages = extract_pages(pdf_path, client=client)

    assert pages == [""]
    assert "could not be transcribed" in capsys.readouterr().out


def test_extract_pages_splits_a_failing_multi_page_batch_and_recovers(tmp_path):
    # A batch of 2 that fails outright (e.g. RECITATION on the combined
    # response) should retry as two separate 1-page batches rather than
    # losing both pages' text.
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=2)
    client = _FakeGemini(
        pages_by_call=[
            None,  # first attempt at the 2-page batch: blocked
            None,  # retry at the 2-page batch: blocked again
            [{"page_number": 1, "text": "page one recovered"}],  # split: page 1 alone
            [{"page_number": 1, "text": "page two recovered"}],  # split: page 2 alone
        ]
    )

    pages = extract_pages(pdf_path, client=client)

    assert pages == ["page one recovered", "page two recovered"]
    assert len(client.calls) == 4


def test_full_text_joins_all_pages():
    text = full_text(["page one", "page two"])

    assert "page one" in text
    assert "page two" in text
