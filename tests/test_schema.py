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
        "issue_year int not null",
        "issue_month_number smallint not null",
        "article_index int not null",
        "issue_month text not null",
        "article_title text not null",
        "author text",
        "body text not null",
        "source_url text",
        "content_type text not null default 'text'",
        "drive_file_id text not null",
    ]:
        assert column in SCHEMA, f"missing column definition: {column}"


def test_chunks_table_references_articles_with_cascade_delete():
    assert "article_id int not null references articles(id) on delete cascade" in SCHEMA


def test_embedding_column_is_1536_dimensions():
    # pgvector's HNSW/IVFFlat indexes cap at 2000 dims -- gemini-embedding-001
    # must be requested at 1536 dims (not its 3072 default) or the index
    # below can't be built and every query falls back to a full scan.
    assert "embedding vector(1536) not null" in SCHEMA


def test_has_issue_month_and_hnsw_indexes():
    assert "create index on articles (issue_month)" in SCHEMA
    assert "create index on chunks (article_id)" in SCHEMA
    assert "create index on chunks using hnsw (embedding vector_cosine_ops)" in SCHEMA


def test_article_coordinates_are_unique_and_validated():
    assert "check (issue_month_number between 1 and 12)" in SCHEMA
    assert "check (article_index >= 1)" in SCHEMA
    assert "unique (issue_year, issue_month_number, article_index)" in SCHEMA


def test_vector_view_starts_with_year_month_and_article_index():
    view = SCHEMA.split("create view sampada_article_vectors as", 1)[1]
    assert view.index("a.issue_year as year") < view.index("a.issue_month_number as month")
    assert view.index("a.issue_month_number as month") < view.index("a.article_index")
    assert "c.embedding" in view


def test_legacy_writer_trigger_can_fill_coordinates_during_rollout():
    assert "create function populate_article_coordinates()" in SCHEMA
    assert "new.issue_month_number := split_part(new.issue_month" in SCHEMA
    assert "new.article_index" in SCHEMA
    assert "create trigger articles_populate_coordinates" in SCHEMA
