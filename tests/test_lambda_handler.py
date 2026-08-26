from unittest.mock import patch

import pytest

from ingest import config as config_module
from ingest.check_web_archive import WebIssue
from ingest.lambda_handler import _load_drive_credentials_from_secret, handler


def test_load_drive_credentials_writes_secret_to_configured_path(tmp_path, monkeypatch):
    dest = tmp_path / "drive-service-account.json"
    monkeypatch.setattr(config_module.CONFIG, "google_service_account_file", str(dest))
    monkeypatch.setattr(
        config_module.CONFIG, "google_drive_credentials_secret_arn", "arn:aws:secretsmanager:...:drive"
    )

    class FakeSecretsClient:
        def get_secret_value(self, SecretId):
            assert SecretId == "arn:aws:secretsmanager:...:drive"
            return {"SecretString": '{"type": "service_account"}'}

    _load_drive_credentials_from_secret(client=FakeSecretsClient())

    assert dest.read_text() == '{"type": "service_account"}'


def test_load_drive_credentials_requires_secret_arn(monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "google_drive_credentials_secret_arn", "")

    with pytest.raises(RuntimeError, match="GOOGLE_DRIVE_CREDENTIALS_SECRET_ARN"):
        _load_drive_credentials_from_secret(client=object())


def test_handler_runs_full_cycle_and_reports_new_web_issues():
    with (
        patch("ingest.lambda_handler._load_drive_credentials_from_secret") as fake_creds,
        patch("ingest.lambda_handler.pull_state") as fake_pull,
        patch("ingest.lambda_handler.cmd_all") as fake_cmd_all,
        patch("ingest.lambda_handler.push_state") as fake_push,
        patch("ingest.lambda_handler.load_index", return_value={"2021-06": {}}) as fake_load_index,
        patch(
            "ingest.lambda_handler.check_for_new_issues",
            return_value=[WebIssue(2026, 7, "2026-07", "SAMPADA JULY 2026", "https://example.com")],
        ) as fake_check,
    ):
        result = handler({}, None)

    fake_creds.assert_called_once()
    fake_pull.assert_called_once()
    fake_push.assert_called_once()
    fake_load_index.assert_called_once()
    fake_check.assert_called_once_with({"2021-06": {}})

    # Ordering matters: credentials + state must be ready before cmd_all runs,
    # and state must be pushed back before we report and exit.
    assert fake_creds.call_count == 1
    assert fake_cmd_all.call_args.args[0].upload is True
    assert fake_cmd_all.call_args.args[0].force is False

    assert result == {"newWebIssuesFound": ["2026-07"]}
