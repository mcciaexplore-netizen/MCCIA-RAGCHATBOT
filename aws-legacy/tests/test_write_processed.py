import json

from ingest.split_articles import Article
from ingest.write_processed import dedupe_slug, format_issue_date, slugify, write_issue_articles


def test_format_issue_date():
    assert format_issue_date(2021, 6) == "June 2021"
    assert format_issue_date(1999, 1) == "January 1999"


def test_slugify_basic():
    assert slugify("Women in Robotics: A New Era!") == "women-in-robotics-a-new-era"


def test_slugify_empty_title_falls_back():
    assert slugify("...") == "untitled"


def test_dedupe_slug():
    taken = {"editorial"}
    assert dedupe_slug("editorial", taken) == "editorial-2"


def test_write_issue_articles_creates_txt_and_metadata(tmp_path):
    articles = [
        Article(title="Editorial", author="", body="Welcome to this issue."),
        Article(title="Women in Robotics", author="Asha Rao", body="Robotics is growing fast."),
    ]
    written = write_issue_articles(articles, year=2021, month=6, source_url="", output_root=tmp_path)

    assert len(written) == 2
    issue_dir = tmp_path / "2021" / "06"
    assert (issue_dir / "editorial.txt").exists()
    assert (issue_dir / "women-in-robotics.txt").exists()

    meta = json.loads((issue_dir / "women-in-robotics.txt.metadata.json").read_text())
    attrs = meta["metadataAttributes"]
    assert attrs == {
        "issue_month": "2021-06",
        "issue_year": 2021,
        "article_title": "Women in Robotics",
        "source_url": "",
        "content_type": "text",
    }

    body = (issue_dir / "women-in-robotics.txt").read_text()
    assert body.startswith("Women in Robotics\nSampada, June 2021\nBy Asha Rao\n")
    assert "Robotics is growing fast." in body


def test_write_issue_articles_dedupes_slugs(tmp_path):
    articles = [
        Article(title="Editorial", author="", body="First."),
        Article(title="Editorial", author="", body="Second, different article same title."),
    ]
    written = write_issue_articles(articles, year=2020, month=1, output_root=tmp_path)
    names = sorted(p.name for p in written)
    assert names == ["editorial-2.txt", "editorial.txt"]
