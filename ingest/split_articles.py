"""Split one issue's full text into individual articles using Claude on Bedrock.

Design note: we do NOT ask Claude to re-emit article bodies. Two reasons:
  1. Bedrock responses are capped by max output tokens; a full magazine issue's
     worth of body text can exceed that and get silently truncated.
  2. Citations need to be byte-exact to the source PDF -- having a model
     retype the body risks paraphrasing/typos that would make citations
     untrustworthy.

Instead, we number every line of the extracted text and ask Claude to return
only (title, author, start_line, end_line) per article -- tiny output -- and
then slice the *original* text ourselves.
"""
import json
from dataclasses import dataclass
from typing import List, Optional

from .config import CONFIG, require_for_bedrock

RECORD_BOUNDARIES_TOOL = {
    "toolSpec": {
        "name": "record_article_boundaries",
        "description": (
            "Record every distinct article found in this magazine issue, as "
            "line-number ranges into the numbered source text provided."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "articles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "The article's title/headline, verbatim.",
                                },
                                "author": {
                                    "type": "string",
                                    "description": "Byline author name, or empty string if none is printed.",
                                },
                                "start_line": {
                                    "type": "integer",
                                    "description": "First line number (inclusive) of this article's body, per the L#### markers.",
                                },
                                "end_line": {
                                    "type": "integer",
                                    "description": "Last line number (inclusive) of this article's body, per the L#### markers.",
                                },
                            },
                            "required": ["title", "author", "start_line", "end_line"],
                        },
                    }
                },
                "required": ["articles"],
            }
        },
    }
}

SYSTEM_PROMPT = """You split one issue of Sampada, an Indian industrial trade \
magazine, into its individual articles. You are given the issue's text with \
every line prefixed by a marker like L0001, L0002, etc.

Rules:
- Every distinct article (feature, column, interview, editorial) gets its own \
entry. Do not merge separate articles together.
- Skip non-article content: cover pages, table of contents, ads, subscription \
forms, back-cover matter. Don't invent an entry for them.
- title: the article's headline, exactly as printed.
- author: the byline name if one is printed (e.g. "By Jane Doe" -> "Jane \
Doe"), otherwise an empty string. Never guess an author.
- start_line/end_line: the L#### line numbers spanning that article's \
headline through its last line of body text, inclusive. Ranges should not \
overlap between articles.
- Call record_article_boundaries exactly once with all articles in reading \
order."""


@dataclass
class ArticleBoundary:
    title: str
    author: str
    start_line: int
    end_line: int


@dataclass
class Article:
    title: str
    author: str
    body: str


def number_lines(text: str) -> str:
    lines = text.split("\n")
    width = len(str(len(lines)))
    return "\n".join(f"L{str(i).zfill(width)}: {line}" for i, line in enumerate(lines))


def _bedrock_client():
    import boto3

    return boto3.client("bedrock-runtime", region_name=CONFIG.aws_region)


def request_boundaries(numbered_text: str, client=None) -> List[ArticleBoundary]:
    """Calls Bedrock Converse with a forced tool call and returns the parsed
    boundaries. Raises if the model doesn't call the tool as expected.
    """
    require_for_bedrock()
    client = client or _bedrock_client()

    response = client.converse(
        modelId=CONFIG.bedrock_article_split_model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": numbered_text}]}],
        toolConfig={
            "tools": [RECORD_BOUNDARIES_TOOL],
            "toolChoice": {"tool": {"name": "record_article_boundaries"}},
        },
    )
    return parse_boundaries_response(response)


def parse_boundaries_response(response: dict) -> List[ArticleBoundary]:
    content = response["output"]["message"]["content"]
    for block in content:
        if "toolUse" in block and block["toolUse"]["name"] == "record_article_boundaries":
            payload = block["toolUse"]["input"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return [
                ArticleBoundary(
                    title=a["title"].strip(),
                    author=a.get("author", "").strip(),
                    start_line=int(a["start_line"]),
                    end_line=int(a["end_line"]),
                )
                for a in payload["articles"]
            ]
    raise ValueError("Model response did not include a record_article_boundaries tool call")


def slice_articles(text: str, boundaries: List[ArticleBoundary]) -> List[Article]:
    """Pure function: slices the original (unnumbered) text using boundary
    line ranges. Kept separate from the Bedrock call so it's unit-testable
    without any network access.
    """
    lines = text.split("\n")
    n = len(lines)
    articles = []
    for b in sorted(boundaries, key=lambda x: x.start_line):
        start = max(0, min(b.start_line, n - 1))
        end = max(0, min(b.end_line, n - 1))
        if end < start:
            continue
        body = "\n".join(lines[start : end + 1]).strip()
        if not body:
            continue
        articles.append(Article(title=b.title, author=b.author, body=body))
    return articles


def split_issue_into_articles(full_text: str, client=None) -> List[Article]:
    numbered = number_lines(full_text)
    boundaries = request_boundaries(numbered, client=client)
    return slice_articles(full_text, boundaries)
