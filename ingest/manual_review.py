"""Log PDFs the pipeline couldn't confidently handle, instead of guessing."""

import csv

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
