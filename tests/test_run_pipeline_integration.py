"""End-to-end smoke test for `process` (no real Drive/Gemini/Postgres calls):
a synthetic PDF goes in, correctly-dated articles+chunks come out as SQL
statements against a fake connection. Gemini and the DB are stubbed since
they need real credentials.
"""

from unittest.mock import patch

import pymupdf

from ingest.run_pipeline import cmd_process
from ingest.split_articles import Article


def _make_pdf(path, pages_text):
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 100), text)
    doc.save(path)
    doc.close()


class _Args:
    force = False


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        sql_norm = sql.strip()
        self._conn.executed.append((sql_norm, params))
        if "select 1 from articles" in sql_norm:
            self._conn.next_fetchone = (1,) if params[0] in self._conn.existing_drive_ids else None
        elif "insert into articles" in sql_norm:
            self._conn.next_id += 1
            self._conn.next_fetchone = (self._conn.next_id,)
        elif "delete from articles" in sql_norm:
            self._conn.existing_drive_ids.discard(params[0])

    def executemany(self, sql, seq_of_params):
        self._conn.executed.append((sql.strip(), list(seq_of_params)))

    def fetchone(self):
        return self._conn.next_fetchone


class _FakeConnection:
    def __init__(self, existing_drive_ids=()):
        self.executed = []
        self.next_id = 0
        self.next_fetchone = None
        self.existing_drive_ids = set(existing_drive_ids)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _patched(fake_conn, articles):
    return (
        patch("ingest.run_pipeline.connect", return_value=fake_conn),
        patch("ingest.run_pipeline.split_issue_into_articles", return_value=articles),
        patch("ingest.run_pipeline.lookup_source_url", return_value=None),
        patch("ingest.db_writer.embed_texts", return_value=[[0.0] * 1536]),
    )


def test_process_writes_dated_articles_from_synthetic_pdf(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))

    _make_pdf(
        staging / "Sampada_June_2021.pdf",
        [
            "SAMPADA\nJune 2021",
            "Editorial\nBy The Editor\nWelcome to this special issue on robotics.",
        ],
    )
    (staging / ".drive_ids.json").write_text('{"Sampada_June_2021.pdf": "drive-abc123"}')

    fake_conn = _FakeConnection()
    fake_articles = [Article(title="Editorial", author="The Editor", body="Welcome to this special issue on robotics.")]

    p1, p2, p3, p4 = _patched(fake_conn, fake_articles)
    with p1, p2, p3, p4:
        cmd_process(_Args())

    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert len(insert_calls) == 1
    _, params = insert_calls[0]
    assert params[0] == "2021-06"  # issue_month
    assert params[1] == 2021  # issue_year
    assert params[2] == "Editorial"  # article_title
    assert params[6] == "drive-abc123"  # drive_file_id
    assert fake_conn.commits == 1


def test_process_logs_manual_review_when_date_undetectable(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    review_log = tmp_path / "manual_review.csv"
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(review_log))

    _make_pdf(staging / "scan_final_v2.pdf", ["no date anywhere on this cover"])
    (staging / ".drive_ids.json").write_text('{"scan_final_v2.pdf": "drive-xyz"}')

    fake_conn = _FakeConnection()
    p1, p2, p3, p4 = _patched(fake_conn, [])
    with p1, p2 as fake_split, p3, p4:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert review_log.exists()
    assert "scan_final_v2.pdf" in review_log.read_text()
    # The resumability check (a SELECT) runs before date detection, but
    # nothing should ever get written for a PDF whose date we can't trust.
    assert not any("insert into articles" in e[0] for e in fake_conn.executed)
    assert fake_conn.commits == 0


def test_process_skips_pdf_already_in_database(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))

    _make_pdf(staging / "2019-03.pdf", ["Editorial\nBy Someone\nBody text here."])
    (staging / ".drive_ids.json").write_text('{"2019-03.pdf": "drive-already-here"}')

    fake_conn = _FakeConnection(existing_drive_ids={"drive-already-here"})
    fake_articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    p1, p2, p3, p4 = _patched(fake_conn, fake_articles)
    with p1, p2 as fake_split, p3, p4:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert not any("insert into articles" in e[0] for e in fake_conn.executed)


def test_process_force_reprocesses_and_deletes_old_rows(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))

    _make_pdf(staging / "2019-03.pdf", ["Editorial\nBy Someone\nBody text here."])
    (staging / ".drive_ids.json").write_text('{"2019-03.pdf": "drive-already-here"}')

    fake_conn = _FakeConnection(existing_drive_ids={"drive-already-here"})
    fake_articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    class _ForceArgs:
        force = True

    p1, p2, p3, p4 = _patched(fake_conn, fake_articles)
    with p1, p2 as fake_split, p3, p4:
        cmd_process(_ForceArgs())
        fake_split.assert_called_once()

    assert any("delete from articles" in e[0] for e in fake_conn.executed)
    assert any("insert into articles" in e[0] for e in fake_conn.executed)


def test_process_skips_pdf_with_no_drive_id_on_record(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))

    _make_pdf(staging / "untracked.pdf", ["Editorial\nBy Someone\nJune 2021 body text."])
    # No .drive_ids.json at all -- sync was never run.

    fake_conn = _FakeConnection()
    p1, p2, p3, p4 = _patched(fake_conn, [])
    with p1, p2 as fake_split, p3, p4:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert fake_conn.executed == []
