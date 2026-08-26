"""Maintains index/issues.json -- the archive browse page's data source.

Bedrock's Retrieve/RetrieveAndGenerate APIs are semantic search, not built
for an exhaustive chronological listing, so the browse page (Phase 5) needs
a real index. This lives at index/issues.json in S3, deliberately outside
processed/ so the knowledge base's S3 data source (scoped to processed/)
never tries to embed it as an article. Key must match BROWSE_INDEX_KEY in
infra/sampada_stack.py.
"""
import json
from pathlib import Path
from typing import Dict, List

from .split_articles import Article
from .write_processed import format_issue_date

INDEX_KEY = "index/issues.json"


def load_index(path: Path) -> Dict[str, dict]:
    """Returns {issue_month: issue_dict}, empty if no index exists yet."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {issue["issueMonth"]: issue for issue in data.get("issues", [])}


def upsert_issue(
    index: Dict[str, dict],
    year: int,
    month: int,
    written_paths: List[Path],
    articles: List[Article],
    source_url: str = "",
) -> Dict[str, dict]:
    """Adds/replaces one issue's entry. written_paths must be the paths
    returned by write_issue_articles for these same articles, in the same
    order -- slugs are read from the filenames actually written rather than
    re-derived, so this can never drift from what's on disk.
    """
    issue_month = f"{year:04d}-{month:02d}"
    index[issue_month] = {
        "year": year,
        "month": month,
        "issueMonth": issue_month,
        "label": format_issue_date(year, month),
        "articles": [
            {"title": article.title, "slug": path.stem, "sourceUrl": source_url}
            for path, article in zip(written_paths, articles)
        ],
    }
    return index


def write_index(index: Dict[str, dict], path: Path) -> None:
    issues = sorted(index.values(), key=lambda issue: issue["issueMonth"], reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"issues": issues}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
