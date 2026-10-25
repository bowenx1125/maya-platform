"""One playback writer per Debate, across threads and backend replicas (PR C).

The old lock was an ``asyncio.Lock`` per Debate: it only held inside one event
loop of one process. Production runs two backend replicas, and playback work
now also runs on worker threads (see ``offload``), so the lock has two layers:

- a ``threading.Lock`` per Debate inside the process (at most one waiter per
  Debate holds a database connection, and memory repositories still work);
- a PostgreSQL session advisory lock on a dedicated connection, shared by
  every replica. The connection is outside the request pool, and the server
  drops the lock if the process dies.

Waiting happens on a dedicated thread pool, never on an event loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

LOCK_PREFIX = "debate-playback:"
_WAITERS = ThreadPoolExecutor(max_workers=64, thread_name_prefix="maya-debate-lock")

Release = Callable[[], None]


class _Entry:
    __slots__ = ("lock", "users")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.users = 0


class DebateLocks:
    def __init__(self, engine: Engine | None = None) -> None:
        self._entries: dict[str, _Entry] = {}
        self._guard = threading.Lock()
        postgres = engine is not None and engine.dialect.name == "postgresql"
        self._source = engine if postgres else None
        self._engine: Engine | None = None

    @classmethod
    def for_session_factory(cls, session_factory: Any) -> DebateLocks:
        bind = getattr(session_factory, "kw", {}).get("bind") if session_factory else None
        return cls(bind if isinstance(bind, Engine) else None)

    @property
    def shared(self) -> bool:
        """Whether the lock also holds across replicas (PostgreSQL)."""

        return self._source is not None

    def _lock_engine(self) -> Engine | None:
        if self._source is None:
            return None
        with self._guard:
            if self._engine is None:
                self._engine = create_engine(self._source.url, poolclass=NullPool, future=True)
            return self._engine

    def acquire_blocking(self, debate_id: str) -> Release:
        with self._guard:
            entry = self._entries.setdefault(debate_id, _Entry())
            entry.users += 1
        entry.lock.acquire()
        connection: Connection | None = None
        try:
            engine = self._lock_engine()
            if engine is not None:
                connection = engine.connect()
                connection.execute(
                    text("SELECT pg_advisory_lock(hashtext(:key))"),
                    {"key": LOCK_PREFIX + debate_id},
                )
                connection.commit()
        except BaseException:
            if connection is not None:
                connection.close()
            self._leave(debate_id, entry)
            raise

        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            try:
                if connection is not None:
                    try:
                        connection.execute(
                            text("SELECT pg_advisory_unlock(hashtext(:key))"),
                            {"key": LOCK_PREFIX + debate_id},
                        )
                        connection.commit()
                    finally:
                        # Closing the session also drops the lock if the
                        # unlock statement itself failed.
                        connection.close()
            finally:
                self._leave(debate_id, entry)

        return release

    def _leave(self, debate_id: str, entry: _Entry) -> None:
        entry.lock.release()
        with self._guard:
            entry.users -= 1
            if entry.users == 0 and self._entries.get(debate_id) is entry:
                self._entries.pop(debate_id, None)

    async def acquire(self, debate_id: str) -> Release:
        """Wait off the event loop; a cancelled wait still releases its lock."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_WAITERS, self.acquire_blocking, debate_id)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:

            def release_late(done: asyncio.Future[Release]) -> None:
                if not done.cancelled() and done.exception() is None:
                    _WAITERS.submit(done.result())

            future.add_done_callback(release_late)
            raise

    async def release(self, release: Release) -> None:
        """Release off the event loop (the unlock is a database round trip)."""

        loop = asyncio.get_running_loop()
        await asyncio.shield(loop.run_in_executor(_WAITERS, release))

    def dispose(self) -> None:
        with self._guard:
            engine, self._engine = self._engine, None
        if engine is not None:
            engine.dispose()
