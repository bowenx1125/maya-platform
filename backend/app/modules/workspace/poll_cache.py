"""Cheap answers to conversation polling while admission sheds load.

60-student rerun (2026-10-19): with the danger latch closed and nothing
admitted, about 55 waiting students polling ``GET /conversations/{id}`` once a
second (plus busy retries) kept both uvicorn workers at 50-90% CPU and load at
4.7-5.9, so the latch never cleared. A conversation view runs one query per
turn plus the Team projection; rebuilding it every second for a chat that has
not moved is pure overhead.

While ``polling_pressure`` holds (danger latched, ramping up after a release,
or a fast brake signal bad), the owner's view is kept for a few seconds per
(user, conversation, revision). Any change that bumps the conversation's
revision (a send, a turn finishing) misses the cache at once; other changes
(scoring progress) show up within the TTL. Outside pressure nothing is
cached and every poll is built fresh, exactly as before.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

MAX_ENTRIES = 4096
# Seconds clients should wait before polling again (sent only under pressure).
POLL_AFTER_HEADER = "X-Maya-Poll-After"

_clock: Callable[[], float] = time.monotonic


def set_clock(clock: Callable[[], float] | None) -> None:
    """Override the clock (tests only). ``None`` restores it."""

    global _clock
    _clock = clock if clock is not None else time.monotonic


class ConversationPollCache:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max_entries
        self._lock = threading.Lock()
        self._rows: OrderedDict[tuple[str, str], tuple[float, int, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, user_id: str, conversation_id: str, revision: int, max_age: float) -> Any:
        key = (user_id, conversation_id)
        now = _clock()
        with self._lock:
            row = self._rows.get(key)
            if row is None or row[1] != revision or now - row[0] > max_age:
                self.misses += 1
                return None
            self.hits += 1
            return row[2]

    def put(self, user_id: str, conversation_id: str, revision: int, view: Any) -> None:
        key = (user_id, conversation_id)
        with self._lock:
            self._rows[key] = (_clock(), revision, view)
            self._rows.move_to_end(key)
            while len(self._rows) > self._max:
                self._rows.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)


CONVERSATION_POLL_CACHE = ConversationPollCache()


def reset_conversation_poll_cache() -> None:
    """Drop cached views (tests only)."""

    CONVERSATION_POLL_CACHE.clear()


__all__ = [
    "CONVERSATION_POLL_CACHE",
    "POLL_AFTER_HEADER",
    "ConversationPollCache",
    "reset_conversation_poll_cache",
    "set_clock",
]
