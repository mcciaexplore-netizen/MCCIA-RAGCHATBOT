import pymupdf

from ingest.extract_text import cover_text, extract_pages, full_text


def _make_pdf(path, pages_text):
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_extract_pages_reads_real_text_layer(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, ["SAMPADA June 2021", "Editorial\nWelcome to this issue."])

    pages = extract_pages(pdf_path)

    assert len(pages) == 2
    assert "SAMPADA" in pages[0]
    assert "June 2021" in pages[0]
    assert "Editorial" in pages[1]


def test_cover_text_limits_to_first_n_pages(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, ["cover page", "toc page", "article page mentioning May 1999"])

    pages = extract_pages(pdf_path)
    cover = cover_text(pages, num_pages=2)

    assert "cover page" in cover
    assert "toc page" in cover
    assert "May 1999" not in cover


def test_full_text_joins_all_pages(tmp_path):
    pdf_path = tmp_path / "issue.pdf"
    _make_pdf(pdf_path, ["page one", "page two"])

    pages = extract_pages(pdf_path)
    text = full_text(pages)

    assert "page one" in text
    assert "page two" in text
