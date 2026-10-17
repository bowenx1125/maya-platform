"""Process-local concurrency gate with a bounded wait queue.

Used by LLM admission and write-path guards. Callers acquire a slot (waiting
briefly when the in-flight cap is full) and always release it afterwards.
In-flight work is never cancelled. A limit of 0 disables the gate.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager


class GateRejected(Exception):
    """The wait queue is full or the wait budget expired."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ConcurrencyGate:
    """Thread-safe in-flight counter with Condition-based waiters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._in_flight = 0
        self._waiters = 0

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    @property
    def waiters(self) -> int:
        with self._lock:
            return self._waiters

    def reset(self) -> None:
        """Drop counters (tests only). Wake any waiters so they re-check."""

        with self._cond:
            self._in_flight = 0
            self._waiters = 0
            self._cond.notify_all()

    def acquire(self, *, limit: int, queue_max: int, wait_seconds: float) -> bool:
        """Take one slot, waiting up to ``wait_seconds``; ``False`` means unthrottled.

        Raises ``GateRejected`` when the wait queue is full or the wait ends.
        A ``True`` result must be paired with exactly one ``release()``, which
        may run on another thread.
        """

        if limit <= 0:
            return False
        with self._cond:
            if self._in_flight < limit:
                self._in_flight += 1
                return True
            if queue_max <= 0 or self._waiters >= queue_max:
                raise GateRejected("queue_full")
            self._waiters += 1
            try:
                deadline = time.monotonic() + max(0.0, float(wait_seconds))
                while self._in_flight >= limit:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GateRejected("wait_timeout")
                    self._cond.wait(timeout=remaining)
                self._in_flight += 1
                return True
            finally:
                self._waiters -= 1

    def release(self) -> None:
        with self._cond:
            self._in_flight = max(0, self._in_flight - 1)
            self._cond.notify()

    @contextmanager
    def hold(
        self,
        *,
        limit: int,
        queue_max: int,
        wait_seconds: float,
    ) -> Iterator[None]:
        """Acquire one slot for the duration of the ``with`` block.

        * ``limit <= 0``: no throttling (yield immediately).
        * Under the limit: admit at once.
        * At the limit with room in the wait queue: block until a slot frees
          or ``wait_seconds`` elapses (then raise ``GateRejected``).
        * Wait queue full: raise ``GateRejected`` immediately.
        """

        acquired = self.acquire(limit=limit, queue_max=queue_max, wait_seconds=wait_seconds)
        try:
            yield
        finally:
            if acquired:
                self.release()


__all__ = ["ConcurrencyGate", "GateRejected"]
