# Archived: web app's Bedrock query-router / generate-answer

The Next.js app's original query-classification and answer-generation
modules, built against Bedrock (Converse for classification,
RetrieveAndGenerate for retrieval+generation in one call). Replaced in
Phase 5 by `web/src/lib/gemini/query-router.ts` and
`web/src/lib/gemini/generate-answer.ts`, which split retrieval and
generation into explicit steps against Neon/pgvector instead of one opaque
Bedrock call. Never run against real AWS credentials.
