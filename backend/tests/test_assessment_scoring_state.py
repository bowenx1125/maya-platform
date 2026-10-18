"""While the Scorer marks a finished test, the Chat says "scoring" and a send waits.

Owner request (2026-10-18): after the last answer the student sees
"评分中…" with Send disabled. A send that still reaches the server meanwhile
gets ``chat_busy`` with ``reason: assessment_scoring``: a short wait, not a
failure, and the scoring turn is not disturbed. No new column: the state is
the existing ``assessment_stage`` of the session view.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import start_or_resume_attempt
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _answer_current,
    _create_formal_conversation,
    _service_actor,
)


def _scoring_chat(database: Any, settings: Any) -> tuple[str, str]:
    """A one-question test, answered, with the Scorer's server turn running."""

    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        _answer_current(db, actor, conversation_id, "我的回答")
        db.commit()
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        roles = runtime._formal_roles_for_conversation(db, conversation)
        assert roles is not None
        scorer = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == roles.scorer_id,
            )
        )
        assert scorer is not None
        executor = runtime.claim_assessment_executor_turn(
            db,
            settings,
            conversation_id=conversation_id,
            participant_id=scorer.id,
            actor_context=actor,
        )
        assert executor is not None
        result = db.scalar(select(TeamTurnResult).where(TeamTurnResult.turn_id == executor.turn_id))
        assert result is not None
        result.state = "running"
        db.commit()
    return conversation_id, executor.turn_id


def test_scoring_shows_in_the_session_and_a_send_waits_without_failing(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    settings = app_bundle[2]
    conversation_id, scoring_turn = _scoring_chat(database, settings)
    _payload, csrf = login(client, "bowen")

    session = client.get(f"/api/v1/conversations/{conversation_id}")
    assert session.status_code == 200, session.text
    view = session.json()
    assert view["assessment_stage"] == "scoring"

    with database.session() as db:
        turns_before = db.scalar(
            select(func.count())
            .select_from(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
        )
    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages:stream",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Accept": "text/event-stream",
        },
        json={
            "request_id": str(uuid4()),
            "expected_revision": view["revision"],
            "message": "好了吗",
            "routing": {"mode": "auto", "participant_ids": []},
        },
    )
    assert sent.status_code == 409, sent.text
    body = sent.json()
    assert body["code"] == "chat_busy"
    assert body["details"]["reason"] == "assessment_scoring"
    assert body["details"]["retryable"] is True

    # Nothing was stored for the refused send, and scoring carries on untouched.
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        turn = db.get(ConversationTurn, scoring_turn)
        assert row is not None and row.active_request_id == scoring_turn
        assert turn is not None and turn.state == "pending"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
            )
            == turns_before
        )
        assert not db.scalars(
            select(TeamTurnResult).where(
                TeamTurnResult.conversation_id == conversation_id,
                TeamTurnResult.state == "failed",
            )
        ).all()


def test_scoring_that_fails_lets_the_chat_continue(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    settings = app_bundle[2]
    conversation_id, scoring_turn = _scoring_chat(database, settings)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        turn = db.get(ConversationTurn, scoring_turn)
        assert row is not None and turn is not None
        turn.state = "failed"
        row.active_request_id = None
        db.commit()
    login(client, "bowen")
    view = client.get(f"/api/v1/conversations/{conversation_id}").json()
    # Nothing runs any more: the Chat stops showing scoring and takes messages.
    assert view["assessment_stage"] is None
    assert view["can_send"] is True


def test_an_ordinary_busy_chat_has_no_scoring_reason(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    from app.core.errors import PlatformError
    from app.modules.workspace.schemas import TeamRouting

    del client
    settings = app_bundle[2]
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        conversation.active_request_id = str(uuid4())  # another message is running
        revision = conversation.revision
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    with database.session() as db:
        try:
            runtime.claim_team_turn(
                db,
                settings,
                conversation_id=conversation_id,
                actor_id=actor.user.id,
                request_id=str(uuid4()),
                expected_revision=revision,
                message="你好",
                routing=TeamRouting(mode="all"),
                actor_context=actor,
            )
        except PlatformError as error:
            assert error.code == "chat_busy"
            assert "reason" not in error.details
        else:
            raise AssertionError("expected chat_busy")
