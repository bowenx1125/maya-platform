"""Deterministic ProviderDataCallV1 control tests; no network or provider calls."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from app.providers.control import (
    FIXED_MODELS,
    FIXED_REGION,
    BudgetExceeded,
    DuplicateOperation,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestError,
    ExportManifestV1,
    InMemoryProviderOperationRepository,
    OperationStateError,
    PolicyValidationError,
    ProviderAcceptanceUnknownError,
    ProviderAcceptanceUnknownResultV1,
    ProviderFailureResultV1,
    ProviderNotSentError,
    ProviderNotSentResultV1,
    ProviderOperationV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
    ProviderSuccessResultV1,
    can_transition,
    canonical_json_bytes,
    confirm_export_manifest,
    execute_provider_call,
    safe_provider_error_code,
    startup_recovery_state,
    validate_provider_preflight,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _policy(**changes: object) -> ProviderPolicySnapshotV1:
    values: dict[str, object] = {
        "privacy_notice_retrieved_at": "2026-08-30T00:00:00Z",
        "privacy_notice_sha256": _digest("privacy"),
        "service_terms_retrieved_at": "2026-08-30T00:00:00Z",
        "service_terms_sha256": _digest("terms"),
        "faq_retrieved_at": "2026-08-30T00:00:00Z",
        "faq_sha256": _digest("faq"),
        "no_training_basis": "payg-api-terms-2026-08-30",
        "prompt_response_logging_disabled": True,
        "inference_log_backflow_disabled": True,
        "optional_content_logging_disabled": True,
        "service_improvement_disabled": True,
        "storage_disclosed": True,
        "retention_setting": "unknown",
    }
    values.update(changes)
    return ProviderPolicySnapshotV1(**cast(Any, values))


def _manifest(policy: ProviderPolicySnapshotV1, **changes: object) -> ExportManifestV1:
    values: dict[str, object] = {
        "scope_id": "snapshot-build-1",
        "provider_operation": "embedding",
        "model_key": FIXED_MODELS["embedding"],
        "policy_hash": policy.policy_hash,
        "build_manifest_hash": _digest("build-1"),
        "persona_spec_hash": _digest("persona-1"),
        "fields": (
            ExportFieldV1("current_evidence_excerpt", _digest("evidence")),
            ExportFieldV1("opaque_local_id", _digest("opaque-id")),
        ),
    }
    values.update(changes)
    return ExportManifestV1(**cast(Any, values))


def _request(
    *,
    scope_id: str = "snapshot-build-1",
    attempt_no: int = 1,
    logical_item_id: str = "batch-0",
    policy_hash: str | None = None,
    export_hash: str | None = None,
) -> ProviderReservationRequestV1:
    return ProviderReservationRequestV1(
        scope_id=scope_id,
        provider_operation="embedding",
        logical_item_id=logical_item_id,
        attempt_no=attempt_no,
        request_hash=_digest(f"request-{scope_id}-{logical_item_id}-{attempt_no}"),
        max_tokens=100,
        max_cost_cny=0.001,
        policy_hash=policy_hash or _digest("policy"),
        export_manifest_hash=export_hash or _digest("export"),
        build_manifest_hash=_digest("build-1"),
        model_key=FIXED_MODELS["embedding"],
    )


def test_policy_and_export_hashes_are_canonical_and_cas_bound() -> None:
    policy = _policy()
    manifest = _manifest(policy)
    confirmation = confirm_export_manifest(
        manifest,
        policy,
        confirmed_at="2026-08-30T01:00:00Z",
        expected_manifest_hash=manifest.manifest_hash,
        expected_policy_hash=policy.policy_hash,
    )
    result = validate_provider_preflight(
        policy,
        manifest,
        confirmation,
        scope_id=manifest.scope_id,
        provider_operation=manifest.provider_operation,
        model_key=manifest.model_key,
    )
    assert result.policy_hash == policy.policy_hash
    assert result.export_manifest_hash == manifest.manifest_hash
    assert policy.canonical_dict() == policy.canonical_dict()
    assert canonical_json_bytes(policy.canonical_dict())
    changed_policy = _policy(snapshot_revision=2)
    with pytest.raises(PolicyValidationError, match="stale"):
        validate_provider_preflight(
            changed_policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation=manifest.provider_operation,
            model_key=manifest.model_key,
        )
    changed_manifest = _manifest(policy, operation_revision=2)
    with pytest.raises(ExportManifestError, match="stale"):
        validate_provider_preflight(
            policy,
            changed_manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation=manifest.provider_operation,
            model_key=manifest.model_key,
        )


def test_policy_requires_explicit_beijing_account_and_logging_controls() -> None:
    with pytest.raises(PolicyValidationError, match="controls"):
        _policy(optional_content_logging_disabled=None)
    with pytest.raises(PolicyValidationError, match="account"):
        _policy(account_product="coding_plan")
    with pytest.raises(PolicyValidationError, match="region"):
        _policy(region="us-east-1")
    with pytest.raises(PolicyValidationError, match="storage"):
        _policy(storage_disclosed=False)


def test_export_manifest_and_payload_reject_secret_identity_and_private_fields() -> None:
    policy = _policy()
    with pytest.raises(ExportManifestError, match="allowlisted"):
        ExportFieldV1("api_key", _digest("secret"))
    manifest = _manifest(policy)
    confirmation = confirm_export_manifest(manifest, policy, confirmed_at="now")
    with pytest.raises(ExportManifestError, match="forbidden"):
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation="embedding",
            model_key=manifest.model_key,
            payload={"input": {"student_name": "Ada"}},
        )
    with pytest.raises(ExportManifestError, match="forbidden"):
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation="embedding",
            model_key=manifest.model_key,
            payload={"teacher_note": "internal"},
        )
    with pytest.raises(ExportManifestError, match="forbidden"):
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation="embedding",
            model_key=manifest.model_key,
            payload={"value": "api_key=secret"},
        )
    assert "api_key" not in str(manifest.canonical_dict()).casefold()
    assert "authorization" not in str(manifest.canonical_dict()).casefold()


def test_exact_prepared_reserved_sending_accepted_succeeded_lifecycle() -> None:
    repository = InMemoryProviderOperationRepository()
    operation = repository.create_prepared(_request())
    assert operation.state == "prepared"
    reservation = repository.reserve(operation.id)
    assert reservation.state == "reserved"
    sending = repository.transition(operation.id, expected="reserved", state="sending")
    assert sending.state == "sending"
    accepted = repository.mark_accepted(operation.id, response_hash=_digest("response"))
    assert accepted.state == "accepted"
    succeeded = repository.mark_succeeded(operation.id)
    assert succeeded.state == "succeeded"
    assert succeeded.request_count == 1
    assert succeeded.charged_request_count == 1
    assert repository.reservation(operation.id).state == "succeeded"
    with pytest.raises(OperationStateError):
        repository.transition(operation.id, expected="succeeded", state="sending")


def test_not_sent_releases_scope_allowance_but_unique_attempt_remains() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1, max_total_tokens=100, max_cost_cny=0.01
        )
    )
    first = repository.create_prepared(_request())
    repository.reserve(first.id)
    repository.transition(first.id, expected="reserved", state="sending")
    not_sent = repository.mark_not_sent(first.id)
    assert not_sent.state == "not_sent"
    assert repository.reservation(first.id).state == "not_sent"
    second = repository.create_prepared(_request(attempt_no=2))
    assert repository.reserve(second.id).state == "reserved"
    with pytest.raises(DuplicateOperation):
        repository.create_prepared(_request(attempt_no=2))


def test_acceptance_unknown_retains_allowance_and_forbids_retry() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1, max_total_tokens=100, max_cost_cny=0.01
        )
    )
    operation = repository.create_prepared(_request())
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    unknown = repository.mark_acceptance_unknown(operation.id)
    assert unknown.state == "acceptance_unknown"
    assert repository.reservation(operation.id).state == "acceptance_unknown"
    assert not can_transition("acceptance_unknown", "sending")
    assert startup_recovery_state("sending") == "acceptance_unknown"
    with pytest.raises(BudgetExceeded):
        second = repository.create_prepared(_request(attempt_no=2))
        repository.reserve(second.id)
    result = ProviderAcceptanceUnknownResultV1("acceptance_unknown", unknown)
    assert result.retry_allowed is False
    assert result.requires_reconciliation


def test_abandoning_an_uncertain_attempt_does_not_silently_release_consumed_cap() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1, max_total_tokens=100, max_cost_cny=0.01
        )
    )
    operation = repository.create_prepared(_request())
    repository.reserve(operation.id)
    repository.transition(operation.id, expected="reserved", state="sending")
    repository.mark_acceptance_unknown(operation.id)
    abandoned = repository.abandon(operation.id)
    assert abandoned.state == "abandoned"
    with pytest.raises(BudgetExceeded):
        retry = repository.create_prepared(_request(attempt_no=2))
        repository.reserve(retry.id)


def test_startup_recovery_is_idempotent_and_distinguishes_staged_acceptance() -> None:
    repository = InMemoryProviderOperationRepository()
    reserved = repository.create_prepared(_request(logical_item_id="reserved"))
    repository.reserve(reserved.id)
    assert repository.recover_one(reserved.id).state == "not_sent"
    assert repository.recover_one(reserved.id).state == "not_sent"

    sending = repository.create_prepared(_request(logical_item_id="sending"))
    repository.reserve(sending.id)
    repository.transition(sending.id, expected="reserved", state="sending")
    assert repository.recover_one(sending.id).state == "acceptance_unknown"
    assert repository.recover_one(sending.id).state == "acceptance_unknown"

    accepted = repository.create_prepared(_request(logical_item_id="accepted"))
    repository.reserve(accepted.id)
    repository.transition(accepted.id, expected="reserved", state="sending")
    repository.mark_accepted(accepted.id, response_hash=_digest("accepted"))
    assert repository.recover_one(accepted.id).state == "acceptance_unknown"

    staged = repository.create_prepared(_request(logical_item_id="staged"))
    repository.reserve(staged.id)
    repository.transition(staged.id, expected="reserved", state="sending")
    repository.mark_accepted(staged.id, response_hash=_digest("staged"))
    assert repository.recover_one(staged.id, staged_response_complete=True).state == "accepted"


def test_scope_cap_reservation_is_atomic_under_concurrency() -> None:
    repository = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1, max_total_tokens=100, max_cost_cny=0.01
        )
    )
    operations = [
        repository.create_prepared(_request(logical_item_id=f"batch-{index}")) for index in range(8)
    ]

    def reserve(operation: ProviderOperationV1) -> str:
        try:
            repository.reserve(operation.id)
        except BudgetExceeded:
            return "rejected"
        return "reserved"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = tuple(executor.map(reserve, operations))
    assert outcomes.count("reserved") == 1
    assert outcomes.count("rejected") == 7
    assert sum(operation.state == "reserved" for operation in repository.operations()) == 1


def test_execute_provider_call_records_redacted_failure_and_unknown_outcomes() -> None:
    repository = InMemoryProviderOperationRepository()
    success = execute_provider_call(_request(scope_id="success"), repository, lambda: {"ok": True})
    assert isinstance(success, ProviderSuccessResultV1)
    assert success.operation.state == "succeeded"

    invalid = execute_provider_call(
        _request(scope_id="invalid"),
        repository,
        lambda: {"ok": True},
        response_validator=lambda _value: (_ for _ in ()).throw(ValueError("supplier secret")),
    )
    assert isinstance(invalid, ProviderFailureResultV1)
    assert invalid.operation.state == "failed"
    assert "secret" not in invalid.safe_error_code

    not_sent = execute_provider_call(
        _request(scope_id="not-sent"),
        repository,
        lambda: (_ for _ in ()).throw(ProviderNotSentError()),
    )
    assert isinstance(not_sent, ProviderNotSentResultV1)
    assert not_sent.operation.state == "not_sent"

    unknown = execute_provider_call(
        _request(scope_id="unknown"),
        repository,
        lambda: (_ for _ in ()).throw(ProviderAcceptanceUnknownError()),
    )
    assert isinstance(unknown, ProviderAcceptanceUnknownResultV1)
    assert unknown.operation.state == "acceptance_unknown"
    assert (
        safe_provider_error_code(TimeoutError("Bearer secret https://supplier.invalid"))
        == "acceptance_unknown"
    )
    assert safe_provider_error_code(RuntimeError("api_key=secret")) == "provider_failed"


def test_preflight_requires_fixed_operation_model_region_and_confirmation() -> None:
    policy = _policy()
    manifest = _manifest(policy)
    confirmation = confirm_export_manifest(manifest, policy, confirmed_at="now")
    with pytest.raises(PolicyValidationError, match="model"):
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation="embedding",
            model_key="latest",
        )
    with pytest.raises(PolicyValidationError, match="region"):
        validate_provider_preflight(
            policy,
            manifest,
            confirmation,
            scope_id=manifest.scope_id,
            provider_operation="embedding",
            model_key=manifest.model_key,
            region="us-east-1",
        )
    assert FIXED_REGION == "cn-beijing"


def test_result_and_policy_records_do_not_contain_supplier_credentials() -> None:
    policy = _policy()
    manifest = _manifest(policy)
    confirmation = ExportConfirmationV1(
        manifest_hash=manifest.manifest_hash,
        policy_hash=policy.policy_hash,
        confirmed_at=datetime.now(UTC).isoformat(),
    )
    assert "api_key" not in str(policy.canonical_dict()).casefold()
    assert "authorization" not in str(confirmation).casefold()
