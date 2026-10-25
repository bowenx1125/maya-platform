"""Which backend replica owns in-flight Debate and report work (2026-10-19).

Production runs two backends. Startup recovery used to fail every running
Debate turn and report job, and revoke every playback controller, whenever the
background leader restarted -- including work the *other*, healthy backend was
doing at that moment. Now:

* every process holds a shared Postgres advisory lock while it lives, so a
  restarting leader can tell whether a peer is serving;
* a process touches ``jobs.updated_at`` every ``TOUCH_SECONDS`` for the turn
  and report jobs it holds (by claim token);
* with a live peer, startup recovery leaves in-flight work alone and only
  reclaims the jobs that were running at startup and were never touched again
  within ``ORPHAN_GRACE_SECONDS`` (their owner died). Without a peer the old
  full recovery runs unchanged.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import bindparam, text

LOGGER = logging.getLogger("maya.replica")

_ALIVE_CLASS = 77001
_ALIVE_OBJ = 0
TOUCH_SECONDS = 15.0
ORPHAN_GRACE_SECONDS = 120.0

_held_tokens: set[str] = set()
_held_lock = threading.Lock()


def hold_claim(token: str | None) -> None:
    """Keep ``jobs.updated_at`` fresh for the running job with this claim token."""

    if token:
        with _held_lock:
            _held_tokens.add(str(token))


def release_claim(token: str | None) -> None:
    if token:
        with _held_lock:
            _held_tokens.discard(str(token))


def held_claims() -> tuple[str, ...]:
    with _held_lock:
        return tuple(_held_tokens)


def touch_held_jobs(session_factory: Callable[[], Any]) -> int:
    """One touch pass; drops tokens whose job is no longer running."""

    tokens = held_claims()
    if not tokens:
        return 0
    with session_factory() as db:
        db.execute(
            text(
                "UPDATE jobs SET updated_at=:now WHERE state='running' AND claim_token IN :tokens"
            ).bindparams(bindparam("tokens", expanding=True)),
            {"now": datetime.now(UTC), "tokens": tokens},
        )
        running = {
            str(row[0])
            for row in db.execute(
                text(
                    "SELECT claim_token FROM jobs WHERE state='running' AND claim_token IN :tokens"
                ).bindparams(bindparam("tokens", expanding=True)),
                {"tokens": tokens},
            ).all()
        }
        db.commit()
    with _held_lock:
        for token in tokens:
            if token not in running:
                _held_tokens.discard(token)
    return len(running)


class ReplicaPresence:
    """Holds the shared "a backend is alive" lock and runs the touch loop."""

    def __init__(self, engine: Any, session_factory: Callable[[], Any]) -> None:
        self.engine = engine
        self.session_factory = session_factory
        self.pid: int | None = None
        self._connection: Any | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def postgres(self) -> bool:
        return bool(self.engine.dialect.name == "postgresql")

    def start(self) -> None:
        if self.postgres and self._connection is None:
            connection = self.engine.connect()
            connection.execute(
                text("SELECT pg_advisory_lock_shared(:a, :b)"),
                {"a": _ALIVE_CLASS, "b": _ALIVE_OBJ},
            )
            self.pid = int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            connection.commit()
            self._connection = connection
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="maya-job-touch", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(TOUCH_SECONDS):
            try:
                touch_held_jobs(self.session_factory)
            except Exception:  # pragma: no cover - logged, next pass retries
                LOGGER.warning("job touch pass failed", exc_info=True)

    def peers_alive(self) -> bool:
        """Another backend process holds the alive lock right now."""

        if not self.postgres:
            return False
        with self.engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                    "AND classid=:a AND objid=:b AND objsubid=2 AND granted "
                    "AND pid <> :me "
                    # Advisory locks belong to one database; another database
                    # on the same server is not a peer.
                    "AND database = (SELECT oid FROM pg_database "
                    "WHERE datname = current_database())"
                ),
                {"a": _ALIVE_CLASS, "b": _ALIVE_OBJ, "me": int(self.pid or 0)},
            ).scalar_one()
        return int(count or 0) > 0

    def close(self) -> None:
        self._stop.set()
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:  # pragma: no cover
                pass


DEBATE_JOB_SQL = "SELECT id, updated_at FROM jobs WHERE state='running' AND debate_id IS NOT NULL"


def running_debate_jobs(db: Any) -> dict[str, Any]:
    """Running Debate-scoped jobs (turns, insights, reports) and their touch time."""

    return {str(row[0]): row[1] for row in db.execute(text(DEBATE_JOB_SQL)).all()}


def untouched(db: Any, snapshot: dict[str, Any], ids: Iterable[str] | None = None) -> set[str]:
    """Jobs from ``snapshot`` still running and never touched since."""

    current = running_debate_jobs(db)
    keys = set(snapshot) if ids is None else set(ids) & set(snapshot)
    return {key for key in keys if key in current and current[key] == snapshot[key]}


__all__ = [
    "ORPHAN_GRACE_SECONDS",
    "ReplicaPresence",
    "TOUCH_SECONDS",
    "hold_claim",
    "release_claim",
    "running_debate_jobs",
    "touch_held_jobs",
    "untouched",
]
