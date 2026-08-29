import pytest

from ingest.db_writer import (
    _parse_issue_month,
    already_ingested,
    file_fully_ocrd,
    ingested_issue_months,
    insert_article,
    insert_smaller_chunks,
    issue_fully_indexed,
    issue_month_source,
    mark_file_stage,
    mark_issue_stage,
    record_file_failure,
    record_issue_failure,
    set_ocr_required,
    upsert_ingestion_file,
    upsert_sampada,
    write_article,
)
from ingest.split_articles import Article


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql.strip(), params))
        if "select source_pdf_id from sampada" in sql:
            issue_month = f"{params[0]:04d}-{params[1]:02d}"
            matches = [drive_id for drive_id, month in self._conn.existing_keys if month == issue_month]
            self._conn.next_fetchone = (matches[0],) if matches else None
        elif "select 1 from sampada" in sql:
            key = (params[0], f"{params[1]:04d}-{params[2]:02d}")
            self._conn.next_fetchone = (1,) if key in self._conn.existing_keys else None
        elif "insert into articles" in sql:
            self._conn.next_id += 1
            self._conn.next_fetchone = (self._conn.next_id,)
        elif "insert into sampada" in sql:
            self._conn.next_fetchone = (params[2],)

    def executemany(self, sql, seq_of_params):
        params_list = list(seq_of_params)
        self._conn.executed.append((sql.strip(), params_list))
        self._conn.executemany_calls.append(params_list)

    def fetchone(self):
        return self._conn.next_fetchone


class _FakeConnection:
    def __init__(self, existing_keys=()):
        self.executed = []
        self.executemany_calls = []
        self.next_id = 0
        self.next_fetchone = None
        self.existing_keys = set(existing_keys)

    def cursor(self):
        return _FakeCursor(self)


def test_parse_issue_month_returns_numeric_coordinates():
    assert _parse_issue_month("2011-06") == (2011, 6)


@pytest.mark.parametrize("value", ["2011-00", "2011-13", "June-2011", "2011-6"])
def test_parse_issue_month_rejects_invalid_coordinates(value):
    with pytest.raises((ValueError, TypeError)):
        _parse_issue_month(value)


def test_already_ingested_is_scoped_to_pdf_year_and_month():
    conn = _FakeConnection(existing_keys={("abc123", "2011-06")})
    assert already_ingested(conn, "abc123", "2011-06") is True
    assert already_ingested(conn, "abc123", "2011-07") is False
    assert already_ingested(conn, "different-pdf", "2011-06") is False


def test_issue_month_source_returns_the_owning_pdf():
    conn = _FakeConnection(existing_keys={("abc123", "2011-06")})
    assert issue_month_source(conn, "2011-06") == "abc123"
    assert issue_month_source(conn, "2011-07") is None


class _IssueCoordinatesCursor:
    def __init__(self, coordinates):
        self._coordinates = coordinates

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        assert "select year, month from sampada" in sql

    def fetchall(self):
        return self._coordinates


class _IssueCoordinatesConnection:
    def __init__(self, coordinates):
        self._coordinates = coordinates

    def cursor(self):
        return _IssueCoordinatesCursor(self._coordinates)


def test_ingested_issue_months_formats_numeric_coordinates():
    conn = _IssueCoordinatesConnection([(1945, 7), (2011, 1)])
    assert ingested_issue_months(conn) == {"1945-07", "2011-01"}


def test_ingested_issue_months_empty_when_nothing_ingested():
    assert ingested_issue_months(_IssueCoordinatesConnection([])) == set()


def test_upsert_sampada_writes_the_monthly_parent_row():
    conn = _FakeConnection()
    upsert_sampada(
        conn,
        year=1945,
        month=7,
        source_pdf_id="drive-1945",
        source_url=None,
    )
    sql, params = conn.executed[-1]
    assert "insert into sampada" in sql
    assert "on conflict (year, month) do update" in sql
    assert "where sampada.source_pdf_id = excluded.source_pdf_id" in sql
    assert params == (1945, 7, "drive-1945", None, None, "Sampada", None)


def test_insert_article_returns_id_and_writes_chronological_coordinates():
    conn = _FakeConnection()
    article_id = insert_article(
        conn,
        issue_year=1945,
        issue_month_number=7,
        article_index=1,
        article_title="Editorial",
        author="Jane Doe",
        body="Welcome to this issue.",
        source_url=None,
        drive_file_id="drive-1945",
    )
    assert article_id == 1
    sql, params = conn.executed[-1]
    assert "insert into articles" in sql
    assert params == (
        1945,
        7,
        1,
        "Editorial",
        "Jane Doe",
        "Welcome to this issue.",
        None,
        "drive-1945",
        None,
        None,
    )


def test_insert_article_stores_empty_author_as_null():
    conn = _FakeConnection()
    insert_article(
        conn,
        issue_year=1945,
        issue_month_number=7,
        article_index=1,
        article_title="Editorial",
        author="",
        body="body",
        source_url=None,
        drive_file_id="drive-1945",
    )
    _, params = conn.executed[-1]
    assert params[4] is None


def test_insert_smaller_chunks_writes_full_vector_coordinates_in_order():
    conn = _FakeConnection()
    insert_smaller_chunks(
        conn,
        year=1945,
        month=7,
        article_index=2,
        chunks=["a", "b"],
        embeddings=[[0.1], [0.2]],
    )
    [params_list] = conn.executemany_calls
    assert params_list == [
        (1945, 7, 2, 0, "a", [0.1], None),
        (1945, 7, 2, 1, "b", [0.2], None),
    ]


def test_insert_smaller_chunks_writes_page_numbers_when_given():
    conn = _FakeConnection()
    insert_smaller_chunks(
        conn,
        year=1945,
        month=7,
        article_index=2,
        chunks=["a", "b"],
        embeddings=[[0.1], [0.2]],
        page_numbers=[3, 4],
    )
    [params_list] = conn.executemany_calls
    assert params_list == [
        (1945, 7, 2, 0, "a", [0.1], 3),
        (1945, 7, 2, 1, "b", [0.2], 4),
    ]


def test_insert_smaller_chunks_rejects_mismatched_page_numbers_length():
    conn = _FakeConnection()
    with pytest.raises(AssertionError):
        insert_smaller_chunks(
            conn,
            year=1945,
            month=7,
            article_index=2,
            chunks=["a", "b"],
            embeddings=[[0.1], [0.2]],
            page_numbers=[3],
        )


def test_write_article_chunks_embeds_and_inserts(monkeypatch):
    monkeypatch.setattr(
        "ingest.db_writer.embed_texts",
        lambda chunks, task_type: [[0.0] * 1536 for _ in chunks],
    )
    monkeypatch.setattr("ingest.db_writer.chunk_text", lambda body: ["chunk one", "chunk two"])

    conn = _FakeConnection()
    article_id = write_article(
        conn,
        Article(title="Editorial", author="Jane Doe", body="Welcome."),
        issue_year=1945,
        issue_month_number=7,
        article_index=1,
        source_url=None,
        drive_file_id="drive-1945",
    )
    assert article_id == 1
    [chunk_params] = conn.executemany_calls
    assert [p[0:5] for p in chunk_params] == [
        (1945, 7, 1, 0, "chunk one"),
        (1945, 7, 1, 1, "chunk two"),
    ]


def test_write_article_attributes_pages_when_word_pages_given(monkeypatch):
    monkeypatch.setattr(
        "ingest.db_writer.embed_texts",
        lambda chunks, task_type: [[0.0] * 1536 for _ in chunks],
    )
    conn = _FakeConnection()
    body = "one two three four five"
    word_pages = [7, 7, 7, 8, 8]  # first 3 words on page 7, last 2 on page 8

    write_article(
        conn,
        Article(title="Editorial", author="Jane Doe", body=body),
        issue_year=1945,
        issue_month_number=7,
        article_index=1,
        source_url=None,
        drive_file_id="drive-1945",
        issue_page_start=7,
        issue_page_end=8,
        word_pages=word_pages,
    )

    insert_article_call = next(e for e in conn.executed if "insert into articles" in e[0])
    _, params = insert_article_call
    assert params[-2:] == (7, 8)  # issue_page_start, issue_page_end

    [chunk_params] = conn.executemany_calls
    # short body -> single chunk -> attributed to its first word's page (7)
    assert chunk_params[0][-1] == 7


def test_write_article_skips_embedding_when_body_has_no_chunks(monkeypatch):
    monkeypatch.setattr("ingest.db_writer.chunk_text", lambda body: [])
    monkeypatch.setattr(
        "ingest.db_writer.embed_texts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected embedding")),
    )
    conn = _FakeConnection()
    write_article(
        conn,
        Article(title="Empty", author="", body=""),
        issue_year=1945,
        issue_month_number=7,
        article_index=1,
        source_url=None,
        drive_file_id="drive-1945",
    )
    assert conn.executemany_calls == []


# --- Ingestion status / resumability ------------------------------------


class _StatusCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql_obj, params=None):
        text = sql_obj.as_string(None) if hasattr(sql_obj, "as_string") else sql_obj
        self._conn.executed.append((text.strip(), params))
        if "select" in text and "ingestion_files" in text:
            self._conn.next_fetchone = self._conn.file_status.get(params[0])
        elif "select" in text and "sampada" in text:
            self._conn.next_fetchone = self._conn.issue_status.get((params[0], params[1]))

    def fetchone(self):
        return self._conn.next_fetchone


class _StatusConnection:
    """file_status: drive_file_id -> (bool,) row for the fully-ocrd query.
    issue_status: (year, month) -> (bool,) row for the fully-indexed query."""

    def __init__(self, file_status=None, issue_status=None):
        self.executed = []
        self.next_fetchone = None
        self.file_status = file_status or {}
        self.issue_status = issue_status or {}

    def cursor(self):
        return _StatusCursor(self)


def test_upsert_ingestion_file_inserts_with_on_conflict_refresh():
    conn = _StatusConnection()
    upsert_ingestion_file(conn, drive_file_id="drive-1", filename="a.pdf", file_size=100, drive_modified_time="2026-01-01")
    sql_text, params = conn.executed[-1]
    assert "insert into ingestion_files" in sql_text
    assert "on conflict (drive_file_id) do update" in sql_text
    assert params == ("drive-1", "a.pdf", 100, "2026-01-01")


def test_mark_file_stage_rejects_unknown_column():
    conn = _StatusConnection()
    with pytest.raises(ValueError):
        mark_file_stage(conn, "drive-1", "not_a_real_column")


def test_mark_file_stage_updates_the_named_column():
    conn = _StatusConnection()
    mark_file_stage(conn, "drive-1", "ocr_completed_at")
    sql_text, params = conn.executed[-1]
    assert '"ocr_completed_at" = now()' in sql_text
    assert params == ("drive-1",)


def test_set_ocr_required_writes_boolean():
    conn = _StatusConnection()
    set_ocr_required(conn, "drive-1", True)
    sql_text, params = conn.executed[-1]
    assert "ocr_required" in sql_text
    assert params == (True, "drive-1")


def test_record_file_failure_writes_stage_and_reason():
    conn = _StatusConnection()
    record_file_failure(conn, "drive-1", "ocr", "Gemini timed out")
    sql_text, params = conn.executed[-1]
    assert "failed = true" in sql_text
    assert params == ("ocr", "Gemini timed out", "drive-1")


def test_mark_issue_stage_rejects_unknown_column():
    conn = _StatusConnection()
    with pytest.raises(ValueError):
        mark_issue_stage(conn, 1945, 7, "not_a_real_column")


def test_mark_issue_stage_updates_the_named_column():
    conn = _StatusConnection()
    mark_issue_stage(conn, 1945, 7, "indexed_at")
    sql_text, params = conn.executed[-1]
    assert '"indexed_at" = now()' in sql_text
    assert params == (1945, 7)


def test_record_issue_failure_writes_stage_and_reason():
    conn = _StatusConnection()
    record_issue_failure(conn, 1945, 7, "embedding", "Gemini quota exceeded")
    sql_text, params = conn.executed[-1]
    assert "failed = true" in sql_text
    assert params == ("embedding", "Gemini quota exceeded", 1945, 7)


def test_file_fully_ocrd_true_when_ocr_and_issue_detection_done_and_not_failed():
    conn = _StatusConnection(file_status={"drive-1": (True,)})
    assert file_fully_ocrd(conn, "drive-1") is True


def test_file_fully_ocrd_false_when_no_row_or_incomplete_or_failed():
    conn = _StatusConnection(file_status={"drive-1": (False,)})
    assert file_fully_ocrd(conn, "drive-1") is False
    conn_missing = _StatusConnection()
    assert file_fully_ocrd(conn_missing, "never-seen") is False


def test_issue_fully_indexed_true_when_indexed_and_not_failed():
    conn = _StatusConnection(issue_status={(1945, 7): (True,)})
    assert issue_fully_indexed(conn, 1945, 7) is True


def test_issue_fully_indexed_false_when_not_yet_or_failed():
    conn = _StatusConnection(issue_status={(1945, 7): (False,)})
    assert issue_fully_indexed(conn, 1945, 7) is False
    conn_missing = _StatusConnection()
    assert issue_fully_indexed(conn_missing, 1999, 1) is False
