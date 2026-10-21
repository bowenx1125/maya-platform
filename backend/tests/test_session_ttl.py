"""Session lifetime follows SESSION_TTL_DAYS (default 30 days)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import SessionRecord, User
from app.modules.auth.service import create_rotated_session, get_auth_context
from sqlalchemy import select

T0 = datetime(2026, 10, 21, 8, 0, 0, tzinfo=UTC)


def _settings(database: Database, **overrides: object) -> Settings:
    return Settings(
        maya_env="test",
        session_secret="x" * 32,
        database_url=f"sqlite:///{Path(database.data_root or Path('.')) / 'ttl.sqlite3'}",
        **overrides,  # type: ignore[arg-type]
    )


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'ttl.sqlite3'}", tmp_path)
    database.initialize_schema()
    return database


@pytest.fixture
def user(database: Database) -> User:
    with database.session() as session:
        row = User(
            id="ttl-user",
            username="ttl-user",
            display_name="TTL User",
            status="active",
            created_at=T0,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    return row


def _seed_session(database: Database, user: User, settings: Settings) -> str:
    with database.session() as session:
        raw_token, _row, _csrf = create_rotated_session(session, user, settings, now=T0)
    return raw_token


def test_default_session_survives_29_days_and_dies_by_31(database: Database, user: User) -> None:
    settings = _settings(database)
    raw_token = _seed_session(database, user, settings)

    with database.session() as session:
        row = session.scalar(select(SessionRecord))
        assert row is not None
        # SQLite stores naive UTC; compare in UTC.
        assert row.expires_at.replace(tzinfo=UTC) == T0 + timedelta(days=30)
        still_valid = get_auth_context(session, settings, raw_token, now=T0 + timedelta(days=29))
        assert still_valid is not None

    with database.session() as session:
        expired = get_auth_context(session, settings, raw_token, now=T0 + timedelta(days=31))
    assert expired is None


def test_session_ttl_days_override_shortens_expiry(database: Database, user: User) -> None:
    settings = _settings(database, session_ttl_days=7)
    raw_token = _seed_session(database, user, settings)

    with database.session() as session:
        row = session.scalar(select(SessionRecord))
        assert row is not None
        assert row.expires_at.replace(tzinfo=UTC) == T0 + timedelta(days=7)
        within = get_auth_context(session, settings, raw_token, now=T0 + timedelta(days=6))
        assert within is not None

    with database.session() as session:
        after = get_auth_context(session, settings, raw_token, now=T0 + timedelta(days=8))
    assert after is None
