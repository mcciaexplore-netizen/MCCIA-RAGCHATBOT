"""Per-PDF Gemini cost breakdown, on top of usage_tracker's running total.

usage_tracker.py logs every Gemini call (see log_usage) but not which PDF
triggered it. archive_processor.py's `run` command separately logs
file_started/file_completed/file_failed events with real timestamps (see
processing_log_path() there) whenever it processes a PDF -- this module
correlates the two by timestamp window to attribute cost per PDF.

Only covers PDFs processed via `python -m ingest.archive_processor run`.
`python -m ingest.run_pipeline process` does not wire up on_event, so it
writes nothing to processing_log.jsonl -- any Gemini calls made that way
show up in the "unattributed" bucket below, not against a filename.

Usage:
    python -m ingest.pdf_cost_report
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ingest.archive_processor import _fmt_duration, processing_log_path
from ingest.config import usage_log as _usage_log_path
from ingest.usage_tracker import summarize


@dataclass
class PdfAttempt:
    filename: str
    start_ts: float
    end_ts: Optional[float] = None
    status: str = "in_progress"  # "completed" | "failed" | "interrupted" | "in_progress"
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_call_type: dict = field(default_factory=dict)


def _load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _build_attempts(events: List[dict]) -> List[PdfAttempt]:
    """Pairs file_started with the event that ends it, in log order.

    A filename can recur (retry after failure, cache-hit reprocessing), so
    attempts are tracked separately in the order they happened rather than
    collapsed by filename.
    """
    attempts: List[PdfAttempt] = []
    open_by_name: dict = {}

    for ev in events:
        name = ev.get("filename")
        if name is None:
            continue
        if ev["event"] == "file_started":
            if name in open_by_name:
                # Prior attempt never got a file_completed/file_failed (e.g.
                # a Ctrl+C or crash) -- close it out at this new start.
                open_by_name[name].end_ts = ev["ts"]
                open_by_name[name].status = "interrupted"
            attempt = PdfAttempt(filename=name, start_ts=ev["ts"])
            attempts.append(attempt)
            open_by_name[name] = attempt
        elif ev["event"] in ("file_completed", "file_failed"):
            attempt = open_by_name.pop(name, None)
            if attempt is not None:
                attempt.end_ts = ev["ts"]
                attempt.status = "completed" if ev["event"] == "file_completed" else "failed"

    return attempts


def build_report(
    processing_events: Optional[List[dict]] = None,
    usage_records: Optional[List[dict]] = None,
) -> tuple:
    """Returns (attempts, unattributed) -- unattributed is usage_log rows
    that fall outside every known file_started..end window."""
    processing_events = (
        processing_events if processing_events is not None else _load_jsonl(processing_log_path())
    )
    usage_records = usage_records if usage_records is not None else _load_jsonl(_usage_log_path())

    attempts = _build_attempts(processing_events)
    # Any attempt still open at the end of the log is genuinely in progress
    # (or the run was killed without logging anything else) -- charge it
    # every usage record from its start onward.
    last_ts = max((r["ts"] for r in usage_records), default=0.0)
    for attempt in attempts:
        if attempt.end_ts is None:
            attempt.end_ts = max(attempt.start_ts, last_ts)

    unattributed: List[dict] = []
    for rec in usage_records:
        ts = rec["ts"]
        target = next((a for a in attempts if a.start_ts <= ts <= a.end_ts), None)
        if target is None:
            unattributed.append(rec)
            continue
        target.calls += 1
        target.input_tokens += rec["input_tokens"]
        target.output_tokens += rec["output_tokens"]
        target.cost_usd += rec["cost_usd"]
        bucket = target.by_call_type.setdefault(rec["call_type"], {"calls": 0, "cost_usd": 0.0})
        bucket["calls"] += 1
        bucket["cost_usd"] += rec["cost_usd"]

    return attempts, unattributed


def _print_report() -> None:
    attempts, unattributed = build_report()
    grand_total = summarize()

    print(f"Total spend so far (all Gemini calls, all time): ${grand_total['total_cost_usd']:.4f} "
          f"across {grand_total['total_calls']} calls\n")

    if not attempts:
        print("No processing_log.jsonl events found -- nothing has been run via "
              "`python -m ingest.archive_processor run` yet, so no PDF can be attributed.")
    else:
        print(f"{'PDF':<28} {'status':<12} {'duration':<10} {'calls':>6} {'cost':>10}")
        print("-" * 70)
        completed_costs = []
        for a in attempts:
            duration = _fmt_duration(a.end_ts - a.start_ts)
            print(f"{a.filename:<28} {a.status:<12} {duration:<10} {a.calls:>6} ${a.cost_usd:>9.4f}")
            if a.status == "completed":
                completed_costs.append(a.cost_usd)

        if completed_costs:
            avg = sum(completed_costs) / len(completed_costs)
            print("-" * 70)
            print(f"Average cost per successfully-completed PDF: ${avg:.4f} "
                  f"(over {len(completed_costs)} completed attempt(s); "
                  f"$0 entries are cache hits that made no new API calls)")

    if unattributed:
        cost = sum(r["cost_usd"] for r in unattributed)
        print(f"\n{len(unattributed)} call(s) totalling ${cost:.4f} fall outside any tracked PDF window "
              f"(likely run via `python -m ingest.run_pipeline process`, which doesn't log per-file events).")


if __name__ == "__main__":
    _print_report()
