import math

from ingest.embeddings import embed_query, embed_texts


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeModels:
    def __init__(self, outer):
        self._outer = outer

    def embed_content(self, *, model, contents, config):
        self._outer.calls.append({"model": model, "contents": list(contents), "config": config})
        # Deterministic, non-unit-length vectors so normalization is testable.
        return type(
            "Result",
            (),
            {"embeddings": [_FakeEmbedding([2.0, 0.0, 0.0]) for _ in contents]},
        )()


class _FakeGemini:
    def __init__(self):
        self.calls = []

    @property
    def models(self):
        return _FakeModels(self)


def test_embed_texts_returns_one_vector_per_input():
    client = _FakeGemini()
    result = embed_texts(["a", "b", "c"], client=client)
    assert len(result) == 3


def test_embed_texts_empty_input_makes_no_api_call():
    client = _FakeGemini()
    assert embed_texts([], client=client) == []
    assert client.calls == []


def test_embed_texts_normalizes_to_unit_length():
    client = _FakeGemini()
    [vector] = embed_texts(["hello"], client=client)
    magnitude = math.sqrt(sum(v * v for v in vector))
    assert math.isclose(magnitude, 1.0, rel_tol=1e-9)


def test_embed_texts_requests_1536_dimensions_and_document_task_type():
    client = _FakeGemini()
    embed_texts(["hello"], task_type="RETRIEVAL_DOCUMENT", client=client)
    assert client.calls[0]["config"].output_dimensionality == 1536
    assert client.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


def test_embed_texts_batches_large_inputs():
    client = _FakeGemini()
    texts = [f"chunk {i}" for i in range(250)]
    result = embed_texts(texts, client=client)

    assert len(result) == 250
    # 250 texts at a 100-per-call batch size -> 3 calls, not 250.
    assert len(client.calls) == 3
    assert [len(c["contents"]) for c in client.calls] == [100, 100, 50]


def test_embed_query_uses_retrieval_query_task_type():
    client = _FakeGemini()
    embed_query("what happened in June 2021?", client=client)
    assert client.calls[0]["config"].task_type == "RETRIEVAL_QUERY"
