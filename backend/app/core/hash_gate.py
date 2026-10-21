"""Cap concurrent Argon2 hash / verify work per process.

Every pwdlib ``PasswordHash.recommended()`` call allocates its full
``memory_cost`` (Argon2id m=65536 KiB = 64 MiB) for the duration of the
hash and frees it right after. MayaLoad's 2026-10-17 16:19 JST run sent 20
logins within ~4 s: each one passed adaptive admission against the
pre-burst MemAvailable (~1.5 GB) and then allocated 64 MiB at once, so host
MemAvailable fell to 463 MB before any pressure sample could see it.

This gate bounds that burst to ``AUTH_HASH_CONCURRENCY`` (default 2) hashes
per process, roughly the classroom host's CPU core count. It wraps only the
Argon2 call itself (not the DB work or the
session write). Callers are synchronous FastAPI handlers that already run in
the threadpool, so blocking here never stalls the event loop. A waiter only
waits for what is left of the request's single adaptive-admission deadline
(180 s by default); past it, or when the wait queue is full, a retryable 503
is returned. Argon2 parameters are unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.core.adaptive_admission import shared_wait_seconds
from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

_GATE = ConcurrencyGate()


def reset_hash_gate_state() -> None:
    """Clear in-flight / waiter counters (tests only)."""

    _GATE.reset()


def hash_gate_in_flight() -> int:
    return _GATE.in_flight


def auth_hash_busy_error(*, reason: str, limit: int, retry_after_seconds: int) -> PlatformError:
    return PlatformError(
        "adaptive_admission_busy",
        "The server is busy. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, retry_after_seconds),
            "reason": f"hash_{reason}",
            "operation": "password_hash",
            "limit": limit,
            "waiters": _GATE.waiters,
        },
    )


@contextmanager
def hash_slot(settings: Settings | None = None) -> Iterator[None]:
    """Hold one Argon2 slot for the duration of the ``with`` block."""

    runtime = settings if settings is not None else get_settings()
    limit = int(runtime.auth_hash_concurrency)
    wait_seconds = shared_wait_seconds(float(runtime.adaptive_admission_wait_seconds))
    try:
        with _GATE.hold(
            limit=limit,
            queue_max=int(runtime.adaptive_admission_queue_max),
            wait_seconds=wait_seconds,
        ):
            yield
    except GateRejected as rejected:
        raise auth_hash_busy_error(
            reason=rejected.reason,
            limit=limit,
            retry_after_seconds=int(runtime.adaptive_admission_retry_seconds),
        ) from None


def run_hash[T](fn: Callable[[], T], settings: Settings | None = None) -> T:
    """Run one Argon2 hash / verify callable inside the gate."""

    with hash_slot(settings):
        return fn()


__all__ = [
    "auth_hash_busy_error",
    "hash_gate_in_flight",
    "hash_slot",
    "reset_hash_gate_state",
    "run_hash",
]
