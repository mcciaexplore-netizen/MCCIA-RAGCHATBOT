from ingest.manual_review import log_manual_review, manual_review_filenames


def test_manual_review_filenames_empty_when_log_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    assert manual_review_filenames() == set()


def test_manual_review_filenames_returns_every_logged_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    log_manual_review("1945 July.PDF", "503 UNAVAILABLE")
    log_manual_review("1947 April.PDF", "503 UNAVAILABLE")

    assert manual_review_filenames() == {"1945 July.PDF", "1947 April.PDF"}


def test_manual_review_filenames_dedupes_repeated_entries_for_the_same_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    log_manual_review("bound.pdf", "first failure")
    log_manual_review("bound.pdf", "second failure")

    assert manual_review_filenames() == {"bound.pdf"}
