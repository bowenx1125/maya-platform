"""Actual transport-boundary revalidation for Team Provider sends."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock

import pytest
from agno.models.message import Message
from app.core.models import Agent, CourseMember, KnowledgeDocument, ProviderOperation, User
from app.modules.knowledge_sets.models import KnowledgeSet
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.teams.models import CourseTeamPublication, Team
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import dispatch_team_model
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from httpx import Response

from tests.test_mayaform_team_conversations import BOWEN_ID, MAYA_ID
from tests.test_team_provider_disclosure import _prepared
from tests.test_wave4_provider_preflight import _digest, _policy


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "actor_inactive",
        "actor_course_removed",
        "teacher_inactive",
        "teacher_role_revoked",
        "source_set_deleted",
        "source_document_epoch_changed",
        "agent_epoch_changed",
        "grant_revoked",
        "team_epoch_changed",
        "publication_revoked",
        "claim_superseded",
        "chat_withdrawn",
    ],
)
def test_team_llm_send_rechecks_live_authorization_after_reservation(
    mutation: str,
    client: TestClient,
    app_bundle: Any,
    monkeypatch: Any,
) -> None:
    _app, database, settings = app_bundle
    result_id, _original, document_id, set_id = _prepared(client, database, settings)
    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    policy = _policy(
        policy_id="team-actual-sending-guard",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("pending-policy"),
        ).resolved_endpoint,
    )
    settings.llm_provider_policy_hash = policy.policy_hash
    ProviderRepository(database).save_policy_snapshot(policy)

    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        row = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert row is not None and turn is not None and participant is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        grant = confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        conversation_id = row.id
        turn_id = turn.id
        participant_id = participant.id
        claim_token = turn.claim_token
        selected_binding_ids = {participant.team_member_id}
        grant_id = grant.id
    assert claim_token is not None
    request = runtime._start_member(
        database.session_factory, turn_id, claim_token, result_id, settings=settings
    )
    assert request is not None

    original_transition = ProviderRepository.transition
    transition_seen: list[str] = []

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        if kwargs.get("expected") == "reserved" and kwargs.get("state") == "sending":
            transition_seen.append(operation_id)
            with database.session() as db:
                row = db.get(Conversation, conversation_id)
                participant = db.get(ConversationParticipant, participant_id)
                assert row is not None and participant is not None
                if mutation == "actor_inactive":
                    actor = db.get(User, BOWEN_ID)
                    assert actor is not None
                    actor.status = "inactive"
                elif mutation == "actor_course_removed":
                    membership = db.get(CourseMember, (row.course_id, BOWEN_ID))
                    assert membership is not None
                    db.delete(membership)
                elif mutation == "teacher_inactive":
                    teacher = db.get(User, MAYA_ID)
                    assert teacher is not None
                    teacher.status = "inactive"
                elif mutation == "teacher_role_revoked":
                    teacher_membership = db.get(CourseMember, (row.course_id, MAYA_ID))
                    assert teacher_membership is not None
                    teacher_membership.role = "student"
                elif mutation == "source_set_deleted":
                    knowledge_set = db.get(KnowledgeSet, set_id)
                    assert knowledge_set is not None
                    knowledge_set.deleted_at = datetime.now(UTC)
                elif mutation == "source_document_epoch_changed":
                    document = db.get(KnowledgeDocument, document_id)
                    assert document is not None
                    document.authorization_epoch += 1
                elif mutation == "agent_epoch_changed":
                    agent = db.get(Agent, participant.agent_id)
                    assert agent is not None
                    agent.authorization_epoch += 1
                elif mutation == "grant_revoked":
                    from app.modules.workspace.models import TeamProviderStandingGrant

                    standing = db.get(TeamProviderStandingGrant, grant_id)
                    assert standing is not None
                    standing.revoked_at = datetime.now(UTC)
                elif mutation == "team_epoch_changed":
                    team = db.get(Team, row.team_id)
                    assert team is not None
                    team.authorization_epoch += 1
                elif mutation == "publication_revoked":
                    publication = db.get(CourseTeamPublication, row.publication_id)
                    assert publication is not None
                    publication.state = "revoked"
                elif mutation == "claim_superseded":
                    persisted_turn = db.get(ConversationTurn, turn_id)
                    assert persisted_turn is not None
                    persisted_turn.claim_token = "superseded-claim"
                elif mutation == "chat_withdrawn":
                    row.withdrawn_at = datetime.now(UTC)
        return original_transition(self, operation_id, **kwargs)

    monkeypatch.setattr(ProviderRepository, "transition", transition)
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Synthetic Team reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", transport
    )
    error: str | None = None
    with database.session() as db:
        try:
            dispatch_team_model(
                db,
                settings,
                request,
                [Message(role="user", content="synthetic current user")],
                [],
                None,
                ordinal=0,
                selected_binding_ids=selected_binding_ids,
                actor_context=None,
            )
        except Exception as exc:  # the public error is intentionally safe and generic
            error = type(exc).__name__

    assert len(transition_seen) == 1
    with database.session() as db:
        operation = db.get(ProviderOperation, transition_seen[0])
        assert operation is not None
        if mutation == "none":
            assert transport.call_count == 1
            assert operation.state == "succeeded"
            assert operation.charged_request_count == 1
            assert error is None
        else:
            assert transport.call_count == 0
            assert operation.state == "not_sent"
            assert operation.charged_request_count == 0
