"""Central configuration for the Sampada ingestion pipeline.

All values come from environment variables (loaded from .env via python-dotenv)
so the same code runs locally, in a Lambda (Phase 6), or in CI.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    aws_region: str = _env("AWS_REGION", "ap-south-1")
    s3_bucket: str = _env("S3_BUCKET", "")
    s3_raw_prefix: str = _env("S3_RAW_PREFIX", "raw")
    s3_processed_prefix: str = _env("S3_PROCESSED_PREFIX", "processed")

    # Must be a "global." cross-region inference profile ID -- Claude has no
    # native in-region hosting in ap-south-1. Verify the exact ID for your
    # account with: aws bedrock list-inference-profiles --region ap-south-1
    bedrock_article_split_model_id: str = _env("BEDROCK_ARTICLE_SPLIT_MODEL_ID", "")

    google_service_account_file: str = _env("GOOGLE_SERVICE_ACCOUNT_FILE", "./secrets/drive-service-account.json")
    google_drive_root_folder_id: str = _env("GOOGLE_DRIVE_ROOT_FOLDER_ID", "")
    # Only set inside the Phase 6 Lambda -- local/dev runs use
    # GOOGLE_SERVICE_ACCOUNT_FILE directly instead. See lambda_handler.py.
    google_drive_credentials_secret_arn: str = _env("GOOGLE_DRIVE_CREDENTIALS_SECRET_ARN", "")

    # Set once infra/sampada_stack.py is deployed (KnowledgeBaseId /
    # DataSourceId outputs) -- lets run_pipeline trigger re-embedding after
    # an upload. Uploading to S3 alone does NOT make Bedrock re-sync.
    bedrock_knowledge_base_id: str = _env("BEDROCK_KNOWLEDGE_BASE_ID", "")
    bedrock_data_source_id: str = _env("BEDROCK_DATA_SOURCE_ID", "")

    # Phase 6: supplementary check against the web archive for issues that
    # don't have a matching entry in our own index yet.
    web_archive_base_url: str = _env("WEB_ARCHIVE_BASE_URL", "https://www.mcciapunesampada.com")

    local_staging_dir: Path = Path(_env("LOCAL_STAGING_DIR", "./staging/raw"))
    local_processed_dir: Path = Path(_env("LOCAL_PROCESSED_DIR", "./staging/processed"))
    local_index_path: Path = Path(_env("LOCAL_INDEX_PATH", "./staging/index/issues.json"))
    manual_review_log: Path = Path(_env("MANUAL_REVIEW_LOG", "./staging/manual_review.csv"))
    state_manifest: Path = Path(_env("STATE_MANIFEST", "./staging/processed_manifest.json"))


CONFIG = Config()


def require_for_bedrock() -> None:
    if not CONFIG.bedrock_article_split_model_id:
        raise RuntimeError(
            "BEDROCK_ARTICLE_SPLIT_MODEL_ID is not set. Run "
            "`aws bedrock list-inference-profiles --region ap-south-1` and set it "
            "to a global.anthropic.claude-* inference profile ID."
        )


def require_for_s3() -> None:
    if not CONFIG.s3_bucket:
        raise RuntimeError(
            "S3_BUCKET is not set. Bucket names are globally unique across all of "
            "AWS -- pick a real name (e.g. mccia-sampada-archive-<something unique>) "
            "and confirm it's free before creating it."
        )


def require_for_kb_sync() -> None:
    if not CONFIG.bedrock_knowledge_base_id or not CONFIG.bedrock_data_source_id:
        raise RuntimeError(
            "BEDROCK_KNOWLEDGE_BASE_ID / BEDROCK_DATA_SOURCE_ID are not set. "
            "Take these from infra/sampada_stack.py's KnowledgeBaseId / "
            "DataSourceId outputs."
        )


def require_for_drive() -> None:
    if not CONFIG.google_drive_root_folder_id:
        raise RuntimeError("GOOGLE_DRIVE_ROOT_FOLDER_ID is not set.")
    if not Path(CONFIG.google_service_account_file).exists():
        raise RuntimeError(
            f"Google service account file not found at "
            f"{CONFIG.google_service_account_file}. Create a service account, "
            f"download its JSON key, and share the Drive folder with its "
            f"client_email as a Viewer."
        )
