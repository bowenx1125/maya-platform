"""Danger latch reserve, finishing priority, max hold and release ramp.

60-student rerun (2026-10-19): the latch (load >= 6, clear at <= 4) admitted
nothing, so no turn and no Scorer/Summarizer ran for 1400 s while student
polling alone held load at 4.7-5.9; it never cleared, and when load dipped to
3.98 the whole backlog came in and re-tripped it 10 s later.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core.config import Settings
from app.core.errors import PlatformError


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


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "adaptive_admission_enabled": True,
        "adaptive_admission_sample_seconds": 1.0,
        "adaptive_admission_adjust_seconds": 1.0,
        "adaptive_admission_wait_seconds": 1,
        "adaptive_admission_max_in_flight": 8,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _trip(probe: _Probe, s: Settings, load: float = 6.5) -> None:
    probe.load = load
    probe.now += 1.0
    assert aa.adaptive_admission_snapshot(s)["danger"] is True


def _tick(probe: _Probe, s: Settings, seconds: float = 1.0) -> dict[str, object]:
    probe.now += seconds
    return aa.adaptive_admission_snapshot(s)


def test_defaults_keep_limits_and_add_a_two_slot_reserve() -> None:
    s = Settings()  # type: ignore[call-arg]
    assert s.adaptive_admission_max_units == 128
    assert s.adaptive_admission_max_in_flight == 48
    assert s.llm_admission_limit == 8
    assert s.write_guard_limit == 8
    assert s.create_admission_limit == 8
    assert s.adaptive_admission_danger_reserve_slots == 2
    assert s.adaptive_admission_danger_max_hold_seconds == 120.0
    assert s.adaptive_admission_release_ramp_seconds == 5.0
    assert s.adaptive_admission_release_ramp_step == 1
    assert s.conversation_poll_pressure_cache_seconds == 5.0


def test_load_danger_still_runs_two_turns_and_queues_the_third(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    first = aa.reserve_slot("write", s)
    second = aa.reserve_slot("write", s)
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["top_in_flight"] == 2
    assert snap["danger_latch"]["reserve_slots"] == 2  # type: ignore[index]
    assert snap["danger_latch"]["reserve_admitted"] == 2  # type: ignore[index]
    # The reserve is full: a third turn waits (here: its 1 s budget runs out).
    with pytest.raises(PlatformError) as caught:
        aa.reserve_slot("write", s)
    assert caught.value.code == "adaptive_admission_busy"
    first.release()
    third = aa.reserve_slot("write", s)  # a finished turn frees a reserve slot
    second.release()
    third.release()
    assert aa._state.top_in_flight == 0


def test_a_turns_nested_model_call_does_not_use_another_reserve_slot(probe: _Probe) -> None:
    s = _settings(adaptive_admission_danger_reserve_slots=1)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    with aa.adaptive_slot("write", s), aa.adaptive_slot("llm", s):
        assert aa._state.top_in_flight == 1
        assert aa._state.in_flight_units == 6  # above the floored budget: fine
    assert aa._state.top_in_flight == 0 and aa._state.in_flight_units == 0


@pytest.mark.parametrize("cls", ["create", "login", "llm"])
def test_the_reserve_is_only_for_turns_and_finishing(probe: _Probe, cls: str) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    with pytest.raises(PlatformError):
        with aa.adaptive_slot(cls, s):
            pass


def test_memory_danger_still_admits_nothing(probe: _Probe) -> None:
    s = _settings()
    probe.mem = 450.0
    with pytest.raises(PlatformError):
        with aa.adaptive_slot("write", s):
            pass
    with pytest.raises(PlatformError):
        aa.reserve_slot("write", s, priority=True)
    # Memory back over the floor but under the resume line: still no reserve.
    probe.mem = 520.0
    probe.load = 6.5
    _tick(probe, s)
    assert aa.adaptive_admission_snapshot(s)["danger_latch"]["reserve_slots"] == 0  # type: ignore[index]


def test_reserve_zero_restores_the_full_stop(probe: _Probe) -> None:
    s = _settings(adaptive_admission_danger_reserve_slots=0)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    with pytest.raises(PlatformError):
        with aa.adaptive_slot("write", s):
            pass


def test_finishing_goes_before_waiting_turns(probe: _Probe) -> None:
    s = _settings(adaptive_admission_danger_reserve_slots=1, adaptive_admission_wait_seconds=10)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    holder = aa.reserve_slot("write", s)
    order: list[str] = []
    lock = threading.Lock()

    def run(name: str, priority: bool) -> None:
        reservation = aa.reserve_slot("write", s, priority=priority)
        with lock:
            order.append(name)
        reservation.release()

    turn = threading.Thread(target=run, args=("turn", False))
    turn.start()
    time.sleep(0.2)  # the ordinary turn queued first
    scorer = threading.Thread(target=run, args=("scorer", True))
    scorer.start()
    time.sleep(0.2)
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["priority"]["queued"] == 1  # type: ignore[index]
    holder.release()
    turn.join(timeout=5)
    scorer.join(timeout=5)
    assert order == ["scorer", "turn"]
    assert aa._state.priority_admitted == 1


def test_max_hold_releases_a_latch_stuck_between_the_lines(probe: _Probe) -> None:
    s = _settings(adaptive_admission_danger_max_hold_seconds=120.0)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    probe.load = 5.0  # what polling alone held it at: under 6, never <= 4
    snap = _tick(probe, s, 60.0)
    assert snap["danger"] is True
    snap = _tick(probe, s, 61.0)
    assert snap["danger"] is False
    latch = snap["danger_latch"]
    assert latch["max_hold_releases"] == 1  # type: ignore[index]
    # Load back over the trip line latches again, as before.
    probe.load = 6.2
    assert _tick(probe, s)["danger"] is True


def test_max_hold_does_not_release_while_load_is_over_the_trip_line(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s, load=7.5)
    assert _tick(probe, s, 500.0)["danger"] is True


def test_max_hold_does_not_release_a_memory_latch(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    probe.load, probe.mem = 5.0, 520.0  # memory under its resume line
    probe.mem = 450.0
    _tick(probe, s)
    probe.mem = 520.0
    assert _tick(probe, s, 500.0)["danger"] is True


def test_release_ramps_up_instead_of_letting_the_backlog_in(probe: _Probe) -> None:
    s = _settings(adaptive_admission_max_in_flight=6, adaptive_admission_max_units=128)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s)
    probe.load = 3.5
    snap = _tick(probe, s)
    assert snap["danger"] is False
    assert snap["release_ramp_cap"] == 2  # starts at the reserve
    held = [aa.reserve_slot("login", s), aa.reserve_slot("login", s)]
    with pytest.raises(PlatformError):
        aa.reserve_slot("login", s)  # cap 2 reached; waits, then times out
    _tick(probe, s, 5.0)
    held.append(aa.reserve_slot("login", s))  # +1 after 5 s
    snap = _tick(probe, s, 10.0)
    assert snap["release_ramp_cap"] == 5
    snap = _tick(probe, s, 5.0)
    assert snap["release_ramp_cap"] is None  # reached the in-flight cap: ramp over
    for reservation in held:
        reservation.release()


def test_polling_pressure_follows_danger_and_ramp(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    assert aa.polling_pressure(s) is False
    _trip(probe, s)
    assert aa.polling_pressure(s) is True
    probe.load = 3.0
    _tick(probe, s)
    assert aa.polling_pressure(s) is True  # ramping
    _tick(probe, s, 60.0)
    assert aa.polling_pressure(s) is False


def test_rerun_scenario_keeps_turns_and_scoring_moving(probe: _Probe) -> None:
    """Load stuck at 5 after the trip, 12 queued: everything still finishes."""

    s = _settings(adaptive_admission_wait_seconds=20)
    aa.adaptive_admission_snapshot(s)
    _trip(probe, s, load=7.4)
    probe.load = 5.5
    finished: list[str] = []
    lock = threading.Lock()

    def work(name: str, priority: bool) -> None:
        reservation = aa.reserve_slot("write", s, priority=priority)
        try:
            time.sleep(0.05)  # a short turn
            with lock:
                finished.append(name)
        finally:
            reservation.release()

    threads = [
        threading.Thread(target=work, args=(f"{'score' if i % 3 == 0 else 'turn'}-{i}", i % 3 == 0))
        for i in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(finished) == 12
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger"] is True  # still latched: the work went through the reserve
    assert snap["danger_latch"]["reserve_admitted"] == 12  # type: ignore[index]
    assert snap["in_flight"] == 0
