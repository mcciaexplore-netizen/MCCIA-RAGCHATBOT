from ingest.web_archive import (
    WebIssue,
    build_issue_month_index,
    check_for_new_issues,
    find_new_web_issues,
    lookup_source_url,
    parse_pages_feed,
)

# Shaped like a real Blogger "Pages" GData JSON feed entry.
SAMPLE_FEED = {
    "feed": {
        "entry": [
            {
                "title": {"$t": "SAMPADA JULY 2026"},
                "link": [
                    {"rel": "self", "href": "https://www.googleapis.com/blogger/v3/.../123"},
                    {"rel": "alternate", "href": "https://www.mcciapunesampada.com/p/sampada-july-2026.html"},
                ],
            },
            {
                # Inconsistent slug, but the title still parses fine.
                "title": {"$t": "Sampada: May 2021 Maharashtra @ 61"},
                "link": [
                    {"rel": "alternate", "href": "https://www.mcciapunesampada.com/p/may-2021-maharashtra-61.html"},
                ],
            },
            {
                # No date anywhere -- should be silently skipped, not crash.
                "title": {"$t": "About Us"},
                "link": [{"rel": "alternate", "href": "https://www.mcciapunesampada.com/p/about.html"}],
            },
        ]
    }
}


def test_parse_pages_feed_extracts_year_month_from_titles():
    issues = parse_pages_feed(SAMPLE_FEED)

    assert issues == [
        WebIssue(
            year=2026,
            month=7,
            issue_month="2026-07",
            title="SAMPADA JULY 2026",
            url="https://www.mcciapunesampada.com/p/sampada-july-2026.html",
        ),
        WebIssue(
            year=2021,
            month=5,
            issue_month="2021-05",
            title="Sampada: May 2021 Maharashtra @ 61",
            url="https://www.mcciapunesampada.com/p/may-2021-maharashtra-61.html",
        ),
    ]


def test_parse_pages_feed_handles_empty_feed():
    assert parse_pages_feed({"feed": {"entry": []}}) == []
    assert parse_pages_feed({}) == []


def test_build_issue_month_index_keys_by_issue_month():
    index = build_issue_month_index(parse_pages_feed(SAMPLE_FEED))
    assert set(index.keys()) == {"2026-07", "2021-05"}
    assert index["2021-05"].url == "https://www.mcciapunesampada.com/p/may-2021-maharashtra-61.html"


def test_lookup_source_url_finds_matching_issue(monkeypatch):
    monkeypatch.setattr("ingest.web_archive.fetch_pages_feed", lambda: SAMPLE_FEED)

    assert lookup_source_url("2021-05") == "https://www.mcciapunesampada.com/p/may-2021-maharashtra-61.html"


def test_lookup_source_url_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr("ingest.web_archive.fetch_pages_feed", lambda: SAMPLE_FEED)

    assert lookup_source_url("1999-01") is None


def test_lookup_source_url_survives_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise TimeoutError("no network in this sandbox")

    monkeypatch.setattr("ingest.web_archive.fetch_pages_feed", boom)

    assert lookup_source_url("2021-05") is None


def test_find_new_web_issues_diffs_against_ingested_months():
    issues = parse_pages_feed(SAMPLE_FEED)
    ingested = {"2021-05"}

    new = find_new_web_issues(ingested, issues)

    assert [i.issue_month for i in new] == ["2026-07"]


def test_find_new_web_issues_empty_when_everything_already_ingested():
    issues = parse_pages_feed(SAMPLE_FEED)
    ingested = {i.issue_month for i in issues}

    assert find_new_web_issues(ingested, issues) == []


def test_check_for_new_issues_survives_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise TimeoutError("no network in this sandbox")

    monkeypatch.setattr("ingest.web_archive.fetch_pages_feed", boom)

    assert check_for_new_issues(set()) == []


def test_check_for_new_issues_returns_new_ones(monkeypatch):
    monkeypatch.setattr("ingest.web_archive.fetch_pages_feed", lambda: SAMPLE_FEED)

    new = check_for_new_issues({"2021-05"})

    assert [i.issue_month for i in new] == ["2026-07"]
