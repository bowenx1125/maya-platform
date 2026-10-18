"""Live view of the per-operation gates behind the adaptive queue.

Each gate is per process (one backend replica). ``/health/admission`` shows
its configured limit next to how many callers hold a slot and how many wait,
so a load test can see which gate is the one holding work back.
"""

from __future__ import annotations

from app.core import create_admission, hash_gate, llm_admission, write_guard
from app.core.concurrency_gate import ConcurrencyGate
from app.core.config import Settings


def _usage(gate: ConcurrencyGate, limit: int) -> dict[str, int | bool]:
    return {
        "limit": limit,
        "enabled": limit > 0,
        "in_flight": gate.in_flight,
        "waiters": gate.waiters,
    }


def backstop_usage(settings: Settings) -> dict[str, dict[str, int | bool]]:
    return {
        "llm_admission": _usage(llm_admission._GATE, int(settings.llm_admission_limit)),
        "write_guard": _usage(write_guard._GATE, int(settings.write_guard_limit)),
        "create_admission": _usage(create_admission._GATE, int(settings.create_admission_limit)),
        "auth_hash": _usage(hash_gate._GATE, int(settings.auth_hash_concurrency)),
    }


__all__ = ["backstop_usage"]
