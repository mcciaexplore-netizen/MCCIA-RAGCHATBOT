from ingest import usage_tracker


def test_log_usage_writes_a_costed_record(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(usage_tracker, "_usage_log_path", lambda: log_path)

    usage_tracker.log_usage("gemini-3.7-flash", "ocr", 1_000_000, 1_000_000)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    import json

    record = json.loads(lines[0])
    assert record["model"] == "gemini-3.7-flash"
    assert record["call_type"] == "ocr"
    # $0.75/1M in + $3.75/1M out, at 1M tokens each.
    assert record["cost_usd"] == 0.75 + 3.75


def test_summarize_totals_across_calls_and_call_types(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(usage_tracker, "_usage_log_path", lambda: log_path)

    usage_tracker.log_usage("gemini-3.7-flash", "ocr", 1_000_000, 0)
    usage_tracker.log_usage("gemini-3.7-flash", "ocr", 1_000_000, 0)
    usage_tracker.log_usage("gemini-embedding-001", "embed", 1_000_000, 0, estimated=True)

    summary = usage_tracker.summarize(log_path)

    assert summary["total_calls"] == 3
    assert summary["by_call_type"]["ocr"]["calls"] == 2
    assert summary["by_call_type"]["ocr"]["cost_usd"] == 0.75 * 2
    assert summary["by_call_type"]["embed"]["cost_usd"] == 0.15
    assert summary["total_cost_usd"] == 0.75 * 2 + 0.15


def test_summarize_with_no_log_file_returns_zero(tmp_path):
    summary = usage_tracker.summarize(tmp_path / "missing.jsonl")
    assert summary == {"total_cost_usd": 0.0, "total_calls": 0, "by_call_type": {}}


def test_unknown_model_costs_nothing_rather_than_raising(tmp_path, monkeypatch):
    log_path = tmp_path / "usage_log.jsonl"
    monkeypatch.setattr(usage_tracker, "_usage_log_path", lambda: log_path)

    usage_tracker.log_usage("some-future-model", "ocr", 1_000_000, 1_000_000)

    summary = usage_tracker.summarize(log_path)
    assert summary["total_cost_usd"] == 0.0
