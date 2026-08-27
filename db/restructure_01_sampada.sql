-- Query 1 of 3: preserve the current data and create one row per monthly Sampada.
-- Run on a Neon branch before queries 2 and 3.

begin;

create extension if not exists vector;

drop view if exists sampada_article_vectors;

do $$
begin
  -- Supports a branch already tested with the earlier table name.
  if to_regclass('public.issues') is not null
     and to_regclass('public.sampada') is null then
    execute 'alter table public.issues rename to sampada';
  end if;

  if to_regclass('public.sampada') is not null then
    if exists (
      select 1 from pg_constraint
      where conrelid = 'public.sampada'::regclass
        and conname = 'issues_pkey'
    ) then
      execute 'alter table public.sampada rename constraint issues_pkey to sampada_pkey';
    end if;

    if exists (
      select 1 from pg_constraint
      where conrelid = 'public.sampada'::regclass
        and conname = 'issues_year_check'
    ) then
      execute 'alter table public.sampada rename constraint issues_year_check to sampada_year_check';
    end if;

    if exists (
      select 1 from pg_constraint
      where conrelid = 'public.sampada'::regclass
        and conname = 'issues_month_check'
    ) then
      execute 'alter table public.sampada rename constraint issues_month_check to sampada_month_check';
    end if;
  end if;

  if to_regclass('public.articles') is not null
     and exists (
       select 1 from pg_constraint
       where conrelid = 'public.articles'::regclass
         and conname = 'articles_issue_fkey'
     ) then
    execute 'alter table public.articles rename constraint articles_issue_fkey to articles_sampada_fkey';
  end if;

  if to_regclass('public.articles') is not null
     and to_regclass('public.articles_legacy') is null then
    execute 'alter table public.articles rename to articles_legacy';
  end if;

  if to_regclass('public.chunks') is not null
     and to_regclass('public.chunks_legacy') is null then
    execute 'alter table public.chunks rename to chunks_legacy';
  end if;

  -- The old compatibility trigger refers to the old column layout. Remove
  -- it from the preserved table so it cannot accidentally be used for writes.
  if to_regclass('public.articles_legacy') is not null then
    execute 'drop trigger if exists articles_populate_coordinates on public.articles_legacy';
  end if;

  -- Table renames do not rename their serial sequences. Free the original
  -- names so query 2 can create a fresh articles identity sequence.
  if to_regclass('public.articles_id_seq') is not null
     and to_regclass('public.articles_legacy_id_seq') is null then
    execute 'alter sequence public.articles_id_seq rename to articles_legacy_id_seq';
  end if;

  if to_regclass('public.chunks_id_seq') is not null
     and to_regclass('public.chunks_legacy_id_seq') is null then
    execute 'alter sequence public.chunks_id_seq rename to chunks_legacy_id_seq';
  end if;
end
$$;

-- PostgreSQL keeps explicit NOT NULL constraint names when a table is
-- renamed. Remove the old table-name prefix on an already-migrated branch.
do $$
declare
  constraint_rename record;
begin
  if to_regclass('public.sampada') is not null then
    for constraint_rename in
      select *
      from (values
        ('issues_year_not_null', 'sampada_year_not_null'),
        ('issues_month_not_null', 'sampada_month_not_null'),
        ('issues_source_pdf_id_not_null', 'sampada_source_pdf_id_not_null'),
        ('issues_created_at_not_null', 'sampada_created_at_not_null')
      ) as names(old_name, new_name)
    loop
      if exists (
        select 1
        from pg_constraint
        where conrelid = 'public.sampada'::regclass
          and conname = constraint_rename.old_name
      ) then
        execute format(
          'alter table public.sampada rename constraint %I to %I',
          constraint_rename.old_name,
          constraint_rename.new_name
        );
      end if;
    end loop;
  end if;
end
$$;

drop function if exists populate_article_coordinates();

-- Refuse to migrate only a subset of the archive. The transaction rolls back
-- with a clear error if the old data cannot fit the requested 1945-2017 shape.
do $$
begin
  if exists (
    select 1
    from articles_legacy
    where issue_year not between 1945 and 2017
       or issue_month_number not between 1 and 12
       or article_index < 1
       or drive_file_id is null
  ) then
    raise exception
      'Restructure stopped: legacy article coordinates or source PDF IDs are invalid';
  end if;

  if exists (
    select 1
    from articles_legacy
    group by issue_year, issue_month_number
    having count(distinct drive_file_id) <> 1
  ) then
    raise exception
      'Restructure stopped: one monthly issue maps to multiple source PDFs';
  end if;
end
$$;

create table if not exists sampada (
  year integer not null check (year between 1945 and 2017),
  month smallint not null check (month between 1 and 12),
  source_pdf_id text not null,
  source_url text,
  created_at timestamptz not null default now(),
  primary key (year, month)
);

-- Preserve every currently ingested year/month. Months that have not been
-- ingested are not invented by this migration.
do $$
begin
  if to_regclass('public.articles_legacy') is not null then
    execute $migration$
      insert into sampada (year, month, source_pdf_id, source_url, created_at)
      select
        issue_year,
        issue_month_number,
        min(drive_file_id),
        min(source_url),
        min(created_at)
      from articles_legacy
      group by issue_year, issue_month_number
      on conflict (year, month) do nothing
    $migration$;
  end if;
end
$$;

commit;

select year, month, source_pdf_id
from sampada
order by year, month;
