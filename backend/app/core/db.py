"""Synchronous SQLAlchemy/SQLite database boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.logging import configure_application_logging
from app.core.models import Base

SQLITE_BUSY_TIMEOUT_MS = 5_000

ALEMBIC_HEAD = "0055_assessment_attempt_submission"


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
    """Build an engine with SQLite safety settings and test-friendly pooling."""

    connect_args: dict[str, object] = {"check_same_thread": False}
    kwargs: dict[str, object] = {
        "future": True,
        "connect_args": connect_args,
    }
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    if engine.url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


class Database:
    """Application database and session factory."""

    def __init__(self, database_url: str, data_root: Path | None = None) -> None:
        self.database_url = database_url
        self.data_root = data_root
        self.using_migrations = False
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
        from app.modules.debates import models as _debate_models
        from app.modules.interactions import models as _interaction_models
        from app.modules.knowledge_sets import models as _knowledge_set_models
        from app.modules.learning import models as _learning_models
        from app.modules.reports import models as _report_models
        from app.modules.runtime_tools import models as _runtime_tool_models
        from app.modules.teams import models as _team_models
        from app.modules.workspace import models as _workspace_models

        del (
            _debate_models,
            _interaction_models,
            _knowledge_set_models,
            _learning_models,
            _report_models,
            _runtime_tool_models,
            _team_models,
            _workspace_models,
        )
        if self.engine.url.get_backend_name() == "sqlite":
            database = self.engine.url.database
            if database and database != ":memory:":
                Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # This path is intentionally limited to isolated test databases.  A
        # deployed process always uses ``upgrade_schema`` so Alembic remains
        # the source of truth for the Wave 1A head.
        Base.metadata.create_all(self.engine)

    def upgrade_schema(self) -> None:
        """Upgrade an application database through the checked-in Alembic head."""

        from alembic import command
        from alembic.config import Config

        migration_dir = Path(__file__).resolve().parents[2]
        config = Config(str(migration_dir / "alembic.ini"))
        config.set_main_option("script_location", str(migration_dir / "migrations"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.attributes["database_url"] = self.database_url
        command.upgrade(config, "head")
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
                    if self.using_migrations:
                        version = connection.execute(
                            text("SELECT version_num FROM alembic_version LIMIT 1")
                        ).scalar_one_or_none()
                        return version == ALEMBIC_HEAD
                    return True
                return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()
