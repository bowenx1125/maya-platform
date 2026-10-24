"""SQLite persistence tests for the server-only ProviderDataCall ledger."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from app.core.db import Database
from app.core.models import (
    ProviderOperation,
    ProviderReservation,
    ProviderScopeBudget,
)
from app.providers.control import (
    FIXED_MODELS,
    LLM_DEBATE_TURN_BUCKET,
    ExportFieldV1,
    ExportManifestV1,
    ProviderAcceptanceUnknownResultV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    confirm_export_manifest,
)
from app.providers.control_repository import (
    PolicyExportStale,
    ProviderRepository,
    ProviderRepositoryError,
    ScopeBudgetMissing,
)
from sqlalchemy import Table, inspect, select
from sqlalchemy.exc import IntegrityError

from tests.postgres_db import named_url


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-30T00:00:00Z",
        privacy_notice_sha256=_digest("privacy"),
        service_terms_retrieved_at="2026-08-30T00:00:00Z",
        service_terms_sha256=_digest("terms"),
        faq_retrieved_at="2026-08-30T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-08-30",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def _manifest(policy: ProviderPolicySnapshotV1, *, scope_id: str = "scope-1") -> ExportManifestV1:
    return ExportManifestV1(
        scope_id=scope_id,
        provider_operation="embedding",
        model_key=FIXED_MODELS["embedding"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest("build-1"),
        persona_spec_hash=_digest("persona-1"),
        fields=(ExportFieldV1("current_evidence_excerpt", _digest("evidence")),),
    )


def _request(
    manifest: ExportManifestV1,
    *,
    attempt_no: int = 1,
    logical_item_id: str = "batch-0",
) -> ProviderReservationRequestV1:
    return ProviderReservationRequestV1(
        scope_id=manifest.scope_id,
        provider_operation=manifest.provider_operation,
        logical_item_id=logical_item_id,
        attempt_no=attempt_no,
        request_hash=_digest(f"request-{attempt_no}-{logical_item_id}"),
        max_tokens=100,
        max_cost_cny=0.001,
        policy_hash=manifest.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=manifest.build_manifest_hash,
        model_key=manifest.model_key,
    )


def _repository_with_confirmed_manifest(
    tmp_path: Path,
    *,
    scope_id: str = "scope-1",
    require_export_confirmation: bool = True,
) -> tuple[Database, ProviderRepository, ExportManifestV1]:
    database = Database(named_url(f"{tmp_path / f'{scope_id}.sqlite3'}"))
    database.upgrade_schema()
    repository = ProviderRepository(
        database,
        require_export_confirmation=require_export_confirmation,
    )
    policy = _policy()
    policy_row_id = repository.save_policy_snapshot(policy, snapshot_id=f"policy-{scope_id}")
    manifest = _manifest(policy, scope_id=scope_id)
    manifest_row_id = repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_row_id,
        manifest_id=f"manifest-{scope_id}",
    )
    confirmation = confirm_export_manifest(manifest, policy, confirmed_at="2026-08-30T01:00:00Z")
    repository.save_export_confirmation(
        manifest_row_id,
        confirmation,
        confirmation_id=f"confirmation-{scope_id}",
    )
    repository.save_scope_budget(
        scope_id,
        ProviderScopeBudgetV1(max_requests=20, max_total_tokens=120_000, max_cost_cny=0.10),
    )
    return database, repository, manifest


def test_0010_creates_server_only_tables_without_key_or_payload_columns(tmp_path: Path) -> None:
    database = Database(named_url(f"{tmp_path / 'schema.sqlite3'}"))
    database.upgrade_schema()
    inspector = inspect(database.engine)
    expected = {
        "provider_policy_snapshots",
        "provider_export_manifests",
        "provider_export_confirmations",
        "provider_scope_budgets",
        "provider_operations",
        "provider_reservations",
    }
    assert expected <= set(inspector.get_table_names())
    for table in expected:
        columns = {item["name"] for item in inspector.get_columns(table)}
        assert not columns.intersection(
            {"api_key", "workspace_id", "payload_json", "request_body", "response_body"}
        )
    assert {
        "uq_provider_operations_attempt",
    } <= {item["name"] for item in inspector.get_unique_constraints("provider_operations")}


def test_policy_manifest_confirmation_round_trip_and_stale_hash_fails_closed(
    tmp_path: Path,
) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    policy = repository.get_policy_snapshot(manifest.policy_hash)
    assert policy is not None and policy.policy_hash == manifest.policy_hash
    persisted_manifest = repository.get_export_manifest(manifest.manifest_hash)
    assert persisted_manifest is not None
    assert (
        repository.ensure_export_manifest(
            manifest,
            policy_snapshot_id="policy-scope-1",
        )
        == "manifest-scope-1"
    )
    confirmation = repository.get_export_confirmation(manifest.manifest_hash)
    assert confirmation is not None
    assert confirmation.manifest_hash == manifest.manifest_hash
    assert confirmation.policy_hash == manifest.policy_hash
    with pytest.raises(ProviderRepositoryError, match="different ownership"):
        repository.ensure_export_manifest(
            manifest,
            policy_snapshot_id="policy-scope-1",
            course_id="different-course",
        )
    request = _request(manifest)
    repository.assert_hashes_current(request)
    assert repository.get_scope_budget(manifest.scope_id) is not None

    changed_policy = replace(_policy(), snapshot_revision=2)
    with pytest.raises(PolicyExportStale):
        repository.assert_hashes_current(
            ProviderReservationRequestV1(
                **cast(Any, {**request.as_record(), "policy_hash": changed_policy.policy_hash})
            )
        )
    database.dispose()


def test_orm_repository_runs_exact_lifecycle_and_persists_hashes(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    operation = repository.create_prepared(_request(manifest))
    assert operation.state == "prepared"
    reservation = repository.reserve(operation.id)
    assert reservation.state == "reserved"
    hydrated = repository.operation(operation.id)
    assert hydrated.reservation_id == reservation.id
    assert (
        repository.transition(operation.id, expected="reserved", state="sending").state == "sending"
    )
    with pytest.raises(ProviderRepositoryError, match="staged response hash"):
        repository.mark_accepted(operation.id, response_hash="x" * 64)
    accepted = repository.mark_accepted(operation.id, response_hash=_digest("response"))
    assert accepted.state == "accepted"
    succeeded = repository.mark_succeeded(operation.id)
    assert succeeded.state == "succeeded"
    assert succeeded.policy_hash == manifest.policy_hash
    assert succeeded.export_manifest_hash == manifest.manifest_hash
    with database.engine.connect() as connection:
        budget = (
            connection.execute(
                select(ProviderScopeBudget.__table__).where(
                    ProviderScopeBudget.scope_id == manifest.scope_id
                )
            )
            .mappings()
            .one()
        )
        assert budget["allocated_requests"] == 1
        assert budget["allocated_total_tokens"] == 100
        operation_row = (
            connection.execute(
                select(ProviderOperation.__table__).where(ProviderOperation.id == operation.id)
            )
            .mappings()
            .one()
        )
        reservation_row = (
            connection.execute(
                select(ProviderReservation.__table__).where(
                    ProviderReservation.id == reservation.id
                )
            )
            .mappings()
            .one()
        )
        assert operation_row["state"] == "succeeded"
        assert reservation_row["state"] == "succeeded"
    database.dispose()


def test_not_sent_releases_budget_and_new_attempt_keeps_unique_history(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    repository.save_scope_budget(
        manifest.scope_id,
        ProviderScopeBudgetV1(max_requests=1, max_total_tokens=100, max_cost_cny=0.01),
        replace_empty=True,
    )
    first = repository.create_prepared(_request(manifest))
    repository.reserve(first.id)
    repository.transition(first.id, expected="reserved", state="sending")
    assert repository.mark_not_sent(first.id).state == "not_sent"
    assert repository.reservation(first.id).state == "not_sent"
    second = repository.create_prepared(_request(manifest, attempt_no=2))
    assert repository.reserve(second.id).state == "reserved"
    with pytest.raises(IntegrityError):
        with database.engine.begin() as connection:
            connection.execute(
                cast(Table, ProviderOperation.__table__)
                .insert()
                .values(
                    id="duplicate",
                    scope_id=manifest.scope_id,
                    provider_operation="embedding",
                    logical_item_id="batch-0",
                    attempt_no=2,
                    request_hash=_digest("duplicate"),
                    max_tokens=1,
                    max_cost_cny=0,
                    policy_hash=manifest.policy_hash,
                    export_manifest_hash=manifest.manifest_hash,
                    build_manifest_hash=manifest.build_manifest_hash,
                    model_key=manifest.model_key,
                    state="prepared",
                    created_at=repository._now(),
                    updated_at=repository._now(),
                )
            )
    database.dispose()


def _knowledge_operation(
    tmp_path: Path,
    scope_id: str,
) -> tuple[Database, ProviderRepository, str]:
    database = Database(named_url(f"{tmp_path / f'{scope_id}.sqlite3'}"))
    database.upgrade_schema()
    repository = ProviderRepository(database)
    policy = _policy()
    policy_id = repository.save_policy_snapshot(policy, snapshot_id=f"policy-{scope_id}")
    manifest = ExportManifestV1(
        scope_id=scope_id,
        provider_operation="llm_knowledge_generate",
        model_key=FIXED_MODELS["llm_knowledge_generate"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest("knowledge-build"),
        persona_spec_hash=_digest("knowledge-agent-md"),
        fields=(ExportFieldV1("teacher_agent_instructions", _digest("agent-md")),),
    )
    manifest_id = repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        manifest_id=f"manifest-{scope_id}",
    )
    confirmation = confirm_export_manifest(manifest, policy, confirmed_at="2026-09-28T00:00:00Z")
    repository.save_export_confirmation(manifest_id, confirmation)
    repository.save_scope_budget(
        scope_id,
        ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=0,
            max_cost_cny=0,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        ),
    )
    request = ProviderReservationRequestV1(
        scope_id=scope_id,
        provider_operation=manifest.provider_operation,
        logical_item_id=scope_id,
        attempt_no=1,
        request_hash=_digest(f"wire:{scope_id}"),
        max_tokens=0,
        max_cost_cny=0,
        policy_hash=manifest.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=manifest.build_manifest_hash,
        model_key=manifest.model_key,
    )
    return database, repository, repository.create_prepared(request).id


def test_knowledge_not_sent_releases_reservation_and_clears_charged_count(
    tmp_path: Path,
) -> None:
    database, repository, operation_id = _knowledge_operation(tmp_path, "knowledge-not-sent")
    repository.reserve(operation_id)
    repository.transition(operation_id, expected="reserved", state="sending")

    operation = repository.mark_not_sent(operation_id, safe_error_code="llm_transport_not_sent")

    assert operation.state == "not_sent"
    assert operation.request_count == operation.charged_request_count == 0
    assert repository.reservation(operation_id).state == "not_sent"
    with database.engine.connect() as connection:
        budget = (
            connection.execute(
                select(ProviderScopeBudget.__table__).where(
                    ProviderScopeBudget.scope_id == "knowledge-not-sent"
                )
            )
            .mappings()
            .one()
        )
    assert budget["allocated_requests"] == 0
    assert budget["allocated_total_tokens"] == 0
    assert budget["allocated_cost_cny"] == 0
    database.dispose()


def test_knowledge_startup_recovery_marks_sending_unknown_and_never_reopens_it(
    tmp_path: Path,
) -> None:
    database, repository, operation_id = _knowledge_operation(tmp_path, "knowledge-unknown")
    repository.reserve(operation_id)
    repository.transition(operation_id, expected="reserved", state="sending")

    recovered = repository.recover_llm_startup()

    assert len(recovered) == 1
    assert recovered[0].id == operation_id
    assert recovered[0].state == "acceptance_unknown"
    assert recovered[0].charged_request_count == 1
    assert repository.recover_llm_startup() == ()
    assert repository.operation(operation_id).state == "acceptance_unknown"
    database.dispose()


def test_acceptance_unknown_retains_budget_and_never_auto_retries(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    repository.save_scope_budget(
        manifest.scope_id,
        ProviderScopeBudgetV1(max_requests=1, max_total_tokens=100, max_cost_cny=0.01),
        replace_empty=True,
    )
    first = repository.create_prepared(_request(manifest))
    repository.reserve(first.id)
    repository.transition(first.id, expected="reserved", state="sending")
    unknown = repository.mark_acceptance_unknown(first.id)
    result = ProviderAcceptanceUnknownResultV1("acceptance_unknown", unknown)
    assert result.retry_allowed is False
    assert repository.reservation(first.id).state == "acceptance_unknown"
    with database.engine.connect() as connection:
        budget = (
            connection.execute(
                select(ProviderScopeBudget.__table__).where(
                    ProviderScopeBudget.scope_id == manifest.scope_id
                )
            )
            .mappings()
            .one()
        )
        assert budget["allocated_requests"] == 1
    other = repository.create_prepared(_request(manifest, logical_item_id="independent-item"))
    assert repository.reserve(other.id).state == "reserved"
    assert repository.operation(first.id).charged_request_count == 1
    database.dispose()


def test_sqlite_scope_reservation_is_atomic_under_concurrency(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(
        tmp_path, scope_id="concurrent"
    )
    repository.save_scope_budget(
        manifest.scope_id,
        ProviderScopeBudgetV1(max_requests=1, max_total_tokens=100, max_cost_cny=0.01),
        replace_empty=True,
    )
    operations = [
        repository.create_prepared(
            _request(manifest, attempt_no=index + 1, logical_item_id=f"batch-{index}")
        )
        for index in range(8)
    ]

    def reserve(operation_id: str) -> str:
        repository.reserve(operation_id)
        return "reserved"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(reserve, (operation.id for operation in operations)))
    assert outcomes.count("reserved") == 8
    assert outcomes.count("rejected") == 0
    database.dispose()


def test_startup_recovery_maps_reserved_and_sending_and_preserves_staged_acceptance(
    tmp_path: Path,
) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    reserved = repository.create_prepared(_request(manifest, logical_item_id="reserved"))
    repository.reserve(reserved.id)
    assert repository.recover_one(reserved.id).state == "not_sent"
    assert repository.recover_one(reserved.id).state == "not_sent"

    sending = repository.create_prepared(_request(manifest, logical_item_id="sending"))
    repository.reserve(sending.id)
    repository.transition(sending.id, expected="reserved", state="sending")
    assert repository.recover_one(sending.id).state == "acceptance_unknown"

    staged = repository.create_prepared(_request(manifest, logical_item_id="staged"))
    repository.reserve(staged.id)
    repository.transition(staged.id, expected="reserved", state="sending")
    repository.mark_accepted(staged.id, response_hash=_digest("staged"))
    assert repository.recover_one(staged.id).state == "accepted"
    database.dispose()


def test_missing_scope_budget_and_invalid_orm_state_fail_closed(tmp_path: Path) -> None:
    database, repository, manifest = _repository_with_confirmed_manifest(tmp_path)
    repository_without_budget = ProviderRepository(database, require_export_confirmation=False)
    operation = repository_without_budget.create_prepared(
        ProviderReservationRequestV1(
            scope_id="missing-scope",
            provider_operation="embedding",
            logical_item_id="batch-0",
            attempt_no=1,
            request_hash=_digest("missing"),
            max_tokens=1,
            max_cost_cny=0.001,
            policy_hash=manifest.policy_hash,
            export_manifest_hash=manifest.manifest_hash,
            build_manifest_hash=manifest.build_manifest_hash,
            model_key=manifest.model_key,
        )
    )
    repository_without_budget.save_scope_budget(
        "other-scope",
        ProviderScopeBudgetV1(max_requests=1, max_total_tokens=1, max_cost_cny=0.01),
    )
    with pytest.raises(ScopeBudgetMissing):
        repository.reserve(operation.id)
    with pytest.raises(IntegrityError):
        with database.engine.begin() as connection:
            connection.execute(
                cast(Table, ProviderOperation.__table__)
                .insert()
                .values(
                    id="bad-state",
                    scope_id=manifest.scope_id,
                    provider_operation="embedding",
                    logical_item_id="bad",
                    attempt_no=9,
                    request_hash=_digest("bad-state"),
                    max_tokens=1,
                    max_cost_cny=0,
                    policy_hash=manifest.policy_hash,
                    export_manifest_hash=manifest.manifest_hash,
                    build_manifest_hash=manifest.build_manifest_hash,
                    model_key=manifest.model_key,
                    state="invalid",
                    created_at=repository._now(),
                    updated_at=repository._now(),
                )
            )
    database.dispose()
