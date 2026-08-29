"""End-to-end smoke test for `process` (no real Drive/Gemini/Postgres calls):
a synthetic PDF goes in, correctly-dated articles+chunks come out as SQL
statements against a fake connection. Gemini and the DB are stubbed since
they need real credentials.
"""

import json
from unittest.mock import patch

from ingest.detect_issue_boundaries import IssueBoundary, IssueBoundaryError
from ingest.run_pipeline import cmd_all, cmd_check_web, cmd_process
from ingest.split_articles import Article, ArticleSplitError


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
        # mark_file_stage/mark_issue_stage build psycopg.sql.Composed
        # objects (for a safely-whitelisted dynamic column name) rather
        # than plain strings -- normalize either to text.
        sql_text = sql.as_string(None) if hasattr(sql, "as_string") else sql
        sql_norm = sql_text.strip()
        self._conn.executed.append((sql_norm, params))
        if "select source_pdf_id from sampada" in sql_norm:
            issue_month = f"{params[0]:04d}-{params[1]:02d}"
            matches = [drive_id for drive_id, month in self._conn.existing_keys if month == issue_month]
            self._conn.next_fetchone = (matches[0],) if matches else None
        elif "select 1 from sampada" in sql_norm:
            key = (params[0], f"{params[1]:04d}-{params[2]:02d}")
            self._conn.next_fetchone = (1,) if key in self._conn.existing_keys else None
        elif "insert into sampada" in sql_norm:
            self._conn.existing_keys.add((params[2], f"{params[0]:04d}-{params[1]:02d}"))
            self._conn.next_fetchone = (params[2],)
        elif "insert into articles" in sql_norm:
            self._conn.next_id += 1
            self._conn.next_fetchone = (self._conn.next_id,)
        elif "delete from sampada" in sql_norm:
            self._conn.existing_keys.discard((params[0], f"{params[1]:04d}-{params[2]:02d}"))

    def executemany(self, sql, seq_of_params):
        self._conn.executed.append((sql.strip(), list(seq_of_params)))

    def fetchone(self):
        return self._conn.next_fetchone

    def fetchall(self):
        return [tuple(map(int, m.split("-"))) for m in self._conn.ingested_months]


class _FakeConnection:
    def __init__(self, existing_keys=(), ingested_months=()):
        self.executed = []
        self.next_id = 0
        self.next_fetchone = None
        self.existing_keys = set(existing_keys)  # {(drive_file_id, issue_month)}
        self.ingested_months = set(ingested_months)
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


def _patched(fake_conn, issues, new_web_issues=(), pages=("page one",)):
    """`issues` is a list of (IssueBoundary, page_texts, articles-or-exception)
    tuples -- one per issue that split_into_issues() should hand back for
    this PDF. split_issue_into_articles() is driven by a side_effect so each
    detected issue can return its own articles (or raise)."""
    boundaries_and_pages = [(boundary, issue_pages) for boundary, issue_pages, _ in issues]
    split_effects = [
        articles_or_exc for _, _, articles_or_exc in issues
    ]

    return (
        patch("ingest.run_pipeline.connect", return_value=fake_conn),
        patch("ingest.run_pipeline.split_into_issues", return_value=boundaries_and_pages),
        patch("ingest.run_pipeline.split_issue_into_articles", side_effect=split_effects),
        patch("ingest.run_pipeline.lookup_source_url", return_value=None),
        patch("ingest.db_writer.embed_texts", return_value=[[0.0] * 1536]),
        patch("ingest.run_pipeline.check_for_new_issues", return_value=list(new_web_issues)),
        patch("ingest.run_pipeline.get_or_extract_pages", return_value=list(pages)),
    )


def test_process_writes_articles_for_a_single_detected_issue(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "Sampada_June_2021.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"Sampada_June_2021.pdf": "drive-abc123"}')

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=2021, month=6)
    # start_line/end_line default to (0, 0) -- Article.body's word count must
    # match issue_pages[0]'s (page 0 occupies line 0) for the page-mapping
    # word-count invariant word_pages_for_line_range() enforces to hold, the
    # same way it always does for a real Article sliced out of real OCR text.
    articles = [Article(title="Editorial", author="The Editor", body="Welcome to this special issue.")]

    patches = _patched(fake_conn, issues=[(boundary, ["Welcome to this special issue.", "body"], articles)])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert len(insert_calls) == 1
    _, params = insert_calls[0]
    assert params[0] == 2021  # year
    assert params[1] == 6  # month
    assert params[2] == 1  # article_index
    assert params[3] == "Editorial"  # article_title
    assert params[7] == "drive-abc123"  # source_pdf_id
    assert fake_conn.commits == 2  # 1 file-level (ingestion_files) + 1 issue-level


def test_process_assigns_one_based_article_indexes_within_an_issue(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "Sampada_June_2021.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"Sampada_June_2021.pdf": "drive-abc123"}')

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=2021, month=6)
    # All 3 default to start_line=end_line=0 (page 0's line) -- each body
    # is 2 words, so page 0 must also be 2 words for the page-mapping
    # word-count invariant to hold for all three.
    articles = [
        Article(title="Editorial", author="", body="Opening article."),
        Article(title="Industry News", author="", body="Second article."),
        Article(title="Member Notes", author="", body="Third article."),
    ]

    patches = _patched(fake_conn, issues=[(boundary, ["cover page", "body"], articles)])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert [params[0:3] for _, params in insert_calls] == [
        (2021, 6, 1),
        (2021, 6, 2),
        (2021, 6, 3),
    ]


def test_process_writes_every_issue_bundled_in_one_pdf(tmp_path, monkeypatch):
    # The real archive: one PDF routinely bundles multiple issues (e.g. a
    # 1945 file bundling a July 1945 issue and a Dec-Jan 1946 issue). Each
    # detected issue should get its own articles under its own issue_month.
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "1945 July.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"1945 July.pdf": "drive-bound-vol"}')

    fake_conn = _FakeConnection()
    issue_one = (
        IssueBoundary(start_page=0, year=1945, month=7),
        ["cover 1", "body 1"],
        [Article(title="News Roundup", author="", body="July news.")],
    )
    issue_two = (
        IssueBoundary(start_page=2, year=1946, month=1),
        ["cover 2", "body 2"],
        [Article(title="Year End Report", author="", body="Jan news.")],
    )

    patches = _patched(fake_conn, issues=[issue_one, issue_two])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert len(insert_calls) == 2
    issue_coordinates = {params[0:2] for _, params in insert_calls}
    assert issue_coordinates == {(1945, 7), (1946, 1)}
    # 1 file-level commit (ingestion_files: OCR + issue-detection status)
    # + 1 commit per issue -- issue writes still aren't one shared commit
    # for the whole PDF, which is the property this test guards.
    assert fake_conn.commits == 3


def test_process_records_failure_stage_and_rolls_back_when_writing_articles_fails(tmp_path, monkeypatch):
    # OCR/issue-detection/article-splitting all already succeeded (this is
    # deliberately the "resumability after chunking/embedding" case) -- only
    # the DB write step fails, on the second of two articles. The already-
    # committed OCR cache means a retry never re-pays for OCR; this test
    # covers that the failure itself is durably recorded, not silently lost.
    staging = tmp_path / "raw"
    staging.mkdir()
    review_log = tmp_path / "manual_review.csv"
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(review_log))
    (staging / "bound.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"bound.pdf": "drive-bound"}')

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=1950, month=5)
    articles = [
        Article(title="First", author="", body="first body"),
        Article(title="Second", author="", body="second body"),
    ]

    patches = _patched(fake_conn, issues=[(boundary, ["first body", "second body"], articles)])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "ingest.run_pipeline.write_article", side_effect=[1, RuntimeError("embedding quota exceeded")]
    ):
        cmd_process(_Args())

    assert fake_conn.rollbacks == 1

    failure_updates = [e for e in fake_conn.executed if "failed = true" in e[0] and "sampada" in e[0]]
    assert len(failure_updates) == 1
    _, params = failure_updates[0]
    assert params == ("writing", "embedding quota exceeded", 1950, 5)

    # The unhandled exception still propagates to cmd_process's per-PDF
    # catch-all -- one bad file's write failure doesn't crash the whole run.
    assert review_log.exists()
    assert "embedding quota exceeded" in review_log.read_text()


def test_process_one_bad_issue_does_not_block_the_others_in_the_same_pdf(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "bound.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"bound.pdf": "drive-bound"}')

    fake_conn = _FakeConnection()
    good_issue = (
        IssueBoundary(start_page=0, year=1945, month=7),
        ["cover 1", "body 1"],
        [Article(title="News Roundup", author="", body="July news.")],
    )
    bad_issue = (
        IssueBoundary(start_page=2, year=1946, month=1),
        ["cover 2", "body 2"],
        ArticleSplitError("Gemini returned malformed article boundaries twice"),
    )

    patches = _patched(fake_conn, issues=[good_issue, bad_issue])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0][1][0:2] == (1945, 7)


def test_process_logs_manual_review_when_issue_boundaries_undetectable(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    review_log = tmp_path / "manual_review.csv"
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(review_log))
    (staging / "scan_final_v2.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"scan_final_v2.pdf": "drive-xyz"}')

    fake_conn = _FakeConnection()
    patches = list(_patched(fake_conn, issues=[]))
    patches[1] = patch("ingest.run_pipeline.split_into_issues", side_effect=IssueBoundaryError("no cover pages found"))
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    assert review_log.exists()
    assert "scan_final_v2.pdf" in review_log.read_text()
    assert not any("insert into articles" in e[0] for e in fake_conn.executed)
    # 1 commit: the file-level ingestion_files failure record (stage=issue_detection).
    assert fake_conn.commits == 1


def test_process_skips_an_issue_already_in_the_database(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "2019-03.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"2019-03.pdf": "drive-already-here"}')

    fake_conn = _FakeConnection(existing_keys={("drive-already-here", "2019-03")})
    boundary = IssueBoundary(start_page=0, year=2019, month=3)
    articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    patches = _patched(fake_conn, issues=[(boundary, ["cover", "body"], articles)])
    with patches[0], patches[1], patches[2] as fake_split, patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert not any("insert into articles" in e[0] for e in fake_conn.executed)


def test_process_skips_and_flags_an_issue_already_ingested_from_a_different_pdf(tmp_path, monkeypatch):
    # The real archive has overlapping scans (e.g. a standalone Jan issue
    # alongside a Feb-Dec bound volume, or a bound volume split across
    # Part-1/Part-2 files). If a different source PDF already wrote this
    # issue_month, don't double-write it -- skip and log for manual review.
    staging = tmp_path / "raw"
    staging.mkdir()
    review_log = tmp_path / "manual_review.csv"
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(review_log))
    (staging / "2011-Feb To 2011-Dec.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"2011-Feb To 2011-Dec.pdf": "drive-bound-volume"}')

    fake_conn = _FakeConnection(existing_keys={("drive-standalone-jan", "2011-02")})
    boundary = IssueBoundary(start_page=0, year=2011, month=2)
    articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    patches = _patched(fake_conn, issues=[(boundary, ["cover", "body"], articles)])
    with patches[0], patches[1], patches[2] as fake_split, patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert not any("insert into articles" in e[0] for e in fake_conn.executed)
    assert review_log.exists()
    assert "2011-Feb To 2011-Dec.pdf" in review_log.read_text()
    assert "different source PDF" in review_log.read_text()


def test_process_skips_ocr_entirely_for_a_file_already_fully_processed(tmp_path, monkeypatch):
    # Once every issue in a file has resolved, a rerun shouldn't pay for
    # OCR again just to rediscover "yes, still already ingested."
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "2019-03.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"2019-03.pdf": "drive-already-here"}')
    (staging / ".fully_processed.json").write_text('["drive-already-here"]')

    fake_conn = _FakeConnection()
    patches = _patched(fake_conn, issues=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as fake_extract:
        cmd_process(_Args())
        fake_extract.assert_not_called()

    assert fake_conn.executed == []


def test_process_marks_a_file_fully_processed_once_every_issue_resolves(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "1945 July.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"1945 July.pdf": "drive-bound-vol"}')

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=1945, month=7)
    articles = [Article(title="News Roundup", author="", body="July news.")]

    patches = _patched(fake_conn, issues=[(boundary, ["cover page", "body"], articles)])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    marker = json.loads((staging / ".fully_processed.json").read_text())
    assert marker == ["drive-bound-vol"]


def test_process_does_not_mark_a_file_fully_processed_when_an_issue_needs_manual_review(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "bound.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"bound.pdf": "drive-bound"}')

    fake_conn = _FakeConnection()
    good_issue = (
        IssueBoundary(start_page=0, year=1945, month=7),
        ["cover 1", "body 1"],
        [Article(title="News Roundup", author="", body="July news.")],
    )
    bad_issue = (
        IssueBoundary(start_page=2, year=1946, month=1),
        ["cover 2", "body 2"],
        ArticleSplitError("Gemini returned malformed article boundaries twice"),
    )

    patches = _patched(fake_conn, issues=[good_issue, bad_issue])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())

    assert not (staging / ".fully_processed.json").exists()


def test_process_force_reprocesses_and_deletes_only_that_issue(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "2019-03.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"2019-03.pdf": "drive-already-here"}')

    fake_conn = _FakeConnection(existing_keys={("drive-already-here", "2019-03")})
    boundary = IssueBoundary(start_page=0, year=2019, month=3)
    articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    class _ForceArgs:
        force = True

    patches = _patched(fake_conn, issues=[(boundary, ["cover", "body"], articles)])
    with patches[0], patches[1], patches[2] as fake_split, patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_ForceArgs())
        fake_split.assert_called_once()

    delete_calls = [e for e in fake_conn.executed if "delete from sampada" in e[0]]
    assert len(delete_calls) == 1
    assert delete_calls[0][1] == ("drive-already-here", 2019, 3)
    assert any("insert into articles" in e[0] for e in fake_conn.executed)


def test_process_skips_pdf_with_no_drive_id_on_record(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "untracked.pdf").write_bytes(b"")
    # No .drive_ids.json at all -- sync was never run.

    fake_conn = _FakeConnection()
    patches = _patched(fake_conn, issues=[])
    with patches[0], patches[1], patches[2] as fake_split, patches[3], patches[4], patches[5], patches[6]:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert fake_conn.executed == []


def test_process_can_retry_only_selected_failed_files(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "1945 July.PDF").write_bytes(b"")
    (staging / "1946 April.PDF").write_bytes(b"")
    (staging / ".drive_ids.json").write_text(
        '{"1945 July.PDF": "drive-1945", "1946 April.PDF": "drive-1946"}'
    )

    class _SelectedArgs:
        force = False
        files = ["1946 April.PDF"]

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=1946, month=4)
    articles = [Article(title="Editorial", author="", body="April issue.")]
    patches = _patched(fake_conn, issues=[(boundary, ["cover page", "body"], articles)])

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as extract:
        cmd_process(_SelectedArgs())

    extract.assert_called_once_with(staging / "1946 April.PDF", "drive-1946")
    insert_calls = [e for e in fake_conn.executed if "insert into articles" in e[0]]
    assert len(insert_calls) == 1
    assert insert_calls[0][1][0:3] == (1946, 4, 1)


def test_process_can_resume_from_an_exact_sorted_pdf(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    for name in ("1948 May.PDF", "1949 April.PDF"):
        (staging / name).write_bytes(b"")
    (staging / ".drive_ids.json").write_text(
        '{"1948 May.PDF":"drive-1948","1949 April.PDF":"drive-1949"}'
    )

    class _ResumeArgs:
        force = False
        start_at = "1949 April.PDF"

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=1949, month=4)
    articles = [Article(title="Editorial", author="", body="April issue.")]
    patches = _patched(fake_conn, issues=[(boundary, ["cover", "body"], articles)])

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6] as extract:
        cmd_process(_ResumeArgs())

    assert extract.call_args_list[0].args[0] == staging / "1949 April.PDF"
    assert all(call.args[0].name != "1948 May.PDF" for call in extract.call_args_list)


def test_check_web_passes_ingested_months_from_the_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))

    fake_conn = _FakeConnection(ingested_months={"2021-06", "2021-07"})
    patches = _patched(fake_conn, issues=[])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as fake_check, patches[6]:
        cmd_check_web(_Args())

    fake_check.assert_called_once_with({"2021-06", "2021-07"})
    assert fake_conn.executed == [("select year, month from sampada", None)]


def test_all_runs_sync_process_and_check_web_in_order(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    staging.mkdir()
    monkeypatch.setenv("LOCAL_STAGING_DIR", str(staging))
    monkeypatch.setenv("MANUAL_REVIEW_LOG", str(tmp_path / "manual_review.csv"))
    (staging / "2021-06.pdf").write_bytes(b"")
    (staging / ".drive_ids.json").write_text('{"2021-06.pdf": "drive-abc"}')

    fake_conn = _FakeConnection()
    boundary = IssueBoundary(start_page=0, year=2021, month=6)
    articles = [Article(title="Editorial", author="Someone", body="Body text here.")]

    patches = _patched(fake_conn, issues=[(boundary, ["cover", "body"], articles)])
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as fake_check, patches[6], patch(
        "ingest.run_pipeline.sync_all", return_value=[]
    ) as fake_sync:
        cmd_all(_Args())

    fake_sync.assert_called_once()
    assert any("insert into articles" in e[0] for e in fake_conn.executed)
    fake_check.assert_called_once()
