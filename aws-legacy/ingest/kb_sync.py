"""Triggers Bedrock to re-embed newly uploaded articles.

Writing files to S3 does NOT make a Bedrock Knowledge Base re-sync on its
own -- you have to explicitly start an ingestion job. Without this, Phase
1/6 could upload perfectly good articles that never become searchable.
"""
from .config import CONFIG, require_for_kb_sync


def _client():
    import boto3

    # Ingestion job management lives on the bedrock-agent control-plane
    # client, not bedrock-agent-runtime (that's Retrieve/RetrieveAndGenerate).
    return boto3.client("bedrock-agent", region_name=CONFIG.aws_region)


def start_ingestion_job(client=None) -> str:
    """Fire-and-forget: returns the ingestion job ID. Bedrock runs it
    asynchronously; poll get_ingestion_job if you need to wait for it.
    """
    require_for_kb_sync()
    client = client or _client()
    response = client.start_ingestion_job(
        knowledgeBaseId=CONFIG.bedrock_knowledge_base_id,
        dataSourceId=CONFIG.bedrock_data_source_id,
        description="Triggered by ingest.run_pipeline after a processed-article upload",
    )
    return response["ingestionJob"]["ingestionJobId"]
