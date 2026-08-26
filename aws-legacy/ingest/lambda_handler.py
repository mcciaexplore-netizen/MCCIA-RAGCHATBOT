"""Phase 6 entry point: EventBridge invokes this on a schedule to keep the
archive current. See infra/sampada_stack.py for the schedule + IAM role.

Lambda's /tmp doesn't reliably survive between invocations, so this pulls
prior state (manifest, index, manual review log) from S3 before running the
normal Phase 1 pipeline, and pushes it back after -- everything in between
is exactly the same code path `python -m ingest.run_pipeline all --upload`
already uses locally, just pointed at /tmp instead of ./staging.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from .build_index import load_index
from .check_web_archive import check_for_new_issues
from .config import CONFIG
from .lambda_state import pull_state, push_state
from .run_pipeline import cmd_all


def _load_drive_credentials_from_secret(client=None) -> None:
    """Writes the Drive service account JSON (kept in Secrets Manager, not
    baked into the deployment package) to where drive_sync.py expects it.
    """
    secret_arn = CONFIG.google_drive_credentials_secret_arn
    if not secret_arn:
        raise RuntimeError("GOOGLE_DRIVE_CREDENTIALS_SECRET_ARN is not set")

    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=CONFIG.aws_region)

    secret = client.get_secret_value(SecretId=secret_arn)
    path = Path(CONFIG.google_service_account_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(secret["SecretString"])


def handler(event, context):
    _load_drive_credentials_from_secret()
    pull_state()

    cmd_all(SimpleNamespace(upload=True, force=False))

    push_state()

    index = load_index(CONFIG.local_index_path)
    new_web_issues = check_for_new_issues(index)

    return {"newWebIssuesFound": [issue.issue_month for issue in new_web_issues]}


if __name__ == "__main__":
    print(json.dumps(handler({}, None)))
