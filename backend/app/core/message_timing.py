"""Per-student-message timing breakdown (structured log + rolling summary).

One collector lives in a ContextVar for the duration of one student message
(a Single Chat reply or a Team turn). Admission gates, the LLM transport and
the DB write timer add to it, so nested calls accumulate without being passed
around. Sync FastAPI handlers run in a threadpool copy of the context; the
collector object is shared by reference, so additions made there are seen.

On exit one JSON log line is emitted (``"event":"message_timing"`` on the
``maya.message_timing`` logger) and the totals feed a 15-minute rolling window
that ``/health/admission`` exposes as p50/p95. Nothing here records message
text, prompts, provider payloads or user data: only ids, labels and timings.

Provider calls are non-streaming today, so ``ttft_ms`` is the time until the
complete response arrived (first token == whole body); it becomes a real TTFT
once a streaming transport records it.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("maya.message_timing")

WINDOW_SECONDS = 900.0
WINDOW_MAX_MESSAGES = 1000
MAX_LOGGED_CALLS = 20


class MessageTiming:
    """Mutable accumulator for one student message."""

    def __init__(self, kind: str, ids: dict[str, str]) -> None:
        self.kind = kind
        self.ids = ids
        self.started = time.perf_counter()
        self.queue_wait_ms = 0.0
        self.db_write_ms = 0.0
        self.db_writes = 0
        self.calls: list[dict[str, Any]] = []
        self.call_count = 0
        self.retry = False
        self.inner_error = False
        # A handled failure (a Team turn that settles failed or partial) the
        # code below never sees as an exception.
        self.outcome: str | None = None
        self._last_failed = False
        self._lock = threading.Lock()

    def add_queue_wait(self, ms: float) -> None:
        with self._lock:
            self.queue_wait_ms += ms

    def add_db_write(self, ms: float) -> None:
        with self._lock:
            self.db_write_ms += ms
            self.db_writes += 1

    def add_model_call(
        self,
        *,
        label: str,
        duration_ms: float,
        ttft_ms: float | None,
        status: int | None,
        failed: bool,
        retry: bool = False,
    ) -> None:
        with self._lock:
            # A call that follows a failed call inside the same message is a
            # retry even when the caller did not say so.
            is_retry = retry or self._last_failed
            self._last_failed = failed
            self.retry = self.retry or is_retry
            self.call_count += 1
            if len(self.calls) < MAX_LOGGED_CALLS:
                self.calls.append(
                    {
                        "label": label,
                        "duration_ms": round(duration_ms, 1),
                        "ttft_ms": None if ttft_ms is None else round(ttft_ms, 1),
                        "status": status,
                        "failed": failed,
                        "retry": is_retry,
                    }
                )

    def record(self, outcome: str) -> dict[str, Any]:
        total_ms = (time.perf_counter() - self.started) * 1000.0
        with self._lock:
            return {
                "event": "message_timing",
                "kind": self.kind,
                **self.ids,
                "outcome": outcome,
                "total_ms": round(total_ms, 1),
                "queue_wait_ms": round(self.queue_wait_ms, 1),
                "db_write_ms": round(self.db_write_ms, 1),
                "db_writes": self.db_writes,
                "llm_calls": self.call_count,
                "retry": self.retry,
                "model_calls": list(self.calls),
            }


_CURRENT: ContextVar[MessageTiming | None] = ContextVar("maya_message_timing", default=None)


class _Window:
    """Recent message records (bounded by age and count) for p50/p95."""

    def __init__(self) -> None:
        self._items: deque[tuple[float, dict[str, Any]]] = deque(maxlen=WINDOW_MAX_MESSAGES)
        self._lock = threading.Lock()

    def add(self, record: dict[str, Any]) -> None:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            self._items.append((now, record))

    def _expire(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self._items and self._items[0][0] < cutoff:
            self._items.popleft()

    def records(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            return [record for _, record in self._items]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_WINDOW = _Window()


def current() -> MessageTiming | None:
    return _CURRENT.get()


@contextmanager
def message_timing(kind: str, **ids: object) -> Iterator[MessageTiming]:
    """Collect timings for one student message; nested use joins the outer one."""

    existing = _CURRENT.get()
    if existing is not None:
        try:
            yield existing
        except BaseException:
            # The handler may swallow a failed reply and still answer 200.
            existing.inner_error = True
            raise
        return
    timing = MessageTiming(kind, {key: str(value) for key, value in ids.items() if value})
    token = _CURRENT.set(timing)
    outcome = "error"
    try:
        yield timing
        outcome = timing.outcome or ("error" if timing.inner_error else "ok")
    finally:
        _CURRENT.reset(token)
        record = timing.record(outcome)
        _WINDOW.add(record)
        try:
            logger.info(json.dumps(record, separators=(",", ":"), sort_keys=False))
        except Exception:  # pragma: no cover - logging must never break a reply
            pass


def set_outcome(outcome: str) -> None:
    """Record how the message ended when that is not an exception.

    Prod (2026-10-18): Team turns that failed were logged as outcome "ok",
    because member failures settle as rows rather than raise.
    """

    timing = _CURRENT.get()
    if timing is not None:
        timing.outcome = outcome


def add_queue_wait(ms: float) -> None:
    timing = _CURRENT.get()
    if timing is not None:
        timing.add_queue_wait(ms)


def add_db_write(ms: float) -> None:
    timing = _CURRENT.get()
    if timing is not None:
        timing.add_db_write(ms)


def add_model_call(
    *,
    label: str,
    duration_ms: float,
    ttft_ms: float | None,
    status: int | None,
    failed: bool,
    retry: bool = False,
) -> None:
    timing = _CURRENT.get()
    if timing is not None:
        timing.add_model_call(
            label=label,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            status=status,
            failed=failed,
            retry=retry,
        )


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None}
    ordered = sorted(values)
    last = len(ordered) - 1
    return {
        "p50": round(ordered[min(last, int(len(ordered) * 0.5))], 1),
        "p95": round(ordered[min(last, int(len(ordered) * 0.95))], 1),
    }


def message_timing_snapshot() -> dict[str, Any]:
    """Rolling summary for /health/admission (no ids, no user data)."""

    records = _WINDOW.records()
    ttfts = [
        float(call["ttft_ms"])
        for record in records
        for call in record["model_calls"]
        if call.get("ttft_ms") is not None
    ]
    return {
        "window_seconds": int(WINDOW_SECONDS),
        "messages": len(records),
        "errors": sum(1 for record in records if record["outcome"] != "ok"),
        "with_retry": sum(1 for record in records if record["retry"]),
        "total_ms": _percentiles([float(record["total_ms"]) for record in records]),
        "queue_wait_ms": _percentiles([float(record["queue_wait_ms"]) for record in records]),
        "db_write_ms": _percentiles([float(record["db_write_ms"]) for record in records]),
        # Write statements per message (load_tune reports it per step).
        "db_writes_per_msg": _percentiles(
            [float(record.get("db_writes", 0)) for record in records]
        ),
        "llm_calls_per_msg": _percentiles([float(record["llm_calls"]) for record in records]),
        "ttft_ms": _percentiles(ttfts),
    }


def reset_message_timing_state() -> None:
    """Drop the rolling window (tests only)."""

    _WINDOW.clear()


__all__ = [
    "MessageTiming",
    "add_db_write",
    "add_model_call",
    "add_queue_wait",
    "current",
    "message_timing",
    "message_timing_snapshot",
    "reset_message_timing_state",
]
