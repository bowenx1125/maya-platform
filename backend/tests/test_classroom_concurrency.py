"""A whole class at once: 40 and 60 students sign in, build a Team, chat with
it and finish a formal assessment, all concurrently.

Mock providers keep model calls instant, so what is exercised is the real
admission queue, the write guard, the login path (Argon2 behind its gate),
Team creation, Team chat claims, and the assessment ledger writes. Every
student must end with a stored attempt whose every question has an answer,
the teacher's Record must list them all, and the admission counters must
drain back to zero (nothing stuck in flight, nothing still queued).
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from app.core import adaptive_admission as aa
from app.core import write_guard as wg
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import (
    apply_assessment_decision,
    mark_attempt_question_presented,
    start_or_resume_attempt,
)
from app.modules.learning.models import AssessmentAttempt, LearningRecord
from app.modules.learning.schemas import AssessmentRuntimeDecision
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tests.conftest import login
from tests.postgres_db import named_url
from tests.test_mayaform_assessment_attempts import _create_formal_conversation
from tests.test_mayaform_team_conversations import _make_agent_version

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
PASSWORD = "classroom-load-1"
# Busy answers are retried the way a student would press Send again.
SEND_AGAIN_CODES = {"adaptive_admission_busy", "write_pressure", "llm_admission_busy"}


def _retrying(call: Any, attempts: int = 30) -> Any:
    for _ in range(attempts):
        response = call()
        if response.status_code == 503 and response.json().get("code") in SEND_AGAIN_CODES:
            time.sleep(0.2)
            continue
        return response
    return response


def _student(
    app: Any, database: Any, settings: Any, index: int, members: list[str]
) -> dict[str, Any]:
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    username = f"load{index:03d}{uuid4().hex[:6]}"
    group = f"Load group {index % 8}"
    registered = _retrying(
        lambda: client.post(
            "/api/v1/auth/register",
            json={
                "username": username,
                "password": PASSWORD,
                "group_name": group,
                "course_id": COURSE_ID,
            },
        )
    )
    assert registered.status_code in (200, 201), registered.text
    signed_in = _retrying(
        lambda: client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    )
    assert signed_in.status_code == 200, signed_in.text
    session = signed_in.json()
    csrf = session["csrf_token"]
    user_id = session["user"]["id"]
    headers = {"X-CSRF-Token": csrf}
    # Students reach teachers' public Agents only through Teams (#182), so each
    # student builds the Team from Agents of their own.
    members = [
        _make_agent_version(
            database, owner_id=user_id, name=f"{username} agent {n}", visibility="private"
        )[1]
        for n in range(2)
    ]

    team = _retrying(
        lambda: client.post(
            f"/api/v1/courses/{COURSE_ID}/teams",
            headers={**headers, "Idempotency-Key": f"load-team-{username}"},
            json={
                "display_name": f"{username} study team",
                "visibility": "private",
                "members": [
                    {
                        "agent_version_id": version_id,
                        "position": position,
                        "is_leader": position == 0,
                    }
                    for position, version_id in enumerate(members)
                ],
            },
        )
    )
    assert team.status_code == 201, team.text
    chat = _retrying(
        lambda: client.post(
            "/api/v1/conversations",
            headers=headers,
            json={"entry": {"kind": "team", "team_id": team.json()["id"]}},
        )
    )
    assert chat.status_code == 200, chat.text
    conversation = chat.json()
    request_id = str(uuid4())
    sent = _retrying(
        lambda: client.post(
            f"/api/v1/conversations/{conversation['id']}/messages:stream",
            headers={**headers, "Accept": "text/event-stream"},
            json={
                "request_id": request_id,
                "expected_revision": conversation["revision"],
                "message": "我们一起复习一下这一课",
                "routing": {"mode": "all", "participant_ids": []},
            },
        )
    )
    assert sent.status_code == 200, sent.text
    assert "turn_done" in sent.text or "member_result" in sent.text

    token = client.cookies.get("maya_session")
    assert token
    with database.session() as db:
        formal_id, *_rest = _create_formal_conversation(db, actor_user_id=user_id)
        db.commit()
    with database.session() as db:
        actor = get_auth_context(db, settings, token)
        assert actor is not None
        context = start_or_resume_attempt(db, actor, formal_id, client_event_id=uuid4())
        assert context is not None
        answered = 0
        while context.current_question is not None:
            question = context.current_question
            mark_attempt_question_presented(
                db, actor, formal_id, question_version_id=question.question_version_id
            )
            recorded = apply_assessment_decision(
                db,
                actor,
                formal_id,
                user_message=f"答案 {answered}",
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="answer_only",
                    answer_span=f"答案 {answered}",
                    question_version_id=question.question_version_id,
                ),
            )
            assert recorded is not None
            context = recorded.context
            answered += 1
        db.commit()
    return {"user_id": user_id, "formal_id": formal_id, "answered": answered}


_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")


@pytest.fixture()
def classroom(app_factory: Any) -> Any:
    """The production database shape: PostgreSQL behind the real app.

    SQLite admits one writer at a time, so a whole class writing at once
    measures its lock, not this code; production runs PostgreSQL. The test
    runs when MAYA_TEST_POSTGRES_URL names a scratch database (its public
    schema is dropped); CI starts one.
    """

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
    aa.set_signal_readers(load=lambda: 0.5, mem=lambda: 4000.0)
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            db.commit()
        yield app, database, settings, client
    aa.set_signal_readers()
    aa.reset_adaptive_admission_state()
    wg.reset_write_guard_state()
    database.dispose()


@pytest.mark.parametrize("students", [40, 60])
def test_a_whole_class_at_once(classroom: Any, students: int) -> None:
    app, database, settings, client = classroom
    members: list[str] = []  # each student seeds their own Agents in _student
    start = threading.Barrier(students)

    def run(index: int) -> dict[str, Any]:
        start.wait(30)
        return _student(app, database, settings, index, members)

    with ThreadPoolExecutor(max_workers=students) as pool:
        futures = [pool.submit(run, index) for index in range(students)]
        results = [future.result(timeout=600) for future in futures]

    assert len({result["user_id"] for result in results}) == students
    assert all(result["answered"] >= 1 for result in results)
    formal_ids = [result["formal_id"] for result in results]
    with database.session() as db:
        attempts = db.scalar(
            select(func.count())
            .select_from(AssessmentAttempt)
            .where(AssessmentAttempt.source_conversation_id.in_(formal_ids))
        )
        assert attempts == students
        answers = db.scalar(
            select(func.count())
            .select_from(LearningRecord)
            .join(AssessmentAttempt, AssessmentAttempt.id == LearningRecord.attempt_id)
            .where(AssessmentAttempt.source_conversation_id.in_(formal_ids))
        )
        assert answers >= sum(result["answered"] for result in results)

    # The teacher reads every student's attempt from Brainform Record.
    _, teacher_csrf = login(client, "maya")
    statements: list[str] = []

    def count(*args: Any) -> None:
        statements.append(args[2])

    event.listen(database.engine, "before_cursor_execute", count)
    try:
        listed = client.get(f"/api/v1/learning/courses/{COURSE_ID}/assessment-attempts")
    finally:
        event.remove(database.engine, "before_cursor_execute", count)
    assert listed.status_code == 200, listed.text
    listed_users = {row["user_id"] for row in listed.json()}
    assert {result["user_id"] for result in results} <= listed_users
    # #123: each activity is checked once and each sheet built once, not once
    # per group (8 groups; here every student has their own Team). 40 rows took
    # 8,712 statements before and 1,127 after.
    assert len(statements) <= 30 * len(listed.json()) + 100
    # One attempt asked for builds one sheet and returns the same row.
    first = listed.json()[0]
    single = client.get(
        f"/api/v1/learning/courses/{COURSE_ID}/assessment-attempts",
        params={"attempt_id": first["attempt_id"]},
    )
    assert single.status_code == 200, single.text
    assert single.json() == [first]

    snapshot = aa.adaptive_admission_snapshot(settings)
    assert snapshot["in_flight"] == 0
    assert snapshot["in_flight_units"] == 0
    assert snapshot["queue_depth"] == 0
    assert wg._GATE.in_flight == 0
