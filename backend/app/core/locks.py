"""Named locks that hold across processes and machines (PostgreSQL advisory).

Every backend process, on this host or another, shares one database, so a
lock taken here serializes work wherever it runs. Use these instead of
process-local locks or lock files for anything two replicas could race on;
moving to a bigger server, or to several, then needs no lock changes.

* ``xact_lock`` / ``try_xact_lock``: held until the caller's transaction
  commits or rolls back. For check-then-write sections inside one transaction.
* ``held_lock``: held on a connection of its own until the block ends, across
  any number of commits, and released by the server if the process dies. For
  operations that commit in several steps.

Names are hashed with PostgreSQL's ``hashtext``; a collision only makes two
unrelated sections wait for each other, never lets two holders in.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

_XACT_LOCK = text("SELECT pg_advisory_xact_lock(hashtext(:name))")
_TRY_XACT_LOCK = text("SELECT pg_try_advisory_xact_lock(hashtext(:name))")
_LOCK = text("SELECT pg_advisory_lock(hashtext(:name))")
_TRY_LOCK = text("SELECT pg_try_advisory_lock(hashtext(:name))")
_UNLOCK = text("SELECT pg_advisory_unlock(hashtext(:name))")


def xact_lock(db: Session | Connection, name: str) -> None:
    """Wait for ``name``; it is released when this transaction ends."""

    db.execute(_XACT_LOCK, {"name": name})


def try_xact_lock(db: Session | Connection, name: str) -> bool:
    """Take ``name`` for this transaction if free; never waits."""

    return bool(db.execute(_TRY_XACT_LOCK, {"name": name}).scalar())


@contextmanager
def held_lock(bind: Engine | Connection, name: str, *, wait: bool = False) -> Iterator[bool]:
    """Hold ``name`` for the block on a connection of its own.

    Yields whether the lock is held: always True with ``wait``; without it,
    False when another holder has it (the caller then skips its work).
    """

    engine = bind.engine if isinstance(bind, Connection) else bind
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        if wait:
            connection.execute(_LOCK, {"name": name})
            acquired = True
        else:
            acquired = bool(connection.execute(_TRY_LOCK, {"name": name}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(_UNLOCK, {"name": name})
