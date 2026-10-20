from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import ALEMBIC_HEAD, Database
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import start_or_resume_attempt
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentAttempt,
    AssessmentAttemptQuestion,
)
from app.modules.learning.recipes import refresh_assessment_activity_questions
from sqlalchemy import inspect, select, text

from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _create_formal_conversation,
    _service_actor,
)


def _config(database_url: str) -> Config:
    root = Path(__file__).parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.attributes["database_url"] = database_url
    return config


def _mark_revision(database: Database) -> None:
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES (?)", (ALEMBIC_HEAD,)
        )


def _assert_foreign_keys(database: Database) -> None:
    with database.engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []


def test_upgrade_backfills_completed_attempt_own_selection_with_fk_children(
    app_bundle: Any,
    client: Any,
) -> None:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, _team_id, _team_version_id, _publication_id, _set_id, _questions = (
            _create_formal_conversation(db, visibility="public")
        )
        student = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, student, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert attempt is not None and activity is not None
        assert attempt.question_selection_revision == 1
        old_questions = list(
            db.scalars(
                select(AssessmentAttemptQuestion).where(
                    AssessmentAttemptQuestion.attempt_id == attempt.id
                )
            ).all()
        )
        assert len(old_questions) == 2
        refresh_assessment_activity_questions(
            db,
            student,
            conversation_id,
            activity,
            force_new_revision=True,
        )
        assert activity.question_selection_revision == 2
        attempt.status = "completed"
        attempt.completed_at = datetime.now(UTC)

    _mark_revision(database)
    database.dispose()
    config = _config(database.database_url)
    command.downgrade(config, "0053_user_profile")
    assert "question_selection_revision" not in {
        column["name"] for column in inspect(database.engine).get_columns("assessment_attempts")
    }
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM assessment_attempt_questions")
            ).scalar_one()
            == 2
        )
    _assert_foreign_keys(database)

    database.dispose()
    database.upgrade_schema()
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert attempt is not None
        assert attempt.question_selection_revision == 1
        assert (
            db.scalar(
                select(AssessmentActivity.question_selection_revision).where(
                    AssessmentActivity.id == attempt.activity_id
                )
            )
            == 2
        )
    assert ALEMBIC_HEAD == "0077_real_delete_history_links"
    _assert_foreign_keys(database)


@pytest.mark.parametrize("status", ("in_progress", "paused"))
def test_downgrade_refuses_to_resurrect_answers_after_zero_question_selection(
    app_bundle: Any,
    client: Any,
    status: str,
) -> None:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, _team_id, _team_version_id, _publication_id, _set_id, _questions = (
            _create_formal_conversation(db, visibility="public")
        )
        student = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, student, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert attempt is not None and activity is not None
        attempt.status = status
        attempt.question_selection_revision = 2
        activity.question_selection_revision = 2
        attempt.revision += 1
        attempt.updated_at = datetime.now(UTC)

    _mark_revision(database)
    database.dispose()
    command.downgrade(_config(database.database_url), "0054_assessment_attempt_question_selection")
    with pytest.raises(RuntimeError, match="Cannot downgrade assessment question generations"):
        command.downgrade(_config(database.database_url), "0053_user_profile")
    assert "question_selection_revision" in {
        column["name"] for column in inspect(database.engine).get_columns("assessment_attempts")
    }
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0054_assessment_attempt_question_selection"
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM assessment_attempt_questions")
            ).scalar_one()
            == 2
        )
    _assert_foreign_keys(database)
