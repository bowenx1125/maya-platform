"""Fake-transport product test for real query retrieval and Evidence receipts."""

from __future__ import annotations

import hashlib
import importlib
import struct
from collections.abc import Mapping
from typing import Any

import pytest
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeSnapshot,
    ProviderExportManifest,
    ProviderReservation,
)
from app.modules.agents.persona import compile_persona
from app.modules.debates.generation.mutual_learning_policy import (
    MUTUAL_LEARNING_RULE_SET_ID,
)
from app.modules.debates.models import Debate, DebateTurn
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.setup.service import commit_start_plan
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportResponse,
)
from app.modules.knowledge.providers.query_manifest import (
    QueryManifestError,
    ensure_real_query_export_manifest,
)
from app.modules.knowledge.providers.snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
)
from app.modules.knowledge.vector import REAL_EMBEDDING_IDENTITY
from app.providers.control import ProviderPolicySnapshotV1
from app.providers.control_repository import ProviderRepository
from app.providers.llm import MockLLMProvider
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_wave3_mock_rag_delta import (
    COURSE_ID,
    GROUP_BOWEN_ID,
    GROUP_KAIKAI_ID,
    _headers,
    _insert_sql_published_agent,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _QueryTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> EmbeddingTransportResponse:
        del headers, timeout
        payload = dict(json)
        self.calls.append(payload)
        nested = payload.get("input")
        assert isinstance(nested, dict)
        texts = nested.get("texts")
        assert isinstance(texts, list)
        vector = [1.0] + [0.0] * (REAL_EMBEDDING_DIMENSION - 1)
        return EmbeddingTransportResponse(
            200,
            {
                "model": REAL_EMBEDDING_MODEL,
                "data": [
                    {"index": index, "embedding": vector} for index, _text in enumerate(texts)
                ],
            },
        )


def _policy(endpoint: str) -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        endpoint=endpoint,
        privacy_notice_retrieved_at="2026-08-31T00:00:00Z",
        privacy_notice_sha256=_digest("privacy"),
        service_terms_retrieved_at="2026-08-31T00:00:00Z",
        service_terms_sha256=_digest("terms"),
        faq_retrieved_at="2026-08-31T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-08-31",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def test_real_query_requires_exact_teacher_confirmation_and_reuses_durable_stage(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        first_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Real Query A",
            evidence=(
                "Accountable recommendation governance needs transparent evidence and public "
                "oversight."
            ),
            confirmed_persona=True,
        )
        second_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Real Query B",
            evidence="A complementary classroom governance perspective.",
            confirmed_persona=True,
        )
        raw_private_marker = "RAW_PRIVATE_PERSONA_MARKER"
        initial_position = "文化知识分享必须保留上下文、来源与共同责任。"
        raw_persona = f"""# Real Query A

## Identity

- Role: 文化知识学习引导者
- Historical or cultural context: 私密原文标记 {raw_private_marker} 只用于查询边界测试。

## Cultural lens

- 跨代互惠
- 语言与土地相连

## Core values

- 共同责任
- 谦逊倾听

## Initial position

{initial_position}

## Speaking style

- Tone: 平静、尊重且清晰
- Argument pattern: 先说明背景，再区分事实与价值
- Concession style: 承认开放学习的好处，再说明保护意义的必要条件
- Question style: 询问谁参与决定以及如何处理不确定性

## Debate strategy

- 连接语言、土地、记忆与共同责任

## Boundaries

- 不把一般推理说成来源支持的事实
"""
        compiled = compile_persona(raw_persona, expected_name="Real Query A")
        assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
        with database.session() as db:
            agent = db.get(Agent, first_agent_id)
            assert agent is not None and agent.current_published_version_id
            version = db.get(AgentVersion, agent.current_published_version_id)
            assert version is not None and version.knowledge_snapshot_id
            version.agent_md = raw_persona
            version.raw_agent_md_hash = compiled.source_agent_md_hash
            version.persona_spec_json = compiled.canonical_json
            version.persona_spec_hash = compiled.persona_spec_hash
            version.persona_compiler_version = compiled.compiler_version
            version.persona_diagnostics_json = "[]"
            version.persona_confirmation_revision = version.revision
            version.student_confirmed_at = version.updated_at
            version.persona_confirming_user_id = "wave4-test-student"
            snapshot = db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
            assert snapshot is not None
            snapshot.embedding_provider = REAL_EMBEDDING_PROVIDER
            snapshot.embedding_model_key = REAL_EMBEDDING_MODEL
            snapshot.embedding_region = REAL_EMBEDDING_REGION
            snapshot.embedding_dimension = REAL_EMBEDDING_DIMENSION
            snapshot.embedding_policy_version = REAL_EMBEDDING_POLICY_VERSION
            vector = struct.pack(
                f"<{REAL_EMBEDDING_DIMENSION}f",
                1.0,
                *([0.0] * (REAL_EMBEDDING_DIMENSION - 1)),
            )
            chunks = db.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.snapshot_id == snapshot.id)
            ).all()
            assert chunks
            for chunk in chunks:
                chunk.embedding_blob = vector
                chunk.embedding_dimension = REAL_EMBEDDING_DIMENSION
                chunk.embedding_key = REAL_EMBEDDING_MODEL

        config = DashScopeEmbeddingConfig(
            api_key="fixture-secret-never-enters-query-payload",
            workspace_id="fixture",
        )
        policy = _policy(config.resolved_endpoint)
        ProviderRepository(database).save_policy_snapshot(
            policy,
            snapshot_id="real-query-policy",
        )
        settings.embedding_provider = "dashscope"
        settings.dashscope_api_key = "fixture-secret-never-enters-query-payload"
        settings.dashscope_workspace_id = "fixture"
        settings.dashscope_region = "cn-beijing"
        settings.provider_policy_hash = policy.policy_hash
        transport = _QueryTransport()
        adapter = DashScopeEmbeddingAdapter(config, transport)
        generation_module = importlib.import_module(
            "app.modules.debates.playback.generation_adapter"
        )
        original_build_turn_subqueries = generation_module.build_turn_subqueries
        observed_contexts: list[Any] = []

        def capture_build_turn_subqueries(context: Any) -> Any:
            queries = original_build_turn_subqueries(context)
            observed_contexts.append(context)
            return queries

        monkeypatch.setattr(
            generation_module,
            "select_embedding_provider",
            lambda _settings: adapter,
        )
        monkeypatch.setattr(
            generation_module,
            "build_turn_subqueries",
            capture_build_turn_subqueries,
        )

        _teacher, csrf = login(client, "teacher-demo")
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "real-query-debate-create-001"}),
            json={
                "topic": "How should recommendation systems be governed?",
                "participants": [
                    {"agent_id": first_agent_id, "stance_mode": "open"},
                    {"agent_id": second_agent_id, "stance_mode": "open"},
                ],
                "rule_set_id": MUTUAL_LEARNING_RULE_SET_ID,
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            turns = commit_start_plan(db, debate_id=debate_id)
            first_turn_id = turns[0].id
            db.commit()
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            turn = db.get(DebateTurn, first_turn_id)
            assert debate is not None and turn is not None
            with pytest.raises(PlatformError) as required:
                SqlTurnPreparer(settings=settings, llm=MockLLMProvider())(
                    db,
                    debate,
                    turn,
                    attempt=1,
                    cancellation_generation=0,
                )
            assert required.value.code == "provider_confirmation_required"
            manifest_hash = required.value.details["manifest_hash"]
            assert required.value.details["turn_id"] == first_turn_id
            assert transport.calls == []
            db.rollback()

        pending = client.get(
            "/api/v1/provider/data-call/pending",
            params={"scope_id": debate_id},
        )
        assert pending.status_code == 200, pending.text
        pending_body = pending.json()
        assert pending_body == {
            "scope_id": debate_id,
            "items": [
                {
                    "manifest_hash": manifest_hash,
                    "turn_id": first_turn_id,
                    "confirmation_revision": 1,
                    "confirmed": False,
                }
            ],
        }
        assert not any(
            forbidden in pending.text.casefold()
            for forbidden in ("dashscope", "text-embedding", "endpoint", "workspace")
        )
        prepared_operations = tuple(
            operation
            for operation in ProviderRepository(database).operations(scope_id=debate_id)
            if operation.provider_operation == "embedding_query"
        )
        assert len(prepared_operations) == 1
        prepared_operation = prepared_operations[0]
        assert (
            prepared_operation.state,
            prepared_operation.request_count,
            prepared_operation.charged_request_count,
            prepared_operation.reservation_id,
        ) == ("prepared", 0, 0, None)
        assert ProviderRepository(database).get_scope_budget(debate_id) is None
        with database.session() as db:
            assert (
                db.scalar(
                    select(ProviderReservation.id).where(
                        ProviderReservation.operation_id == prepared_operation.id
                    )
                )
                is None
            )

        disclosure = client.get(
            "/api/v1/provider/data-call/disclosure",
            params={"manifest_hash": manifest_hash},
        )
        assert disclosure.status_code == 200, disclosure.text
        disclosed = disclosure.json()
        confirmed = client.post(
            "/api/v1/provider/data-call/disclosure/confirm",
            headers=_headers(csrf),
            json={
                "policy_hash": policy.policy_hash,
                "manifest_hash": manifest_hash,
                "expected_revision": disclosed["confirmation_revision"],
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        confirmed_pending = client.get(
            "/api/v1/provider/data-call/pending",
            params={"scope_id": debate_id},
        )
        assert confirmed_pending.status_code == 200
        assert confirmed_pending.json()["items"][0]["confirmed"] is True

        for _run in range(2):
            with database.session() as db:
                debate = db.get(Debate, debate_id)
                assert debate is not None
                turn = db.get(DebateTurn, first_turn_id)
                assert turn is not None
                prepared = SqlTurnPreparer(settings=settings, llm=MockLLMProvider())(
                    db,
                    debate,
                    turn,
                    attempt=1,
                    cancellation_generation=0,
                )
                assert prepared.retrieval_status == "matched"
                assert prepared.sources
                assert prepared.source_receipts
                assert prepared.evidence_trace
        assert len(transport.calls) == 1
        assert transport.calls[0]["parameters"] == {"dimension": 1024}
        assert "api_key" not in transport.calls[0]
        assert observed_contexts
        projected = observed_contexts[0].participant
        assert projected.persona is not None
        assert projected.persona.initial_position == initial_position
        assert projected.initial_position_summary == ""
        assert projected.current_position_summary == ""
        assert raw_private_marker in projected.agent_md
        opening_queries = original_build_turn_subqueries(observed_contexts[0])
        assert opening_queries[0].query_kind == "viewpoint"
        assert initial_position in opening_queries[0].text
        assert raw_private_marker not in opening_queries[0].text
        nested = transport.calls[0]["input"]
        assert isinstance(nested, dict)
        query_texts = nested["texts"]
        assert isinstance(query_texts, list) and len(query_texts) == 1
        assert initial_position in query_texts[0]
        assert raw_private_marker not in query_texts[0]
        operations = ProviderRepository(database).operations(scope_id=debate_id)
        query_operations = [
            operation
            for operation in operations
            if operation.provider_operation == "embedding_query"
        ]
        assert len(query_operations) == 1
        assert query_operations[0].state == "succeeded"


def test_unsafe_real_query_is_rejected_before_manifest_persistence(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app):
        config = DashScopeEmbeddingConfig(api_key="fixture", workspace_id="fixture")
        with database.session() as db:
            with pytest.raises(QueryManifestError) as raised:
                ensure_real_query_export_manifest(
                    database,
                    db=db,
                    scope_id="query-scope",
                    turn_id="query-turn",
                    course_id="course-id",
                    group_id="group-id",
                    agent_version_id="version-id",
                    snapshot_id="snapshot-id",
                    identity=REAL_EMBEDDING_IDENTITY,
                    transcript_hash=_digest("transcript"),
                    persona_spec_hash=_digest("persona"),
                    subqueries=(("viewpoint", "student_id: 123456"),),
                    policy=_policy(config.resolved_endpoint),
                )
            assert raised.value.code == "embedding_outbound_data_forbidden"
        with database.engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(ProviderExportManifest)
                ).scalar_one()
                == 0
            )
    database.dispose()
