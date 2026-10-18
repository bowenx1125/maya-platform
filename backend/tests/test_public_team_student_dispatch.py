"""A student's Teams-list Chat with a teacher's public Team reaches the model.

Bug (2026-10-19): after #186 the student could open and send in the teacher's
public Team "情感测试", but every member failed with team_context_changed and no
model call was made. The Provider sending guard and the dispatch recheck still
accepted an ordinary ("team") Chat only from the Team owner.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agno.models.message import Message
from app.core.errors import PlatformError
from app.modules.teams.models import CourseTeamPublication
from app.modules.workspace import team_runtime
from app.modules.workspace.chat_team_provider import dispatch_team_model
from app.modules.workspace.chat_team_sdk import TeamDispatchError
from app.modules.workspace.models import Conversation, ConversationTurn, TeamTurnResult
from app.modules.workspace.schemas import TeamRouting
from app.modules.workspace.team_runtime import claim_team_turn, result_ids
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select

from tests.conftest import login
from tests.test_mayaform_team_conversations import _create, _team
from tests.test_mayaform_teams import BOWEN_ID
from tests.test_wave4_provider_preflight import _digest, _policy


def _student_member_request(client: TestClient, app_bundle: Any) -> tuple[Any, Any, Any, str]:
    _app, database, settings = app_bundle
    team, _versions, _csrf = _team(client, database)
    _, student_csrf = login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "team", "team_id": team["id"]})
    assert session["entry_kind"] == "team" and session["origin"] == "custom_team"
    assert session["can_send"] is True

    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    policy = _policy(
        policy_id="public-team-student-dispatch",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("public-team-student-dispatch"),
        ).resolved_endpoint,
    )
    settings.llm_provider_policy_hash = policy.policy_hash
    ProviderRepository(database).save_policy_snapshot(policy)

    member_id = session["team"]["members"][0]["id"]
    with database.session() as db:
        claim = claim_team_turn(
            db,
            settings,
            conversation_id=session["id"],
            actor_id=BOWEN_ID,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="你好",
            routing=TeamRouting(mode="selected", participant_ids=[member_id]),
        )
    result_id = result_ids(database.session_factory, claim.turn_id)[0]
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        turn = db.get(ConversationTurn, claim.turn_id)
        assert result is not None and turn is not None and turn.claim_token is not None
        token = turn.claim_token
        participant = db.get(team_runtime.ConversationParticipant, result.participant_id)
        assert participant is not None
        binding_ids = {participant.team_member_id}
    request = team_runtime._start_member(
        database.session_factory, claim.turn_id, token, result_id, settings=settings
    )
    assert request is not None
    return database, settings, request, binding_ids


def _transport(monkeypatch: pytest.MonkeyPatch) -> Mock:
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Synthetic reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", transport
    )
    return transport


def _dispatch(database: Any, settings: Any, request: Any, binding_ids: set[str]) -> Any:
    with database.session() as db:
        return dispatch_team_model(
            db,
            settings,
            request,
            [Message(role="user", content="synthetic current user")],
            [],
            None,
            ordinal=0,
            selected_binding_ids=binding_ids,
            actor_context=None,
        )


def test_student_reaches_the_model_in_a_teacher_public_team_chat(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, settings, request, binding_ids = _student_member_request(client, app_bundle)
    transport = _transport(monkeypatch)

    _dispatch(database, settings, request, binding_ids)

    assert transport.call_count == 1


def test_revoked_teacher_publication_still_blocks_the_student_dispatch(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    database, settings, request, binding_ids = _student_member_request(client, app_bundle)
    with database.session() as db:
        conversation = db.get(Conversation, request.conversation_id)
        assert conversation is not None
        publication = db.scalar(
            select(CourseTeamPublication).where(
                CourseTeamPublication.team_id == conversation.team_id
            )
        )
        assert publication is not None
        publication.state = "revoked"
        db.commit()
    transport = _transport(monkeypatch)

    with pytest.raises((TeamDispatchError, PlatformError)):
        _dispatch(database, settings, request, binding_ids)

    assert transport.call_count == 0
