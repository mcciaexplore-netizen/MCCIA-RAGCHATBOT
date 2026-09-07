"""Multi-model OCR benchmark: all local models vs all Gemini tiers.

Start whichever local servers you want tested. Missing ones are skipped
automatically, so you can run this with any subset up.
"""
import base64, os, time, requests, pymupdf
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
gclient = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

PDF = "staging/raw/1945 July.PDF"
PAGES = [0, 5, 12, 25, 40]
PROMPT = ("Transcribe all text from this page verbatim in Devanagari. "
          "Marathi magazine. Preserve archaic spelling. Output only text.")

LOCAL = [
    ("PaddleOCR-VL", 8111, "PaddlePaddle/PaddleOCR-VL-1.6"),
    ("Qwen3-VL-8B",  8112, "mlx-community/Qwen3-VL-8B-Instruct-4bit"),
    ("Gemma 4 E4B",  8113, "mlx-community/gemma-4-e4b-it-4bit"),
]

CLOUD = [
    ("gemini-3.7-flash",      0.75, 3.75),
    ("gemini-3.5-flash-lite", 0.30, 2.50),
]

def alive(port):
    try:
        requests.get(f"http://localhost:{port}/", timeout=2)
        return True
    except Exception:
        return False

def run_local(port, model, png):
    b64 = base64.b64encode(png).decode()
    t = time.time()
    r = requests.post(f"http://localhost:{port}/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": PROMPT}]}],
            "max_tokens": 4096}, timeout=900)
    return r.json()["choices"][0]["message"]["content"], time.time() - t, 0, 0

def run_cloud(model, png):
    t = time.time()
    r = gclient.models.generate_content(model=model,
        contents=[types.Part.from_bytes(data=png, mime_type="image/png"), PROMPT])
    u = r.usage_metadata
    return (r.text or ""), time.time() - t, u.prompt_token_count or 0, \
           u.candidates_token_count or 0

doc = pymupdf.open(PDF)
images = [doc[p].get_pixmap(dpi=300).tobytes("png") for p in PAGES]

backends = []
for name, port, model in LOCAL:
    if alive(port):
        backends.append((name, lambda png, p=port, m=model: run_local(p, m, png), 0, 0))
    else:
        print(f"skip {name} (port {port} down)")
for name, pin, pout in CLOUD:
    backends.append((name, lambda png, m=name: run_cloud(m, png), pin, pout))

results = {}
for name, fn, pin, pout in backends:
    print(f"\nrunning {name} ...", flush=True)
    tot_t = tot_c = cost = 0.0
    samples = []
    for i, png in enumerate(images):
        try:
            txt, dt, itok, otok = fn(png)
        except Exception as e:
            print(f"  page {PAGES[i]+1} FAILED: {e}")
            continue
        tot_t += dt
        tot_c += len(txt)
        cost += itok / 1e6 * pin + otok / 1e6 * pout
        if i == 0:
            samples.append(txt[:200])
        print(f"  page {PAGES[i]+1}: {dt:.1f}s", flush=True)
    n = len(images)
    results[name] = (tot_t / n, tot_c // n, cost / n, samples[0] if samples else "")

# ---------- table ----------
print("\n" + "=" * 78)
print(f"{'model':<24}{'sec/page':>10}{'chars':>8}{'$/page':>10}{'110k pages':>13}{'cost':>12}")
print("-" * 78)
for name, (t, c, cp, _) in sorted(results.items(), key=lambda x: x[1][0]):
    hrs = 110000 * t / 3600
    tot = 110000 * cp
    print(f"{name:<24}{t:>10.1f}{c:>8}{cp:>10.4f}{hrs:>11.0f}h{'$'+format(tot, ',.0f'):>12}")

print("\n" + "=" * 78)
print("FIRST PAGE SAMPLES (check the date — should be जुले १९४५)")
print("=" * 78)
for name, (_, _, _, s) in results.items():
    print(f"\n--- {name} ---\n{s}")