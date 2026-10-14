from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Job,
    KnowledgeDocument,
    ProviderOperation,
    User,
)
from app.modules.agents.schemas import KnowledgeGenerationIntent
from app.modules.auth.service import AuthContext
from app.modules.knowledge_sets.generation import (
    block_claimed_generation,
    claim_generation_run,
    enqueue_generation_for_publish,
    recover_generation_runs_at_startup,
)
from app.modules.knowledge_sets.materialization import materialize_accepted_knowledge_generation
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeGenerationItem,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
from app.providers.control import (
    FIXED_MODELS,
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    KnowledgeGenerationAcceptedStageV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    confirm_export_manifest,
)
from app.providers.control_repository import ProviderRepository, ProviderRepositoryError
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _provider_policy(
    endpoint: str = ("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
) -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        endpoint=endpoint,
        privacy_notice_retrieved_at="2026-09-28T00:00:00Z",
        privacy_notice_sha256=_digest("privacy notice"),
        service_terms_retrieved_at="2026-09-28T00:00:00Z",
        service_terms_sha256=_digest("service terms"),
        faq_retrieved_at="2026-09-28T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-09-28",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _teacher_agent_with_source(
    client: TestClient,
    csrf: str,
    *,
    agent_markdown: str = "# Course Guide\n\nUse the selected courseware.",
) -> tuple[str, str, int, str]:
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2a-agent-{uuid4()}"}),
        json={"name": "Course Guide", "description": "Owner's source-backed Agent."},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    draft = agent["versions"][0]

    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2a-source-{uuid4()}"}),
        files={"file": ("lesson.md", b"# Lesson\n\nA source canary.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]

    selected = client.put(
        f"/api/v1/agent-versions/{draft['id']}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": draft["revision"], "document_ids": [document_id]},
    )
    assert selected.status_code == 200, selected.text
    edited = client.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(csrf),
        json={
            "expected_revision": selected.json()["revision"],
            "agent_md": agent_markdown,
        },
    )
    assert edited.status_code == 200, edited.text
    assert [row["id"] for row in edited.json()["enabled_documents"]] == [document_id]
    return agent["id"], draft["id"], edited.json()["revision"], document_id


def _publish(
    client: TestClient,
    csrf: str,
    version_id: str,
    revision: int,
    document_id: str,
    key: str,
):
    return client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={
            "expected_revision": revision,
            "generation": {"source_document_ids": [document_id]},
        },
    )


def test_done_creates_one_stable_owner_run_and_blocks_without_provider(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)

    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-initial-0001",
    )
    assert published.status_code == 200, published.text
    first = published.json()
    receipt = first["knowledge_generation"]
    assert first["state"] == "published"
    assert receipt["state"] == "pending"

    status = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "pending"

    _student, _student_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-sets/{receipt['knowledge_set_id']}").status_code == 404
    _teacher, csrf = login(client, "maya")

    replay = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-initial-0001",
    )
    assert replay.status_code == 200
    assert replay.json() == first

    next_version = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-next-version-00001"}),
    )
    assert next_version.status_code == 201, next_version.text
    second_publish = _publish(
        client,
        csrf,
        next_version.json()["id"],
        next_version.json()["revision"],
        document_id,
        "k2a-publish-new-key-0001",
    )
    assert second_publish.status_code == 200, second_publish.text
    assert second_publish.json()["knowledge_generation"]["run_id"] == receipt["run_id"]
    assert second_publish.json()["knowledge_generation"]["job_id"] == receipt["job_id"]

    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.operation == "knowledge_set.generate")
            )
            == 1
        )
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        assert len(run.input_key) == 64
        assert version_id not in run.input_key
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0

    block_claimed_generation(database.session_factory, receipt["run_id"])
    blocked = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "blocked"
    assert blocked.json()["safe_error_code"] == "provider_not_configured"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "blocked"
        assert job is not None and job.state == "failed"
        assert job.attempt == 1
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0
    assert settings.llm_provider == "mock"


def test_ordinary_teacher_done_with_rag_does_not_enqueue_and_chat_still_works(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, _document_id = _teacher_agent_with_source(
        client,
        csrf,
        agent_markdown=(
            "# Course Guide\n\nDo not prepare lessons or teaching materials. "
            "Answer questions using the selected courseware."
        ),
    )

    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-ordinary-done-no-run-01"}),
        json={"expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    published_body = published.json()
    assert published_body["state"] == "published"
    assert published_body["knowledge_snapshot_id"] is not None
    assert published_body["knowledge_generation"] is None

    conversation = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"version_id": version_id},
    )
    assert conversation.status_code == 200, conversation.text
    conversation_id = conversation.json()["id"]
    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "What does the courseware say?",
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"][-1]["state"] == "ready"

    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.operation == "knowledge_set.generate")
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0


@pytest.mark.parametrize("authorized", [True, False])
def test_provider_accepted_stage_is_atomic_and_suppresses_revoked_content(
    client: TestClient,
    app_bundle: Any,
    authorized: bool,
) -> None:
    _app, database, settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        f"k2b1-stage-{uuid4()}",
    )
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    with database.session() as db:
        token = claim_generation_run(db, run_id)
    assert token is not None

    repository = ProviderRepository(database)
    policy = _provider_policy()
    policy_id = repository.save_policy_snapshot(policy, snapshot_id=f"k2b1-policy-{uuid4()}")
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        agent = db.get(Agent, run.agent_id)
        version = db.get(AgentVersion, run.agent_version_id)
        assert agent is not None and version is not None
        group_id = agent.group_id
        course_id = agent.course_id
        md_hash = _digest(version.agent_md)
        run_claim_token = run.claim_token
    assert run_claim_token == token

    build_hash = _digest("k2b1 exact agent schema and prompt bundle")
    manifest = ExportManifestV1(
        scope_id=run_id,
        provider_operation="llm_knowledge_generate",
        model_key=FIXED_MODELS["llm_knowledge_generate"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=build_hash,
        persona_spec_hash=md_hash,
        fields=(
            ExportFieldV1("teacher_agent_instructions", md_hash),
            ExportFieldV1("authorized_courseware_text", _digest("selected source")),
            ExportFieldV1("topic_and_platform_rules", _digest("bounded output schema")),
        ),
    )
    manifest_id = repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=course_id,
        group_id=group_id,
        agent_version_id=version_id,
    )
    confirmation = confirm_export_manifest(
        manifest,
        policy,
        confirmed_at="2026-09-28T00:00:00Z",
    )
    repository.save_export_confirmation(manifest_id, confirmation)
    repository.save_scope_budget(
        run_id,
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=0,
            max_cost_cny=0,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        run.provider_manifest_hash = manifest.manifest_hash
        db.commit()

    request = ProviderReservationRequestV1(
        scope_id=run_id,
        provider_operation="llm_knowledge_generate",
        logical_item_id=run_id,
        attempt_no=1,
        request_hash=_digest(f"exact-final-wire:{run_id}"),
        max_tokens=0,
        max_cost_cny=0,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build_hash,
        model_key=manifest.model_key,
    )
    operation = repository.create_knowledge_generation_prepared(
        request,
        run_id=run_id,
        claim_token=token,
    )
    assert (
        repository.create_knowledge_generation_prepared(
            request,
            run_id=run_id,
            claim_token=token,
        ).id
        == operation.id
    )
    changed_request = ProviderReservationRequestV1(
        scope_id=run_id,
        provider_operation="llm_knowledge_generate",
        logical_item_id=run_id,
        attempt_no=1,
        request_hash=_digest(f"changed-wire:{run_id}"),
        max_tokens=0,
        max_cost_cny=0,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build_hash,
        model_key=manifest.model_key,
    )
    with pytest.raises(ProviderRepositoryError, match="cannot be reused"):
        repository.create_knowledge_generation_prepared(
            changed_request,
            run_id=run_id,
            claim_token=token,
        )
    reservation = repository.reserve(operation.id)
    assert reservation.state == "reserved"
    repository.transition(operation.id, expected="reserved", state="sending")

    canonical_stage = json.dumps(
        {"assets": [{"kind": "note", "title": "Canary", "body": "full text"}]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    stage = KnowledgeGenerationAcceptedStageV1(
        run_id=run_id,
        claim_token=token,
        operation_id=operation.id,
        request_hash=request.request_hash,
        manifest_hash=manifest.manifest_hash,
        policy_hash=policy.policy_hash,
        model_key=manifest.model_key,
        schema_hash=_digest("k2b1-schema"),
        canonical_stage_json=canonical_stage,
        canonical_stage_hash=_digest(canonical_stage),
        item_count=1,
    )
    persisted = repository.stage_knowledge_generation_accepted(
        stage,
        content_authorized=lambda _connection, _run_id, _claim: authorized,
    )

    assert persisted.safe_error_code == (None if authorized else "authorization_revoked_after_send")
    assert persisted.canonical_stage_json == (canonical_stage if authorized else None)
    assert persisted.item_count == (1 if authorized else 0)
    assert repository.knowledge_generation_stage(run_id) is not None
    assert repository.operation(operation.id).state == "accepted"
    assert repository.reservation(operation.id).state == "accepted"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.scalar(select(Job).where(Job.id == run.job_id)) if run is not None else None
        assert run is not None
        assert job is not None
        assert (run.safe_error_code, job.state) == (
            (None, "running") if authorized else ("authorization_revoked_after_send", "failed")
        )
        if authorized:
            assert run.state == "running" and run.claim_token == token
        else:
            assert run.state == "blocked" and run.claim_token is None

    if authorized:
        materialize_accepted_knowledge_generation(
            database.session_factory,
            run_id,
            token,
            data_root=settings.resolved_data_root,
        )
        with database.session() as db:
            run = db.get(KnowledgeGenerationRun, run_id)
            job = db.get(Job, run.job_id) if run is not None else None
            assert run is not None and run.state == "completed"
            assert job is not None and job.state == "completed"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(KnowledgeAsset)
                    .where(KnowledgeAsset.knowledge_set_id == run.knowledge_set_id)
                )
                == 1
            )
            assert (
                db.scalar(
                    select(KnowledgeGenerationItem.state).where(
                        KnowledgeGenerationItem.run_id == run_id
                    )
                )
                == "applied"
            )
    else:
        with database.session() as db:
            run = db.get(KnowledgeGenerationRun, run_id)
            assert run is not None and run.state == "blocked"
            assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0


@pytest.mark.parametrize(
    ("transport_outcome", "usage_payload"),
    [
        (
            "accepted",
            {"prompt_tokens": 24, "completion_tokens": 19, "total_tokens": 43},
        ),
        ("accepted", None),
        (
            "accepted",
            {"prompt_tokens": -1, "completion_tokens": 19, "total_tokens": 18},
        ),
        ("not_sent", None),
        ("unknown", None),
    ],
)
def test_teacher_generation_intent_confirms_exact_manifest_and_dispatches_once(
    client: TestClient,
    app_bundle: Any,
    transport_outcome: str,
    usage_payload: dict[str, int] | None,
) -> None:
    _app, database, base_settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(
        client,
        csrf,
        agent_markdown=(
            "# Course Guide\n\nUse the full selected text. "
            "Authorization and API key are ordinary teaching terms here."
        ),
    )
    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        f"k2b1-runtime-{uuid4()}",
    )
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        generated_set_id = run.knowledge_set_id
        generated_agent_id = run.agent_id
    set_detail = client.get(f"/api/v1/knowledge-sets/{generated_set_id}")
    assert set_detail.status_code == 200, set_detail.text
    assert set_detail.json()["generated_by_agent_id"] == generated_agent_id
    with database.session() as db:
        source_receipt_id = db.scalar(
            select(KnowledgeGenerationSourceReceipt.id).where(
                KnowledgeGenerationSourceReceipt.run_id == run_id
            )
        )
    assert isinstance(source_receipt_id, str)

    workspace = "syntheticknowledgeworkspace"
    endpoint = (
        f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    policy = _provider_policy(endpoint)
    repository = ProviderRepository(database)
    repository.save_policy_snapshot(policy, snapshot_id=f"k2b1-runtime-policy-{uuid4()}")
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-key",
            "dashscope_workspace_id": workspace,
            "dashscope_region": "cn-beijing",
        }
    )

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation
    from app.providers.llm_transport import (
        LLMAcceptanceUnknown,
        LLMTransportNotSent,
        LLMTransportResponse,
    )

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str], bytes]] = []

        def post_bytes(
            self,
            url: str,
            *,
            headers: dict[str, str],
            content: bytes,
            timeout: object,
        ) -> LLMTransportResponse:
            del timeout
            self.calls.append((url, headers, content))
            if transport_outcome == "not_sent":
                raise LLMTransportNotSent()
            if transport_outcome == "unknown":
                raise LLMAcceptanceUnknown()
            payload: dict[str, Any] = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "assets": [
                                        {
                                            "kind": "question",
                                            "prompt": "Why does the example matter?",
                                            "reference_answer": (
                                                "It links the idea to the source."
                                            ),
                                            "rubric": {
                                                "criteria": [
                                                    {
                                                        "label": "Explain",
                                                        "guidance": (
                                                            "Connect the idea and example."
                                                        ),
                                                        "points": 2,
                                                    }
                                                ],
                                                "total_points": 2,
                                            },
                                            "source_receipt_ids": [source_receipt_id],
                                        },
                                        {"kind": "question", "prompt": "invalid middle item"},
                                        {
                                            "kind": "note",
                                            "title": "Closing note",
                                            "body": "A valid item is kept after an invalid one.",
                                            "source_receipt_ids": [
                                                "00000000-0000-0000-0000-000000000001"
                                            ],
                                        },
                                    ]
                                },
                                ensure_ascii=False,
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
            if usage_payload is not None:
                payload["usage"] = usage_payload
            return LLMTransportResponse(status_code=200, payload=payload)

    fake = FakeTransport()
    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        settings,
        transport=fake,
    )

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        assert run.provider_manifest_hash is not None
        manifest_hash = run.provider_manifest_hash
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.provider_operation == "llm_knowledge_generate")
            )
            == 1
        )
    assert len(fake.calls) == 1
    job_id = published.json()["knowledge_generation"]["job_id"]
    owner_status = client.get(f"/api/v1/knowledge-generation-jobs/{job_id}")
    assert owner_status.status_code == 200, owner_status.text
    assert owner_status.json()["provider_manifest_hash"] == manifest_hash
    _student, _student_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/knowledge-generation-jobs/{job_id}").status_code == 404
    _teacher, csrf = login(client, "maya")

    manifest = repository.get_export_manifest(manifest_hash)
    assert manifest is not None and manifest.scope_id == run_id
    assert manifest.provider_operation == "llm_knowledge_generate"
    assert manifest.policy_hash == policy.policy_hash
    confirmation = repository.get_export_confirmation(manifest_hash)
    assert confirmation is not None
    assert confirmation.manifest_hash == manifest_hash
    assert confirmation.policy_hash == policy.policy_hash

    called_url, headers, wire_bytes = fake.calls[0]
    assert called_url == endpoint
    assert headers == {"Authorization": "Bearer fixture-key"}
    assert b"fixture-key" not in wire_bytes
    wire = json.loads(wire_bytes)
    assert [item["role"] for item in wire["messages"]] == ["system", "user"]
    assert "Authorization and API key" in wire["messages"][1]["content"]
    operation_rows = repository.operations(scope_id=run_id)
    assert len(operation_rows) == 1
    operation = operation_rows[0]
    assert operation.provider_operation == "llm_knowledge_generate"
    assert operation.request_hash == _digest(wire_bytes)
    if transport_outcome != "accepted":
        expected_state = "not_sent" if transport_outcome == "not_sent" else "acceptance_unknown"
        expected_count = 0 if transport_outcome == "not_sent" else 1
        assert operation.state == expected_state
        assert operation.request_count == operation.charged_request_count == expected_count
        assert repository.reservation(operation.id).state == expected_state
        assert repository.knowledge_generation_stage(run_id) is None
        assert repository.recover_llm_startup() == ()
        with database.session() as db:
            run = db.get(KnowledgeGenerationRun, run_id)
            job = db.scalar(select(Job).where(Job.id == run.job_id)) if run is not None else None
            assert run is not None and run.state == "blocked"
            assert job is not None and job.state == "failed"
            assert run.safe_error_code == (
                "llm_transport_not_sent"
                if transport_outcome == "not_sent"
                else "acceptance_unknown"
            )
        run_claimed_knowledge_generation(
            database.session_factory,
            run_id,
            settings,
            transport=fake,
        )
        assert len(fake.calls) == 1
        assert len(repository.operations(scope_id=run_id)) == 1
        return
    assert operation.state == "accepted"
    assert operation.request_count == operation.charged_request_count == 1
    recovered = repository.recover_llm_startup()
    assert len(recovered) == 1 and recovered[0].id == operation.id
    assert recovered[0].state == "accepted"
    assert len(fake.calls) == 1
    persisted_stage = repository.knowledge_generation_stage(run_id)
    assert persisted_stage is not None
    assert persisted_stage["canonical_stage_json"] is not None
    assert "reference_answer" in str(persisted_stage["canonical_stage_json"])
    assert persisted_stage["item_count"] == 3
    assert "synthetic-secret-never-send-to-real-provider" not in str(persisted_stage)
    assert persisted_stage["usage_json"] == (
        '{"input_tokens":24,"output_tokens":19,"total_tokens":43}'
        if usage_payload == {"prompt_tokens": 24, "completion_tokens": 19, "total_tokens": 43}
        else None
    )

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.scalar(select(Job).where(Job.id == run.job_id)) if run is not None else None
        assert run is not None and run.state == "completed"
        assert job is not None and job.state == "completed"
        assert run.safe_error_code is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.knowledge_set_id == run.knowledge_set_id)
            )
            == 2
        )
        assert db.scalar(select(func.count()).select_from(KnowledgeAssetVersionSource)) == 1
        items = db.scalars(
            select(KnowledgeGenerationItem)
            .where(KnowledgeGenerationItem.run_id == run_id)
            .order_by(KnowledgeGenerationItem.item_index)
        ).all()
        assert [item.state for item in items] == ["applied", "failed", "applied"]
        assert items[1].safe_error_code == "provider_asset_invalid"
        assert items[2].citation_unverified_count == 1
        assert items[2].safe_error_code == "citation_unverified"
        versions = db.scalars(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.generation_job_id == job.id)
        ).all()
        assert len(versions) == 2
        assert all(version.origin == "ai" for version in versions)
        markdown_versions = db.scalars(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == run.knowledge_set_id
            )
        ).all()
        assert len(markdown_versions) == 1
        status = client.get(f"/api/v1/knowledge-generation-jobs/{job.id}")
        assert status.status_code == 200, status.text
        assert status.json()["accepted_item_count"] == 3
        assert status.json()["materialized_item_count"] == 2
        assert status.json()["failed_item_count"] == 1
        assert status.json()["state"] == "completed"


def test_new_teacher_regeneration_resumes_exact_unconfirmed_run_once(
    client: TestClient,
    app_bundle: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, database, base_settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    publish_key = f"k2b1-unconfirmed-publish-{uuid4()}"
    published = _publish(client, csrf, version_id, revision, document_id, publish_key)
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    job_id = published.json()["knowledge_generation"]["job_id"]
    set_id = published.json()["knowledge_generation"]["knowledge_set_id"]
    with database.session() as db:
        initial_intent_generation = db.get(KnowledgeSet, set_id).generation_intent_seq

    workspace = "syntheticknowledgeworkspace"
    endpoint = (
        f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    policy = _provider_policy(endpoint)
    repository = ProviderRepository(database)
    repository.save_policy_snapshot(policy, snapshot_id=f"k2b1-unconfirmed-policy-{uuid4()}")
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "llm_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-key",
            "dashscope_workspace_id": workspace,
            "dashscope_region": "cn-beijing",
        }
    )

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation
    from app.modules.provider_disclosure.service import (
        ProviderDisclosureError,
        ProviderDisclosureService,
    )
    from app.providers.llm_transport import LLMTransportResponse

    class FakeTransport:
        def __init__(self) -> None:
            self.calls: list[bytes] = []

        def post_bytes(
            self,
            url: str,
            *,
            headers: dict[str, str],
            content: bytes,
            timeout: object,
        ) -> LLMTransportResponse:
            del timeout
            assert url == endpoint
            assert headers == {"Authorization": "Bearer fixture-key"}
            self.calls.append(content)
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
                                                "title": "Generated note",
                                                "body": "One exact run was resumed.",
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

    def require_new_teacher_intent(
        _service: Any,
        _request: Any,
        *,
        actor_user_id: str,
        manifest_ref: str | None = None,
        **_kwargs: Any,
    ) -> Any:
        del actor_user_id, manifest_ref
        raise ProviderDisclosureError(
            "provider_confirmation_required",
            "A newer explicit Teacher action is required.",
        )

    original_confirm = ProviderDisclosureService.confirm
    monkeypatch.setattr(ProviderDisclosureService, "confirm", require_new_teacher_intent)
    fake = FakeTransport()
    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        settings,
        transport=fake,
    )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.get(Job, job_id)
        assert run is not None and run.state == "blocked"
        assert run.safe_error_code == "provider_confirmation_required"
        assert run.provider_manifest_hash is not None
        assert run.provider_operation_id is None and run.request_hash is None
        assert job is not None and job.state == "failed"
        assert job.attempt == 1
        manifest_hash = run.provider_manifest_hash
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.scope_id == run_id)
            )
            == 0
        )
    assert fake.calls == []

    replayed_publish = _publish(client, csrf, version_id, revision, document_id, publish_key)
    assert replayed_publish.status_code == 200, replayed_publish.text
    assert replayed_publish.json()["knowledge_generation"]["run_id"] == run_id
    with database.session() as db:
        agent = db.get(Agent, _agent_id)
        version = db.get(AgentVersion, version_id)
        assert agent is not None and version is not None
        context = AuthContext(
            raw_session_token="",
            session=None,
            user=db.get(User, agent.owner_user_id),
            csrf_token="",
        )
        queued_publish = enqueue_generation_for_publish(
            db,
            context,
            agent,
            version,
            KnowledgeGenerationIntent(source_document_ids=[document_id]),
        )
        assert queued_publish.run.id == run_id
        assert queued_publish.run.state == "blocked"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.get(Job, job_id)
        assert run is not None and run.state == "blocked"
        assert job is not None and job.state == "failed"
    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        settings,
        transport=fake,
    )
    assert fake.calls == []
    assert repository.operations(scope_id=run_id) == ()

    monkeypatch.setattr(ProviderDisclosureService, "confirm", original_confirm)
    explicit_action_id = str(uuid4())
    regenerated = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(
            csrf,
            **{"Idempotency-Key": f"k2b1-unconfirmed-explicit-regen-{uuid4()}"},
        ),
        json={"action_id": explicit_action_id},
    )
    assert regenerated.status_code == 202, regenerated.text
    assert regenerated.json()["run_id"] == run_id
    assert regenerated.json()["job_id"] == job_id
    assert regenerated.json()["action_id"] == explicit_action_id
    replayed_regeneration = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(
            csrf,
            **{"Idempotency-Key": f"k2b1-unconfirmed-explicit-regen-retry-{uuid4()}"},
        ),
        json={"action_id": explicit_action_id},
    )
    assert replayed_regeneration.status_code == 202, replayed_regeneration.text
    assert replayed_regeneration.json()["run_id"] == run_id
    assert replayed_regeneration.json()["job_id"] == job_id
    assert replayed_regeneration.json()["action_id"] == explicit_action_id
    _student, student_csrf = login(client, "bowen")
    other_actor_replay = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(
            student_csrf,
            **{"Idempotency-Key": f"k2b1-unconfirmed-cross-actor-{uuid4()}"},
        ),
        json={"action_id": explicit_action_id},
    )
    assert other_actor_replay.status_code == 404, other_actor_replay.text
    from app.core.errors import PlatformError
    from app.modules.knowledge_sets.generation import _generation_action_replay

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        with pytest.raises(PlatformError) as changed_scope:
            _generation_action_replay(
                db,
                owner_user_id=run.owner_user_id,
                set_id=str(uuid4()),
                action_id=explicit_action_id,
                payload_hash="0" * 64,
            )
        assert changed_scope.value.code == "knowledge_generation_action_conflict"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.get(Job, job_id)
        set_row = db.get(KnowledgeSet, set_id)
        assert run is not None and run.state == "pending"
        assert run.safe_error_code is None
        assert job is not None and job.state == "pending"
        assert job.attempt == 1
        assert set_row is not None
        assert set_row.generation_intent_seq == initial_intent_generation
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
            )
            == 1
        )

    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        settings,
        transport=fake,
    )
    assert len(fake.calls) == 1
    operations = repository.operations(scope_id=run_id)
    assert len(operations) == 1
    assert operations[0].state == "accepted"
    assert operations[0].charged_request_count == 1
    confirmation = repository.get_export_confirmation(manifest_hash)
    assert confirmation is not None and confirmation.manifest_hash == manifest_hash
    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        set_row = db.get(KnowledgeSet, set_id)
        assert version is not None and set_row is not None
        version.agent_md += "\n\n# Different generation input\n"
        intent_generation_before_conflict = set_row.generation_intent_seq
        db.commit()
    _teacher, changed_payload_csrf = login(client, "maya")
    changed_payload_replay = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(
            changed_payload_csrf,
            **{"Idempotency-Key": f"k2b1-unconfirmed-payload-conflict-{uuid4()}"},
        ),
        json={"action_id": explicit_action_id},
    )
    assert changed_payload_replay.status_code == 409, changed_payload_replay.text
    assert changed_payload_replay.json()["code"] == "knowledge_generation_action_conflict"
    assert fake.calls and len(fake.calls) == 1
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        assert set_row.generation_intent_seq == intent_generation_before_conflict
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.scope_id == run_id)
            )
            == 1
        )
    with database.session() as db:
        owner_membership = db.scalar(
            select(CourseMember).where(
                CourseMember.user_id == db.get(Agent, _agent_id).owner_user_id,
                CourseMember.course_id == COURSE_ID,
            )
        )
        assert owner_membership is not None
        owner_membership.role = "student"
        db.commit()
    _demoted_owner, demoted_csrf = login(client, "maya")
    demoted_owner_replay = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(
            demoted_csrf,
            **{"Idempotency-Key": f"k2b1-unconfirmed-demoted-{uuid4()}"},
        ),
        json={"action_id": explicit_action_id},
    )
    assert demoted_owner_replay.status_code == 404, demoted_owner_replay.text


def test_concurrent_regeneration_business_action_replays_under_http_writer_lock(
    app_factory: Any,
) -> None:
    first_app, database, _settings = app_factory()
    second_app, second_database, _second_settings = app_factory()
    assert database.engine.url == second_database.engine.url
    with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
        _teacher, first_csrf = login(first_client, "maya")
        _teacher, second_csrf = login(second_client, "maya")
        agent_id, version_id, revision, document_id = _teacher_agent_with_source(
            first_client, first_csrf
        )
        published = _publish(
            first_client,
            first_csrf,
            version_id,
            revision,
            document_id,
            f"k2b1-concurrent-regeneration-publish-{uuid4()}",
        )
        assert published.status_code == 200, published.text
        set_id = published.json()["knowledge_generation"]["knowledge_set_id"]
        action_ids: list[str] = []

        def regenerate(
            client: TestClient,
            csrf: str,
            key: str,
            action_id: str,
            barrier: Barrier,
        ) -> Any:
            barrier.wait(timeout=10)
            return client.post(
                f"/api/v1/knowledge-sets/{set_id}/regenerate",
                headers=_headers(csrf, **{"Idempotency-Key": key}),
                json={"action_id": action_id},
            )

        for iteration in range(6):
            action_id = str(uuid4())
            action_ids.append(action_id)
            barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(
                    regenerate,
                    first_client,
                    first_csrf,
                    f"k2b1-race-{iteration}-first-{uuid4()}",
                    action_id,
                    barrier,
                )
                second = executor.submit(
                    regenerate,
                    second_client,
                    second_csrf,
                    f"k2b1-race-{iteration}-second-{uuid4()}",
                    action_id,
                    barrier,
                )
                responses = [first.result(timeout=30), second.result(timeout=30)]
            assert [response.status_code for response in responses] == [202, 202], [
                response.text for response in responses
            ]
            payloads = [response.json() for response in responses]
            assert payloads[0]["run_id"] == payloads[1]["run_id"]
            assert payloads[0]["job_id"] == payloads[1]["job_id"]
            assert payloads[0]["action_id"] == payloads[1]["action_id"] == action_id

        with database.session() as db:
            agent = db.get(Agent, agent_id)
            set_row = db.get(KnowledgeSet, set_id)
            assert agent is not None and set_row is not None
            all_runs = db.scalars(
                select(KnowledgeGenerationRun).where(
                    KnowledgeGenerationRun.knowledge_set_id == set_id
                )
            ).all()
            assert len(all_runs) == 7
            assert set_row.generation_intent_seq == 7
            for intent_generation, action_id in enumerate(action_ids, start=2):
                action_runs = db.scalars(
                    select(KnowledgeGenerationRun).where(
                        KnowledgeGenerationRun.knowledge_set_id == set_id,
                        KnowledgeGenerationRun.action_id == action_id,
                    )
                ).all()
                assert len(action_runs) == 1
                assert action_runs[0].intent_generation == intent_generation
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(ProviderOperation)
                        .where(ProviderOperation.scope_id == action_runs[0].id)
                    )
                    == 0
                )


def test_generation_source_mismatch_and_non_teacher_owner_fail_before_enqueue(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)

    mismatch = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-source-mismatch-0001"}),
        json={"expected_revision": revision, "generation": {"source_document_ids": [str(uuid4())]}},
    )
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["code"] == "generation_source_selection_stale"
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        assert db.get(AgentVersion, version_id).state == "draft"
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0

    with database.session() as db:
        member = db.scalar(
            select(CourseMember).where(
                CourseMember.user_id == agent.owner_user_id,
                CourseMember.course_id == COURSE_ID,
            )
        )
        assert member is not None
        member.role = "student"
        db.commit()
    denied = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-nonteacher-owner-01",
    )
    assert denied.status_code == 404, denied.text
    with database.session() as db:
        assert db.get(AgentVersion, version_id).state == "draft"
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0
        assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0


def test_generation_revocation_fences_worker_and_startup_reclaims_old_lease(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-revocation-01",
    )
    assert published.status_code == 200, published.text
    receipt = published.json()["knowledge_generation"]

    with database.session() as db:
        token = claim_generation_run(db, receipt["run_id"])
        assert token is not None
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "running"
        assert job is not None and job.state == "running"
        assert claim_generation_run(db, receipt["run_id"]) is None

    with database.session() as db:
        assert recover_generation_runs_at_startup(db) == 1
    with database.session() as db:
        token_after_recovery = claim_generation_run(db, receipt["run_id"])
        assert token_after_recovery is not None and token_after_recovery != token

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        db.commit()

    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.authorization_epoch += 1
        document.workspace_state = "hidden"
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    block_claimed_generation(database.session_factory, receipt["run_id"])
    blocked = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "blocked"
    assert blocked.json()["safe_error_code"] == "authorization_revoked"

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "blocked"
        assert job is not None and job.state == "failed"
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0


@pytest.mark.parametrize(
    ("fault_boundary", "committed"),
    [
        ("publish.after_final_db_prepare", False),
        ("publish.after_final_commit", True),
    ],
)
def test_done_and_generation_run_share_the_publish_commit(
    client: TestClient,
    app_bundle: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault_boundary: str,
    committed: bool,
) -> None:
    from app.modules.agents import router as agents_router

    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    original = agents_router.saga_checkpoint

    def fail_at(boundary: str) -> None:
        if boundary == fault_boundary:
            raise RuntimeError("injected publish boundary failure")
        original(boundary)

    monkeypatch.setattr(agents_router, "saga_checkpoint", fail_at)
    with pytest.raises(RuntimeError, match="injected publish boundary failure"):
        _publish(
            client,
            csrf,
            version_id,
            revision,
            document_id,
            "k2a-publish-fault-boundary-1",
        )
    monkeypatch.setattr(agents_router, "saga_checkpoint", original)

    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        runs = db.scalars(select(KnowledgeGenerationRun)).all()
        generation_jobs = db.scalars(
            select(Job).where(Job.operation == "knowledge_set.generate")
        ).all()
        if committed:
            assert version.state == "published"
            assert len(runs) == len(generation_jobs) == 1
        else:
            assert version.state == "draft"
            assert runs == []
            assert generation_jobs == []
            assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0

    if committed:
        retry = _publish(
            client,
            csrf,
            version_id,
            revision,
            document_id,
            "k2a-publish-fault-boundary-1",
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["knowledge_generation"]["run_id"] == runs[0].id
        with database.session() as db:
            assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 1


def test_publish_enqueue_reuses_inflight_run_for_same_version_and_sources(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    first = _publish(client, csrf, version_id, revision, document_id, "k2-debounce-publish-1")
    assert first.status_code == 200, first.text
    receipt = first.json()["knowledge_generation"]
    assert receipt is not None
    run_id = receipt["run_id"]
    job_id = receipt["job_id"]

    with database.session() as db:
        agent = db.get(Agent, agent_id)
        version = db.get(AgentVersion, version_id)
        assert agent is not None and version is not None
        owner = db.get(User, agent.owner_user_id)
        assert owner is not None
        context = AuthContext("", None, owner, "")
        intent = KnowledgeGenerationIntent(source_document_ids=[document_id])
        replay = enqueue_generation_for_publish(db, context, agent, version, intent)
        assert replay.created is False
        assert replay.run.id == run_id
        assert replay.job.id == job_id
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationRun)
                .where(KnowledgeGenerationRun.agent_id == agent_id)
            )
            == 1
        )
