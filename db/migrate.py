"""Apply db/schema.sql to the database at DATABASE_URL.

Usage:
    python -m db.migrate
"""

from pathlib import Path

import psycopg
from dotenv import load_dotenv

from db.config import database_url

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def migrate() -> None:
    schema_sql = SCHEMA_PATH.read_text()
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    print(f"Applied {SCHEMA_PATH} to the database.")


if __name__ == "__main__":
    load_dotenv()
    migrate()
