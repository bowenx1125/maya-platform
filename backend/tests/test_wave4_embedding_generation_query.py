"""Fake-transport product test for real query retrieval and Evidence receipts."""

from __future__ import annotations

import hashlib
import importlib
import struct
from collections.abc import Mapping
from typing import Any

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion, KnowledgeChunk, KnowledgeSnapshot
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
from app.modules.knowledge.providers.snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
)
from app.providers.control import ProviderPolicySnapshotV1
from app.providers.control_repository import ProviderRepository
from app.providers.llm import MockLLMProvider
from fastapi.testclient import TestClient
from sqlalchemy import select

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
        with database.session() as db:
            agent = db.get(Agent, first_agent_id)
            assert agent is not None and agent.current_published_version_id
            version = db.get(AgentVersion, agent.current_published_version_id)
            assert version is not None and version.knowledge_snapshot_id
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
        monkeypatch.setattr(
            generation_module,
            "select_embedding_provider",
            lambda _settings: adapter,
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
        operations = ProviderRepository(database).operations(scope_id=debate_id)
        query_operations = [
            operation
            for operation in operations
            if operation.provider_operation == "embedding_query"
        ]
        assert len(query_operations) == 1
        assert query_operations[0].state == "succeeded"
