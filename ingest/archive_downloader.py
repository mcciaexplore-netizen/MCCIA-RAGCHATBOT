"""Standalone chronological downloader for the approved MCCI/Sampada Drive
archive. DOWNLOAD + VALIDATION ONLY -- this never OCRs, splits articles,
embeds, or touches Neon (see run_pipeline.py for that separate, explicitly
triggered stage).

Meant to run as an ordinary, independent terminal process: once started, it
does not depend on Claude Code, this repo's dev server, or anything else
staying open. Stop it any time with Ctrl+C; re-running the same command
later picks up wherever it left off (see `run`'s resumability notes below).

Every status this module reports comes from a live Drive listing plus a
real, current-moment check of staging/raw/ -- never from a cached "already
downloaded" assumption. Reuses drive_sync.py's auth, walk, and download
mechanics rather than re-implementing them.

No true byte-range resume: drive_sync.download_file() always writes a fresh
.part from byte 0 (Drive's Python client isn't given a Range header here).
An interrupted file is safely restarted from scratch next run, not resumed
mid-file -- this module does not claim otherwise.

Usage:
    python -m ingest.archive_downloader status   # report only, never downloads
    python -m ingest.archive_downloader run       # chronological download + live dashboard
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

from db.config import google_drive_folder_id
from ingest.config import download_log, local_staging_dir
from ingest.drive_sync import (
    build_drive_service,
    download_file,
    load_drive_ids,
    save_drive_ids,
    validate_pdf,
    walk_pdfs,
)

LOCK_FILENAME = ".downloader.lock"
FAILURES_FILENAME = ".download_failures.json"
MAX_FILE_ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 3

YEAR_RE = re.compile(r"^\s*(\d{4})")


def parse_year(name: str) -> Optional[int]:
    """The leading 4-digit year in every filename observed in this archive
    (verified against a live listing of all 85 Drive PDFs, zero exceptions)
    -- not a guess, just reading what the archive's own naming convention
    already encodes. Returns None (never a guessed year) if a given name
    doesn't match, so callers can flag it rather than silently mis-sort it."""
    m = YEAR_RE.match(name)
    return int(m.group(1)) if m else None


@dataclass
class ArchiveEntry:
    name: str
    file_id: str
    drive_size: int
    year: Optional[int]
    local_path: Path
    status: str  # "complete" | "missing" | "incomplete" | "invalid"
    local_size: Optional[int] = None
    page_count: Optional[int] = None
    invalid_reason: Optional[str] = None


def _sort_key(e: ArchiveEntry):
    return (e.year is None, e.year or 0, e.name)


# ---------------------------------------------------------------------------
# Small persisted state: a lock (prevents two downloaders at once) and a
# failures record (survives across runs so `status` can show FAILED without
# a downloader running). Same co-located-sidecar convention drive_sync.py
# and run_pipeline.py already use for .drive_ids.json / .fully_processed.json.
# ---------------------------------------------------------------------------


def _lock_path(staging_dir: Path) -> Path:
    return staging_dir / LOCK_FILENAME


def _failures_path(staging_dir: Path) -> Path:
    return staging_dir / FAILURES_FILENAME


def _load_failures(staging_dir: Path) -> dict:
    path = _failures_path(staging_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_failures(staging_dir: Path, failures: dict) -> None:
    _failures_path(staging_dir).write_text(json.dumps(failures, indent=2, sort_keys=True))


def _log_event(event: str, **fields) -> None:
    path = download_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, **fields}
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else
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
                f"Another archive downloader is already running against {staging_dir} "
                f"(PID {pid}, started {info.get('started_at', 'unknown time')}). "
                f"Refusing to start a second one -- stop that one first (Ctrl+C in its terminal) "
                f"or, if it's truly dead, remove {lock_path}."
            )
        print(f"[LOCK] Found a stale lock (PID {pid} is not running) -- clearing it and continuing.")
    lock_path.write_text(json.dumps({"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}))


def release_lock(staging_dir: Path) -> None:
    _lock_path(staging_dir).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Archive status -- the single source of truth both `status` and `run` use.
# ---------------------------------------------------------------------------


def build_archive_status(service, staging_dir: Path) -> List[ArchiveEntry]:
    drive_files = list(walk_pdfs(service, google_drive_folder_id()))
    entries: List[ArchiveEntry] = []
    for f in drive_files:
        local_path = staging_dir / f.name
        part_path = local_path.with_suffix(local_path.suffix + ".part")
        year = parse_year(f.name)

        if local_path.exists() and local_path.stat().st_size == f.size:
            valid, page_count, reason = validate_pdf(local_path)
            if valid:
                status, invalid_reason = "complete", None
            else:
                status, invalid_reason = "invalid", reason
            entries.append(
                ArchiveEntry(
                    name=f.name,
                    file_id=f.file_id,
                    drive_size=f.size,
                    year=year,
                    local_path=local_path,
                    status=status,
                    local_size=local_path.stat().st_size,
                    page_count=page_count,
                    invalid_reason=invalid_reason,
                )
            )
        elif local_path.exists():
            # Present under the right name but the wrong size -- not safely
            # resumable (see module docstring), so this is treated the same
            # as an incomplete .part: needs a fresh download.
            entries.append(
                ArchiveEntry(
                    name=f.name,
                    file_id=f.file_id,
                    drive_size=f.size,
                    year=year,
                    local_path=local_path,
                    status="incomplete",
                    local_size=local_path.stat().st_size,
                )
            )
        elif part_path.exists():
            entries.append(
                ArchiveEntry(
                    name=f.name,
                    file_id=f.file_id,
                    drive_size=f.size,
                    year=year,
                    local_path=local_path,
                    status="incomplete",
                    local_size=part_path.stat().st_size,
                )
            )
        else:
            entries.append(
                ArchiveEntry(
                    name=f.name, file_id=f.file_id, drive_size=f.size, year=year, local_path=local_path, status="missing"
                )
            )
    return entries


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


def _year_label(e: ArchiveEntry) -> str:
    return str(e.year) if e.year is not None else "DATE NOT VERIFIED"


def print_status(entries: List[ArchiveEntry], staging_dir: Path) -> None:
    complete = [e for e in entries if e.status == "complete"]
    missing = [e for e in entries if e.status == "missing"]
    incomplete = [e for e in entries if e.status == "incomplete"]
    invalid = [e for e in entries if e.status == "invalid"]

    downloaded_bytes = sum(e.local_size or 0 for e in complete)
    remaining_bytes = sum(e.drive_size for e in missing + incomplete + invalid)

    print("=" * 66)
    print("MCCI ARCHIVE STATUS")
    print("=" * 66)
    print(f"Total Drive PDFs:  {len(entries)}")
    print(f"Downloaded:        {len(complete)}")
    print(f"Remaining:         {len(missing)}")
    print(f"Incomplete:        {len(incomplete)}")
    print(f"Invalid:           {len(invalid)}")
    print()
    print(f"Downloaded size:   {_human_size(downloaded_bytes)}")
    print(f"Remaining size:    {_human_size(remaining_bytes)} (Drive-reported sizes, estimate)")
    print()

    print("DOWNLOADED ✓")
    for e in sorted(complete, key=_sort_key):
        print(f"  {_year_label(e):>18}  {e.name}  ({e.page_count} pages)")
    if not complete:
        print("  (none)")
    print()

    print("REMAINING")
    for e in sorted(missing, key=_sort_key):
        print(f"  {_year_label(e):>18}  {e.name}  ({_human_size(e.drive_size)})")
    if not missing:
        print("  (none)")
    print()

    print("INCOMPLETE")
    for e in sorted(incomplete, key=_sort_key):
        print(f"  {_year_label(e):>18}  {e.name}  ({_human_size(e.local_size)} / {_human_size(e.drive_size)})")
    if not incomplete:
        print("  (none)")
    print()

    print("INVALID")
    for e in sorted(invalid, key=_sort_key):
        print(f"  {_year_label(e):>18}  {e.name}  -- {e.invalid_reason}")
    if not invalid:
        print("  (none)")
    print()

    failures = _load_failures(staging_dir)
    print("FAILED (persisted across runs)")
    if failures:
        for name, info in sorted(failures.items()):
            print(f"  {name}  -- {info.get('error')}  (retries: {info.get('retries')}, last attempt {info.get('last_attempt')})")
    else:
        print("  (none)")


# ---------------------------------------------------------------------------
# `run`: chronological download with a live terminal dashboard.
# ---------------------------------------------------------------------------


@dataclass
class RunState:
    total: int
    complete_count: int
    to_download: List[ArchiveEntry]
    failed_count: int = 0
    recently_completed: list = field(default_factory=list)
    session_bytes_downloaded: int = 0
    session_start: float = field(default_factory=time.monotonic)
    current: Optional[dict] = None


def _clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")


def render(state: RunState, position_in_queue: int) -> None:
    remaining = len(state.to_download) - position_in_queue
    lines = [
        "MCCI GOOGLE — ARCHIVE DOWNLOAD",
        "",
        f"Total PDFs:        {state.total}",
        f"Downloaded:        {state.complete_count}",
        f"Remaining:         {remaining}",
        f"Downloading:       {1 if state.current else 0}",
        f"Failed:            {state.failed_count}",
        "",
        "-" * 56,
        "CURRENT PDF",
        "",
    ]

    if state.current:
        c = state.current
        lines.append(f"Archive position:  {position_in_queue + 1} / {len(state.to_download)}")
        lines.append(f"Year:              {c['year'] if c['year'] is not None else 'DATE NOT VERIFIED'}")
        lines.append(f"Filename:          {c['name']}")
        lines.append(f"Status:            {c['phase']}")
        total_bytes = c.get("total_bytes")
        downloaded = c["downloaded_bytes"]
        if total_bytes:
            pct = downloaded / total_bytes * 100
            lines.append(f"Progress:          {_human_size(downloaded)} / {_human_size(total_bytes)}")
            lines.append(f"Percentage:        {pct:.1f}%")
        elapsed = time.monotonic() - c["start_ts"]
        speed = downloaded / elapsed if elapsed > 0 else 0
        lines.append(f"Speed:             {_human_size(speed)}/s" if speed else "Speed:             measuring...")
        lines.append(f"Elapsed:           {_fmt_duration(elapsed)}")
        if speed > 0 and total_bytes:
            eta = (total_bytes - downloaded) / speed
            lines.append(f"ETA (this file):   ~{_fmt_duration(eta)} (estimate)")
        lines.append(f"Retries:           {c.get('attempt', 1) - 1}")
    else:
        lines.append("(idle)")

    lines += ["", "-" * 56, "RECENTLY COMPLETED"]
    if state.recently_completed:
        for year, name in state.recently_completed[-3:]:
            label = year if year is not None else "DATE NOT VERIFIED"
            lines.append(f"  ✓ {label}  {name}")
    else:
        lines.append("  (none yet)")

    lines += ["", "NEXT"]
    upcoming = state.to_download[position_in_queue + 1 : position_in_queue + 4]
    if upcoming:
        for e in upcoming:
            lines.append(f"  {_year_label(e)}  {e.name}")
    else:
        lines.append("  (none)")

    session_elapsed = time.monotonic() - state.session_start
    lines += ["", f"Session elapsed: {_fmt_duration(session_elapsed)}   Session downloaded: {_human_size(state.session_bytes_downloaded)}"]
    if state.session_bytes_downloaded > 0 and session_elapsed > 0:
        avg_speed = state.session_bytes_downloaded / session_elapsed
        remaining_bytes_total = sum(e.drive_size for e in state.to_download[position_in_queue:])
        if avg_speed > 0:
            overall_eta = remaining_bytes_total / avg_speed
            lines.append(f"Overall ETA: ~{_fmt_duration(overall_eta)} (rough estimate, this session's average speed so far)")

    lines += ["", "Press Ctrl+C to stop safely."]

    _clear_screen()
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def cmd_run(_args) -> None:
    staging_dir = local_staging_dir()
    staging_dir.mkdir(parents=True, exist_ok=True)
    acquire_lock(staging_dir)
    try:
        service = build_drive_service()
        print("Checking archive status against live Google Drive listing...")
        entries = build_archive_status(service, staging_dir)
        print_status(entries, staging_dir)

        to_download = sorted(
            [e for e in entries if e.status in ("missing", "incomplete", "invalid")], key=_sort_key
        )
        if not to_download:
            print("\nNothing to download -- archive is already complete.")
            return

        print(f"\n{len(to_download)} PDF(s) to download, oldest to newest. Starting in 3s (Ctrl+C to cancel)...")
        time.sleep(3)

        state = RunState(
            total=len(entries),
            complete_count=sum(1 for e in entries if e.status == "complete"),
            to_download=to_download,
        )
        drive_ids = load_drive_ids(staging_dir)
        failures = _load_failures(staging_dir)

        for i, entry in enumerate(to_download):
            dest = entry.local_path
            part_path = dest.with_suffix(dest.suffix + ".part")
            if dest.exists() and entry.status in ("incomplete", "invalid"):
                dest.unlink()
            part_path.unlink(missing_ok=True)

            attempt = 0
            success = False
            last_error = None

            while attempt < MAX_FILE_ATTEMPTS and not success:
                attempt += 1
                state.current = {
                    "name": entry.name,
                    "year": entry.year,
                    "phase": "DOWNLOADING",
                    "downloaded_bytes": 0,
                    "total_bytes": entry.drive_size,
                    "start_ts": time.monotonic(),
                    "attempt": attempt,
                }
                render(state, i)
                _log_event("started", filename=entry.name, drive_file_id=entry.file_id, attempt=attempt)

                def _progress(downloaded, total, _state=state, _i=i):
                    _state.current["downloaded_bytes"] = downloaded
                    _state.current["total_bytes"] = total or _state.current["total_bytes"]
                    render(_state, _i)

                try:
                    download_file(service, entry.file_id, dest, progress_cb=_progress)
                except Exception as exc:
                    last_error = repr(exc)
                    _log_event("failed", filename=entry.name, drive_file_id=entry.file_id, attempt=attempt, error=last_error)
                    if attempt < MAX_FILE_ATTEMPTS:
                        state.current["phase"] = f"RETRYING ({attempt}/{MAX_FILE_ATTEMPTS})"
                        render(state, i)
                        time.sleep(RETRY_PAUSE_SECONDS)
                    continue

                state.current["phase"] = "VALIDATING"
                render(state, i)
                valid, page_count, reason = validate_pdf(dest)
                if not valid:
                    last_error = f"downloaded but failed PDF validation: {reason}"
                    _log_event("failed", filename=entry.name, drive_file_id=entry.file_id, attempt=attempt, error=last_error)
                    dest.unlink(missing_ok=True)
                    if attempt < MAX_FILE_ATTEMPTS:
                        state.current["phase"] = f"RETRYING ({attempt}/{MAX_FILE_ATTEMPTS})"
                        render(state, i)
                        time.sleep(RETRY_PAUSE_SECONDS)
                    continue

                success = True
                drive_ids[entry.name] = entry.file_id
                save_drive_ids(staging_dir, drive_ids)
                failures.pop(entry.name, None)
                _save_failures(staging_dir, failures)
                _log_event("validated", filename=entry.name, drive_file_id=entry.file_id, page_count=page_count)
                state.complete_count += 1
                state.session_bytes_downloaded += entry.drive_size
                state.recently_completed.append((entry.year, entry.name))
                state.current["phase"] = f"DONE ✓ ({page_count} pages)"
                render(state, i)
                time.sleep(1)

            if not success:
                state.failed_count += 1
                failures[entry.name] = {
                    "drive_file_id": entry.file_id,
                    "year": entry.year,
                    "error": last_error,
                    "retries": attempt,
                    "last_attempt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                _save_failures(staging_dir, failures)
                _log_event("failed_final", filename=entry.name, drive_file_id=entry.file_id, error=last_error)

            state.current = None

        _clear_screen()
        print("=" * 66)
        print("FINAL ARCHIVE STATUS")
        print("=" * 66)
        final_entries = build_archive_status(service, staging_dir)
        print_status(final_entries, staging_dir)
    except KeyboardInterrupt:
        print(
            "\n\n[STOPPED] Ctrl+C received -- exiting safely.\n"
            "Any file mid-download when you stopped has its .part left on disk as-is\n"
            "(no partial file is ever renamed into a completed name).\n"
            "There is no byte-range resume: re-running the same command restarts just\n"
            "that one file from 0%, and skips everything already completed."
        )
    finally:
        release_lock(staging_dir)


def cmd_status(_args) -> None:
    staging_dir = local_staging_dir()
    print("Checking archive status against live Google Drive listing (read-only, no downloads)...")
    service = build_drive_service()
    entries = build_archive_status(service, staging_dir)
    print_status(entries, staging_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Report archive status against live Drive; never downloads")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser(
        "run", help="Chronologically download every missing/incomplete/invalid PDF, one at a time, with a live dashboard"
    )
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    load_dotenv()
    sys.exit(main())
