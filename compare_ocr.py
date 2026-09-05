import base64, os, sys, time
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

IMG = sys.argv[1] if len(sys.argv) > 1 else "page1_300.png"
PROMPT = "Extract all text from this document as markdown. Preserve the original Marathi/Devanagari text exactly as printed. Do not translate or correct spelling."

raw = open(IMG, "rb").read()
b64 = base64.b64encode(raw).decode()

t = time.time()
try:
    r = requests.post("http://localhost:8111/v1/chat/completions", json={
        "model": "PaddlePaddle/PaddleOCR-VL-1.6",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": PROMPT}]}],
        "max_tokens": 4096}, timeout=300)
    paddle_out = r.json()["choices"][0]["message"]["content"]
except Exception as e:
    paddle_out = f"FAILED: {e}"
paddle_time = time.time() - t

t = time.time()
try:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=[types.Part.from_bytes(data=raw, mime_type="image/png"), PROMPT])
    gem_out = resp.text
except Exception as e:
    gem_out = f"FAILED: {e}"
gem_time = time.time() - t

print("=" * 70)
print(f"PADDLEOCR-VL  ({paddle_time:.1f}s)")
print("=" * 70)
print(paddle_out)
print()
print("=" * 70)
print(f"GEMINI  ({gem_time:.1f}s)")
print("=" * 70)
print(gem_out)

with open("ocr_comparison.txt", "w") as f:
    f.write(f"=== PADDLEOCR-VL ({paddle_time:.1f}s) ===\n{paddle_out}\n\n")
    f.write(f"=== GEMINI ({gem_time:.1f}s) ===\n{gem_out}\n")
print("\nSaved to ocr_comparison.txt")