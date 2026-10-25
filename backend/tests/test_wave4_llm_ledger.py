"""Focused W4-LLM-A ledger and bucket invariants."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from app.core.config import configured_llm_model
from app.core.db import Database
from app.providers.control import (
    EMBEDDING_QUERY_BUCKET,
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestError,
    ExportManifestV1,
    InMemoryProviderOperationRepository,
    LLMAcceptedStageV1,
    OperationStateError,
    ProviderControlError,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    canonical_json_bytes,
)
from app.providers.control_repository import (
    ProviderRepository,
    ProviderRepositoryError,
    ScopeBudgetAmbiguous,
)
from app.providers.llm_recovery import recover_llm_startup
from sqlalchemy import inspect, text

from tests.postgres_db import named_url


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _output_hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _valid_stage(*, operation_id: str = "missing-operation") -> LLMAcceptedStageV1:
    return LLMAcceptedStageV1(
        operation_id=operation_id,
        turn_id="turn",
        attempt_no=1,
        request_hash=_hash("request"),
        prompt_hash=_hash("prompt"),
        prompt_contract_version="PromptRequestV1",
        schema_hash=_hash("schema"),
        tokenizer_id="test-tokenizer",
        tokenizer_hash=_hash("tokenizer"),
        rule_set_hash=_hash("rules"),
        persona_spec_hash=_hash("persona"),
        transcript_hash=_hash("transcript"),
        receipt_hash=_hash("receipts"),
        policy_hash=_hash("policy"),
        export_manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
        model_key=configured_llm_model(),
        output_json=json.dumps({"ok": True}),
        output_hash=_output_hash({"ok": True}),
        prompt_tokens=4,
        cached_input_tokens=1,
        completion_tokens=2,
        total_tokens=6,
        input_price_cny_per_million="1",
        cached_input_price_cny_per_million="1",
        output_price_cny_per_million="1",
        estimated_cost_cny="0.000006",
    )


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
        model_key=configured_llm_model() if operation == "llm_debate_turn" else "",
    )


def _valid_policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-30T00:00:00Z",
        privacy_notice_sha256=_hash("privacy"),
        service_terms_retrieved_at="2026-08-30T00:00:00Z",
        service_terms_sha256=_hash("terms"),
        faq_retrieved_at="2026-08-30T00:00:00Z",
        faq_sha256=_hash("faq"),
        no_training_basis="payg-api-terms-2026-08-30",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def test_legacy_llm_alias_is_read_only_for_new_operation_and_manifest_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProviderControlError, match="closed budget bucket"):
        _request(scope_id="debate", operation="llm_debate", item="turn")

    policy = _valid_policy()
    legacy_manifest = ExportManifestV1(
        scope_id="debate",
        provider_operation="llm_debate",
        model_key=configured_llm_model(),
        policy_hash=policy.policy_hash,
        build_manifest_hash=_hash("build"),
        persona_spec_hash=_hash("persona"),
        fields=(ExportFieldV1("topic_and_platform_rules", _hash("rules")),),
    )
    with pytest.raises(ExportManifestError, match="read-only"):
        replace(legacy_manifest, max_attempts=2)

    database = Database(named_url(f"{tmp_path / 'legacy-alias.sqlite3'}"))
    database.initialize_schema()
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    with pytest.raises(ProviderRepositoryError, match="legacy"):
        repository.save_export_manifest(legacy_manifest, policy_snapshot_id=policy_id)
    database.dispose()


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
        model_key=configured_llm_model(),
        output_json=json.dumps({"ok": True}),
        output_hash=_output_hash({"ok": True}),
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
        repository.stage_llm_accepted(
            replace(stage, output_json='{"ok":false}', output_hash=_output_hash({"ok": False}))
        )
    with pytest.raises(ProviderControlError, match="hash"):
        replace(stage, output_json='{"ok":false}')


def test_sql_llm_stage_rejects_tampered_output_before_insert(tmp_path: Path) -> None:
    database = Database(named_url(f"{tmp_path / 'stage-tamper.sqlite3'}"))
    database.initialize_schema()
    repository = ProviderRepository(database, require_export_confirmation=False)
    stage = _valid_stage()
    object.__setattr__(stage, "output_json", '{"ok":false}')
    with pytest.raises(ProviderControlError, match="hash"):
        repository.stage_llm_accepted(stage)
    with database.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM llm_accepted_stages")).scalar_one() == 0
        )
    database.dispose()


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


def test_llm_startup_recovery_does_not_touch_other_provider_buckets() -> None:
    repository = InMemoryProviderOperationRepository(
        scope_budgets={
            ("debate", EMBEDDING_QUERY_BUCKET): ProviderScopeBudgetV1(
                max_requests=1,
                max_total_tokens=10,
                max_cost_cny=0.01,
                budget_bucket=EMBEDDING_QUERY_BUCKET,
            ),
            ("debate", LLM_DEBATE_TURN_BUCKET): ProviderScopeBudgetV1(
                max_requests=1,
                max_total_tokens=10,
                max_cost_cny=0.01,
                budget_bucket=LLM_DEBATE_TURN_BUCKET,
            ),
        }
    )
    embedding = repository.create_prepared(
        _request(scope_id="debate", operation="embedding_query", item="query")
    )
    llm = repository.create_prepared(
        _request(scope_id="debate", operation="llm_debate_turn", item="turn")
    )
    repository.reserve(embedding.id)
    repository.reserve(llm.id)

    recovered = recover_llm_startup(repository)

    assert tuple(item.id for item in recovered) == (llm.id,)
    assert repository.get(llm.id).state == "not_sent"
    assert repository.get(embedding.id).state == "reserved"


def test_0014_schema_has_composite_budget_and_llm_stage(tmp_path: Path) -> None:
    database = Database(named_url(f"{tmp_path / 'schema.sqlite3'}"))
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
    database = Database(named_url(f"{tmp_path / 'budget.sqlite3'}"))
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


def test_sql_budget_reservation_and_release_are_bucket_isolated(tmp_path: Path) -> None:
    database = Database(named_url(f"{tmp_path / 'bucket-isolation.sqlite3'}"))
    database.upgrade_schema()
    repository = ProviderRepository(database, require_export_confirmation=False)
    for bucket in (EMBEDDING_QUERY_BUCKET, LLM_DEBATE_TURN_BUCKET):
        repository.save_scope_budget(
            "shared-scope",
            ProviderScopeBudgetV1(
                max_requests=1,
                max_total_tokens=10,
                max_cost_cny=0.01,
                budget_bucket=bucket,
            ),
        )
    operations = [
        repository.create_prepared(
            _request(scope_id="shared-scope", operation=operation, item=f"item-{index}")
        )
        for index, operation in enumerate(
            ("embedding_query", "embedding_query", "llm_debate_turn", "llm_debate_turn")
        )
    ]

    def reserve(operation_id: str) -> str:
        repository.reserve(operation_id)
        return "reserved"

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = tuple(executor.map(reserve, (operation.id for operation in operations)))
    assert outcomes.count("reserved") == 4
    assert outcomes.count("rejected") == 0
    query_budget = repository.get_scope_budget("shared-scope", EMBEDDING_QUERY_BUCKET)
    llm_budget = repository.get_scope_budget("shared-scope", LLM_DEBATE_TURN_BUCKET)
    assert query_budget is not None and query_budget.max_requests == 1
    assert llm_budget is not None and llm_budget.max_requests == 1
    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT budget_bucket, allocated_requests FROM provider_scope_budgets "
                "WHERE scope_id='shared-scope' ORDER BY budget_bucket"
            )
        ).all()
    assert dict(rows) == {
        EMBEDDING_QUERY_BUCKET: 2,
        LLM_DEBATE_TURN_BUCKET: 2,
    }
    for operation, outcome in zip(operations, outcomes, strict=True):
        if outcome == "reserved":
            repository.mark_not_sent(operation.id)
    with database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT budget_bucket, allocated_requests FROM provider_scope_budgets "
                "WHERE scope_id='shared-scope' ORDER BY budget_bucket"
            )
        ).all()
    assert dict(rows) == {
        EMBEDDING_QUERY_BUCKET: 0,
        LLM_DEBATE_TURN_BUCKET: 0,
    }
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


@pytest.mark.parametrize("persistent", [False, True])
def test_accepted_usage_above_estimate_is_recorded(tmp_path: Path, persistent: bool) -> None:
    database = Database(named_url(f"{tmp_path / 'unbounded-usage.sqlite3'}"))
    budget = ProviderScopeBudgetV1(
        max_requests=1, max_total_tokens=1, max_cost_cny=0, budget_bucket=LLM_DEBATE_TURN_BUCKET
    )
    if persistent:
        from tests.test_wave4_llm_recovery import _seed_turn

        database.upgrade_schema()
        _seed_turn(database, debate_id="scope", turn_id="turn")
        repository = ProviderRepository(database, require_export_confirmation=False)
        repository.save_scope_budget("scope", budget)
    else:
        repository = InMemoryProviderOperationRepository(default_budget=budget)
    request = _request(scope_id="scope", operation="llm_debate_turn", item="turn")
    operation = repository.create_prepared(request)
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    stage = replace(
        _valid_stage(operation_id=operation.id),
        request_hash=request.request_hash,
        prompt_tokens=400_000,
        completion_tokens=300_000,
        input_tokens=400_000,
        output_tokens=300_000,
        total_tokens=700_000,
        estimated_cost_cny="0.7",
        actual_cost_cny="100",
    )
    assert repository.stage_llm_accepted(stage) == stage
    assert repository.mark_succeeded(operation.id).charged_request_count == 1
    from tests.test_wave4_llm_recovery import _assert_stage_equal

    stored = repository.get_llm_accepted_stage(operation.id)
    assert stored is not None
    _assert_stage_equal(stored, stage)
    database.dispose()
