"""Adaptive admission: AIMD, danger-line queue-only, weights, fairness, 503."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core.config import Settings
from app.core.errors import PlatformError

from tests.postgres_db import named_url


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
        # These tests pin the full-stop latch; the reserve and memory trickle
        # (on by default) are covered in test_danger_latch_reserve.py.
        "adaptive_admission_danger_reserve_slots": 0,
        "adaptive_admission_memory_danger_trickle": 0,
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
    assert _budget() == 6  # +4 while below half of max
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


def test_nested_llm_call_gets_a_fresh_backstop_wait(probe: _Probe) -> None:
    from app.core import llm_admission as la

    la.reset_llm_admission_state()
    s = _settings(
        adaptive_admission_wait_seconds=1,
        llm_admission_limit=1,
        llm_admission_wait_seconds=60,
    )
    held = threading.Event()

    def holder() -> None:
        with la.llm_admission_slot(s):
            held.set()
            time.sleep(1.5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(2)
    with aa.adaptive_slot("write", s):
        # The turn runs past its request deadline before its model call.
        time.sleep(1.2)
        assert aa.shared_wait_seconds(60.0) == 0.0
        with la.llm_admission_slot(s):
            pass  # waited for the holder instead of failing at once
    t.join()


def test_waiter_timeout_removes_only_itself(probe: _Probe) -> None:
    from collections import deque

    first = aa._Waiter(cls="write", weight=2)
    second = aa._Waiter(cls="write", weight=2)
    queue = deque([first, second])
    queue.remove(second)  # what a timed-out waiter does
    assert list(queue) == [first] and queue[0] is first


def test_shared_wait_seconds_without_deadline_returns_cap() -> None:
    assert aa.shared_wait_seconds(60.0) == 60.0


def test_request_p95_window_drains_after_60s(probe: _Probe) -> None:
    for _ in range(20):
        aa.record_request_ms(20_000.0)
    assert aa._REQUEST.p95() == 20_000.0
    probe.now = 59.0
    assert aa._REQUEST.p95() == 20_000.0
    probe.now = 61.0  # every sample is now older than 60 s
    assert aa._REQUEST.p95() is None
    s = _settings()
    aa.adaptive_admission_snapshot(s)
    assert aa.adaptive_admission_snapshot(s)["request_p95_ms"] is None


def test_request_latency_never_shrinks_the_budget(probe: _Probe) -> None:
    """Request p95 includes queue time; acting on it shrank the budget
    further the longer people waited (the #101 40-student run)."""

    s = _settings()
    aa.adaptive_admission_snapshot(s)
    for _ in range(50):
        aa.record_request_ms(60_000.0)
    probe.now = 1.0
    snapshot = aa.adaptive_admission_snapshot(s)
    assert snapshot["request_p95_ms"] == 60_000.0
    assert _budget() == 8
    assert snapshot["last_shrink_reason"] is None


def test_llm_requests_are_excluded_from_request_p95(probe: _Probe) -> None:
    s = _settings(adaptive_admission_max_units=48)
    for _ in range(20):
        sample = aa.begin_request_sample()
        with aa.adaptive_slot("llm", s):
            pass
        assert sample.llm is True
        assert aa.record_request_sample(sample, 30_000.0) is False
    assert aa._REQUEST.p95() is None
    for _ in range(20):
        sample = aa.begin_request_sample()
        with aa.adaptive_slot("write", s):
            pass
        assert aa.record_request_sample(sample, 100.0) is True
    assert aa._REQUEST.p95() == 100.0


def test_stream_responses_are_excluded_from_request_p95(probe: _Probe) -> None:
    for _ in range(20):
        sample = aa.begin_request_sample()
        assert (
            aa.record_request_sample(
                sample, 40_000.0, content_type="text/event-stream; charset=utf-8"
            )
            is False
        )
    assert aa._REQUEST.p95() is None
    assert aa.record_request_sample(None, 5.0, content_type="application/json") is True


def test_llm_mark_crosses_threadpool_context_copy(probe: _Probe) -> None:
    """Sync handlers run in a copied context; the marker is shared by reference."""

    import contextvars

    s = _settings(adaptive_admission_max_units=48)
    sample = aa.begin_request_sample()
    ctx = contextvars.copy_context()

    def handler() -> None:
        with aa.adaptive_slot("llm", s):
            pass

    t = threading.Thread(target=lambda: ctx.run(handler))
    t.start()
    t.join()
    assert sample.llm is True


# --- server-side AIMD signals (PR: AIMD shrink signals) -------------------


# The fast brake (tests/test_admission_brake.py) off, to test AIMD alone.
_NO_BRAKE: dict[str, object] = {
    "adaptive_admission_brake_db_write_p95_ms": 0,
    "adaptive_admission_brake_pool_wait_p95_ms": 0,
    "adaptive_admission_brake_writes_in_flight": 0,
    "adaptive_admission_brake_cpu_ratio": 0,
}


def _defaults(**overrides: object) -> Settings:
    base: dict[str, object] = {"adaptive_admission_wait_seconds": 1}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _tick(probe: _Probe, s: Settings, seconds: float = 2.0) -> dict[str, object]:
    probe.now += seconds
    return aa.adaptive_admission_snapshot(s)


def test_defaults_keep_the_danger_line_and_start_at_72(probe: _Probe) -> None:
    s = _defaults()
    assert (s.host_load_reject_threshold, s.host_load_resume_threshold) == (6.0, 4.0)
    assert (s.memory_guard_min_available_mb, s.memory_guard_resume_available_mb) == (500, 550)
    assert s.adaptive_admission_decrease_factor == 0.7
    assert s.adaptive_admission_min_units == 4
    assert s.adaptive_admission_queue_max == 200
    assert s.adaptive_admission_wait_seconds == 1  # overridden here; default below
    assert Settings().adaptive_admission_wait_seconds == 180  # type: ignore[call-arg]
    assert aa.adaptive_admission_snapshot(s)["adaptive_limit_units"] == 72


def test_long_queue_with_healthy_signals_does_not_shrink(probe: _Probe) -> None:
    s = _defaults(adaptive_admission_max_in_flight=1, adaptive_admission_queue_max=200)
    aa.adaptive_admission_snapshot(s)
    with aa._cond:
        aa._state.in_flight["llm"] = 1  # the one global slot is taken
        aa._state.in_flight_units = 4
        for _ in range(150):
            aa._state.queues["login"].append(aa._Waiter(cls="login", weight=1))
    for _ in range(50):
        aa.record_request_ms(120_000.0)  # everyone has waited minutes
    for _ in range(5):
        snapshot = _tick(probe, s)
    assert snapshot["queue_depth"] == 150
    assert _budget() > 72
    assert snapshot["last_shrink_reason"] is None
    assert sum(snapshot["shrink_counts"].values()) == 0  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("reason", "setup"),
    [
        ("danger", lambda p: setattr(p, "load", 6.0)),
        ("load", lambda p: setattr(p, "load", 4.0)),
        ("mem", lambda p: setattr(p, "mem", 899.0)),
        ("db_write_p95", lambda p: [aa.record_db_write_ms(600.0) for _ in range(20)]),
        ("pool_wait_p95", lambda p: [aa.record_pool_wait_ms(600.0) for _ in range(20)]),
    ],
)
def test_each_shrink_signal(probe: _Probe, reason: str, setup) -> None:  # type: ignore[no-untyped-def]
    s = _defaults(**_NO_BRAKE)  # the slow AIMD signals alone
    aa.adaptive_admission_snapshot(s)
    setup(probe)
    snapshot = _tick(probe, s)
    assert _budget() == pytest.approx(72 * 0.7)
    assert snapshot["last_shrink_reason"] == reason
    assert snapshot["shrink_counts"][reason] == 1  # type: ignore[index]


def test_db_signals_need_twenty_samples_in_thirty_seconds(probe: _Probe) -> None:
    s = _defaults(**_NO_BRAKE)
    aa.adaptive_admission_snapshot(s)
    for _ in range(19):
        aa.record_db_write_ms(2_000.0)
        aa.record_pool_wait_ms(2_000.0)
    _tick(probe, s)
    assert _budget() == 74  # 19 slow samples are not enough to judge
    aa.record_db_write_ms(2_000.0)
    _tick(probe, s)
    assert _budget() == pytest.approx(74 * 0.7)
    probe.now += 31.0  # all samples age out of the 30 s window
    assert aa._DB_WRITE.p95() is None
    assert aa._POOL_WAIT.p95() is None


@pytest.mark.parametrize(
    "setup",
    [
        lambda p: setattr(p, "load", 3.0),
        lambda p: setattr(p, "load", 3.99),
        lambda p: setattr(p, "mem", 900.0),
        lambda p: setattr(p, "mem", 1099.0),
        lambda p: aa.set_threadpool_reader(lambda: 0.9),
    ],
)
def test_hold_band_neither_grows_nor_shrinks(probe: _Probe, setup) -> None:  # type: ignore[no-untyped-def]
    s = _defaults()
    try:
        aa.adaptive_admission_snapshot(s)
        setup(probe)
        for _ in range(3):
            snapshot = _tick(probe, s)
        assert _budget() == 72
        assert snapshot["last_shrink_reason"] is None
    finally:
        aa.set_threadpool_reader(None)


@pytest.mark.parametrize(("borrowed", "grows"), [(100, True), (120, False)])
def test_threadpool_hold_trips_near_115_of_256_threads(
    probe: _Probe, borrowed: int, grows: bool
) -> None:
    """#141: with the 256-thread pool, 0.9 only tripped at 231 borrowed threads."""

    from app.main import ANYIO_THREAD_TOKENS

    s = _defaults()
    try:
        aa.adaptive_admission_snapshot(s)
        aa.set_threadpool_reader(lambda: borrowed / ANYIO_THREAD_TOKENS)
        _tick(probe, s)
        assert (_budget() > 72) is grows
    finally:
        aa.set_threadpool_reader(None)


def test_growth_is_plus_four_below_half_of_max_then_plus_two(probe: _Probe) -> None:
    s = _defaults(adaptive_admission_initial_units=40, adaptive_admission_max_units=96)
    aa.adaptive_admission_snapshot(s)
    with aa._cond:
        aa._state.in_flight_units = 4  # busy, so idle recovery stays out of it
    _tick(probe, s)
    assert _budget() == 44
    _tick(probe, s)
    assert _budget() == 48  # 44 < 48 (half of 96): still +4
    _tick(probe, s)
    assert _budget() == 50  # at half of max: +2
    for _ in range(40):
        _tick(probe, s)
    assert _budget() == 96


def test_idle_and_healthy_returns_to_the_initial_budget(probe: _Probe) -> None:
    s = _defaults()
    aa.adaptive_admission_snapshot(s)
    probe.load = 5.0
    for _ in range(6):
        _tick(probe, s)
    shrunk = _budget()
    assert shrunk < 20
    probe.load = 0.5
    _tick(probe, s)
    assert _budget() == pytest.approx(shrunk + 4)  # not idle long enough yet
    probe.now += 30.0
    _tick(probe, s)
    assert _budget() == 72


def test_every_budget_change_is_logged(probe: _Probe, caplog: pytest.LogCaptureFixture) -> None:
    s = _defaults()
    aa.adaptive_admission_snapshot(s)
    probe.load = 4.5
    with caplog.at_level("INFO", logger="maya.admission"):
        _tick(probe, s)
    assert any(
        "adaptive_budget from=72.0 to=50.4 reason=load" in record.getMessage()
        for record in caplog.records
    )


def test_pool_checkout_wait_is_recorded(probe: _Probe, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.core import db as db_module
    from sqlalchemy import create_engine, text

    engine = create_engine(named_url(f"{tmp_path / 'pool.sqlite3'}"))
    db_module._time_pool_checkout(engine)
    try:
        for _ in range(20):
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()
    p95 = aa._POOL_WAIT.p95()
    assert p95 is not None and p95 < 500


def test_danger_latch_logs_enter_and_release_and_counts_them(
    probe: _Probe, caplog: pytest.LogCaptureFixture
) -> None:
    s = _settings()
    caplog.set_level("WARNING", logger="maya.admission")
    aa.adaptive_admission_snapshot(s)
    latch = aa.adaptive_admission_snapshot(s)["danger_latch"]
    assert latch == {
        "entries": 0,
        "releases": 0,
        "reason": None,
        "active_seconds": 0.0,
        "total_seconds": 0.0,
        "max_hold_releases": 0,
        "reserve_slots": 0,
        "reserve_admitted": 0,
    }

    probe.load = 6.5
    probe.mem = 450.0
    probe.now = 1.0
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger"] is True
    assert snap["danger_latch"]["entries"] == 1
    assert snap["danger_latch"]["reason"] == "load+mem"
    entered = [
        r.getMessage() for r in caplog.records if "admission_danger_entered" in r.getMessage()
    ]
    assert entered == [
        "admission_danger_entered reason=load+mem load=6.5 mem_mb=450.0 in_flight_units=0 queued=0"
    ]

    # Still latched (hysteresis): no second entry, no release.
    probe.load = 4.5
    probe.mem = 600.0
    probe.now = 3.0
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger"] is True
    assert snap["danger_latch"]["entries"] == 1
    assert snap["danger_latch"]["active_seconds"] == 2.0

    probe.load = 3.5
    probe.now = 5.0
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger"] is False
    assert snap["danger_latch"]["releases"] == 1
    assert snap["danger_latch"]["total_seconds"] == 4.0
    assert snap["danger_latch"]["active_seconds"] == 0.0
    released = [
        r.getMessage() for r in caplog.records if "admission_danger_released" in r.getMessage()
    ]
    assert released == [
        "admission_danger_released reason=load+mem held_s=4.0 load=3.5 mem_mb=600.0 queued=0"
        " release=recovered"
    ]

    probe.mem = 300.0
    probe.now = 6.0
    snap = aa.adaptive_admission_snapshot(s)
    assert snap["danger_latch"]["entries"] == 2
    assert snap["danger_latch"]["reason"] == "mem"
