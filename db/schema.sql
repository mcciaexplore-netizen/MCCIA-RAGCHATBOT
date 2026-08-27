create extension if not exists vector;

create table articles (
  id serial primary key,
  issue_year int not null,
  issue_month_number smallint not null check (issue_month_number between 1 and 12),
  article_index int not null check (article_index >= 1),
  issue_month text not null,        -- canonical lookup key, e.g. '2021-06'
  article_title text not null,
  author text,
  body text not null,
  source_url text,
  content_type text not null default 'text',
  drive_file_id text not null,
  created_at timestamptz not null default now(),
  constraint articles_issue_coordinates_match check (
    issue_month = issue_year::text || '-' || lpad(issue_month_number::text, 2, '0')
  ),
  unique (issue_year, issue_month_number, article_index)
);

create table chunks (
  id serial primary key,
  article_id int not null references articles(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  embedding vector(1536) not null,
  unique (article_id, chunk_index)
);

create index on articles (issue_month);
create index on chunks (article_id);
create index on chunks using hnsw (embedding vector_cosine_ops);

-- Vector-facing shape requested by the archive: year -> month -> article.
-- One article can have several chunk vectors, distinguished by chunk_index.
create view sampada_article_vectors as
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

-- Allows an ingestion process started during a rolling deployment to finish
-- safely even if it still uses the pre-coordinate INSERT statement.
create function populate_article_coordinates()
returns trigger
language plpgsql
as $$
begin
  if new.issue_month_number is null then
    new.issue_month_number := split_part(new.issue_month, '-', 2)::smallint;
  end if;

  if new.article_index is null then
    perform pg_advisory_xact_lock(new.issue_year, new.issue_month_number);
    select coalesce(max(a.article_index), 0) + 1
    into new.article_index
    from articles a
    where a.issue_year = new.issue_year
      and a.issue_month_number = new.issue_month_number;
  end if;

  return new;
end
$$;

create trigger articles_populate_coordinates
before insert on articles
for each row
execute function populate_article_coordinates();
