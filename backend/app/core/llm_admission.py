"""Admit LLM HTTP attempts under a process-local concurrency cap.

MayaLoad's real-model Team assessment run showed 10 concurrent users stable
(peak load ~3.8) and 20 concurrent blowing host load past 8. Cap default is
12 (midpoint of the 10–15 recommendation). Callers wait in a bounded queue
so messages still send when a slot frees; only a full queue or wait timeout
returns a retryable 503. In-flight calls are never cancelled. Limit 0
disables the gate. This is now the only per-operation backstop; it sits
behind the unified adaptive queue and shares its single wait deadline.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.adaptive_admission import adaptive_slot, shared_wait_seconds
from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

_GATE = ConcurrencyGate()


def reset_llm_admission_state() -> None:
    """Clear in-flight / waiter counters (tests only)."""

    _GATE.reset()


def llm_admission_busy_error(
    *,
    reason: str,
    limit: int,
    retry_after_seconds: int,
    in_flight: int,
    waiters: int,
) -> PlatformError:
    """Build the 503 clients should treat as a short, retryable pause."""

    return PlatformError(
        "llm_admission_busy",
        "The server is handling many model requests. Wait a moment and try again.",
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
def llm_admission_slot(settings: Settings | None = None) -> Iterator[None]:
    """Hold one LLM in-flight slot for the duration of the ``with`` block."""

    runtime = settings if settings is not None else get_settings()
    # Layer 1: the unified pressure queue (suspends under the danger line).
    with adaptive_slot("llm", runtime):
        limit = int(runtime.llm_admission_limit)
        if limit <= 0:
            yield
            return
        queue_max = int(runtime.llm_admission_queue_max)
        # Layer 2 backstop waits only for what is left of the one request
        # deadline started in layer 1, so a call is never timed twice.
        wait_seconds = shared_wait_seconds(float(runtime.llm_admission_wait_seconds))
        retry_after = int(runtime.llm_admission_retry_seconds)
        try:
            with _GATE.hold(limit=limit, queue_max=queue_max, wait_seconds=wait_seconds):
                yield
        except GateRejected as rejected:
            raise llm_admission_busy_error(
                reason=rejected.reason,
                limit=limit,
                retry_after_seconds=retry_after,
                in_flight=_GATE.in_flight,
                waiters=_GATE.waiters,
            ) from None


__all__ = [
    "llm_admission_busy_error",
    "llm_admission_slot",
    "reset_llm_admission_state",
]
