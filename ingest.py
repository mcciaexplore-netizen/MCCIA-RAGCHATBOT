import base64, json, os, re, sys
import pymupdf, requests, psycopg
from pgvector.psycopg import register_vector
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

OCR = os.getenv("OCR_BACKEND", "gemini")   # "gemini" or "paddle"
DB = os.environ["DATABASE_URL"]
EMBED_URL = "http://localhost:8001/embed"

MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
          "july":7,"august":8,"september":9,"october":10,"november":11,"december":12}

def issue_date_from_filename(name):
    m = re.search(r"(\d{4})", name)
    year = int(m.group(1)) if m else None
    month = next((v for k, v in MONTHS.items() if k in name.lower()), None)
    if year and month:
        return f"{year}-{month:02d}-01"
    return None

def ocr_gemini(png_bytes):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = ("Transcribe all text from this page verbatim in Devanagari. "
              "This is a Marathi magazine. Preserve archaic spelling exactly. "
              "Do not translate or modernise. Output only the transcription.")
    r = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[types.Part.from_bytes(data=png_bytes, mime_type="image/png"), prompt])
    return r.text or ""

def ocr_paddle(png_bytes):
    b64 = base64.b64encode(png_bytes).decode()
    r = requests.post("http://localhost:8111/v1/chat/completions", json={
        "model": "PaddlePaddle/PaddleOCR-VL-1.6",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": "Extract all text from this document as markdown."}]}],
        "max_tokens": 4096}, timeout=600)
    return r.json()["choices"][0]["message"]["content"]

def chunk(text, target_words=600):
    out, buf, n = [], [], 0
    for line in text.split("\n"):
        w = len(line.split())
        if n + w > target_words and buf:
            out.append("\n".join(buf)); buf, n = [], 0
        buf.append(line); n += w
    if buf: out.append("\n".join(buf))
    return [c for c in out if c.strip()]

def embed(texts):
    r = requests.post(EMBED_URL, json={"texts": texts}, timeout=300)
    return r.json()["vectors"]

def main(pdf_path):
    fname = os.path.basename(pdf_path)
    issue_date = issue_date_from_filename(fname)
    print(f"{fname}  ->  issue_date={issue_date}  ocr={OCR}")

    conn = psycopg.connect(DB, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sampada_chunks (
          id          bigserial PRIMARY KEY,
          source_file text NOT NULL,
          page_number int NOT NULL,
          issue_date  date,
          chunk_index int NOT NULL,
          content     text NOT NULL,
          embedding   vector(1024),
          ocr_backend text,
          UNIQUE (source_file, page_number, chunk_index)
        )""")

    doc = pymupdf.open(pdf_path)
    for pno in range(len(doc)):
        png = doc[pno].get_pixmap(dpi=300).tobytes("png")
        text = ocr_gemini(png) if OCR == "gemini" else ocr_paddle(png)
        if not text.strip():
            print(f"  page {pno+1}: empty, skipped"); continue

        chunks = chunk(text)
        vecs = embed(chunks)
        for i, (c, v) in enumerate(zip(chunks, vecs)):
            conn.execute("""
                INSERT INTO sampada_chunks
                  (source_file, page_number, issue_date, chunk_index, content, embedding, ocr_backend)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_file, page_number, chunk_index) DO UPDATE
                  SET content=EXCLUDED.content, embedding=EXCLUDED.embedding,
                      ocr_backend=EXCLUDED.ocr_backend
            """, (fname, pno+1, issue_date, i, c, v, OCR))
        print(f"  page {pno+1}: {len(chunks)} chunks")

    conn.close()
    print("done")

if __name__ == "__main__":
    main(sys.argv[1])