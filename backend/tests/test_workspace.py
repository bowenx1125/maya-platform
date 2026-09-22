import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from app.core.models import CourseMember, ProviderOperation
from app.modules.debates.models import Debate, PlaybackState
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.workspace.chat_provider import chat_messages
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    LivePresence,
    ProviderPreferences,
)
from app.modules.workspace.providers import preferences_settings
from app.providers.control_repository import ProviderRepository
from app.providers.llm_price_card import LLMPriceCardV1
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
    _, database, client = workspace
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
    monkeypatch.setattr(LLMPriceCardV1, "reservation_cost", lambda self: Decimal("0.076080"))
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
            "message": f"Question {revision}",
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
    ] == ["Question 0", "A considered reply", "Question 1", "A considered reply", "Question 2"]
    assert "agent_markdown" in transport.call_args.kwargs["json"]["messages"][0]["content"]
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
    monkeypatch.setattr(LLMPriceCardV1, "reservation_cost", lambda self: Decimal("0.076080"))
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
    assert (
        client.post(
            f"{url}/messages", headers=headers, json={**body, "expected_revision": 0}
        ).json()["code"]
        == "chat_acceptance_unknown"
    )
    with database.session() as db:
        row = db.get(Conversation, created["id"])
        db.execute(delete(CourseMember).where(CourseMember.user_id == row.user_id))
    assert client.get(url).status_code == 404
    assert client.get("/api/v1/conversations").json() == []


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
    _, student_csrf = login(client, "bowen")
    assert (
        client.post(
            url, headers={"X-CSRF-Token": student_csrf}, json={"lease_id": lease_id}
        ).status_code
        == 404
    )
    snapshot = client.get(f"/api/v1/live/{debate_id}")
    assert snapshot.status_code == 200 and snapshot.json()["active"]
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
        presence = db.get(LivePresence, COURSE_ID)
        presence.expires_at = now - timedelta(seconds=1)
    assert client.get(f"/api/v1/courses/{COURSE_ID}/live").json() is None
    assert client.get(f"/api/v1/live/{debate_id}").json()["active"] is False
    assert app.state.settings.tts_provider == "mock"
