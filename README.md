# Sampada ingestion pipeline (Phases 1 and 6)

Turns raw Sampada issue PDFs (currently in Google Drive) into per-article text
files + metadata sidecars, laid out ready for a Bedrock Knowledge Base data
source at `s3://<bucket>/processed/<year>/<month>/<slug>.txt`.

Nothing in this phase has been run against real AWS or Google credentials yet
(none are configured in this environment) -- all logic is covered by unit and
integration tests using synthetic PDFs and a mocked Bedrock response instead.

## Pipeline stages

```
Google Drive (PDFs)          ingest/drive_sync.py
        |                    walks the whole folder tree recursively,
        v                    downloads every application/pdf file
  staging/raw/*.pdf
        |                    ingest/extract_text.py (PyMuPDF, no OCR)
        v
  full issue text
        |                    ingest/detect_issue_date.py
        |                    tries filename first, then first-2-pages cover
        |                    text. Logs to manual_review.csv if inconclusive
        |                    rather than guessing.
        v
  (year, month)
        |                    ingest/split_articles.py
        |                    Claude (Bedrock Converse, forced tool call)
        |                    identifies article title/author/line-range
        |                    boundaries only -- the actual body text is
        |                    sliced from the ORIGINAL extracted text
        |                    client-side, so citations stay byte-exact
        |                    and we're not bounded by Bedrock's max output
        |                    tokens on long issues.
        v
  [Article(title, author, body), ...]
        |                    ingest/write_processed.py
        |                    also prints "Sampada, <Month Year>" under the
        |                    title in the body text itself -- Bedrock's
        |                    generation model never sees metadata, only
        |                    chunk text, so the citation date has to live
        |                    here for Phase 4's citations to work at all.
        v
  staging/processed/<year>/<month>/<slug>.txt (+ .metadata.json)
        |                    ingest/build_index.py updates
        |                    staging/index/issues.json (issue -> articles),
        |                    the archive browse page's data source (Phase 5)
        v
  staging/index/issues.json
        |                    ingest/s3_upload.py (only with --upload)
        v
  s3://<bucket>/raw/<year>/<month>.pdf
  s3://<bucket>/processed/<year>/<month>/<slug>.txt(.metadata.json)
  s3://<bucket>/index/issues.json
        |                    ingest/kb_sync.py (only if something uploaded)
        v
  one Bedrock StartIngestionJob for the whole run
```

`ingest/run_pipeline.py` orchestrates all of this and tracks a
sha256-per-PDF manifest (`staging/processed_manifest.json`) so re-running is
idempotent -- unchanged PDFs are skipped. Writing files to S3 does **not**
make Bedrock re-embed them on its own -- `kb_sync.start_ingestion_job()`
is the explicit trigger, called once per run (not once per PDF) whenever
`--upload` actually uploaded something.

## Phase 6: keeping it current

```
EventBridge (weekly) --> ingest/lambda_handler.py (Lambda, Python 3.12)
                            |
                            |-- pulls prior state (manifest/index/manual-
                            |   review log) from s3://<bucket>/state/ and
                            |   index/issues.json -- Lambda's /tmp doesn't
                            |   survive between invocations (lambda_state.py)
                            |-- fetches the Drive service account key from
                            |   Secrets Manager into /tmp
                            |-- runs run_pipeline.cmd_all(upload=True) --
                            |   the exact same code path as a local
                            |   `python -m ingest.run_pipeline all --upload`
                            |-- pushes state back to S3
                            `-- checks mcciapunesampada.com's Blogger
                                "Pages" feed for issues not yet in our
                                index, logs any found (check_web_archive.py)
```

I considered guessing issue-page URLs directly (the spec's own example,
`sampada-<month>-<year>.html`) but checked the real site first: actual
slugs are inconsistent (`sampada-february-2025`, but also
`may-2021-maharashtra-61`, `october-and-november-2021-business`), so
guessed URLs would silently miss real issues. `check_web_archive.py`
instead reads the site's Blogger Pages JSON feed (`/feeds/pages/default`),
which lists every issue page regardless of slug, and parses the issue
date from each page's *title* instead (consistently "SAMPADA <MONTH>
<YEAR>"-shaped) using the same `detect_issue_date` logic Phase 1 already
uses on PDF filenames/cover text. This is a supplementary signal only --
it logs what it finds (a new issue is live on the web but we don't have
its PDF yet), it doesn't scrape article content or attempt ingestion from
HTML, matching the spec's framing of the web archive as "useful... but
not required."

Chose EventBridge + Lambda over the spec's n8n alternative: everything
else in this build is AWS-native with no separate service to host/patch,
and Lambda directly reuses Phase 1's own tested code (no reimplementation)
via `ingest/lambda_handler.py`.

## One assumption worth flagging

The spec's metadata schema is exactly `issue_month`, `issue_year`,
`article_title`, `source_url`, `content_type`. When topic tags are supplied
(the optional 2021+ cross-check against mcciapunesampada.com from spec step
5), `write_issue_articles` adds them as an extra `topic_tags` array in the
same file rather than inventing a separate file.

That cross-check itself is still only half-built: `check_web_archive.py`
(Phase 6) detects that an issue exists on the web and logs it, but doesn't
pull its topic tags or article-level `source_url`s into our metadata --
doing that would mean matching individual articles across two independent
sources (our Bedrock-derived title vs. the site's own article slugs), which
felt like a real design decision rather than something to guess at, and the
spec marks it optional. `source_url`/`topic_tags` stay wired up as
parameters, just still empty by default.

## Setup (once you're ready to run this for real)

```bash
cd sampada
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the CHANGE-ME values
```

You'll need, before `sync`/`process --upload` will work:

1. **A GCP service account** with the Drive folder shared to its
   `client_email` (Viewer). Save its JSON key and point
   `GOOGLE_SERVICE_ACCOUNT_FILE` at it.
2. **A real, available S3 bucket name** in `S3_BUCKET` -- `sampada-archive`
   from the spec is illustrative, not reserved; bucket names are globally
   unique across all AWS accounts. (Created in Phase 2, not here.)
3. **A Bedrock global inference profile ID** for Claude in
   `BEDROCK_ARTICLE_SPLIT_MODEL_ID`. Claude has no native in-region hosting in
   ap-south-1, so this must be a `global.anthropic.claude-*` profile ID
   (confirm the exact string with
   `aws bedrock list-inference-profiles --region ap-south-1`), and model
   access must be enabled for it in the Bedrock console first.
4. **`BEDROCK_KNOWLEDGE_BASE_ID` / `BEDROCK_DATA_SOURCE_ID`** (from
   `infra/sampada_stack.py`'s outputs) -- only needed for `--upload`, so the
   pipeline can trigger re-embedding afterwards.

Phase 6's Lambda needs the same values, set as CDK environment variables
(`infra/sampada_stack.py`) rather than a `.env` file -- see
`infra/README.md`'s "After deploy" section for the three it can't know
ahead of time (the Drive credential, folder ID, and inference profile ARN).

## Running it

```bash
python -m ingest.run_pipeline sync              # pull PDFs from Drive into staging/raw/
python -m ingest.run_pipeline process           # extract + split + write, local only
python -m ingest.run_pipeline process --upload  # also push to S3
python -m ingest.run_pipeline process --force   # reprocess even if a PDF is unchanged
python -m ingest.run_pipeline all --upload      # sync then process in one go
```

PDFs whose issue date can't be determined from filename or cover text are
skipped and appended to `staging/manual_review.csv` with a reason, instead of
being silently mis-filed.

## Tests

```bash
python -m pytest -q
```

47 tests, all passing, covering: issue-date detection across filename/cover-text
formats, slug generation and collision handling, article boundary slicing
(including out-of-range/overlapping ranges), the metadata JSON shape, the
browse index's upsert/sort/reload behavior, an end-to-end run of `process`
against a synthetically generated PDF with the Bedrock call mocked out,
KB-sync triggering (once per run, only when something uploaded), the
Blogger-feed parsing and diff-against-index logic (against a fixture shaped
like the real feed response), and the Lambda handler's state pull/run/push
sequencing. Drive sync, the real Bedrock calls, S3 upload, and the real web
feed fetch are not exercised by tests since they need live credentials or
network access -- worth a manual dry run against a single real issue once
credentials exist, before pointing this at the full 70-year archive.
