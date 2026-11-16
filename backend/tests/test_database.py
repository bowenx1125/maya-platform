from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.db import ALEMBIC_HEAD, MIGRATION_BASELINE, Database
from sqlalchemy import inspect, text

from tests.postgres_db import named_url


def test_schema_constraints(tmp_path: Path) -> None:
    db = Database(named_url(f"{tmp_path / 'pragma.sqlite3'}"))
    db.upgrade_schema()
    inspector = inspect(db.engine)
    # create_all names a column-level UNIQUE the PostgreSQL way (production's
    # schema was created like this, not by the SQLite migrations).
    assert {item["name"] for item in inspector.get_unique_constraints("users")} == {
        "users_username_key"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("courses")} == {
        "courses_code_key"
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
    db = Database(named_url(f"{tmp_path / 'alembic.sqlite3'}"))
    db.upgrade_schema()
    db.upgrade_schema()
    assert db.using_migrations
    assert ALEMBIC_HEAD == "0094_agent_debate_cards"
    assert db.check_ready()
    with db.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )


def test_database_below_the_squashed_baseline_is_refused(tmp_path: Path) -> None:
    db = Database(named_url(f"{tmp_path / 'old.sqlite3'}"))
    db.upgrade_schema()
    with db.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0079_old'"))
    try:
        db.upgrade_schema()
    except RuntimeError as error:
        assert "older than the squashed migration baseline" in str(error)
        assert MIGRATION_BASELINE in str(error)
    else:
        raise AssertionError("an unknown pre-squash revision must be refused")
    with db.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0079_old"
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


def test_session_time_zone_is_utc_whatever_the_client_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A JST host (PGTZ or the server default) must not shift timestamptz
    # values: code reads them back with .replace(tzinfo=UTC).
    monkeypatch.setenv("PGTZ", "Asia/Tokyo")
    db = Database(named_url(f"{tmp_path / 'tz.sqlite3'}"))
    try:
        with db.engine.connect() as connection:
            assert connection.execute(text("SHOW TIME ZONE")).scalar_one() == "UTC"
            stored = connection.execute(
                text("SELECT TIMESTAMPTZ '2026-10-25 12:00:00+00'")
            ).scalar_one()
        assert stored.utcoffset() == timedelta(0)
    finally:
        db.dispose()


def test_database_at_the_baseline_runs_no_ddl_and_keeps_its_version(tmp_path: Path) -> None:
    # An empty database is created from the models and stamped at head.
    # Starting again must not replay DDL. The squashed baseline stays 0080;
    # later revisions run only when the database is behind head.
    from sqlalchemy import event

    db = Database(named_url(f"{tmp_path / 'baseline.sqlite3'}"))
    db.upgrade_schema()
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        db.upgrade_schema()
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    assert MIGRATION_BASELINE == "0080_drop_playback_rate"
    assert ALEMBIC_HEAD == "0094_agent_debate_cards"
    assert not {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"} & set(statements)
    with db.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )


def test_upgrade_0089_keeps_existing_student_session_and_adds_choice_metadata(
    tmp_path: Path,
) -> None:
    from app.core.models import SessionRecord, User
    from app.modules.auth.service import create_rotated_session
    from app.modules.org.classes import ensure_classes
    from app.seed import BOWEN_ID, seed_demo_data

    db = Database(named_url(f"{tmp_path / 'bowen-upgrade'}"))
    db.upgrade_schema()
    settings = Settings(maya_env="test", session_secret="x" * 32)
    with db.session() as session:
        seed_demo_data(session)
        ensure_classes(session)
        _, row, _ = create_rotated_session(session, session.get(User, BOWEN_ID), settings)
        saved_hash = row.id_hash
        saved_courses = session.execute(
            text("SELECT id, name, code FROM courses ORDER BY id")
        ).all()
    with db.engine.begin() as connection:
        connection.execute(text("DROP TABLE agent_debate_cards"))
        connection.execute(text("ALTER TABLE classroom_quizzes DROP COLUMN show_results"))
        connection.execute(text("DROP TABLE login_identity_challenges"))
        connection.execute(text("ALTER TABLE sessions DROP COLUMN active_course_id"))
        connection.execute(text("ALTER TABLE sessions DROP COLUMN entered_via_user_id"))
        connection.execute(text("UPDATE alembic_version SET version_num = '0089_debate_cards'"))
    db.upgrade_schema()
    assert db.check_ready()
    with db.session() as session:
        row = session.get(SessionRecord, saved_hash)
        assert row.user_id == BOWEN_ID
        assert row.revoked_at is None
        assert row.entered_via_user_id is None
        assert row.active_course_id is None
        assert (
            session.execute(text("SELECT id, name, code FROM courses ORDER BY id")).all()
            == saved_courses
        )
    assert "login_identity_challenges" in inspect(db.engine).get_table_names()
