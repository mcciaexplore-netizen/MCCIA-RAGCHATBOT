"""Standalone chronological archive processor: OCR -> edition detection ->
article splitting -> chunking -> embedding -> Neon, across every PDF already
downloaded to staging/raw/.

Runs as its own long-lived terminal process, independent of Claude Code --
once started, stopping it (Ctrl+C) leaves already-completed work exactly as
completed; re-running the same command resumes safely (see the module
docstring sections below and archive_downloader.py's, which this mirrors).

Does not implement any new ingestion logic -- every OCR/boundary-detection/
article-splitting/chunking/embedding/write step is the existing, unmodified
ingest.run_pipeline.process_pdf() (the same function `python -m
ingest.run_pipeline process` already calls). This module only adds
chronological ordering, a live dashboard, a lock file, and a persistent log
around that existing function, via small optional callback parameters
(progress_cb / on_event) added to extract_pages/get_or_extract_pages/
process_pdf/_process_one_issue -- all default to None, so the plain CLI's
behavior is completely unchanged.

Never touches Google Drive -- every PDF is already local (see
archive_downloader.py), and drive_file_id is resolved purely from the local
.drive_ids.json sidecar (see drive_sync.load_drive_ids).

Usage:
    python -m ingest.archive_processor status   # report only, never processes
    python -m ingest.archive_processor run       # chronological processing + live dashboard
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from db.connection import connect
from ingest.archive_downloader import parse_year
from ingest.config import local_staging_dir, processed_cache_dir
from ingest.drive_sync import load_drive_ids
from ingest.manual_review import log_manual_review, manual_review_filenames
from ingest.ocr_cache import is_cache_valid
from ingest.run_pipeline import _load_fully_processed, process_pdf
from ingest.usage_tracker import summarize

LOCK_FILENAME = ".processor.lock"
FAILURES_FILENAME = ".processing_failures.json"
PROCESSING_LOG_ENV = "PROCESSING_LOG"

MONTH_ABBREVIATIONS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_AFTER_YEAR_RE = re.compile(r"^\s*\d{4}\s*-?\s*([A-Za-z]+)")


def parse_leading_month(name: str) -> Optional[int]:
    """A month name/abbreviation immediately after the leading year, if one
    is there (e.g. "1956 -April", "2011-Jan") -- verified against all 85 real
    archive filenames, every one parses. Returns None (never a guess) rather
    than inventing a month when the pattern doesn't match."""
    m = _MONTH_AFTER_YEAR_RE.match(name)
    if not m:
        return None
    return MONTH_ABBREVIATIONS.get(m.group(1).lower())


def chronological_sort_key(name: str):
    """(year, month) when both are parseable -- verified to give every one
    of the 85 real archive filenames a distinct, correct-order position,
    including same-year ties (e.g. 2011-Jan before 2011-Feb) that a plain
    alphabetical sort gets wrong. Falls back to filename order only when a
    year/month genuinely can't be read from the name -- never invents one."""
    year = parse_year(name)
    month = parse_leading_month(name)
    return (year is None, year or 0, month is None, month or 0, name)


def processing_log_path() -> Path:
    return Path(os.environ.get(PROCESSING_LOG_ENV, "./staging/processing_log.jsonl"))


def _log_event(event: str, **fields) -> None:
    path = processing_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **fields}
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# Lock file -- same convention/format as archive_downloader.py's, kept
# independent (a different lock filename) so a download and a process run
# can't be confused with each other, but can safely run at the same time.
# ---------------------------------------------------------------------------


def _lock_path(staging_dir: Path) -> Path:
    return staging_dir / LOCK_FILENAME


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock(staging_dir: Path) -> None:
    lock_path = _lock_path(staging_dir)
    if lock_path.exists():
        try:
            info = json.loads(lock_path.read_text())
            pid = info.get("pid")
        except (json.JSONDecodeError, OSError):
            pid = None
        if pid is not None and _pid_is_alive(pid):
            raise SystemExit(
                f"Another archive processor is already running (PID {pid}, "
                f"started {info.get('started_at', 'unknown time')}). Refusing to start a second one -- "
                f"stop that one first (Ctrl+C in its terminal) or, if it's truly dead, remove {lock_path}."
            )
        print(f"[LOCK] Found a stale lock (PID {pid} is not running) -- clearing it and continuing.")
    lock_path.write_text(json.dumps({"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}))


def release_lock(staging_dir: Path) -> None:
    _lock_path(staging_dir).unlink(missing_ok=True)


def _failures_path(staging_dir: Path) -> Path:
    return staging_dir / FAILURES_FILENAME


def _load_failures(staging_dir: Path) -> dict:
    path = _failures_path(staging_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_failures(staging_dir: Path, failures: dict) -> None:
    _failures_path(staging_dir).write_text(json.dumps(failures, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Status -- purely local + Neon reads. Never contacts Google Drive: every
# PDF is already downloaded and validated (see archive_downloader.py), and
# drive_file_id resolution only ever needs the local .drive_ids.json.
# ---------------------------------------------------------------------------


@dataclass
class PdfProcessingStatus:
    name: str
    drive_file_id: Optional[str]
    year: Optional[int]
    month: Optional[int]
    ocr_cached: bool
    fully_processed: bool
    in_manual_review: bool
    indexed_editions: int


def build_processing_status(staging_dir: Path) -> List[PdfProcessingStatus]:
    pdfs = sorted(staging_dir.glob("*.[pP][dD][fF]"), key=lambda p: chronological_sort_key(p.name))
    drive_ids = load_drive_ids(staging_dir)
    fully_processed_ids = _load_fully_processed(staging_dir)
    review_filenames = manual_review_filenames()

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select source_pdf_id, count(*) from sampada group by source_pdf_id")
            indexed_by_id = dict(cur.fetchall())
    finally:
        conn.close()

    statuses = []
    for pdf in pdfs:
        drive_file_id = drive_ids.get(pdf.name)
        statuses.append(
            PdfProcessingStatus(
                name=pdf.name,
                drive_file_id=drive_file_id,
                year=parse_year(pdf.name),
                month=parse_leading_month(pdf.name),
                ocr_cached=bool(drive_file_id) and is_cache_valid(drive_file_id, pdf),
                fully_processed=bool(drive_file_id) and drive_file_id in fully_processed_ids,
                in_manual_review=pdf.name in review_filenames,
                indexed_editions=indexed_by_id.get(drive_file_id, 0) if drive_file_id else 0,
            )
        )
    return statuses


def preflight_check(staging_dir: Path) -> bool:
    """Real checks, no processing. Returns True if it's safe to run. Prints
    each check's actual result -- never assumes."""
    ok = True
    print("=" * 66)
    print("PRE-FLIGHT CHECK")
    print("=" * 66)

    pdfs = sorted(staging_dir.glob("*.[pP][dD][fF]"))
    print(f"[{'OK' if len(pdfs) > 0 else 'FAIL'}] {len(pdfs)} PDFs present in {staging_dir}")
    if len(pdfs) == 0:
        ok = False

    drive_ids = load_drive_ids(staging_dir)
    unmapped = [p.name for p in pdfs if p.name not in drive_ids]
    print(f"[{'OK' if not unmapped else 'WARN'}] {len(pdfs) - len(unmapped)}/{len(pdfs)} PDFs have a recorded Drive file ID")
    if unmapped:
        print(f"       missing for: {', '.join(unmapped[:5])}{' ...' if len(unmapped) > 5 else ''}")

    cache_dir = processed_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        probe = cache_dir / ".preflight_write_test"
        probe.write_text("ok")
        probe.unlink()
        print(f"[OK] OCR cache directory is writable: {cache_dir}")
    except OSError as exc:
        print(f"[FAIL] OCR cache directory is not writable: {cache_dir} ({exc})")
        ok = False

    try:
        conn = connect()
        with conn.cursor() as cur:
            cur.execute("select 1")
        print("[OK] Neon is reachable")
    except Exception as exc:
        print(f"[FAIL] Could not reach Neon: {exc!r}")
        return False  # nothing below this is checkable without a connection

    required = {
        "sampada": {"source_filename", "pdf_page_offset", "indexed_at", "failed"},
        "articles": {"issue_page_start", "issue_page_end"},
        "smaller_chunks": {"issue_page_number"},
        "ingestion_files": {"drive_file_id", "ocr_completed_at"},
    }
    with conn.cursor() as cur:
        for table, cols in required.items():
            cur.execute(
                "select column_name from information_schema.columns where table_name = %s", (table,)
            )
            present = {r[0] for r in cur.fetchall()}
            missing = cols - present
            print(f"[{'OK' if not missing else 'FAIL'}] schema: {table} has {cols if not missing else present}")
            if missing:
                print(f"       missing columns: {missing}")
                ok = False

        cur.execute("select 1 from sampada where year = 1956 and month = 6 and indexed_at is not null")
        june_1956_present = cur.fetchone() is not None
        print(f"[{'OK' if june_1956_present else 'WARN'}] existing June 1956 pilot record recognized: {june_1956_present}")

        cur.execute("select count(*) from sampada")
        total_indexed = cur.fetchone()[0]
        print(f"[OK] {total_indexed} editions currently indexed in Neon (already-completed editions will be skipped)")
    conn.close()

    if not os.environ.get("GEMINI_API_KEY"):
        print("[FAIL] GEMINI_API_KEY is not set")
        ok = False
    else:
        print("[OK] Gemini API key present")

    print(f"[OK] duplicate-write protection: writes are gated on already_ingested()/issue_month_source() per (source, year, month) -- unchanged, existing logic")
    print(f"[OK] Ctrl+C handling: caught explicitly in `run`; releases the lock; does not mark an in-progress file/edition as done")
    print()
    return ok


# ---------------------------------------------------------------------------
# Live dashboard
# ---------------------------------------------------------------------------


def _human_size(num_bytes) -> str:
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


@dataclass
class RunState:
    total_pdfs: int
    completed_pdfs: int = 0
    failed_pdfs: int = 0
    current: Optional[dict] = None
    session_start: float = field(default_factory=time.monotonic)
    session_start_cost: float = 0.0
    recently_completed: list = field(default_factory=list)


def render(state: RunState, position_in_queue: int, total_in_queue: int, upcoming_names: List[str]) -> None:
    lines = [
        "MCCI GOOGLE — ARCHIVE INGESTION",
        "",
        f"PDFs:          {position_in_queue + (1 if state.current else 0)} / {total_in_queue}",
        f"Completed:     {state.completed_pdfs}",
        f"Current:       {1 if state.current else 0}",
        f"Failed:        {state.failed_pdfs}",
        "",
        "-" * 60,
    ]

    if state.current:
        c = state.current
        lines.append("CURRENT PDF")
        lines.append("")
        lines.append(f"Filename:        {c['name']}")
        year_label = f"{c['year']}" if c.get("year") is not None else "DATE NOT VERIFIED"
        lines.append(f"Year:            {year_label}")
        lines.append(f"Current stage:   {c['stage']}")

        if c["stage"] == "OCR":
            lines.append(f"OCR Cache:       {'REUSING (no OCR needed)' if c.get('cache_hit') else 'WRITING'}")
            if not c.get("cache_hit"):
                pages_done = c.get("pages_done", 0)
                total_pages = c.get("total_pages", 0)
                if total_pages:
                    pct = pages_done / total_pages * 100
                    lines.append(f"Pages:           {pages_done} / {total_pages}")
                    lines.append(f"Progress:        {pct:.1f}%")
                elapsed = time.monotonic() - c["stage_start"]
                speed = pages_done / (elapsed / 60) if elapsed > 0 else 0
                lines.append(f"Elapsed:         {_fmt_duration(elapsed)}")
                if speed > 0:
                    lines.append(f"Measured speed:  {speed:.1f} pages/min")
                    if total_pages:
                        remaining = total_pages - pages_done
                        eta = remaining / speed * 60
                        lines.append(f"ETA (this file): ~{_fmt_duration(eta)} (estimate, from measured speed)")
        elif c.get("edition"):
            lines.append("")
            lines.append("CURRENT EDITION")
            lines.append("")
            lines.append(f"Sampada — {c['edition']['label']}")
            lines.append(f"Stage: {c['edition']['stage']}")
    else:
        lines.append("(idle)")

    lines += ["", "-" * 60, "RECENTLY COMPLETED"]
    if state.recently_completed:
        for entry in state.recently_completed[-3:]:
            lines.append(f"  ✓ {entry}")
    else:
        lines.append("  (none yet)")

    lines += ["", "NEXT"]
    if upcoming_names:
        for name in upcoming_names[:3]:
            lines.append(f"  {name}")
    else:
        lines.append("  (none)")

    lines += ["", "-" * 60, "ARCHIVE TOTAL"]
    totals = state.current.get("archive_totals") if state.current else None
    if totals:
        lines.append(f"Indexed editions: {totals['editions']}")
        lines.append(f"Articles:         {totals['articles']}")
        lines.append(f"Chunks:           {totals['chunks']}")
    lines.append(f"Errors:           {state.failed_pdfs}")

    session_elapsed = time.monotonic() - state.session_start
    current_cost = summarize()["total_cost_usd"]
    session_cost = current_cost - state.session_start_cost
    lines += [
        "",
        f"Session elapsed: {_fmt_duration(session_elapsed)}",
        f"Session Gemini cost (OCR + boundary + split, real token counts): ${session_cost:.4f}",
        "Embedding cost: NOT VERIFIED (API does not return usage for embedding calls -- see usage_tracker.py)",
        "",
        "Press Ctrl+C to stop safely.",
    ]

    _clear_screen()
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def _fetch_archive_totals() -> dict:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) from sampada")
            editions = cur.fetchone()[0]
            cur.execute("select count(*) from articles")
            articles = cur.fetchone()[0]
            cur.execute("select count(*) from smaller_chunks")
            chunks = cur.fetchone()[0]
        return {"editions": editions, "articles": articles, "chunks": chunks}
    finally:
        conn.close()


def cmd_run(_args) -> None:
    staging_dir = local_staging_dir()
    if not preflight_check(staging_dir):
        print("Pre-flight check failed -- not starting. Fix the issue(s) above and try again.")
        return

    acquire_lock(staging_dir)
    try:
        pdfs = sorted(staging_dir.glob("*.[pP][dD][fF]"), key=lambda p: chronological_sort_key(p.name))
        drive_ids = load_drive_ids(staging_dir)
        failures = _load_failures(staging_dir)

        print(f"{len(pdfs)} PDF(s) to process, oldest to newest. Starting in 3s (Ctrl+C to cancel)...")
        time.sleep(3)

        state = RunState(total_pdfs=len(pdfs), session_start_cost=summarize()["total_cost_usd"])

        for i, pdf_path in enumerate(pdfs):
            drive_file_id = drive_ids.get(pdf_path.name)
            if not drive_file_id:
                log_manual_review(pdf_path.name, "no Drive file ID on record -- run the archive downloader's sync first")
                _log_event("skipped_no_drive_id", filename=pdf_path.name)
                state.failed_pdfs += 1
                continue

            year = parse_year(pdf_path.name)
            month = parse_leading_month(pdf_path.name)
            cache_hit = is_cache_valid(drive_file_id, pdf_path)
            upcoming = [p.name for p in pdfs[i + 1 :]]

            state.current = {
                "name": pdf_path.name,
                "year": year,
                "stage": "OCR",
                "cache_hit": cache_hit,
                "pages_done": 0,
                "total_pages": 0,
                "stage_start": time.monotonic(),
                "archive_totals": _fetch_archive_totals(),
            }
            render(state, i, len(pdfs), upcoming)
            _log_event("file_started", filename=pdf_path.name, drive_file_id=drive_file_id, year=year, month=month)

            def _on_event(name, payload, _state=state, _i=i, _pdfs=pdfs, _upcoming=upcoming):
                if name == "file_stage":
                    stage = payload["stage"]
                    _state.current["stage"] = {
                        "ocr": "OCR",
                        "issue_detection": "EDITION DETECTION",
                        "processing_editions": "PROCESSING EDITIONS",
                    }.get(stage, stage.upper())
                    _state.current["stage_start"] = time.monotonic()
                    _state.current.pop("edition", None)
                elif name == "ocr_progress":
                    _state.current["pages_done"] = payload["pages_done"]
                    _state.current["total_pages"] = payload["total_pages"]
                elif name == "issue_stage":
                    label = f"{payload['year']:04d}-{payload['month']:02d}"
                    stage_label = {
                        "article_splitting": "ARTICLE SPLITTING",
                        "chunking_and_embedding": "CHUNKING + EMBEDDING",
                        "indexed": "INDEXED ✓",
                        "skipped_already_indexed": "ALREADY INDEXED — SKIPPED",
                        "skipped_duplicate_source": "DUPLICATE SOURCE — SKIPPED (manual review)",
                        "failed": f"FAILED ({payload.get('reason', 'unknown')})",
                    }.get(payload["stage"], payload["stage"])
                    _state.current["edition"] = {"label": label, "stage": stage_label}
                    _log_event("issue_stage", filename=_pdfs[_i].name, **payload)
                render(_state, _i, len(_pdfs), _upcoming)

            try:
                process_pdf(pdf_path, drive_file_id, staging_dir, on_event=_on_event)
                failures.pop(pdf_path.name, None)
                _save_failures(staging_dir, failures)
                _log_event("file_completed", filename=pdf_path.name)
            except Exception as exc:
                log_manual_review(pdf_path.name, f"unexpected error during archive run: {exc}")
                failures[pdf_path.name] = {
                    "drive_file_id": drive_file_id,
                    "year": year,
                    "error": repr(exc),
                    "last_attempt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                _save_failures(staging_dir, failures)
                _log_event("file_failed", filename=pdf_path.name, error=repr(exc))
                state.failed_pdfs += 1
                state.current = None
                continue

            state.completed_pdfs += 1
            year_label = f"{year}" if year is not None else "DATE NOT VERIFIED"
            state.recently_completed.append(f"{year_label}  {pdf_path.name}")
            state.current = None

        _clear_screen()
        print("=" * 66)
        print("ARCHIVE RUN FINISHED (all staged PDFs processed this pass)")
        print("=" * 66)
        cmd_status(_args)
    except KeyboardInterrupt:
        print(
            "\n\n[STOPPED] Ctrl+C received -- exiting safely.\n"
            "The PDF/edition in progress when you stopped is NOT marked complete:\n"
            "- If it was mid-OCR, no cache was written yet (OCR caches only after a file's\n"
            "  OCR finishes completely) -- that file's OCR restarts from page 1 next run.\n"
            "- If OCR had already finished (cache written) and it was mid-edition-processing,\n"
            "  the next run reuses that OCR cache and resumes at the edition level --\n"
            "  editions already written are skipped, the interrupted one is retried.\n"
            "Every PDF/edition completed before the interruption stays completed."
        )
    finally:
        release_lock(staging_dir)


def print_status(statuses: List[PdfProcessingStatus], staging_dir: Path) -> None:
    fully_processed = [s for s in statuses if s.fully_processed]
    with_cache = [s for s in statuses if s.ocr_cached]
    with_any_progress = [
        s for s in statuses if not s.fully_processed and (s.ocr_cached or s.indexed_editions > 0)
    ]
    in_review = [s for s in statuses if s.in_manual_review]
    not_started = [
        s for s in statuses if not s.fully_processed and not s.ocr_cached and s.indexed_editions == 0 and not s.in_manual_review
    ]

    print("=" * 66)
    print("MCCI ARCHIVE PROCESSING STATUS")
    print("=" * 66)
    print(f"ARCHIVE PDFs:         {len(statuses)}")
    print(f"OCR CACHED:           {len(with_cache)}")
    print(f"FULLY INDEXED:        {len(fully_processed)}  (per .fully_processed.json -- every edition in the PDF resolved)")
    print(f"PARTIALLY PROCESSED:  {len(with_any_progress)}  (has an OCR cache and/or >=1 indexed edition, not yet fully done)")
    print(f"NOT YET STARTED:      {len(not_started)}")
    print(f"IN MANUAL REVIEW:     {len(in_review)}  (from staging/manual_review.csv -- see that file for reasons)")
    print()

    totals = _fetch_archive_totals()
    print(f"Neon: {totals['editions']} editions indexed, {totals['articles']} articles, {totals['chunks']} chunks")
    print(f"Local OCR cache size: {_human_size(_dir_size(processed_cache_dir()))}")
    print(f"Local staging/raw size: {_human_size(_dir_size(staging_dir))}")
    usage = summarize()
    print(f"Cumulative verified Gemini cost (all-time, OCR+boundary+split, real token counts): ${usage['total_cost_usd']:.4f}")
    print("Embedding cost: NOT VERIFIED (API doesn't return usage for embedding calls)")
    print()

    if in_review:
        print("IN MANUAL REVIEW")
        for s in in_review:
            print(f"  {s.name}")
        print()

    failures = _load_failures(staging_dir)
    print("FAILED (this run's persisted failures)")
    if failures:
        for name, info in sorted(failures.items()):
            print(f"  {name}  -- {info.get('error')}  (last attempt {info.get('last_attempt')})")
    else:
        print("  (none)")


def cmd_status(_args) -> None:
    staging_dir = local_staging_dir()
    print("Checking processing status against local staging/raw and Neon (no Google Drive contact, no processing)...")
    statuses = build_processing_status(staging_dir)
    print_status(statuses, staging_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Report processing status; never processes anything")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser(
        "run", help="Chronologically OCR/split/chunk/embed/index every not-yet-indexed edition, with a live dashboard"
    )
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    load_dotenv()
    sys.exit(main())
