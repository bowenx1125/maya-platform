"""Focused W4-LLM-A ledger and bucket invariants."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.providers.control import (
    EMBEDDING_QUERY_BUCKET,
    LLM_DEBATE_TURN_BUCKET,
    InMemoryProviderOperationRepository,
    LLMAcceptedStageV1,
    OperationStateError,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository, ScopeBudgetAmbiguous
from sqlalchemy import inspect, text


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request(*, scope_id: str, operation: str, item: str) -> ProviderReservationRequestV1:
    return ProviderReservationRequestV1(
        scope_id=scope_id,
        provider_operation=operation,
        logical_item_id=item,
        attempt_no=1,
        request_hash=_hash(f"request:{scope_id}:{operation}:{item}"),
        max_tokens=10,
        max_cost_cny=0.001,
        policy_hash=_hash("policy"),
        export_manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
        model_key="qwen3.7-plus-2026-05-26" if operation == "llm_debate_turn" else "",
    )


def test_in_memory_budget_buckets_do_not_collide() -> None:
    repository = InMemoryProviderOperationRepository(
        scope_budgets={
            ("debate", EMBEDDING_QUERY_BUCKET): ProviderScopeBudgetV1(
                max_requests=1,
                max_total_tokens=10,
                max_cost_cny=0.001,
                budget_bucket=EMBEDDING_QUERY_BUCKET,
            ),
            ("debate", LLM_DEBATE_TURN_BUCKET): ProviderScopeBudgetV1(
                max_requests=1,
                max_total_tokens=10,
                max_cost_cny=0.001,
                budget_bucket=LLM_DEBATE_TURN_BUCKET,
            ),
        }
    )
    query = repository.create_prepared(
        _request(scope_id="debate", operation="embedding_query", item="query")
    )
    llm = repository.create_prepared(
        _request(scope_id="debate", operation="llm_debate_turn", item="turn")
    )
    assert repository.reserve(query.id).budget_bucket == EMBEDDING_QUERY_BUCKET
    assert repository.reserve(llm.id).budget_bucket == LLM_DEBATE_TURN_BUCKET


def test_llm_stage_is_immutable_and_required_for_success() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=10,
            max_cost_cny=0.01,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    request = _request(scope_id="debate", operation="llm_debate_turn", item="turn")
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    stage = LLMAcceptedStageV1(
        operation_id=operation.id,
        turn_id="turn",
        attempt_no=1,
        request_hash=request.request_hash,
        prompt_hash=_hash("prompt"),
        prompt_contract_version="PromptRequestV1",
        schema_hash=_hash("schema"),
        tokenizer_id="test-tokenizer",
        tokenizer_hash=_hash("tokenizer"),
        rule_set_hash=_hash("rules"),
        persona_spec_hash=_hash("persona"),
        transcript_hash=_hash("transcript"),
        receipt_hash=_hash("receipts"),
        policy_hash=request.policy_hash,
        export_manifest_hash=request.export_manifest_hash,
        build_manifest_hash=_hash("build"),
        model_key="qwen3.7-plus-2026-05-26",
        output_json=json.dumps({"ok": True}),
        output_hash=_hash("output"),
        prompt_tokens=4,
        cached_input_tokens=1,
        completion_tokens=2,
        total_tokens=6,
        input_price_cny_per_million="1",
        cached_input_price_cny_per_million="1",
        output_price_cny_per_million="1",
        estimated_cost_cny="0.000006",
    )
    assert repository.stage_llm_accepted(stage) == stage
    assert repository.mark_succeeded(operation.id).state == "succeeded"
    with pytest.raises(OperationStateError, match="immutable"):
        repository.stage_llm_accepted(replace(stage, output_hash=_hash("other")))


def test_llm_startup_never_treats_unstaged_accepted_output_as_complete() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=10,
            max_cost_cny=0.01,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    request = _request(scope_id="debate", operation="llm_debate_turn", item="turn")
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    repository.mark_accepted(operation.id, response_hash=_hash("response"))
    assert repository.recover_one(operation.id).state == "acceptance_unknown"


def test_0014_schema_has_composite_budget_and_llm_stage(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'schema.sqlite3'}")
    database.upgrade_schema()
    inspector = inspect(database.engine)
    assert inspector.get_pk_constraint("provider_scope_budgets")["constrained_columns"] == [
        "scope_id",
        "budget_bucket",
    ]
    assert inspector.has_table("llm_accepted_stages")
    assert {item["name"] for item in inspector.get_indexes("provider_export_manifests")} >= {
        "ix_provider_export_manifests_debate",
        "ix_provider_export_manifests_turn",
    }
    database.dispose()


def test_sql_budget_lookup_is_ambiguous_without_bucket(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'budget.sqlite3'}")
    database.upgrade_schema()
    repository = ProviderRepository(database, require_export_confirmation=False)
    repository.save_scope_budget(
        "scope",
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=1,
            max_cost_cny=0.01,
            budget_bucket=EMBEDDING_QUERY_BUCKET,
        ),
    )
    repository.save_scope_budget(
        "scope",
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=1,
            max_cost_cny=0.01,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    with pytest.raises(ScopeBudgetAmbiguous, match="more than one budget bucket"):
        repository.get_scope_budget("scope")
    assert repository.get_scope_budget("scope", LLM_DEBATE_TURN_BUCKET) is not None
    database.dispose()


def _migration_config(database: Database) -> Config:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    config.set_main_option("sqlalchemy.url", database.database_url)
    config.attributes["database_url"] = database.database_url
    return config


def _populate_0013_budget(database: Database, *operations: str) -> None:
    now = datetime.now(UTC).isoformat(sep=" ")
    digest = "a" * 64
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_scope_budgets "
                "(scope_id,max_requests,max_total_tokens,max_cost_cny,allocated_requests,"
                "allocated_total_tokens,allocated_cost_cny,created_at,updated_at) "
                "VALUES ('legacy',20,100,0.1,0,0,0,:now,:now)"
            ),
            {"now": now},
        )
        for index, provider_operation in enumerate(operations):
            connection.execute(
                text(
                    "INSERT INTO provider_operations "
                    "(id,scope_id,provider_operation,logical_item_id,attempt_no,request_hash,"
                    "max_tokens,max_cost_cny,policy_hash,export_manifest_hash,build_manifest_hash,"
                    "model_key,state,request_count,charged_request_count,created_at,updated_at) "
                    "VALUES (:id,'legacy',:provider_operation,:item,1,:digest,1,0,:digest,:digest,"
                    ":digest,'', 'prepared',0,0,:now,:now)"
                ),
                {
                    "id": f"operation-{index}",
                    "provider_operation": provider_operation,
                    "item": f"item-{index}",
                    "digest": digest,
                    "now": now,
                },
            )


def test_0014_populated_upgrade_backfills_only_unambiguous_bucket(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'populated.sqlite3'}")
    config = _migration_config(database)
    command.upgrade(config, "0013_embedding_identity_stage")
    _populate_0013_budget(database, "embedding_query")
    command.upgrade(config, "head")
    with database.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT budget_bucket FROM provider_scope_budgets WHERE scope_id='legacy'")
            ).scalar_one()
            == EMBEDDING_QUERY_BUCKET
        )
    command.downgrade(config, "0013_embedding_identity_stage")
    command.upgrade(config, "head")
    database.dispose()


def test_0014_ambiguous_populated_backfill_fails_closed(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'ambiguous.sqlite3'}")
    config = _migration_config(database)
    command.upgrade(config, "0013_embedding_identity_stage")
    _populate_0013_budget(database, "embedding", "embedding_query")
    with pytest.raises(RuntimeError, match="multiple operation buckets"):
        command.upgrade(config, "head")
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0013_embedding_identity_stage"
        )
    database.dispose()
