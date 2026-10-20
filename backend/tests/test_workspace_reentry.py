from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import CourseMember
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import (
    apply_attempt_lifecycle_action,
    start_or_resume_attempt,
)
from app.modules.learning.models import AssessmentAttempt
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_mayaform_assessment_attempts import _create_formal_conversation

AttemptStatus = Literal["in_progress", "paused", "completed", "abandoned"]
HISTORY_TEXT = "Saved earlier team reply."


@pytest.fixture
def reentry_env(
    app_bundle: Any,
    client: TestClient,
) -> tuple[Database, Any, TestClient]:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return database, settings, client


def _login(client: TestClient, username: str) -> tuple[str, str, str]:
    payload, csrf = login(client, username)
    token = client.cookies.get("maya_session")
    assert token
    return str(payload["user"]["id"]), token, csrf


def _create_attempt(
    database: Database,
    settings: Any,
    *,
    actor_user_id: str,
    actor_token: str,
    visibility: Literal["private", "public"],
    status: AttemptStatus,
) -> tuple[str, str, str, int]:
    with database.session() as db:
        source_id, team_id, *_ = _create_formal_conversation(
            db,
            actor_user_id=actor_user_id,
            visibility=visibility,
        )
        actor = get_auth_context(db, settings, actor_token)
        assert actor is not None
        started = start_or_resume_attempt(db, actor, source_id, client_event_id=uuid4())
        assert started is not None
        attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert attempt is not None
        if status == "paused":
            paused = apply_attempt_lifecycle_action(
                db,
                actor,
                attempt.id,
                client_event_id=uuid4(),
                action="pause",
            )
            assert paused is not None and paused.response_key == "assessment.paused"
        elif status == "abandoned":
            abandoned = apply_attempt_lifecycle_action(
                db,
                actor,
                attempt.id,
                client_event_id=uuid4(),
                action="abandon",
            )
            assert abandoned is not None and abandoned.response_key == "assessment.abandoned"
        elif status == "completed":
            attempt.status = "completed"
            attempt.completed_at = datetime.now(UTC)
            attempt.updated_at = datetime.now(UTC)
            db.flush()

        participant = db.scalar(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == source_id)
            .order_by(ConversationParticipant.position)
        )
        assert participant is not None
        now = datetime.now(UTC)
        turn = ConversationTurn(
            id=str(uuid4()),
            conversation_id=source_id,
            position=0,
            user_text="Show my saved progress.",
            assistant_text=None,
            sources_json="[]",
            mode="mock",
            state="ready",
            safe_error_code=None,
            routing_json=None,
            request_hash=None,
            claim_token=None,
            created_at=now,
        )
        db.add(turn)
        db.flush()
        db.add(
            TeamTurnResult(
                id=str(uuid4()),
                turn_id=turn.id,
                conversation_id=source_id,
                participant_id=participant.id,
                ordinal=0,
                state="ready",
                assistant_text=HISTORY_TEXT,
                sources_json="[]",
                safe_error_code=None,
                created_at=now,
                completed_at=now,
            )
        )
        conversation = db.get(Conversation, source_id)
        assert conversation is not None
        conversation.revision = 1
        db.flush()
        return source_id, team_id, attempt.id, attempt.revision


def _post_maya_team(
    client: TestClient,
    csrf: str,
    team_id: str,
    *,
    include_csrf: bool = True,
) -> Any:
    headers = {"Origin": "http://testserver"}
    if include_csrf:
        headers["X-CSRF-Token"] = csrf
    return client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"entry": {"kind": "maya_team", "team_id": team_id}},
    )


# A source Chat stored before every Chat became private may still read "public".
@pytest.mark.parametrize("visibility", ["private", "public"])
@pytest.mark.parametrize(
    ("attempt_status", "reuse_source"),
    [
        ("in_progress", True),
        ("paused", True),
        ("completed", False),
        ("abandoned", False),
    ],
)
def test_public_maya_team_post_reuses_only_the_live_owned_attempt_chat(
    reentry_env: tuple[Database, Any, TestClient],
    visibility: Literal["private", "public"],
    attempt_status: AttemptStatus,
    reuse_source: bool,
) -> None:
    database, settings, client = reentry_env
    actor_user_id, actor_token, csrf = _login(client, "bowen")
    source_id, team_id, attempt_id, attempt_revision = _create_attempt(
        database,
        settings,
        actor_user_id=actor_user_id,
        actor_token=actor_token,
        visibility=visibility,
        status=attempt_status,
    )

    rejected = _post_maya_team(client, csrf, team_id, include_csrf=False)
    assert rejected.status_code == 403

    response = _post_maya_team(client, csrf, team_id)
    assert response.status_code == 200, response.text
    session = response.json()
    if reuse_source:
        assert session["id"] == source_id
        assert session["chat_visibility"] == visibility
        assert session["read_only"] is False
        assert session["turns"][0]["user_text"] == "Show my saved progress."
        assert session["turns"][0]["member_results"][0]["assistant_text"] == HISTORY_TEXT
    else:
        assert session["id"] != source_id
        assert session["chat_visibility"] == "private"
        assert session["turns"] == []
        assert session["revision"] == 0

    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None
        assert attempt.status == attempt_status
        assert attempt.revision == attempt_revision
        assert (
            db.scalar(
                select(func.count(AssessmentAttempt.id)).where(
                    AssessmentAttempt.actor_user_id == actor_user_id,
                    AssessmentAttempt.team_id == team_id,
                )
            )
            == 1
        )
        assert db.scalar(
            select(func.count(Conversation.id)).where(
                Conversation.user_id == actor_user_id,
                Conversation.team_id == team_id,
            )
        ) == (1 if reuse_source else 2)


def test_reentry_lookup_is_scoped_to_actor_and_current_course_membership(
    reentry_env: tuple[Database, Any, TestClient],
) -> None:
    database, settings, client = reentry_env
    bowen_id, bowen_token, _bowen_csrf = _login(client, "bowen")
    source_id, team_id, _attempt_id, _attempt_revision = _create_attempt(
        database,
        settings,
        actor_user_id=bowen_id,
        actor_token=bowen_token,
        visibility="private",
        status="paused",
    )

    kaikai_id, _kaikai_token, kaikai_csrf = _login(client, "kaikai")
    kaikai_response = _post_maya_team(client, kaikai_csrf, team_id)
    assert kaikai_response.status_code == 200, kaikai_response.text
    kaikai_session = kaikai_response.json()
    assert kaikai_session["id"] != source_id
    assert kaikai_session["chat_visibility"] == "private"
    assert kaikai_session["turns"] == []
    assert client.get(f"/api/v1/conversations/{source_id}").status_code == 404

    with database.session() as db:
        membership = db.get(CourseMember, ("b1ae79ed-e4a6-5b02-9abd-3a3ae944284b", kaikai_id))
        assert membership is not None
        db.delete(membership)
    denied = _post_maya_team(client, kaikai_csrf, team_id)
    assert denied.status_code == 404

    _teacher_id, _teacher_token, teacher_csrf = _login(client, "maya")
    teacher_response = _post_maya_team(client, teacher_csrf, team_id)
    assert teacher_response.status_code == 200, teacher_response.text
    assert teacher_response.json()["id"] not in {source_id, kaikai_session["id"]}


def test_deleted_chat_keeps_its_unfinished_attempt_for_a_new_chat(
    reentry_env: tuple[Database, Any, TestClient],
) -> None:
    database, settings, client = reentry_env
    actor_user_id, actor_token, csrf = _login(client, "bowen")
    source_id, team_id, attempt_id, _attempt_revision = _create_attempt(
        database,
        settings,
        actor_user_id=actor_user_id,
        actor_token=actor_token,
        visibility="private",
        status="paused",
    )

    deleted = client.delete(
        f"/api/v1/conversations/{source_id}",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert deleted.status_code == 204
    response = _post_maya_team(client, csrf, team_id)
    assert response.status_code == 200, response.text
    session = response.json()
    assert session["id"] != source_id
    assert session["chat_visibility"] == "private"
    assert session["turns"] == []

    with database.session() as db:
        source = db.get(Conversation, source_id)
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert source is not None and source.withdrawn_at is not None
        assert attempt is not None
        # Owner rule (2026-10-20): deleting the Chat keeps the attempt unfinished
        # until the student chooses to continue it or restart.
        assert attempt.status == "paused"
        assert attempt.abandonment_reason is None
