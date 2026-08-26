"""Writes split, chunked, embedded articles into Postgres.

Resumability (Phase 2 step 8) is a DB check, not a local manifest file: an
issue is considered already ingested if any article with its Drive file ID
is already in the articles table.
"""

from typing import List, Optional

import psycopg

from ingest.chunking import chunk_text
from ingest.embeddings import embed_texts
from ingest.split_articles import Article


def already_ingested(conn: psycopg.Connection, drive_file_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("select 1 from articles where drive_file_id = %s limit 1", (drive_file_id,))
        return cur.fetchone() is not None


def insert_article(
    conn: psycopg.Connection,
    *,
    issue_month: str,
    issue_year: int,
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
                (issue_month, issue_year, article_title, author, body, source_url, drive_file_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                issue_month,
                issue_year,
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
    issue_month: str,
    issue_year: int,
    source_url: Optional[str],
    drive_file_id: str,
) -> int:
    """Inserts one article and its chunks+embeddings. Caller controls the
    transaction (commit/rollback) -- see run_pipeline.process_pdf.
    """
    article_id = insert_article(
        conn,
        issue_month=issue_month,
        issue_year=issue_year,
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
