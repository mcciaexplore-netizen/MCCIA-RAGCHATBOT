import base64, sys, time, requests

PORTS = {"paddle": (8111, "PaddlePaddle/PaddleOCR-VL-1.6"),
         "qwen":   (8112, "mlx-community/Qwen3-VL-8B-Instruct-4bit"),
         "gemma":  (8113, "mlx-community/gemma-4-e4b-it-4bit")}

which = sys.argv[1]
img = sys.argv[2] if len(sys.argv) > 2 else "page1_300.png"
port, model = PORTS[which]

b64 = base64.b64encode(open(img, "rb").read()).decode()
t = time.time()
r = requests.post(f"http://localhost:{port}/v1/chat/completions", json={
    "model": model,
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        {"type": "text", "text": "Transcribe all text in this image verbatim, exactly as printed. This is a 1945 Marathi periodical in Devanagari script. Preserve archaic spelling. Output only the transcription."}]}],
    "max_tokens": 4096}, timeout=900)

out = r.json()["choices"][0]["message"]["content"]
elapsed = time.time() - t
print(out)
print(f"\n--- {which}: {elapsed:.1f}s ---")

with open(f"result_{which}.txt", "w") as f:
    f.write(f"{out}\n\n--- {elapsed:.1f}s ---\n")