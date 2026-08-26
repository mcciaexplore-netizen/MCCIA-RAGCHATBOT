"""A single place that knows how to open a connection to Neon -- swapping
the retrieval layer's backing store later (Aurora pgvector, a Bedrock
Knowledge Base) means changing this module and db/schema.sql, not code
scattered through ingest/ or the web app.
"""

import psycopg
from pgvector.psycopg import register_vector

from db.config import database_url


def connect() -> psycopg.Connection:
    conn = psycopg.connect(database_url())
    register_vector(conn)
    return conn
