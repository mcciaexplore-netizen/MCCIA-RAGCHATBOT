"""Write split articles to the local processed/ tree, mirroring the S3 layout:
processed/<year>/<month>/<article-slug>.txt (+ .metadata.json sidecar).
"""
import json
import re
from datetime import date
from pathlib import Path
from typing import List, Optional

from .config import CONFIG
from .split_articles import Article

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = 60) -> str:
    slug = _SLUG_STRIP_RE.sub("-", title.lower()).strip("-")
    if not slug:
        slug = "untitled"
    return slug[:max_len].strip("-")


def dedupe_slug(slug: str, taken: set) -> str:
    if slug not in taken:
        return slug
    i = 2
    while f"{slug}-{i}" in taken:
        i += 1
    return f"{slug}-{i}"


def format_issue_date(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def article_text_body(article: Article, year: int, month: int) -> str:
    # Bedrock's RetrieveAndGenerate never exposes metadata attributes to the
    # generation model -- it only ever sees this chunk text. The issue date
    # has to be printed here, not just in the metadata sidecar, or the model
    # has no way to write the "(Sampada, <Month Year>, ...)" citations the
    # spec requires.
    header = f"{article.title}\nSampada, {format_issue_date(year, month)}\n"
    if article.author:
        header += f"By {article.author}\n"
    return header + "\n" + article.body


def write_issue_articles(
    articles: List[Article],
    year: int,
    month: int,
    source_url: str = "",
    topic_tags: Optional[List[str]] = None,
    output_root: Optional[Path] = None,
) -> List[Path]:
    output_root = output_root or CONFIG.local_processed_dir
    issue_dir = output_root / f"{year:04d}" / f"{month:02d}"
    issue_dir.mkdir(parents=True, exist_ok=True)

    taken_slugs = set()
    written = []
    for article in articles:
        slug = dedupe_slug(slugify(article.title), taken_slugs)
        taken_slugs.add(slug)

        txt_path = issue_dir / f"{slug}.txt"
        txt_path.write_text(article_text_body(article, year, month), encoding="utf-8")

        metadata_attrs = {
            "issue_month": f"{year:04d}-{month:02d}",
            "issue_year": year,
            "article_title": article.title,
            "source_url": source_url,
            "content_type": "text",
        }
        if topic_tags:
            metadata_attrs["topic_tags"] = topic_tags

        meta_path = issue_dir / f"{slug}.txt.metadata.json"
        meta_path.write_text(
            json.dumps({"metadataAttributes": metadata_attrs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(txt_path)
    return written
