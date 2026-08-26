# Archived: AWS/Bedrock pipeline

This is the original ingestion pipeline and CDK infrastructure, built around
S3 + Bedrock Knowledge Bases + Bedrock Converse. It was never run against
real AWS credentials (see the original top-level README, preserved in git
history at the commit before this move).

Superseded by the Gemini + Neon Postgres/pgvector pipeline described in the
top-level README. Kept here for reference in case any of it is useful later
(the migration note in the original spec calls out swapping Neon pgvector
for Aurora pgvector or a Bedrock Knowledge Base as a possible future move).

- `ingest/` -- the Python ingestion scripts (Drive sync, PDF extraction,
  article splitting via Bedrock Converse, S3 upload, Bedrock KB sync)
- `infra/` -- the CDK stack (S3 bucket, Bedrock Knowledge Base, Lambda,
  EventBridge schedule)
- `tests/` -- pytest suite for the above
- `.env.example.aws` -- the env vars this pipeline needs
- `web-bedrock/` -- the Next.js app's original query-router/generate-answer
  modules (Phase 5 replaced these; see its own README)

To run any of this, create a venv and `pip install -r requirements.txt`
from this directory.
