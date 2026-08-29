-- PROPOSAL -- NOT YET APPLIED. Additive-only: one generated column, one
-- index. No existing column or row is modified or dropped.
--
-- 'simple' config, not 'english': the corpus is bilingual (English +
-- Devanagari Marathi/Hindi mixed per page, see ingest/extract_text.py's OCR
-- prompt). English's stemming rules assume English morphology and would
-- distort exact proper-noun matches ("Kirloskar", "Tata") for no benefit --
-- Postgres has no Devanagari-aware config either way, so 'simple' (tokenize
-- + lowercase, no stemming) is the safer, more literal default here. Easy
-- to swap later per-query if stemmed English recall turns out to matter.
alter table smaller_chunks
  add column if not exists content_tsv tsvector
    generated always as (to_tsvector('simple', content)) stored;

create index if not exists smaller_chunks_content_tsv_idx
  on smaller_chunks using gin (content_tsv);

-- Doing this now, at ~1,510 rows, matters: a STORED generated column is
-- computed for every existing row when the column is added (a full table
-- rewrite). At today's tiny scale that's instant; deferring this until
-- after a tens-of-thousands-of-chunks backfill would make the same ALTER
-- an expensive, lock-holding operation on live data. This is the cheap
-- moment to do it.
