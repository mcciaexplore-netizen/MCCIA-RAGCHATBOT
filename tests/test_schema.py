"""Structural checks on db/schema.sql that don't require a live database.

A real migration run (`python -m db.migrate` against a Neon connection
string) is the actual verification -- this just catches accidental drift
in the schema file itself.
"""

from pathlib import Path

SCHEMA = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()


def test_enables_pgvector():
    assert "create extension if not exists vector" in SCHEMA


def test_articles_table_has_required_columns():
    for column in [
        "issue_month text not null",
        "issue_year int not null",
        "article_title text not null",
        "author text",
        "body text not null",
        "source_url text",
        "content_type text not null default 'text'",
        "drive_file_id text",
    ]:
        assert column in SCHEMA, f"missing column definition: {column}"


def test_chunks_table_references_articles_with_cascade_delete():
    assert "article_id int references articles(id) on delete cascade" in SCHEMA


def test_embedding_column_is_1536_dimensions():
    # pgvector's HNSW/IVFFlat indexes cap at 2000 dims -- gemini-embedding-001
    # must be requested at 1536 dims (not its 3072 default) or the index
    # below can't be built and every query falls back to a full scan.
    assert "embedding vector(1536)" in SCHEMA


def test_has_issue_month_and_hnsw_indexes():
    assert "create index on articles (issue_month)" in SCHEMA
    assert "create index on chunks using hnsw (embedding vector_cosine_ops)" in SCHEMA
