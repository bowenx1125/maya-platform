"""Synthetic shared-ledger and lossless Team Provider stage probes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from agno.models.message import Message
from app.core.errors import PlatformError
from app.core.models import ProviderExportManifest, ProviderOperation
from app.modules.provider_disclosure.team_standing import (
    authorize_team_dispatch,
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import dispatch_team_model, team_request_bytes
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from app.modules.workspace.team_runtime import _start_member
from app.providers.control import (
    LLM_DEBATE_TURN_BUCKET,
    OperationStateError,
    ProviderScopeBudgetV1,
    authorized_provider_model,
)
from app.providers.control_repository import ProviderRepository, ProviderRepositoryError
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from tests.test_mayaform_team_conversations import MAYA_ID
from tests.test_team_provider_disclosure import _prepared
from tests.test_wave4_provider_control_orm import _repository_with_confirmed_manifest, _request
from tests.test_wave4_provider_preflight import _digest, _policy


def test_team_not_sent_releases_shared_budget_and_charged_count(tmp_path: Path) -> None:
    _database, repository, manifest = _repository_with_confirmed_manifest(
        tmp_path, scope_id="team-result:synthetic", require_export_confirmation=False
    )
    request = replace(
        _request(manifest),
        provider_operation="llm_agent_chat",
        budget_bucket=LLM_DEBATE_TURN_BUCKET,
        model_key=authorized_provider_model("llm_agent_chat"),
    )
    repository.save_scope_budget(
        request.scope_id,
        ProviderScopeBudgetV1(
            max_requests=10,
            max_total_tokens=10000,
            max_cost_cny=1,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    not_sent = repository.mark_not_sent(operation.id)
    assert not_sent.state == "not_sent"
    assert not_sent.request_count == not_sent.charged_request_count == 0


def _dispatch(
    client: TestClient, app_bundle: Any, *, wire: str | None = None
) -> tuple[Any, Any, str]:
    _app, database, settings = app_bundle
    result_id, original, _document, _set = _prepared(client, database, settings)
    wire = wire or '{"messages":[{"role":"user","content":"exact"}]}'
    manifest = replace(original, build_manifest_hash=_digest(wire))
    repository = ProviderRepository(database)
    with database.session() as db:
        original_row = db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == original.manifest_hash
            )
        )
        policy_id, version_id = original_row.policy_snapshot_id, original_row.agent_version_id
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=original_row.course_id,
        agent_version_id=version_id,
    )
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=manifest.policy_hash,
            provider_operation=manifest.provider_operation,
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=manifest.policy_hash,
            provider_operation=manifest.provider_operation,
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        participant_id = result.participant_id
        turn_id = result.turn_id
        token = db.get(ConversationTurn, turn_id).claim_token
    assert _start_member(database.session_factory, turn_id, token, result_id) is not None
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        participant = db.get(ConversationParticipant, participant_id)
        turn = db.get(ConversationTurn, result.turn_id)
        assert turn is not None and turn.claim_token is not None
        authorize_team_dispatch(
            db,
            actor_user_id=conversation.user_id,
            result_id=result_id,
            manifest=manifest,
            selected_binding_ids={participant.team_member_id},
            claim_token=turn.claim_token,
        )
        result = db.get(TeamTurnResult, result_id)
        turn = db.get(ConversationTurn, result.turn_id)
        token, turn_id = turn.claim_token, turn.id
        db.commit()
    request = replace(_request(manifest), request_hash=_digest(wire))
    operation = repository.create_team_prepared(
        request,
        result_id=result_id,
        ordinal=0,
        request_json=wire,
        claim_token=token,
        binding_guard=lambda _connection, _row: True,
    )
    repository.save_scope_budget(
        request.scope_id,
        ProviderScopeBudgetV1(
            max_requests=100,
            max_total_tokens=10000,
            max_cost_cny=1,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    return database, repository, operation.id


def test_team_dispatch_requires_current_claim_when_conversation_revision_advances(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, _document, _set = _prepared(client, database, settings)
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        conversation = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert conversation is not None and turn is not None and participant is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=manifest.policy_hash,
            provider_operation=manifest.provider_operation,
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=manifest.policy_hash,
            provider_operation=manifest.provider_operation,
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        turn_id = turn.id
        initial_claim_token = turn.claim_token
    assert initial_claim_token is not None
    assert (
        _start_member(database.session_factory, turn_id, initial_claim_token, result_id) is not None
    )

    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        conversation = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert conversation is not None and turn is not None and participant is not None
        current_claim_token = turn.claim_token
        assert current_claim_token is not None
        conversation.revision = max(conversation.revision, turn.position + 1)
        target = {
            "actor_user_id": conversation.user_id,
            "result_id": result_id,
            "manifest": manifest,
            "selected_binding_ids": {participant.team_member_id},
        }
        with pytest.raises(PlatformError) as stale_claim:
            authorize_team_dispatch(
                db,
                **target,
                claim_token=f"stale-{current_claim_token}",
            )
        assert stale_claim.value.code == "not_found"
        authorized = authorize_team_dispatch(
            db,
            **target,
            claim_token=current_claim_token,
        )
        assert authorized.standing_grant_id is not None


def test_team_acceptance_is_atomic_immutable_and_usage_is_optional(
    client: TestClient, app_bundle: Any
) -> None:
    database, repository, operation_id = _dispatch(client, app_bundle)
    response = '{"choices":[{"message":{"role":"assistant","content":"valid reply"}}]}'

    def fail(_db: Any, _cursor: Any, sql: str, params: Any, _ctx: Any, _many: bool) -> None:
        values = params.values() if isinstance(params, dict) else params
        if sql.startswith("UPDATE provider_operations") and "accepted" in values:
            raise RuntimeError("injected acceptance failure")

    event.listen(Engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="injected acceptance failure"):
            repository.stage_team_accepted(operation_id, response_json=response)
    finally:
        event.remove(Engine, "before_cursor_execute", fail)
    with database.session() as db:
        stage = db.scalar(select(TeamProviderCall))
        assert stage.accepted_response_json is None
        assert db.get(ProviderOperation, operation_id).state == "sending"
    assert repository.stage_team_accepted(operation_id, response_json=response).state == "accepted"
    assert repository.stage_team_accepted(operation_id, response_json=response).state == "accepted"
    with pytest.raises(ProviderRepositoryError, match="immutable"):
        repository.stage_team_accepted(operation_id, response_json='{"different":true}')
    with database.session() as db:
        stage = db.scalar(select(TeamProviderCall))
        assert stage.accepted_response_json == response
        assert stage.accepted_response_hash == _digest(response)
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 1
    assert repository.mark_succeeded(operation_id).state == "succeeded"


def test_unknown_keeps_charged_count_and_cannot_accept_a_late_response(
    client: TestClient, app_bundle: Any
) -> None:
    _database, repository, operation_id = _dispatch(client, app_bundle)
    operation = repository.mark_acceptance_unknown(operation_id)
    assert operation.charged_request_count == 1
    with pytest.raises(OperationStateError):
        repository.stage_team_accepted(operation_id, response_json='{"late":true}')


def test_real_team_dispatch_stages_exact_wire_and_resumes_without_a_second_transport(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    result_id, _original, _document, _set = _prepared(client, database, settings)
    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    policy = _policy(
        policy_id="team-runtime-synthetic",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("pending-policy"),
        ).resolved_endpoint,
    )
    settings.llm_provider_policy_hash = policy.policy_hash
    repository = ProviderRepository(database)
    repository.save_policy_snapshot(policy)

    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        turn = db.get(ConversationTurn, result.turn_id)
        conversation = db.get(Conversation, result.conversation_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert turn is not None and conversation is not None and participant is not None
        grant_plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        grant = confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=grant_plan.resource_hash,
            expected_team_epoch=grant_plan.team_epoch,
            expected_publication_epoch=grant_plan.publication_epoch,
        )
        assert grant.revoked_at is None
        claim_token = turn.claim_token
        turn_id = turn.id
        actor_id = conversation.user_id
        selected_binding_ids = {participant.team_member_id}
    request = runtime._start_member(
        database.session_factory, turn_id, claim_token, result_id, settings=settings
    )
    assert request is not None
    messages = [Message(role="user", content="A synthetic exact Team request")]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_session",
                "description": "Read current session context",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        }
    ]
    expected_wire = team_request_bytes(settings.llm_model, messages, tools, "auto")
    accepted_body = (
        b'{"choices":[{"message":{"role":"assistant","content":"A staged answer"},'
        b'"finish_reason":"stop"}]}'
    )

    class FakeResponse:
        status_code = 200
        content = accepted_body

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []

        def post_bytes(self, endpoint: str, *, content: bytes, **_kwargs: Any) -> FakeResponse:
            self.calls.append((endpoint, content))
            return FakeResponse()

    transport = FakeTransport()
    with database.session() as db:
        first = dispatch_team_model(
            db,
            settings,
            request,
            messages,
            tools,
            "auto",
            ordinal=0,
            selected_binding_ids=selected_binding_ids,
            actor_context=None,
            transport=transport,
        )
    assert first.response.content == "A staged answer"
    assert len(transport.calls) == 1
    assert transport.calls[0][1] == expected_wire

    with database.session() as db:
        runtime.pause_team_turn(
            db,
            conversation_id=request.conversation_id,
            actor_id=actor_id,
            turn_id=turn_id,
        )
    with database.session() as db:
        resumed = runtime.resume_team_turn(
            db,
            settings,
            conversation_id=request.conversation_id,
            actor_id=actor_id,
            turn_id=turn_id,
        )
    replay_request = replace(request, claim_token=resumed.token)
    with database.session() as db:
        replayed = dispatch_team_model(
            db,
            settings,
            replay_request,
            messages,
            tools,
            "auto",
            ordinal=0,
            selected_binding_ids=selected_binding_ids,
            actor_context=None,
            transport=transport,
        )
    assert replayed.response.content == "A staged answer"
    assert replayed.call_id == first.call_id
    assert len(transport.calls) == 1
    with database.session() as db:
        stage = db.get(TeamProviderCall, first.call_id)
        assert stage is not None
        assert stage.request_json.encode("utf-8") == expected_wire
        assert stage.accepted_response_json == accepted_body.decode("utf-8")
        operation = db.get(ProviderOperation, stage.operation_id)
        assert operation is not None and operation.state == "succeeded"
