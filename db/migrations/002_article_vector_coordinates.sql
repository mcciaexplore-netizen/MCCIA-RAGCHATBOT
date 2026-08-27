-- Backfill an existing Sampada database into the vector-facing coordinate
-- shape: (year, month, article_index, chunk_index, embedding).

alter table articles
  add column if not exists issue_month_number smallint;

alter table articles
  add column if not exists article_index int;

update articles
set issue_month_number = split_part(issue_month, '-', 2)::smallint
where issue_month_number is null;

with ranked_articles as (
  select
    id,
    row_number() over (
      partition by issue_year, issue_month
      order by id
    )::int as inferred_article_index
  from articles
)
update articles a
set article_index = r.inferred_article_index
from ranked_articles r
where a.id = r.id
  and a.article_index is null;

alter table articles
  alter column issue_month_number set not null,
  alter column article_index set not null,
  alter column drive_file_id set not null,
  alter column created_at set not null;

alter table chunks
  alter column article_id set not null,
  alter column embedding set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'articles_issue_month_number_check'
      and conrelid = 'public.articles'::regclass
  ) then
    alter table articles
      add constraint articles_issue_month_number_check
      check (issue_month_number between 1 and 12);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'articles_article_index_check'
      and conrelid = 'public.articles'::regclass
  ) then
    alter table articles
      add constraint articles_article_index_check
      check (article_index >= 1);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conname = 'articles_issue_coordinates_match'
      and conrelid = 'public.articles'::regclass
  ) then
    alter table articles
      add constraint articles_issue_coordinates_match check (
        issue_month = issue_year::text || '-' || lpad(issue_month_number::text, 2, '0')
      );
  end if;
end
$$;

create unique index if not exists articles_issue_article_index_uidx
  on articles (issue_year, issue_month_number, article_index);

create unique index if not exists chunks_article_chunk_index_uidx
  on chunks (article_id, chunk_index);

create index if not exists chunks_article_id_idx
  on chunks (article_id);

create or replace view sampada_article_vectors as
select
  a.issue_year as year,
  a.issue_month_number as month,
  a.article_index,
  c.chunk_index,
  a.id as article_id,
  a.article_title,
  a.author,
  c.content,
  c.embedding,
  a.drive_file_id,
  a.source_url
from articles a
join chunks c on c.article_id = a.id;
