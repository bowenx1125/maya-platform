"""Restart recovery preserves accepted envelopes and invalidates stale execution."""

from dataclasses import replace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

from app.core.models import ProviderOperation
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.runtime_tools.models import RuntimeModelCallStage
from app.modules.runtime_tools.recovery import (
    accepted_chat_stage_complete,
    recover_single_chat_runs,
)
from app.modules.workspace.models import Conversation, ConversationTurn
from app.providers.control_repository import ProviderRepository
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select

from tests.conftest import login
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy


def test_restart_preserves_single_accepted_stage_for_explicit_resume(
    app_bundle: Any, client: TestClient, monkeypatch: Any
) -> None:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    app.state.settings = settings.model_copy(
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
                        "message": {"role": "assistant", "content": "Saved response"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
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
    response = client.post(
        f"/api/v1/conversations/{created['id']}/messages",
        headers={"X-CSRF-Token": csrf},
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "Save this response.",
        },
    )
    assert response.status_code == 200, response.text
    turn_id = response.json()["turns"][0]["id"]
    with database.session() as db:
        turn = db.get(ConversationTurn, turn_id)
        conversation = db.get(Conversation, created["id"])
        stage = db.scalar(
            select(RuntimeModelCallStage).where(RuntimeModelCallStage.turn_id == turn_id)
        )
        assert turn is not None and conversation is not None and stage is not None
        operation = db.get(ProviderOperation, stage.operation_id)
        assert operation is not None and accepted_chat_stage_complete(db, operation)
        # Model receipt is durable but local completion did not survive the crash.
        turn.state = "pending"
        turn.assistant_text = None
        conversation.active_request_id = turn.id
        revision = conversation.revision
        db.flush()
        recover_single_chat_runs(db)
        assert turn.state == "paused"
        assert turn.safe_error_code == "chat_recovery_available"
        assert conversation.active_request_id is None
        assert conversation.revision == revision + 1
        assert operation.state in {"accepted", "succeeded"}
        assert accepted_chat_stage_complete(db, operation)
        assert stage.accepted_response_json is not None
        assert operation.charged_request_count == 1
    assert transport.call_count == 1
