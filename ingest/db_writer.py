"""Writes Sampada publications, articles, and vector chunks into Postgres."""

from typing import List, Optional, Set

import psycopg
from psycopg import sql

from ingest.chunking import chunk_text, chunk_text_with_pages
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


# --- Ingestion status / resumability -----------------------------------
#
# Two granularities, matching the fact that one Drive PDF can bundle several
# monthly issues (see ingest/detect_issue_boundaries.py): file-level stages
# (download/validate/OCR/issue-detection) live on ingestion_files, keyed by
# drive_file_id; issue-level stages (article-splitting/chunk/embed/index)
# live as columns directly on sampada, keyed by (year, month) -- it already
# has one row per issue, so no second issue-level table is needed.
#
# Column names are checked against an explicit whitelist before being used
# as SQL identifiers (psycopg.sql.Identifier), rather than accepting an
# arbitrary string -- this is internal-only (never fed from user input) but
# there's no reason to build unvalidated SQL identifiers regardless.

_FILE_TIMESTAMP_COLUMNS = {
    "downloaded_at",
    "validated_at",
    "text_extracted_at",
    "ocr_started_at",
    "ocr_completed_at",
    "issue_detection_completed_at",
}

_ISSUE_TIMESTAMP_COLUMNS = {
    "article_splitting_completed_at",
    "chunked_at",
    "embedded_at",
    "indexed_at",
}


def upsert_ingestion_file(
    conn: psycopg.Connection,
    *,
    drive_file_id: str,
    filename: str,
    file_size: Optional[int] = None,
    drive_modified_time: Optional[str] = None,
) -> None:
    """Ensures a status row exists for this file -- discovered_at defaults
    to now() only on first insert; a rerun just refreshes the descriptive
    fields without resetting progress already recorded."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into ingestion_files (drive_file_id, filename, file_size, drive_modified_time)
            values (%s, %s, %s, %s)
            on conflict (drive_file_id) do update
            set filename = excluded.filename,
                file_size = excluded.file_size,
                drive_modified_time = coalesce(excluded.drive_modified_time, ingestion_files.drive_modified_time),
                updated_at = now()
            """,
            (drive_file_id, filename, file_size, drive_modified_time),
        )


def mark_file_stage(conn: psycopg.Connection, drive_file_id: str, column: str) -> None:
    if column not in _FILE_TIMESTAMP_COLUMNS:
        raise ValueError(f"unknown ingestion_files timestamp column: {column!r}")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "update ingestion_files set {col} = now(), updated_at = now() where drive_file_id = %s"
            ).format(col=sql.Identifier(column)),
            (drive_file_id,),
        )


def set_ocr_required(conn: psycopg.Connection, drive_file_id: str, required: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update ingestion_files set ocr_required = %s, updated_at = now() where drive_file_id = %s",
            (required, drive_file_id),
        )


def record_file_failure(conn: psycopg.Connection, drive_file_id: str, stage: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update ingestion_files
            set failed = true, failure_stage = %s, failure_reason = %s, updated_at = now()
            where drive_file_id = %s
            """,
            (stage, reason, drive_file_id),
        )


def mark_issue_stage(conn: psycopg.Connection, year: int, month: int, column: str) -> None:
    if column not in _ISSUE_TIMESTAMP_COLUMNS:
        raise ValueError(f"unknown sampada timestamp column: {column!r}")
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "update sampada set {col} = now(), last_processed_at = now() where year = %s and month = %s"
            ).format(col=sql.Identifier(column)),
            (year, month),
        )


def record_issue_failure(conn: psycopg.Connection, year: int, month: int, stage: str, reason: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update sampada
            set failed = true, failure_stage = %s, failure_reason = %s, last_processed_at = now()
            where year = %s and month = %s
            """,
            (stage, reason, year, month),
        )


def file_fully_ocrd(conn: psycopg.Connection, drive_file_id: str) -> bool:
    """True if this file's OCR + issue-detection stages already completed
    (and it isn't marked failed) -- resuming a run can skip straight past
    OCR for it (the OCR cache handles skipping the actual Gemini calls;
    this is the DB-visible status check the resumability requirement asks
    for alongside it)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select ocr_completed_at is not null and issue_detection_completed_at is not null and not failed
            from ingestion_files
            where drive_file_id = %s
            """,
            (drive_file_id,),
        )
        row = cur.fetchone()
        return bool(row and row[0])


def issue_fully_indexed(conn: psycopg.Connection, year: int, month: int) -> bool:
    """True if this issue reached indexed_at (and isn't marked failed) --
    the resumable equivalent of already_ingested(), but keyed purely on
    the issue rather than requiring a specific source drive_file_id."""
    with conn.cursor() as cur:
        cur.execute(
            "select indexed_at is not null and not failed from sampada where year = %s and month = %s",
            (year, month),
        )
        row = cur.fetchone()
        return bool(row and row[0])


def upsert_sampada(
    conn: psycopg.Connection,
    *,
    year: int,
    month: int,
    source_pdf_id: str,
    source_url: Optional[str],
    source_filename: Optional[str] = None,
    publication: str = "Sampada",
    pdf_page_offset: Optional[int] = None,
) -> None:
    """Create the monthly Sampada row before inserting its articles.

    pdf_page_offset is the physical PDF page (0-based, into the source
    file's full page list) where this issue's cover page starts -- from
    IssueBoundary.start_page, already computed by issue-boundary detection.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into sampada
                (year, month, source_pdf_id, source_url, source_filename, publication, pdf_page_offset)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (year, month) do update
            set source_url = coalesce(excluded.source_url, sampada.source_url),
                source_filename = coalesce(excluded.source_filename, sampada.source_filename),
                pdf_page_offset = coalesce(excluded.pdf_page_offset, sampada.pdf_page_offset)
            where sampada.source_pdf_id = excluded.source_pdf_id
            returning source_pdf_id
            """,
            (year, month, source_pdf_id, source_url, source_filename, publication, pdf_page_offset),
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
    issue_page_start: Optional[int] = None,
    issue_page_end: Optional[int] = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into articles
                (year, month, article_index, article_title, author, body,
                 source_url, source_pdf_id, issue_page_start, issue_page_end)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                issue_page_start,
                issue_page_end,
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
    page_numbers: Optional[List[Optional[int]]] = None,
) -> None:
    assert len(chunks) == len(embeddings), "chunk/embedding count mismatch"
    if page_numbers is None:
        page_numbers = [None] * len(chunks)
    assert len(page_numbers) == len(chunks), "page_numbers must have one entry per chunk"
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into smaller_chunks
                (year, month, article_index, chunk_index, content, embedding, issue_page_number)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (year, month, article_index, i, content, embedding, page)
                for i, (content, embedding, page) in enumerate(zip(chunks, embeddings, page_numbers))
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
    issue_page_start: Optional[int] = None,
    issue_page_end: Optional[int] = None,
    word_pages: Optional[List[int]] = None,
) -> int:
    """Inserts one article and its chunks+embeddings. Caller controls the
    transaction (commit/rollback) -- see run_pipeline.process_pdf.

    word_pages, when given, is one issue-relative page number per word of
    article.body (see ingest/page_mapping.py) -- each chunk is then
    attributed to the page its first word came from. Omitting it (the
    default) falls back to plain chunk_text() with no page attribution,
    for callers that don't have page information available.
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
        issue_page_start=issue_page_start,
        issue_page_end=issue_page_end,
    )

    if word_pages is not None:
        chunk_pairs = chunk_text_with_pages(article.body, word_pages)
        chunks = [content for content, _page in chunk_pairs]
        page_numbers = [page for _content, page in chunk_pairs]
    else:
        chunks = chunk_text(article.body)
        page_numbers = None

    if chunks:
        embeddings = embed_texts(chunks, task_type="RETRIEVAL_DOCUMENT")
        insert_smaller_chunks(
            conn,
            year=issue_year,
            month=issue_month_number,
            article_index=article_index,
            chunks=chunks,
            embeddings=embeddings,
            page_numbers=page_numbers,
        )

    return article_id
