import os, psycopg
from dotenv import load_dotenv

load_dotenv()
c = psycopg.connect(os.environ["DATABASE_URL"])

print("=== TABLES ===")
for r in c.execute("""
    SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename
""").fetchall():
    print(" ", r[0])

print("\n=== ROW COUNTS ===")
for t in ["sampada", "articles", "smaller_chunks"]:
    try:
        n = c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n}")
    except Exception as e:
        print(f"  {t}: ERROR {e}")

print("\n=== smaller_chunks COLUMNS ===")
for r in c.execute("""
    SELECT column_name, data_type FROM information_schema.columns
    WHERE table_name='smaller_chunks' ORDER BY ordinal_position
""").fetchall():
    print(f"  {r[0]:20} {r[1]}")

print("\n=== EMBEDDING DIMENSION ===")
try:
    d = c.execute("SELECT vector_dims(embedding) FROM smaller_chunks LIMIT 1").fetchone()
    print("  actual dims:", d[0] if d else "no rows")
except Exception as e:
    print("  ", e)

print("\n=== INDEXES ===")
for r in c.execute("""
    SELECT indexname FROM pg_indexes WHERE tablename='smaller_chunks'
""").fetchall():
    print(" ", r[0])

print("\n=== WHICH ISSUES ARE LOADED ===")
for r in c.execute("""
    SELECT year, month, source_pdf_id FROM sampada ORDER BY year, month
""").fetchall():
    print(f"  {r[0]}-{r[1]:02d}  {r[2]}")

print("\n=== ORPHAN CHECK ===")
o = c.execute("""
    SELECT count(*) FROM smaller_chunks sc
    LEFT JOIN articles a USING (year, month, article_index)
    WHERE a.year IS NULL
""").fetchone()[0]
print(f"  chunks with no parent article: {o}")

e = c.execute("SELECT count(*) FROM smaller_chunks WHERE embedding IS NULL").fetchone()[0]
print(f"  chunks with no embedding: {e}")

print("\n=== SAMPLE CHUNK ===")
s = c.execute("""
    SELECT year, month, article_index, chunk_index, left(content, 120)
    FROM smaller_chunks LIMIT 1
""").fetchone()
print(" ", s if s else "empty")

c.close()