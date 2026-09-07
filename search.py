import os, sys, requests, psycopg
from pgvector.psycopg import register_vector
from dotenv import load_dotenv
from google import genai

load_dotenv()
DB = os.environ["DATABASE_URL"]

def main(question):
    qvec = requests.post("http://localhost:8001/embed",
                         json={"texts": [question]}, timeout=60).json()["vectors"][0]

    conn = psycopg.connect(DB)
    register_vector(conn)
    rows = conn.execute("""
        SELECT content, source_file, page_number, issue_date
        FROM sampada_chunks
        ORDER BY embedding <=> %s::vector
        LIMIT 30
    """, (qvec,)).fetchall()
    conn.close()

    if not rows:
        print("no chunks in database"); return

    docs = [r[0] for r in rows]
    scores = requests.post("http://localhost:8001/rerank",
                           json={"query": question, "docs": docs}, timeout=120).json()["scores"]
    ranked = sorted(zip(scores, rows), key=lambda x: -x[0])[:8]

    print("\n--- top sources ---")
    for s, r in ranked:
        print(f"  {s:.3f}  {r[1]} p{r[2]} ({r[3]})")

    context = "\n\n".join(
        f"[{i+1}] (source: {r[1]}, page {r[2]}, issue {r[3]})\n{r[0]}"
        for i, (_, r) in enumerate(ranked))

    prompt = f"""Answer the question using ONLY the numbered excerpts below.
Cite each claim with its number, like [2].
If the answer is not in the excerpts, say so plainly. Do not guess.

EXCERPTS:
{context}

QUESTION: {question}"""

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    r = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    print("\n--- answer ---")
    print(r.text)

if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))