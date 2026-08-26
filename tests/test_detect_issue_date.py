from ingest.detect_issue_date import detect_issue_date


def test_filename_iso_format():
    assert detect_issue_date("2021-06.pdf", "") == (2021, 6)


def test_filename_month_name():
    assert detect_issue_date("Sampada_June_2021.pdf", "") == (2021, 6)


def test_filename_day_month_reversed():
    assert detect_issue_date("06-2021.pdf", "") == (2021, 6)


def test_falls_back_to_cover_text():
    assert detect_issue_date("issue-42.pdf", "SAMPADA\nVol. XI No. 6, June 2021\n") == (2021, 6)


def test_prefers_filename_over_cover_text():
    # if the filename is conclusive, don't let a stray date on the cover win
    assert detect_issue_date("2019-03.pdf", "Celebrating 70 years since 1953") == (2019, 3)


def test_unparseable_returns_none():
    assert detect_issue_date("scan_final_v2.pdf", "no date printed anywhere on this page") == (None, None)


def test_rejects_out_of_range_year():
    assert detect_issue_date("photo_2150_vacation.pdf", "") == (None, None)


def test_accepts_years_from_the_archives_actual_start():
    # The real Sampada archive starts in 1945 -- these must not be rejected
    # as "too old" the way a stray unrelated year might be.
    assert detect_issue_date("1945 July.pdf", "") == (1945, 7)
    assert detect_issue_date("1949 April.pdf", "") == (1949, 4)
