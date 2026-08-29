"""Log PDFs the pipeline couldn't confidently handle, instead of guessing."""

import csv
from typing import Set

from ingest.config import manual_review_log as _manual_review_log_path


def log_manual_review(filename: str, reason: str) -> None:
    path = _manual_review_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(["filename", "reason"])
        writer.writerow([filename, reason])


def manual_review_filenames() -> Set[str]:
    """Every filename with at least one logged entry -- the read-side
    counterpart to log_manual_review(), used by archive_processor.py's
    status report. Returns an empty set if the log doesn't exist yet."""
    path = _manual_review_log_path()
    if not path.exists():
        return set()
    with path.open(newline="") as fh:
        return {row["filename"] for row in csv.DictReader(fh)}
