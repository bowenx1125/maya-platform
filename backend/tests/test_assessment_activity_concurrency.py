"""Many students starting one published assessment at once share one activity row.

40-student run (2026-10-18): uq_assessment_activity_recipe_publication was
violated 5 times when students started the same published assessment Team
together. Creating the shared activity is now an INSERT ... ON CONFLICT DO
NOTHING followed by a read, so a concurrent start never raises (or logs) a
unique violation. PostgreSQL only: SQLite's writer lock serializes starts.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.models import AssessmentActivity, AssessmentActivityQuestion
from app.modules.learning.recipes import ensure_assessment_activity
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

from tests.conftest import login
from tests.postgres_db import named_url
from tests.test_mayaform_assessment_attempts import _create_formal_conversation

_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")
STARTS = 12


@pytest.fixture()
def postgres_classroom(app_factory: Any) -> Any:
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    from app.core.db import Database
    from app.main import create_app
    from sqlalchemy import text

    _app, sqlite_database, base = app_factory()
    sqlite_database.dispose()
    settings = base.model_copy(update={"database_url": named_url("pg", schema=False)})
    database = Database(named_url("pg", schema=False), settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    app = create_app(settings, database)
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            db.commit()
        yield database, settings, client
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    database.dispose()


def test_concurrent_starts_create_one_activity_without_a_unique_violation(
    postgres_classroom: Any,
) -> None:
    database, settings, client = postgres_classroom
    session, _csrf = login(client, "bowen")
    token = client.cookies.get("maya_session")
    assert token
    with database.session() as db:
        conversation_id, *_rest, questions = _create_formal_conversation(
            db, actor_user_id=session["user"]["id"]
        )
        db.commit()

    violations: list[str] = []

    def count_violation(context: Any) -> None:
        if isinstance(context.original_exception, Exception) and isinstance(
            context.sqlalchemy_exception, IntegrityError
        ):
            violations.append(str(context.original_exception).splitlines()[0])

    event.listen(database.engine, "handle_error", count_violation)
    barrier = threading.Barrier(STARTS)
    results: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def start() -> None:
        try:
            with database.session() as db:
                actor = get_auth_context(db, settings, token)
                assert actor is not None
                barrier.wait(timeout=30)
                activity = ensure_assessment_activity(db, actor, conversation_id)
                assert activity is not None
                activity_id = activity.id
                db.commit()
            with lock:
                results.append(activity_id)
        except BaseException as exc:  # noqa: BLE001 - reported below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(STARTS)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
    finally:
        event.remove(database.engine, "handle_error", count_violation)

    assert errors == []
    assert violations == []
    assert len(results) == STARTS and len(set(results)) == 1
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(AssessmentActivity)) == 1
        assert db.scalar(
            select(func.count())
            .select_from(AssessmentActivityQuestion)
            .where(AssessmentActivityQuestion.activity_id == results[0])
        ) == len(questions)
