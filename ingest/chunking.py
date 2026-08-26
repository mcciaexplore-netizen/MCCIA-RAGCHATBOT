"""Split an article body into overlapping chunks for embedding.

Token counts are approximated from word counts (~0.75 words per token for
English is the standard rule of thumb) rather than pulling in a tokenizer --
chunk boundaries don't need to be exact, just roughly consistent, and this
keeps the ingestion pipeline dependency-light. This only affects
chunks.content; articles.body (used for citations) is untouched.
"""

from typing import List

from ingest.config import CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS

_WORDS_PER_TOKEN = 0.75


def chunk_text(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> List[str]:
    words = text.split()
    if not words:
        return []

    chunk_size = max(1, round(target_tokens * _WORDS_PER_TOKEN))
    overlap = max(0, round(overlap_tokens * _WORDS_PER_TOKEN))
    if overlap >= chunk_size:
        overlap = chunk_size - 1
    stride = chunk_size - overlap

    if len(words) <= chunk_size:
        return [" ".join(words)]

    chunks = []
    start = 0
    while start < len(words):
        chunk_words = words[start : start + chunk_size]
        chunks.append(" ".join(chunk_words))
        if start + chunk_size >= len(words):
            break
        start += stride
    return chunks
