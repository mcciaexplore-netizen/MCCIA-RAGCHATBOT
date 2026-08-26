"""Supplementary signal: issues published on mcciapunesampada.com that we
don't have in our own index yet.

Guessing issue-page URLs (e.g. "sampada-<month>-<year>.html") doesn't work
reliably -- real slugs on the site are inconsistent ("sampada-february-2025",
but also "may-2021-maharashtra-61", "october-and-november-2021-business").
Instead this reads the site's Blogger "Pages" JSON feed, which lists every
issue page regardless of its slug, and reuses detect_issue_date's month/year
parsing against each page's *title* (titles are consistently "SAMPADA
<MONTH> <YEAR>"-shaped even when slugs aren't).
"""
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import CONFIG
from .detect_issue_date import detect_issue_date

PAGES_FEED_PATH = "/feeds/pages/default?alt=json"


@dataclass
class WebIssue:
    year: int
    month: int
    issue_month: str
    title: str
    url: str


def _entry_title(entry: dict) -> str:
    return entry.get("title", {}).get("$t", "")


def _entry_url(entry: dict) -> str:
    for link in entry.get("link", []):
        if link.get("rel") == "alternate":
            return link.get("href", "")
    return ""


def parse_pages_feed(feed_json: dict) -> List[WebIssue]:
    """Pure parsing, no network -- unit-testable with a captured fixture."""
    issues = []
    for entry in feed_json.get("feed", {}).get("entry", []):
        title = _entry_title(entry)
        url = _entry_url(entry)
        year, month = detect_issue_date(url, title)
        if year is None:
            continue
        issues.append(
            WebIssue(
                year=year,
                month=month,
                issue_month=f"{year:04d}-{month:02d}",
                title=title,
                url=url,
            )
        )
    return issues


def fetch_pages_feed(base_url: Optional[str] = None, max_results: int = 50, timeout: int = 10) -> dict:
    base_url = base_url or CONFIG.web_archive_base_url
    url = f"{base_url}{PAGES_FEED_PATH}&max-results={max_results}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_new_web_issues(index: Dict[str, dict], web_issues: List[WebIssue]) -> List[WebIssue]:
    """Pure diff against our own index (see build_index.load_index)."""
    return [issue for issue in web_issues if issue.issue_month not in index]


def check_for_new_issues(index: Dict[str, dict]) -> List[WebIssue]:
    """Best-effort: a network hiccup here should never fail the whole
    pipeline run, since this is a supplementary signal, not the mechanism
    that actually ingests anything.
    """
    try:
        feed = fetch_pages_feed()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[WEB CHECK] could not reach {CONFIG.web_archive_base_url}: {exc}")
        return []

    web_issues = parse_pages_feed(feed)
    new_issues = find_new_web_issues(index, web_issues)
    for issue in new_issues:
        print(
            f"[WEB CHECK] '{issue.title}' ({issue.issue_month}) is live at "
            f"{issue.url} but not yet in our archive"
        )
    return new_issues
