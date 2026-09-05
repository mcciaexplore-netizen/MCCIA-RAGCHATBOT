import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from ingest.gemini_retry import GEMINI_REQUEST_TIMEOUT_MS, call_with_retry, gemini_client


def _server_error(code: int) -> ServerError:
    return ServerError(code, {"error": {"code": code, "status": "UNAVAILABLE"}})


def test_retries_transient_server_errors_with_exponential_backoff():
    attempts = 0
    delays = []

    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _server_error(503)
        return "ok"

    result = call_with_retry(
        "test",
        flaky_call,
        max_attempts=5,
        base_delay_seconds=0.5,
        sleep=delays.append,
    )

    assert result == "ok"
    assert attempts == 3
    assert delays == [0.5, 1.0]


def test_raises_after_the_final_transient_attempt():
    attempts = 0

    def unavailable():
        nonlocal attempts
        attempts += 1
        raise _server_error(503)

    with pytest.raises(ServerError):
        call_with_retry("test", unavailable, max_attempts=3, sleep=lambda _delay: None)

    assert attempts == 3


def test_does_not_retry_permanent_client_errors():
    attempts = 0

    def invalid_request():
        nonlocal attempts
        attempts += 1
        raise ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})

    with pytest.raises(ClientError):
        call_with_retry("test", invalid_request, sleep=lambda _delay: None)

    assert attempts == 1


def test_is_transient_override_lets_another_api_reuse_this_backoff_loop():
    # e.g. ingest/drive_sync.py, whose errors aren't google.genai APIErrors.
    attempts = 0

    def flaky_download():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise TimeoutError("read timed out")
        return "downloaded"

    result = call_with_retry(
        "test",
        flaky_download,
        sleep=lambda _delay: None,
        is_transient=lambda exc: isinstance(exc, TimeoutError),
    )

    assert result == "downloaded"
    assert attempts == 2


def test_is_transient_override_still_raises_for_errors_it_does_not_recognize():
    with pytest.raises(ValueError):
        call_with_retry(
            "test",
            lambda: (_ for _ in ()).throw(ValueError("not retryable")),
            sleep=lambda _delay: None,
            is_transient=lambda exc: isinstance(exc, TimeoutError),
        )


def test_retries_a_timed_out_request_with_the_default_predicate():
    # Regression test: a request timeout (see GEMINI_REQUEST_TIMEOUT_MS) is a
    # raw httpx exception, not a google.genai APIError -- confirmed live that
    # a hung OCR request never raised anything at all before a timeout was
    # added; this checks the timeout's exception actually gets retried
    # instead of failing on the first attempt.
    attempts = 0

    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.TimeoutException("timed out waiting for a response")
        return "ok"

    result = call_with_retry("test", flaky_call, max_attempts=5, base_delay_seconds=0.1, sleep=lambda _d: None)

    assert result == "ok"
    assert attempts == 3


def test_retries_a_connection_error_with_the_default_predicate():
    attempts = 0

    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise httpx.ConnectError("connection refused")
        return "ok"

    result = call_with_retry("test", flaky_call, sleep=lambda _d: None)

    assert result == "ok"
    assert attempts == 2


def test_gemini_client_configures_a_request_timeout(monkeypatch):
    # Regression test: gemini_client() used to build a plain genai.Client()
    # with no timeout at all -- confirmed live that a request can then hang
    # indefinitely (an established, idle connection, 0% CPU, no progress for
    # minutes) rather than ever raising something retryable.
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    client = gemini_client()
    assert client._api_client._http_options.timeout == GEMINI_REQUEST_TIMEOUT_MS
