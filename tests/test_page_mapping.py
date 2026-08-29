from ingest.page_mapping import (
    article_page_range,
    build_page_line_map,
    word_pages_for_line_range,
)


def test_build_page_line_map_matches_full_text_join():
    # Mirrors extract_text.full_text()'s "\n\n".join(pages) exactly -- if
    # this ever drifts from that join, page numbers silently go wrong.
    pages = ["cover\nmasthead", "article one\nmore text", "article two"]
    joined, line_to_page = build_page_line_map(pages)
    assert joined == "\n\n".join(pages)
    assert len(joined.split("\n")) == len(line_to_page)


def test_build_page_line_map_attributes_each_line_to_its_own_page():
    pages = ["line a\nline b", "line c"]
    joined, line_to_page = build_page_line_map(pages)
    lines = joined.split("\n")
    assert lines == ["line a", "line b", "", "line c"]
    # page 1: "line a", "line b"; the "\n\n" blank separator; page 2: "line c"
    assert line_to_page == [1, 1, 1, 2]


def test_build_page_line_map_single_page():
    pages = ["only page here"]
    joined, line_to_page = build_page_line_map(pages)
    assert joined == "only page here"
    assert line_to_page == [1]


def test_article_page_range_entirely_on_one_page():
    pages = ["cover", "L0\nL1\nL2", "next page"]
    _, line_to_page = build_page_line_map(pages)
    # page 2 occupies lines 2,3,4 (after "cover" + its separator at 0,1)
    start, end = article_page_range(line_to_page, 2, 4)
    assert (start, end) == (2, 2)


def test_article_page_range_spans_multiple_pages():
    pages = ["cover", "start of article", "end of article"]
    _, line_to_page = build_page_line_map(pages)
    # line 0 = page1 "cover"; line1 = blank sep; line2 = page2; line3 = blank sep; line4 = page3
    assert line_to_page == [1, 1, 2, 2, 3]
    start, end = article_page_range(line_to_page, 2, 4)
    assert (start, end) == (2, 3)


def test_article_page_range_first_page_of_issue():
    pages = ["masthead line", "body"]
    _, line_to_page = build_page_line_map(pages)
    start, end = article_page_range(line_to_page, 0, 0)
    assert (start, end) == (1, 1)


def test_article_page_range_last_page_of_issue():
    pages = ["page one", "page two", "page three"]
    _, line_to_page = build_page_line_map(pages)
    # page three is the final line (index 4: 0,1,2,3,4 -> p1,sep,p2,sep,p3)
    start, end = article_page_range(line_to_page, 4, 4)
    assert (start, end) == (3, 3)


def test_article_page_range_clamps_out_of_range_end_line():
    pages = ["only page"]
    _, line_to_page = build_page_line_map(pages)
    start, end = article_page_range(line_to_page, 0, 9999)
    assert (start, end) == (1, 1)


def test_word_pages_for_line_range_matches_body_word_count():
    pages = ["cover masthead", "first line words\nsecond line more words"]
    joined, line_to_page = build_page_line_map(pages)
    lines = joined.split("\n")
    # page 2 spans lines 2 and 3 (0="cover masthead", 1=blank sep, 2/3=page2)
    word_pages = word_pages_for_line_range(lines, line_to_page, 2, 3)
    body = "\n".join(lines[2:4])
    assert len(word_pages) == len(body.split())
    assert set(word_pages) == {2}


def test_word_pages_for_line_range_across_a_page_boundary():
    pages = ["a b c", "d e", "f g h"]
    joined, line_to_page = build_page_line_map(pages)
    lines = joined.split("\n")
    # article spans from page 1's line through page 2's line
    word_pages = word_pages_for_line_range(lines, line_to_page, 0, 2)
    body = "\n".join(lines[0:3])
    assert len(word_pages) == len(body.split())
    # "a b c" (page 1, 3 words), blank line (0 words), "d e" (page 2, 2 words)
    assert word_pages == [1, 1, 1, 2, 2]


def test_word_pages_handles_blank_separator_lines_without_shifting():
    # The "\n\n" join inserts a blank line between every pair of pages --
    # blank lines must contribute zero words, or later words would be
    # misattributed to the wrong page.
    pages = ["", "real content here"]
    joined, line_to_page = build_page_line_map(pages)
    lines = joined.split("\n")
    assert lines == ["", "", "real content here"]
    word_pages = word_pages_for_line_range(lines, line_to_page, 0, 2)
    assert word_pages == [2, 2, 2]  # only "real content here"'s 3 words, all page 2
