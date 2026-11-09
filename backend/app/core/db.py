"""Synchronous SQLAlchemy database boundary.

PostgreSQL is the only database: production, local development and tests.
SQLite support was removed (PR B, 2026-10-24) and its one-off copy script
retired once production had moved (2026-11-03; it is in git history).

Pool capacity (per process)
---------------------------
``POSTGRES_POOL_SIZE`` + ``POSTGRES_MAX_OVERFLOW`` is the max checked-out
connections **per uvicorn/gunicorn worker process**. Total app DB connections
≈ ``workers × (pool_size + max_overflow)``. Keep that under Postgres
``max_connections`` with headroom for admin/migrations/replicas.

Defaults (15 + 25 = 40) suit two small replicas under a 200-connection
server. For concurrency ladders (e.g. L2=1500 simultaneous submits), raise
the env vars so ``workers × (size + overflow)`` covers the concurrency
without silently lowering client count. Example: 8 workers × (100 + 100) =
1600 slots needs ``max_connections`` ≥ ~1700. Also size write/admission
gates (``WRITE_GUARD_LIMIT``, adaptive admission) for the same load test;
do not disable production safety by default.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import configure_application_logging
from app.core.models import Base
from app.core.postgres_compat import ensure_postgres_compat

# Module-level defaults. Tests may monkeypatch these before Database().
# build_engine prefers env when set (POSTGRES_POOL_SIZE / POSTGRES_MAX_OVERFLOW
# / POSTGRES_POOL_TIMEOUT), otherwise these constants.
POSTGRES_POOL_SIZE = 15
POSTGRES_MAX_OVERFLOW = 25
POSTGRES_POOL_TIMEOUT = 30.0


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(raw)


def resolve_pool_config(
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_timeout: float | None = None,
) -> tuple[int, int, float]:
    """Resolve pool kwargs: explicit args > env > module defaults.

    Capacity formula: per_process = pool_size + max_overflow;
    total ≈ uvicorn_workers × per_process (must stay under max_connections).
    """

    size = (
        pool_size
        if pool_size is not None
        else _env_int("POSTGRES_POOL_SIZE", POSTGRES_POOL_SIZE)
    )
    overflow = (
        max_overflow
        if max_overflow is not None
        else _env_int("POSTGRES_MAX_OVERFLOW", POSTGRES_MAX_OVERFLOW)
    )
    timeout = (
        pool_timeout
        if pool_timeout is not None
        else _env_float("POSTGRES_POOL_TIMEOUT", POSTGRES_POOL_TIMEOUT)
    )
    if size < 1:
        raise ValueError("POSTGRES_POOL_SIZE must be >= 1")
    if overflow < 0:
        raise ValueError("POSTGRES_MAX_OVERFLOW must be >= 0")
    if timeout <= 0:
        raise ValueError("POSTGRES_POOL_TIMEOUT must be > 0")
    return size, overflow, timeout

ALEMBIC_HEAD = "0085_quiz_manual_grading"
# The oldest revision this checkout has (migrations squashed 2026-10-25).
MIGRATION_BASELINE = "0080_drop_playback_rate"


def _known_revision(config: Any, revision: str) -> bool:
    from alembic.script import ScriptDirectory

    try:
        return ScriptDirectory.from_config(config).get_revision(revision) is not None
    except Exception:
        return False


_STARTUP_LOCK = "maya-startup"
_LEADER_LOCK = "maya-background-leader"


def build_engine(database_url: str) -> Engine:
    """Build a PostgreSQL engine with a checked pool."""

    backend = make_url(database_url).get_backend_name()
    if backend == "sqlite":
        raise RuntimeError("SQLite is no longer supported. Set DATABASE_URL to PostgreSQL.")
    if backend == "postgresql":
        pool_size, max_overflow, pool_timeout = resolve_pool_config()
        engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )
        # No connection here: building an app (or a script's Database) must
        # not need the server. The JSON helpers are installed with the schema.
        _session_time_zone_utc(engine)
        _time_writes(engine)
        _time_pool_checkout(engine)
        return engine
    raise RuntimeError("Unsupported database backend.")


def _session_time_zone_utc(engine: Engine) -> None:
    """Read timestamptz values back in UTC whatever the server or PGTZ says.

    Code compares stored times with ``value.replace(tzinfo=UTC)``; under a
    non-UTC session time zone (a JST host, PGTZ) that shifts every lease and
    expiry by the offset, so an expired Live lease stayed live for hours.
    """

    @event.listens_for(engine, "connect")
    def _utc(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")
        dbapi_connection.commit()


def _time_writes(engine: Engine) -> None:
    """Feed non-SELECT statement latency to adaptive admission's DB signal."""

    from app.core.adaptive_admission import (
        db_write_finished,
        db_write_started,
        record_db_write_ms,
    )
    from app.core.message_timing import add_db_write

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        is_write = not statement.lstrip()[:6].upper().startswith("SELECT")
        if is_write:
            db_write_started()
        conn.info.setdefault("_adaptive_t0", []).append((time.perf_counter(), is_write))

    @event.listens_for(engine, "after_cursor_execute")
    def _end(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        stack = conn.info.get("_adaptive_t0")
        if not stack:
            return
        started, is_write = stack.pop()
        if is_write:
            db_write_finished()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            record_db_write_ms(elapsed_ms)
            add_db_write(elapsed_ms)

    @event.listens_for(engine, "handle_error")
    def _failed(context):  # type: ignore[no-untyped-def]
        # A failed statement never reaches after_cursor_execute.
        connection = context.connection
        stack = connection.info.get("_adaptive_t0") if connection is not None else None
        if stack:
            _started, is_write = stack.pop()
            if is_write:
                db_write_finished()


def _time_pool_checkout(engine: Engine) -> None:
    """Feed how long callers wait for a pooled connection to admission.

    SQLAlchemy has no "before checkout" event, so the pool's own connect is
    wrapped. A pool that is out of connections shows up here long before
    statement latency moves.
    """

    from app.core.adaptive_admission import record_pool_wait_ms

    pool = engine.pool
    checkout = pool.connect

    def timed_connect():  # type: ignore[no-untyped-def]
        started = time.perf_counter()
        connection = checkout()
        record_pool_wait_ms((time.perf_counter() - started) * 1000.0)
        return connection

    pool.connect = timed_connect  # type: ignore[method-assign]


def registered_metadata() -> MetaData:
    """The model metadata with every vertical-domain table registered.

    Isolated tests call create_all through this; deployment still uses
    Alembic as the source of truth.
    """

    from app.modules.auth import admission as _admission_models
    from app.modules.cardroom import models as _cardroom_models
    from app.modules.debates import models as _debate_models
    from app.modules.interactions import models as _interaction_models
    from app.modules.knowledge_sets import models as _knowledge_set_models
    from app.modules.learning import models as _learning_models
    from app.modules.quiz import models as _quiz_models
    from app.modules.reports import models as _report_models
    from app.modules.runtime_tools import models as _runtime_tool_models
    from app.modules.teams import models as _team_models
    from app.modules.workspace import models as _workspace_models

    del (
        _admission_models,
        _cardroom_models,
        _quiz_models,
        _debate_models,
        _interaction_models,
        _knowledge_set_models,
        _learning_models,
        _report_models,
        _runtime_tool_models,
        _team_models,
        _workspace_models,
    )
    return Base.metadata


class Database:
    """Application database and session factory."""

    def __init__(self, database_url: str, data_root: Path | None = None) -> None:
        self.database_url = database_url
        self.data_root = data_root
        self.using_migrations = False
        self._leader_connection: Connection | None = None
        self.engine = build_engine(database_url)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    def initialize_schema(self) -> None:
        """Create the current baseline for an application process.

        Deployment upgrades are performed through Alembic (see migrations/);
        create_all builds isolated test databases and an empty database's
        first schema.
        """

        registered_metadata()
        ensure_postgres_compat(self.engine)
        # This path is intentionally limited to isolated test databases.  A
        # deployed process always uses ``upgrade_schema`` so Alembic remains
        # the source of truth for the Wave 1A head.
        Base.metadata.create_all(self.engine)

    def _alembic_config(self) -> object:
        from alembic.config import Config

        migration_dir = Path(__file__).resolve().parents[2]
        config = Config(str(migration_dir / "alembic.ini"))
        config.set_main_option("script_location", str(migration_dir / "migrations"))
        # ConfigParser interpolates "%": a percent-encoded socket path or
        # password would otherwise fail here.
        config.set_main_option("sqlalchemy.url", self.database_url.replace("%", "%%"))
        config.attributes["database_url"] = self.database_url
        return config

    def _alembic_version(self) -> str | None:
        with self.engine.connect() as connection:
            exists = connection.execute(
                text("SELECT to_regclass('public.alembic_version')")
            ).scalar_one_or_none()
            if exists is None:
                return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()

    @contextmanager
    def startup_lock(self) -> Iterator[None]:
        """Serialize schema upgrade and the first import across replicas.

        The lock is held on its own connection and released before background
        leadership is claimed, so the two locks cannot deadlock.
        """

        connection = self.engine.connect()
        connection.execute(
            text("SELECT pg_advisory_lock(hashtext(:key))"),
            {"key": _STARTUP_LOCK},
        )
        connection.commit()
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"),
                {"key": _STARTUP_LOCK},
            )
            connection.commit()
            connection.close()

    def try_background_leader(self) -> bool:
        """True when this process should run startup recovery and schedulers.

        The lock is held until dispose. Another replica serves HTTP and leaves
        the stranded-work recovery to the holder, so a provider call is not
        resumed twice.
        """

        connection = self.engine.connect()
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"),
            {"key": _LEADER_LOCK},
        ).scalar_one()
        connection.commit()
        if not acquired:
            connection.close()
            return False
        self._leader_connection = connection
        return True

    def upgrade_schema(self) -> None:
        """Upgrade an application database through the checked-in Alembic head.

        The old SQLite-shaped migration history is not replayed. An empty
        database is created from the current models and stamped at head.
        Later revisions run through Alembic.
        """

        from alembic import command

        ensure_postgres_compat(self.engine)
        version = self._alembic_version()
        config = self._alembic_config()
        if version is None:
            self.initialize_schema()
            command.stamp(config, "head")  # type: ignore[arg-type]
        elif version != ALEMBIC_HEAD:
            if not _known_revision(config, version):
                # Revisions before the 2026-10-25 squash are gone from this
                # checkout; refuse clearly instead of Alembic's lookup error.
                raise RuntimeError(
                    f"Database is at {version}, older than the squashed migration "
                    f"baseline {MIGRATION_BASELINE}. Deploy the last release before "
                    "the squash, let it upgrade, then deploy this one."
                )
            command.upgrade(config, "head")  # type: ignore[arg-type]
        # Alembic's fileConfig rewrites the root logger from alembic.ini,
        # which drops the application's stdout handler and forces the root
        # level back to WARN. Re-assert the application configuration so
        # later application logs still leave the container.
        configure_application_logging()
        self.using_migrations = True

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def check_ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                if not self.using_migrations:
                    # An isolated test schema from create_all has no Alembic row.
                    exists = connection.execute(
                        text("SELECT to_regclass('public.alembic_version')")
                    ).scalar_one_or_none()
                    if exists is None:
                        return True
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                ).scalar_one_or_none()
                return version == ALEMBIC_HEAD
        except Exception:
            return False

    def dispose(self) -> None:
        from app.core.chat_turn_locks import forget_chat_turn_locks

        forget_chat_turn_locks(self.engine)
        leader = self._leader_connection
        self._leader_connection = None
        if leader is not None:
            try:
                leader.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:key))"),
                    {"key": _LEADER_LOCK},
                )
                leader.commit()
            except Exception:
                pass
            leader.close()
        self.engine.dispose()
