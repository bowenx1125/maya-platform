import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    ProviderExportManifest,
    ProviderOperation,
    ProviderReservation,
    ProviderScopeBudget,
    User,
)
from app.modules.auth.service import AuthContext
from app.modules.debates.models import Debate, PlaybackState
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.interactions.service import ensure_closed_window
from app.modules.interactions.tokens import issue_token
from app.modules.knowledge.providers.query_embedding import QueryEmbeddingError
from app.modules.knowledge_sets.models import AgentKnowledgeSet, KnowledgeSet
from app.modules.knowledge_sets.schemas import SaveKnowledgeMarkdownRequest
from app.modules.knowledge_sets.service import get_agent_runtime_knowledge, save_brainform_markdown
from app.modules.workspace.chat import (
    _chat_sending_guard,
    _saved_chat_history,
    claim_chat_send,
    record_chat_failure,
    release_chat_request,
    store_assistant_text,
)
from app.modules.workspace.chat_provider import chat_messages
from app.modules.workspace.models import (
    ChatMemoryEntryAction,
    ChatProviderConsentBinding,
    ChatProviderStandingGrant,
    Conversation,
    ConversationTurn,
    LivePresence,
)
from app.modules.workspace.providers import settings_view
from app.providers.control_repository import ProviderRepository
from app.providers.llm_transport import LLMAcceptanceUnknown, LLMTransportNotSent
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, func, select

from tests.conftest import login, post_message
from tests.provider_confirm_helpers import chat_standing_disclosure, confirm_disclosure
from tests.test_mayaform_team_conversations import _make_agent_version
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy


@pytest.fixture
def workspace(app_bundle: Any, client: TestClient) -> tuple[Any, Any, TestClient]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, client


def _last_wire_payload(transport: Mock) -> dict[str, Any]:
    return json.loads(transport.call_args.kwargs["content"])


def test_chat_is_private_idempotent_and_preserves_multiturn_history(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    catalog = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents").json()
    assert any(item["version_id"] == BASELINE_VERSION_ID for item in catalog)
    assert (
        next(item for item in catalog if item["version_id"] == BASELINE_VERSION_ID)["version_label"]
        == "V1.0"
    )
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    )
    assert created.status_code == 200
    conversation_id = created.json()["id"]
    url = f"/api/v1/conversations/{conversation_id}"
    body = {"request_id": str(uuid4()), "expected_revision": 0, "message": "What is justice?"}
    first = post_message(client, f"{url}/messages", headers=headers, json=body)
    assert first.status_code == 200
    assert first.json()["turns"][0]["state"] == "ready"
    assert first.json()["turns"][0]["mode"] == "mock"
    assert (
        post_message(client, f"{url}/messages", headers=headers, json=body).json() == first.json()
    )
    assert (
        post_message(
            client, f"{url}/messages", headers=headers, json={**body, "message": "Changed"}
        ).status_code
        == 409
    )
    second = post_message(
        client,
        f"{url}/messages",
        headers=headers,
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Why?"},
    )
    assert second.status_code == 200
    assert len(second.json()["turns"]) == 2
    assert client.get(url).json() == second.json()
    assert len(client.get("/api/v1/conversations").json()) == 1
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/conversations").json() == []
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    url = f"/api/v1/conversations/{created['id']}"
    first = post_message(
        client,
        f"{url}/messages",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "What is justice?",
        },
    )
    assert first.status_code == 200
    _, teacher_csrf = login(client)
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/conversations").json() == []
    assert (
        post_message(
            client, f"{url}/messages", headers={"X-CSRF-Token": teacher_csrf}, json=body
        ).status_code
        == 404
    )
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_real_chat_keeps_decimal_budget_stable_across_messages(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "A considered reply"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    url = f"/api/v1/conversations/{created['id']}/messages"
    for revision in range(3):
        if revision == 2:
            _, csrf = login(client)
            headers = {"X-CSRF-Token": csrf}
            assert len(client.get(f"/api/v1/conversations/{created['id']}").json()["turns"]) == 2
        body = {
            "request_id": str(uuid4()),
            "expected_revision": revision,
            "message": "请用中文解释刚才的观点。" if revision == 2 else f"Question {revision}",
        }
        result = post_message(client, url, headers=headers, json=body)
        assert result.status_code == 200
        assert len(result.json()["turns"]) == revision + 1
        assert all(turn["state"] == "ready" for turn in result.json()["turns"])
        assert post_message(client, url, headers=headers, json=body).json() == result.json()
        assert transport.call_count == revision + 1
    sent_payload = _last_wire_payload(transport)
    assert [message["role"] for message in sent_payload["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert [message["content"] for message in sent_payload["messages"][1:]] == [
        "Question 0",
        "A considered reply",
        "Question 1",
        "A considered reply",
        "请用中文解释刚才的观点。",
    ]
    instruction = sent_payload["messages"][0]["content"]
    assert "final user message" in instruction
    assert "When that message is in Chinese, write the reply in Chinese" in instruction
    assert "takes priority over language preferences in agent_markdown" in instruction
    assert "including earlier assistant replies" in instruction
    assert "agent_markdown" in sent_payload["messages"][0]["content"]
    assert "max_tokens" not in sent_payload
    assert "response_format" not in sent_payload
    with database.session() as db:
        from app.modules.runtime_tools.models import RuntimeModelCallStage

        operations = list(
            db.scalars(select(ProviderOperation).where(ProviderOperation.scope_id == created["id"]))
        )
        assert len(operations) == 3
        assert all(operation.state == "succeeded" for operation in operations)
        stages = list(
            db.scalars(
                select(RuntimeModelCallStage)
                .where(
                    RuntimeModelCallStage.turn_id.in_(
                        [operation.logical_item_id for operation in operations]
                    )
                )
                .order_by(RuntimeModelCallStage.turn_id, RuntimeModelCallStage.ordinal)
            )
        )
        assert len(stages) == 3
        stages_by_request_hash = {stage.request_hash: stage for stage in stages}
        for call in transport.call_args_list:
            wire = call.kwargs["content"]
            stage = stages_by_request_hash[hashlib.sha256(wire).hexdigest()]
            assert stage.request_json.encode() == wire
            assert stage.accepted_response_json.encode() == transport.return_value.content
            assert hashlib.sha256(stage.request_json.encode()).hexdigest() == stage.request_hash
            assert stage.accepted_response_json is not None
            assert (
                hashlib.sha256(stage.accepted_response_json.encode()).hexdigest()
                == stage.accepted_response_hash
            )
            operation = db.get(ProviderOperation, stage.operation_id)
            assert operation is not None and operation.state == "succeeded"
            assert operation.staged_response_hash == stage.accepted_response_hash
            assert "max_tokens" not in json.loads(stage.request_json)


def test_static_course_chat_disclosure_creates_standing_grant_before_any_student_chat(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": False,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "A considered reply"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )

    reviewed = chat_standing_disclosure(
        database,
        TEACHER_ID,
        course_id=COURSE_ID,
        policy_hash=app.state.settings.provider_policy_hash_for("llm"),
    )
    disclosure_text = json.dumps(reviewed)
    assert reviewed["disclosure"]["outbound_field_classes"] == [
        "authorized_courseware_text",
        "private_conversation_messages",
        "teacher_agent_instructions",
        "topic_and_platform_rules",
    ]
    assert "Private" not in disclosure_text and "Student" not in disclosure_text
    with database.session() as db:
        static_manifest = db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == reviewed["manifest_hash"]
            )
        )
        assert static_manifest is not None
        assert static_manifest.scope_id == f"chat-course:{COURSE_ID}"
        assert static_manifest.agent_version_id is None
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        assert db.scalar(select(func.count()).select_from(ChatProviderStandingGrant)) == 0

    confirm_disclosure(
        database,
        TEACHER_ID,
        policy_hash=reviewed["policy_hash"],
        manifest_hash=reviewed["manifest_hash"],
        expected_revision=reviewed["confirmation_revision"],
    )
    with database.session() as db:
        grant = db.scalar(select(ChatProviderStandingGrant))
        assert grant is not None
        assert grant.course_id == COURSE_ID
        assert grant.policy_hash == policy.policy_hash
        assert grant.field_classes_json == (
            '["authorized_courseware_text","private_conversation_messages",'
            '"teacher_agent_instructions","topic_and_platform_rules"]'
        )
        assert db.scalar(select(func.count()).select_from(ChatProviderConsentBinding)) == 0
        assert db.scalar(select(func.count()).select_from(ChatProviderStandingGrant)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0

    _, student_csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": student_csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    sent = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": student_csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "A private student question",
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"][0]["state"] == "ready"
    assert transport.call_count == 1
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ChatProviderStandingGrant)) == 1
        assert db.scalar(select(func.count()).select_from(ChatProviderConsentBinding)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 1


@pytest.mark.parametrize("operator_consent", [False, True])
def test_operator_standing_consent_records_course_chat_grant_without_disclosure_screen(
    workspace: Any, monkeypatch: Any, operator_consent: bool
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_mode": False,
            "demo_auto_confirm_provider": False,
            "provider_standing_consent": operator_consent,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "A considered reply"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": None,
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )

    _, student_csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": student_csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    sent = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": student_csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "A private student question",
        },
    )

    with database.session() as db:
        grants = db.scalars(select(ChatProviderStandingGrant)).all()
        bindings = db.scalar(select(func.count()).select_from(ChatProviderConsentBinding))
        operations = db.scalar(select(func.count()).select_from(ProviderOperation))
    assert sent.status_code == 200, sent.text
    # PROVIDER_STANDING_CONSENT is a no-op: the turn auto-confirms and writes
    # the same standing grant, consent binding and Provider operation either way.
    assert sent.json()["turns"][0]["state"] == "ready"
    assert transport.call_count == 1
    assert [(grant.course_id, grant.confirmed_by_user_id) for grant in grants] == [
        (COURSE_ID, TEACHER_ID)
    ]
    assert (bindings, operations) == (1, 1)


def test_single_retrieval_uses_purpose_specific_embedding_grant(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    from app.core.models import Agent
    from app.modules.knowledge.providers.adapters import (
        DashScopeEmbeddingAdapter,
        DashScopeEmbeddingConfig,
    )
    from app.modules.workspace.chat_provider import retrieve_sources

    from tests.test_wave3_mock_rag_delta import GROUP_DEMO_ID, _insert_sql_published_agent
    from tests.test_wave4_query_standing_consent import _policy, _QueryTransport, _realise_snapshot

    agent_id = _insert_sql_published_agent(
        database,
        group_id=GROUP_DEMO_ID,
        name="Single Query Consent",
        evidence="A source that remains available to its published Agent.",
    )
    _realise_snapshot(database, agent_id)
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None and agent.current_published_version_id is not None
        version_id = agent.current_published_version_id

    config = DashScopeEmbeddingConfig(api_key="fixture-query-key", workspace_id="fixture")
    policy = _policy(config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "embedding_provider": "dashscope",
            "embedding_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-query-key",
            "dashscope_workspace_id": "fixture",
            "dashscope_region": "cn-beijing",
            "demo_auto_confirm_provider": False,
        }
    )
    transport = _QueryTransport()
    adapter = DashScopeEmbeddingAdapter(config, transport)
    monkeypatch.setattr("app.modules.workspace.chat_provider.embedding_provider", lambda _: adapter)

    reviewed = chat_standing_disclosure(
        database,
        TEACHER_ID,
        course_id=COURSE_ID,
        policy_hash=app.state.settings.provider_policy_hash_for("embedding"),
        provider_operation="embedding_query",
    )
    preview_text = json.dumps(reviewed)
    assert reviewed["disclosure"]["outbound_field_classes"] == ["current_evidence_excerpt"]
    assert "A source that remains available" not in preview_text
    confirm_disclosure(
        database,
        TEACHER_ID,
        policy_hash=reviewed["policy_hash"],
        manifest_hash=reviewed["manifest_hash"],
        expected_revision=reviewed["confirmation_revision"],
    )
    with database.session() as db:
        grant = db.scalar(
            select(ChatProviderStandingGrant).where(
                ChatProviderStandingGrant.provider_operation == "embedding_query"
            )
        )
        assert grant is not None and grant.policy_hash == policy.policy_hash
        assert grant.field_classes_json == '["current_evidence_excerpt"]'
        grant_id = grant.id

    student, student_csrf = login(client, "bowen")
    actor_user_id = str(student["user"]["id"])
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": student_csrf},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    conversation_id = str(created.json()["id"])
    request_id = str(uuid4())
    message = "My current retrieval question"
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        version = db.get(AgentVersion, version_id)
        assert conversation is not None and version is not None
        turn, is_new = claim_chat_send(
            db,
            conversation,
            request_id=request_id,
            expected_revision=0,
            message=message,
            settings=app.state.settings,
        )
        assert is_new and turn.id == request_id
        sources = retrieve_sources(
            db,
            app.state.settings,
            version,
            course_id=conversation.course_id,
            scope_id=conversation.id,
            request_id=request_id,
            message=message,
            actor_user_id=actor_user_id,
            turn_id=turn.id,
            claim_revision=1,
            sending_guard=_chat_sending_guard(
                conversation.id, turn.id, 1, actor_user_id=actor_user_id
            ),
        )
        assert sources

    assert len(transport.calls) == 1
    assert transport.calls[0]["input"]["texts"] == [message]  # type: ignore[index]
    encoded = json.dumps(transport.calls, ensure_ascii=False)
    assert "A source that remains available" not in encoded
    assert "teacher_agent_instructions" not in encoded
    assert "Classroom technology ethics expert" not in encoded
    with database.session() as db:
        binding = db.scalar(
            select(ChatProviderConsentBinding).where(
                ChatProviderConsentBinding.conversation_id == conversation_id
            )
        )
        assert binding is not None and binding.standing_grant_id == grant_id
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == conversation_id,
                ProviderOperation.provider_operation == "embedding_query",
            )
        )
        assert operation is not None and operation.state == "succeeded"
        manifest_hash = binding.manifest_hash

    from app.modules.provider_disclosure.service import single_chat_consent_is_current

    consent_args = {
        "manifest_hash": manifest_hash,
        "conversation_id": conversation_id,
        "actor_user_id": actor_user_id,
        "course_id": COURSE_ID,
        "policy_hash": policy.policy_hash,
        "field_classes": ("current_evidence_excerpt",),
        "provider_operation": "embedding_query",
    }
    with database.engine.connect() as connection:
        assert single_chat_consent_is_current(connection, **consent_args)
        assert not single_chat_consent_is_current(
            connection,
            **{
                **consent_args,
                "policy_hash": hashlib.sha256(b"different policy").hexdigest(),
            },
        )
        assert not single_chat_consent_is_current(
            connection, **{**consent_args, "provider_operation": "llm_agent_chat"}
        )
    with database.session() as db:
        membership = db.get(CourseMember, (COURSE_ID, actor_user_id))
        assert membership is not None
        db.delete(membership)
        db.commit()
    with database.engine.connect() as connection:
        assert not single_chat_consent_is_current(connection, **consent_args)
    with database.session() as db:
        revoked = db.get(ChatProviderStandingGrant, grant_id)
        assert revoked is not None
        revoked.revoked_at = datetime.now(UTC)
        db.commit()
    with database.engine.connect() as connection:
        assert not single_chat_consent_is_current(connection, **consent_args)


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "actor_inactive",
        "actor_course_removed",
        "source_hidden",
        "source_file_deleted",
        "agent_archived",
        "grant_revoked",
        "claim_superseded",
        "chat_withdrawn",
    ],
)
def test_single_llm_sending_guard_rechecks_live_owner_source_and_consent(
    mutation: str, workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    from app.core.models import Agent, KnowledgeDocument, StoredFile, User

    from tests.test_mayaform_team_conversations import BOWEN_ID, _make_agent_version
    from tests.test_mayaform_teams import _attach_personal_snapshot

    agent_id, version_id = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Independent private student"
    )
    document_id = _attach_personal_snapshot(database, version_id)
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.owner_user_id = BOWEN_ID

    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": False,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)

    disclosure = chat_standing_disclosure(
        database,
        TEACHER_ID,
        course_id=COURSE_ID,
        policy_hash=app.state.settings.provider_policy_hash_for("llm"),
    )
    confirm_disclosure(
        database,
        TEACHER_ID,
        policy_hash=disclosure["policy_hash"],
        manifest_hash=disclosure["manifest_hash"],
        expected_revision=disclosure["confirmation_revision"],
    )

    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    conversation_id = str(created.json()["id"])
    boundary_seen: list[str] = []
    original_transition = ProviderRepository.transition

    def transition(self: Any, operation_id: str, **kwargs: Any) -> Any:
        if kwargs.get("expected") == "reserved" and kwargs.get("state") == "sending":
            boundary_seen.append(operation_id)
            with database.session() as db:
                row = db.get(Conversation, conversation_id)
                assert row is not None
                if mutation == "actor_inactive":
                    actor = db.get(User, BOWEN_ID)
                    assert actor is not None
                    actor.status = "inactive"
                elif mutation == "actor_course_removed":
                    membership = db.get(CourseMember, (COURSE_ID, BOWEN_ID))
                    assert membership is not None
                    db.delete(membership)
                elif mutation == "source_hidden":
                    document = db.get(KnowledgeDocument, document_id)
                    assert document is not None
                    document.workspace_state = "hidden"
                elif mutation == "source_file_deleted":
                    document = db.get(KnowledgeDocument, document_id)
                    assert document is not None
                    source_file = db.get(StoredFile, document.stored_file_id)
                    assert source_file is not None
                    source_file.state = "deleted"
                elif mutation == "agent_archived":
                    agent = db.get(Agent, agent_id)
                    assert agent is not None
                    agent.status = "archived"
                elif mutation == "grant_revoked":
                    grant = db.scalar(
                        select(ChatProviderStandingGrant).where(
                            ChatProviderStandingGrant.provider_operation == "llm_agent_chat"
                        )
                    )
                    assert grant is not None
                    grant.revoked_at = datetime.now(UTC)
                elif mutation == "claim_superseded":
                    row.active_request_id = None
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
                        "message": {"role": "assistant", "content": "Synthetic private reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    response = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "current synthetic private user",
        },
    )
    # The send streams; the follow-up read reflects any access the actor lost.
    expected_status = {
        "actor_course_removed": 404,
        "chat_withdrawn": 404,
        "actor_inactive": 401,
    }.get(mutation, 200)
    assert response.status_code == expected_status, response.text
    assert len(boundary_seen) == 1
    with database.session() as db:
        operation = db.get(ProviderOperation, boundary_seen[0])
        assert operation is not None
        if mutation == "none":
            assert transport.call_count == 1
            assert operation.state == "succeeded"
            assert operation.charged_request_count == 1
        else:
            assert transport.call_count == 0
            assert operation.state == "not_sent"
            assert operation.charged_request_count == 0


def test_memory_entry_action_reuses_its_chat_and_request_identity_without_sending_implicitly(
    workspace: Any,
) -> None:
    app, database, client = workspace
    with database.session() as db:
        version = db.get(AgentVersion, BASELINE_VERSION_ID)
        assert version is not None
        agent_id = version.agent_id
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    action_id = str(uuid4())
    body = {
        "action_id": action_id,
        "course_id": COURSE_ID,
        "source": {"kind": "agent", "agent_id": agent_id},
    }
    first = client.post("/api/v1/conversations/memory-entry", headers=headers, json=body)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["message"] == "你目前记得我们之前聊过什么？"
    assert result["session"]["entry_kind"] == "agent"
    assert result["session"]["turns"] == []
    conversation_id = result["conversation_id"]
    request_id = result["request_id"]
    assert result["session"]["id"] == conversation_id
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ChatMemoryEntryAction)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.scope_id == conversation_id)
            )
            == 0
        )

    repeated = client.post("/api/v1/conversations/memory-entry", headers=headers, json=body)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["conversation_id"] == conversation_id
    assert repeated.json()["request_id"] == request_id
    assert repeated.json()["session"]["turns"] == []

    sent = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={
            "request_id": request_id,
            "expected_revision": result["session"]["revision"],
            "message": result["message"],
        },
    )
    assert sent.status_code == 200, sent.text
    assert len(sent.json()["turns"]) == 1
    repeated_after_send = client.post(
        "/api/v1/conversations/memory-entry", headers=headers, json=body
    )
    assert repeated_after_send.status_code == 200
    assert repeated_after_send.json()["request_id"] == request_id
    assert len(repeated_after_send.json()["session"]["turns"]) == 1
    changed_intent = client.post(
        "/api/v1/conversations/memory-entry",
        headers=headers,
        json={
            **body,
            "source": {"kind": "conversation", "id": conversation_id},
        },
    )
    assert changed_intent.status_code == 409
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ChatMemoryEntryAction)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
            )
            == 1
        )


def test_memory_entry_never_uses_a_teachers_read_only_view_of_a_students_public_chat(
    workspace: Any,
) -> None:
    _app, database, client = workspace
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    with database.session() as db:
        db.get(Conversation, created.json()["id"]).chat_visibility = "public"
    _, teacher_csrf = login(client)
    response = client.post(
        "/api/v1/conversations/memory-entry",
        headers={"X-CSRF-Token": teacher_csrf},
        json={
            "action_id": str(uuid4()),
            "course_id": COURSE_ID,
            "source": {"kind": "conversation", "id": created.json()["id"]},
        },
    )
    assert response.status_code == 404


def test_memory_entry_by_agent_opens_a_new_chat_instead_of_the_latest(
    workspace: Any,
) -> None:
    _app, database, client = workspace
    with database.session() as db:
        version = db.get(AgentVersion, BASELINE_VERSION_ID)
        assert version is not None
        agent_id = version.agent_id
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert created.status_code == 200, created.text
    action = client.post(
        "/api/v1/conversations/memory-entry",
        headers={"X-CSRF-Token": csrf},
        json={
            "action_id": str(uuid4()),
            "course_id": COURSE_ID,
            "source": {"kind": "agent", "agent_id": agent_id},
        },
    )
    assert action.status_code == 200, action.text
    assert action.json()["conversation_id"] != created.json()["id"]
    assert action.json()["message"] == "你目前记得我们之前聊过什么？"
    assert action.json()["session"]["turns"] == []


def test_memory_entry_stays_a_new_chat_when_an_assessment_is_active(
    workspace: Any,
) -> None:
    _app, _database, client = workspace
    with _database.session() as db:
        version = db.get(AgentVersion, BASELINE_VERSION_ID)
        assert version is not None
        agent_id = version.agent_id
    _, csrf = login(client, "bowen")
    response = client.post(
        "/api/v1/conversations/memory-entry",
        headers={"X-CSRF-Token": csrf},
        json={
            "action_id": str(uuid4()),
            "course_id": COURSE_ID,
            "source": {"kind": "agent", "agent_id": agent_id},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["message"] == "你目前记得我们之前聊过什么？"
    assert response.json()["session"]["turns"] == []


def test_real_chat_allows_educational_authorization_word(workspace: Any, monkeypatch: Any) -> None:
    """SiyaH Agent.md contains 'Authorization'; chat must not treat that as a secret leak."""
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])

    def messages_with_authorization(version: Any, history: Any, sources: Any, **kwargs: Any) -> Any:
        packed, fingerprint = chat_messages(version, history, sources, **kwargs)
        packed[0]["content"] = packed[0]["content"] + "\nAuthorization is a lesson topic."
        return packed, fingerprint

    monkeypatch.setattr("app.modules.workspace.chat.chat_messages", messages_with_authorization)
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Authorization is discussed in class.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    result = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "Explain Authorization",
        },
    )
    assert result.status_code == 200
    turn = result.json()["turns"][0]
    assert turn["state"] == "ready"
    assert turn["safe_error_code"] is None
    assert transport.call_count == 1
    assert "Authorization" in _last_wire_payload(transport)["messages"][0]["content"]


def test_single_chat_model_input_uses_current_canonical_knowledge_version(workspace: Any) -> None:
    _app, database, _client = workspace
    agent_id, agent_version_id = _make_agent_version(
        database,
        owner_id=TEACHER_ID,
        name="Single Chat canonical Knowledge",
    )
    version_one = "# Teacher notes\n\nMANUAL_NOTE_VERSION_ONE is now current.\n"
    version_two = "# Teacher notes\n\nMANUAL_NOTE_VERSION_TWO is now current.\n"
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None and agent.owner_user_id is not None
        owner_user_id = agent.owner_user_id
        owner = db.get(User, agent.owner_user_id)
        assert owner is not None
        context = AuthContext(
            raw_session_token="",
            session=None,
            user=owner,
            csrf_token="",
        )
        knowledge_set = KnowledgeSet(
            id=str(uuid4()),
            owner_user_id=owner.id,
            course_id=agent.course_id,
            group_id=None,
            ownership_scope="personal",
            visibility="private",
            display_name="Single Chat dynamic Knowledge",
            metadata_revision=0,
            content_revision=0,
            current_markdown_version_seq=0,
            generation_intent_seq=0,
            authorization_epoch=0,
            deleted_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(knowledge_set)
        db.flush()
        current_order = db.scalar(
            select(func.max(AgentKnowledgeSet.order_index)).where(
                AgentKnowledgeSet.agent_id == agent_id
            )
        )
        db.add(
            AgentKnowledgeSet(
                agent_id=agent_id,
                knowledge_set_id=knowledge_set.id,
                order_index=(current_order or -1) + 1,
                created_by_user_id=owner.id,
                created_at=datetime.now(UTC),
            )
        )
        save_brainform_markdown(
            db,
            context,
            knowledge_set.id,
            SaveKnowledgeMarkdownRequest(expected_version_seq=0, markdown=version_one),
        )
        db.commit()

    with database.session() as db:
        agent_version = db.get(AgentVersion, agent_version_id)
        assert agent_version is not None
        owner = db.get(User, owner_user_id)
        assert owner is not None
        context = AuthContext("", None, owner, "")
        history = [{"role": "user", "content": "Use the saved notes."}]
        knowledge_v1 = get_agent_runtime_knowledge(db, context, agent_id)
        messages_v1, _ = chat_messages(agent_version, history, [], canonical_knowledge=knowledge_v1)
        payload_v1 = json.loads(messages_v1[0]["content"].split("\n", 1)[1])
        assert payload_v1["canonical_knowledge"][0]["markdown"] == version_one
        assert len(payload_v1["canonical_knowledge"]) == 1
        db.commit()

    with database.session() as db:
        owner = db.get(User, owner_user_id)
        assert owner is not None
        context = AuthContext("", None, owner, "")
        save_brainform_markdown(
            db,
            context,
            knowledge_set.id,
            SaveKnowledgeMarkdownRequest(expected_version_seq=1, markdown=version_two),
        )
        db.commit()

    with database.session() as db:
        agent_version = db.get(AgentVersion, agent_version_id)
        owner = db.get(User, owner_user_id)
        assert agent_version is not None and owner is not None
        context = AuthContext("", None, owner, "")
        knowledge_v2 = get_agent_runtime_knowledge(db, context, agent_id)
        messages_v2, _ = chat_messages(
            agent_version,
            [{"role": "user", "content": "Use the saved notes."}],
            [],
            canonical_knowledge=knowledge_v2,
        )
        payload_v2 = json.loads(messages_v2[0]["content"].split("\n", 1)[1])
        serialized_markdown = payload_v2["canonical_knowledge"][0]["markdown"]
        assert serialized_markdown == version_two
        assert version_one not in serialized_markdown
        assert payload_v2["canonical_knowledge"][0]["canonical_set_id"] == knowledge_set.id


def test_single_agent_replays_tools_from_the_exact_accepted_model_stage(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    responses = [
        Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-read-session",
                                    "type": "function",
                                    "function": {
                                        "name": "read_session",
                                        "arguments": '{"arguments":{}}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ),
        Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I checked the saved session.",
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]
    transport = Mock(side_effect=responses)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    response = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "Please check my saved session.",
        },
    )
    assert response.status_code == 200, response.text
    turn = response.json()["turns"][0]
    assert turn["state"] == "ready"
    assert turn["assistant_text"] == "I checked the saved session."
    assert transport.call_count == 2
    with database.session() as db:
        from app.modules.runtime_tools.models import RuntimeModelCallStage, RuntimeToolReceipt

        stages = list(
            db.scalars(
                select(RuntimeModelCallStage)
                .where(RuntimeModelCallStage.turn_id == turn["id"])
                .order_by(RuntimeModelCallStage.ordinal)
            )
        )
        assert len(stages) == 2
        for stage, call, accepted in zip(stages, transport.call_args_list, responses, strict=True):
            assert stage.request_json.encode() == call.kwargs["content"]
            assert stage.accepted_response_json.encode() == accepted.content
        first_wire = json.loads(stages[0].request_json)
        assert any(
            tool.get("function", {}).get("name") == "read_session" for tool in first_wire["tools"]
        )
        assert (
            json.loads(stages[0].accepted_response_json)["choices"][0]["message"]["tool_calls"][0][
                "id"
            ]
            == "call-read-session"
        )
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(RuntimeToolReceipt.turn_id == turn["id"])
        )
        assert receipt is not None and receipt.tool_name == "read_session"


def test_single_not_sent_releases_reservation_and_a_new_request_can_continue(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        side_effect=[
            LLMTransportNotSent(),
            Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "The follow-up worked."},
                            "finish_reason": "stop",
                        }
                    ]
                },
            ),
        ]
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    failed_id = str(uuid4())
    failed = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": failed_id,
            "expected_revision": 0,
            "message": "First request was never sent.",
        },
    )
    assert failed.json()["turns"][0]["state"] == "failed"
    assert failed.json()["turns"][0]["safe_error_code"] == "chat_provider_not_sent"
    with database.session() as db:
        operation = db.scalar(
            select(ProviderOperation).where(ProviderOperation.logical_item_id == failed_id)
        )
        assert operation is not None
        assert operation.state == "not_sent"
        assert operation.request_count == operation.charged_request_count == 0
        reservation = db.scalar(
            select(ProviderReservation).where(ProviderReservation.operation_id == operation.id)
        )
        assert reservation is not None and reservation.state == "not_sent"
        budget = db.scalar(
            select(ProviderScopeBudget).where(
                ProviderScopeBudget.scope_id == created["id"],
                ProviderScopeBudget.budget_bucket == "llm_debate_turn",
            )
        )
        assert budget is not None and budget.allocated_requests == 0
    continued = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "message": "Continue with a new request.",
        },
    )
    assert continued.status_code == 200
    assert [turn["state"] for turn in continued.json()["turns"]] == ["failed", "ready"]
    assert transport.call_count == 2


def test_single_unknown_stage_is_not_resent_on_idempotent_replay(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(side_effect=LLMAcceptanceUnknown())
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    body = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "message": "Provider acceptance is uncertain.",
    }
    url = f"/api/v1/conversations/{created['id']}/messages"
    first = post_message(client, url, headers={"X-CSRF-Token": csrf}, json=body)
    assert first.json()["turns"][0]["state"] == "acceptance_unknown"
    replay = post_message(client, url, headers={"X-CSRF-Token": csrf}, json=body)
    assert replay.json() == first.json()
    assert transport.call_count == 1
    with database.session() as db:
        from app.modules.runtime_tools.models import RuntimeModelCallStage

        stage = db.scalar(
            select(RuntimeModelCallStage).where(RuntimeModelCallStage.turn_id == body["request_id"])
        )
        operation = db.scalar(
            select(ProviderOperation).where(ProviderOperation.logical_item_id == body["request_id"])
        )
        assert stage is not None and stage.accepted_response_json is None
        assert operation is not None and operation.state == "acceptance_unknown"


def test_single_resume_reuses_accepted_stage_and_new_revision_fences_old_worker(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    from app.modules.workspace import chat_provider as provider_module

    request_wires: list[bytes] = []
    original_canonical_json_bytes = provider_module.canonical_json_bytes

    def capture_canonical_json_bytes(value: Any) -> bytes:
        result = original_canonical_json_bytes(value)
        if isinstance(value, dict) and "messages" in value:
            request_wires.append(result)
        return result

    monkeypatch.setattr(provider_module, "canonical_json_bytes", capture_canonical_json_bytes)
    accepted_response = Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Accepted before restart."},
                    "finish_reason": "stop",
                }
            ]
        },
    )
    transport = Mock(return_value=accepted_response)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    request_id = str(uuid4())
    from app.modules.workspace import chat as chat_module

    original_store = chat_module.store_assistant_text

    def simulate_crash(*_args: Any, **_kwargs: Any) -> Any:
        raise PlatformError("chat_interrupted", "Synthetic accepted-stage interruption.", 503)

    monkeypatch.setattr(chat_module, "store_assistant_text", simulate_crash)
    original = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": request_id,
            "expected_revision": 0,
            "message": "Continue this saved turn.",
        },
    )
    assert original.json()["turns"][0]["state"] == "failed"
    assert transport.call_count == 1
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        turn = db.get(ConversationTurn, request_id)
        assert row is not None and turn is not None
        row.revision += 1
        row.active_request_id = None
        turn.state = "paused"
        turn.safe_error_code = "chat_recovery_available"
        db.commit()
    monkeypatch.setattr(chat_module, "store_assistant_text", original_store)

    paused_view = client.get(f"/api/v1/conversations/{created['id']}").json()
    assert paused_view["can_send"] is True
    new_message = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "message": "Keep the paused turn and answer this new question.",
        },
    )
    assert new_message.status_code == 200, new_message.text
    assert new_message.json()["turns"][-1]["user_text"] == (
        "Keep the paused turn and answer this new question."
    )
    assert transport.call_count == 2

    resumed = client.post(
        f"/api/v1/conversations/{created['id']}/turns/{request_id}:resume",
        headers={"X-CSRF-Token": csrf},
    )
    assert resumed.status_code == 200, resumed.text
    saved = next(turn for turn in resumed.json()["turns"] if turn["id"] == request_id)
    assert saved["id"] == request_id
    assert saved["state"] == "ready"
    assert request_wires[0] == request_wires[2]
    assert saved["assistant_text"] == "Accepted before restart."
    assert transport.call_count == 2
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        turn = db.get(ConversationTurn, request_id)
        assert row is not None and turn is not None
        assert row.revision == 4
        assert turn.position == 1
        newer_turn = db.scalar(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == row.id, ConversationTurn.id != turn.id
            )
        )
        assert newer_turn is not None and newer_turn.position == 3
        assert row.active_request_id is None
        with pytest.raises(PlatformError) as stale:
            store_assistant_text(
                db,
                row.id,
                turn.id,
                1,
                "Stale old worker result.",
                [],
                None,
            )
        assert stale.value.code == "chat_request_stale"


def test_single_resume_retries_only_a_proven_not_sent_followup_stage(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    responses = [
        Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-read-before-not-sent",
                                    "type": "function",
                                    "function": {
                                        "name": "read_session",
                                        "arguments": '{"arguments":{}}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ),
        LLMTransportNotSent(),
        Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "The safely resumed call completed.",
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        ),
    ]
    transport = Mock(side_effect=responses)
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    turn_id = str(uuid4())
    from app.modules.workspace import chat as chat_module

    original_store = chat_module.store_assistant_text
    monkeypatch.setattr(
        chat_module,
        "store_assistant_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlatformError("chat_interrupted", "Synthetic recovery point.", 503)
        ),
    )
    failed = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": turn_id,
            "expected_revision": 0,
            "message": "Replay the accepted read, then retry only what was not sent.",
        },
    )
    assert failed.json()["turns"][0]["state"] == "failed"
    assert failed.json()["turns"][0]["safe_error_code"] == "chat_provider_not_sent"
    assert transport.call_count == 2
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        turn = db.get(ConversationTurn, turn_id)
        assert row is not None and turn is not None
        # Recreate the durable state left by a process crash after the first
        # accepted response and a later transport proved it sent no bytes.
        recovered_revision = row.revision + 1
        row.active_request_id = turn.id
        turn.state = "pending"
        turn.safe_error_code = None
        db.commit()
        from app.modules.runtime_tools.recovery import recover_single_chat_runs

        recover_single_chat_runs(db)
        assert row.active_request_id is None
        assert row.revision == recovered_revision
        assert turn.state == "paused"
        assert turn.safe_error_code == "chat_recovery_available"
    monkeypatch.setattr(chat_module, "store_assistant_text", original_store)

    resumed = client.post(
        f"/api/v1/conversations/{created['id']}/turns/{turn_id}:resume",
        headers={"X-CSRF-Token": csrf},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["turns"][0]["assistant_text"] == "The safely resumed call completed."
    assert transport.call_count == 3
    with database.session() as db:
        from app.modules.runtime_tools.models import RuntimeModelCallStage

        stages = list(
            db.scalars(
                select(RuntimeModelCallStage)
                .where(RuntimeModelCallStage.turn_id == turn_id)
                .order_by(RuntimeModelCallStage.ordinal)
            )
        )
        assert [(stage.ordinal, stage.dispatch_ordinal) for stage in stages] == [
            (0, 0),
            (1, 1),
            (2, 1),
        ]
        assert stages[1].accepted_response_json is None
        assert stages[1].request_json == stages[2].request_json
        old_not_sent = db.get(ProviderOperation, stages[1].operation_id)
        retry = db.get(ProviderOperation, stages[2].operation_id)
        assert old_not_sent is not None and old_not_sent.state == "not_sent"
        assert retry is not None and retry.state == "succeeded"


def test_single_pause_advances_revision_and_fences_old_reply(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    real_settings = app.state.settings.model_copy(update={"llm_provider": "dashscope"})
    app.state.settings = real_settings
    request_id = str(uuid4())
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        turn, is_new = claim_chat_send(
            db,
            row,
            request_id=request_id,
            expected_revision=0,
            message="Pause this pending turn.",
            settings=real_settings,
        )
        assert is_new and turn.state == "pending"
    paused = client.post(
        f"/api/v1/conversations/{created['id']}/turns/{request_id}:pause",
        headers={"X-CSRF-Token": csrf},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["can_send"] is True
    assert paused.json()["revision"] == 2
    assert paused.json()["turns"][0]["state"] == "paused"
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        turn = db.get(ConversationTurn, request_id)
        assert row is not None and turn is not None
        assert row.active_request_id is None
        assert row.revision == 2
        assert turn.position == 1
        with pytest.raises(PlatformError) as stale:
            store_assistant_text(
                db,
                row.id,
                turn.id,
                1,
                "Old worker reply.",
                [],
                None,
            )
        assert stale.value.code == "chat_request_stale"


def test_chat_rejects_stale_revision_csrf_revoked_membership_and_unknown_outcome(
    workspace: Any,
) -> None:
    _, database, client = workspace
    payload, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    url = f"/api/v1/conversations/{created['id']}"
    body = {"request_id": str(uuid4()), "expected_revision": 10, "message": "Hello"}
    assert post_message(client, f"{url}/messages", headers=headers, json=body).status_code == 409
    assert post_message(client, f"{url}/messages", json=body).status_code == 403
    with database.session() as db:
        db.add(
            ConversationTurn(
                id=str(uuid4()),
                conversation_id=created["id"],
                position=1,
                user_text="Hello",
                assistant_text=None,
                sources_json="[]",
                mode="real",
                state="acceptance_unknown",
                created_at=datetime.now(UTC),
            )
        )
        row = db.get(Conversation, created["id"])
        row.revision = 1
    recovered = post_message(
        client,
        f"{url}/messages",
        headers=headers,
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Try again"},
    )
    assert recovered.status_code == 200
    assert [turn["state"] for turn in recovered.json()["turns"]] == [
        "acceptance_unknown",
        "ready",
    ]
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        db.execute(delete(CourseMember).where(CourseMember.user_id == row.user_id))
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/conversations").json() == []


@pytest.mark.parametrize(
    "provider_operation,logical_item,state,expected_state",
    [
        ("llm_agent_chat", "current", "acceptance_unknown", "acceptance_unknown"),
        ("embedding_query", "chat:current", "sending", "acceptance_unknown"),
        ("llm_agent_chat", "previous", "acceptance_unknown", "failed"),
        ("llm_agent_chat", "chat:current", "acceptance_unknown", "failed"),
        ("embedding_query", "current", "sending", "failed"),
        ("tts", "current", "acceptance_unknown", "failed"),
        ("llm_agent_chat", "current", "accepted", "failed"),
    ],
)
def test_chat_unknown_inference_is_scoped_to_the_current_provider_operation(
    workspace: Any,
    provider_operation: str,
    logical_item: str,
    state: str,
    expected_state: str,
) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    request_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        turn, is_new = claim_chat_send(
            db,
            conversation,
            request_id=request_id,
            expected_revision=0,
            message="Current request",
            settings=app.state.settings,
        )
        assert is_new
        now = datetime.now(UTC)
        db.add(
            ProviderOperation(
                id=str(uuid4()),
                scope_id=conversation.id,
                provider_operation=provider_operation,
                logical_item_id=(
                    request_id
                    if logical_item == "current"
                    else f"chat:{request_id}"
                    if logical_item == "chat:current"
                    else logical_item
                ),
                attempt_no=1,
                request_hash="a" * 64,
                max_tokens=100,
                max_cost_cny=0,
                policy_hash="b" * 64,
                export_manifest_hash="c" * 64,
                build_manifest_hash="d" * 64,
                model_key="test-model",
                state=state,
                request_count=1,
                charged_request_count=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        claim_revision = turn.position
        record_chat_failure(
            db,
            conversation.id,
            request_id,
            claim_revision,
            RuntimeError("local validation failed"),
        )
        release_chat_request(db, conversation.id, request_id, claim_revision)
        db.commit()
        db.expire_all()
        saved = db.get(ConversationTurn, request_id)
        assert saved is not None and saved.state == expected_state


def test_chat_unknown_replay_is_free_and_followup_receives_complete_saved_history(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "A considered reply"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    from app.modules.workspace import chat as chat_module

    original_generate = chat_module.generate_reply
    generated: list[str] = []

    def fail_first(
        db: Any,
        settings: Any,
        row: Any,
        request_id: str,
        claim_revision: int,
        message: str,
        **kwargs: Any,
    ) -> Any:
        generated.append(message)
        if message == "uncertain original":
            raise PlatformError("chat_acceptance_unknown", "The outcome is unknown.", 503)
        return original_generate(db, settings, row, request_id, claim_revision, message, **kwargs)

    monkeypatch.setattr(chat_module, "generate_reply", fail_first)
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    url = f"/api/v1/conversations/{created['id']}"
    earlier = post_message(
        client,
        f"{url}/messages",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "Earlier successful question",
        },
    )
    assert earlier.status_code == 200
    assert earlier.json()["turns"][0]["state"] == "ready"
    assert generated == ["Earlier successful question"]
    first_body = {
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "message": "uncertain original",
    }
    first = post_message(client, f"{url}/messages", headers=headers, json=first_body)
    assert first.status_code == 200
    assert first.json()["turns"][1]["state"] == "acceptance_unknown"
    assert first.json()["turns"][1]["user_text"] == "uncertain original"
    replay = post_message(client, f"{url}/messages", headers=headers, json=first_body)
    assert replay.json() == first.json()
    assert generated == ["Earlier successful question", "uncertain original"]
    second = post_message(
        client,
        f"{url}/messages",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 2,
            "message": "Follow up after uncertainty",
        },
    )
    assert second.status_code == 200
    assert [turn["state"] for turn in second.json()["turns"]] == [
        "ready",
        "acceptance_unknown",
        "ready",
    ]
    assert transport.call_count == 2
    sent_messages = _last_wire_payload(transport)["messages"]
    assert [message["role"] for message in sent_messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "system",
        "user",
    ]
    assert sent_messages[1]["content"] == "Earlier successful question"
    assert sent_messages[2]["content"] == "A considered reply"
    assert sent_messages[3]["content"] == "uncertain original"
    assert "acceptance_unknown" in sent_messages[4]["content"]
    assert "No assistant reply was saved" in sent_messages[4]["content"]
    assert sent_messages[5]["content"] == "Follow up after uncertainty"
    assert generated == [
        "Earlier successful question",
        "uncertain original",
        "Follow up after uncertainty",
    ]


def test_chat_stale_embedding_dispatch_is_refunded_before_provider_call(
    workspace: Any, tmp_path: Any
) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    old_request_id = str(uuid4())
    new_request_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        old_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=old_request_id,
            expected_revision=0,
            message="Old embedding query",
            settings=app.state.settings,
        )
        old_revision = old_turn.position
        record_chat_failure(
            db,
            conversation.id,
            old_request_id,
            old_revision,
            RuntimeError("client disconnected before Embedding dispatch"),
        )
        release_chat_request(db, conversation.id, old_request_id, old_revision)
        db.commit()
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        new_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=new_request_id,
            expected_revision=1,
            message="Current message",
            settings=app.state.settings,
        )
        assert new_turn.position == 2
        snapshot_id = conversation.snapshot_id

    from tests.test_wave4_embedding_sql_query import _fixture as embedding_fixture
    from tests.test_wave4_embedding_sql_query import _snapshot as embedding_snapshot

    _db, repository, control, service, provider, stage = embedding_fixture(
        tmp_path,
        database=database,
        scope_id=created["id"],
        logical_item_id=f"chat:{old_request_id}",
        snapshot_id=snapshot_id,
        sending_guard=_chat_sending_guard(created["id"], old_request_id, old_revision),
    )
    with pytest.raises(QueryEmbeddingError) as rejected:
        service.embed_subqueries(embedding_snapshot(snapshot_id), ("alpha", "beta"))
    assert getattr(rejected.value, "code", None) == "chat_request_stale"
    assert provider.calls == []
    assert stage.values == {}
    operation = repository.operations(scope_id=created["id"])[0]
    assert operation.state == "not_sent"
    assert operation.request_count == 0
    assert operation.charged_request_count == 0
    with database.session() as db:
        saved_conversation = db.get(Conversation, created["id"])
        assert saved_conversation is not None
        assert saved_conversation.active_request_id == new_request_id
        assert saved_conversation.revision == 2


def test_chat_history_reads_legacy_one_based_ready_and_unknown_turns(workspace: Any) -> None:
    _, database, client = workspace
    _, csrf = login(client)
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        conversation.revision = 2
        db.add_all(
            [
                ConversationTurn(
                    id=str(uuid4()),
                    conversation_id=conversation.id,
                    position=1,
                    user_text="Legacy successful user turn",
                    assistant_text="Legacy saved assistant answer",
                    sources_json="[]",
                    mode="mock",
                    state="ready",
                    created_at=datetime.now(UTC),
                ),
                ConversationTurn(
                    id=str(uuid4()),
                    conversation_id=conversation.id,
                    position=2,
                    user_text="Legacy uncertain user turn",
                    assistant_text=None,
                    sources_json="[]",
                    mode="real",
                    state="acceptance_unknown",
                    safe_error_code="chat_acceptance_unknown",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()
        history = _saved_chat_history(db, conversation.id, before_position=3)
    assert [message["role"] for message in history] == [
        "user",
        "assistant",
        "user",
        "system",
    ]
    assert history[0]["content"] == "Legacy successful user turn"
    assert history[1]["content"] == "Legacy saved assistant answer"
    assert history[2]["content"] == "Legacy uncertain user turn"
    assert "acceptance_unknown" in history[3]["content"]


@pytest.mark.parametrize(
    "usage_case,usage_value",
    [
        ("missing", "missing"),
        ("null", None),
        ("malformed", "not-an-object"),
        ("negative", {"prompt_tokens": -2, "completion_tokens": 3}),
        ("partial", {"prompt_tokens": 4}),
    ],
)
def test_chat_usage_metadata_never_gates_a_valid_reply(
    workspace: Any, monkeypatch: Any, usage_case: str, usage_value: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    provider_payload: dict[str, Any] = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "Accepted content"},
                "finish_reason": "stop",
            }
        ]
    }
    if usage_case != "missing":
        provider_payload["usage"] = usage_value
    transport = Mock(return_value=Response(200, json=provider_payload))
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    request_id = str(uuid4())
    response = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers=headers,
        json={
            "request_id": request_id,
            "expected_revision": 0,
            "message": f"Question with {usage_case} usage",
        },
    )
    assert response.status_code == 200
    assert response.json()["turns"][0]["state"] == "ready"
    assert response.json()["turns"][0]["assistant_text"] == "Accepted content"
    assert transport.call_count == 1
    with database.session() as db:
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == created["id"],
                ProviderOperation.logical_item_id == request_id,
            )
        )
        assert operation is not None
        assert operation.charged_request_count == 1
        assert operation.state == "succeeded"


@pytest.mark.parametrize(
    "content,finish_reason",
    [("", "stop"), ("Unfinished", "length")],
)
def test_chat_invalid_content_stays_failed_even_after_http_200(
    workspace: Any, monkeypatch: Any, content: str, finish_reason: str
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": None,
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    request_id = str(uuid4())
    response = post_message(
        client,
        f"/api/v1/conversations/{created['id']}/messages",
        headers=headers,
        json={"request_id": request_id, "expected_revision": 0, "message": "Check content"},
    )
    assert response.status_code == 200
    turn = response.json()["turns"][0]
    assert turn["state"] == "failed"
    assert turn["safe_error_code"] == "chat_response_invalid"
    assert turn["assistant_text"] is None
    with database.session() as db:
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == created["id"],
                ProviderOperation.logical_item_id == request_id,
            )
        )
        assert operation is not None
        assert operation.charged_request_count == 1
        assert operation.state == "failed"


def test_chat_late_result_and_failure_cannot_change_a_later_claim(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    old_request = str(uuid4())
    new_request = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        old_turn, created_old = claim_chat_send(
            db,
            conversation,
            request_id=old_request,
            expected_revision=0,
            message="Older delayed request",
            settings=app.state.settings,
        )
        assert created_old
        old_revision = old_turn.position
        record_chat_failure(
            db,
            conversation.id,
            old_request,
            old_revision,
            RuntimeError("request worker disconnected"),
        )
        release_chat_request(db, conversation.id, old_request, old_revision)
        db.commit()

        current_turn, created_current = claim_chat_send(
            db,
            conversation,
            request_id=new_request,
            expected_revision=1,
            message="New current request",
            settings=app.state.settings,
        )
        assert created_current
        current_revision = current_turn.position
        from app.modules.workspace.chat import generate_reply

        with pytest.raises(PlatformError) as stale_generation:
            generate_reply(
                db,
                app.state.settings,
                conversation,
                old_request,
                old_revision,
                "Older delayed request",
            )
        assert stale_generation.value.code == "chat_request_stale"
        with pytest.raises(PlatformError) as stale_store:
            store_assistant_text(
                db,
                conversation.id,
                old_request,
                old_revision,
                "Late assistant result",
                [],
                None,
            )
        assert stale_store.value.code == "chat_request_stale"
        db.rollback()
        record_chat_failure(
            db,
            conversation.id,
            old_request,
            old_revision,
            RuntimeError("late worker error"),
        )
        release_chat_request(db, conversation.id, old_request, old_revision)
        db.commit()
        db.expire_all()
        active = db.get(Conversation, conversation.id)
        assert active is not None
        assert active.active_request_id == new_request
        assert active.revision == current_revision
        old_saved = db.get(ConversationTurn, old_request)
        assert old_saved is not None and old_saved.state == "failed"
        store_assistant_text(
            db,
            conversation.id,
            new_request,
            current_revision,
            "Current assistant result",
            [],
            None,
        )
        release_chat_request(db, conversation.id, new_request, current_revision)
        db.commit()
        db.expire_all()
        current_saved = db.get(ConversationTurn, new_request)
        active = db.get(Conversation, conversation.id)
        assert current_saved is not None and current_saved.state == "ready"
        assert current_saved.assistant_text == "Current assistant result"
        assert active is not None and active.active_request_id is None


@pytest.mark.asyncio
async def test_chat_sse_releases_claim_before_terminal_events(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    failure_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        failure_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=failure_id,
            expected_revision=0,
            message="Terminal failure",
            settings=app.state.settings,
        )
        failure_revision = failure_turn.position

    def stub_reply(
        _database: Any,
        _settings: Any,
        _conversation_id: str,
        _request_id: str,
        _claim_revision: int,
        message: str,
        _actor_context: Any | None = None,
        _generation_waker: Any | None = None,
        _write_slot: Any | None = None,
    ) -> tuple[str, list[Any], None]:
        if message == "Terminal failure":
            raise PlatformError("chat_acceptance_unknown", "Unknown outcome.", 503)
        return "One committed reply", [], None

    monkeypatch.setattr("app.modules.workspace.chat_stream._reply_segment", stub_reply)
    from app.modules.workspace.chat_stream import stream_events

    failure_events = stream_events(
        database,
        app.state.settings,
        conversation_id=created["id"],
        created=True,
        message="Terminal failure",
        request_id=failure_id,
        claim_revision=failure_revision,
    )
    error_event = await anext(failure_events)
    assert b"event: error" in error_event
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        assert conversation is not None and conversation.active_request_id is None
    await failure_events.aclose()

    success_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        success_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=success_id,
            expected_revision=1,
            message="Terminal success",
            settings=app.state.settings,
        )
        success_revision = success_turn.position
    success_events = stream_events(
        database,
        app.state.settings,
        conversation_id=created["id"],
        created=True,
        message="Terminal success",
        request_id=success_id,
        claim_revision=success_revision,
    )
    delta_event = await anext(success_events)
    assert b"event: delta" in delta_event
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        assert conversation is not None and conversation.active_request_id == success_id
    text_done = await anext(success_events)
    assert b"event: text_done" in text_done
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        assert conversation is not None and conversation.active_request_id is None
    await success_events.aclose()


@pytest.mark.asyncio
async def test_chat_stream_disconnect_settles_request_before_worker_finishes(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    request_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        turn, is_new = claim_chat_send(
            db,
            conversation,
            request_id=request_id,
            expected_revision=0,
            message="A request whose client disconnected",
            settings=app.state.settings,
        )
        assert is_new
        claim_revision = turn.position

    worker_started = threading.Event()
    allow_worker_to_finish = threading.Event()
    worker_finished = threading.Event()

    def delayed_reply(*args: Any, **kwargs: Any) -> tuple[str, list[Any], None]:
        worker_started.set()
        allow_worker_to_finish.wait(timeout=5)
        worker_finished.set()
        return "late reply must not be published", [], None

    monkeypatch.setattr("app.modules.workspace.chat_stream._reply_segment", delayed_reply)
    from app.modules.workspace.chat_stream import stream_events

    events = stream_events(
        database,
        app.state.settings,
        conversation_id=created["id"],
        created=True,
        message="A request whose client disconnected",
        request_id=request_id,
        claim_revision=claim_revision,
    )
    next_event = asyncio.create_task(anext(events))
    assert await asyncio.to_thread(worker_started.wait, 2)
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event
    assert not worker_finished.is_set()
    allow_worker_to_finish.set()
    assert await asyncio.to_thread(worker_finished.wait, 2)
    await asyncio.sleep(0)
    with database.session() as db:
        saved = db.get(ConversationTurn, request_id)
        conversation = db.get(Conversation, created["id"])
        assert saved is not None
        assert saved.state == "failed"
        assert saved.safe_error_code == "chat_interrupted"
        assert saved.assistant_text is None
        assert conversation is not None
        assert conversation.active_request_id is None
        assert conversation.revision == claim_revision


@pytest.mark.asyncio
async def test_chat_cancelled_llm_dispatch_is_rejected_before_ledger_charge(
    workspace: Any, monkeypatch: Any
) -> None:
    app, database, client = workspace
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = app.state.settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "demo_auto_confirm_provider": True,
        }
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.llm_provider", lambda _: adapter)
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *a, **kw: [])
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Should never be dispatched",
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    from app.modules.workspace import chat_provider, chat_stream

    entered_preflight = threading.Event()
    resume_worker = threading.Event()
    worker_finished = threading.Event()
    original_confirm = chat_provider.confirm_manifest

    def pause_after_confirm(*args: Any, **kwargs: Any) -> None:
        original_confirm(*args, **kwargs)
        entered_preflight.set()
        assert resume_worker.wait(timeout=5)

    monkeypatch.setattr(chat_provider, "confirm_manifest", pause_after_confirm)
    original_reply = chat_stream._reply_segment

    def track_reply(*args: Any, **kwargs: Any) -> Any:
        try:
            return original_reply(*args, **kwargs)
        finally:
            worker_finished.set()

    monkeypatch.setattr(chat_stream, "_reply_segment", track_reply)
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    old_request_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        old_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=old_request_id,
            expected_revision=0,
            message="Old LLM request",
            settings=app.state.settings,
        )
        old_revision = old_turn.position
    events = chat_stream.stream_events(
        database,
        app.state.settings,
        conversation_id=created["id"],
        created=True,
        message="Old LLM request",
        request_id=old_request_id,
        claim_revision=old_revision,
    )
    worker = asyncio.create_task(anext(events))
    assert await asyncio.to_thread(entered_preflight.wait, 2)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker

    new_request_id = str(uuid4())
    with database.session() as db:
        old_turn = db.get(ConversationTurn, old_request_id)
        conversation = db.get(Conversation, created["id"])
        assert old_turn is not None
        assert old_turn.state == "failed"
        assert old_turn.safe_error_code == "chat_interrupted"
        assert conversation is not None and conversation.active_request_id is None
        new_turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=new_request_id,
            expected_revision=1,
            message="New current request",
            settings=app.state.settings,
        )
        assert new_turn.position == 2

    resume_worker.set()
    assert await asyncio.to_thread(worker_finished.wait, 2)
    assert transport.call_count == 0
    with database.session() as db:
        old_operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == created["id"],
                ProviderOperation.logical_item_id == old_request_id,
            )
        )
        conversation = db.get(Conversation, created["id"])
        # Cancellation happened after disclosure preflight but before the exact
        # request was bound, so no Provider operation or charge exists.
        assert old_operation is None
        assert conversation is not None
        assert conversation.active_request_id == new_request_id
        assert conversation.revision == 2


def test_chat_sse_unknown_then_new_request_succeeds(workspace: Any, monkeypatch: Any) -> None:
    _, _, client = workspace
    from app.modules.workspace import chat as chat_module

    original_generate = chat_module.generate_reply
    generated: list[str] = []

    def fail_first(
        db: Any,
        settings: Any,
        row: Any,
        request_id: str,
        claim_revision: int,
        message: str,
        **kwargs: Any,
    ) -> Any:
        generated.append(message)
        if message == "SSE uncertain original":
            raise PlatformError("chat_acceptance_unknown", "The outcome is unknown.", 503)
        return original_generate(db, settings, row, request_id, claim_revision, message, **kwargs)

    monkeypatch.setattr(chat_module, "generate_reply", fail_first)
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf, "Accept": "text/event-stream"}
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    url = f"/api/v1/conversations/{created['id']}"
    first_body = {
        "request_id": str(uuid4()),
        "expected_revision": 0,
        "message": "SSE uncertain original",
    }
    first = client.post(f"{url}/messages:stream", headers=headers, json=first_body)
    assert "event: error" in first.text
    assert "chat_acceptance_unknown" in first.text
    assert "event: delta" not in first.text
    replay = client.post(f"{url}/messages:stream", headers=headers, json=first_body)
    assert "event: error" in replay.text
    assert generated == ["SSE uncertain original"]
    second = client.post(
        f"{url}/messages:stream",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "message": "A distinct SSE follow-up",
        },
    )
    assert second.status_code == 200
    assert "event: delta" in second.text
    assert "event: text_done" in second.text
    session = client.get(url).json()
    assert [turn["state"] for turn in session["turns"]] == ["acceptance_unknown", "ready"]
    assert [turn["user_text"] for turn in session["turns"]] == [
        "SSE uncertain original",
        "A distinct SSE follow-up",
    ]
    assert generated == ["SSE uncertain original", "A distinct SSE follow-up"]


def test_chat_pending_id_replay_reports_pending_without_releasing_claim(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    request_id = str(uuid4())
    body = {
        "request_id": request_id,
        "expected_revision": 0,
        "message": "Still generating",
    }
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        claim_chat_send(
            db,
            conversation,
            request_id=request_id,
            expected_revision=0,
            message=body["message"],
            settings=app.state.settings,
        )
    response = client.post(
        f"/api/v1/conversations/{created['id']}/messages:stream",
        headers={"X-CSRF-Token": csrf, "Accept": "text/event-stream"},
        json=body,
    )
    assert response.status_code == 200
    assert "event: pending" in response.text
    assert "event: error" not in response.text
    with database.session() as db:
        turn = db.get(ConversationTurn, request_id)
        conversation = db.get(Conversation, created["id"])
        assert turn is not None and turn.state == "pending"
        assert conversation is not None
        assert conversation.active_request_id == request_id


def test_chat_ready_replay_releases_only_its_own_claim(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client, "bowen")
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": BASELINE_VERSION_ID},
    ).json()
    url = f"/api/v1/conversations/{created['id']}/messages:stream"
    headers = {"X-CSRF-Token": csrf, "Accept": "text/event-stream"}
    replay_id = str(uuid4())
    replay_body = {
        "request_id": replay_id,
        "expected_revision": 0,
        "message": "Saved reply awaiting stream replay",
    }
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        turn, _ = claim_chat_send(
            db,
            conversation,
            request_id=replay_id,
            expected_revision=0,
            message=replay_body["message"],
            settings=app.state.settings,
        )
        store_assistant_text(
            db,
            conversation.id,
            replay_id,
            turn.position,
            "Already saved reply",
            [],
            None,
        )
    first_replay = client.post(url, headers=headers, json=replay_body)
    assert "event: text_done" in first_replay.text
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        assert conversation is not None and conversation.active_request_id is None

    next_id = str(uuid4())
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        claim_chat_send(
            db,
            conversation,
            request_id=next_id,
            expected_revision=1,
            message="New request remains active",
            settings=app.state.settings,
        )
    old_replay = client.post(url, headers=headers, json=replay_body)
    assert "event: text_done" in old_replay.text
    with database.session() as db:
        conversation = db.get(Conversation, created["id"])
        assert conversation is not None
        assert conversation.active_request_id == next_id
        assert conversation.revision == 2


def test_chat_failure_is_safe_and_does_not_retry(
    workspace: Any, monkeypatch: Any, caplog: Any
) -> None:
    app, _, client = workspace
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    app.state.settings = app.state.settings.model_copy(update={"llm_provider": "dashscope"})
    calls = []

    def fail(*args: Any, **kwargs: Any) -> None:
        calls.append(1)
        raise RuntimeError("private-provider-body secret credential")

    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", fail)
    body = {"request_id": str(uuid4()), "expected_revision": 0, "message": "Private learner text"}
    url = f"/api/v1/conversations/{created['id']}/messages"
    result = post_message(client, url, headers=headers, json=body)
    assert result.json()["turns"][0]["safe_error_code"] == "chat_failed"
    assert post_message(client, url, headers=headers, json=body).status_code == 200
    assert len(calls) == 1
    assert "chat_failed" in caplog.text
    assert "private-provider-body" not in caplog.text + result.text
    assert "Private learner text" not in caplog.text


@pytest.mark.parametrize("selector,status", [("mock", "deferred"), ("dashscope", "unchecked")])
def test_speech_configuration_does_not_claim_live_acceptance(
    workspace: Any, selector: str, status: str
) -> None:
    app, _, _ = workspace
    settings = app.state.base_settings.model_copy(
        update={"tts_provider": selector, "voice_provider": selector}
    )
    result = settings_view(settings, None)
    speech = [item for item in result.components if item.key in {"tts", "voice"}]
    assert len(speech) == 2
    assert all(item.mode == ("real" if selector == "dashscope" else "mock") for item in speech)
    assert all(item.status == status and not item.switchable for item in speech)
    assert all(item.checked_at is None for item in speech)


@pytest.mark.parametrize("current_turn_id", [None, UUID("d9184dc9-e513-483a-b811-a642907222fa")])
def test_live_lease_authorization_expiry_readonly_socket_and_safe_projection(
    workspace: Any, monkeypatch: Any, current_turn_id: UUID | None
) -> None:
    app, database, client = workspace
    # This test edits rows directly (no Debate events): read them uncached.
    monkeypatch.setattr(app.state.settings, "debate_public_cache_seconds", 0.0)
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    debate_id, lease_id = str(uuid4()), str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic="Public classroom",
                background="Private background",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json="{}",
                status="draft",
                revision=0,
                last_sequence=0,
                created_by=TEACHER_ID,
                created_at=now,
                updated_at=now,
            )
        )
    url = f"/api/v1/debates/{debate_id}/live"
    with database.session() as db:
        db.add(PlaybackState(id=str(uuid4()), debate_id=debate_id, created_at=now, updated_at=now))
    assert client.get(f"/api/v1/courses/{COURSE_ID}/live").json() is None
    assert client.post(url, headers=headers, json={"lease_id": lease_id}).status_code == 200
    assert client.post(url, headers=headers, json={"lease_id": str(uuid4())}).status_code == 409
    with database.session() as db:
        window = ensure_closed_window(db, debate_id=debate_id, course_id=COURSE_ID)
        window.status = "open"
        window.token_nonce = b"i" * 32
        window.opened_by = TEACHER_ID
        window.opened_at = now
        expected_token = issue_token(window.id, window.token_nonce, app.state.settings.secret_bytes)
    _, student_csrf = login(client, "bowen")
    assert (
        client.post(
            url, headers={"X-CSRF-Token": student_csrf}, json={"lease_id": lease_id}
        ).status_code
        == 404
    )
    snapshot = client.get(f"/api/v1/live/{debate_id}")
    assert snapshot.status_code == 200 and snapshot.json()["active"]
    assert snapshot.json()["interaction_url"] == f"/classroom/{expected_token}"
    form_url = f"/api/v1/classroom-interactions/{expected_token}"
    assert client.get(form_url).status_code == 200
    for index in range(3):
        assert (
            client.post(
                f"{form_url}/barrages",
                json={
                    "nickname": "Student",
                    "raw_text": "A question",
                    "client_submission_id": str(uuid4()),
                },
                # Three viewers: one barrage per viewer per 3 s (2026-10-19).
                headers={"X-Maya-Audience": f"viewer-{index}"},
            ).status_code
            == 201
        )
    assert "Private background" not in snapshot.text
    assert "controller_epoch" not in snapshot.text
    assert client.get(f"/api/v1/live/{debate_id}/audio/{uuid4()}").status_code == 404
    original_dto = app.state.playback_service._state_dto
    monkeypatch.setattr(
        app.state.playback_service,
        "_state_dto",
        lambda *args: original_dto(*args).model_copy(update={"current_turn_id": current_turn_id}),
    )
    with client.websocket_connect(
        f"/api/v1/live/{debate_id}/events", headers={"origin": "http://testserver"}
    ) as socket:
        event = socket.receive_json()
        assert event["active"]
        assert event["playback"]["current_turn_id"] == (
            str(current_turn_id) if current_turn_id else None
        )
        socket.send_json({"command": "advance"})
        assert socket.receive()["code"] == 4403
    with database.session() as db:
        db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id)).mode = "replay"
    assert client.get(f"/api/v1/live/{debate_id}").json()["interaction_url"] is None
    with database.session() as db:
        db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id)).mode = "live"
        db.get(Debate, debate_id).rule_snapshot_json = '{"turn_protocol":"segments_v2"}'
    assert client.get(f"/api/v1/live/{debate_id}").json()["interaction_url"] is None
    with database.session() as db:
        db.get(Debate, debate_id).rule_snapshot_json = "{}"
        db.get(Debate, debate_id).final_input_json = "{}"
    assert client.get(f"/api/v1/live/{debate_id}").json()["interaction_url"] is None
    with database.session() as db:
        db.get(Debate, debate_id).final_input_json = None
        presence = db.get(LivePresence, COURSE_ID)
        presence.expires_at = now - timedelta(seconds=1)
    assert client.get(f"/api/v1/courses/{COURSE_ID}/live").json() is None
    expired = client.get(f"/api/v1/live/{debate_id}").json()
    assert expired["active"] is False
    assert expired["interaction_url"] is None
    assert app.state.settings.tts_provider == "mock"
