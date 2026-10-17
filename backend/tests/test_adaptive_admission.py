"""Adaptive admission: AIMD, danger-line queue-only, weights, fairness, 503."""

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
        "adaptive_admission_max_units": 8,
        "adaptive_admission_min_units": 2,
        "adaptive_admission_sample_seconds": 1.0,
        "adaptive_admission_adjust_seconds": 1.0,
        "adaptive_admission_wait_seconds": 1,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _budget() -> float:
    return aa._state.budget


def test_aimd_decreases_on_pressure_and_increases_when_healthy(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    assert _budget() == 8
    probe.load = 5.0  # soft pressure (>= 4) but below danger 6
    probe.now = 1.0
    aa.adaptive_admission_snapshot(s)
    assert _budget() == pytest.approx(5.6)
    probe.now = 2.0
    aa.adaptive_admission_snapshot(s)
    assert _budget() == pytest.approx(3.92)
    for step in range(3, 10):
        probe.now = float(step)
        aa.adaptive_admission_snapshot(s)
    assert _budget() == 2  # floored at min
    probe.load = 1.0
    probe.now = 10.0
    aa.adaptive_admission_snapshot(s)
    assert _budget() == 4  # +2 additive
    for step in range(11, 20):
        probe.now = float(step)
        aa.adaptive_admission_snapshot(s)
    assert _budget() == 8  # never above max (hard cap)


def test_latency_signals_cause_decrease(probe: _Probe) -> None:
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    for _ in range(20):
        aa.record_db_write_ms(2000.0)
    probe.now = 1.0
    aa.adaptive_admission_snapshot(s)
    assert _budget() < 8


def test_unreadable_signals_fail_open(probe: _Probe) -> None:
    s = _settings()
    probe.load = None
    probe.mem = None
    with aa.adaptive_slot("llm", s):
        pass
    assert aa.adaptive_admission_snapshot(s)["danger"] is False


def test_danger_line_queues_then_admits_after_hysteresis(probe: _Probe) -> None:
    s = _settings(adaptive_admission_wait_seconds=30)
    probe.load = 6.5
    aa.adaptive_admission_snapshot(s)
    assert aa._state.danger
    done = threading.Event()

    def worker() -> None:
        with aa.adaptive_slot("create", s):
            done.set()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.2)
    assert not done.is_set()  # queued, not rejected
    probe.load = 4.5  # above resume 4: still latched
    probe.now = 2.0
    time.sleep(0.2)
    assert not done.is_set()
    probe.load = 3.9
    probe.now = 4.0
    t.join(timeout=5)
    assert done.is_set()


def test_memory_danger_line(probe: _Probe) -> None:
    s = _settings()
    probe.mem = 400.0
    with pytest.raises(PlatformError) as excinfo:
        with aa.adaptive_slot("write", s):
            pass
    assert excinfo.value.code == "adaptive_admission_busy"
    assert excinfo.value.status_code == 503
    assert excinfo.value.details["retryable"] is True
    assert excinfo.value.details["retry_after_seconds"] >= 1
    assert excinfo.value.details["reason"] == "wait_timeout"


def test_weights_limit_concurrency(probe: _Probe) -> None:
    s = _settings()  # budget 8, llm weight 4
    with aa.adaptive_slot("llm", s), aa.adaptive_slot("llm", s):
        pass
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["classes"]["llm"]["weight"] == 4
    assert snap["classes"]["login"]["weight"] == 1
    # Two LLM calls on other threads fill the budget; a third must queue.
    release = threading.Event()
    started = threading.Barrier(3)

    def hold() -> None:
        with aa.adaptive_slot("llm", s):
            started.wait()
            release.wait(5)

    threads = [threading.Thread(target=hold) for _ in range(2)]
    for t in threads:
        t.start()
    started.wait()
    with pytest.raises(PlatformError):
        with aa.adaptive_slot("llm", s):
            pass
    # A login (weight 1) also queues: FIFO, no free units.
    assert aa._state.in_flight_units == 8
    release.set()
    for t in threads:
        t.join()
    assert aa._state.in_flight_units == 0


def test_queue_full_rejects(probe: _Probe) -> None:
    s = _settings(adaptive_admission_queue_max=0)
    probe.load = 7.0
    with pytest.raises(PlatformError) as excinfo:
        with aa.adaptive_slot("login", s):
            pass
    assert excinfo.value.details["reason"] == "queue_full"
    assert aa.adaptive_admission_snapshot(s)["classes"]["login"]["rejects"] == 1


def test_round_robin_fairness_across_classes(probe: _Probe) -> None:
    s = _settings()
    w = {"write": aa._Waiter("write", 2), "llm": aa._Waiter("llm", 4)}
    with aa._cond:
        aa._refresh_locked(s)
        for _ in range(3):
            aa._state.queues["write"].append(aa._Waiter("write", 2))
        aa._state.queues["write"].appendleft(w["write"])
        aa._state.queues["llm"].append(w["llm"])
        aa._state.rr_index = aa.CLASSES.index("write")
        aa._dispatch_locked(s)
    # write served first, then llm gets its turn before more writes.
    assert w["write"].granted and w["llm"].granted
    assert aa._state.in_flight_units == 8
    assert len(aa._state.queues["write"]) == 2


def test_head_that_does_not_fit_blocks_lighter_classes(probe: _Probe) -> None:
    s = _settings()
    heavy = aa._Waiter("llm", 4)
    light = aa._Waiter("login", 1)
    with aa._cond:
        aa._refresh_locked(s)
        aa._state.in_flight_units = 6
        aa._state.queues["llm"].append(heavy)
        aa._state.queues["login"].append(light)
        aa._state.rr_index = aa.CLASSES.index("llm")
        aa._dispatch_locked(s)
    assert not heavy.granted and not light.granted  # no starvation of llm


def test_reads_bypass_even_in_danger(probe: _Probe) -> None:
    s = _settings()
    probe.load = 20.0
    with aa.adaptive_slot("read", s):
        pass


def test_nested_slot_on_same_thread_does_not_wait(probe: _Probe) -> None:
    s = _settings(adaptive_admission_max_units=4, adaptive_admission_min_units=4)
    with aa.adaptive_slot("write", s), aa.adaptive_slot("llm", s):
        assert aa._state.in_flight_units == 6
    assert aa._state.in_flight_units == 0


def test_aimd_off_still_suspends_on_pressure(probe: _Probe) -> None:
    # Pressure queueing is unconditional; the flag only turns AIMD off.
    s = _settings(adaptive_admission_enabled=False)
    probe.load = 50.0
    with pytest.raises(PlatformError) as excinfo:
        with aa.adaptive_slot("llm", s):
            pass
    assert excinfo.value.details["reason"] == "wait_timeout"
    probe.load = 5.0
    probe.now = 5.0
    aa.adaptive_admission_snapshot(s)
    assert _budget() == 8  # no multiplicative decrease when AIMD is off


def test_guard_reader_overrides_feed_unified_signal(probe: _Probe) -> None:
    from app.core.memory_guard import set_mem_available_reader

    aa.set_signal_readers(load=lambda: 0.5, clock=lambda: probe.now)
    set_mem_available_reader(lambda: 499)
    try:
        aa.adaptive_admission_snapshot(_settings())
        assert aa._state.danger
    finally:
        set_mem_available_reader(None)


def test_global_in_flight_cap_is_the_only_backstop(probe: _Probe) -> None:
    s = _settings(adaptive_admission_max_in_flight=2, adaptive_admission_max_units=100)
    release = threading.Event()
    started = threading.Barrier(3)

    def hold() -> None:
        with aa.adaptive_slot("login", s):
            started.wait()
            release.wait(5)

    threads = [threading.Thread(target=hold) for _ in range(2)]
    for t in threads:
        t.start()
    started.wait()
    with pytest.raises(PlatformError) as excinfo:
        with aa.adaptive_slot("login", s):
            pass
    assert excinfo.value.details["reason"] == "wait_timeout"
    release.set()
    for t in threads:
        t.join()
    assert aa.adaptive_admission_snapshot(s)["max_in_flight"] == 2


def test_pressure_suspends_then_resumes_across_classes(probe: _Probe) -> None:
    s = _settings(adaptive_admission_wait_seconds=30)
    probe.mem = 450.0
    done: list[str] = []

    def worker(cls: str) -> None:
        with aa.adaptive_slot(cls, s):
            done.append(cls)

    threads = [threading.Thread(target=worker, args=(c,)) for c in aa.CLASSES]
    for t in threads:
        t.start()
    time.sleep(0.3)
    assert done == []  # every class suspended, none rejected
    probe.mem = 540.0  # above floor but below resume 550: still latched
    probe.now = 2.0
    time.sleep(0.3)
    assert done == []
    probe.mem = 600.0
    probe.now = 4.0
    for t in threads:
        t.join(timeout=5)
    assert sorted(done) == sorted(aa.CLASSES)


def test_single_wait_budget_for_nested_slots(probe: _Probe) -> None:
    # A nested slot (write -> llm) never opens a second wait window.
    s = _settings()
    with aa.adaptive_slot("write", s):
        probe.load = 9.0  # danger latches after the outer slot was admitted
        probe.now = 5.0
        start = time.monotonic()
        with aa.adaptive_slot("llm", s):
            pass
        assert time.monotonic() - start < 0.5


def test_llm_backstop_shares_the_single_deadline(probe: _Probe) -> None:
    from app.core import llm_admission as la

    la.reset_llm_admission_state()
    s = _settings(
        adaptive_admission_wait_seconds=1,
        llm_admission_limit=1,
        llm_admission_wait_seconds=60,
    )
    release = threading.Event()
    held = threading.Event()

    def holder() -> None:
        with la.llm_admission_slot(s):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(2)
    started = time.monotonic()
    with pytest.raises(PlatformError) as excinfo:
        with la.llm_admission_slot(s):
            pass
    elapsed = time.monotonic() - started
    release.set()
    t.join()
    # The backstop waited only the ~1s left of the request deadline, not 60s.
    assert elapsed < 3
    assert excinfo.value.status_code == 503
    assert excinfo.value.details["reason"] == "wait_timeout"


def test_shared_wait_seconds_without_deadline_returns_cap() -> None:
    assert aa.shared_wait_seconds(60.0) == 60.0
