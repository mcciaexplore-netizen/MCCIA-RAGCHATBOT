import pytest
from google.genai.errors import ClientError, ServerError

from ingest.gemini_retry import call_with_retry


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
