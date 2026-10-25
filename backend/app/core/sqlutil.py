"""Writer fences and upserts on PostgreSQL.

A named advisory lock is used only for the few sections that must stay
single-file across replicas (login admission, registration). Other callers
rely on row locks and unique indexes so concurrent students can commit
together. ``begin_immediate`` keeps its historical name (it was SQLite's
``BEGIN IMMEDIATE`` writer fence before PostgreSQL became the only database).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.orm import Session


def begin_immediate(session: Session, *, lock_key: str | None = None) -> None:
    """Share one named transaction lock across replicas when a key is given."""

    if lock_key:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )


def dialect_insert(session: Session, table: Any) -> Any:
    """An INSERT that supports ON CONFLICT."""

    del session
    return postgres_insert(table)
