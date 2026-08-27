from ingest.db_writer import (
    already_ingested,
    ingested_issue_months,
    insert_article,
    insert_chunks,
    issue_month_source,
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
        if "select drive_file_id from articles where issue_month" in sql:
            matches = [drive_id for drive_id, month in self._conn.existing_drive_ids if month == params[0]]
            self._conn.next_fetchone = (matches[0],) if matches else None
        elif "select 1 from articles" in sql:
            key = (params[0], params[1])
            self._conn.next_fetchone = (1,) if key in self._conn.existing_drive_ids else None
        elif "insert into articles" in sql:
            self._conn.next_id += 1
            self._conn.last_inserted_id = self._conn.next_id

    def executemany(self, sql, seq_of_params):
        params_list = list(seq_of_params)
        self._conn.executed.append((sql.strip(), params_list))
        self._conn.executemany_calls.append(params_list)

    def fetchone(self):
        return self._conn.next_fetchone if hasattr(self._conn, "next_fetchone") else (self._conn.last_inserted_id,)


class _FakeConnection:
    def __init__(self, existing_drive_ids=()):
        self.executed = []
        self.executemany_calls = []
        self.next_id = 0
        self.last_inserted_id = None
        self.existing_drive_ids = set(existing_drive_ids)
        self.committed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True


def test_already_ingested_true_when_drive_id_and_issue_month_present():
    conn = _FakeConnection(existing_drive_ids={("abc123", "2021-06")})
    assert already_ingested(conn, "abc123", "2021-06") is True


def test_already_ingested_false_when_drive_id_absent():
    conn = _FakeConnection(existing_drive_ids={("abc123", "2021-06")})
    assert already_ingested(conn, "not-there", "2021-06") is False


def test_already_ingested_false_for_a_different_issue_bundled_in_the_same_pdf():
    # One PDF can bundle several issues -- ingesting one shouldn't make a
    # different issue_month bundled in that same file look already-done.
    conn = _FakeConnection(existing_drive_ids={("abc123", "2021-06")})
    assert already_ingested(conn, "abc123", "2021-07") is False


def test_issue_month_source_returns_the_owning_drive_file_id():
    conn = _FakeConnection(existing_drive_ids={("abc123", "2021-06")})
    assert issue_month_source(conn, "2021-06") == "abc123"


def test_issue_month_source_none_when_not_ingested_from_anywhere():
    conn = _FakeConnection(existing_drive_ids={("abc123", "2021-06")})
    assert issue_month_source(conn, "2021-07") is None


class _DistinctMonthsCursor:
    def __init__(self, months):
        self._months = months

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        assert "select distinct issue_month from articles" in sql

    def fetchall(self):
        return [(m,) for m in self._months]


class _DistinctMonthsConnection:
    def __init__(self, months):
        self._months = months

    def cursor(self):
        return _DistinctMonthsCursor(self._months)


def test_ingested_issue_months_returns_distinct_months_as_a_set():
    conn = _DistinctMonthsConnection(["2021-06", "2021-07", "2021-06"])
    assert ingested_issue_months(conn) == {"2021-06", "2021-07"}


def test_ingested_issue_months_empty_when_nothing_ingested():
    conn = _DistinctMonthsConnection([])
    assert ingested_issue_months(conn) == set()


def test_insert_article_returns_new_id():
    conn = _FakeConnection()
    article_id = insert_article(
        conn,
        issue_year=2021,
        issue_month_number=6,
        article_index=1,
        issue_month="2021-06",
        article_title="Editorial",
        author="Jane Doe",
        body="Welcome to this issue.",
        source_url="https://example.com/p/sampada-june-2021.html",
        drive_file_id="abc123",
    )
    assert article_id == 1
    sql, params = conn.executed[-1]
    assert "insert into articles" in sql
    assert params == (
        2021,
        6,
        1,
        "2021-06",
        "Editorial",
        "Jane Doe",
        "Welcome to this issue.",
        "https://example.com/p/sampada-june-2021.html",
        "abc123",
    )


def test_insert_article_stores_empty_author_as_null():
    conn = _FakeConnection()
    insert_article(
        conn,
        issue_year=2021,
        issue_month_number=6,
        article_index=1,
        issue_month="2021-06",
        article_title="Editorial",
        author="",
        body="body",
        source_url=None,
        drive_file_id="abc123",
    )
    _, params = conn.executed[-1]
    assert params[5] is None  # author


def test_insert_chunks_writes_one_row_per_chunk_in_order():
    conn = _FakeConnection()
    insert_chunks(conn, article_id=42, chunks=["a", "b", "c"], embeddings=[[0.1], [0.2], [0.3]])

    [params_list] = conn.executemany_calls
    assert params_list == [
        (42, 0, "a", [0.1]),
        (42, 1, "b", [0.2]),
        (42, 2, "c", [0.3]),
    ]


def test_write_article_chunks_embeds_and_inserts(monkeypatch):
    monkeypatch.setattr(
        "ingest.db_writer.embed_texts",
        lambda chunks, task_type: [[0.0] * 1536 for _ in chunks],
    )
    monkeypatch.setattr("ingest.db_writer.chunk_text", lambda body: ["chunk one", "chunk two"])

    conn = _FakeConnection()
    article = Article(title="Editorial", author="Jane Doe", body="Welcome to this issue.")

    article_id = write_article(
        conn,
        article,
        issue_year=2021,
        issue_month_number=6,
        article_index=1,
        issue_month="2021-06",
        source_url=None,
        drive_file_id="abc123",
    )

    assert article_id == 1
    [chunk_params] = conn.executemany_calls
    assert [p[2] for p in chunk_params] == ["chunk one", "chunk two"]


def test_write_article_skips_embedding_when_body_produces_no_chunks(monkeypatch):
    monkeypatch.setattr("ingest.db_writer.chunk_text", lambda body: [])

    def boom(*args, **kwargs):
        raise AssertionError("embed_texts should not be called for zero chunks")

    monkeypatch.setattr("ingest.db_writer.embed_texts", boom)

    conn = _FakeConnection()
    article = Article(title="Empty", author="", body="")
    write_article(
        conn,
        article,
        issue_year=2021,
        issue_month_number=6,
        article_index=1,
        issue_month="2021-06",
        source_url=None,
        drive_file_id="abc123",
    )
    assert conn.executemany_calls == []
