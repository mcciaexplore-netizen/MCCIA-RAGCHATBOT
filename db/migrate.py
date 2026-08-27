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
            cur.execute("select to_regclass('public.articles')")
            articles_exist = cur.fetchone()[0] is not None
            migration_paths = (
                sorted(MIGRATIONS_DIR.glob("*.sql"))
                if articles_exist
                else [SCHEMA_PATH]
            )
            for migration_path in migration_paths:
                cur.execute(migration_path.read_text())
        conn.commit()
    print("Applied: " + ", ".join(str(path) for path in migration_paths))


if __name__ == "__main__":
    load_dotenv()
    migrate()
