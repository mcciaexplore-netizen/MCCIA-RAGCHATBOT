import os, time, requests, psycopg
from pgvector.psycopg import register_vector
from dotenv import load_dotenv

load_dotenv()
BATCH = 64

conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
register_vector(conn)

total = conn.execute(
    "SELECT count(*) FROM smaller_chunks WHERE embedding_bge IS NULL"
).fetchone()[0]
print(f"{total} chunks to embed")

done, t0 = 0, time.time()
while True:
    rows = conn.execute("""
        SELECT year, month, article_index, chunk_index, content
        FROM smaller_chunks WHERE embedding_bge IS NULL LIMIT %s
    """, (BATCH,)).fetchall()
    if not rows:
        break

    r = requests.post("http://localhost:8001/embed",
                      json={"texts": [x[4] for x in rows]}, timeout=300)
    r.raise_for_status()
    vecs = r.json()["vectors"]

    with conn.cursor() as cur:
        cur.executemany("""
            UPDATE smaller_chunks SET embedding_bge = %s
            WHERE year=%s AND month=%s AND article_index=%s AND chunk_index=%s
        """, [(v, x[0], x[1], x[2], x[3]) for x, v in zip(rows, vecs)])

    done += len(rows)
    print(f"  {done}/{total}  ({done/(time.time()-t0):.0f}/s)", flush=True)

print("done")