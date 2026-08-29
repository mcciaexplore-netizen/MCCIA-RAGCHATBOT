"""Embed text with Gemini at the fixed dimensionality our pgvector index
expects.

gemini-embedding-001 defaults to 3072 dimensions; pgvector's HNSW/IVFFlat
indexes cap at 2000, so we request EMBEDDING_DIMENSIONS (1536) explicitly.
Google's docs note that at a non-default dimensionality the model does not
auto-normalize the vector (only gemini-embedding-2 does), so we L2-normalize
it ourselves -- harmless for our cosine-distance index either way, but it's
what Google's own guidance recommends and costs nothing.

Batches multiple texts per API call (the API accepts a list of contents)
rather than one call per chunk. If ingestion volume ever grows enough to
matter, Gemini's async Batch API runs the same job at half price -- not
implemented yet, this is the straightforward synchronous path.
"""

import math
from typing import List, Optional

from google import genai
from google.genai import types

from ingest.config import EMBEDDING_DIMENSIONS, GEMINI_EMBED_MODEL
from ingest.gemini_retry import call_with_retry, gemini_client
from ingest.usage_tracker import CHARS_PER_TOKEN_ESTIMATE, log_usage

# Keeps individual requests well within payload/token limits regardless of
# how long the chunks in a batch happen to be.
_BATCH_SIZE = 100


def _normalize(vector: List[float]) -> List[float]:
    magnitude = math.sqrt(sum(v * v for v in vector))
    if magnitude == 0:
        return vector
    return [v / magnitude for v in vector]


def _embed_batch(texts: List[str], task_type: str, client: genai.Client) -> List[List[float]]:
    result = call_with_retry(
        "embedding",
        lambda: client.models.embed_content(
            model=GEMINI_EMBED_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=EMBEDDING_DIMENSIONS,
            ),
        ),
    )
    metadata = getattr(result, "metadata", None)
    if metadata is not None and getattr(metadata, "billable_character_count", None):
        estimated_tokens = metadata.billable_character_count // CHARS_PER_TOKEN_ESTIMATE
        log_usage(GEMINI_EMBED_MODEL, "embed", estimated_tokens, 0, estimated=True)
    return [_normalize(e.values) for e in result.embeddings]


def embed_texts(
    texts: List[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
    client: Optional[genai.Client] = None,
) -> List[List[float]]:
    """Embeds a list of texts, batching API calls. Order is preserved.

    task_type is "RETRIEVAL_DOCUMENT" for chunks being indexed (Phase 2) and
    should be "RETRIEVAL_QUERY" for a user's question at query time
    (Phase 3/4) -- Gemini's retrieval embeddings are asymmetric.
    """
    if not texts:
        return []

    client = client or gemini_client()
    embeddings: List[List[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        embeddings.extend(_embed_batch(batch, task_type, client))
    return embeddings


def embed_query(text: str, client: Optional[genai.Client] = None) -> List[float]:
    return embed_texts([text], task_type="RETRIEVAL_QUERY", client=client)[0]
