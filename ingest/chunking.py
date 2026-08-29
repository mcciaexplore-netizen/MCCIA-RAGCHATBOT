"""Split an article body into overlapping chunks for embedding.

Token counts are approximated from word counts (~0.75 words per token for
English is the standard rule of thumb) rather than pulling in a tokenizer --
chunk boundaries don't need to be exact, just roughly consistent, and this
keeps the ingestion pipeline dependency-light. This only affects
chunks.content; articles.body (used for citations) is untouched.
"""

from typing import List, Tuple

from ingest.config import CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS

_WORDS_PER_TOKEN = 0.75


def _chunk_sizing(target_tokens: int, overlap_tokens: int) -> Tuple[int, int]:
    chunk_size = max(1, round(target_tokens * _WORDS_PER_TOKEN))
    overlap = max(0, round(overlap_tokens * _WORDS_PER_TOKEN))
    if overlap >= chunk_size:
        overlap = chunk_size - 1
    return chunk_size, overlap


def _chunk_word_ranges(word_count: int, chunk_size: int, overlap: int) -> List[Tuple[int, int]]:
    """The sliding-window word ranges chunk_text()/chunk_text_with_pages()
    both slice from -- factored out so the two stay in exact lockstep
    instead of maintaining the same windowing math twice."""
    if word_count <= chunk_size:
        return [(0, word_count)]

    stride = chunk_size - overlap
    ranges = []
    start = 0
    while start < word_count:
        end = min(start + chunk_size, word_count)
        ranges.append((start, end))
        if start + chunk_size >= word_count:
            break
        start += stride
    return ranges


def chunk_text(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> List[str]:
    words = text.split()
    if not words:
        return []

    chunk_size, overlap = _chunk_sizing(target_tokens, overlap_tokens)
    ranges = _chunk_word_ranges(len(words), chunk_size, overlap)
    return [" ".join(words[start:end]) for start, end in ranges]


def chunk_text_with_pages(
    text: str,
    word_pages: List[int],
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> List[Tuple[str, int]]:
    """Like chunk_text(), but also returns each chunk's issue-relative page
    number -- the page of the chunk's FIRST word (word_pages[i] is the page
    of the i-th word of `text`, see ingest/page_mapping.py).

    A chunk that spans a page boundary is attributed to the page it starts
    on, not a range: smaller_chunks.issue_page_number is a single column,
    and "the page this passage begins on" is the same convention any printed
    citation already uses for content that continues onto the next page.
    """
    words = text.split()
    if not words:
        return []
    assert len(words) == len(word_pages), (
        "word_pages must have exactly one entry per word of `text` -- "
        "build it with ingest.page_mapping.word_pages_for_line_range()"
    )

    chunk_size, overlap = _chunk_sizing(target_tokens, overlap_tokens)
    ranges = _chunk_word_ranges(len(words), chunk_size, overlap)
    return [(" ".join(words[start:end]), word_pages[start]) for start, end in ranges]
