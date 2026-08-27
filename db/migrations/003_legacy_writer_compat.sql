-- Keep an ingestion process started before migration 002 compatible with the
-- new NOT NULL coordinate columns. New writers provide both values directly;
-- this trigger only fills them when an older INSERT omits them.

create or replace function populate_article_coordinates()
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

do $$
begin
  if not exists (
    select 1
    from pg_trigger
    where tgname = 'articles_populate_coordinates'
      and tgrelid = 'public.articles'::regclass
      and not tgisinternal
  ) then
    create trigger articles_populate_coordinates
    before insert on articles
    for each row
    execute function populate_article_coordinates();
  end if;
end
$$;
