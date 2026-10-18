from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.db import ALEMBIC_HEAD, SQLITE_BUSY_TIMEOUT_MS, Database
from sqlalchemy import inspect, text


def test_sqlite_pragmas_and_constraints(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'pragma.sqlite3'}")
    db.upgrade_schema()
    with db.engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert str(connection.execute(text("PRAGMA journal_mode")).scalar_one()).lower() == "wal"
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()
        assert 0 < busy_timeout <= SQLITE_BUSY_TIMEOUT_MS
    inspector = inspect(db.engine)
    assert {item["name"] for item in inspector.get_unique_constraints("users")} == {
        "uq_users_username"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("courses")} == {
        "uq_courses_code"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("groups")} == {
        "uq_groups_course_name"
    }
    assert {item["name"] for item in inspector.get_indexes("sessions")} == {
        "ix_sessions_user_id",
        "ix_sessions_expires_at",
    }
    assert inspector.get_pk_constraint("course_members")["constrained_columns"] == [
        "course_id",
        "user_id",
    ]
    assert inspector.get_pk_constraint("group_members")["constrained_columns"] == [
        "group_id",
        "user_id",
    ]
    assert {item["name"] for item in inspector.get_indexes("group_members")} == {
        "ix_group_members_user_id"
    }


def test_alembic_upgrade_is_idempotent_and_readiness_checks_head(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'alembic.sqlite3'}")
    db.upgrade_schema()
    db.upgrade_schema()
    assert db.using_migrations
    assert ALEMBIC_HEAD == "0071_chat_reports"
    assert db.check_ready()
    with db.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )


def test_provider_selectors_are_mock_safe_by_default() -> None:
    settings = Settings(
        maya_env="test",
        llm_provider="",
        embedding_provider="",
        tts_provider="",
        voice_provider="",
        report_provider="",
        dashscope_api_key=None,
    )
    assert settings.llm_provider == "mock"
    assert settings.embedding_provider == "mock"
    assert settings.tts_provider == "mock"
    assert settings.voice_provider == "mock"
