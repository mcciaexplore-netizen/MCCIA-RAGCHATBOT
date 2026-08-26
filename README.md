# Sampada RAG chatbot

MCCIA's RAG chatbot over 70+ years of Sampada, their monthly industrial
magazine. Gemini for extraction, classification, embeddings, and answer
generation; Neon Postgres with pgvector for storage and vector search. No
AWS in this build.

```
Google Drive PDFs --> extract text --> Gemini splits into articles --> Neon Postgres
                                                                            |
                                                       Gemini embeds each chunk
                                                                            |
                                                                            v
                                                              pgvector index in Neon
                                                                            |
                                                                            v
                     Query --> Gemini classifies scope --> SQL vector search --> Gemini generates
                                                                            |
                                                                            v
                                                             Cited answer (issue + article)
```

Being built phase by phase:

- [x] **Phase 1: Database setup** -- `db/schema.sql`, `db/migrate.py`
- [ ] Phase 2: Ingestion (Drive sync, text extraction, Gemini article
      splitting, chunking + embedding)
- [ ] Phase 3: Query routing (issue-scoped vs. open topic search)
- [ ] Phase 4: Answer generation with citations
- [ ] Phase 5: Chat UI (`web/`)
- [ ] Phase 6: Keep it current (scheduled re-ingestion)

An earlier AWS/Bedrock version of this pipeline is archived in
[aws-legacy/](aws-legacy/) -- never run against real credentials, superseded
by this build.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in GEMINI_API_KEY, DATABASE_URL, GOOGLE_DRIVE_FOLDER_ID
```

`DATABASE_URL` is a Neon Postgres connection string (pooled) from a project
with the `vector` extension available -- Neon enables it on request via
`create extension vector`, which `db/migrate.py` runs for you.

## Phase 1: Database setup

```bash
python -m db.migrate
```

Applies `db/schema.sql`: enables pgvector, creates `articles` and `chunks`,
and indexes `articles.issue_month` plus an HNSW index on
`chunks.embedding`. Embeddings are stored at 1536 dimensions (requested
explicitly from `gemini-embedding-001`, whose default is 3072) because
pgvector's HNSW/IVFFlat indexes cap at 2000 dimensions -- anything wider
can't be indexed and every query would fall back to a full scan.

`articles.content_type` (`'text'` for now) is the extension point for
adding photos later without a schema change -- see the migration note in
the original build spec about `gemini-embedding-2`'s multimodal embeddings.

## Tests

```bash
python -m pytest
```

Phase 1's tests check `db/schema.sql`'s structure directly (extension,
columns, cascade delete, embedding dimensions, indexes) rather than
requiring a live database -- `python -m db.migrate` against a real
`DATABASE_URL` is the actual verification.

## Web app

`web/` is the existing Next.js chat UI -- its MCCIA-branded design (logo,
brand colors, layout) stays as built. Phase 5 only rewires its API routes
from Bedrock to the new Gemini + Neon retrieval layer.
