"""Limit concurrent Team / Chat write-heavy turns on a small host.

Paired with LLM admission: MayaLoad's 20-user assessment spike melted host
load (peak ~8.5 on 2 vCPU) via concurrent turn execution and DB writes even
when MemAvailable stayed healthy. Default cap 12 matches the LLM band.
Callers wait in a bounded queue so the send still completes when a slot
frees; a full queue or wait timeout returns a retryable 503. Limit 0
disables the gate. In-flight turns are not cancelled.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

_GATE = ConcurrencyGate()


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


@contextmanager
def write_guard_slot(settings: Settings | None = None) -> Iterator[None]:
    """Hold one write-path slot for the duration of the ``with`` block."""

    runtime = settings if settings is not None else get_settings()
    limit = int(runtime.write_guard_limit)
    if limit <= 0:
        yield
        return
    queue_max = int(runtime.write_guard_queue_max)
    wait_seconds = float(runtime.write_guard_wait_seconds)
    retry_after = int(runtime.write_guard_retry_seconds)
    try:
        with _GATE.hold(limit=limit, queue_max=queue_max, wait_seconds=wait_seconds):
            yield
    except GateRejected as rejected:
        raise write_pressure_error(
            reason=rejected.reason,
            limit=limit,
            retry_after_seconds=retry_after,
            in_flight=_GATE.in_flight,
            waiters=_GATE.waiters,
        ) from None


__all__ = [
    "reset_write_guard_state",
    "write_guard_slot",
    "write_pressure_error",
]
