"""Pressure protection for Debate audience traffic (votes, barrages, live views).

Load plan 2026-10-19: 60 anonymous viewers voting, sending barrages and
watching a Debate must never starve assessment scoring or chat. Before this,
none of these routes passed any admission: each vote or barrage opened a
writer transaction on the window row, and the live views read the database
for every viewer, every second.

* ``interaction_slot`` -- a small per-process asyncio gate
  (``DEBATE_INTERACTION_GATE_LIMIT``, default 4) with a bounded queue and a
  wait limit. It ranks below the adaptive admission classes: under the danger
  latch it refuses at once (503) and never takes a reserved slot, and while
  scoring/chat work is queued for the adaptive budget it lets them go first.
  A full queue or a spent wait answers 503 with ``retry_after_seconds``.
* ``PublicCopy`` -- the last answer of a cheap read (the anonymous form, the
  live snapshot), served while fresh, and served stale instead of reading
  the database while the server sheds load.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Hashable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.core.adaptive_admission import admission_waiting, danger_latched, polling_pressure
from app.core.config import Settings
from app.core.errors import PlatformError

# How often a queued audience request looks again while higher-priority work
# waits for the adaptive budget.
_YIELD_POLL_SECONDS = 0.05


def debate_busy_error(reason: str, retry_after_seconds: int) -> PlatformError:
    """503 the audience client treats as "busy, try again shortly"."""

    return PlatformError(
        "debate_interaction_busy",
        "Many people are taking part right now. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, int(retry_after_seconds)),
            "reason": reason,
        },
    )


class _Gate:
    """Bounded concurrency with a bounded FIFO queue, per event loop."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.waiters = 0
        self._condition: asyncio.Condition | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _cond(self) -> asyncio.Condition:
        loop = asyncio.get_running_loop()
        if self._condition is None or self._loop is not loop:
            # A new loop (test clients) starts with a fresh, empty gate.
            self._condition = asyncio.Condition()
            self._loop = loop
            self.in_flight = 0
            self.waiters = 0
        return self._condition

    def reset(self) -> None:
        self.in_flight = 0
        self.waiters = 0
        self._condition = None
        self._loop = None


_GATE = _Gate()


def reset_debate_gate() -> None:
    """Forget in-flight/queued counts (tests only)."""

    _GATE.reset()


def debate_gate_snapshot() -> dict[str, int]:
    return {"in_flight": _GATE.in_flight, "waiters": _GATE.waiters}


@asynccontextmanager
async def interaction_slot(settings: Settings) -> AsyncIterator[None]:
    """Hold one Debate audience write slot for the ``async with`` block."""

    retry = int(settings.debate_interaction_retry_seconds)
    if danger_latched(settings):
        # The reserve belongs to scoring and chat; audience writes wait outside.
        raise debate_busy_error("danger", retry)
    limit = int(settings.debate_interaction_gate_limit)
    if limit <= 0:
        yield
        return
    condition = _GATE._cond()
    deadline = time.monotonic() + float(settings.debate_interaction_gate_wait_seconds)
    async with condition:
        if _GATE.waiters >= int(settings.debate_interaction_gate_queue_max) and (
            _GATE.in_flight >= limit
        ):
            raise debate_busy_error("queue_full", retry)
        _GATE.waiters += 1
        try:
            while _GATE.in_flight >= limit or admission_waiting() > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise debate_busy_error("wait_timeout", retry)
                if danger_latched(settings):
                    raise debate_busy_error("danger", retry)
                timeout = (
                    min(remaining, _YIELD_POLL_SECONDS) if _GATE.in_flight < limit else remaining
                )
                try:
                    await asyncio.wait_for(condition.wait(), timeout=timeout)
                except TimeoutError:
                    continue
            _GATE.in_flight += 1
        finally:
            _GATE.waiters -= 1
    try:
        yield
    finally:
        async with condition:
            _GATE.in_flight -= 1
            condition.notify(1)


@dataclass
class _Copy:
    value: Any
    stored_at: float


class PublicCopy:
    """Last answers of a cheap public read, keyed per resource, thread-safe."""

    def __init__(self, max_entries: int = 512) -> None:
        self._items: dict[Hashable, _Copy] = {}
        self._lock = Lock()
        self._max = max_entries

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def get(self, key: Hashable, max_age: float) -> Any | None:
        with self._lock:
            item = self._items.get(key)
        if item is None or time.monotonic() - item.stored_at > max_age:
            return None
        return item.value

    def put(self, key: Hashable, value: Any) -> None:
        with self._lock:
            if len(self._items) >= self._max and key not in self._items:
                oldest = min(self._items, key=lambda k: self._items[k].stored_at)
                self._items.pop(oldest, None)
            self._items[key] = _Copy(value, time.monotonic())

    def read(
        self,
        key: Hashable,
        settings: Settings,
        load: Callable[[], Any],
        *,
        what: str,
    ) -> Any:
        """A fresh copy, else (under pressure) a stale one or 503, else ``load()``."""

        fresh = self.get(key, float(settings.debate_public_cache_seconds))
        if fresh is not None:
            return fresh
        if polling_pressure(settings):
            stale = self.get(key, float(settings.debate_public_stale_seconds))
            if stale is not None:
                return stale
            raise debate_busy_error(
                f"{what}_pressure", int(settings.debate_interaction_retry_seconds)
            )
        value = load()
        self.put(key, value)
        return value


__all__ = [
    "PublicCopy",
    "debate_busy_error",
    "debate_gate_snapshot",
    "interaction_slot",
    "reset_debate_gate",
]
