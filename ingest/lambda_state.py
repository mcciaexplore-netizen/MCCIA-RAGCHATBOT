"""Round-trips Lambda's ephemeral local state (manifest, index, manual
review log) through S3, since /tmp doesn't reliably survive between
invocations. Uses botocore's own NoSuchKey-equivalent (404 ClientError) to
treat "nothing there yet" as the normal first-run case, not an error.
"""
from pathlib import Path

from .build_index import INDEX_KEY
from .config import CONFIG

STATE_PREFIX = "state"


def _client():
    import boto3

    return boto3.client("s3", region_name=CONFIG.aws_region)


def _download_if_exists(key: str, local_path: Path, client) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(CONFIG.s3_bucket, key, str(local_path))
    except client.exceptions.ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
            raise


def _upload_if_exists(key: str, local_path: Path, client) -> None:
    if local_path.exists():
        client.upload_file(str(local_path), CONFIG.s3_bucket, key)


def pull_state(client=None) -> None:
    client = client or _client()
    _download_if_exists(f"{STATE_PREFIX}/processed_manifest.json", CONFIG.state_manifest, client)
    _download_if_exists(f"{STATE_PREFIX}/manual_review.csv", CONFIG.manual_review_log, client)
    _download_if_exists(INDEX_KEY, CONFIG.local_index_path, client)


def push_state(client=None) -> None:
    client = client or _client()
    _upload_if_exists(f"{STATE_PREFIX}/processed_manifest.json", CONFIG.state_manifest, client)
    _upload_if_exists(f"{STATE_PREFIX}/manual_review.csv", CONFIG.manual_review_log, client)
    # index/issues.json is already uploaded by s3_upload.upload_index as
    # part of normal processing -- nothing extra to push here.
