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
- [x] **Phase 2: Ingestion** -- `ingest/` (Drive sync, text extraction,
      Gemini article splitting, chunking + embedding, Postgres writes)
- [x] **Phase 3: Query routing** -- `web/src/lib/gemini/query-router.ts`,
      `web/src/lib/retrieval.ts`
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

## Phase 2: Ingestion

```bash
python -m ingest.run_pipeline sync              # pull PDFs from Drive into staging/raw/
python -m ingest.run_pipeline process            # extract, split, chunk, embed, write to Postgres
python -m ingest.run_pipeline process --force    # reprocess even if already in the database
python -m ingest.run_pipeline all                # sync then process
```

Needs, beyond `.env`: a GCP service account with the Drive folder shared to
its `client_email` (Viewer), JSON key path in `GOOGLE_SERVICE_ACCOUNT_FILE`
(defaults to `./secrets/drive-service-account.json`, which is gitignored).

Pipeline, per PDF:

1. `ingest/drive_sync.py` walks the whole Drive folder tree recursively and
   downloads every `application/pdf`, regardless of how it's organized. Also
   writes `staging/raw/.drive_ids.json` (filename -> Drive file ID), since
   `articles.drive_file_id` needs the real ID and `process` works from local
   files.
2. `ingest/extract_text.py` pulls the text layer directly (PyMuPDF, no OCR).
3. `ingest/detect_issue_date.py` tries the filename, then the first 2 pages'
   text. Undated PDFs are logged to `staging/manual_review.csv` rather than
   guessed.
4. `ingest/split_articles.py` sends the issue's text to Gemini
   (`gemini-3.7-flash`, structured JSON output) to identify each article's
   title/author/line-range boundaries -- not the body text itself, so
   there's no risk of the model truncating or paraphrasing a long issue.
   The body is sliced from the *original* extracted text client-side, so
   citations stay byte-exact. A malformed response gets one retry, then the
   PDF is logged to manual review and skipped.
5. Each article is inserted into `articles`, keeping `drive_file_id` so
   citations can always trace back to the source PDF. For 2021+ issues,
   `ingest/web_archive.py` looks up the matching mcciapunesampada.com page
   for `source_url` (best-effort -- a network hiccup never fails the run).
6. `ingest/chunking.py` splits the body into ~300-token chunks with a ~50
   token overlap; `ingest/embeddings.py` embeds each with
   `gemini-embedding-001` at 1536 dimensions (batched, L2-normalized per
   Google's guidance for non-default dimensionality) and inserts into
   `chunks`.

Resumable per Phase 2's spec: `already_ingested()` checks the database
itself (any article with this Drive file ID) rather than a local manifest,
so a crash partway through doesn't mean starting over -- just re-run
`process`. One PDF's unexpected failure is logged and skipped rather than
stopping the whole run.

**Schema gap flagged, not guessed:** the original spec's step 7 also
mentions pulling topic tags into the archive, but the approved Phase 1
schema has no `topic_tags` column -- confirmed with the user to store only
`source_url` and drop tags rather than alter the already-built schema.

## Phase 3: Query routing

Lives in `web/` (TypeScript), not `ingest/` (Python) -- this is runtime
query-serving logic that Next.js API routes call on every question, not a
batch ingestion step. Not wired into `api/chat/route.ts` yet (still calling
the Bedrock version) -- that swap is Phase 5.

- `web/src/lib/gemini/query-router.ts` -- `classifyQuery(question)` sends the
  question to `gemini-3.5-flash-lite` with a small classification prompt
  (today's date included, so "the latest issue" resolves), gets back strict
  JSON (`{scope, issue_month?}`), and falls back to `scope: "open"` on
  anything malformed rather than risking a broken SQL filter that silently
  returns zero rows.
- `web/src/lib/retrieval.ts` -- `search(embedding, route)` is the shared
  query the spec describes: same SQL either way, issue-scoped adds
  `where a.issue_month = $1`, both join `chunks` to `articles` so every
  result carries `issueMonth`/`articleTitle`/`sourceUrl` for citations.
  Defaults to the spec's top-8-to-12 range (10). Embedding the question
  itself is Phase 4's first step, not this one -- `search()` just takes
  whatever embedding vector it's given.
- `web/src/lib/db.ts` -- the one place that knows how to reach Neon from the
  web app (`@neondatabase/serverless`), mirroring `db/connection.py` on the
  Python side. pgvector has no native type in the HTTP driver, so embeddings
  are sent as a bracketed literal and cast with `::vector` in the query.

Model IDs and 1536-dimensional embeddings are the same constants as the
ingestion side (`web/src/lib/gemini/models.ts` mirrors `ingest/config.py`) --
re-verified against ai.google.dev's JS/TS docs specifically (`@google/genai`,
not Python's `google-genai`; confirmed the `interactions.create` /
`models.embedContent` param shapes against the installed package's own
`.d.ts` files, not just the docs prose).

## Tests

```bash
python -m pytest      # ingestion (Phases 1-2)
cd web && npm test    # web app, including Phases 3+ (Vitest)
```

Python: 56 tests, covering the schema's structure (Phase 1), issue-date
detection across filename/cover-text formats, PDF text extraction, article
boundary slicing and Gemini response validation/retry (with a fake client,
no real API calls), chunking, embedding batching/normalization (fake
client), Postgres writes and resumability (fake connection), the
mcciapunesampada.com feed parsing, and an end-to-end `process` run against a
synthetic PDF with Gemini and Postgres both stubbed.

Web: 57 tests, including Phase 3's classification parsing/fallback behavior
and `search()`'s query shape (issue filter present/absent, vector literal
formatting, the chunks-join-articles select list, default vs. caller-supplied
limit) -- all against a fake `interactions.create`/tagged-template client,
no real Gemini or Neon calls.

None of this has been run against real Gemini or Neon credentials yet (none
are configured in this environment) -- worth a manual dry run against a
single real issue before pointing this at the full 70-year archive.

## Web app

`web/` is the existing Next.js chat UI -- its MCCIA-branded design (logo,
brand colors, layout) stays as built. Phase 5 only rewires its API routes
from Bedrock to the new Gemini + Neon retrieval layer.
