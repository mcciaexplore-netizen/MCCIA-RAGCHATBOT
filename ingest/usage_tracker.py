"""Tracks Gemini API token usage/cost during ingestion.

The real run against the full Drive archive makes thousands of OCR/
boundary-detection/article-split/embedding calls against a real billed API
key -- this gives a running local $ estimate (`python -m ingest.usage_tracker`)
without waiting on Google's own billing dashboard, which lags and isn't
reachable from this environment anyway. Not a substitute for the real
number: check Google AI Studio -> Dashboard -> Usage for the authoritative
figure.

Pricing confirmed against ai.google.dev/gemini-api/docs/pricing on
2026-08-27 (standard tier, non-batch, current promotional rate where one is
in effect) -- re-check before trusting an old number, Google's rates change.
Embedding cost is estimated from the API's billable_character_count (it
doesn't return a token count for embeddings) via a ~4-chars/token heuristic,
so embed-call figures are approximate; OCR/split/boundary figures come from
real token counts and are exact.
"""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from ingest.config import usage_log as _usage_log_path

PRICING_USD_PER_MILLION_TOKENS = {
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-embedding-001": {"input": 0.15, "output": 0.0},
}

CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass
class UsageRecord:
    ts: float
    model: str
    call_type: str  # "ocr" | "split" | "boundary" | "embed"
    input_tokens: int
    output_tokens: int
    estimated: bool = False  # True when input_tokens is a character-based estimate


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = PRICING_USD_PER_MILLION_TOKENS.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]


def log_usage(
    model: str, call_type: str, input_tokens: int, output_tokens: int, estimated: bool = False
) -> None:
    record = UsageRecord(
        ts=time.time(),
        model=model,
        call_type=call_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated=estimated,
    )
    path = _usage_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = asdict(record)
    row["cost_usd"] = _cost_usd(model, input_tokens, output_tokens)
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def summarize(path: Optional[Path] = None) -> dict:
    """Reads the usage log and totals cost/tokens by call_type."""
    path = path or _usage_log_path()
    if not path.exists():
        return {"total_cost_usd": 0.0, "total_calls": 0, "by_call_type": {}}

    by_type: dict = {}
    total_cost = 0.0
    total_calls = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        bucket = by_type.setdefault(
            rec["call_type"],
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += rec["input_tokens"]
        bucket["output_tokens"] += rec["output_tokens"]
        bucket["cost_usd"] += rec["cost_usd"]
        total_cost += rec["cost_usd"]
        total_calls += 1

    return {"total_cost_usd": total_cost, "total_calls": total_calls, "by_call_type": by_type}


def _print_summary() -> None:
    summary = summarize()
    print(f"Total estimated spend: ${summary['total_cost_usd']:.4f} across {summary['total_calls']} calls\n")
    for call_type, bucket in sorted(summary["by_call_type"].items()):
        print(
            f"  {call_type:>10}: {bucket['calls']:>5} calls, "
            f"{bucket['input_tokens']:>10,} in / {bucket['output_tokens']:>9,} out tokens, "
            f"${bucket['cost_usd']:.4f}"
        )


if __name__ == "__main__":
    _print_summary()
