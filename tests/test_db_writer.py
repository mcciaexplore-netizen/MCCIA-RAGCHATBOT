import pytest

from ingest.db_writer import (
    _parse_issue_month,
    already_ingested,
    ingested_issue_months,
    insert_article,
    insert_smaller_chunks,
    issue_month_source,
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
    assert params == (1945, 7, "drive-1945", None)


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
        (1945, 7, 2, 0, "a", [0.1]),
        (1945, 7, 2, 1, "b", [0.2]),
    ]


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
