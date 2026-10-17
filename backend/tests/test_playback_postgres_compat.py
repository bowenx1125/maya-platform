"""Debate playback / cleanup SQL must also run on PostgreSQL (production).

#103 moved the playback claims to ``id`` and added Postgres branches for the
predecessor checks.  These tests cover what was still SQLite-only on top of
that: untyped ``:param IS NULL`` binds (psycopg AmbiguousParameter), the
text-fallback claim's ``json_each``, the jsonb predecessor comparison, the
cleanup ``WHERE 0`` / ``WHERE 1`` predicates and the qmark course_id default.

The static checks run everywhere.  Set ``MAYA_TEST_POSTGRES_URL`` (a scratch
database; its ``public`` schema is dropped) to also execute them there.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import event, select, text

_APP = Path(__file__).resolve().parents[1] / "app"
_REPOSITORY = _APP / "modules/debates/playback/sql_repository.py"
_CLEANUP = _APP / "modules/debates/cleanup.py"
_MODELS = _APP / "core/models.py"


def test_playback_sql_has_no_untyped_null_binds():
    source = _REPOSITORY.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    # psycopg cannot type a bare ``$n IS NULL`` parameter.
    assert not re.search(r"[^(]:\w+ IS (NOT )?NULL", code)


def test_cleanup_uses_boolean_literals_not_integer_text():
    source = _CLEANUP.read_text(encoding="utf-8")
    # PostgreSQL rejects ``WHERE 0`` (argument of WHERE must be type boolean).
    assert 'text("0")' not in source
    assert 'text("1")' not in source


def test_course_id_default_does_not_use_qmark_driver_sql():
    source = _MODELS.read_text(encoding="utf-8")
    # psycopg uses %s/$n placeholders; ``?`` only works on sqlite3.
    assert "WHERE id = ?" not in source


_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")


@pytest.fixture
def postgres_database(tmp_path):
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    from app.core.db import Database

    database = Database(_POSTGRES_URL, tmp_path)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    database.initialize_schema()
    errors: list[BaseException] = []
    event.listen(database.engine, "handle_error", lambda ctx: errors.append(ctx.original_exception))
    yield database, errors
    database.engine.dispose()


def test_playback_claims_execute_on_postgres(postgres_database):
    from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

    database, errors = postgres_database
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    assert not repository.claim_next_playback(
        debate_id="d",
        expected_control_version=1,
        expected_current_turn_id="t",
        successor_turn_id="s",
        teacher_user_id="u",
    )
    assert not repository.claim_pause_playback(
        debate_id="d", expected_control_version=1, cursor_ms=0, teacher_user_id="u"
    )
    assert not repository.claim_resume_playback(
        debate_id="d", expected_control_version=1, teacher_user_id="u"
    )
    assert (
        repository.claim_finish_playback(
            debate_id="d", expected_control_version=1, teacher_user_id="u"
        )
        is None
    )
    assert (
        repository.claim_finish_playback(
            debate_id="d",
            expected_control_version=1,
            teacher_user_id="u",
            expected_current_turn_id=None,
        )
        is None
    )
    assert not repository.claim_replay_next_playback(
        debate_id="d",
        expected_control_version=1,
        expected_current_turn_id="t",
        successor_turn_id="s",
        expected_replay_index=0,
        teacher_user_id="u",
    )
    with database.session_factory() as session:
        assert not repository.claim_text_media_playback(
            session, debate_id="d", turn_id="t", expected_control_version=1, controller_epoch="e"
        )
    assert errors == []


def test_jsonb_predecessor_comparison_matches_compact_storage(postgres_database):
    database, _errors = postgres_database
    with database.engine.connect() as connection:
        # The column stores json.dumps(..., separators=(",", ":")).
        matched = connection.execute(
            text(
                "SELECT CAST(:stored AS TEXT)::jsonb = ("
                "SELECT COALESCE(jsonb_agg(x ORDER BY o), '[]'::jsonb) "
                "FROM (VALUES ('b', 2), ('a', 1)) AS v(x, o))"
            ),
            {"stored": '["a","b"]'},
        ).scalar()
        assert matched is True


def test_cleanup_empty_predicates_execute_on_postgres(postgres_database):
    from app.modules.debates import cleanup

    database, errors = postgres_database
    jobs = cleanup._table("jobs")
    with database.engine.connect() as connection:
        assert connection.execute(select(jobs.c.id).where(cleanup._or_all([]))).all() == []
    assert errors == []


def test_ensure_turn_job_on_conflict_matches_partial_unique_index(postgres_database):
    """uq_jobs_operation_idempotency_key is partial on Postgres (models.py).

    A bare ``ON CONFLICT (operation, idempotency_key)`` raised
    InvalidColumnReference in production prewarm; the insert must infer the
    partial index and stay idempotent.
    """

    from types import SimpleNamespace

    from app.modules.debates.playback.sql_repository import SqlPlaybackRepository

    database, errors = postgres_database
    with database.engine.connect() as connection:
        predicate = connection.execute(
            text(
                "SELECT pg_get_expr(i.indpred, i.indrelid) FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = 'uq_jobs_operation_idempotency_key'"
            )
        ).scalar()
    assert predicate is not None and "idempotency_key IS NOT NULL" in predicate

    debate = SimpleNamespace(id="d-1", cancellation_generation=0)
    turn = SimpleNamespace(id="t-1")
    with database.session_factory() as session:
        # The scratch schema has no debate/turn rows; skip FK triggers for this
        # rolled-back insert so only the ON CONFLICT inference is exercised.
        session.execute(text("SET session_replication_role = replica"))
        SqlPlaybackRepository._ensure_turn_job(session, debate, turn)
        SqlPlaybackRepository._ensure_turn_job(session, debate, turn)
        count = session.execute(
            text("SELECT COUNT(*) FROM jobs WHERE idempotency_key = 'd-1:t-1'")
        ).scalar()
        session.rollback()
    assert count == 1
    assert errors == []
