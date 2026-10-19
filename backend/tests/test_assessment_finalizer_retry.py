"""#121: a stalled scoring/summary chain is retried, and its retry calls keep
the executor's Tool required until the write is saved."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from app.modules.learning import finalizer
from app.modules.workspace import team_runtime


def _finalizer() -> finalizer.AssessmentFinalizer:
    return finalizer.AssessmentFinalizer(
        lambda: None,  # type: ignore[arg-type,return-value]
        lambda: SimpleNamespace(llm_provider="dashscope"),  # type: ignore[arg-type,return-value]
    )


def _wait_for(predicate: Any, seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)


def test_a_stalled_chain_is_retried_with_backoff_then_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    lock = threading.Lock()

    def stalled(_factory: Any, _settings: Any, conversation_id: str) -> bool:
        with lock:
            calls.append(conversation_id)
        return True

    monkeypatch.setattr(finalizer, "drive_assessment", stalled)
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.01, 0.02))
    runner = _finalizer()
    try:
        runner.wake("c-1")
        _wait_for(lambda: len(calls) >= 3)
        time.sleep(0.2)
        # The first run plus one per delay; then it waits for a new wake.
        assert calls == ["c-1"] * 3
        runner.wake("c-1")  # the student's next message
        _wait_for(lambda: len(calls) >= 4)
        time.sleep(0.1)
        assert len(calls) == 4
    finally:
        runner.close()


def test_a_saved_step_resets_the_retry_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter([True, False, True, True, True])
    calls: list[str] = []

    def drive(_factory: Any, _settings: Any, conversation_id: str) -> bool:
        calls.append(conversation_id)
        return next(results)

    monkeypatch.setattr(finalizer, "drive_assessment", drive)
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.01,))
    runner = _finalizer()
    try:
        runner.wake("c-2")
        _wait_for(lambda: len(calls) >= 2)
        time.sleep(0.1)
        assert len(calls) == 2  # stalled, retried once, then saved
        runner.wake("c-2")  # a later round stalls: it has its retry again
        _wait_for(lambda: len(calls) >= 4)
        time.sleep(0.1)
        assert len(calls) == 4
    finally:
        runner.close()


def test_a_busy_refusal_is_retried_like_a_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.errors import PlatformError

    calls: list[str] = []

    def busy(_factory: Any, _settings: Any, conversation_id: str) -> bool:
        calls.append(conversation_id)
        raise PlatformError("write_pressure", "busy", 503, {"retryable": True})

    monkeypatch.setattr(finalizer, "drive_assessment", busy)
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.01,))
    runner = _finalizer()
    try:
        runner.wake("c-4")
        _wait_for(lambda: len(calls) >= 2)
        # Busy refusals keep retrying (see the never-run-out test below).
        assert calls[:2] == ["c-4", "c-4"]
    finally:
        runner.close()


def test_close_cancels_a_pending_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        finalizer, "drive_assessment", lambda _f, _s, cid: calls.append(cid) or True
    )
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.2,))
    runner = _finalizer()
    runner.wake("c-3")
    _wait_for(lambda: len(calls) >= 1)
    runner.close()
    time.sleep(0.4)
    assert calls == ["c-3"]


@pytest.mark.parametrize(
    ("purpose", "ordinal", "saved", "forced"),
    [
        ("assessment_evaluate", 0, False, False),  # ordinal 0 has its own rule
        ("assessment_evaluate", 1, False, True),
        ("boundary_summarize", 2, False, True),
        ("assessment_evaluate", 3, False, False),
        ("assessment_evaluate", 1, True, False),  # saved: the closing call is free
        (None, 1, False, False),  # not an executor turn
    ],
)
def test_executor_retry_calls_keep_the_tool_required(
    monkeypatch: pytest.MonkeyPatch, purpose: str | None, ordinal: int, saved: bool, forced: bool
) -> None:
    monkeypatch.setattr(team_runtime, "_assessment_executor_write_saved", lambda *_args: saved)
    db = SimpleNamespace(get=lambda _model, _id: object())
    request = SimpleNamespace(assessment_purpose=purpose, turn_id="t", result_id="r")
    assert (
        team_runtime._executor_write_still_required(db, request, ordinal)  # type: ignore[arg-type]
        is forced
    )


def test_a_busy_refusal_woken_mid_run_still_gets_its_delayed_retry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """50-student run (2026-10-19): backend-2 scheduled 4 retries for 18 busy
    refusals. A wake that arrived while the chain waited in the full queue
    (the sweep wakes every waiting attempt) took the immediate re-wake path,
    which skipped the retry and went straight back into the busy queue."""

    from app.core.errors import PlatformError

    calls: list[float] = []
    entered = threading.Event()
    proceed = threading.Event()
    runner = _finalizer()

    def busy(_factory: Any, _settings: Any, conversation_id: str) -> bool:
        calls.append(time.monotonic())
        if len(calls) == 1:
            entered.set()
            proceed.wait(3)  # queued in admission while the sweep wakes it
        raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})

    monkeypatch.setattr(finalizer, "drive_assessment", busy)
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.3,))
    caplog.set_level("INFO", logger="maya.assessment")
    try:
        runner.wake("c-5")
        assert entered.wait(3)
        runner.wake("c-5")  # the sweep (or a message) wakes it mid-run
        stopped_at = time.monotonic()
        proceed.set()
        _wait_for(lambda: len(calls) >= 2)
        assert len(calls) == 2
        # The second run came from the delayed retry, not an immediate re-wake.
        assert calls[1] - stopped_at >= 0.25
        scheduled = [r for r in caplog.records if "retry scheduled" in r.getMessage()]
        assert len(scheduled) >= 1
    finally:
        runner.close()


def test_busy_refusals_keep_being_retried_and_never_run_out(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.errors import PlatformError

    calls: list[str] = []

    def busy(_factory: Any, _settings: Any, conversation_id: str) -> bool:
        calls.append(conversation_id)
        raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})

    monkeypatch.setattr(finalizer, "drive_assessment", busy)
    monkeypatch.setattr(finalizer, "RETRY_DELAYS_SECONDS", (0.01, 0.02))
    caplog.set_level("INFO", logger="maya.assessment")
    runner = _finalizer()
    try:
        runner.wake("c-6")
        _wait_for(lambda: len(calls) >= 6)
        # A stall that saved nothing would stop after 2 retries; a latch can
        # outlast 600 s, so busy refusals keep their (longest) delay instead.
        assert len(calls) >= 6
        assert not [r for r in caplog.records if "exhausted" in r.getMessage()]
    finally:
        runner.close()
