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
- [x] **Phase 4: Answer generation with citations** --
      `web/src/lib/gemini/embed.ts`, `web/src/lib/gemini/generate-answer.ts`
- [x] **Phase 5: Chat UI** -- `web/` rewired to the Gemini + Neon backend
- [x] **Phase 6: Keep it current** -- `.github/workflows/ingest.yml`,
      `ingest/run_pipeline.py check-web`

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
`create extension vector`, which `db/migrate.py` runs for you. Migrations use
`DATABASE_URL_UNPOOLED` when provided; otherwise the migration command derives
Neon's direct endpoint by removing `-pooler` from the configured hostname.

## Phase 1: Database setup

```bash
python -m db.migrate
```

Applies `db/schema.sql` for a fresh database. Existing databases are moved to
the new hierarchy with the three branch-first scripts in this order:
`db/restructure_01_sampada.sql`, `db/restructure_02_articles.sql`, then
`db/restructure_03_smaller_chunks.sql`. The old tables are renamed with a
`_legacy` suffix, not deleted, so migrated counts can be verified before any
production cutover.

After running all three scripts on a Neon branch, verify row contents,
embeddings, foreign keys, chronology, the HNSW index, and web query shapes:

```bash
python -m db.verify_restructure \
  --project-id <neon-project-id> \
  --branch <migration-branch-name>
```

The hierarchy is `sampada -> articles -> smaller_chunks`. A monthly Sampada is
keyed by `(year, month)`, an article by `(year, month, article_index)`, and a
vector piece by `(year, month, article_index, chunk_index)`. Every searchable
piece stores a 1536-dimensional vector. Queries that must be chronological use
`order by year, month, article_index, chunk_index`; row display order is not an
implicit property of a Postgres table.

The schema has a numeric chronology index plus an HNSW index on
`smaller_chunks.embedding`. Embeddings are stored at 1536 dimensions (requested
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
python -m ingest.run_pipeline process --file "1947 April.PDF" # retry one exact staged PDF
python -m ingest.run_pipeline process --start-at "1949 April.PDF" # resume here (inclusive)
python -m ingest.run_pipeline all                # sync then process
```

Needs, beyond `.env`: a GCP service account with the Drive folder shared to
its `client_email` (Viewer), JSON key path in `GOOGLE_SERVICE_ACCOUNT_FILE`
(defaults to `./secrets/drive-service-account.json`, which is gitignored).

Pipeline, per PDF:

1. `ingest/drive_sync.py` walks the whole Drive folder tree recursively and
   downloads every `application/pdf`, regardless of how it's organized. Also
   writes `staging/raw/.drive_ids.json` (filename -> Drive file ID), since
   `sampada.source_pdf_id` needs the real ID and `process` works from local
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
5. The monthly parent is upserted into `sampada`, then each article is inserted
   into `articles` with its numeric year, month, and 1-based position. The
   source PDF ID is retained at both levels so data remains traceable. For
   2021+ issues,
   `ingest/web_archive.py` looks up the matching mcciapunesampada.com page
   for `source_url` (best-effort -- a network hiccup never fails the run).
6. `ingest/chunking.py` splits the body into ~300-token chunks with a ~50
   token overlap; `ingest/embeddings.py` embeds each with
   `gemini-embedding-001` at 1536 dimensions (batched, L2-normalized per
   Google's guidance for non-default dimensionality) and inserts into
   `smaller_chunks` with the full year/month/article/chunk coordinate.

Gemini rate limits and temporary server failures (`429`, `500`, `502`,
`503`, `504`) are retried up to five times with exponential backoff. If a
PDF still fails, its exact filename is written to `manual_review.csv` and can
be retried alone with the repeatable `--file` option instead of restarting the
whole 45 GB archive.

For an interrupted first import, `--start-at` resumes from an exact staged
filename (inclusive). OCR rasterization is streamed in six-page batches so
the largest annual bound volumes do not hold every rendered page in memory.

Resumable per Phase 2's spec: `already_ingested()` checks the `sampada` table
for the source PDF ID plus numeric year/month rather than a local manifest,
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
batch ingestion step. Wired into `api/chat/route.ts` as of Phase 5.

- `web/src/lib/gemini/query-router.ts` -- `classifyQuery(question)` sends the
  question to `gemini-3.5-flash-lite` with a small classification prompt
  (today's date included, so "the latest issue" resolves), gets back strict
  JSON (`{scope, issue_month?}`), and falls back to `scope: "open"` on
  anything malformed rather than risking a broken SQL filter that silently
  returns zero rows.
- `web/src/lib/retrieval.ts` -- `search(embedding, route)` is the shared
  query the spec describes: same SQL either way, issue-scoped adds
  numeric `where c.year = $1 and c.month = $2`; both join `smaller_chunks`
  to `articles` using `(year, month, article_index)` so every result carries
  `issueMonth`/`articleTitle`/`sourceUrl` for citations.
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

## Phase 4: Answer generation with citations

Also `web/` (TypeScript) -- the same runtime query-serving path as Phase 3.

- `web/src/lib/gemini/embed.ts` -- `embedQuery()` is Phase 4 step 1: embeds
  the question with `RETRIEVAL_QUERY` (chunks were indexed with
  `RETRIEVAL_DOCUMENT` -- Gemini's retrieval embeddings are asymmetric, so
  the two sides must use the matching task type to compare meaningfully).
- `web/src/lib/gemini/generate-answer.ts` -- `generateAnswer(question, route)`
  chains it together: embed -> `search()` (Phase 3) -> label each chunk
  `Sampada, <Month Year>, "<Article Title>"` so Gemini can attribute
  correctly (step 2) -> `gemini-3.7-flash` generates from that context ->
  citations are built from the SQL rows via `buildCitations()`, not parsed
  back out of the model's own text (step 3, deduped since multiple chunks
  from one article commonly land in the same result set). A route whose
  search comes back empty (e.g. an issue-scoped question for a month with no
  ingested articles yet) returns a plain "couldn't find anything" answer
  without spending a generation call.
- The system prompt (`SYSTEM_PROMPT`, matches the spec verbatim) is what
  actually satisfies acceptance test 3 ("archive doesn't cover this ->
  say so, don't invent") -- Gemini itself judges relevance from the labeled
  excerpts; nothing in the code tries to detect that case.

**Not yet verified against the acceptance tests** (no real Gemini/Neon
credentials or ingested data in this environment) -- now that Phase 5 has
wired this into the UI, once there's real content in Postgres it's worth
running the spec's three acceptance questions for real:
1. "What was in the June 2021 issue of Sampada?" -- issue-scoped, cites only
   that issue.
2. "What did MCCIA do during COVID to help people?" -- open search, cites
   the specific issue/article per point.
3. A genuinely uncovered question -- plain "not found," not an invented
   answer.

## Tests

```bash
python -m pytest tests # active Neon ingestion pipeline (Phases 1, 2, 6)
cd web && npm test    # web app (Phases 3-5, Vitest)
```

Python: 106 tests, covering the schema's structure (Phase 1), issue-date
detection across filename/cover-text formats, PDF text extraction, article
boundary slicing and Gemini response validation/retry (with a fake client,
no real API calls), chunking, embedding batching/normalization (fake
client), Postgres writes and resumability (fake connection), the
mcciapunesampada.com feed parsing and new-issue diffing (Phases 2 and 6),
and end-to-end `process`/`check-web`/`all` runs with Gemini and Postgres
both stubbed.

Web: 66 tests, including Phase 3's classification parsing/fallback behavior,
`search()`'s query shape (issue filter present/absent, vector literal
formatting, the chunks-join-articles select list, default vs. caller-supplied
limit), Phase 4's query embedding (task type, normalization) and answer
generation (context labeling, citation building/deduping, the empty-search
short circuit), and Phase 5's Postgres-backed archive grouping (`api/chat`'s
route test now mocks `lib/gemini/*` instead of `lib/bedrock/*`) -- all
against fake `interactions.create`/`embedContent`/tagged-template clients,
no real Gemini or Neon calls.

None of this has been run against real Gemini or Neon credentials yet (none
are configured in this environment) -- worth a manual dry run against a
single real issue before pointing this at the full 70-year archive.

## Phase 5: Chat UI

`web/` is the existing Next.js chat UI -- its MCCIA-branded design (real
logo, brand colors matching mcciapune.com, layout, copy) stays exactly as
built; per the original spec's forest-green/amber/"no blue"/DM Serif Display
branding would have reverted that work, so Phase 5 was scoped to the data
layer only, confirmed with the user rather than guessed.

- `api/chat/route.ts` now imports `classifyQuery`/`generateAnswer` from
  `lib/gemini/` instead of `lib/bedrock/` -- the only change the route
  itself needed, since both modules were built to the same
  `(question, route) -> {answer, citations}` shape.
- `lib/archive-index.ts` -- the archive browse page's data source, rewired
  from an S3 JSON index to a live query against `articles` (grouped into
  issues client-side by `groupIntoIssues()`). Same `getBrowseIndex()` return
  shape as before, so `app/archive/page.tsx` and `ArchiveBrowser.tsx` needed
  no changes beyond swapping `BrowseArticle.slug` (a file-path artifact from
  the old S3 layout, meaningless in the new schema) for the article's real
  Postgres `id`.
- `lib/config.ts` dropped the now-unused `awsRegion`/`bedrockModelArn`/
  `knowledgeBaseId`/`s3Bucket` getters; `package.json` dropped the `@aws-sdk/*`
  dependencies entirely -- nothing in `web/` calls AWS anymore.
- The old `lib/bedrock/` modules moved to `aws-legacy/web-bedrock/` (same
  archive-don't-delete treatment as Phases 1-2's AWS pipeline).

Verified by hitting the running dev server without any real credentials
configured: both `/archive` and `POST /api/chat` fail exactly where
expected (`DATABASE_URL is not set` / a caught, generic 500), confirming the
new code path is actually reached end-to-end rather than just type-checking.

## Phase 6: Keep it current

**GitHub Actions over the spec's Vercel Cron / n8n options.** Vercel Cron
triggers a Next.js API route -- it fits a job written in TypeScript running
inside the Vercel deployment, not a Python CLI script; using it here would
mean either reimplementing all of `ingest/` in TypeScript (far beyond what
this phase asks) or having it call out to somewhere else that actually runs
Python, which is more moving parts for no benefit. n8n doesn't run Python
natively either, and would need its own hosting decision. Since this repo
is already on GitHub, a scheduled workflow needs no new service, no new
account, and no new secret-management story -- it just runs the exact CLI
already built for Phase 2, on a schedule. (Same kind of call the original
AWS build made choosing EventBridge + Lambda over n8n, for the same
reason: reuse what's already there instead of adding a service to host.)

`.github/workflows/ingest.yml` -- weekly (Sampada is monthly; anything
tighter is wasted API calls), plus `workflow_dispatch` for a manual run.
Installs `requirements.txt`, writes the Drive service account key from a
secret to `secrets/drive-service-account.json`, then runs
`python -m ingest.run_pipeline all`. Caches `staging/` between runs
(keyed on the run ID, falling back to the most recent prior entry) so
`drive_sync.py`'s existing skip-if-same-size check actually has something
to compare against -- without it, every run starts from an empty
`staging/raw/` and re-downloads the whole 70-year archive from Drive every
week just to skip re-processing all of it against Postgres.

Needs these set as repo secrets (Settings -> Secrets and variables ->
Actions): `GEMINI_API_KEY`, `DATABASE_URL`, `GOOGLE_DRIVE_FOLDER_ID`,
`GOOGLE_SERVICE_ACCOUNT_JSON` (the *contents* of the service account JSON
key file, not a path).

`all` now runs a third step after sync/process: `ingest/run_pipeline.py
check-web` (`ingest/web_archive.py`'s `check_for_new_issues`, deferred from
Phase 2). It diffs mcciapunesampada.com's page feed against
`ingested_issue_months()` (a `select year, month from sampada`,
not a local index file the way the archived build did it) and logs any
issue that's live on the web but has no Drive PDF ingested yet -- matching
the spec's framing exactly: a supplementary signal, not an ingestion path.
It never scrapes article content or writes anything from the web archive;
Drive PDFs stay the only source of truth.

64 Python tests now (8 new): the diffing logic (`find_new_web_issues`,
`check_for_new_issues`, both against a fake feed, no network),
`ingested_issue_months()` (fake cursor), and `cmd_check_web`/`cmd_all`'s
ordering (fake connection + mocked `check_for_new_issues`).

**Not run for real** -- no GitHub remote, repo secrets, or scheduled trigger
exist for this local, not-yet-pushed repository. Once this is on GitHub
with real secrets configured, worth triggering `workflow_dispatch` manually
once to confirm the whole chain end to end before trusting the weekly
schedule.
