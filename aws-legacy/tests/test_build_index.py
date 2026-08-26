import json

from ingest.build_index import load_index, upsert_issue, write_index
from ingest.split_articles import Article


def test_load_index_missing_file_returns_empty(tmp_path):
    assert load_index(tmp_path / "issues.json") == {}


def test_upsert_and_write_roundtrip(tmp_path):
    index = {}
    articles = [
        Article(title="Editorial", author="", body="..."),
        Article(title="Women in Robotics", author="Asha Rao", body="..."),
    ]
    written_paths = [tmp_path / "editorial.txt", tmp_path / "women-in-robotics.txt"]

    upsert_issue(index, 2021, 6, written_paths, articles, source_url="https://example.com/june")

    index_path = tmp_path / "index" / "issues.json"
    write_index(index, index_path)

    data = json.loads(index_path.read_text())
    assert data == {
        "issues": [
            {
                "year": 2021,
                "month": 6,
                "issueMonth": "2021-06",
                "label": "June 2021",
                "articles": [
                    {"title": "Editorial", "slug": "editorial", "sourceUrl": "https://example.com/june"},
                    {
                        "title": "Women in Robotics",
                        "slug": "women-in-robotics",
                        "sourceUrl": "https://example.com/june",
                    },
                ],
            }
        ]
    }


def test_write_index_sorts_newest_first(tmp_path):
    index = {}
    upsert_issue(index, 2020, 1, [tmp_path / "a.txt"], [Article(title="A", author="", body="")])
    upsert_issue(index, 2021, 6, [tmp_path / "b.txt"], [Article(title="B", author="", body="")])
    upsert_issue(index, 2019, 12, [tmp_path / "c.txt"], [Article(title="C", author="", body="")])

    index_path = tmp_path / "issues.json"
    write_index(index, index_path)

    data = json.loads(index_path.read_text())
    assert [issue["issueMonth"] for issue in data["issues"]] == ["2021-06", "2020-01", "2019-12"]


def test_upsert_replaces_existing_issue_on_reprocess(tmp_path):
    index = {}
    upsert_issue(index, 2021, 6, [tmp_path / "old.txt"], [Article(title="Old Title", author="", body="")])
    upsert_issue(index, 2021, 6, [tmp_path / "new.txt"], [Article(title="New Title", author="", body="")])

    assert len(index) == 1
    assert index["2021-06"]["articles"] == [{"title": "New Title", "slug": "new", "sourceUrl": ""}]


def test_load_index_reads_back_what_write_index_wrote(tmp_path):
    index_path = tmp_path / "issues.json"
    index = {}
    upsert_issue(index, 2021, 6, [tmp_path / "editorial.txt"], [Article(title="Editorial", author="", body="")])
    write_index(index, index_path)

    reloaded = load_index(index_path)
    assert set(reloaded.keys()) == {"2021-06"}
    assert reloaded["2021-06"]["label"] == "June 2021"
