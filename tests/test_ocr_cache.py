import gzip
import json

import pytest

from ingest.ocr_cache import (
    cache_path,
    get_or_extract_pages,
    is_cache_valid,
    read_cache,
    write_cache,
)


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    cache_dir = tmp_path / "processed"
    monkeypatch.setenv("PROCESSED_CACHE_DIR", str(cache_dir))
    return cache_dir


def _make_pdf(tmp_path, name="issue.pdf", content=b"%PDF-1.4 fake pdf bytes"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_write_then_read_cache_round_trips_pages(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    pages = ["page one text", "page two text", "page three text"]

    write_cache("drive-abc", pdf_path, pages)
    result = read_cache("drive-abc", pdf_path)

    assert result == pages


def test_read_cache_returns_none_when_nothing_cached(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    assert read_cache("never-cached", pdf_path) is None


def test_cache_is_valid_immediately_after_writing(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    write_cache("drive-abc", pdf_path, ["a page"])
    assert is_cache_valid("drive-abc", pdf_path) is True


def test_stale_cache_invalidated_when_source_file_size_changes(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    write_cache("drive-abc", pdf_path, ["original ocr text"])

    # Source PDF changed (e.g. re-downloaded, different content) -- size differs now.
    pdf_path.write_bytes(b"%PDF-1.4 completely different, longer fake pdf content here")

    assert is_cache_valid("drive-abc", pdf_path) is False
    assert read_cache("drive-abc", pdf_path) is None


def test_stale_cache_invalidated_when_mtime_changes_but_size_matches(tmp_path):
    pdf_path = _make_pdf(tmp_path, content=b"%PDF-1.4 exact same twenty chars!!")
    write_cache("drive-abc", pdf_path, ["original ocr text"])

    # Rewrite with identical size but a different mtime (simulates a
    # same-size re-download of different content).
    import os
    import time

    time.sleep(0.01)
    pdf_path.write_bytes(b"%PDF-1.4 exact same twenty chars!!")
    os.utime(pdf_path, None)  # bump mtime to "now"

    # Force a distinguishable mtime in case the filesystem's resolution
    # collapsed the two writes onto the same timestamp.
    current = pdf_path.stat()
    os.utime(pdf_path, (current.st_atime, current.st_mtime + 5))

    assert is_cache_valid("drive-abc", pdf_path) is False


def test_corrupt_cache_file_is_rejected_not_crashed_on(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    path = cache_path("drive-abc")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not valid gzip data at all")

    assert is_cache_valid("drive-abc", pdf_path) is False
    assert read_cache("drive-abc", pdf_path) is None


def test_incomplete_cache_missing_required_keys_is_rejected(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    path = cache_path("drive-abc")
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump({"drive_file_id": "drive-abc"}, fh)  # missing pages/size/mtime

    assert is_cache_valid("drive-abc", pdf_path) is False
    assert read_cache("drive-abc", pdf_path) is None


def test_write_cache_is_atomic_no_tmp_file_left_behind_on_success(tmp_path):
    pdf_path = _make_pdf(tmp_path)
    write_cache("drive-abc", pdf_path, ["a page"])

    final = cache_path("drive-abc")
    tmp = final.with_suffix(final.suffix + ".tmp")
    assert final.exists()
    assert not tmp.exists()


def test_write_cache_cleans_up_tmp_file_on_failure(tmp_path, monkeypatch):
    pdf_path = _make_pdf(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("json.dump", _boom)

    with pytest.raises(RuntimeError):
        write_cache("drive-abc", pdf_path, ["a page"])

    final = cache_path("drive-abc")
    tmp = final.with_suffix(final.suffix + ".tmp")
    assert not final.exists()
    assert not tmp.exists()


def test_get_or_extract_pages_uses_cache_on_hit_without_calling_extract(tmp_path, monkeypatch):
    pdf_path = _make_pdf(tmp_path)
    write_cache("drive-abc", pdf_path, ["cached page one", "cached page two"])

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("extract_pages should not be called on a cache hit")

    monkeypatch.setattr("ingest.ocr_cache.extract_pages", _fail_if_called)

    pages = get_or_extract_pages(pdf_path, "drive-abc")
    assert pages == ["cached page one", "cached page two"]


def test_get_or_extract_pages_extracts_and_caches_on_miss(tmp_path, monkeypatch):
    pdf_path = _make_pdf(tmp_path)
    calls = []

    def _fake_extract(path, client=None, max_workers=None, progress_cb=None):
        calls.append(path)
        return ["freshly ocrd page"]

    monkeypatch.setattr("ingest.ocr_cache.extract_pages", _fake_extract)

    pages = get_or_extract_pages(pdf_path, "drive-abc")
    assert pages == ["freshly ocrd page"]
    assert calls == [pdf_path]

    # A second call should now hit the cache instead of extracting again.
    pages_again = get_or_extract_pages(pdf_path, "drive-abc")
    assert pages_again == ["freshly ocrd page"]
    assert calls == [pdf_path]  # still just the one extraction
