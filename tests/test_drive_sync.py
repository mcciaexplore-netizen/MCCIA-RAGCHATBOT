import ssl

import httplib2
import pytest
from googleapiclient.errors import HttpError

from ingest.drive_sync import DriveFile, _is_transient_drive_error, download_file, sync_all


def _http_error(status: int) -> HttpError:
    resp = httplib2.Response({"status": status})
    resp.status = status
    return HttpError(resp, b"error body")


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_http_statuses_are_retried(status):
    assert _is_transient_drive_error(_http_error(status)) is True


@pytest.mark.parametrize("status", [403, 404])
def test_permanent_http_statuses_are_not_retried(status):
    assert _is_transient_drive_error(_http_error(status)) is False


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("The read operation timed out"),
        ConnectionResetError("connection reset by peer"),
        ssl.SSLError("bad handshake"),
        httplib2.ServerNotFoundError("unable to resolve host"),
    ],
)
def test_network_layer_failures_are_retried(exc):
    assert _is_transient_drive_error(exc) is True


def test_unrelated_errors_are_not_retried():
    assert _is_transient_drive_error(ValueError("not a network problem")) is False


def test_sync_all_logs_and_continues_past_a_failed_download(tmp_path, monkeypatch):
    """A single file that exhausts retries (or hits a permanent Drive error)
    must not take down the whole archive-wide sync -- the remaining files
    should still be attempted and returned."""
    files = [
        DriveFile(file_id="ok-1", name="ok-1.pdf", modified_time="", size=3),
        DriveFile(file_id="bad", name="bad.pdf", modified_time="", size=3),
        DriveFile(file_id="ok-2", name="ok-2.pdf", modified_time="", size=3),
    ]
    monkeypatch.setattr("ingest.drive_sync.walk_pdfs", lambda service, folder_id: iter(files))
    monkeypatch.setattr("ingest.drive_sync.google_drive_folder_id", lambda: "fake-folder-id")

    def fake_download(service, file_id, dest):
        if file_id == "bad":
            raise RuntimeError("simulated permanent download failure")
        dest.write_bytes(b"pdf")

    monkeypatch.setattr("ingest.drive_sync.download_file", fake_download)

    review_log = tmp_path / "manual_review.csv"
    monkeypatch.setattr("ingest.manual_review._manual_review_log_path", lambda: review_log)

    downloaded = sync_all(dest_dir=tmp_path, service=object())

    assert {p.name for p in downloaded} == {"ok-1.pdf", "ok-2.pdf"}
    assert review_log.exists()
    assert "bad.pdf" in review_log.read_text()
    assert "simulated permanent download failure" in review_log.read_text()


def test_download_file_cleans_up_partial_file_on_failure(tmp_path, monkeypatch):
    """A failed download (hundreds of MB partially written for a real bound
    volume) must not leave its .part debris behind -- the next sync starts
    that file fresh anyway."""

    class _FakeDownloader:
        def __init__(self, fh, request):
            pass

        def next_chunk(self):
            raise RuntimeError("network died mid-download")

    class _FakeFiles:
        def get_media(self, fileId):
            return object()

    class _FakeService:
        def files(self):
            return _FakeFiles()

    monkeypatch.setattr("ingest.drive_sync.MediaIoBaseDownload", _FakeDownloader)

    dest = tmp_path / "issue.pdf"
    with pytest.raises(RuntimeError):
        download_file(_FakeService(), "file-id", dest)

    assert not dest.exists()
    assert not dest.with_suffix(dest.suffix + ".part").exists()
