import pytest

from ingest.pdf_cost_report import _build_attempts, _print_report, build_report


def _started(name, ts):
    return {"event": "file_started", "filename": name, "ts": ts}


def _completed(name, ts):
    return {"event": "file_completed", "filename": name, "ts": ts}


def _failed(name, ts):
    return {"event": "file_failed", "filename": name, "ts": ts}


def _usage(ts, input_tokens=10, output_tokens=5, cost_usd=0.01, call_type="ocr"):
    return {
        "ts": ts,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "call_type": call_type,
    }


class TestBuildAttempts:
    def test_pairs_started_with_completed(self):
        events = [_started("a.pdf", 1.0), _completed("a.pdf", 2.0)]
        attempts = _build_attempts(events)
        assert len(attempts) == 1
        assert attempts[0].filename == "a.pdf"
        assert attempts[0].start_ts == 1.0
        assert attempts[0].end_ts == 2.0
        assert attempts[0].status == "completed"

    def test_pairs_started_with_failed(self):
        events = [_started("a.pdf", 1.0), _failed("a.pdf", 2.0)]
        attempts = _build_attempts(events)
        assert attempts[0].status == "failed"

    def test_recurring_filename_tracked_as_separate_attempts(self):
        # Retry after failure -- must not collapse into one row.
        events = [
            _started("a.pdf", 1.0),
            _failed("a.pdf", 2.0),
            _started("a.pdf", 3.0),
            _completed("a.pdf", 4.0),
        ]
        attempts = _build_attempts(events)
        assert len(attempts) == 2
        assert attempts[0].status == "failed"
        assert attempts[1].status == "completed"

    def test_unclosed_attempt_marked_interrupted_by_next_start(self):
        # Simulates a crash/Ctrl+C: no file_completed/file_failed was ever
        # logged for the first attempt before the file was retried.
        events = [
            _started("a.pdf", 1.0),
            _started("a.pdf", 5.0),
            _completed("a.pdf", 6.0),
        ]
        attempts = _build_attempts(events)
        assert len(attempts) == 2
        assert attempts[0].status == "interrupted"
        assert attempts[0].end_ts == 5.0
        assert attempts[1].status == "completed"
        assert attempts[1].end_ts == 6.0

    def test_still_open_attempt_left_with_no_end_ts(self):
        attempts = _build_attempts([_started("a.pdf", 1.0)])
        assert attempts[0].end_ts is None
        assert attempts[0].status == "in_progress"

    def test_ignores_events_without_filename(self):
        assert _build_attempts([{"event": "some_other_event", "ts": 1.0}]) == []

    def test_completion_event_for_unknown_filename_is_ignored(self):
        # e.g. log truncated between file_started and file_completed.
        assert _build_attempts([_completed("ghost.pdf", 1.0)]) == []


class TestBuildReport:
    def test_attributes_usage_within_window(self):
        events = [_started("a.pdf", 10.0), _completed("a.pdf", 20.0)]
        usage = [_usage(15.0, input_tokens=100, output_tokens=50, cost_usd=0.5, call_type="ocr")]

        attempts, unattributed = build_report(events, usage)

        assert unattributed == []
        a = attempts[0]
        assert a.calls == 1
        assert a.input_tokens == 100
        assert a.output_tokens == 50
        assert a.cost_usd == 0.5
        assert a.by_call_type == {"ocr": {"calls": 1, "cost_usd": 0.5}}

    def test_usage_outside_every_window_is_unattributed(self):
        events = [_started("a.pdf", 10.0), _completed("a.pdf", 20.0)]
        usage = [_usage(30.0, cost_usd=0.2)]

        attempts, unattributed = build_report(events, usage)

        assert attempts[0].calls == 0
        assert len(unattributed) == 1
        assert unattributed[0]["cost_usd"] == 0.2

    def test_multiple_calls_accumulate_on_same_attempt(self):
        events = [_started("a.pdf", 10.0), _completed("a.pdf", 20.0)]
        usage = [
            _usage(12.0, cost_usd=0.1, call_type="ocr"),
            _usage(14.0, cost_usd=0.2, call_type="ocr"),
        ]

        attempts, _ = build_report(events, usage)

        a = attempts[0]
        assert a.calls == 2
        assert a.cost_usd == pytest.approx(0.3)
        assert a.by_call_type["ocr"]["calls"] == 2

    def test_still_open_attempt_charged_every_record_from_its_start_onward(self):
        # Nothing ever closed this attempt (run killed without a final log
        # line) -- it should be charged everything logged after its start.
        events = [_started("a.pdf", 10.0)]
        usage = [_usage(15.0, cost_usd=0.1), _usage(50.0, cost_usd=0.2)]

        attempts, unattributed = build_report(events, usage)

        a = attempts[0]
        assert a.end_ts == 50.0
        assert a.calls == 2
        assert unattributed == []

    def test_overlapping_windows_attribute_to_earlier_attempt(self):
        # Documents the current tie-break: when an interrupted attempt's
        # end_ts lands exactly on the next attempt's start_ts, a usage
        # record at that exact timestamp goes to the FIRST attempt in list
        # order, not the one actually running the call.
        events = [
            _started("a.pdf", 1.0),
            _started("a.pdf", 5.0),  # closes the first attempt as "interrupted" at ts=5.0
            _completed("a.pdf", 10.0),
        ]
        usage = [_usage(5.0, cost_usd=0.4)]

        attempts, _ = build_report(events, usage)

        assert attempts[0].status == "interrupted"
        assert attempts[0].calls == 1
        assert attempts[1].calls == 0

    def test_no_events_and_no_usage_returns_empty(self):
        attempts, unattributed = build_report([], [])
        assert attempts == []
        assert unattributed == []


class TestPrintReport:
    def test_reports_nothing_run_yet_when_no_processing_log(self, monkeypatch, capsys):
        monkeypatch.setattr("ingest.pdf_cost_report.build_report", lambda: ([], []))
        monkeypatch.setattr(
            "ingest.pdf_cost_report.summarize", lambda: {"total_cost_usd": 0.0, "total_calls": 0}
        )

        _print_report()

        out = capsys.readouterr().out
        assert "nothing has been run" in out

    def test_reports_unattributed_calls(self, monkeypatch, capsys):
        attempt_events = [_started("a.pdf", 10.0), _completed("a.pdf", 20.0)]
        attempts, unattributed = build_report(attempt_events, [_usage(30.0, cost_usd=0.2)])
        monkeypatch.setattr("ingest.pdf_cost_report.build_report", lambda: (attempts, unattributed))
        monkeypatch.setattr(
            "ingest.pdf_cost_report.summarize", lambda: {"total_cost_usd": 0.2, "total_calls": 1}
        )

        _print_report()

        out = capsys.readouterr().out
        assert "a.pdf" in out
        assert "1 call(s) totalling $0.2000 fall outside" in out
