-- Read-only verification for the restructured Sampada schema.
-- Run after restructure_01, restructure_02, and restructure_03 on a Neon branch.

-- Migrated and preserved row counts must match exactly.
select
  (select count(*) from articles_legacy) as legacy_articles,
  (select count(*) from articles) as migrated_articles,
  (select count(*) from chunks_legacy) as legacy_vector_chunks,
  (select count(*) from smaller_chunks) as migrated_vector_chunks,
  (select count(distinct (issue_year, issue_month_number)) from articles_legacy)
    as legacy_sampada,
  (select count(*) from sampada) as migrated_sampada;

-- Every coordinate and vector must be valid, unique, and connected to its parent.
select
  (select count(*)
   from sampada
   where year not between 1945 and 2017 or month not between 1 and 12)
    as invalid_sampada,
  (select count(*)
   from articles
   where year not between 1945 and 2017
      or month not between 1 and 12
      or article_index < 1)
    as invalid_articles,
  (select count(*)
   from smaller_chunks
   where year not between 1945 and 2017
      or month not between 1 and 12
      or article_index < 1
      or chunk_index < 0)
    as invalid_smaller_chunks,
  (select count(*)
   from articles a
   left join sampada s on s.year = a.year and s.month = a.month
   where s.year is null)
    as orphan_articles,
  (select count(*)
   from articles a
   join sampada s on s.year = a.year and s.month = a.month
   where a.source_pdf_id <> s.source_pdf_id)
    as mismatched_article_sources,
  (select count(*)
   from smaller_chunks c
   left join articles a
     on a.year = c.year
    and a.month = c.month
    and a.article_index = c.article_index
   where a.id is null)
    as orphan_smaller_chunks,
  (select count(*)
   from smaller_chunks
   where embedding is null or vector_dims(embedding) <> 1536)
    as invalid_embeddings;

-- Article and chunk indexes should be contiguous inside each parent.
select
  (select count(*)
   from (
     select year, month
     from articles
     group by year, month
     having min(article_index) <> 1
        or max(article_index) <> count(*)
        or count(distinct article_index) <> count(*)
   ) bad_article_sets)
    as non_contiguous_article_sets,
  (select count(*)
   from (
     select year, month, article_index
     from smaller_chunks
     group by year, month, article_index
     having min(chunk_index) <> 0
        or max(chunk_index) <> count(*) - 1
        or count(distinct chunk_index) <> count(*)
   ) bad_chunk_sets)
    as non_contiguous_chunk_sets;

-- This is the chronology Neon must display when the query has ORDER BY.
select
  s.year,
  s.month,
  count(distinct a.article_index) as article_count,
  count(c.chunk_index) as vector_chunk_count,
  min(a.article_index) as first_article_index,
  max(a.article_index) as last_article_index
from sampada s
left join articles a on a.year = s.year and a.month = s.month
left join smaller_chunks c
  on c.year = a.year
 and c.month = a.month
 and c.article_index = a.article_index
group by s.year, s.month
order by s.year, s.month;

-- Explicitly recheck the two years that previously looked suspicious.
select year, month, article_index, id, article_title
from articles
where year in (1946, 2011)
order by year, month, article_index;
