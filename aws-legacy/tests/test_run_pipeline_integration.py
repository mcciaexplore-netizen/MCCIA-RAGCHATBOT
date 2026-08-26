"""End-to-end smoke test for the local part of Phase 1 (no AWS/Google calls):
a synthetic PDF goes in, correctly-dated article .txt/.metadata.json files
come out. The Bedrock call is stubbed since it needs real credentials.
"""
import json
from unittest.mock import patch

import pymupdf

from ingest import config as config_module
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
    upload = False
    force = False


def test_process_writes_dated_articles_from_synthetic_pdf(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    processed = tmp_path / "processed"
    staging.mkdir()

    _make_pdf(
        staging / "Sampada_June_2021.pdf",
        [
            "SAMPADA\nJune 2021",
            "Editorial\nBy The Editor\nWelcome to this special issue on robotics.",
        ],
    )

    monkeypatch.setattr(config_module.CONFIG, "local_staging_dir", staging)
    monkeypatch.setattr(config_module.CONFIG, "local_processed_dir", processed)
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    fake_articles = [Article(title="Editorial", author="The Editor", body="Welcome to this special issue on robotics.")]
    with patch("ingest.run_pipeline.split_issue_into_articles", return_value=fake_articles):
        cmd_process(_Args())

    issue_dir = processed / "2021" / "06"
    assert (issue_dir / "editorial.txt").exists()
    meta = json.loads((issue_dir / "editorial.txt.metadata.json").read_text())
    assert meta["metadataAttributes"]["issue_month"] == "2021-06"
    assert meta["metadataAttributes"]["article_title"] == "Editorial"

    index = json.loads((tmp_path / "index" / "issues.json").read_text())
    assert index["issues"] == [
        {
            "year": 2021,
            "month": 6,
            "issueMonth": "2021-06",
            "label": "June 2021",
            "articles": [{"title": "Editorial", "slug": "editorial", "sourceUrl": ""}],
        }
    ]


def test_process_logs_manual_review_when_date_undetectable(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    processed = tmp_path / "processed"
    review_log = tmp_path / "manual_review.csv"
    staging.mkdir()

    _make_pdf(staging / "scan_final_v2.pdf", ["no date anywhere on this cover"])

    monkeypatch.setattr(config_module.CONFIG, "local_staging_dir", staging)
    monkeypatch.setattr(config_module.CONFIG, "local_processed_dir", processed)
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", review_log)
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    with patch("ingest.run_pipeline.split_issue_into_articles") as fake_split:
        cmd_process(_Args())
        fake_split.assert_not_called()

    assert review_log.exists()
    assert "scan_final_v2.pdf" in review_log.read_text()
    assert not processed.exists()


def test_process_skips_unchanged_pdf_on_second_run(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    processed = tmp_path / "processed"
    staging.mkdir()
    _make_pdf(staging / "2019-03.pdf", ["Editorial\nBy Someone\nBody text here."])

    monkeypatch.setattr(config_module.CONFIG, "local_staging_dir", staging)
    monkeypatch.setattr(config_module.CONFIG, "local_processed_dir", processed)
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    fake_articles = [Article(title="Editorial", author="Someone", body="Body text here.")]
    with patch("ingest.run_pipeline.split_issue_into_articles", return_value=fake_articles) as fake_split:
        cmd_process(_Args())
        assert fake_split.call_count == 1
        cmd_process(_Args())  # second run, PDF unchanged
        assert fake_split.call_count == 1  # not called again


class _UploadArgs:
    upload = True
    force = False


def test_process_with_upload_triggers_one_kb_ingestion_job(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    processed = tmp_path / "processed"
    staging.mkdir()
    _make_pdf(staging / "2021-06.pdf", ["Editorial\nBy Someone\nBody text here."])
    _make_pdf(staging / "2021-07.pdf", ["Editorial\nBy Someone\nMore body text."])

    monkeypatch.setattr(config_module.CONFIG, "local_staging_dir", staging)
    monkeypatch.setattr(config_module.CONFIG, "local_processed_dir", processed)
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    fake_articles = [Article(title="Editorial", author="Someone", body="Body text here.")]
    with (
        patch("ingest.run_pipeline.split_issue_into_articles", return_value=fake_articles),
        patch("ingest.s3_upload.upload_raw_pdf"),
        patch("ingest.s3_upload.upload_processed_issue"),
        patch("ingest.s3_upload.upload_index"),
        patch("ingest.kb_sync.start_ingestion_job", return_value="job-1") as fake_kb_sync,
    ):
        cmd_process(_UploadArgs())

    # One ingestion job for the whole run, not one per uploaded PDF.
    fake_kb_sync.assert_called_once()


def test_process_without_upload_never_triggers_kb_sync(tmp_path, monkeypatch):
    staging = tmp_path / "raw"
    processed = tmp_path / "processed"
    staging.mkdir()
    _make_pdf(staging / "2021-06.pdf", ["Editorial\nBy Someone\nBody text here."])

    monkeypatch.setattr(config_module.CONFIG, "local_staging_dir", staging)
    monkeypatch.setattr(config_module.CONFIG, "local_processed_dir", processed)
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    fake_articles = [Article(title="Editorial", author="Someone", body="Body text here.")]
    with (
        patch("ingest.run_pipeline.split_issue_into_articles", return_value=fake_articles),
        patch("ingest.kb_sync.start_ingestion_job") as fake_kb_sync,
    ):
        cmd_process(_Args())

    fake_kb_sync.assert_not_called()
