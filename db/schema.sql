create extension if not exists vector;

create table articles (
  id serial primary key,
  issue_month text not null,        -- '2021-06'
  issue_year int not null,
  article_title text not null,
  author text,
  body text not null,
  source_url text,
  content_type text not null default 'text',
  drive_file_id text,
  created_at timestamptz default now()
);

create table chunks (
  id serial primary key,
  article_id int references articles(id) on delete cascade,
  chunk_index int not null,
  content text not null,
  embedding vector(1536)
);

create index on articles (issue_month);
create index on chunks using hnsw (embedding vector_cosine_ops);
