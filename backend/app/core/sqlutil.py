"""Dialect helpers for the SQLite writer fence and shared upserts.

SQLite ``BEGIN IMMEDIATE`` takes the reserved lock before a read-modify-write.
PostgreSQL has no equivalent statement. A named advisory lock is used only for
the few sections that must stay single-file across replicas (login admission,
registration). Other callers rely on row locks and unique indexes so concurrent
students can commit together.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement


class _DialectSql(ColumnElement[Any]):
    """CHECK expression that compiles to different SQL on SQLite and Postgres.

    SQLite keeps the historical ``GLOB`` form so ``create_all`` matches the
    migration constraints. Postgres has no ``GLOB`` operator, and SQLite has
    no ``translate()``, so the two predicates cannot share one string.
    """

    inherit_cache = True

    def __init__(self, sqlite: str, postgresql: str) -> None:
        self.sqlite = sqlite
        self.postgresql = postgresql


@compiles(_DialectSql)
@compiles(_DialectSql, "sqlite")
def _compile_sqlite_sql(element: _DialectSql, compiler: Any, **kw: Any) -> str:
    return element.sqlite


@compiles(_DialectSql, "postgresql")
def _compile_postgresql_sql(element: _DialectSql, compiler: Any, **kw: Any) -> str:
    return element.postgresql


def portable_sql(sqlite: str, postgresql: str) -> _DialectSql:
    """Return a CHECK clause that is valid on both supported backends."""

    return _DialectSql(sqlite, postgresql)


def foreign_keys_ok(session: Session) -> bool:
    """SQLite needs an explicit check. PostgreSQL rejects violations as they happen."""

    if session.get_bind().dialect.name != "sqlite":
        return True
    return session.execute(text("PRAGMA foreign_key_check")).first() is None


def begin_immediate(session: Session, *, lock_key: str | None = None) -> None:
    """Start the writer fence for this session, or share one named Postgres lock."""

    bind = session.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        return
    if dialect == "postgresql" and lock_key:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )


def dialect_insert(session: Session, table: Any) -> Any:
    """Return the dialect insert that supports ON CONFLICT for this session."""

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgres_insert

        return postgres_insert(table)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert(table)
