"""Look up an issue's page on mcciapunesampada.com, for 2021+ issues'
source_url (Phase 2 step 7).

Guessing issue-page URLs (e.g. "sampada-<month>-<year>.html") doesn't work
reliably -- real slugs on the site are inconsistent ("sampada-february-2025",
but also "may-2021-maharashtra-61", "october-and-november-2021-business").
Instead this reads the site's Blogger "Pages" JSON feed, which lists every
issue page regardless of its slug, and reuses detect_issue_date's month/year
parsing against each page's *title* (titles are consistently "SAMPADA
<MONTH> <YEAR>"-shaped even when slugs aren't).

Note: the approved db/schema.sql has no topic_tags column, so despite the
original spec mentioning topic tags, only the post URL is pulled here.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from ingest.config import web_archive_base_url as _web_archive_base_url
from ingest.detect_issue_date import detect_issue_date

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


def fetch_pages_feed(base_url: Optional[str] = None, max_results: int = 200, timeout: int = 10) -> dict:
    base_url = base_url or _web_archive_base_url()
    url = f"{base_url}{PAGES_FEED_PATH}&max-results={max_results}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def build_issue_month_index(web_issues: List[WebIssue]) -> Dict[str, WebIssue]:
    """Last entry wins on a duplicate issue_month -- good enough for a
    best-effort supplementary signal, not worth failing ingestion over.
    """
    return {issue.issue_month: issue for issue in web_issues}


def lookup_source_url(issue_month: str) -> Optional[str]:
    """Best-effort: a network hiccup or missing page should never fail the
    whole pipeline run, since this is a supplementary signal, not the
    mechanism that actually ingests anything.
    """
    try:
        feed = fetch_pages_feed()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[WEB CHECK] could not reach {_web_archive_base_url()}: {exc}")
        return None

    index = build_issue_month_index(parse_pages_feed(feed))
    issue = index.get(issue_month)
    return issue.url if issue else None


def find_new_web_issues(ingested_months: Set[str], web_issues: List[WebIssue]) -> List[WebIssue]:
    """Pure diff against whatever issue_months are already in Postgres."""
    return [issue for issue in web_issues if issue.issue_month not in ingested_months]


def check_for_new_issues(ingested_months: Set[str]) -> List[WebIssue]:
    """Phase 6: supplementary signal that an issue is live on the web but we
    don't have its PDF yet -- logs what it finds, doesn't scrape article
    content or attempt ingestion from HTML (Drive PDFs stay the only
    ingestion source). Best-effort like lookup_source_url: a network hiccup
    here should never fail the scheduled job.
    """
    try:
        feed = fetch_pages_feed()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[WEB CHECK] could not reach {_web_archive_base_url()}: {exc}")
        return []

    web_issues = parse_pages_feed(feed)
    new_issues = find_new_web_issues(ingested_months, web_issues)
    for issue in new_issues:
        print(
            f"[WEB CHECK] '{issue.title}' ({issue.issue_month}) is live at "
            f"{issue.url} but not yet in our archive"
        )
    return new_issues
