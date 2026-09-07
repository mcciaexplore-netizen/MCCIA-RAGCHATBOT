from fastapi import FastAPI
from pydantic import BaseModel
from FlagEmbedding import BGEM3FlagModel, FlagReranker
import uvicorn

app = FastAPI()
embedder = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)

class EmbedReq(BaseModel):
    texts: list[str]

class RerankReq(BaseModel):
    query: str
    docs: list[str]

@app.post("/embed")
def embed(r: EmbedReq):
    out = embedder.encode(r.texts, batch_size=32, max_length=1024)
    return {"vectors": out['dense_vecs'].tolist()}

@app.post("/rerank")
def rerank(r: RerankReq):
    pairs = [[r.query, d] for d in r.docs]
    return {"scores": reranker.compute_score(pairs, normalize=True)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)