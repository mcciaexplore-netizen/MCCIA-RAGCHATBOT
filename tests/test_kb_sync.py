import pytest

from ingest import config as config_module
from ingest.kb_sync import start_ingestion_job


def test_start_ingestion_job_returns_job_id(monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "bedrock_knowledge_base_id", "kb-123")
    monkeypatch.setattr(config_module.CONFIG, "bedrock_data_source_id", "ds-456")

    class FakeClient:
        def start_ingestion_job(self, **kwargs):
            assert kwargs["knowledgeBaseId"] == "kb-123"
            assert kwargs["dataSourceId"] == "ds-456"
            return {"ingestionJob": {"ingestionJobId": "job-789"}}

    assert start_ingestion_job(client=FakeClient()) == "job-789"


def test_start_ingestion_job_requires_config(monkeypatch):
    monkeypatch.setattr(config_module.CONFIG, "bedrock_knowledge_base_id", "")
    monkeypatch.setattr(config_module.CONFIG, "bedrock_data_source_id", "")

    with pytest.raises(RuntimeError, match="BEDROCK_KNOWLEDGE_BASE_ID"):
        start_ingestion_job(client=object())
