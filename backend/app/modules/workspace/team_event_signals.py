"""Wake a waiting Team stream when its turn commits a new event (2026-11-02).

A Team stream used to find new events only by polling the database, backing
off to every 0.5 s while a member was thinking; across a class that polling
was the largest steady database load and kept host load near the admission
trip line. The turn runs in the same process as the stream that started it,
so the commit that adds an event now wakes that stream directly. Polling
stays as the fallback (an event written by another process, a lost wake-up)
but backs off much further.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

_INFO_KEY = "maya_team_event_turns"
_lock = threading.Lock()
_watchers: dict[str, set[TeamEventWatch]] = {}


class TeamEventWatch:
    """One stream's wake-up for one turn; use as a context manager."""

    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()

    def __enter__(self) -> TeamEventWatch:
        with _lock:
            _watchers.setdefault(self.turn_id, set()).add(self)
        return self

    def __exit__(self, *_exc: object) -> None:
        with _lock:
            watchers = _watchers.get(self.turn_id)
            if watchers is not None:
                watchers.discard(self)
                if not watchers:
                    del _watchers[self.turn_id]

    def clear(self) -> None:
        """Call before reading, so a commit during the read still wakes."""

        self._event.clear()

    async def wait(self) -> None:
        await self._event.wait()

    def _wake(self) -> None:
        try:
            self._loop.call_soon_threadsafe(self._event.set)
        except RuntimeError:  # the stream's loop is gone; nothing to wake
            pass


def note_team_event(db: Session, turn_id: str) -> None:
    """Wake the turn's streams once ``db`` commits (never before)."""

    db.info.setdefault(_INFO_KEY, set()).add(turn_id)


def wake_team_streams(turn_ids: set[str]) -> None:
    with _lock:
        watchers = [watch for turn_id in turn_ids for watch in _watchers.get(turn_id, ())]
    for watch in watchers:
        watch._wake()


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    turn_ids: Any = session.info.pop(_INFO_KEY, None)
    if turn_ids:
        wake_team_streams(set(turn_ids))


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop(_INFO_KEY, None)
