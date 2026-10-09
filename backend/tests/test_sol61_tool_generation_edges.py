from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from agno.tools.function import FunctionCall
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    IdempotencyRecord,
    Job,
    KnowledgeDocument,
    ProviderOperation,
    SessionRecord,
)
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.models import (
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.runtime_tools.models import RuntimeModelCallStage, RuntimeToolReceipt
from app.modules.runtime_tools.registry import ToolCallIdentity, execute_tool
from app.modules.runtime_tools.runtime import build_runtime_tools
from app.seed import COURSE_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_knowledge_generation import _headers
from tests.test_runtime_tool_knowledge import (
    GENERATE_AGENT_KNOWLEDGE_TOOL,
    _configure_chat,
    _FakeGenerationWorkerTransport,
    _reply_response,
    _result_for_turn,
    _send_tool_turn,
    _teacher_agent_chat,
    _tool_response,
)


@pytest.fixture
def runtime_tool_workspace(app_bundle: Any, client: TestClient) -> tuple[Any, Any, TestClient, Any]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, client, settings


def _started(workspace, monkeypatch):
    app, database, client, settings = workspace
    transport = _configure_chat(app, database, settings, monkeypatch)
    _, csrf = login(client, "maya")
    agent_id, version_id, document_id, chat_id = _teacher_agent_chat(
        client, csrf, agent_markdown="# Current Guide\n\nCall generate_agent_knowledge when asked."
    )
    wakes = []
    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", wakes.append)
    transport.side_effect = [_tool_response("edge-first"), _reply_response()]
    first = _send_tool_turn(client, csrf, chat_id, expected_revision=0, call_id="edge-first")
    turn_id = first.json()["turns"][0]["id"]
    result = _result_for_turn(database, turn_id)
    return (
        app,
        database,
        client,
        transport,
        csrf,
        agent_id,
        version_id,
        document_id,
        chat_id,
        turn_id,
        first,
        result,
        wakes,
    )


@pytest.mark.parametrize(
    "revocation", ["source_hidden", "source_epoch", "set_deleted", "set_epoch"]
)
def test_accepted_sdk_receipt_replay_rechecks_source_and_set(
    revocation, runtime_tool_workspace, monkeypatch
):
    (
        app,
        database,
        client,
        transport,
        csrf,
        _,
        version_id,
        document_id,
        chat_id,
        turn_id,
        first,
        result,
        wakes,
    ) = _started(runtime_tool_workspace, monkeypatch)
    with database.session() as db:
        original_receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == turn_id,
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
        )
        assert original_receipt is not None
        original_receipt_json = original_receipt.result_json
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, result["canonical_set_id"])
        if revocation == "source_hidden":
            document.workspace_state = "hidden"
        elif revocation == "source_epoch":
            document.authorization_epoch += 1
        elif revocation == "set_deleted":
            set_row.deleted_at = datetime.now(UTC)
        else:
            set_row.authorization_epoch += 1
    with database.session() as db:
        actor = get_auth_context(db, app.state.settings, client.cookies.get("maya_session"))
        assert actor is not None
    functions = build_runtime_tools(
        database.session_factory,
        actor.user.id,
        chat_id,
        version_id,
        turn_id,
        app.state.settings,
        actor_context=actor,
        generation_waker=wakes.append,
    )
    function = next(item for item in functions if item.name == GENERATE_AGENT_KNOWLEDGE_TOOL)
    call = FunctionCall(function=function, arguments={"arguments": {}}, call_id="edge-first")
    call.execute()
    assert isinstance(call.result, dict), call.result
    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation

    fake_worker = _FakeGenerationWorkerTransport(database, result["run_id"])
    run_claimed_knowledge_generation(
        database.session_factory, result["run_id"], app.state.settings, transport=fake_worker
    )
    assert fake_worker.calls == 0
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, result["run_id"])
        assert run.state == "blocked" and run.safe_error_code == "authorization_revoked"
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.scope_id == run.id)
            )
            == 0
        )
    assert call.result["ok"] is False, (revocation, call.result, wakes)
    assert wakes == [result["run_id"]]
    with database.session() as db:
        preserved_receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == turn_id,
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
        )
        assert preserved_receipt is not None
        assert preserved_receipt.result_json == original_receipt_json
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, result["canonical_set_id"])
        binding = db.scalar(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.knowledge_set_id == result["canonical_set_id"],
                KnowledgeSetSource.document_id == document_id,
                KnowledgeSetSource.is_active.is_(True),
            )
        )
        run = db.get(KnowledgeGenerationRun, result["run_id"])
        assert (
            document is not None and set_row is not None and binding is not None and run is not None
        )
        if revocation == "source_hidden":
            document.workspace_state = "active"
        elif revocation == "source_epoch":
            document.authorization_epoch = binding.source_authorization_epoch
        elif revocation == "set_deleted":
            set_row.deleted_at = None
        else:
            set_row.authorization_epoch = run.set_authorization_epoch
    transport.side_effect = [_tool_response("edge-legal-again"), _reply_response()]
    followup = _send_tool_turn(
        client,
        csrf,
        chat_id,
        expected_revision=first.json()["revision"],
        call_id="edge-legal-again",
    )
    followup_result = _result_for_turn(database, followup.json()["turns"][1]["id"])
    assert followup_result["status"] == "generating"
    assert followup_result["run_id"] != result["run_id"]
    assert wakes == [result["run_id"], followup_result["run_id"]]


@pytest.mark.parametrize(
    "revocation", ["session", "teacher_role", "agent_epoch", "wrong_participant", "wrong_arguments"]
)
def test_accepted_receipt_scope_negatives(revocation, runtime_tool_workspace, monkeypatch):
    app, database, client, _, _, agent_id, version_id, _, chat_id, turn_id, _, result, _ = _started(
        runtime_tool_workspace, monkeypatch
    )
    with database.session() as db:
        actor = get_auth_context(db, app.state.settings, client.cookies.get("maya_session"))
        stage = db.scalar(
            select(RuntimeModelCallStage).where(
                RuntimeModelCallStage.turn_id == turn_id, RuntimeModelCallStage.ordinal == 1
            )
        )
        assert actor is not None and stage is not None
        identity = ToolCallIdentity(chat_id, turn_id, version_id, stage.operation_id, "edge-first")
        if revocation == "session":
            db.get(SessionRecord, actor.session.id_hash).revoked_at = datetime.now(UTC)
        elif revocation == "teacher_role":
            db.get(CourseMember, (COURSE_ID, actor.user.id)).role = "student"
        elif revocation == "agent_epoch":
            db.get(Agent, agent_id).authorization_epoch += 1
        elif revocation == "wrong_participant":
            identity = ToolCallIdentity(
                chat_id, turn_id, str(uuid4()), stage.operation_id, "edge-first"
            )
        arguments = {"agent_id": str(uuid4())} if revocation == "wrong_arguments" else {}
        db.flush()
        replay = execute_tool(
            db, actor, identity, GENERATE_AGENT_KNOWLEDGE_TOOL, arguments, runtime_registry()
        )
        assert replay["ok"] is False, (revocation, replay)
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 1
        assert db.get(KnowledgeGenerationRun, result["run_id"]).state == "pending"


def test_known_retry_after_rag_selection_change_keeps_exact_current_sources(
    runtime_tool_workspace, monkeypatch
):
    app, database, client, transport, csrf, agent_id, _, old_doc, _, _, _, old_result, wakes = (
        _started(runtime_tool_workspace, monkeypatch)
    )
    draft = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
    )
    assert draft.status_code == 201, draft.text
    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        files={
            "file": (
                "new.md",
                b"# New current RAG\n\nOnly this source is selected.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    new_doc = uploaded.json()["document"]["id"]
    selected = client.put(
        f"/api/v1/agent-versions/{draft.json()['id']}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": draft.json()["revision"], "document_ids": [new_doc]},
    )
    assert selected.status_code == 200, selected.text
    published = client.post(
        f"/api/v1/agent-versions/{draft.json()['id']}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
        json={"expected_revision": selected.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    chat = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": published.json()["id"]}
    )
    assert chat.status_code == 200, chat.text
    chat_id = chat.json()["id"]
    transport.side_effect = [_tool_response("new-source-first"), _reply_response()]
    first = _send_tool_turn(client, csrf, chat_id, expected_revision=0, call_id="new-source-first")
    first_result = _result_for_turn(database, first.json()["turns"][0]["id"])
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, first_result["run_id"])
        assert [item["document_id"] for item in json.loads(run.source_manifest_json)] == [new_doc]
        assert run.id != old_result["run_id"]
        run.state = "blocked"
        run.safe_error_code = "llm_transport_not_sent"
        job = db.get(Job, run.job_id)
        job.state = "failed"
        job.safe_error_code = run.safe_error_code
    transport.side_effect = [_tool_response("new-source-retry"), _reply_response()]
    retry = _send_tool_turn(
        client,
        csrf,
        chat_id,
        expected_revision=first.json()["revision"],
        call_id="new-source-retry",
    )
    retry_result = _result_for_turn(database, retry.json()["turns"][1]["id"])
    with database.session() as db:
        retry_run = db.get(KnowledgeGenerationRun, retry_result["run_id"])
        sources = [item["document_id"] for item in json.loads(retry_run.source_manifest_json)]
        historical_sources = list(
            db.scalars(
                select(KnowledgeSetSource.document_id)
                .where(
                    KnowledgeSetSource.knowledge_set_id == retry_run.knowledge_set_id,
                    KnowledgeSetSource.is_active.is_(True),
                )
                .order_by(KnowledgeSetSource.order_index, KnowledgeSetSource.id)
            ).all()
        )
        from app.modules.knowledge_sets.generation import (
            _current_generation_authorized,
            _generation_action_payload_hash,
            _generation_action_request_hash,
        )

        assert _current_generation_authorized(db, retry_run) is True
        agent = db.get(Agent, retry_run.agent_id)
        version = db.get(AgentVersion, retry_run.agent_version_id)
        set_row = db.get(KnowledgeSet, retry_run.knowledge_set_id)
        assert agent is not None and version is not None and set_row is not None
        expected_payload_hash = _generation_action_payload_hash(
            agent=agent,
            version=version,
            set_row=set_row,
            agent_md_hash=retry_run.agent_md_hash,
            source_manifest=json.loads(retry_run.source_manifest_json),
        )
        matching_action = next(
            record
            for record in db.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.operation == "knowledgeGenerationAction",
                    IdempotencyRecord.actor_user_id == retry_run.owner_user_id,
                )
            ).all()
            if json.loads(record.response_json)["run_id"] == retry_run.id
        )
        action_id = matching_action.key.removeprefix("action:")
        assert matching_action.request_hash == _generation_action_request_hash(
            retry_run.owner_user_id,
            retry_run.knowledge_set_id,
            action_id,
            expected_payload_hash,
        )

    class CapturingWorker(_FakeGenerationWorkerTransport):
        def post_bytes(self, url, *, headers, content, timeout):
            self.sent_payload = content.decode()
            return super().post_bytes(url, headers=headers, content=content, timeout=timeout)

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation

    worker = CapturingWorker(database, retry_result["run_id"])
    run_claimed_knowledge_generation(
        database.session_factory, retry_result["run_id"], app.state.settings, transport=worker
    )
    assert worker.calls == 1
    assert "A source canary." not in worker.sent_payload
    assert "Only this source is selected." in worker.sent_payload
    assert sources == [new_doc], {"old": old_doc, "new": new_doc, "actual": sources, "wakes": wakes}
    assert set(historical_sources) == {old_doc, new_doc}


def test_latest_intent_wins_even_when_old_run_created_at_is_later(
    runtime_tool_workspace, monkeypatch
):
    app, database, client, transport, csrf, _, _, _, chat_id, _, first, old_result, wakes = (
        _started(runtime_tool_workspace, monkeypatch)
    )
    with database.session() as db:
        old = db.get(KnowledgeGenerationRun, old_result["run_id"])
        old.state = "blocked"
        old.safe_error_code = "llm_transport_not_sent"
        job = db.get(Job, old.job_id)
        job.state = "failed"
        job.safe_error_code = old.safe_error_code
    transport.side_effect = [_tool_response("latest-retry"), _reply_response()]
    second = _send_tool_turn(
        client, csrf, chat_id, expected_revision=first.json()["revision"], call_id="latest-retry"
    )
    latest_result = _result_for_turn(database, second.json()["turns"][1]["id"])
    assert latest_result["run_id"] != old_result["run_id"]
    with database.session() as db:
        old = db.get(KnowledgeGenerationRun, old_result["run_id"])
        old.created_at = datetime.now(UTC) + timedelta(days=1)
    transport.side_effect = [_tool_response("latest-pending"), _reply_response()]
    third = _send_tool_turn(
        client, csrf, chat_id, expected_revision=second.json()["revision"], call_id="latest-pending"
    )
    current = _result_for_turn(database, third.json()["turns"][2]["id"])
    assert current["run_id"] == latest_result["run_id"]
    assert current["status"] == "generating"
    assert wakes == [old_result["run_id"], latest_result["run_id"], latest_result["run_id"]]


def test_receipt_insert_failure_rolls_back_first_generation_and_alias(
    runtime_tool_workspace, monkeypatch
):
    app, database, client, settings = runtime_tool_workspace
    transport = _configure_chat(app, database, settings, monkeypatch)
    _, csrf = login(client, "maya")
    agent_id, _, _, chat_id = _teacher_agent_chat(
        client, csrf, agent_markdown="# Guide\n\nCall generate_agent_knowledge when asked."
    )
    wakes = []
    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", wakes.append)

    def fail_receipt(self, **kwargs):
        raise RuntimeError("synthetic receipt construction failure")

    monkeypatch.setattr(RuntimeToolReceipt, "__init__", fail_receipt)
    transport.side_effect = [_tool_response("receipt-failure"), _reply_response()]
    _send_tool_turn(client, csrf, chat_id, expected_revision=0, call_id="receipt-failure")
    with database.session() as db:
        from app.core.models import IdempotencyRecord
        from app.modules.knowledge_sets.models import AgentKnowledgeSet

        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_id == agent_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AgentKnowledgeSet)
                .where(AgentKnowledgeSet.agent_id == agent_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation == "knowledgeGenerationAction")
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0
        assert wakes == []
