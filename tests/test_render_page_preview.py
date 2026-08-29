import pymupdf
import pytest

from ingest.render_page_preview import render_page


def _make_pdf(path, num_pages):
    doc = pymupdf.open()
    for _ in range(num_pages):
        doc.new_page()
    doc.save(path)
    doc.close()


def test_render_page_writes_a_real_jpeg(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=3)
    out_path = tmp_path / "previews" / "page-0001.jpg"

    render_page(pdf_path, 1, out_path)

    assert out_path.exists()
    data = out_path.read_bytes()
    assert data[:2] == b"\xff\xd8"  # JPEG magic bytes
    assert not out_path.with_suffix(out_path.suffix + ".part").exists()


def test_render_page_creates_parent_dirs(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=1)
    out_path = tmp_path / "a" / "b" / "c" / "page-0000.jpg"

    render_page(pdf_path, 0, out_path)

    assert out_path.exists()


def test_render_page_rejects_out_of_range_page(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=2)
    out_path = tmp_path / "page-0099.jpg"

    with pytest.raises(IndexError):
        render_page(pdf_path, 99, out_path)
    assert not out_path.exists()


def test_render_page_rejects_negative_page(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, num_pages=2)
    out_path = tmp_path / "page-neg.jpg"

    with pytest.raises(IndexError):
        render_page(pdf_path, -1, out_path)
    assert not out_path.exists()
