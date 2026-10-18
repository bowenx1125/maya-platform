"""Synchronous SQLAlchemy database boundary.

SQLite remains the local and test database. PostgreSQL is the production
database: concurrent writers, and one schema shared by every backend replica.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.logging import configure_application_logging
from app.core.models import Base
from app.core.postgres_compat import ensure_postgres_compat

SQLITE_BUSY_TIMEOUT_MS = 5_000
# Per backend: 15 + 25 = 40, so two replicas hold at most 80 of PostgreSQL's
# 200 connections; 48 admitted requests rarely hold a connection at once.
POSTGRES_POOL_SIZE = 15
POSTGRES_MAX_OVERFLOW = 25

ALEMBIC_HEAD = "0068_attempt_activity_index"
_STARTUP_LOCK = "maya-startup"
_LEADER_LOCK = "maya-background-leader"


def _sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
    """Apply required pragmas to every SQLite DB-API connection."""

    # sqlite3.Connection exposes execute; typing it as object keeps this small
    # adapter independent of a particular DB-API implementation.
    connection = dbapi_connection
    execute = connection.execute  # type: ignore[attr-defined]
    execute("PRAGMA foreign_keys=ON")
    execute("PRAGMA journal_mode=WAL")
    execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")


def build_engine(database_url: str) -> Engine:
    """Build an engine. SQLite keeps its pragmas; PostgreSQL uses a checked pool."""

    backend = make_url(database_url).get_backend_name()
    if backend == "sqlite":
        connect_args: dict[str, object] = {"check_same_thread": False}
        kwargs: dict[str, object] = {
            "future": True,
            "connect_args": connect_args,
        }
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **kwargs)
        event.listen(engine, "connect", _sqlite_pragmas)
        return engine
    if backend == "postgresql":
        engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            pool_size=POSTGRES_POOL_SIZE,
            max_overflow=POSTGRES_MAX_OVERFLOW,
            pool_timeout=30,
        )
        ensure_postgres_compat(engine)
        _time_writes(engine)
        _time_pool_checkout(engine)
        return engine
    raise RuntimeError("Unsupported database backend.")


def _time_writes(engine: Engine) -> None:
    """Feed non-SELECT statement latency to adaptive admission's DB signal."""

    from app.core.adaptive_admission import record_db_write_ms
    from app.core.message_timing import add_db_write

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        conn.info.setdefault("_adaptive_t0", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _end(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        stack = conn.info.get("_adaptive_t0")
        if not stack:
            return
        started = stack.pop()
        if not statement.lstrip()[:6].upper().startswith("SELECT"):
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            record_db_write_ms(elapsed_ms)
            add_db_write(elapsed_ms)


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

        Deployment upgrades are performed through Alembic (see migrations/),
        while create_all keeps isolated unit-test SQLite databases useful and
        does not create any later-wave tables.
        """

        # Register Wave 2/3 vertical-domain tables before isolated tests call
        # create_all. Deployment still uses Alembic as the source of truth.
        from app.modules.auth import admission as _admission_models
        from app.modules.debates import models as _debate_models
        from app.modules.interactions import models as _interaction_models
        from app.modules.knowledge_sets import models as _knowledge_set_models
        from app.modules.learning import models as _learning_models
        from app.modules.reports import models as _report_models
        from app.modules.runtime_tools import models as _runtime_tool_models
        from app.modules.teams import models as _team_models
        from app.modules.workspace import models as _workspace_models

        del (
            _admission_models,
            _debate_models,
            _interaction_models,
            _knowledge_set_models,
            _learning_models,
            _report_models,
            _runtime_tool_models,
            _team_models,
            _workspace_models,
        )
        if self.engine.url.get_backend_name() == "postgresql":
            ensure_postgres_compat(self.engine)
        if self.engine.url.get_backend_name() == "sqlite":
            database = self.engine.url.database
            if database and database != ":memory:":
                Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # This path is intentionally limited to isolated test databases.  A
        # deployed process always uses ``upgrade_schema`` so Alembic remains
        # the source of truth for the Wave 1A head.
        Base.metadata.create_all(self.engine)

    def _alembic_config(self) -> object:
        from alembic.config import Config

        migration_dir = Path(__file__).resolve().parents[2]
        config = Config(str(migration_dir / "alembic.ini"))
        config.set_main_option("script_location", str(migration_dir / "migrations"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.attributes["database_url"] = self.database_url
        return config

    def _alembic_version(self) -> str | None:
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "postgresql":
                exists = connection.execute(
                    text("SELECT to_regclass('public.alembic_version')")
                ).scalar_one_or_none()
                if exists is None:
                    return None
            else:
                row = connection.execute(
                    text(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                        "AND name = 'alembic_version'"
                    )
                ).first()
                if row is None:
                    return None
            return connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()

    @contextmanager
    def startup_lock(self) -> Iterator[None]:
        """Serialize schema upgrade and the first import across replicas.

        SQLite has one process, so the lock is a no-op. The PostgreSQL lock is
        held on its own connection and released before background leadership is
        claimed, so the two locks cannot deadlock.
        """

        if self.engine.dialect.name != "postgresql":
            yield
            return
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

        if self.engine.dialect.name != "postgresql":
            return True
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

        PostgreSQL does not replay the SQLite-shaped migration history. An
        empty database is created from the current models and stamped at head.
        Later revisions run through Alembic and must stay dialect-neutral.
        """

        from alembic import command

        if self.engine.dialect.name == "postgresql":
            ensure_postgres_compat(self.engine)
            version = self._alembic_version()
            config = self._alembic_config()
            if version is None:
                self.initialize_schema()
                command.stamp(config, "head")  # type: ignore[arg-type]
            elif version != ALEMBIC_HEAD:
                command.upgrade(config, "head")  # type: ignore[arg-type]
        else:
            command.upgrade(self._alembic_config(), "head")  # type: ignore[arg-type]
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
                if self.engine.url.get_backend_name() == "sqlite":
                    foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
                    journal_mode = str(
                        connection.execute(text("PRAGMA journal_mode")).scalar_one()
                    ).lower()
                    busy_timeout = int(connection.execute(text("PRAGMA busy_timeout")).scalar_one())
                    pragma_ready = (
                        foreign_keys == 1 and journal_mode == "wal" and 0 < busy_timeout <= 60_000
                    )
                    if not pragma_ready:
                        return False
                if self.using_migrations or self.engine.url.get_backend_name() == "postgresql":
                    version = connection.execute(
                        text("SELECT version_num FROM alembic_version LIMIT 1")
                    ).scalar_one_or_none()
                    return version == ALEMBIC_HEAD
                return True
        except Exception:
            return False

    def dispose(self) -> None:
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
