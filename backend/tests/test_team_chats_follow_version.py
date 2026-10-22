"""Open Team chats follow a new Team version and keep their history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.learning.models import AssessmentActivity, AssessmentAttempt
from app.modules.teams.models import Team, TeamVersionMember
from app.modules.teams.service import follow_published_agent
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_mayaform_team_conversations import _create, _team
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers


def _resave(client: TestClient, csrf: str, team: dict[str, Any], name: str) -> dict[str, Any]:
    saved = client.put(
        f"/api/v1/teams/{team['id']}",
        headers=_headers(csrf, f"team-retarget-{uuid4()}"),
        json={
            "display_name": name,
            "visibility": team["visibility"],
            "members": [
                {
                    "agent_version_id": member["agent_version_id"],
                    "is_leader": member["is_leader"],
                    "position": member["position"],
                }
                for member in team["members"]
            ],
            "shared_knowledge_set_ids": team["shared_knowledge_set_ids"],
            "expected_metadata_revision": team["metadata_revision"],
        },
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def _remember(database: Any, conversation_id: str, text: str) -> str:
    now = datetime.now(UTC)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        speaker = db.scalar(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation_id)
            .order_by(ConversationParticipant.position)
        )
        assert speaker is not None
        turn_id = str(uuid4())
        db.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=conversation_id,
                position=0,
                user_text=text,
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="ready",
                created_at=now,
            )
        )
        db.add(
            TeamTurnResult(
                id=str(uuid4()),
                turn_id=turn_id,
                conversation_id=conversation_id,
                participant_id=speaker.id,
                ordinal=0,
                state="ready",
                assistant_text="kept answer",
                sources_json="[]",
                created_at=now,
                completed_at=now,
            )
        )
        speaker_id = speaker.id
    return speaker_id


def test_editing_a_team_moves_the_open_chat_and_keeps_history(
    client: TestClient, database: Any
) -> None:
    team, _versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    speaker_id = _remember(database, session["id"], "first question")
    saved = _resave(client, csrf, team, "Reasoning circle 2")
    assert saved["current_version_id"] != team["current_version_id"]

    reloaded = client.get(f"/api/v1/conversations/{session['id']}", headers=_headers(csrf))
    assert reloaded.status_code == 200, reloaded.text
    body = reloaded.json()
    assert body["team"]["version_id"] == saved["current_version_id"]
    assert body["team"]["name"] == "Reasoning circle 2"
    assert [turn["user_text"] for turn in body["turns"]] == ["first question"]
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None
        assert row.revision == 0
        result = db.scalar(
            select(TeamTurnResult).where(TeamTurnResult.conversation_id == session["id"])
        )
        assert result is not None and result.participant_id == speaker_id
        assert result.assistant_text == "kept answer"


def test_follow_published_agent_moves_the_open_chat(client: TestClient, database: Any) -> None:
    from app.core.models import Agent, AgentVersion

    team, versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    _remember(database, session["id"], "still here")
    first_agent = next(
        member["agent_id"]
        for member in team["members"]
        if member["agent_version_id"] == versions[0]
    )
    republished = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        old = db.get(AgentVersion, versions[0])
        assert old is not None
        old.state = "superseded"
        db.add(
            AgentVersion(
                id=republished,
                agent_id=first_agent,
                version_seq=2,
                state="published",
                revision=1,
                agent_md="# Follow v2",
                avatar_config_json=old.avatar_config_json,
                authorization_epoch=0,
                draft_visibility="public",
                published_visibility="public",
                published_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        agent = db.get(Agent, first_agent)
        assert agent is not None
        agent.current_published_version_id = republished
        db.commit()
        follow_published_agent(db, first_agent)

    with database.session() as db:
        current = db.get(Team, team["id"])
        assert current is not None and current.current_version_seq == 2
        version_id = db.scalar(
            select(TeamVersionMember.team_version_id).where(
                TeamVersionMember.agent_version_id == republished
            )
        )
        # The member row's version id is the team version that holds the republished agent.
        row = db.get(Conversation, session["id"])
        assert row is not None and version_id is not None
        assert row.team_version_id == version_id
        moved = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == session["id"],
                ConversationParticipant.agent_id == first_agent,
            )
        )
        assert moved is not None and moved.agent_version_id == republished
        turn = db.scalar(
            select(ConversationTurn).where(ConversationTurn.conversation_id == session["id"])
        )
        assert turn is not None and turn.user_text == "still here"


def test_a_mid_reply_chat_waits_until_the_sweep(client: TestClient, database: Any) -> None:
    from app.modules.teams.retarget import retarget_team_chats, teams_with_stale_chats

    team, _versions, csrf = _team(client, database)
    session = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    _remember(database, session["id"], "in flight")
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None
        row.active_request_id = str(uuid4())
    saved = _resave(client, csrf, team, "Still answering")
    with database.session() as db:
        row = db.get(Conversation, session["id"])
        assert row is not None and row.team_version_id == team["current_version_id"]
        row.active_request_id = None
        db.commit()
        assert team["id"] in teams_with_stale_chats(db)
        assert retarget_team_chats(db, team["id"]) == 1
    reloaded = client.get(f"/api/v1/conversations/{session['id']}", headers=_headers(csrf))
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["team"]["version_id"] == saved["current_version_id"]
    assert reloaded.json()["turns"][0]["user_text"] == "in flight"


def test_in_progress_assessment_chat_stays_on_its_attempt(
    client: TestClient, database: Any
) -> None:
    team, _versions, csrf = _team(client, database)
    formal = _create(client, csrf, {"kind": "maya_team", "team_id": team["id"]})
    ordinary = _create(client, csrf, {"kind": "team", "team_id": team["id"]})
    _remember(database, formal["id"], "exam answer")
    now = datetime.now(UTC)
    with database.session() as db:
        row = db.get(Conversation, formal["id"])
        assert row is not None and row.publication_id is not None
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == row.id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        assert leader is not None
        activity_id = str(uuid4())
        db.add(
            AssessmentActivity(
                id=activity_id,
                course_id=COURSE_ID,
                team_id=row.team_id,
                team_version_id=row.team_version_id,
                publication_id=row.publication_id,
                recipe_id="mayaform.retarget.test",
                recipe_version_id=leader.agent_version_id,
                evaluator_team_member_id=leader.team_member_id,
                evaluator_agent_version_id=leader.agent_version_id,
                boundary_team_member_id=leader.team_member_id,
                boundary_agent_version_id=leader.agent_version_id,
                publisher_user_id=MAYA_ID,
                questions_hash="a" * 64,
                question_selection_revision=1,
                created_at=now,
            )
        )
        db.flush()
        attempt_id = str(uuid4())
        db.add(
            AssessmentAttempt(
                id=attempt_id,
                activity_id=activity_id,
                team_id=row.team_id,
                recipe_id="mayaform.retarget.test",
                actor_user_id=MAYA_ID,
                source_conversation_id=row.id,
                chat_visibility="private",
                status="in_progress",
                revision=1,
                question_selection_revision=1,
                started_at=now,
                updated_at=now,
            )
        )
    saved = _resave(client, csrf, team, "Exam still open")
    with database.session() as db:
        frozen = db.get(Conversation, formal["id"])
        moved = db.get(Conversation, ordinary["id"])
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert frozen is not None and moved is not None and attempt is not None
        assert frozen.team_version_id == team["current_version_id"]
        assert moved.team_version_id == saved["current_version_id"]
        assert attempt.status == "in_progress"
        assert attempt.source_conversation_id == formal["id"]
        answer = db.scalar(
            select(TeamTurnResult.assistant_text).where(
                TeamTurnResult.conversation_id == formal["id"]
            )
        )
        assert answer == "kept answer"
