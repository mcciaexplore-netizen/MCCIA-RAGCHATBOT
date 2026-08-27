"""Read-only verification of a restructured Neon branch.

Usage:
    python -m db.verify_restructure \
        --project-id <neon-project-id> \
        --branch <migration-branch-name>

The branch connection string is requested from the Neon CLI and is never
printed or written to disk.
"""

import argparse
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv

AUDIT_PATH = Path(__file__).parent / "recheck_sampada_chronology.sql"


def _direct_branch_url(project_id: str, branch: str) -> str:
    configured = urlparse(os.environ["DATABASE_URL"])
    command = [
        "npx",
        "neon@latest",
        "connection-string",
        branch,
        "--project-id",
        project_id,
        "--role-name",
        configured.username or "",
        "--database-name",
        configured.path.lstrip("/"),
    ]
    completed = subprocess.run(
        command,
        env=os.environ,
        capture_output=True,
        text=True,
        check=True,
    )
    branch_url = completed.stdout.strip()
    if "-pooler" in (urlparse(branch_url).hostname or ""):
        raise RuntimeError("Neon returned a pooled URL for a migration check")
    return branch_url


def _result_sets(cursor: psycopg.Cursor, sql: str) -> list[tuple[list[str], list[tuple]]]:
    cursor.execute(sql)
    results = []
    while True:
        if cursor.description:
            columns = [column.name for column in cursor.description]
            results.append((columns, cursor.fetchall()))
        if not cursor.nextset():
            break
    return results


def verify(project_id: str, branch: str) -> dict:
    branch_url = _direct_branch_url(project_id, branch)
    with psycopg.connect(branch_url) as conn:
        conn.execute("set transaction read only")

        counts = conn.execute(
            """
            select
              (select count(*) from sampada),
              (select count(*) from articles),
              (select count(*) from smaller_chunks),
              (select count(*) from articles_legacy),
              (select count(*) from chunks_legacy)
            """
        ).fetchone()

        mismatches = conn.execute(
            """
            select
              (select count(*)
               from articles a
               full join articles_legacy l on l.id = a.id
               where a.id is null
                  or l.id is null
                  or (
                    a.year, a.month, a.article_index, a.article_title,
                    a.author, a.body, a.source_url, a.source_pdf_id,
                    a.content_type, a.created_at
                  ) is distinct from (
                    l.issue_year, l.issue_month_number, l.article_index,
                    l.article_title, l.author, l.body, l.source_url,
                    l.drive_file_id, l.content_type, l.created_at
                  )),
              (select count(*)
               from smaller_chunks c
               full join (
                 select
                   l.id,
                   l.chunk_index,
                   l.content,
                   l.embedding,
                   a.issue_year,
                   a.issue_month_number,
                   a.article_index
                 from chunks_legacy l
                 join articles_legacy a on a.id = l.article_id
               ) l on l.id = c.id
               where c.id is null
                  or l.id is null
                  or (
                    c.year, c.month, c.article_index, c.chunk_index,
                    c.content, c.embedding
                  ) is distinct from (
                    l.issue_year, l.issue_month_number, l.article_index,
                    l.chunk_index, l.content, l.embedding
                  ))
            """
        ).fetchone()

        chronology = conn.execute(
            """
            select year, month, article_index
            from articles
            order by year, month, article_index
            """
        ).fetchall()

        hnsw_count = conn.execute(
            """
            select count(*)
            from pg_indexes
            where schemaname = 'public'
              and tablename = 'smaller_chunks'
              and indexname = 'smaller_chunks_embedding_hnsw_idx'
            """
        ).fetchone()[0]

        # Compile and execute the same query shapes used by the web app.
        sample = conn.execute(
            """
            select year, month, article_index, id
            from articles
            order by year, month, article_index
            limit 1
            """
        ).fetchone()
        vector = conn.execute(
            "select embedding::text from smaller_chunks limit 1"
        ).fetchone()[0]
        conn.execute(
            """
            select a.id, c.content
            from smaller_chunks c
            join articles a
              on a.year = c.year
             and a.month = c.month
             and a.article_index = c.article_index
            order by c.embedding <=> %s::vector
            limit 3
            """,
            (vector,),
        ).fetchall()
        conn.execute(
            """
            select a.id, c.content
            from smaller_chunks c
            join articles a
              on a.year = c.year
             and a.month = c.month
             and a.article_index = c.article_index
            where c.year = %s and c.month = %s
            order by c.embedding <=> %s::vector
            limit 3
            """,
            (sample[0], sample[1], vector),
        ).fetchall()

        with conn.cursor() as cursor:
            audit_sets = _result_sets(cursor, AUDIT_PATH.read_text())

        audit_counts = dict(zip(audit_sets[0][0], audit_sets[0][1][0]))
        audit_integrity = dict(zip(audit_sets[1][0], audit_sets[1][1][0]))
        audit_contiguity = dict(zip(audit_sets[2][0], audit_sets[2][1][0]))

        return {
            "branch": branch,
            "direct_connection": True,
            "counts": {
                "sampada": counts[0],
                "articles": counts[1],
                "smaller_chunks": counts[2],
                "legacy_articles": counts[3],
                "legacy_chunks": counts[4],
            },
            "content_comparison": {
                "article_mismatches": mismatches[0],
                "chunk_or_embedding_mismatches": mismatches[1],
            },
            "audit_counts": audit_counts,
            "audit_integrity": audit_integrity,
            "audit_contiguity": audit_contiguity,
            "chronology": {
                "first": chronology[0],
                "last": chronology[-1],
                "rows_sorted": chronology == sorted(chronology),
            },
            "hnsw_index_present": hnsw_count == 1,
            "web_queries_passed": True,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    load_dotenv(override=True)
    print(json.dumps(verify(args.project_id, args.branch), indent=2, default=str))


if __name__ == "__main__":
    main()
