# Handoff: Sampada RAG chatbot — current state as of 2026-08-27

Paste this whole file into a fresh Claude conversation to get it oriented. It
describes exactly what this project is, what state it's in right now, what
just happened, and what's still open. `README.md` has the deeper
architecture/setup docs; this file is a snapshot of *right now*, not a
replacement for it.

## What this project is

MCCIA's RAG chatbot over 70+ years (1945-2017) of Sampada, their monthly
industrial magazine, scanned as PDFs in Google Drive. Gemini does OCR,
article splitting, embeddings, and answer generation; Neon Postgres
(pgvector) stores everything. Next.js web app (`web/`) serves a chat UI
("Ask MCCIA") plus a browsable archive. Python ingestion pipeline lives in
`ingest/` + `db/`.

Multiple AI sessions/tools have been working on this project in parallel
(at least two, possibly including a Codex/ChatGPT session based on process
listings seen during this work) — some work described below was done by a
different session than the one writing this file, then picked up and
finished here after that other session ran out of tokens mid-task.

## Database: schema just got restructured (finished, verified)

**Old schema** (`issue_month` text key, e.g. `"2021-06"`) has been replaced
with a **chronological composite-key schema**:

- `sampada` — one row per monthly issue, PK `(year, month)`
- `articles` — PK `(year, month, article_index)`, FK to `sampada`, `id` kept
  as a stable public identifier (for URLs/citations)
- `smaller_chunks` — PK `(year, month, article_index, chunk_index)`, FK to
  `articles`, holds the 1536-dim embedding + HNSW index

The old tables are preserved as `articles_legacy` / `chunks_legacy` (not
dropped) so nothing was lost in the cutover. Migration was applied via three
scripts, in order, against production:
`db/restructure_01_sampada.sql` → `db/restructure_02_articles.sql` →
`db/restructure_03_smaller_chunks.sql`. All three are idempotent
(`create table if not exists`, `on conflict do nothing`) and were verified
clean both on a Neon branch (`db/verify_restructure.py`) and directly against
production (`db/recheck_sampada_chronology.sql`) before/after applying:
**zero integrity violations, zero contiguity gaps, row counts match
exactly.**

Current production data: **42 issues, 347 articles, 1510 chunks**, spanning
**July 1945 → January 1949, plus a standalone January 2011** (real gaps in
between — most of the archive isn't ingested yet, see below).

`ingest/db_writer.py`, `ingest/run_pipeline.py`, and the web app's
`web/src/lib/archive-index.ts` / `retrieval.ts` / `article.ts` already query
the new schema — this was done by the other session before it ran out of
tokens, and it's why the restructure had to be finished (the app was 500ing
on `relation "smaller_chunks" does not exist` until all three scripts ran).

**The app is confirmed working right now**: chat (`/api/chat`, bilingual
English+Marathi answers with citations), the archive browse page, and
individual article pages all return 200 with correct data. 109 Python tests
+ 66 web tests pass.

## Ingestion: the big remaining gap

The Drive archive has ~30,000+ pages across ~55-82 PDF files spanning
1945-2017 (some individual-issue files, some annual/multi-year bound
volumes up to 900+ pages each). Only a small slice (42 issues, mostly
1945-1949) is actually ingested. **No ingestion job is currently running.**

- `python -m ingest.run_pipeline sync` pulls PDFs from Drive into
  `staging/raw/` (currently 45GB / 82 files downloaded, not necessarily
  complete — it crashed once already on an uncaught `TimeoutError` around a
  Drive download; **`ingest/drive_sync.py` has no retry logic around network
  calls**, unlike the Gemini calls which do (`ingest/gemini_retry.py`,
  wrapping `split_articles.py`/`detect_issue_boundaries.py`). Worth adding
  before restarting a long unattended run.
- `python -m ingest.run_pipeline process` does OCR (Gemini vision, per
  page) → issue-boundary detection → article splitting → chunk/embed →
  write. Supports `--start-at "<filename>"` and `--file "<filename>"` for
  resuming a specific point. **Real cost so far: $4.31 across 225 Gemini
  calls** (`python -m ingest.usage_tracker` for a live breakdown — OCR
  dominates cost: $3.96 of that $4.31).
- **Rough estimate for the full remaining archive**: ~24-30 hours of
  continuous OCR + supporting calls, roughly **$70-120** in Gemini spend,
  based on real measured throughput (~21 pages/min) and real per-page cost
  early in the run (denser/later pages likely cost somewhat more per page
  than the sparse 1940s issues measured so far).
- **Known inefficiency**: `process_pdf` OCRs a whole PDF before checking
  whether its issue(s) are already ingested, so already-done files get
  needlessly re-OCR'd on every rerun. Not fixed — flagged but judged not
  worth interrupting a live run for (~12% of total time).
- **Duplicate-issue guard exists**: `ingest/db_writer.py`'s
  `issue_month_source()` / `already_ingested()` prevent the same
  `(year, month)` being written twice from two different source PDFs (the
  real archive has overlapping scans — e.g. a bound volume split into
  `Part-1`/`Part-2` files, or a standalone Jan file alongside a Feb-Dec
  bound volume covering the same year).
- **This needs to run somewhere that stays awake** — it was running as a
  local background process and got interrupted multiple times (schema work,
  disk pressure, a laptop that presumably isn't meant to stay on for 24-30
  hours straight). Cloud deployment for this was being discussed
  (GitHub Actions already has `.github/workflows/ingest.yml` for the
  *incremental* weekly check, but that's a 6-hour-max job type, ill-suited
  to one continuous 24-30h run without chunking via `--start-at`) —
  **no decision made yet on how/where to run the backfill.**

## Disk space: tight

**13GB free / 94% used** on the machine running ingestion, out of a 228GB
volume. The downloaded archive is already 45GB. Clearing the
already-fully-ingested older PDFs from `staging/raw/` would reclaim some
space but this needs attention before resuming a long download+process run.

## Other loose ends

- **Git**: 10 commits ahead of `origin` (`https://github.com/mcciaexplore-netizen/sampada.git`),
  not pushed. Push is blocked: GitHub refuses to push a change to
  `.github/workflows/ingest.yml` without the `workflow` OAuth scope, which
  neither `gh`-authenticated account (`mcciaexplore-netizen`, `sujalll21`)
  currently has. Fix needs a human running
  `gh auth refresh -h github.com -s workflow` (interactive browser
  approval) or a classic PAT with `repo`+`workflow` scopes.
- Several new/uncommitted files from the restructure work:
  `db/restructure_0{1,2,3}_*.sql`, `db/recheck_sampada_chronology.sql`,
  `db/verify_restructure.py`, plus modifications across `db/`, `ingest/`,
  `tests/`, `web/src/lib/` — not yet committed (only auto-committed
  snapshots from earlier exist; verify current `git status` before
  assuming what's captured).
- Neon project: `polished-wind-75032477` ("Mccia Google"), org
  `org-wild-leaf-81925287`. Production branch `br-divine-recipe-ay7yw12x`.
  A migration-testing branch `br-floral-voice-ayhg2cf8`
  ("sampada-chronology-migration") still exists (7-day TTL, expires
  2026-09-03) — safe to delete once you're confident in the cutover, or
  leave it, it'll auto-expire.
- Bilingual chat answers (English + Marathi in one Gemini call, with
  citations built only from excerpts the model says it actually used — not
  every retrieved chunk) and a `thinking_level: "low"` config on the answer
  call (was adding several seconds of latency for no benefit on this
  bounded task) both live in `web/src/lib/gemini/generate-answer.ts`.

## Suggested next steps (not yet decided/actioned)

1. Add retry/backoff to `ingest/drive_sync.py`'s network calls.
2. Free up disk space (clear redundant already-ingested PDFs from
   `staging/raw/`).
3. Decide where the long-running `sync` + `process` backfill actually runs
   (cloud VM? chunked GitHub Actions using `--start-at`? something else) —
   this was mid-discussion when this handoff was written.
4. Resume/complete ingestion for the rest of 1945-2017.
5. Sort out the GitHub push permission gap and push the 10 pending commits.
6. Commit the restructure SQL files and related code changes properly
   (currently a mix of auto-committed and uncommitted).
