-- PROPOSAL -- NOT YET APPLIED. Additive-only (new nullable/defaulted
-- columns), no existing column, constraint, or row is touched or dropped.
-- Safe to run multiple times (idempotent via `if not exists`).
--
-- Adds: publication name + original Drive filename (per issue), and
-- page-number attribution (per article, per chunk) so citations can name
-- an actual page instead of just an issue/article.
--
-- THREE DISTINCT page concepts, deliberately not conflated (per review):
--   1. pdf_page_offset (sampada)      -- physical PDF page (0-based index
--                                        into the source PDF's full page
--                                        list) where THIS ISSUE begins.
--                                        = ingest/detect_issue_boundaries.py's
--                                        IssueBoundary.start_page, already
--                                        computed today, just never persisted.
--   2. issue_page_number (articles/   -- 1-based page number WITHIN this
--      smaller_chunks)                   issue (page 1 = this issue's own
--                                        first page) -- what a citation like
--                                        "Page 27" means to a reader.
--   3. printed magazine page number   -- NOT implemented here. The magazine's
--                                        own printed page number may not
--                                        match either of the above (e.g. a
--                                        cover page often isn't numbered "1").
--                                        Detecting this would need an extra
--                                        Gemini call per page and is
--                                        explicitly out of scope for now.
--                                        Nothing below prevents adding a
--                                        nullable `printed_page_number`
--                                        column later -- same additive
--                                        pattern as everything here.
--
-- The true physical PDF page for any chunk is a DERIVED value, not stored
-- redundantly on every row:
--   pdf_page_number = sampada.pdf_page_offset + smaller_chunks.issue_page_number
-- (both defined 0-based-offset + 1-based-issue-page, so the sum lands on the
-- correct 1-based physical page number) -- computed via the existing join
-- from smaller_chunks -> articles -> sampada, not a new column.

alter table sampada
  add column if not exists source_filename text,
  add column if not exists publication text not null default 'Sampada',
  add column if not exists pdf_page_offset integer;

-- Issue-relative page range this article was found on. Nullable: the 347
-- existing articles predate this feature and simply won't have it until/
-- unless backfilled; new articles from the fixed pipeline populate it.
alter table articles
  add column if not exists issue_page_start integer,
  add column if not exists issue_page_end integer;

-- Issue-relative page this specific chunk's text came from -- the field
-- citations actually need ("Page 27"), since one article can span several
-- pages and a chunk is a sub-slice of the article body.
alter table smaller_chunks
  add column if not exists issue_page_number integer;
