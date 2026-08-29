-- PROPOSAL -- NOT YET APPLIED. Additive-only: one new table, plus new
-- nullable/defaulted columns on the existing `sampada` table. No existing
-- data is modified or dropped. Idempotent.
--
-- Two granularities, because one Drive PDF can bundle several monthly
-- issues (see ingest/detect_issue_boundaries.py) -- a single file-level
-- table can't cleanly represent "issue 3 of 4 in this file finished
-- embedding, issue 4 failed." File-level stages (download/validate/OCR)
-- happen once per PDF; issue-level stages (chunk/embed/index) happen once
-- per (year, month), which already has its own row in `sampada`.

create table if not exists ingestion_files (
  drive_file_id text primary key,
  filename text not null,
  file_size bigint,
  drive_modified_time timestamptz,

  discovered_at timestamptz not null default now(),  -- seen in the Drive folder listing
  downloaded_at timestamptz,
  validated_at timestamptz,             -- confirmed to open as a valid PDF
  ocr_required boolean,                 -- decided after checking for a native text layer
  text_extracted_at timestamptz,        -- native-text-layer extraction attempted
  ocr_started_at timestamptz,           -- distinguishes "crashed mid-OCR" from "never started"
  ocr_completed_at timestamptz,         -- Gemini vision OCR finished (only meaningful if ocr_required)
  issue_detection_completed_at timestamptz,  -- know how many issues this file contains

  failed boolean not null default false,
  failure_stage text,   -- e.g. 'download', 'ocr', 'issue_detection' -- what to retry
  failure_reason text,

  updated_at timestamptz not null default now()
);

alter table sampada
  add column if not exists article_splitting_completed_at timestamptz,
  add column if not exists chunked_at timestamptz,
  add column if not exists embedded_at timestamptz,
  add column if not exists indexed_at timestamptz,
  add column if not exists failed boolean not null default false,
  add column if not exists failure_stage text,
  add column if not exists failure_reason text,
  add column if not exists last_processed_at timestamptz;

-- Resumability check: "has this file already been fully handled?" --
--   select * from ingestion_files where drive_file_id = ... and not failed
--   and ocr_completed_at is not null (or ocr_required = false)
-- "Has this specific issue already been chunked/embedded/indexed?" --
--   select * from sampada where year = ... and month = ... and indexed_at is not null
-- If a run stops at file 37 of 80, restarting only needs to skip files
-- whose ingestion_files row shows every required stage complete and not
-- failed -- exactly the "continue from the correct point" requirement. A
-- failure_stage lets a resume target only the failed stage (e.g. redo
-- embedding without redoing OCR) instead of restarting the whole issue.
