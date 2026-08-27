"""Writes Sampada publications, articles, and vector chunks into Postgres."""

from typing import List, Optional, Set

import psycopg

from ingest.chunking import chunk_text
from ingest.embeddings import embed_texts
from ingest.split_articles import Article


def _parse_issue_month(issue_month: str) -> tuple[int, int]:
    year_text, month_text = issue_month.split("-", maxsplit=1)
    year, month = int(year_text), int(month_text)
    if len(year_text) != 4 or len(month_text) != 2 or not 1 <= month <= 12:
        raise ValueError(f"invalid issue month: {issue_month!r}")
    return year, month


def already_ingested(conn: psycopg.Connection, drive_file_id: str, issue_month: str) -> bool:
    """A single PDF can bundle several issues (see extract_text.py), so
    resumability is keyed on (drive_file_id, issue_month), not just the
    file -- otherwise ingesting one issue from a PDF would make every other
    issue still bundled in that same file look "already done"."""
    year, month = _parse_issue_month(issue_month)
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from sampada where source_pdf_id = %s and year = %s and month = %s limit 1",
            (drive_file_id, year, month),
        )
        return cur.fetchone() is not None


def issue_month_source(conn: psycopg.Connection, issue_month: str) -> Optional[str]:
    """The drive_file_id already holding this issue_month, if any -- from
    ANY source PDF, not just the one currently being processed.

    The real Drive archive has overlapping scans (e.g. a standalone
    "2011-Jan.PDF" alongside a "2011-Feb To 2011-Dec.PDF" bound volume, or a
    bound volume split into "Part-1"/"Part-2" files that can misdetect a
    shared boundary page): already_ingested() alone only catches the same
    file being reprocessed, not a different file claiming an issue_month
    that's already here from elsewhere. Used to skip -- and flag for manual
    review -- rather than silently writing the same issue twice from two
    different sources."""
    year, month = _parse_issue_month(issue_month)
    with conn.cursor() as cur:
        cur.execute(
            "select source_pdf_id from sampada where year = %s and month = %s limit 1",
            (year, month),
        )
        row = cur.fetchone()
        return row[0] if row else None


def ingested_issue_months(conn: psycopg.Connection) -> Set[str]:
    """Phase 6: what check_for_new_issues() diffs the web archive against."""
    with conn.cursor() as cur:
        cur.execute("select year, month from sampada")
        return {f"{year:04d}-{month:02d}" for year, month in cur.fetchall()}


def upsert_sampada(
    conn: psycopg.Connection,
    *,
    year: int,
    month: int,
    source_pdf_id: str,
    source_url: Optional[str],
) -> None:
    """Create the monthly Sampada row before inserting its articles."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into sampada (year, month, source_pdf_id, source_url)
            values (%s, %s, %s, %s)
            on conflict (year, month) do update
            set source_url = coalesce(excluded.source_url, sampada.source_url)
            where sampada.source_pdf_id = excluded.source_pdf_id
            returning source_pdf_id
            """,
            (year, month, source_pdf_id, source_url),
        )
        if cur.fetchone() is None:
            raise ValueError(
                f"issue {year:04d}-{month:02d} already belongs to a different source PDF"
            )


def insert_article(
    conn: psycopg.Connection,
    *,
    issue_year: int,
    issue_month_number: int,
    article_index: int,
    article_title: str,
    author: str,
    body: str,
    source_url: Optional[str],
    drive_file_id: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into articles
                (year, month, article_index, article_title, author, body,
                 source_url, source_pdf_id)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                issue_year,
                issue_month_number,
                article_index,
                article_title,
                author or None,
                body,
                source_url,
                drive_file_id,
            ),
        )
        row = cur.fetchone()
        return row[0]


def insert_smaller_chunks(
    conn: psycopg.Connection,
    *,
    year: int,
    month: int,
    article_index: int,
    chunks: List[str],
    embeddings: List[List[float]],
) -> None:
    assert len(chunks) == len(embeddings), "chunk/embedding count mismatch"
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into smaller_chunks
                (year, month, article_index, chunk_index, content, embedding)
            values (%s, %s, %s, %s, %s, %s)
            """,
            [
                (year, month, article_index, i, content, embedding)
                for i, (content, embedding) in enumerate(zip(chunks, embeddings))
            ],
        )


def write_article(
    conn: psycopg.Connection,
    article: Article,
    *,
    issue_year: int,
    issue_month_number: int,
    article_index: int,
    source_url: Optional[str],
    drive_file_id: str,
) -> int:
    """Inserts one article and its chunks+embeddings. Caller controls the
    transaction (commit/rollback) -- see run_pipeline.process_pdf.
    """
    article_id = insert_article(
        conn,
        issue_year=issue_year,
        issue_month_number=issue_month_number,
        article_index=article_index,
        article_title=article.title,
        author=article.author,
        body=article.body,
        source_url=source_url,
        drive_file_id=drive_file_id,
    )

    chunks = chunk_text(article.body)
    if chunks:
        embeddings = embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")
        insert_smaller_chunks(
            conn,
            year=issue_year,
            month=issue_month_number,
            article_index=article_index,
            chunks=chunks,
            embeddings=embeddings,
        )

    return article_id
