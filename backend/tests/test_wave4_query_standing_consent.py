"""Focused regression tests for real query disclosure consent and accounting."""

from __future__ import annotations

import importlib
import struct
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import Database
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

from tests.conftest import login
from tests.test_wave3_mock_rag_delta import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _headers,
    _insert_sql_published_agent,
)
from tests.test_wave4_embedding_generation_query import _policy, _QueryTransport


def _realise_snapshot(database: Database, agent_id: str) -> None:
    vector = struct.pack(
        f"<{REAL_EMBEDDING_DIMENSION}f",
        1.0,
        *([0.0] * (REAL_EMBEDDING_DIMENSION - 1)),
    )
    with database.session() as db:
        agent = db.get(Agent, agent_id)
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
        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.snapshot_id == snapshot.id).all()
        assert chunks
        for chunk in chunks:
            chunk.embedding_blob = vector
            chunk.embedding_dimension = REAL_EMBEDDING_DIMENSION
            chunk.embedding_key = REAL_EMBEDDING_MODEL


def _query_setup(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    standing_consent: bool,
) -> tuple[Database, Settings, str, str, ProviderPolicySnapshotV1, _QueryTransport]:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        first_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="Standing Query A",
            evidence="A source record for the first query participant.",
            confirmed_persona=True,
        )
        second_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="Standing Query B",
            evidence="A source record for the second query participant.",
            confirmed_persona=True,
        )
        _realise_snapshot(database, first_agent_id)

        config = DashScopeEmbeddingConfig(api_key="fixture-query-key", workspace_id="fixture")
        policy = _policy(config.resolved_endpoint)
        ProviderRepository(database).save_policy_snapshot(
            policy,
            snapshot_id="standing-query-policy",
        )
        settings.embedding_provider = "dashscope"
        settings.llm_provider = "dashscope"
        settings.embedding_provider_policy_hash = policy.policy_hash
        settings.dashscope_api_key = "fixture-query-key"
        settings.dashscope_workspace_id = "fixture"
        settings.dashscope_region = "cn-beijing"
        settings.demo_mode = True
        settings.demo_auto_confirm_provider = standing_consent
        settings.provider_standing_consent = standing_consent

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
        teacher, csrf = login(client, "maya")
        del teacher
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "standing-query-debate-001"}),
            json={
                "topic": "How should the two source records be compared?",
                "participants": [
                    {"agent_id": first_agent_id, "stance_mode": "open"},
                    {"agent_id": second_agent_id, "stance_mode": "open"},
                ],
                "rule_set_id": MUTUAL_LEARNING_RULE_SET_ID,
                "round_count": 4,
                "turn_protocol": "segments_v2",
            "round_unit_caps": [200, 200, 200, 200]
        },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        with database.session() as db:
            turns = commit_start_plan(db, debate_id=debate_id)
            turn_id = str(turns[0].id)
            db.commit()
    return database, settings, str(debate_id), turn_id, policy, transport


# Provider disclosures are always auto-confirmed: with the standing-consent
# flags off the debate query proceeds and writes the same ledger rows.
@pytest.mark.parametrize("standing_consent", [True, False])
def test_standing_query_consent_confirms_exact_owner_manifest_and_runs_once(
    app_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    standing_consent: bool,
) -> None:
    database, settings, debate_id, turn_id, policy, transport = _query_setup(
        app_factory,
        monkeypatch,
        standing_consent=standing_consent,
    )
    generation_module = importlib.import_module("app.modules.debates.playback.generation_adapter")
    original_require = generation_module.require_exact_confirmation
    confirmation_checks: list[dict[str, object]] = []

    def observe_confirmation(*args: object, **kwargs: object) -> object:
        confirmation_checks.append(dict(kwargs))
        return original_require(*args, **kwargs)

    monkeypatch.setattr(generation_module, "require_exact_confirmation", observe_confirmation)
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        turn = db.get(DebateTurn, turn_id)
        assert debate is not None and turn is not None
        prepared = SqlTurnPreparer(settings=settings, llm=MockLLMProvider())(
            db,
            debate,
            turn,
            attempt=1,
            cancellation_generation=0,
        )
        assert prepared.retrieval_status == "matched"
        assert prepared.source_receipts
    assert len(confirmation_checks) == 2
    assert all(
        check.get("course_id") == COURSE_ID
        and check.get("group_id") == GROUP_DEMO_ID
        and isinstance(check.get("agent_version_id"), str)
        for check in confirmation_checks
    )
    assert len(transport.calls) == 1
    operations = tuple(
        item
        for item in ProviderRepository(database).operations(scope_id=debate_id)
        if item.provider_operation == "embedding_query"
    )
    assert len(operations) == 1
    assert operations[0].state == "succeeded"
    assert operations[0].request_count == 1
    assert operations[0].charged_request_count == 1
    confirmation = ProviderRepository(database).get_export_confirmation(
        operations[0].export_manifest_hash
    )
    assert confirmation is not None
    assert confirmation.policy_hash == policy.policy_hash
