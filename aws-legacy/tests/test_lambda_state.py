from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from ingest import config as config_module
from ingest.lambda_state import pull_state, push_state


def _not_found_error(operation="HeadObject"):
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


class FakeS3Client:
    def __init__(self):
        self.exceptions = type("Exceptions", (), {"ClientError": ClientError})()
        self.downloaded = []
        self.uploaded = []
        self.missing_keys = set()

    def download_file(self, bucket, key, local_path):
        if key in self.missing_keys:
            raise _not_found_error()
        self.downloaded.append((bucket, key, local_path))

    def upload_file(self, local_path, bucket, key):
        self.uploaded.append((local_path, bucket, key))


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "s3_bucket", "test-bucket")


def test_pull_state_downloads_all_three_files_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    client = FakeS3Client()
    pull_state(client=client)

    keys = {key for _, key, _ in client.downloaded}
    assert keys == {"state/processed_manifest.json", "state/manual_review.csv", "index/issues.json"}


def test_pull_state_tolerates_missing_objects_on_first_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    client = FakeS3Client()
    client.missing_keys = {"state/processed_manifest.json", "state/manual_review.csv", "index/issues.json"}

    pull_state(client=client)  # should not raise

    assert client.downloaded == []


def test_pull_state_reraises_non_404_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "state_manifest", tmp_path / "manifest.json")
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", tmp_path / "manual_review.csv")
    monkeypatch.setattr(config_module.CONFIG, "local_index_path", tmp_path / "index" / "issues.json")

    client = MagicMock()
    client.exceptions.ClientError = ClientError
    client.download_file.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject"
    )

    with pytest.raises(ClientError):
        pull_state(client=client)


def test_push_state_only_uploads_files_that_exist_locally(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    review_log = tmp_path / "manual_review.csv"  # deliberately not created

    monkeypatch.setattr(config_module.CONFIG, "state_manifest", manifest)
    monkeypatch.setattr(config_module.CONFIG, "manual_review_log", review_log)

    client = FakeS3Client()
    push_state(client=client)

    keys = {key for _, _, key in client.uploaded}
    assert keys == {"state/processed_manifest.json"}
