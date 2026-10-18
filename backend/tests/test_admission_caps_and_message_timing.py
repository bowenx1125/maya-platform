"""LLM cap 20 / adaptive budget 128 / in-flight 48, danger still wins, and the
per-message timing collector (structured log + /health/admission summary)."""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from app.core import adaptive_admission as aa
from app.core import message_timing as mt
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot, reset_llm_admission_state
from app.providers.llm_transport import HttpxLLMTransport


class _Probe:
    def __init__(self) -> None:
        self.load: float | None = 0.5
        self.mem: float | None = 4000.0
        self.now = 0.0


@pytest.fixture()
def probe() -> Iterator[_Probe]:
    p = _Probe()
    aa.reset_adaptive_admission_state()
    aa.set_signal_readers(load=lambda: p.load, mem=lambda: p.mem, clock=lambda: p.now)
    yield p
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_llm_admission_state()
    mt.reset_message_timing_state()
    yield
    reset_llm_admission_state()
    mt.reset_message_timing_state()


def _default(name: str) -> object:
    return Settings.model_fields[name].default


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adaptive_admission_enabled": True,
        "adaptive_admission_sample_seconds": 1.0,
        "adaptive_admission_adjust_seconds": 1.0,
        "adaptive_admission_wait_seconds": 1,
        "memory_guard_min_available_mb": 500,
        "memory_guard_resume_available_mb": 550,
        "host_load_reject_threshold": 6.0,
        "host_load_resume_threshold": 4.0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_new_caps_and_unchanged_protection_defaults() -> None:
    assert _default("llm_admission_limit") == 8
    assert _default("adaptive_admission_max_units") == 128
    assert _default("adaptive_admission_max_in_flight") == 48
    assert _default("adaptive_admission_initial_units") == 72
    # Protection is unchanged.
    assert _default("adaptive_admission_min_units") == 4
    assert _default("adaptive_admission_decrease_factor") == 0.7
    assert _default("adaptive_admission_increase_units") == 2.0
    assert _default("adaptive_admission_queue_max") == 200
    assert _default("adaptive_admission_wait_seconds") == 180
    assert _default("adaptive_admission_weight_llm") == 4
    assert _default("host_load_reject_threshold") == 6.0
    assert _default("host_load_resume_threshold") == 4.0
    assert _default("memory_guard_min_available_mb") == 500
    assert _default("memory_guard_resume_available_mb") == 550
    # 20 LLM calls fit the ceiling and the global cap.
    weight = int(_default("adaptive_admission_weight_llm"))  # type: ignore[call-overload]
    assert 20 * weight <= int(_default("adaptive_admission_max_units"))  # type: ignore[call-overload]
    assert 20 <= int(_default("adaptive_admission_max_in_flight"))  # type: ignore[call-overload]


def test_budget_starts_at_initial_and_climbs_to_new_max(probe: _Probe) -> None:
    s = _settings()
    snap = aa.adaptive_admission_snapshot(s)
    # Starts at exactly 72, not straight at 128.
    assert snap["adaptive_limit_units"] == 72
    assert snap["max_units"] == 128 and snap["max_in_flight"] == 48
    assert snap["min_units"] == 4 and snap["initial_units"] == 72
    for step in range(1, 40):
        probe.now = float(step)
        aa.adaptive_admission_snapshot(s)
    assert aa._state.budget == 128  # +2 per healthy adjust, capped at max
    probe.load = 5.0  # soft pressure
    probe.now = 40.0
    aa.adaptive_admission_snapshot(s)
    assert aa._state.budget == pytest.approx(128 * 0.7)
    for step in range(41, 60):
        probe.now = float(step)
        aa.adaptive_admission_snapshot(s)
    assert aa._state.budget == 4  # floor unchanged


def _hold_llm(s: Settings, count: int) -> tuple[threading.Event, list[threading.Thread]]:
    release = threading.Event()
    started = threading.Barrier(count + 1)

    def hold() -> None:
        with aa.adaptive_slot("llm", s):
            started.wait(5)
            release.wait(10)

    threads = [threading.Thread(target=hold) for _ in range(count)]
    for thread in threads:
        thread.start()
    started.wait(5)
    return release, threads


def test_twenty_llm_calls_fit_at_full_budget(probe: _Probe) -> None:
    s = _settings(adaptive_admission_initial_units=96)
    release, threads = _hold_llm(s, 20)
    try:
        assert aa._state.in_flight["llm"] == 20
        assert aa._state.in_flight_units == 80
    finally:
        release.set()
        for thread in threads:
            thread.join()


def test_cold_start_budget_limits_to_eighteen(probe: _Probe) -> None:
    s = _settings()  # initial 72 -> 18 LLM calls until AIMD earns more
    release, threads = _hold_llm(s, 18)
    try:
        with pytest.raises(PlatformError):
            with aa.adaptive_slot("llm", s):
                pass
    finally:
        release.set()
        for thread in threads:
            thread.join()


def test_in_flight_cap_48_still_binds(probe: _Probe) -> None:
    s = _settings(adaptive_admission_initial_units=200, adaptive_admission_max_units=200)
    release = threading.Event()
    started = threading.Barrier(49)

    def hold() -> None:
        with aa.adaptive_slot("login", s):
            started.wait(5)
            release.wait(10)

    threads = [threading.Thread(target=hold) for _ in range(48)]
    for thread in threads:
        thread.start()
    started.wait(5)
    try:
        with pytest.raises(PlatformError):
            with aa.adaptive_slot("login", s):
                pass
    finally:
        release.set()
        for thread in threads:
            thread.join()


@pytest.mark.parametrize(
    ("load", "mem", "recover_load", "recover_mem"),
    [(6.0, 4000.0, 4.0, 4000.0), (0.5, 499.0, 0.5, 550.0)],
)
def test_danger_still_suspends_at_new_caps(
    probe: _Probe, load: float, mem: float, recover_load: float, recover_mem: float
) -> None:
    s = _settings(adaptive_admission_initial_units=96)
    aa.adaptive_admission_snapshot(s)
    probe.load, probe.mem = load, mem
    probe.now = 1.0
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger"] is True
    with pytest.raises(PlatformError) as caught:
        with aa.adaptive_slot("llm", s):
            pass
    assert caught.value.code == "adaptive_admission_busy"
    # Hysteresis: half-way recovery keeps the latch.
    probe.load, probe.mem = 4.5 if load >= 6 else 0.5, 549.0 if mem < 500 else 4000.0
    probe.now = 2.0
    assert aa.adaptive_admission_snapshot(s)["danger"] is True
    probe.load, probe.mem = recover_load, recover_mem
    probe.now = 3.0
    assert aa.adaptive_admission_snapshot(s)["danger"] is False
    with aa.adaptive_slot("llm", s):
        pass


def test_llm_backstop_admits_eight() -> None:
    s = _settings(
        adaptive_admission_initial_units=96,
        memory_guard_min_available_mb=0,
        host_load_reject_threshold=0,
        llm_admission_wait_seconds=1,
    )
    assert s.llm_admission_limit == 8
    release = threading.Event()
    started = threading.Barrier(9)

    def hold() -> None:
        with llm_admission_slot(s):
            started.wait(5)
            release.wait(10)

    aa.reset_adaptive_admission_state()
    threads = [threading.Thread(target=hold) for _ in range(8)]
    for thread in threads:
        thread.start()
    started.wait(5)
    try:
        from app.core import llm_admission as la

        assert la._GATE.in_flight == 8  # noqa: SLF001
    finally:
        release.set()
        for thread in threads:
            thread.join()
        aa.reset_adaptive_admission_state()


# --- message timing -------------------------------------------------------


def test_message_timing_accumulates_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    statuses = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), json={"ok": True})

    quiet = _settings(memory_guard_min_available_mb=0, host_load_reject_threshold=0)
    monkeypatch.setattr(
        "app.providers.llm_transport.llm_admission_slot",
        lambda settings=None: llm_admission_slot(quiet),
    )
    caplog.set_level(logging.INFO, logger="maya.message_timing")
    with mt.message_timing("chat", conversation_id="c1", request_id="r1"):
        mt.add_db_write(3.0)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            transport = HttpxLLMTransport(client)
            for _ in range(2):
                transport.post(
                    "https://example.invalid/v1/chat/completions",
                    headers={"Authorization": "Bearer fixture"},
                    json={"model": "qwen-test", "messages": [{"role": "user", "content": "x"}]},
                )
        # A nested scope (e.g. generate_reply inside the handler) joins.
        with mt.message_timing("chat", conversation_id="ignored"):
            mt.add_db_write(2.0)
    lines = [r.getMessage() for r in caplog.records if r.name == "maya.message_timing"]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "message_timing"
    assert record["kind"] == "chat"
    assert record["conversation_id"] == "c1" and record["request_id"] == "r1"
    assert record["outcome"] == "ok"
    assert record["llm_calls"] == 2
    assert record["db_writes"] == 2 and record["db_write_ms"] == 5.0
    assert record["queue_wait_ms"] >= 0
    assert record["retry"] is True
    first, second = record["model_calls"]
    assert first["label"] == "qwen-test/completions"
    assert first["status"] == 429 and first["failed"] is True and first["retry"] is False
    assert second["status"] == 200 and second["retry"] is True
    assert second["ttft_ms"] is not None and second["duration_ms"] >= 0
    assert "content" not in lines[0]  # no prompt / message text
    summary = mt.message_timing_snapshot()
    assert summary["messages"] == 1 and summary["with_retry"] == 1
    assert summary["llm_calls_per_msg"] == {"p50": 2.0, "p95": 2.0}
    assert summary["db_writes_per_msg"] == {"p50": 2.0, "p95": 2.0}
    assert summary["ttft_ms"]["p50"] is not None


def test_inner_failure_marks_outcome_error() -> None:
    with mt.message_timing("chat", request_id="r2"):
        with pytest.raises(RuntimeError):
            with mt.message_timing("chat"):
                raise RuntimeError("provider failed")
    assert mt.message_timing_snapshot()["errors"] == 1


def test_collector_crosses_threadpool_context_copy() -> None:
    with mt.message_timing("team", turn_id="t1") as timing:
        ctx = contextvars.copy_context()
        worker = threading.Thread(target=lambda: ctx.run(mt.add_queue_wait, 12.5))
        worker.start()
        worker.join()
    assert timing.queue_wait_ms == 12.5


def test_queue_wait_recorded_by_gates() -> None:
    s = _settings(memory_guard_min_available_mb=0, host_load_reject_threshold=0)
    aa.reset_adaptive_admission_state()
    with mt.message_timing("chat", request_id="r3") as timing:
        with llm_admission_slot(s):
            pass
    assert timing.queue_wait_ms >= 0
    assert mt.message_timing_snapshot()["queue_wait_ms"]["p50"] is not None
    aa.reset_adaptive_admission_state()


def test_no_collector_outside_a_message() -> None:
    mt.add_db_write(1.0)
    mt.add_queue_wait(1.0)
    assert mt.current() is None
    assert mt.message_timing_snapshot()["messages"] == 0


def test_health_admission_exposes_limits_and_timing(client) -> None:  # type: ignore[no-untyped-def]
    body = client.get("/health/admission").json()
    assert body["max_units"] == 128 and body["max_in_flight"] == 48
    assert body["backstops"]["llm_admission_limit"] == 8
    assert body["backstops"]["write_guard_limit"] == 8
    assert body["backstops"]["create_admission_limit"] == 8
    assert body["backstops"]["auth_hash_concurrency"] == 3
    assert body["backstops_enabled"] == {
        "llm_admission": True,
        "write_guard": True,
        "create_admission": True,
        "auth_hash": True,
    }
    assert set(body["danger_latch"]) == {
        "entries",
        "releases",
        "reason",
        "active_seconds",
        "total_seconds",
    }
    timing = body["message_timing"]
    assert set(timing) >= {"messages", "total_ms", "queue_wait_ms", "llm_calls_per_msg", "ttft_ms"}


def test_a_handled_failure_sets_the_outcome() -> None:
    with mt.message_timing("team", turn_id="t-failed"):
        mt.set_outcome("failed")
    summary = mt.message_timing_snapshot()
    assert summary["messages"] == 1 and summary["errors"] == 1


def test_a_failed_team_turn_is_not_logged_as_ok(
    client: Any, database: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Prod (2026-10-18): every member failed, yet message_timing said "ok".
    from app.modules.workspace import team_runtime as runtime

    from tests.conftest import post_message
    from tests.test_mayaform_team_turns import _body, _chat, _headers

    session, csrf, _actor = _chat(client, database)

    def fail(_request: Any) -> Any:
        raise PlatformError("team_provider_not_sent", "The provider was not called.", 502)

    monkeypatch.setattr(runtime, "invoke_mock_member", fail)
    caplog.set_level(logging.INFO, logger="maya.message_timing")
    url = f"/api/v1/conversations/{session['id']}/messages"
    post_message(client, url, headers=_headers(csrf), json=_body(session, "all"))
    records = [
        json.loads(r.getMessage()) for r in caplog.records if r.name == "maya.message_timing"
    ]
    team = [record for record in records if record["kind"] == "team"]
    assert team and team[-1]["outcome"] == "failed"
