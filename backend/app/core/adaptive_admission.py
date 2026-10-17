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
* AIMD: while load, MemAvailable, DB write p95 and request p95 are healthy
  the weighted budget grows additively; any soft-pressure signal shrinks it
  multiplicatively, never past configured min / max.
* Cost weights (llm heavy, create/write medium, login light, read free),
  FIFO per class, served round-robin so one class cannot starve others.
* One global in-flight hard cap per process; LLM calls, Team/Chat
  turns and creates additionally pass ``llm_admission`` / ``write_guard``
  (12) / ``create_admission`` (4) as per-operation backstops, which wait only for the remainder of
  this layer's deadline.
* Retryable ``adaptive_admission_busy`` 503 is raised only when the queue
  (max 200) is full or the single 180 s wait budget runs out.

``/proc/loadavg`` and ``/proc/meminfo`` are host-wide (not cgroup-scoped)
inside the production containers, so both backend replicas see the same
pressure and shrink together without extra shared state. Unreadable signals
fail open (only the global cap then applies).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from app.core import host_load_guard, memory_guard
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

CLASSES: tuple[str, ...] = ("llm", "create", "write", "login")
READ_CLASS = "read"

SignalReader = Callable[[], float | None]
_load_reader: SignalReader | None = None
_mem_reader: SignalReader | None = None
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


def _read_load() -> float | None:
    if _load_reader is not None:
        return _load_reader()
    return host_load_guard.active_reader()()


def _read_mem() -> float | None:
    if _mem_reader is not None:
        return _mem_reader()
    value = memory_guard.active_reader()()
    return None if value is None else float(value)


class _LatencyWindow:
    """Small ring buffer of recent durations (ms) for a cheap p95."""

    def __init__(self, size: int = 200) -> None:
        self._samples: deque[float] = deque(maxlen=size)
        self._lock = threading.Lock()

    def add(self, ms: float) -> None:
        with self._lock:
            self._samples.append(ms)

    def p95(self) -> float | None:
        with self._lock:
            if len(self._samples) < 10:
                return None  # too few samples to judge; treat as unknown
            ordered = sorted(self._samples)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


_DB_WRITE = _LatencyWindow()
_REQUEST = _LatencyWindow()


def record_db_write_ms(ms: float) -> None:
    _DB_WRITE.add(ms)


def record_request_ms(ms: float) -> None:
    _REQUEST.add(ms)


@dataclass
class _Waiter:
    cls: str
    weight: int
    granted: bool = False


@dataclass
class _State:
    budget: float = -1.0  # <0 means "not initialised yet"
    in_flight_units: int = 0
    last_adjust: float = float("-inf")
    last_sample: float = float("-inf")
    danger: bool = False
    load: float | None = None
    mem: float | None = None
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
    if s.budget < 0:
        s.budget = max_units  # start open; pressure will pull it down
    now = _clock()
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
        s.danger = load_bad or mem_bad
    else:
        load_ok = load_reject <= 0 or s.load is None or s.load <= load_resume
        mem_ok = mem_floor <= 0 or s.mem is None or s.mem >= mem_resume
        s.danger = not (load_ok and mem_ok)

    if not settings.adaptive_admission_enabled:
        return  # AIMD off: budget stays at max, danger latch still applies
    if now - s.last_adjust < float(settings.adaptive_admission_adjust_seconds):
        return
    s.last_adjust = now
    db_p95 = _DB_WRITE.p95()
    req_p95 = _REQUEST.p95()
    soft_load = float(settings.adaptive_admission_soft_load)
    soft_mem = float(settings.adaptive_admission_soft_mem_mb)
    pressured = (
        s.danger
        or (soft_load > 0 and s.load is not None and s.load >= soft_load)
        or (soft_mem > 0 and s.mem is not None and s.mem < soft_mem)
        or (db_p95 is not None and db_p95 > settings.adaptive_admission_db_write_p95_ms)
        or (req_p95 is not None and req_p95 > settings.adaptive_admission_request_p95_ms)
    )
    if pressured:
        s.budget = max(min_units, s.budget * float(settings.adaptive_admission_decrease_factor))
    else:
        s.budget = min(max_units, s.budget + float(settings.adaptive_admission_increase_units))


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


@contextmanager
def adaptive_slot(cls: str, settings: Settings | None = None) -> Iterator[None]:
    """Hold weighted budget for one ``cls`` operation; reads bypass entirely."""

    runtime = settings if settings is not None else get_settings()
    if cls == READ_CLASS:
        yield
        return
    if cls not in CLASSES:
        raise ValueError(f"unknown admission class: {cls}")
    outer_deadline = getattr(_held, "deadline", None)
    # One deadline per request, started at the first layer: the per-operation
    # backstop gate waits only for whatever is left of it (no double timeout).
    deadline = (
        outer_deadline
        if outer_deadline is not None
        else time.monotonic() + float(runtime.adaptive_admission_wait_seconds)
    )
    weight = max(0, _weight(runtime, cls))
    if weight == 0:
        _held.deadline = deadline
        try:
            yield
        finally:
            _held.deadline = outer_deadline
        return
    retry_after = int(runtime.adaptive_admission_retry_seconds)
    waiter = _Waiter(cls=cls, weight=weight)
    depth = int(getattr(_held, "depth", 0))
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
    _held.depth = depth + 1
    _held.deadline = deadline
    try:
        yield
    finally:
        _held.depth = depth
        _held.deadline = outer_deadline
        with _cond:
            _state.in_flight_units = max(0, _state.in_flight_units - weight)
            _state.in_flight[cls] = max(0, _state.in_flight[cls] - 1)
            _refresh_locked(runtime)
            _dispatch_locked(runtime)


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
            "max_in_flight": int(runtime.adaptive_admission_max_in_flight),
            "in_flight": sum(s.in_flight.values()),
            "in_flight_units": s.in_flight_units,
            "danger": s.danger,
            "load_1m": s.load,
            "mem_available_mb": s.mem,
            "db_write_p95_ms": _DB_WRITE.p95(),
            "request_p95_ms": _REQUEST.p95(),
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
    "adaptive_slot",
    "record_db_write_ms",
    "record_request_ms",
    "reset_adaptive_admission_state",
    "set_signal_readers",
    "shared_wait_seconds",
]
