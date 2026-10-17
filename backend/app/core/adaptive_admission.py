"""One request-level, pressure-driven admission queue for heavy work.

The old per-operation gates (LLM / write 12, create 4, login 8) each capped
one operation in isolation, yet MayaLoad's runs melted the host from the
*combined* work before any single gate filled. They now sit behind
this single queue as backstops (the login queue is folded into it):

* Unified pressure signal: 1m loadavg and MemAvailable share one latch
  (danger at load >= 6 or Mem < 500 MiB; clear only when load <= 4 AND
  Mem >= 550 MiB) so the old memory and load guards cannot disagree.
  Under danger nothing new is admitted; callers suspend in the queue and
  continue automatically once the latch clears.
* AIMD on server-side signals only: danger, load, MemAvailable, DB write
  p95 and DB pool checkout wait p95 shrink the weighted budget x0.7; a band
  just below those (load 3-4, Mem 900-1100 MiB, thread pool >= 90%) holds
  it; otherwise it grows (+4 below half of max, else +2). Request p95
  includes time spent in this queue, so feeding it back shrank the budget
  further the longer people waited; it is reported, never acted on.
* Cost weights (llm heavy, create/write medium, login light, read free),
  FIFO per class, served round-robin so one class cannot starve others.
* One global in-flight hard cap per process; LLM calls, Team/Chat
  turns and creates additionally pass ``llm_admission`` (20) / ``write_guard``
  (20) / ``create_admission`` (4) as per-operation backstops, which wait only for the remainder of
  this layer's deadline (a call nested in an admitted operation starts a fresh one).
* Retryable ``adaptive_admission_busy`` 503 is raised only when the queue
  (max 200) is full or the single 180 s wait budget runs out.

``/proc/loadavg`` and ``/proc/meminfo`` are host-wide (not cgroup-scoped)
inside the production containers, so both backend replicas see the same
pressure and shrink together without extra shared state. Unreadable signals
fail open (only the global cap then applies).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.core import host_load_guard, memory_guard
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

CLASSES: tuple[str, ...] = ("llm", "create", "write", "login")
READ_CLASS = "read"

LOGGER = logging.getLogger("maya.admission")

SignalReader = Callable[[], float | None]
_load_reader: SignalReader | None = None
_mem_reader: SignalReader | None = None
# Fraction of the AnyIO worker-thread pool in use; main.py installs it.
_threadpool_reader: SignalReader | None = None
_clock: Callable[[], float] = time.monotonic


def set_signal_readers(
    *,
    load: SignalReader | None = None,
    mem: SignalReader | None = None,
    clock: Callable[[], float] | None = None,
) -> None:
    """Override host probes / clock (tests only). ``None`` restores defaults."""

    global _load_reader, _mem_reader, _clock
    _load_reader = load
    _mem_reader = mem
    _clock = clock if clock is not None else time.monotonic


def set_threadpool_reader(reader: SignalReader | None) -> None:
    """Install the thread-pool usage probe (0..1). ``None`` removes it."""

    global _threadpool_reader
    _threadpool_reader = reader


def _read_threadpool() -> float | None:
    reader = _threadpool_reader
    if reader is None:
        return None
    try:
        return reader()
    except Exception:
        return None  # an observation must never break admission


def _read_load() -> float | None:
    if _load_reader is not None:
        return _load_reader()
    return host_load_guard.active_reader()()


def _read_mem() -> float | None:
    if _mem_reader is not None:
        return _mem_reader()
    value = memory_guard.active_reader()()
    return None if value is None else float(value)


class _TimedLatencyWindow:
    """Durations (ms) from the last ``horizon`` seconds for a cheap p95.

    Unlike a last-N ring buffer, old samples age out on the clock, so the
    signal drains back to "unknown" when traffic stops instead of pinning the
    budget at the floor with stale minutes-old latencies.
    """

    def __init__(
        self, horizon_seconds: float = 60.0, max_samples: int = 2000, min_samples: int = 10
    ) -> None:
        self._horizon = horizon_seconds
        self._min_samples = min_samples
        self._samples: deque[tuple[float, float]] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def _expire_locked(self, now: float) -> None:
        cutoff = now - self._horizon
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def add(self, ms: float) -> None:
        now = _clock()
        with self._lock:
            self._expire_locked(now)
            self._samples.append((now, ms))

    def p95(self) -> float | None:
        now = _clock()
        with self._lock:
            self._expire_locked(now)
            if len(self._samples) < self._min_samples:
                return None  # too few samples to judge; treat as unknown
            ordered = sorted(ms for _, ms in self._samples)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


REQUEST_P95_WINDOW_SECONDS = 60.0
# DB signals judge the last 30 s and need 20 samples, so one slow statement
# in a quiet minute cannot shrink the budget.
DB_P95_WINDOW_SECONDS = 30.0
DB_P95_MIN_SAMPLES = 20

_DB_WRITE = _TimedLatencyWindow(DB_P95_WINDOW_SECONDS, min_samples=DB_P95_MIN_SAMPLES)
_POOL_WAIT = _TimedLatencyWindow(DB_P95_WINDOW_SECONDS, min_samples=DB_P95_MIN_SAMPLES)
_REQUEST = _TimedLatencyWindow(REQUEST_P95_WINDOW_SECONDS)


class RequestSample:
    """Per-request marker: set when the request runs model (LLM) work.

    The HTTP middleware installs one per request in a ContextVar; the object
    is shared by reference with the threadpool copy of the context, so an
    ``adaptive_slot("llm")`` inside a sync handler can flag it.
    """

    __slots__ = ("llm",)

    def __init__(self) -> None:
        self.llm = False


_REQUEST_SAMPLE: ContextVar[RequestSample | None] = ContextVar(
    "adaptive_admission_request_sample", default=None
)


def begin_request_sample() -> RequestSample:
    sample = RequestSample()
    _REQUEST_SAMPLE.set(sample)
    return sample


def _mark_request_llm() -> None:
    sample = _REQUEST_SAMPLE.get()
    if sample is not None:
        sample.llm = True


def record_request_sample(
    sample: RequestSample | None, ms: float, *, content_type: str | None = None
) -> bool:
    """Feed request p95 unless the request was LLM work or a stream.

    Model calls and SSE / chat streams are slow by nature (tens of seconds),
    so counting them made the request-p95 soft signal fire on every chat
    burst. Returns whether the sample was recorded.
    """

    if sample is not None and sample.llm:
        return False
    if content_type and content_type.split(";", 1)[0].strip().lower() == "text/event-stream":
        return False
    _REQUEST.add(ms)
    return True


def record_db_write_ms(ms: float) -> None:
    _DB_WRITE.add(ms)


def record_pool_wait_ms(ms: float) -> None:
    """Time a caller waited for a pooled DB connection (db.py)."""

    _POOL_WAIT.add(ms)


def record_request_ms(ms: float) -> None:
    _REQUEST.add(ms)


# Identity equality: deque.remove() on a timeout must drop this waiter, not
# the first queued one of the same class and weight.
@dataclass(eq=False)
class _Waiter:
    cls: str
    weight: int
    granted: bool = False


SHRINK_REASONS: tuple[str, ...] = ("danger", "load", "mem", "db_write_p95", "pool_wait_p95")


@dataclass
class _State:
    budget: float = -1.0  # <0 means "not initialised yet"
    in_flight_units: int = 0
    last_adjust: float = float("-inf")
    last_sample: float = float("-inf")
    # Last time anything was admitted or waiting; idle recovery counts from it.
    last_busy: float = float("-inf")
    danger: bool = False
    # Danger latch history for /health/admission and the enter/release logs.
    danger_entries: int = 0
    danger_releases: int = 0
    danger_since: float | None = None
    danger_reason: str | None = None
    danger_seconds_total: float = 0.0
    load: float | None = None
    mem: float | None = None
    threadpool: float | None = None
    last_shrink_reason: str | None = None
    shrink_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SHRINK_REASONS, 0))
    rr_index: int = 0
    queues: dict[str, deque[_Waiter]] = field(
        default_factory=lambda: {name: deque() for name in CLASSES}
    )
    in_flight: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    rejects: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))
    admitted: dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLASSES, 0))


_lock = threading.Lock()
# Team/Chat turns hold a write slot and then call the model inside it. A
# nested acquire on the same thread must not wait behind its own outer slot
# (that deadlocks at a small budget), so it is charged without queuing.
_held = threading.local()
_cond = threading.Condition(_lock)
_state = _State()


def reset_adaptive_admission_state() -> None:
    """Drop all counters and samples (tests only)."""

    global _state
    with _cond:
        _state = _State()
        _cond.notify_all()
    _DB_WRITE.clear()
    _POOL_WAIT.clear()
    _REQUEST.clear()


def _weight(settings: Settings, cls: str) -> int:
    return int(
        {
            "llm": settings.adaptive_admission_weight_llm,
            "create": settings.adaptive_admission_weight_create,
            "write": settings.adaptive_admission_weight_write,
            "login": settings.adaptive_admission_weight_login,
        }[cls]
    )


def _refresh_locked(settings: Settings) -> None:
    """Sample signals and apply AIMD at most once per adjust interval."""

    s = _state
    max_units = float(settings.adaptive_admission_max_units)
    min_units = float(min(settings.adaptive_admission_min_units, max_units))
    now = _clock()
    if s.budget < 0:
        # Start at the configured cold-start budget, not the ceiling: AIMD
        # earns the rest of the headroom while signals stay healthy, starting
        # one adjust interval from now.
        initial = float(settings.adaptive_admission_initial_units)
        s.budget = max(min_units, min(max_units, initial))
        s.last_adjust = now
    if now - s.last_sample < float(settings.adaptive_admission_sample_seconds):
        return
    s.last_sample = now
    s.load = _read_load()
    s.mem = _read_mem()

    # Danger line reuses host_load_guard / memory_guard thresholds + hysteresis.
    load_reject = float(settings.host_load_reject_threshold)
    load_resume = min(float(settings.host_load_resume_threshold), load_reject)
    mem_floor = float(settings.memory_guard_min_available_mb)
    mem_resume = max(float(settings.memory_guard_resume_available_mb), mem_floor)
    load_bad = load_reject > 0 and s.load is not None and s.load >= load_reject
    mem_bad = mem_floor > 0 and s.mem is not None and s.mem < mem_floor
    if not s.danger:
        if load_bad or mem_bad:
            _enter_danger_locked(now, load_bad=load_bad, mem_bad=mem_bad)
    else:
        load_ok = load_reject <= 0 or s.load is None or s.load <= load_resume
        mem_ok = mem_floor <= 0 or s.mem is None or s.mem >= mem_resume
        if load_ok and mem_ok:
            _release_danger_locked(now)

    if s.in_flight_units > 0 or _waiting_total() > 0 or s.last_busy == float("-inf"):
        s.last_busy = now
    if not settings.adaptive_admission_enabled:
        s.budget = max_units  # AIMD off: budget frozen at max, danger latch still applies
        return
    if now - s.last_adjust < float(settings.adaptive_admission_adjust_seconds):
        return
    s.last_adjust = now
    s.threadpool = _read_threadpool()
    before = s.budget
    reason = _shrink_reason(settings)
    if reason is not None:
        s.budget = max(min_units, s.budget * float(settings.adaptive_admission_decrease_factor))
        s.last_shrink_reason = reason
        s.shrink_counts[reason] += 1
    elif _hold(settings):
        pass
    else:
        step = (
            float(settings.adaptive_admission_fast_increase_units)
            if s.budget < max_units * 0.5
            else float(settings.adaptive_admission_increase_units)
        )
        s.budget = min(max_units, s.budget + step)
        idle = now - s.last_busy >= float(settings.adaptive_admission_idle_seconds)
        if idle:
            initial = max(
                min_units, min(max_units, float(settings.adaptive_admission_initial_units))
            )
            s.budget = max(s.budget, initial)
    if s.budget != before:
        LOGGER.info(
            "adaptive_budget from=%.1f to=%.1f reason=%s load=%s mem_mb=%s "
            "in_flight_units=%s queued=%s",
            before,
            s.budget,
            reason or "grow",
            s.load,
            s.mem,
            s.in_flight_units,
            _waiting_total(),
        )


def _enter_danger_locked(now: float, *, load_bad: bool, mem_bad: bool) -> None:
    s = _state
    reason = "+".join(name for name, bad in (("load", load_bad), ("mem", mem_bad)) if bad)
    s.danger = True
    s.danger_since = now
    s.danger_reason = reason
    s.danger_entries += 1
    LOGGER.warning(
        "admission_danger_entered reason=%s load=%s mem_mb=%s in_flight_units=%s queued=%s",
        reason,
        s.load,
        s.mem,
        s.in_flight_units,
        _waiting_total(),
    )


def _release_danger_locked(now: float) -> None:
    s = _state
    held = max(0.0, now - s.danger_since) if s.danger_since is not None else 0.0
    s.danger = False
    s.danger_releases += 1
    s.danger_seconds_total += held
    LOGGER.warning(
        "admission_danger_released reason=%s held_s=%.1f load=%s mem_mb=%s queued=%s",
        s.danger_reason,
        held,
        s.load,
        s.mem,
        _waiting_total(),
    )
    s.danger_since = None


def _shrink_reason(settings: Settings) -> str | None:
    """First server-side pressure signal that asks the budget to shrink."""

    s = _state
    soft_load = float(settings.adaptive_admission_soft_load)
    soft_mem = float(settings.adaptive_admission_soft_mem_mb)
    db_p95 = _DB_WRITE.p95()
    pool_p95 = _POOL_WAIT.p95()
    if s.danger:
        return "danger"
    if soft_load > 0 and s.load is not None and s.load >= soft_load:
        return "load"
    if soft_mem > 0 and s.mem is not None and s.mem < soft_mem:
        return "mem"
    if db_p95 is not None and db_p95 > settings.adaptive_admission_db_write_p95_ms:
        return "db_write_p95"
    if pool_p95 is not None and pool_p95 > settings.adaptive_admission_pool_wait_p95_ms:
        return "pool_wait_p95"
    return None


def _hold(settings: Settings) -> bool:
    """The band just short of shrinking: keep the budget where it is."""

    s = _state
    hold_load = float(settings.adaptive_admission_hold_load)
    hold_mem = float(settings.adaptive_admission_hold_mem_mb)
    hold_pool = float(settings.adaptive_admission_hold_threadpool_ratio)
    return (
        (hold_load > 0 and s.load is not None and s.load >= hold_load)
        or (hold_mem > 0 and s.mem is not None and s.mem < hold_mem)
        or (hold_pool > 0 and s.threadpool is not None and s.threadpool >= hold_pool)
    )


def _fits(weight: int, settings: Settings) -> bool:
    s = _state
    if s.danger:
        return False
    if sum(s.in_flight.values()) >= int(settings.adaptive_admission_max_in_flight):
        return False  # global hard cap
    # An idle process always admits one caller, so a weight above a shrunken
    # budget still makes progress instead of deadlocking.
    return s.in_flight_units == 0 or s.in_flight_units + weight <= s.budget


def _grant(waiter: _Waiter) -> None:
    s = _state
    waiter.granted = True
    s.in_flight_units += waiter.weight
    s.in_flight[waiter.cls] += 1
    s.admitted[waiter.cls] += 1


def _dispatch_locked(settings: Settings) -> bool:
    """Grant queued waiters round-robin across classes, FIFO within a class.

    When the class whose turn it is cannot fit, stop rather than letting
    lighter classes jump ahead; otherwise a steady stream of light work could
    starve heavy model calls forever.
    """

    s = _state
    granted_any = False
    while True:
        active = [name for name in CLASSES if s.queues[name]]
        if not active:
            break
        cls = None
        for offset in range(len(CLASSES)):
            candidate = CLASSES[(s.rr_index + offset) % len(CLASSES)]
            if s.queues[candidate]:
                cls = candidate
                break
        assert cls is not None
        head = s.queues[cls][0]
        if not _fits(head.weight, settings):
            break
        s.queues[cls].popleft()
        _grant(head)
        s.rr_index = (CLASSES.index(cls) + 1) % len(CLASSES)
        granted_any = True
    if granted_any:
        _cond.notify_all()
    return granted_any


def _waiting_total() -> int:
    return sum(len(q) for q in _state.queues.values())


def adaptive_admission_busy_error(
    *, cls: str, reason: str, retry_after_seconds: int
) -> PlatformError:
    s = _state
    return PlatformError(
        "adaptive_admission_busy",
        "The server is busy. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, retry_after_seconds),
            "reason": reason,
            "operation": cls,
            "adaptive_limit_units": round(s.budget, 2),
            "in_flight_units": s.in_flight_units,
            "waiters": _waiting_total(),
            "danger": s.danger,
        },
    )


class Reservation:
    """Admitted budget for one operation, releasable from any thread.

    A send claims its turn only after admission, but its model work runs on
    a worker thread; the reservation carries the slot across. ``release`` is
    idempotent, so every exit path may call it.
    """

    __slots__ = ("cls", "weight", "deadline", "settings", "_released")

    def __init__(self, cls: str, weight: int, deadline: float, settings: Settings) -> None:
        self.cls = cls
        self.weight = weight
        self.deadline = deadline
        self.settings = settings
        self._released = weight == 0

    def release(self) -> None:
        with _cond:
            if self._released:
                return
            self._released = True
            _state.in_flight_units = max(0, _state.in_flight_units - self.weight)
            _state.in_flight[self.cls] = max(0, _state.in_flight[self.cls] - 1)
            _refresh_locked(self.settings)
            _dispatch_locked(self.settings)


def reserve_slot(cls: str, settings: Settings | None = None) -> Reservation:
    """Wait for weighted budget for one ``cls`` operation and hold it.

    Raises the retryable ``adaptive_admission_busy`` 503 when the queue is
    full or the request deadline passes; nothing is held in that case.
    """

    runtime = settings if settings is not None else get_settings()
    if cls not in CLASSES:
        raise ValueError(f"unknown admission class: {cls}")
    if cls == "llm":
        _mark_request_llm()
    outer_deadline = getattr(_held, "deadline", None)
    depth = int(getattr(_held, "depth", 0))
    # One deadline per request, started at the first layer: the per-operation
    # backstop gate waits only for whatever is left of it (no double timeout).
    # A call nested in an admitted operation never queues here, so it starts a
    # fresh wait: a Team turn that ran past the request's 180 s must not give
    # its later model calls zero backstop wait.
    if outer_deadline is None or depth > 0:
        deadline = time.monotonic() + float(runtime.adaptive_admission_wait_seconds)
    else:
        deadline = outer_deadline
    weight = max(0, _weight(runtime, cls))
    reservation = Reservation(cls, weight, deadline, runtime)
    if weight == 0:
        return reservation
    retry_after = int(runtime.adaptive_admission_retry_seconds)
    waiter = _Waiter(cls=cls, weight=weight)
    with _cond:
        _refresh_locked(runtime)
        if depth > 0:
            _grant(waiter)
        elif _waiting_total() == 0 and _fits(weight, runtime):
            _grant(waiter)
        else:
            if _waiting_total() >= int(runtime.adaptive_admission_queue_max):
                _state.rejects[cls] += 1
                raise adaptive_admission_busy_error(
                    cls=cls, reason="queue_full", retry_after_seconds=retry_after
                )
            _state.queues[cls].append(waiter)
            poll = max(0.05, float(runtime.adaptive_admission_sample_seconds))
            while not waiter.granted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _state.queues[cls].remove(waiter)
                    _state.rejects[cls] += 1
                    # Our departure may unblock the next class in line.
                    _dispatch_locked(runtime)
                    raise adaptive_admission_busy_error(
                        cls=cls, reason="wait_timeout", retry_after_seconds=retry_after
                    )
                # Wake periodically: the danger latch only clears on a fresh
                # sample, which no release may trigger while nothing runs.
                _cond.wait(timeout=min(remaining, poll))
                if not waiter.granted:
                    _refresh_locked(runtime)
                    _dispatch_locked(runtime)
    return reservation


@contextmanager
def adopt_reservation(reservation: Reservation) -> Iterator[None]:
    """Run the ``with`` block as the holder of ``reservation``, then release it.

    Nested slots on this thread are charged without queueing behind it, and
    layer-2 gates wait only for what is left of its deadline.
    """

    depth = int(getattr(_held, "depth", 0))
    outer_deadline = getattr(_held, "deadline", None)
    if reservation.weight > 0:
        _held.depth = depth + 1
    _held.deadline = reservation.deadline
    try:
        yield
    finally:
        _held.depth = depth
        _held.deadline = outer_deadline
        reservation.release()


@contextmanager
def adaptive_slot(cls: str, settings: Settings | None = None) -> Iterator[None]:
    """Hold weighted budget for one ``cls`` operation; reads bypass entirely."""

    if cls == READ_CLASS:
        yield
        return
    reservation = reserve_slot(cls, settings)
    with adopt_reservation(reservation):
        yield


def shared_wait_seconds(cap: float) -> float:
    """Seconds a layer-2 gate may still wait: ``cap`` bounded by the request
    deadline set in ``adaptive_slot`` (0 when it already expired)."""

    deadline: float | None = getattr(_held, "deadline", None)
    if deadline is None:
        return cap
    return max(0.0, min(cap, deadline - time.monotonic()))


def adaptive_admission_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    """Metrics for /health/admission. Contains no secrets or user data."""

    runtime = settings if settings is not None else get_settings()
    with _cond:
        if runtime.adaptive_admission_enabled:
            _refresh_locked(runtime)
        s = _state
        return {
            "enabled": bool(runtime.adaptive_admission_enabled),
            "adaptive_limit_units": round(max(s.budget, 0.0), 2),
            "max_units": int(runtime.adaptive_admission_max_units),
            "min_units": int(
                min(runtime.adaptive_admission_min_units, runtime.adaptive_admission_max_units)
            ),
            "initial_units": int(runtime.adaptive_admission_initial_units),
            "max_in_flight": int(runtime.adaptive_admission_max_in_flight),
            "in_flight": sum(s.in_flight.values()),
            "in_flight_units": s.in_flight_units,
            "danger": s.danger,
            "danger_latch": {
                "entries": s.danger_entries,
                "releases": s.danger_releases,
                "reason": s.danger_reason,
                "active_seconds": (
                    round(max(0.0, _clock() - s.danger_since), 1)
                    if s.danger and s.danger_since is not None
                    else 0.0
                ),
                "total_seconds": round(s.danger_seconds_total, 1),
            },
            "load_1m": s.load,
            "mem_available_mb": s.mem,
            "db_write_p95_ms": _DB_WRITE.p95(),
            "pool_wait_p95_ms": _POOL_WAIT.p95(),
            "threadpool_usage": s.threadpool,
            # Observed only: it includes queue time, so it never drives AIMD.
            "request_p95_ms": _REQUEST.p95(),
            "last_shrink_reason": s.last_shrink_reason,
            "shrink_counts": dict(s.shrink_counts),
            "queue_depth": _waiting_total(),
            "classes": {
                name: {
                    "weight": _weight(runtime, name),
                    "queued": len(s.queues[name]),
                    "in_flight": s.in_flight[name],
                    "admitted": s.admitted[name],
                    "rejects": s.rejects[name],
                }
                for name in CLASSES
            },
        }


__all__ = [
    "CLASSES",
    "adaptive_admission_busy_error",
    "adaptive_admission_snapshot",
    "begin_request_sample",
    "record_request_sample",
    "adaptive_slot",
    "adopt_reservation",
    "Reservation",
    "reserve_slot",
    "record_db_write_ms",
    "record_pool_wait_ms",
    "record_request_ms",
    "reset_adaptive_admission_state",
    "set_signal_readers",
    "set_threadpool_reader",
    "shared_wait_seconds",
]
