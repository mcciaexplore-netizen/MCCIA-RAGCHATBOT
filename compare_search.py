import os, sys, requests, psycopg
from pgvector.psycopg import register_vector
from dotenv import load_dotenv
from ingest.embeddings import embed_query

load_dotenv()
q = " ".join(sys.argv[1:]) or "मराठा चेंबरची उद्दिष्टे"

conn = psycopg.connect(os.environ["DATABASE_URL"])
register_vector(conn)

gem = embed_query(q)
bge = requests.post("http://localhost:8001/embed",
                    json={"texts": [q]}, timeout=60).json()["vectors"][0]

def top(col, vec):
    return conn.execute(f"""
        SELECT year, month, article_index, chunk_index, left(content, 90)
        FROM smaller_chunks WHERE {col} IS NOT NULL
        ORDER BY {col} <=> %s::{'vector' if col=='embedding' else 'halfvec'}
        LIMIT 5
    """, (vec,)).fetchall()

print(f"QUERY: {q}\n")
for label, rows in [("GEMINI", top("embedding", gem)), ("BGE-M3", top("embedding_bge", bge))]:
    print(f"--- {label} ---")
    for r in rows:
        print(f"  {r[0]}-{r[1]:02d} a{r[2]}c{r[3]}: {r[4]}")
    print()