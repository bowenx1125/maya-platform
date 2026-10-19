"""Limit concurrent Team / Chat write-heavy turns on a small host.

Paired with LLM admission: MayaLoad's 20-user assessment spike melted host
load (peak ~8.5 on 2 vCPU) via concurrent turn execution and DB writes even
when MemAvailable stayed healthy. Default cap 12 matches the LLM band.
Callers wait in a bounded queue so the send still completes when a slot
frees; a full queue or wait timeout returns a retryable 503. Limit 0
disables the gate. In-flight turns are not cancelled.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.adaptive_admission import Reservation, adopt_reservation, reserve_slot
from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.message_timing import add_queue_wait

_GATE = ConcurrencyGate()
# Write slots held by this thread (a send reserves before claiming, then its
# reply generation asks again on the same thread).
_held = threading.local()


def reset_write_guard_state() -> None:
    """Clear in-flight / waiter counters (tests only)."""

    _GATE.reset()


def write_pressure_error(
    *,
    reason: str,
    limit: int,
    retry_after_seconds: int,
    in_flight: int,
    waiters: int,
) -> PlatformError:
    """Build the 503 clients should treat as a short, retryable pause."""

    return PlatformError(
        "write_pressure",
        "The server is busy saving chat activity. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, retry_after_seconds),
            "reason": reason,
            "limit": limit,
            "in_flight": in_flight,
            "waiters": waiters,
        },
    )


class WriteSlot:
    """A held write slot (both layers), releasable once from any thread."""

    __slots__ = (
        "reservation",
        "gate_acquired",
        "entered",
        "_lock",
        "_released",
        "_adopted",
        "__weakref__",
    )

    def __init__(self, reservation: Reservation, gate_acquired: bool, entered: float) -> None:
        self.reservation = reservation
        self.gate_acquired = gate_acquired
        self.entered = entered
        self._lock = threading.Lock()
        self._released = False
        self._adopted = False

    def adopt(self) -> None:
        with self._lock:
            self._adopted = True

    def release_if_unadopted(self) -> None:
        """Give the slot back unless a worker is running on it.

        A stream that closes (or never starts) before its worker adopted the
        slot releases it; a running worker keeps it until the turn ends.
        """

        with self._lock:
            if self._adopted:
                return
        self.release()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        if self.gate_acquired:
            _GATE.release()
        self.reservation.release()


def reserve_write_slot(settings: Settings | None = None, *, priority: bool = False) -> WriteSlot:
    """Wait for a Chat/Team turn's write slot before anything is stored.

    A rejection (queue full, wait over) raises its retryable 503 and holds
    nothing, so the student's message was never saved and nothing replays it.
    ``priority`` (Scorer/Summarizer finishing) goes first in layer 1.
    """

    runtime = settings if settings is not None else get_settings()
    entered = time.perf_counter()
    # Layer 1: the unified pressure queue (suspends under the danger line).
    reservation = reserve_slot("write", runtime, priority=priority)
    limit = int(runtime.write_guard_limit)
    if limit <= 0:
        return WriteSlot(reservation, False, entered)
    # Layer 2 backstop waits only for what is left of the one request
    # deadline started in layer 1, so a turn is never timed twice.
    wait_seconds = max(
        0.0,
        min(float(runtime.write_guard_wait_seconds), reservation.deadline - time.monotonic()),
    )
    try:
        acquired = _GATE.acquire(
            limit=limit, queue_max=int(runtime.write_guard_queue_max), wait_seconds=wait_seconds
        )
    except GateRejected as rejected:
        reservation.release()
        raise write_pressure_error(
            reason=rejected.reason,
            limit=limit,
            retry_after_seconds=int(runtime.write_guard_retry_seconds),
            in_flight=_GATE.in_flight,
            waiters=_GATE.waiters,
        ) from None
    return WriteSlot(reservation, acquired, entered)


@contextmanager
def write_guard_slot(
    settings: Settings | None = None, *, reserved: WriteSlot | None = None
) -> Iterator[None]:
    """Hold one write-path slot for the duration of the ``with`` block.

    ``reserved`` adopts a slot taken earlier (possibly on another thread).
    On a thread that already holds a write slot this is a no-op, so a send
    that reserved before claiming does not take a second one for its reply.
    """

    if reserved is None and int(getattr(_held, "depth", 0)) > 0:
        yield
        return
    slot = reserved if reserved is not None else reserve_write_slot(settings)
    slot.adopt()
    # Time spent in both layers before the work starts.
    add_queue_wait((time.perf_counter() - slot.entered) * 1000.0)
    _held.depth = int(getattr(_held, "depth", 0)) + 1
    try:
        with adopt_reservation(slot.reservation):
            yield
    finally:
        _held.depth -= 1
        slot.release()


__all__ = [
    "WriteSlot",
    "reserve_write_slot",
    "reset_write_guard_state",
    "write_guard_slot",
    "write_pressure_error",
]
