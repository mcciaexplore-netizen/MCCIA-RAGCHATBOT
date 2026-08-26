from ingest.chunking import chunk_text


def test_short_text_returns_a_single_chunk():
    text = "one two three four five"
    assert chunk_text(text, target_tokens=300, overlap_tokens=50) == [text]


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_long_text_splits_into_multiple_overlapping_chunks():
    words = [f"word{i}" for i in range(1000)]
    text = " ".join(words)

    chunks = chunk_text(text, target_tokens=300, overlap_tokens=50)

    assert len(chunks) > 1
    # Every chunk should be non-empty and (except possibly the last) roughly
    # target-sized -- not exact since we approximate tokens from words.
    for chunk in chunks[:-1]:
        assert len(chunk.split()) > 0

    # Consecutive chunks should share some words at the boundary (overlap).
    # overlap_tokens=50 -> ~38 words at the 0.75 words/token approximation;
    # sample a window wide enough to catch it regardless of rounding.
    first_words = chunks[0].split()
    second_words = chunks[1].split()
    assert set(first_words[-40:]) & set(second_words[:40])


def test_all_words_are_covered_at_least_once():
    words = [f"word{i}" for i in range(500)]
    text = " ".join(words)

    chunks = chunk_text(text, target_tokens=300, overlap_tokens=50)
    seen = set()
    for chunk in chunks:
        seen.update(chunk.split())

    assert seen == set(words)


def test_last_chunk_is_not_dropped_when_shorter_than_target():
    # 250 words at ~225 words/chunk (300 tokens * 0.75) should produce a
    # short tail chunk, not silently drop the remainder.
    words = [f"word{i}" for i in range(250)]
    text = " ".join(words)

    chunks = chunk_text(text, target_tokens=300, overlap_tokens=50)
    assert "word249" in chunks[-1]
