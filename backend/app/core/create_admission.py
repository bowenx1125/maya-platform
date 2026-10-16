"""Admit Agent / Team / Conversation create under a process-local concurrency cap.

MayaLoad's n=40 ChatForm run spiked host load to ~13.5 during concurrent
create-Agent/Team before any LLM admission 503 fired. Cap default is 4 per
process so two backend replicas admit at most ~8 creates at once. Callers wait
in a bounded queue; a full queue or wait timeout returns retryable 503.
Limit 0 disables the gate. In-flight creates are never cancelled.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError
from app.core.host_load_guard import ensure_host_load_ok

_GATE = ConcurrencyGate()


def reset_create_admission_state() -> None:
    """Clear in-flight / waiter counters (tests only)."""

    _GATE.reset()


def create_admission_busy_error(
    *,
    reason: str,
    limit: int,
    retry_after_seconds: int,
    in_flight: int,
    waiters: int,
) -> PlatformError:
    """Build the 503 clients should treat as a short, retryable pause."""

    return PlatformError(
        "create_admission_busy",
        "The server is handling many create requests. Wait a moment and try again.",
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
def create_admission_slot(settings: Settings | None = None) -> Iterator[None]:
    """Hold one create-path slot for the duration of the ``with`` block."""

    runtime = settings if settings is not None else get_settings()
    # Host load is checked before and after any queue wait so a spiked host
    # rejects creates even when the create gate still has room.
    ensure_host_load_ok(runtime)
    limit = int(runtime.create_admission_limit)
    if limit <= 0:
        yield
        return
    queue_max = int(runtime.create_admission_queue_max)
    wait_seconds = float(runtime.create_admission_wait_seconds)
    retry_after = int(runtime.create_admission_retry_seconds)
    try:
        with _GATE.hold(limit=limit, queue_max=queue_max, wait_seconds=wait_seconds):
            ensure_host_load_ok(runtime)
            yield
    except GateRejected as rejected:
        raise create_admission_busy_error(
            reason=rejected.reason,
            limit=limit,
            retry_after_seconds=retry_after,
            in_flight=_GATE.in_flight,
            waiters=_GATE.waiters,
        ) from None


__all__ = [
    "create_admission_busy_error",
    "create_admission_slot",
    "reset_create_admission_state",
]
