"""Which backend process is running a chat turn (2026-11-02).

A Chat holds ``active_request_id`` while one of its turns runs; until it is
cleared, every new message is refused with ``chat_busy``. Startup recovery
used to be the only thing that cleared a turn whose process died, and only the
background leader ran it -- so a chat whose replica was restarted while the
leader stayed up stayed busy for good, and a leader restart failed the turns
the other, healthy replica was still running.

Now the process that runs a turn holds a session-level PostgreSQL advisory
lock on it, on one connection of its own. The lock goes away with the process
(its connection closes), so "nobody holds this turn" is exactly "its runner is
gone", with no clocks or heartbeats to tune. ``turn_is_held`` asks inside a
transaction without disturbing a holder.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

LOGGER = logging.getLogger("maya.chat_turns")

# A different class from replica.py's alive lock (77001) and the leader lock.
_CHAT_TURN_CLASS = 77002
# A sweeper's check holds the lock for one tiny transaction; a runner taking
# the turn at that moment waits it out instead of running unmarked.
_HOLD_ATTEMPTS = 5
_HOLD_RETRY_SECONDS = 0.02

_LOCK = text("SELECT pg_try_advisory_lock(:c, hashtext(:k))")
_UNLOCK = text("SELECT pg_advisory_unlock(:c, hashtext(:k))")
_PROBE = text("SELECT pg_try_advisory_xact_lock(:c, hashtext(:k))")


class ChatTurnLocks:
    """The turns this process is running, held as advisory locks."""

    def __init__(self, engine: Engine, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.engine = engine
        self._sleep = sleep
        self._mutex = threading.Lock()
        self._connection: Connection | None = None
        self._counts: dict[str, int] = {}
        self._locked: set[str] = set()

    @property
    def enabled(self) -> bool:
        return bool(self.engine.dialect.name == "postgresql")

    def hold(self, turn_id: str) -> None:
        """Mark ``turn_id`` as running here. Nested holds are counted."""

        if not self.enabled:
            return
        with self._mutex:
            count = self._counts.get(turn_id, 0)
            self._counts[turn_id] = count + 1
            if count:
                return
            for attempt in range(_HOLD_ATTEMPTS):
                if self._try_lock(turn_id):
                    self._locked.add(turn_id)
                    return
                if attempt + 1 < _HOLD_ATTEMPTS:
                    self._sleep(_HOLD_RETRY_SECONDS)
            # Another live process holds it (it is running this turn too, e.g.
            # a replayed request): that holder already marks it as running.
            LOGGER.info("Chat turn already held elsewhere turn_id=%s", turn_id)

    def release(self, turn_id: str) -> None:
        if not self.enabled:
            return
        with self._mutex:
            count = self._counts.get(turn_id, 0)
            if count > 1:
                self._counts[turn_id] = count - 1
                return
            self._counts.pop(turn_id, None)
            if turn_id not in self._locked:
                return
            self._locked.discard(turn_id)
            try:
                connection = self._connect()
                connection.execute(_UNLOCK, {"c": _CHAT_TURN_CLASS, "k": turn_id})
            except Exception:
                LOGGER.warning("Chat turn unlock failed turn_id=%s", turn_id, exc_info=True)
                self._replace_connection()

    @contextmanager
    def holding(self, turn_id: str) -> Iterator[None]:
        self.hold(turn_id)
        try:
            yield
        finally:
            self.release(turn_id)

    def held(self) -> tuple[str, ...]:
        with self._mutex:
            return tuple(self._counts)

    def close(self) -> None:
        with self._mutex:
            connection, self._connection = self._connection, None
            self._counts.clear()
            self._locked.clear()
        if connection is not None:
            _drop(connection)

    def _connect(self) -> Connection:
        if self._connection is None:
            # Autocommit: session-level locks need no transaction, and one
            # left open for a whole turn would sit "idle in transaction".
            self._connection = self.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        return self._connection

    def _try_lock(self, turn_id: str) -> bool:
        try:
            connection = self._connect()
            acquired = connection.execute(_LOCK, {"c": _CHAT_TURN_CLASS, "k": turn_id}).scalar()
            return bool(acquired)
        except Exception:
            LOGGER.warning("Chat turn lock failed turn_id=%s", turn_id, exc_info=True)
            self._replace_connection()
            return False

    def _replace_connection(self) -> None:
        """A broken connection lost every lock it held: take them again."""

        old, self._connection = self._connection, None
        if old is not None:
            _drop(old)
        kept: set[str] = set()
        try:
            connection = self._connect()
            for turn_id in self._locked:
                if connection.execute(_LOCK, {"c": _CHAT_TURN_CLASS, "k": turn_id}).scalar():
                    kept.add(turn_id)
        except Exception:
            LOGGER.warning("Chat turn locks could not be restored", exc_info=True)
            self._connection = None
        self._locked = kept


def _drop(connection: Connection) -> None:
    # Returned to the pool, the server session (and every lock it holds)
    # would live on; invalidating closes it, which releases them.
    try:
        connection.invalidate()
        connection.close()
    except Exception:  # pragma: no cover - closing a dead connection
        pass


def turn_is_held(connection: Connection, turn_id: str) -> bool:
    """True when a live process is running ``turn_id``.

    Call inside a transaction: the probe takes the lock only until that
    transaction ends, so a free turn stays free and a held one is untouched.
    """

    if connection.dialect.name != "postgresql":
        return False
    acquired = connection.execute(_PROBE, {"c": _CHAT_TURN_CLASS, "k": turn_id}).scalar()
    return not acquired


_registry: dict[int, ChatTurnLocks] = {}
_registry_lock = threading.Lock()


def chat_turn_locks(engine: Engine) -> ChatTurnLocks:
    """The one holder for this engine (one per process and database)."""

    with _registry_lock:
        locks = _registry.get(id(engine))
        if locks is None or locks.engine is not engine:
            locks = ChatTurnLocks(engine)
            _registry[id(engine)] = locks
        return locks


@contextmanager
def holding_chat_turn(bind: Any, turn_id: str) -> Iterator[None]:
    """Hold ``turn_id`` for the block; ``bind`` is an Engine or a sessionmaker."""

    engine = bind if isinstance(bind, Engine) else getattr(bind, "kw", {}).get("bind")
    if not isinstance(engine, Engine):
        yield
        return
    with chat_turn_locks(engine).holding(turn_id):
        yield


def forget_chat_turn_locks(engine: Engine) -> None:
    with _registry_lock:
        locks = _registry.pop(id(engine), None)
    if locks is not None:
        locks.close()
