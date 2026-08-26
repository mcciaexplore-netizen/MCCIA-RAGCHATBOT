"""Figure out which (year, month) issue a PDF belongs to.

We can't assume a naming convention in the Drive folder, so this tries, in
order: the filename, then the first couple of pages of extracted text (magazine
covers/mastheads almost always print the issue month somewhere). If neither
matches, the caller is expected to log it for manual review rather than guess.
"""

import re
from typing import Optional, Tuple

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_NAMES = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))

# Ordered: most specific / least ambiguous first.
_PATTERNS = [
    # 2021-06, 2021_06, 2021.06
    re.compile(r"(?P<year>19\d{2}|20\d{2})[-_.](?P<month>0?[1-9]|1[0-2])(?![0-9])"),
    # 06-2021, 06_2021
    re.compile(r"(?P<month>0?[1-9]|1[0-2])[-_.](?P<year>19\d{2}|20\d{2})(?![0-9])"),
    # June 2021 / Jun 2021 / June-2021 / June_2021
    re.compile(rf"(?P<mon>{_MONTH_NAMES})[a-z]*[\s\-_,]+(?P<year>19\d{{2}}|20\d{{2}})", re.IGNORECASE),
    # 2021 June
    re.compile(rf"(?P<year>19\d{{2}}|20\d{{2}})[\s\-_,]+(?P<mon>{_MONTH_NAMES})[a-z]*", re.IGNORECASE),
]


def _match_to_year_month(m: re.Match) -> Optional[Tuple[int, int]]:
    groups = m.groupdict()
    year = int(groups["year"])
    if "month" in groups and groups["month"]:
        month = int(groups["month"])
    else:
        month = MONTHS.get(groups["mon"].lower())
    if month is None or not (1 <= month <= 12):
        return None
    # The Sampada archive itself runs from 1945 -- don't reject real issues.
    if not (1900 <= year <= 2100):
        return None
    return year, month


def _search_all_patterns(text: str) -> Optional[Tuple[int, int]]:
    for pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            result = _match_to_year_month(m)
            if result:
                return result
    return None


def detect_issue_date(filename: str, cover_text: str = "") -> Tuple[Optional[int], Optional[int]]:
    """Returns (year, month) or (None, None) if neither source is conclusive.

    `cover_text` should be the extracted text of roughly the first 2 pages --
    that's where a masthead/cover date almost always lives, and keeping it
    short avoids false positives from dates mentioned deeper in article bodies.
    """
    result = _search_all_patterns(filename)
    if result:
        return result

    result = _search_all_patterns(cover_text)
    if result:
        return result

    return None, None
