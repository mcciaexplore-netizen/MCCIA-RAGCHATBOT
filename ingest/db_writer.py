"""Writes split, chunked, embedded articles into Postgres.

Resumability (Phase 2 step 8) is a DB check, not a local manifest file: an
issue is considered already ingested if any article with its Drive file ID
is already in the articles table.
"""

from typing import List, Optional, Set

import psycopg

from ingest.chunking import chunk_text
from ingest.embeddings import embed_texts
from ingest.split_articles import Article


def already_ingested(conn: psycopg.Connection, drive_file_id: str, issue_month: str) -> bool:
    """A single PDF can bundle several issues (see extract_text.py), so
    resumability is keyed on (drive_file_id, issue_month), not just the
    file -- otherwise ingesting one issue from a PDF would make every other
    issue still bundled in that same file look "already done"."""
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from articles where drive_file_id = %s and issue_month = %s limit 1",
            (drive_file_id, issue_month),
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
    with conn.cursor() as cur:
        cur.execute(
            "select drive_file_id from articles where issue_month = %s limit 1",
            (issue_month,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def ingested_issue_months(conn: psycopg.Connection) -> Set[str]:
    """Phase 6: what check_for_new_issues() diffs the web archive against."""
    with conn.cursor() as cur:
        cur.execute("select distinct issue_month from articles")
        return {row[0] for row in cur.fetchall()}


def insert_article(
    conn: psycopg.Connection,
    *,
    issue_year: int,
    issue_month_number: int,
    article_index: int,
    issue_month: str,
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
                (issue_year, issue_month_number, article_index, issue_month,
                 article_title, author, body, source_url, drive_file_id)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                issue_year,
                issue_month_number,
                article_index,
                issue_month,
                article_title,
                author or None,
                body,
                source_url,
                drive_file_id,
            ),
        )
        row = cur.fetchone()
        return row[0]


def insert_chunks(conn: psycopg.Connection, article_id: int, chunks: List[str], embeddings: List[List[float]]) -> None:
    assert len(chunks) == len(embeddings), "chunk/embedding count mismatch"
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into chunks (article_id, chunk_index, content, embedding)
            values (%s, %s, %s, %s)
            """,
            [
                (article_id, i, content, embedding)
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
    issue_month: str,
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
        issue_month=issue_month,
        article_title=article.title,
        author=article.author,
        body=article.body,
        source_url=source_url,
        drive_file_id=drive_file_id,
    )

    chunks = chunk_text(article.body)
    if chunks:
        embeddings = embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")
        insert_chunks(conn, article_id, chunks, embeddings)

    return article_id
