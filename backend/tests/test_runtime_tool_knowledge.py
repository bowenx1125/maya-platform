from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import IdempotencyRecord, Job, KnowledgeDocument, ProviderOperation
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import BASELINE_VERSION_ID, ensure_demo_baseline
from app.modules.knowledge_sets.materialization import materialize_accepted_knowledge_generation
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
from app.modules.knowledge_sets.service import now_utc
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.runtime_tools.knowledge import (
    GENERATE_AGENT_KNOWLEDGE_TOOL,
    GenerateAgentKnowledgeArguments,
    generate_agent_knowledge,
)
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.runtime_tools.registry import ToolCallIdentity, exposed_tools
from app.modules.workspace.models import Conversation
from app.providers.control_repository import ProviderRepository
from app.providers.llm_transport import LLMAcceptanceUnknown, LLMTransportResponse
from app.seed import COURSE_ID
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_knowledge_generation import _headers, _teacher_agent_with_source
from tests.test_knowledge_generation_materialization import _accept_stage
from tests.test_wave4_llm_adapter import _adapter
from tests.test_wave4_llm_ledger import _valid_policy


def _tool_response(call_id: str) -> Response:
    return _tool_calls_response([call_id])


def _tool_calls_response(call_ids: list[str]) -> Response:
    return Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": GENERATE_AGENT_KNOWLEDGE_TOOL,
                                    "arguments": '{"arguments":{}}',
                                },
                            }
                            for call_id in call_ids
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
    )


def _reply_response(text: str = "I checked the current Knowledge generation.") -> Response:
    return Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ]
        },
    )


def _configure_chat(app: Any, database: Any, base_settings: Any, monkeypatch: Any) -> Mock:
    adapter = _adapter(None)
    policy = replace(_valid_policy(), endpoint=adapter.config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(policy)
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-secret",
            "dashscope_workspace_id": "workspace123",
            "dashscope_region": "cn-beijing",
            "demo_auto_confirm_provider": True,
        }
    )
    app.state.settings = settings
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.llm_provider", lambda _settings: adapter
    )
    monkeypatch.setattr("app.modules.workspace.chat.retrieve_sources", lambda *args, **kwargs: [])
    transport = Mock()
    monkeypatch.setattr(
        "app.modules.workspace.chat_provider.HttpxLLMTransport.post_bytes", transport
    )
    return transport


def _teacher_agent_chat(
    client: TestClient,
    csrf: str,
    *,
    agent_markdown: str,
) -> tuple[str, str, str, str]:
    agent_id, draft_id, revision, document_id = _teacher_agent_with_source(
        client, csrf, agent_markdown=agent_markdown
    )
    published = client.post(
        f"/api/v1/agent-versions/{draft_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": f"tool-knowledge-publish-{uuid4()}"}),
        json={"expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    version_id = published.json()["id"]
    created = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": version_id},
    )
    assert created.status_code == 200, created.text
    return agent_id, version_id, document_id, created.json()["id"]


def _send_tool_turn(
    client: TestClient,
    csrf: str,
    conversation_id: str,
    *,
    expected_revision: int,
    call_id: str,
    request_id: str | None = None,
) -> Response:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "request_id": request_id or str(uuid4()),
            "expected_revision": expected_revision,
            "message": "Please generate Knowledge from this Agent's current RAG sources.",
        },
    )
    assert response.status_code == 200, response.text
    return response


def _result_for_turn(database: Any, turn_id: str) -> dict[str, Any]:
    with database.session() as db:
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == turn_id,
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
        )
        assert receipt is not None
        return json.loads(receipt.result_json)["result"]


def _assert_postcommit_generation(database: Any, run_id: str) -> None:
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        assert db.get(Job, run.job_id) is not None
        receipts = db.scalars(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL
            )
        ).all()
        assert any(
            json.loads(row.result_json)["result"].get("run_id") == run_id for row in receipts
        )


class _FakeGenerationWorkerTransport:
    def __init__(self, database: Any, run_id: str) -> None:
        self.database = database
        self.run_id = run_id
        self.calls = 0

    def post_bytes(
        self,
        _url: str,
        *,
        headers: dict[str, str],
        content: bytes,
        timeout: object,
    ) -> LLMTransportResponse:
        del headers, content, timeout
        self.calls += 1
        with self.database.session() as db:
            receipt_id = db.scalar(
                select(KnowledgeGenerationSourceReceipt.id).where(
                    KnowledgeGenerationSourceReceipt.run_id == self.run_id
                )
            )
        assert receipt_id is not None
        return LLMTransportResponse(
            status_code=200,
            payload={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "assets": [
                                        {
                                            "kind": "note",
                                            "title": "Course note",
                                            "body": "A generated source-backed note.",
                                            "source_receipt_ids": [receipt_id],
                                        }
                                    ]
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )


@pytest.fixture
def runtime_tool_workspace(app_bundle: Any, client: TestClient) -> tuple[Any, Any, TestClient, Any]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, client, settings


def test_teacher_agent_chat_generates_once_and_reuses_pending_then_completed_run(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, _document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown=(
            "# Course Guide\n\nWhen the teacher asks, call generate_agent_knowledge "
            "to create canonical Knowledge from the selected RAG source."
        ),
    )
    wakes: list[str] = []
    task_manager = app.state.knowledge_generation_task_manager

    def wake(run_id: str) -> None:
        _assert_postcommit_generation(database, run_id)
        wakes.append(run_id)

    monkeypatch.setattr(task_manager, "wake", wake)
    transport.side_effect = [_tool_response("knowledge-call-1"), _reply_response()]
    first = _send_tool_turn(
        client, csrf, conversation_id, expected_revision=0, call_id="knowledge-call-1"
    )
    first_receipt = _result_for_turn(database, first.json()["turns"][0]["id"])
    assert first_receipt["status"] == "generating"
    run_id = first_receipt["run_id"]
    set_id = first_receipt["canonical_set_id"]
    job_id = first_receipt["job_id"]
    assert wakes == [run_id]
    first_wire = json.loads(transport.call_args_list[0].kwargs["content"])
    assert any(
        item.get("function", {}).get("name") == GENERATE_AGENT_KNOWLEDGE_TOOL
        for item in first_wire["tools"]
    )
    assert "call generate_agent_knowledge" in first_wire["messages"][0]["content"]

    transport.side_effect = [_tool_response("knowledge-call-2"), _reply_response()]
    pending_replay = _send_tool_turn(
        client,
        csrf,
        conversation_id,
        expected_revision=first.json()["revision"],
        call_id="knowledge-call-2",
    )
    pending_receipt = _result_for_turn(database, pending_replay.json()["turns"][1]["id"])
    assert pending_receipt["status"] == "generating"
    assert (
        pending_receipt["run_id"],
        pending_receipt["job_id"],
        pending_receipt["canonical_set_id"],
    ) == (
        run_id,
        job_id,
        set_id,
    )
    assert wakes == [run_id, run_id]

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation

    fake_worker = _FakeGenerationWorkerTransport(database, run_id)
    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        app.state.settings,
        transport=fake_worker,
    )
    assert fake_worker.calls == 1

    transport.side_effect = [_tool_response("knowledge-call-3"), _reply_response()]
    completed_replay = _send_tool_turn(
        client,
        csrf,
        conversation_id,
        expected_revision=pending_replay.json()["revision"],
        call_id="knowledge-call-3",
    )
    completed_receipt = _result_for_turn(database, completed_replay.json()["turns"][2]["id"])
    assert completed_receipt["status"] == "completed"
    assert completed_receipt["run_id"] == run_id
    assert wakes == [run_id, run_id]

    with database.session() as db:
        assert db.get(AgentKnowledgeSet, (agent_id, set_id)) is not None
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None and run.agent_version_id == version_id
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_id == agent_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(
                    ProviderOperation.scope_id == run_id,
                    ProviderOperation.provider_operation == "llm_knowledge_generate",
                )
            )
            == 1
        )


def test_same_turn_tool_calls_share_one_known_failure_action_but_new_turn_can_retry(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    _agent_id, _version_id, _document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nCall generate_agent_knowledge when asked.",
    )
    wakes: list[str] = []

    def fail_first_known_run(run_id: str) -> None:
        _assert_postcommit_generation(database, run_id)
        wakes.append(run_id)
        if len(wakes) == 1:
            with database.session() as db:
                run = db.get(KnowledgeGenerationRun, run_id)
                assert run is not None
                job = db.get(Job, run.job_id)
                assert job is not None
                run.state = "blocked"
                run.safe_error_code = "llm_transport_not_sent"
                job.state = "failed"
                job.safe_error_code = "llm_transport_not_sent"

    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", fail_first_known_run)
    transport.side_effect = [
        _tool_calls_response(["same-turn-call-1", "same-turn-call-2"]),
        _reply_response(),
    ]
    first_turn = _send_tool_turn(
        client,
        csrf,
        conversation_id,
        expected_revision=0,
        call_id="same-turn-call-1",
    )
    turn_id = first_turn.json()["turns"][0]["id"]
    with database.session() as db:
        receipts = db.scalars(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == turn_id,
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
        ).all()
        assert len(receipts) == 2
        first_results = [json.loads(receipt.result_json)["result"] for receipt in receipts]
        assert len({result["run_id"] for result in first_results}) == 1
        assert {result["status"] for result in first_results} == {"generating", "failed"}
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_version_id == _version_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation == "knowledgeGenerationAction")
            )
            == 1
        )
    old_run_id = first_results[0]["run_id"]
    assert wakes == [old_run_id]

    transport.side_effect = [_tool_response("new-turn-retry"), _reply_response()]
    second_turn = _send_tool_turn(
        client,
        csrf,
        conversation_id,
        expected_revision=first_turn.json()["revision"],
        call_id="new-turn-retry",
    )
    retry_result = _result_for_turn(database, second_turn.json()["turns"][1]["id"])
    assert retry_result["status"] == "generating"
    assert retry_result["run_id"] != old_run_id
    assert wakes == [old_run_id, retry_result["run_id"]]
    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_version_id == _version_id)
            )
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(IdempotencyRecord.operation == "knowledgeGenerationAction")
            )
            == 2
        )


def test_unknown_generation_call_is_not_retried_by_a_later_tool_invocation(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    _agent_id, _version_id, _document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nCall generate_agent_knowledge when asked.",
    )
    wakes: list[str] = []
    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", wakes.append)
    transport.side_effect = [_tool_response("unknown-call-1"), _reply_response()]
    first = _send_tool_turn(
        client, csrf, conversation_id, expected_revision=0, call_id="unknown-call-1"
    )
    first_result = _result_for_turn(database, first.json()["turns"][0]["id"])
    run_id = first_result["run_id"]
    assert wakes == [run_id]

    class UnknownTransport:
        def post_bytes(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise LLMAcceptanceUnknown()

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation

    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        app.state.settings,
        transport=UnknownTransport(),
    )
    with database.session() as db:
        unknown_run = db.get(KnowledgeGenerationRun, run_id)
        assert unknown_run is not None
        assert unknown_run.state == "blocked"
        assert unknown_run.safe_error_code == "acceptance_unknown"
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == run_id,
                ProviderOperation.provider_operation == "llm_knowledge_generate",
            )
        )
        assert operation is not None
        assert operation.state == "acceptance_unknown"
        assert operation.charged_request_count == 1

    transport.side_effect = [_tool_response("unknown-call-2"), _reply_response()]
    second = _send_tool_turn(
        client,
        csrf,
        conversation_id,
        expected_revision=first.json()["revision"],
        call_id="unknown-call-2",
    )
    second_result = _result_for_turn(database, second.json()["turns"][1]["id"])
    assert second_result["status"] == "failed"
    assert second_result["safe_error_code"] == "acceptance_unknown"
    assert second_result["run_id"] == run_id
    assert wakes == [run_id]
    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.id == run_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(
                    ProviderOperation.scope_id == run_id,
                    ProviderOperation.provider_operation == "llm_knowledge_generate",
                )
            )
            == 1
        )


def test_new_rag_source_version_fences_late_accepted_tool_generation(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, old_document_id, old_conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nUse the first source-backed instruction.",
    )
    wakes: list[str] = []
    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", wakes.append)
    transport.side_effect = [_tool_response("late-call-1"), _reply_response()]
    old_reply = _send_tool_turn(
        client, csrf, old_conversation_id, expected_revision=0, call_id="late-call-1"
    )
    old_result = _result_for_turn(database, old_reply.json()["turns"][0]["id"])
    old_run_id = old_result["run_id"]
    set_id = old_result["canonical_set_id"]
    old_token = _accept_stage(
        database,
        old_run_id,
        [{"kind": "note", "title": "Old note", "body": "This late result must not win."}],
    )

    next_draft = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": f"tool-knowledge-next-{uuid4()}"}),
    )
    assert next_draft.status_code == 201, next_draft.text
    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"tool-knowledge-new-source-{uuid4()}"}),
        files={
            "file": (
                "updated-lesson.md",
                b"# Updated lesson\n\nNew RAG source.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    new_document_id = uploaded.json()["document"]["id"]
    selected = client.put(
        f"/api/v1/agent-versions/{next_draft.json()['id']}/knowledge-documents",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={
            "expected_revision": next_draft.json()["revision"],
            "document_ids": [new_document_id],
        },
    )
    assert selected.status_code == 200, selected.text
    published = client.post(
        f"/api/v1/agent-versions/{next_draft.json()['id']}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": f"tool-knowledge-publish-next-{uuid4()}"}),
        json={"expected_revision": selected.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    new_version_id = published.json()["id"]
    new_chat = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": csrf},
        json={"version_id": new_version_id},
    )
    assert new_chat.status_code == 200, new_chat.text

    transport.side_effect = [_tool_response("late-call-2"), _reply_response()]
    new_reply = _send_tool_turn(
        client, csrf, new_chat.json()["id"], expected_revision=0, call_id="late-call-2"
    )
    new_result = _result_for_turn(database, new_reply.json()["turns"][0]["id"])
    new_run_id = new_result["run_id"]
    assert new_run_id != old_run_id
    assert new_result["canonical_set_id"] == set_id
    assert wakes == [old_run_id, new_run_id]

    materialize_accepted_knowledge_generation(
        database.session_factory,
        old_run_id,
        old_token,
        data_root=app.state.settings.resolved_data_root,
    )
    with database.session() as db:
        old_run = db.get(KnowledgeGenerationRun, old_run_id)
        new_run = db.get(KnowledgeGenerationRun, new_run_id)
        assert old_run is not None and old_run.state == "blocked"
        assert old_run.safe_error_code == "authorization_revoked"
        assert new_run is not None and new_run.state == "pending"
        assert (
            db.scalar(
                select(KnowledgeGenerationSourceReceipt.document_id).where(
                    KnowledgeGenerationSourceReceipt.run_id == new_run_id
                )
            )
            == new_document_id
        )
        assert old_document_id != new_document_id
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeSetMarkdownVersion)
                .where(KnowledgeSetMarkdownVersion.knowledge_set_id == set_id)
            )
            == 0
        )

    new_token = _accept_stage(
        database,
        new_run_id,
        [{"kind": "note", "title": "Current note", "body": "The latest Agent version wins."}],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        new_run_id,
        new_token,
        data_root=app.state.settings.resolved_data_root,
    )
    with database.session() as db:
        latest_markdown = db.scalar(
            select(KnowledgeSetMarkdownVersion.markdown).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id
            )
        )
        assert latest_markdown is not None and "Current note" in latest_markdown
        assert "Old note" not in latest_markdown
        assert db.get(KnowledgeGenerationRun, new_run_id).agent_version_id == new_version_id
        assert db.get(KnowledgeGenerationRun, old_run_id).agent_version_id == version_id


def test_teacher_tool_wake_failure_keeps_receipt_and_never_claims_completion(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    _agent_id, _version_id, _document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nCall generate_agent_knowledge when asked.",
    )

    def fail_wake(run_id: str) -> None:
        _assert_postcommit_generation(database, run_id)
        raise RuntimeError("synthetic wake failure")

    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", fail_wake)
    transport.side_effect = [_tool_response("wake-failure-call"), _reply_response()]
    response = _send_tool_turn(
        client, csrf, conversation_id, expected_revision=0, call_id="wake-failure-call"
    )
    result = _result_for_turn(database, response.json()["turns"][0]["id"])
    assert result["status"] == "generating"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, result["run_id"])
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == response.json()["turns"][0]["id"],
                RuntimeToolReceipt.tool_name == GENERATE_AGENT_KNOWLEDGE_TOOL,
            )
        )
        assert run is not None and run.state == "pending"
        assert receipt is not None


def test_teacher_tool_is_not_exposed_to_students_or_cross_actor_or_revoked_source(
    runtime_tool_workspace: Any,
) -> None:
    _app, database, client, settings = runtime_tool_workspace
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nCall generate_agent_knowledge when asked.",
    )
    registry = runtime_registry()
    spec = registry[GENERATE_AGENT_KNOWLEDGE_TOOL]
    assert spec.authorization_class == "Teacher"
    assert spec.entry_kinds == frozenset({"agent"})
    with pytest.raises(ValidationError):
        GenerateAgentKnowledgeArguments.model_validate({"source_document_ids": [str(uuid4())]})

    _student, student_csrf = login(client, "bowen")
    student_chat = client.post(
        "/api/v1/conversations",
        headers={"X-CSRF-Token": student_csrf},
        json={"version_id": BASELINE_VERSION_ID},
    )
    assert student_chat.status_code == 200, student_chat.text
    with database.session() as db:
        student = get_auth_context(db, settings, client.cookies.get("maya_session"))
        assert student is not None
        assert GENERATE_AGENT_KNOWLEDGE_TOOL not in {
            item.name for item in exposed_tools(db, student, student_chat.json()["id"], registry)
        }
        row = db.get(Conversation, conversation_id)
        assert row is not None
        with pytest.raises(PlatformError) as cross_actor:
            generate_agent_knowledge(
                db,
                student,
                row,
                GenerateAgentKnowledgeArguments(),
                str(uuid4()),
                ToolCallIdentity(conversation_id, str(uuid4()), version_id, str(uuid4()), "call"),
            )
        assert cross_actor.value.code == "not_found"
        db.rollback()

    _teacher, csrf = login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        row = db.get(Conversation, conversation_id)
        actor = get_auth_context(db, settings, client.cookies.get("maya_session"))
        assert document is not None and row is not None and actor is not None
        document.workspace_state = "hidden"
        db.flush()
        with pytest.raises(PlatformError) as hidden_source:
            generate_agent_knowledge(
                db,
                actor,
                row,
                GenerateAgentKnowledgeArguments(),
                str(uuid4()),
                ToolCallIdentity(conversation_id, str(uuid4()), version_id, str(uuid4()), "call"),
            )
        assert hidden_source.value.code == "knowledge_generation_sources_unavailable"
        db.rollback()
    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_id == agent_id)
            )
            == 0
        )


def test_teacher_tool_revives_soft_deleted_canonical_set(
    runtime_tool_workspace: Any,
) -> None:
    # Courser-class Agents keep one uuid5 Set. Soft-deleting that row used to
    # make generate_agent_knowledge fail closed as not_found even with active RAG.
    _app, database, client, settings = runtime_tool_workspace
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, _document_id, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nCall generate_agent_knowledge when asked.",
    )
    with database.session() as db:
        actor = get_auth_context(db, settings, client.cookies.get("maya_session"))
        row = db.get(Conversation, conversation_id)
        assert actor is not None and row is not None
        first = generate_agent_knowledge(
            db,
            actor,
            row,
            GenerateAgentKnowledgeArguments(),
            str(uuid4()),
            ToolCallIdentity(conversation_id, str(uuid4()), version_id, str(uuid4()), "call"),
        )
        set_id = first["canonical_set_id"]
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        prior_epoch = set_row.authorization_epoch
        prior_metadata = set_row.metadata_revision
        set_row.deleted_at = now_utc()
        db.flush()
        revived = generate_agent_knowledge(
            db,
            actor,
            row,
            GenerateAgentKnowledgeArguments(),
            str(uuid4()),
            ToolCallIdentity(conversation_id, str(uuid4()), version_id, str(uuid4()), "call"),
        )
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        assert set_row.deleted_at is None
        assert set_row.authorization_epoch == prior_epoch + 1
        assert set_row.metadata_revision == prior_metadata + 1
        assert revived["canonical_set_id"] == set_id
        assert db.get(AgentKnowledgeSet, (agent_id, set_id)) is not None
        db.commit()


def test_an_old_chat_generates_from_the_swapped_rag_and_keeps_its_turn(
    runtime_tool_workspace: Any, monkeypatch: Any
) -> None:
    # The teacher swapped the RAG and published again, then asked an earlier
    # Chat for Knowledge. That Chat is pinned to the old version; generation
    # must follow the current version's RAG, and the reply after the Tool call
    # must not fail its own turn because the Agent's Knowledge just changed.
    app, database, client, base_settings = runtime_tool_workspace
    transport = _configure_chat(app, database, base_settings, monkeypatch)
    _teacher, csrf = login(client, "maya")
    agent_id, old_version_id, _old_document, conversation_id = _teacher_agent_chat(
        client,
        csrf,
        agent_markdown="# Course Guide\n\nWhen asked, call generate_agent_knowledge.",
    )
    monkeypatch.setattr(app.state.knowledge_generation_task_manager, "wake", lambda _run: None)
    draft = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": f"swap-draft-{uuid4()}"}),
    )
    assert draft.status_code == 201, draft.text
    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"swap-source-{uuid4()}"}),
        files={"file": ("new.md", b"# New lesson\n\nA swapped source.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    new_document = uploaded.json()["document"]["id"]
    selected = client.put(
        f"/api/v1/agent-versions/{draft.json()['id']}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": draft.json()["revision"], "document_ids": [new_document]},
    )
    assert selected.status_code == 200, selected.text
    published = client.post(
        f"/api/v1/agent-versions/{draft.json()['id']}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": f"swap-publish-{uuid4()}"}),
        json={"expected_revision": selected.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    new_version_id = published.json()["id"]
    assert new_version_id != old_version_id

    transport.side_effect = [_tool_response("swap-call-1"), _reply_response()]
    sent = _send_tool_turn(
        client, csrf, conversation_id, expected_revision=0, call_id="swap-call-1"
    )
    turn = sent.json()["turns"][0]
    assert turn["state"] == "ready", turn
    receipt = _result_for_turn(database, turn["id"])
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        assert run.agent_version_id == new_version_id
        assert [item["document_id"] for item in json.loads(run.source_manifest_json)] == [
            new_document
        ]
