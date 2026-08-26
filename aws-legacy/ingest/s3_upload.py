"""Upload raw PDFs and processed article files to S3. Kept as small,
composable functions so Phase 6's Lambda can reuse them directly.
"""
from pathlib import Path

from .build_index import INDEX_KEY
from .config import CONFIG, require_for_s3


def _client():
    import boto3

    return boto3.client("s3", region_name=CONFIG.aws_region)


def upload_raw_pdf(local_pdf: Path, year: int, month: int, client=None) -> str:
    require_for_s3()
    client = client or _client()
    key = f"{CONFIG.s3_raw_prefix}/{year:04d}/{month:02d}.pdf"
    client.upload_file(str(local_pdf), CONFIG.s3_bucket, key)
    return key


def upload_processed_article(local_txt: Path, client=None) -> tuple:
    """local_txt is expected at .../processed/<year>/<month>/<slug>.txt with a
    sibling <slug>.txt.metadata.json. Returns (txt_key, metadata_key).
    """
    require_for_s3()
    client = client or _client()
    meta_path = local_txt.with_name(local_txt.name + ".metadata.json")

    relative = local_txt.relative_to(CONFIG.local_processed_dir)
    txt_key = f"{CONFIG.s3_processed_prefix}/{relative.as_posix()}"
    meta_key = f"{txt_key}.metadata.json"

    client.upload_file(str(local_txt), CONFIG.s3_bucket, txt_key)
    if meta_path.exists():
        client.upload_file(str(meta_path), CONFIG.s3_bucket, meta_key)
    return txt_key, meta_key


def upload_processed_issue(issue_dir: Path, client=None) -> list:
    client = client or _client()
    return [upload_processed_article(p, client=client) for p in sorted(issue_dir.glob("*.txt"))]


def upload_index(local_index_path: Path, client=None) -> str:
    """INDEX_KEY must match BROWSE_INDEX_KEY in infra/sampada_stack.py --
    that's the one S3 key the app's IAM role is granted read access to.
    """
    require_for_s3()
    client = client or _client()
    client.upload_file(str(local_index_path), CONFIG.s3_bucket, INDEX_KEY)
    return INDEX_KEY
