// Confirmed against ai.google.dev/gemini-api/docs/models on 2026-08-26 --
// re-check before bumping, Google deprecates these fast. Kept in sync with
// ingest/config.py, which does the same ingestion-side.
export const GEMINI_CLASSIFY_MODEL = "gemini-3.5-flash-lite";
export const GEMINI_ANSWER_MODEL = "gemini-3.7-flash";
export const GEMINI_EMBED_MODEL = "gemini-embedding-001";

// pgvector's HNSW/IVFFlat indexes cap at 2000 dims -- must match
// db/schema.sql's `vector(1536)` column and ingest/config.py's
// EMBEDDING_DIMENSIONS.
export const EMBEDDING_DIMENSIONS = 1536;
