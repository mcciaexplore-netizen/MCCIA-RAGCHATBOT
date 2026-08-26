from ingest.split_articles import (
    ArticleBoundary,
    number_lines,
    parse_boundaries_response,
    slice_articles,
)

SAMPLE_TEXT = "\n".join(
    [
        "SAMPADA",  # 0
        "June 2021",  # 1
        "",  # 2
        "Editorial",  # 3
        "By The Editor",  # 4
        "Welcome to this special issue on robotics.",  # 5
        "",  # 6
        "Women in Robotics",  # 7
        "By Asha Rao",  # 8
        "The field is changing fast.",  # 9
        "More women are entering it every year.",  # 10
    ]
)


def test_number_lines_prefixes_every_line():
    numbered = number_lines("a\nb\nc")
    assert numbered.split("\n") == ["L0: a", "L1: b", "L2: c"]


def test_slice_articles_extracts_correct_bodies():
    boundaries = [
        ArticleBoundary(title="Editorial", author="The Editor", start_line=3, end_line=5),
        ArticleBoundary(title="Women in Robotics", author="Asha Rao", start_line=7, end_line=10),
    ]
    articles = slice_articles(SAMPLE_TEXT, boundaries)

    assert len(articles) == 2
    assert articles[0].title == "Editorial"
    assert "Welcome to this special issue" in articles[0].body
    assert articles[1].title == "Women in Robotics"
    assert "More women are entering it every year." in articles[1].body
    # cover/masthead lines (0-2) and the blank separator (6) should not leak in
    assert "SAMPADA" not in articles[0].body
    assert "SAMPADA" not in articles[1].body


def test_slice_articles_sorts_by_start_line_regardless_of_input_order():
    boundaries = [
        ArticleBoundary(title="Women in Robotics", author="Asha Rao", start_line=7, end_line=10),
        ArticleBoundary(title="Editorial", author="The Editor", start_line=3, end_line=5),
    ]
    articles = slice_articles(SAMPLE_TEXT, boundaries)
    assert [a.title for a in articles] == ["Editorial", "Women in Robotics"]


def test_slice_articles_clamps_out_of_range_lines():
    boundaries = [ArticleBoundary(title="Runaway", author="", start_line=9, end_line=9999)]
    articles = slice_articles(SAMPLE_TEXT, boundaries)
    assert len(articles) == 1
    assert "More women are entering it every year." in articles[0].body


def test_slice_articles_drops_empty_ranges():
    boundaries = [ArticleBoundary(title="Empty", author="", start_line=2, end_line=2)]
    articles = slice_articles(SAMPLE_TEXT, boundaries)
    assert articles == []


def test_parse_boundaries_response_reads_tool_use_block():
    response = {
        "output": {
            "message": {
                "content": [
                    {"text": "some preamble the model might add"},
                    {
                        "toolUse": {
                            "name": "record_article_boundaries",
                            "input": {
                                "articles": [
                                    {"title": "Editorial", "author": "", "start_line": 3, "end_line": 5}
                                ]
                            },
                        }
                    },
                ]
            }
        }
    }
    boundaries = parse_boundaries_response(response)
    assert boundaries == [ArticleBoundary(title="Editorial", author="", start_line=3, end_line=5)]
