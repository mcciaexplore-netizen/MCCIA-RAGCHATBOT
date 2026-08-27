import ssl

import httplib2
import pytest
from googleapiclient.errors import HttpError

from ingest.drive_sync import _is_transient_drive_error


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
