"""#111: a production process on SQLite says so at startup."""

from __future__ import annotations

from app.core.config import Settings


def _settings(**values: object) -> Settings:
    return Settings(**values)  # type: ignore[arg-type]


def test_production_on_sqlite_is_flagged() -> None:
    warning = _settings(
        MAYA_ENV="production", DATABASE_URL="sqlite:////app/data/maya.sqlite3"
    ).single_writer_production_warning()
    assert warning is not None and "PostgreSQL" in warning


def test_production_on_postgres_and_local_sqlite_are_not_flagged() -> None:
    assert (
        _settings(
            MAYA_ENV="production", DATABASE_URL="postgresql+psycopg://maya:x@postgres:5432/maya"
        ).single_writer_production_warning()
        is None
    )
    assert (
        _settings(DATABASE_URL="sqlite:///data/maya.sqlite3").single_writer_production_warning()
        is None
    )
