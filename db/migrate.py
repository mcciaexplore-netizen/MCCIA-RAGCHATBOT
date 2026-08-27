"""Create or upgrade the database schema using a direct Neon connection.

Usage:
    python -m db.migrate
"""

from pathlib import Path

import psycopg
from dotenv import load_dotenv

from db.config import migration_database_url

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migrate() -> None:
    with psycopg.connect(migration_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                  to_regclass('public.articles') is not null,
                  to_regclass('public.sampada') is not null
                    and to_regclass('public.smaller_chunks') is not null
                    and exists (
                      select 1
                      from information_schema.columns
                      where table_schema = 'public'
                        and table_name = 'articles'
                        and column_name = 'year'
                    )
                """
            )
            articles_exist, current_schema = cur.fetchone()

            if current_schema:
                migration_paths = []
            elif articles_exist:
                # These migrations only support the pre-restructure schema.
                # The three explicit restructure_*.sql files are intentionally
                # branch-first and are never auto-applied to a live database.
                migration_paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
            else:
                migration_paths = [SCHEMA_PATH]

            for migration_path in migration_paths:
                cur.execute(migration_path.read_text())
        conn.commit()
    if migration_paths:
        print("Applied: " + ", ".join(str(path) for path in migration_paths))
    else:
        print("Schema already uses sampada -> articles -> smaller_chunks")


if __name__ == "__main__":
    load_dotenv()
    migrate()
