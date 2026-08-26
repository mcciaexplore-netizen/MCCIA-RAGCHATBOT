import json

import pytest

from ingest.detect_issue_boundaries import (
    IssueBoundary,
    IssueBoundaryError,
    number_page_previews,
    parse_boundaries_json,
    request_boundaries,
    split_into_issues,
)

PAGES = [
    "Year 1] July 1945 [Issue 1",  # 0: cover
    "body text of the July 1945 issue",  # 1
    "more body text",  # 2
    "Year 1] December-January 1946 [Issue 2",  # 3: cover
    "body text of the combined issue",  # 4
]


def test_number_page_previews_prefixes_every_page():
    numbered = number_page_previews(["a", "b"])
    assert numbered == "PAGE0:\na\n\nPAGE1:\nb"


def test_number_page_previews_truncates_to_preview_chars():
    numbered = number_page_previews(["x" * 1000], preview_chars=10)
    assert numbered == "PAGE0:\n" + "x" * 10


def test_parse_boundaries_json_reads_valid_response():
    raw = json.dumps({"issues": [{"start_page": 0, "year": 1945, "month": 7}]})
    boundaries = parse_boundaries_json(raw, page_count=5)
    assert boundaries == [IssueBoundary(start_page=0, year=1945, month=7)]


def test_parse_boundaries_json_sorts_by_start_page():
    raw = json.dumps(
        {
            "issues": [
                {"start_page": 3, "year": 1946, "month": 1},
                {"start_page": 0, "year": 1945, "month": 7},
            ]
        }
    )
    boundaries = parse_boundaries_json(raw, page_count=5)
    assert [b.start_page for b in boundaries] == [0, 3]


def test_parse_boundaries_json_rejects_invalid_json():
    with pytest.raises(IssueBoundaryError):
        parse_boundaries_json("not json at all", page_count=5)


def test_parse_boundaries_json_rejects_wrong_shape():
    with pytest.raises(IssueBoundaryError):
        parse_boundaries_json(json.dumps({"not_issues": []}), page_count=5)


def test_parse_boundaries_json_rejects_empty_issue_list():
    with pytest.raises(IssueBoundaryError):
        parse_boundaries_json(json.dumps({"issues": []}), page_count=5)


def test_parse_boundaries_json_rejects_out_of_range_start_page():
    raw = json.dumps({"issues": [{"start_page": 99, "year": 1945, "month": 7}]})
    with pytest.raises(IssueBoundaryError):
        parse_boundaries_json(raw, page_count=5)


class _FakeGemini:
    """Stands in for a genai.Client -- returns queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    class _Interactions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.calls += 1
            text = self._outer._responses.pop(0)
            return type("Interaction", (), {"output_text": text})()

    @property
    def interactions(self):
        return self._Interactions(self)


VALID_RESPONSE = json.dumps(
    {
        "issues": [
            {"start_page": 0, "year": 1945, "month": 7},
            {"start_page": 3, "year": 1946, "month": 1},
        ]
    }
)


def test_request_boundaries_succeeds_on_first_try():
    client = _FakeGemini([VALID_RESPONSE])
    boundaries = request_boundaries("PAGE0:\ntext", page_count=5, client=client)
    assert boundaries == [
        IssueBoundary(start_page=0, year=1945, month=7),
        IssueBoundary(start_page=3, year=1946, month=1),
    ]
    assert client.calls == 1


def test_request_boundaries_retries_once_then_succeeds():
    client = _FakeGemini(["not json", VALID_RESPONSE])
    boundaries = request_boundaries("PAGE0:\ntext", page_count=5, client=client)
    assert len(boundaries) == 2
    assert client.calls == 2


def test_request_boundaries_gives_up_after_one_retry():
    client = _FakeGemini(["not json", "still not json"])
    with pytest.raises(IssueBoundaryError):
        request_boundaries("PAGE0:\ntext", page_count=5, client=client)
    assert client.calls == 2


def test_split_into_issues_groups_pages_between_consecutive_covers():
    client = _FakeGemini([VALID_RESPONSE])
    issues = split_into_issues(PAGES, client=client)

    assert len(issues) == 2
    (first_boundary, first_pages), (second_boundary, second_pages) = issues

    assert first_boundary == IssueBoundary(start_page=0, year=1945, month=7)
    assert first_pages == PAGES[0:3]

    assert second_boundary == IssueBoundary(start_page=3, year=1946, month=1)
    assert second_pages == PAGES[3:5]


def test_split_into_issues_single_issue_runs_to_end_of_document():
    raw = json.dumps({"issues": [{"start_page": 0, "year": 2021, "month": 6}]})
    client = _FakeGemini([raw])
    issues = split_into_issues(["cover", "body one", "body two"], client=client)

    assert len(issues) == 1
    boundary, pages = issues[0]
    assert boundary == IssueBoundary(start_page=0, year=2021, month=6)
    assert pages == ["cover", "body one", "body two"]
