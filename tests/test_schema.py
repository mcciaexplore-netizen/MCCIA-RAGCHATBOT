"""Structural checks on the fresh three-level Sampada schema."""

from pathlib import Path

SCHEMA = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()


def test_enables_pgvector():
    assert "create extension if not exists vector" in SCHEMA


def test_sampada_is_keyed_by_year_then_month():
    assert "create table sampada" in SCHEMA
    assert "year integer not null check (year between 1945 and 2017)" in SCHEMA
    assert "month smallint not null check (month between 1 and 12)" in SCHEMA
    assert "primary key (year, month)" in SCHEMA


def test_articles_use_year_month_article_index_coordinates():
    assert "create table articles" in SCHEMA
    assert "article_index integer not null check (article_index >= 1)" in SCHEMA
    assert "primary key (year, month, article_index)" in SCHEMA
    assert "references sampada (year, month)" in SCHEMA
    assert "constraint articles_id_unique unique (id)" in SCHEMA


def test_smaller_chunks_use_complete_vector_coordinates():
    assert "create table smaller_chunks" in SCHEMA
    assert "primary key (year, month, article_index, chunk_index)" in SCHEMA
    assert "references articles (year, month, article_index)" in SCHEMA
    assert "embedding vector(1536) not null" in SCHEMA


def test_schema_has_chronology_and_vector_indexes():
    assert "on articles (year, month, article_index)" in SCHEMA
    assert "on smaller_chunks using hnsw (embedding vector_cosine_ops)" in SCHEMA


def test_source_pdf_is_preserved_at_issue_and_article_levels():
    assert SCHEMA.count("source_pdf_id text not null") == 2
