"""Preserves page identity through the one join that erases it.

extract_text.extract_pages() returns one string per physical PDF page, and
detect_issue_boundaries.split_into_issues() already knows exactly which
physical pages belong to each issue -- but run_pipeline used to join those
pages into one flat string (full_text()) before article splitting, and that
join is where page numbers were lost. No extra Gemini call is needed to get
them back: split_articles already returns line-based boundaries (start_line/
end_line) against that same joined text, so a line-to-page lookup array,
built once at the join step, gives exact page attribution for free.
"""

from typing import List, Tuple


def build_page_line_map(issue_pages: List[str]) -> Tuple[str, List[int]]:
    """Joins issue_pages exactly like extract_text.full_text() does
    ("\\n\\n".join(pages)), and returns that joined text alongside a
    line_to_page array: line_to_page[i] is the 1-based issue-relative page
    number (page 1 = this issue's own first page) that line i came from.

    The blank line "\\n\\n".join() inserts between pages is attributed to
    the page it follows, so every line of the joined text -- including that
    separator -- has an entry, keeping the two arrays in exact lockstep.
    """
    line_to_page: List[int] = []
    for i, page_text in enumerate(issue_pages):
        page_number = i + 1
        line_to_page.extend([page_number] * len(page_text.split("\n")))
        if i < len(issue_pages) - 1:
            line_to_page.append(page_number)  # the "\n\n" join's blank line

    joined_text = "\n\n".join(issue_pages)
    assert len(joined_text.split("\n")) == len(line_to_page), (
        "line_to_page must have exactly one entry per line of the joined text -- "
        "a mismatch here means a citation's page number would silently be wrong"
    )
    return joined_text, line_to_page


def _clamp_line_range(line_to_page: List[int], start_line: int, end_line: int) -> Tuple[int, int]:
    """Mirrors split_articles.slice_articles()'s own clamping exactly, so a
    page lookup never reads out of bounds for the same out-of-range
    start_line/end_line Gemini can return."""
    n = len(line_to_page)
    start = max(0, min(start_line, n - 1))
    end = max(0, min(end_line, n - 1))
    return start, end


def article_page_range(line_to_page: List[int], start_line: int, end_line: int) -> Tuple[int, int]:
    """Issue-relative (page_start, page_end) for an article's line range."""
    start, end = _clamp_line_range(line_to_page, start_line, end_line)
    pages_in_range = line_to_page[start : end + 1]
    return min(pages_in_range), max(pages_in_range)


def word_pages_for_line_range(
    lines: List[str], line_to_page: List[int], start_line: int, end_line: int
) -> List[int]:
    """One page number per word of the article body that
    "\\n".join(lines[start_line:end_line+1]) would produce, in the same
    order text.split() would yield them -- lets chunking.chunk_text_with_pages
    attribute each chunk to a page without re-deriving anything from Gemini.

    Blank lines (e.g. the "\\n\\n" join's separator) contribute zero words,
    consistent with how .split() treats them -- so this array's length
    always matches len(body.split()) for the corresponding article body.
    """
    start, end = _clamp_line_range(line_to_page, start_line, end_line)
    word_pages: List[int] = []
    for i in range(start, end + 1):
        page = line_to_page[i]
        word_pages.extend([page] * len(lines[i].split()))
    return word_pages
