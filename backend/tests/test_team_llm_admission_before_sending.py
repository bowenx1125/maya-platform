"""A Team model call waits for its LLM slot before it marks the call "sending".

Audit item 4: the operation used to be written "sending" before the LLM
admission wait. A refusal was corrected back to not_sent, but a process that
died while queued left a "sending" row that recovery had to call unknown.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import Mock

import pytest
from agno.models.message import Message
from app.core.errors import PlatformError
from app.core.models import ProviderOperation
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
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
from sqlalchemy import select

from tests.test_mayaform_team_conversations import MAYA_ID
from tests.test_team_provider_disclosure import _prepared
from tests.test_wave4_provider_preflight import _digest, _policy


def _ready_request(client: TestClient, database: Any, settings: Any) -> tuple[Any, set[str]]:
    result_id, _original, _document_id, _set_id = _prepared(client, database, settings)
    settings.llm_provider = "dashscope"
    settings.dashscope_api_key = "synthetic-key"
    settings.dashscope_workspace_id = "synthetic-workspace"
    settings.dashscope_region = "cn-beijing"
    policy = _policy(
        policy_id="team-llm-admission-before-sending",
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
        assert row is not None and turn is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        participant = db.get(ConversationParticipant, result.participant_id)
        assert participant is not None
        participant_binding = {participant.team_member_id}
        turn_id = turn.id
        claim_token = turn.claim_token
    assert claim_token is not None
    request = runtime._start_member(
        database.session_factory, turn_id, claim_token, result_id, settings=settings
    )
    assert request is not None
    return request, participant_binding


def _states(database: Any) -> list[str]:
    with database.session() as db:
        return [
            op.state
            for op in db.scalars(
                select(ProviderOperation).where(
                    ProviderOperation.provider_operation == "llm_agent_chat"
                )
            )
        ]


def _dispatch(database: Any, settings: Any, request: Any, bindings: set[str]) -> None:
    with database.session() as db:
        dispatch_team_model(
            db,
            settings,
            request,
            [Message(role="user", content="synthetic current user")],
            [],
            None,
            ordinal=0,
            selected_binding_ids=bindings,
            actor_context=None,
        )


def _ok_transport() -> Mock:
    return Mock(
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


def test_admission_is_granted_before_the_call_is_marked_sending(
    client: TestClient, app_bundle: Any, monkeypatch: Any
) -> None:
    _app, database, settings = app_bundle
    request, bindings = _ready_request(client, database, settings)
    seen_at_admission: list[list[str]] = []
    held = {"now": False}

    @contextmanager
    def slot(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        seen_at_admission.append(_states(database))
        held["now"] = True
        try:
            yield
        finally:
            held["now"] = False

    transport = _ok_transport()

    def send(*args: Any, **kwargs: Any) -> Any:
        assert held["now"], "the model request must run inside the LLM slot"
        assert _states(database) == ["sending"]
        return transport(*args, **kwargs)

    monkeypatch.setattr("app.modules.workspace.chat_team_provider.llm_admission_slot", slot)
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", send
    )
    _dispatch(database, settings, request, bindings)

    assert seen_at_admission == [["reserved"]]
    assert transport.call_count == 1
    assert _states(database) == ["succeeded"]


def test_admission_refusal_leaves_the_call_not_sent_and_never_sending(
    client: TestClient, app_bundle: Any, monkeypatch: Any
) -> None:
    _app, database, settings = app_bundle
    request, bindings = _ready_request(client, database, settings)
    transitions: list[tuple[str, str]] = []
    original_transition = ProviderRepository.transition

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        transitions.append((str(kwargs.get("expected")), str(kwargs.get("state"))))
        return original_transition(self, operation_id, **kwargs)

    @contextmanager
    def busy(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})
        yield  # pragma: no cover

    transport = _ok_transport()
    monkeypatch.setattr(ProviderRepository, "transition", transition)
    monkeypatch.setattr("app.modules.workspace.chat_team_provider.llm_admission_slot", busy)
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", transport
    )
    with pytest.raises(PlatformError) as raised:
        _dispatch(database, settings, request, bindings)

    assert raised.value.code == "adaptive_admission_busy"
    assert transport.call_count == 0
    assert ("reserved", "sending") not in transitions
    assert _states(database) == ["not_sent"]


def test_failed_sending_transition_leaves_the_call_not_sent_and_frees_the_slot(
    client: TestClient, app_bundle: Any, monkeypatch: Any
) -> None:
    """#141: a transition error after the slot wait used to strand a "reserved" row."""

    from app.modules.workspace.chat_team_provider import TeamDispatchError

    _app, database, settings = app_bundle
    request, bindings = _ready_request(client, database, settings)
    original_transition = ProviderRepository.transition
    held = {"now": False}

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        if kwargs.get("expected") == "reserved" and kwargs.get("state") == "sending":
            raise RuntimeError("database went away")
        return original_transition(self, operation_id, **kwargs)

    @contextmanager
    def slot(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        held["now"] = True
        try:
            yield
        finally:
            held["now"] = False

    transport = _ok_transport()
    monkeypatch.setattr(ProviderRepository, "transition", transition)
    monkeypatch.setattr("app.modules.workspace.chat_team_provider.llm_admission_slot", slot)
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.HttpxLLMTransport.post_bytes", transport
    )
    with pytest.raises(TeamDispatchError):
        _dispatch(database, settings, request, bindings)

    assert transport.call_count == 0
    assert held["now"] is False
    assert _states(database) == ["not_sent"]
