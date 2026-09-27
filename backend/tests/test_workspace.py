import asyncio
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import CourseMember, ProviderOperation
from app.modules.debates.models import Debate, PlaybackState
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.interactions.service import ensure_closed_window
from app.modules.interactions.tokens import issue_token
from app.modules.knowledge.providers.query_embedding import QueryEmbeddingError
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
    Conversation,
    ConversationTurn,
    LivePresence,
    ProviderPreferences,
)
from app.modules.workspace.providers import preferences_settings, settings_view
from app.providers.control_repository import ProviderRepository
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, func, select

from tests.conftest import login
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy


@pytest.fixture
def workspace(app_bundle: Any, client: TestClient) -> tuple[Any, Any, TestClient]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, client


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
    first = client.post(f"{url}/messages", headers=headers, json=body)
    assert first.status_code == 200
    assert first.json()["turns"][0]["state"] == "ready"
    assert first.json()["turns"][0]["mode"] == "mock"
    assert client.post(f"{url}/messages", headers=headers, json=body).json() == first.json()
    assert (
        client.post(
            f"{url}/messages", headers=headers, json={**body, "message": "Changed"}
        ).status_code
        == 409
    )
    second = client.post(
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
    first = client.post(
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
        client.post(
            f"{url}/messages", headers={"X-CSRF-Token": teacher_csrf}, json=body
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
                        "message": {"content": '{"reply":"A considered reply"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
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
        result = client.post(url, headers=headers, json=body)
        assert result.status_code == 200
        assert len(result.json()["turns"]) == revision + 1
        assert all(turn["state"] == "ready" for turn in result.json()["turns"])
        assert client.post(url, headers=headers, json=body).json() == result.json()
        assert transport.call_count == revision + 1
    assert [message["role"] for message in transport.call_args.kwargs["json"]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert [
        message["content"] for message in transport.call_args.kwargs["json"]["messages"][1:]
    ] == [
        "Question 0",
        "A considered reply",
        "Question 1",
        "A considered reply",
        "请用中文解释刚才的观点。",
    ]
    instruction = transport.call_args.kwargs["json"]["messages"][0]["content"]
    assert "final user message" in instruction
    assert "When that message is in Chinese, write the reply in Chinese" in instruction
    assert "takes priority over language preferences in agent_markdown" in instruction
    assert "including earlier assistant replies" in instruction
    assert "agent_markdown" in transport.call_args.kwargs["json"]["messages"][0]["content"]
    response_format = transport.call_args.kwargs["json"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["required"] == ["reply"]
    with database.session() as db:
        operations = list(
            db.scalars(select(ProviderOperation).where(ProviderOperation.scope_id == created["id"]))
        )
        assert len(operations) == 3
        assert all(operation.state == "succeeded" for operation in operations)


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

    def messages_with_authorization(version: Any, history: Any, sources: Any) -> Any:
        packed, fingerprint = chat_messages(version, history, sources)
        packed[0]["content"] = packed[0]["content"] + "\nAuthorization is a lesson topic."
        return packed, fingerprint

    monkeypatch.setattr("app.modules.workspace.chat.chat_messages", messages_with_authorization)
    transport = Mock(
        return_value=Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"reply":"Authorization is discussed in class."}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            },
        )
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    result = client.post(
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
    assert "Authorization" in transport.call_args.kwargs["json"]["messages"][0]["content"]


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
    assert client.post(f"{url}/messages", headers=headers, json=body).status_code == 409
    assert client.post(f"{url}/messages", json=body).status_code == 403
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
    recovered = client.post(
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
                        "message": {"content": '{"reply":"A considered reply"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
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
    earlier = client.post(
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
    first = client.post(f"{url}/messages", headers=headers, json=first_body)
    assert first.status_code == 200
    assert first.json()["turns"][1]["state"] == "acceptance_unknown"
    assert first.json()["turns"][1]["user_text"] == "uncertain original"
    replay = client.post(f"{url}/messages", headers=headers, json=first_body)
    assert replay.json() == first.json()
    assert generated == ["Earlier successful question", "uncertain original"]
    second = client.post(
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
    sent_messages = transport.call_args.kwargs["json"]["messages"]
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
                "message": {"content": '{"reply":"Accepted content"}'},
                "finish_reason": "stop",
            }
        ]
    }
    if usage_case != "missing":
        provider_payload["usage"] = usage_value
    transport = Mock(return_value=Response(200, json=provider_payload))
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    request_id = str(uuid4())
    response = client.post(
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
    [('{"not_reply":"bad"}', "stop"), ('{"reply":"Unfinished"}', "length")],
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
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": None,
            },
        )
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
    _, csrf = login(client, "bowen")
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/conversations", headers=headers, json={"version_id": BASELINE_VERSION_ID}
    ).json()
    request_id = str(uuid4())
    response = client.post(
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
                        "message": {"content": '{"reply":"Should never be dispatched"}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    monkeypatch.setattr("app.modules.workspace.chat_provider.HttpxLLMTransport.post", transport)
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
        assert old_operation is not None
        assert old_operation.state == "not_sent"
        assert old_operation.request_count == 0
        assert old_operation.charged_request_count == 0
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
    result = client.post(url, headers=headers, json=body)
    assert result.json()["turns"][0]["safe_error_code"] == "chat_failed"
    assert client.post(url, headers=headers, json=body).status_code == 200
    assert len(calls) == 1
    assert "chat_failed" in caplog.text
    assert "private-provider-body" not in caplog.text + result.text
    assert "Private learner text" not in caplog.text


def test_provider_controls_are_teacher_only_and_key_is_encrypted(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client, "bowen")
    url = f"/api/v1/courses/{COURSE_ID}/provider-settings"
    assert client.get(url).status_code == 404
    assert (
        client.post(url, headers={"X-CSRF-Token": csrf}, json={"expected_revision": 0}).status_code
        == 404
    )
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    assert client.get(url).json()["credential_ready"] is False
    missing = client.post(
        url, headers=headers, json={"expected_revision": 0, "component": "llm", "mode": "real"}
    )
    assert missing.json()["code"] == "provider_key_required"
    secret = "test-only-not-a-real-key"
    saved = client.post(url, headers=headers, json={"expected_revision": 0, "api_key": secret})
    assert saved.status_code == 200, saved.text
    assert saved.json()["credential_ready"] is True
    assert secret not in saved.text + client.get(url).text
    with database.session() as db:
        row = db.get(ProviderPreferences, 1)
        assert secret not in row.encrypted_key
        assert preferences_settings(app.state.base_settings, row).dashscope_api_key == secret
    assert (
        client.post(
            url, headers=headers, json={"expected_revision": 0, "component": "llm", "mode": "mock"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            url, headers=headers, json={"expected_revision": 1, "component": "tts", "mode": "real"}
        ).json()["code"]
        == "provider_deferred"
    )


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


def test_environment_dashscope_key_wins_over_saved_dialog_key(workspace: Any) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    url = f"/api/v1/courses/{COURSE_ID}/provider-settings"
    saved_key = "saved-dialog-key-not-real"
    saved = client.post(
        url, headers={"X-CSRF-Token": csrf}, json={"expected_revision": 0, "api_key": saved_key}
    )
    assert saved.status_code == 200, saved.text
    rotated = "rotated-env-key-not-real"
    app.state.base_settings = app.state.base_settings.model_copy(
        update={"dashscope_api_key": rotated}
    )
    with database.session() as db:
        row = db.get(ProviderPreferences, 1)
        assert row is not None
        effective = preferences_settings(app.state.base_settings, row)
        stored = row.encrypted_key or ""
    assert effective.dashscope_api_key == rotated
    assert saved_key not in stored
    assert rotated not in stored
    assert saved_key not in saved.text
    assert rotated not in saved.text


def test_provider_refresh_and_mock_check_never_make_a_paid_call(workspace: Any) -> None:
    _, database, client = workspace
    _, csrf = login(client)
    url = f"/api/v1/courses/{COURSE_ID}/provider-settings"
    before = client.get(url).json()
    assert all(item["status"] in {"unchecked", "deferred"} for item in before["components"])
    request = {"request_id": str(uuid4()), "expected_revision": 0}
    first = client.post(f"{url}/llm/check", headers={"X-CSRF-Token": csrf}, json=request)
    assert first.status_code == 200
    assert (
        next(item for item in first.json()["components"] if item["key"] == "llm")["status"]
        == "ready"
    )
    assert (
        client.post(f"{url}/llm/check", headers={"X-CSRF-Token": csrf}, json=request).json()
        == first.json()
    )
    assert client.get(url).json() == first.json()
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


def test_mode_change_invalidates_only_that_check_and_key_change_invalidates_all(
    workspace: Any,
) -> None:
    app, database, client = workspace
    _, csrf = login(client)
    headers = {"X-CSRF-Token": csrf}
    url = f"/api/v1/courses/{COURSE_ID}/provider-settings"
    with database.session() as db:
        db.add(
            ProviderPreferences(
                id=1,
                revision=0,
                modes_json="{}",
                checks_json=json.dumps(
                    {key: {"status": "ready"} for key in ("llm", "embedding", "report")}
                ),
            )
        )
    app.state.settings = app.state.settings.model_copy(update={"llm_provider": "dashscope"})
    result = client.post(
        url, headers=headers, json={"expected_revision": 0, "component": "llm", "mode": "mock"}
    )
    assert result.status_code == 200
    statuses = {item["key"]: item["status"] for item in result.json()["components"]}
    assert statuses["llm"] == "unchecked"
    assert statuses["embedding"] == statuses["report"] == "ready"
    result = client.post(
        url, headers=headers, json={"expected_revision": 1, "api_key": "test-only-not-a-real-key"}
    )
    assert result.status_code == 200
    assert all(item["status"] in ("unchecked", "deferred") for item in result.json()["components"])
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("current_turn_id", [None, UUID("d9184dc9-e513-483a-b811-a642907222fa")])
def test_live_lease_authorization_expiry_readonly_socket_and_safe_projection(
    workspace: Any, monkeypatch: Any, current_turn_id: UUID | None
) -> None:
    app, database, client = workspace
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
    for _ in range(3):
        assert (
            client.post(
                f"{form_url}/barrages",
                json={
                    "nickname": "Student",
                    "raw_text": "A question",
                    "client_submission_id": str(uuid4()),
                },
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
