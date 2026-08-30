"""Bounded restart continuation for multi-batch SnapshotBuild embedding.

This module is deliberately separate from the first-run runtime.  Recovery is
not another full ``run``: accepted stages are validated and reused, while only
the latest ``not_sent`` operation for each missing batch may claim the single
next attempt.  All durable identity checks happen before a new reservation or
provider call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from .adapters import EmbeddingAcceptanceUnknown, EmbeddingProviderError, EmbeddingTransportNotSent
from .embedding import EmbeddingProvider, ValidatedEmbeddingBatchV1
from .manifest import canonical_json_bytes, sha256_hex
from .operations import EmbeddingOperationV1, ReservationRequestV1
from .packing import (
    DEFAULT_EMBEDDING_COST_CAP_CNY,
    DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    EmbeddingBatchV1,
    EmbeddingPlanV1,
    plan_embedding_batches,
)
from .snapshot_build import SnapshotBuildV1, SnapshotPublishCandidateV1
from .tokenizer import PinnedTokenizer

if TYPE_CHECKING:
    from .runtime import (
        AcceptedEmbeddingStageV1,
        EmbeddingBatchOutcomeV1,
        EmbeddingControlPort,
        EmbeddingStagePort,
        SnapshotBuildDocumentInput,
        SnapshotEmbeddingRuntime,
        SnapshotEmbeddingRunV1,
        SnapshotPublicationPort,
    )

# The W4-EMBED contract authorizes one frozen retry for a batch that is proven
# ``not_sent``.  This is intentionally local to continuation, so repeated
# process startups cannot turn it into an unbounded retry loop.
MAX_EMBEDDING_ATTEMPTS = 2


@dataclass(frozen=True, slots=True)
class _ContinuationValidationV1:
    accepted: tuple[
        tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1], ...
    ]
    missing: tuple[tuple[EmbeddingBatchV1, EmbeddingOperationV1], ...]
    latest_operations: tuple[EmbeddingOperationV1, ...]
    stages: Mapping[str, AcceptedEmbeddingStageV1]


@dataclass(frozen=True, slots=True)
class _ContinuationBatchResultV1:
    status: Literal["accepted", "not_sent", "acceptance_unknown", "failed"]
    operation: EmbeddingOperationV1
    validated_batch: ValidatedEmbeddingBatchV1 | None = None
    stage: AcceptedEmbeddingStageV1 | None = None
    safe_error_code: str | None = None


def continue_from_stages(
    runtime: SnapshotEmbeddingRuntime,
    build: SnapshotBuildV1,
    *,
    operations: Sequence[EmbeddingOperationV1] | None = None,
    stages: (
        Sequence[AcceptedEmbeddingStageV1] | Mapping[str, AcceptedEmbeddingStageV1] | None
    ) = None,
    scope_id: str | None = None,
    attempt_no: int | None = None,
    plan: EmbeddingPlanV1 | None = None,
    current_build: SnapshotBuildV1 | None = None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
    current_persona_spec_hash: str | None = None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
    existing_snapshot_ids: Sequence[str] = (),
) -> SnapshotEmbeddingRunV1:
    """Continue a frozen build, sending only missing ``not_sent`` batches.

    ``runtime.py`` delegates here lazily after its legacy run/resume classes
    are loaded, keeping this recovery state machine out of the first-run path.
    """

    # Local imports avoid a module cycle while keeping the legacy runtime file
    # independent of this continuation state machine.
    from .runtime import (
        _assert_fixed_build,
        _assert_fixed_control,
        _assert_fixed_provider,
        _safe_code,
    )

    control = runtime.control
    publisher = runtime.publisher
    stage_store = runtime.stage_store
    provider = runtime.provider
    provider_operation = runtime.provider_operation
    tokenizer = runtime.tokenizer
    price = runtime.price_cny_per_million
    cost_cap = runtime.cost_cap_cny

    _assert_fixed_build(build)
    _assert_fixed_provider(provider, build)
    _assert_fixed_control(control, build)
    _assert_current(
        build,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
    )

    if plan is None:
        resolved_plan = plan_embedding_batches(
            build,
            tokenizer=tokenizer,
            price_cny_per_million=price,
            cost_cap_cny=cost_cap,
        )
    else:
        resolved_plan = plan
        try:
            _assert_plan_matches_build(resolved_plan, build)
        except Exception as error:
            return _fail_closed(
                control,
                build=build,
                plan=resolved_plan,
                operations=tuple(operations or ()),
                stages={},
                safe_error_code=_safe_code(
                    getattr(error, "code", None), default="embedding_plan_invalid"
                ),
            )
    _assert_plan_matches_build(resolved_plan, build)

    resolved_scope = scope_id or build.build_id
    operation_values = _resolve_operations(
        control,
        operations=operations,
        scope_id=resolved_scope,
        provider_operation=provider_operation,
        build_manifest_hash=resolved_plan.build_manifest_hash,
    )
    try:
        stage_values = _resolve_stages(stage_store, stages, operation_values)
        validation = _validate_state(
            resolved_plan,
            operation_values,
            stage_values,
            scope_id=resolved_scope,
            provider_operation=provider_operation,
            price_cny_per_million=price,
        )
    except Exception as error:
        return _fail_closed(
            control,
            build=build,
            plan=resolved_plan,
            operations=operation_values,
            stages=locals().get("stage_values", {}),
            safe_error_code=_safe_code(
                getattr(error, "code", None), default="embedding_stage_invalid"
            ),
        )

    return _continue_missing(
        runtime,
        build=build,
        plan=resolved_plan,
        validation=validation,
        scope_id=resolved_scope,
        attempt_no=attempt_no,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
        existing_snapshot_ids=existing_snapshot_ids,
    )


def continue_snapshot_embedding(
    build: SnapshotBuildV1,
    *,
    control: EmbeddingControlPort,
    provider: EmbeddingProvider,
    publisher: SnapshotPublicationPort,
    stage_store: EmbeddingStagePort | None = None,
    tokenizer: PinnedTokenizer | object | None = None,
    price_cny_per_million: Decimal | float | int | str = (DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION),
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
    provider_operation: str = "embedding_snapshot",
    scope_id: str | None = None,
    attempt_no: int | None = None,
    operations: Sequence[EmbeddingOperationV1] | None = None,
    stages: (
        Sequence[AcceptedEmbeddingStageV1] | Mapping[str, AcceptedEmbeddingStageV1] | None
    ) = None,
    plan: EmbeddingPlanV1 | None = None,
    current_build: SnapshotBuildV1 | None = None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
    current_persona_spec_hash: str | None = None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
    existing_snapshot_ids: Sequence[str] = (),
) -> SnapshotEmbeddingRunV1:
    """Functional continuation wrapper for an injected provider."""

    from .runtime import SnapshotEmbeddingRuntime

    instance = SnapshotEmbeddingRuntime(
        control=control,
        provider=provider,
        publisher=publisher,
        stage_store=stage_store,
        tokenizer=tokenizer,
        price_cny_per_million=price_cny_per_million,
        cost_cap_cny=cost_cap_cny,
        provider_operation=provider_operation,
    )
    return continue_from_stages(
        instance,
        build,
        operations=operations,
        stages=stages,
        scope_id=scope_id,
        attempt_no=attempt_no,
        plan=plan,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
        existing_snapshot_ids=existing_snapshot_ids,
    )


def _assert_current(
    build: SnapshotBuildV1,
    *,
    current_build: SnapshotBuildV1 | None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None,
    current_persona_spec_hash: str | None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None,
) -> None:
    from .runtime import assert_snapshot_build_current

    assert_snapshot_build_current(
        build,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
    )


def _assert_plan_matches_build(plan: EmbeddingPlanV1, build: SnapshotBuildV1) -> None:
    from .runtime import SnapshotEmbeddingRuntimeError

    if not isinstance(plan, EmbeddingPlanV1):
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation plan is invalid", code="embedding_plan_invalid"
        )
    if (
        plan.build_id != build.build_id
        or plan.build_manifest_hash != build.manifest_hash
        or plan.model_key != build.embedding_model_key
        or plan.dimension != build.embedding_dimension
        or plan.embedding_provider != build.embedding_provider
        or plan.embedding_region != build.embedding_region
        or plan.policy_version != build.embedding_policy_version
        or plan.chunk_ids != tuple(chunk.chunk_id for chunk in build.chunks)
        or tuple(batch.batch_index for batch in plan.batches) != tuple(range(len(plan.batches)))
    ):
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation plan does not match SnapshotBuild",
            code="embedding_build_mismatch",
        )
    for batch in plan.batches:
        if (
            batch.build_id != build.build_id
            or batch.build_manifest_hash != build.manifest_hash
            or batch.model_key != build.embedding_model_key
            or batch.dimension != build.embedding_dimension
            or batch.embedding_provider != build.embedding_provider
            or batch.embedding_region != build.embedding_region
            or batch.policy_version != build.embedding_policy_version
        ):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation batch identity does not match SnapshotBuild",
                code="embedding_build_mismatch",
            )


def _resolve_operations(
    control: EmbeddingControlPort,
    *,
    operations: Sequence[EmbeddingOperationV1] | None,
    scope_id: str,
    provider_operation: str,
    build_manifest_hash: str,
) -> tuple[EmbeddingOperationV1, ...]:
    if operations is None:
        method = getattr(control, "operations", None)
        if not callable(method):
            return ()
        try:
            values = method(scope_id=scope_id)
        except TypeError:
            values = method()
        return tuple(values)
    output = list(operations)
    method = getattr(control, "operations", None)
    if callable(method):
        try:
            advertised = method(scope_id=scope_id)
        except TypeError:
            advertised = method()
        known_ids = {value.id for value in output if isinstance(value, EmbeddingOperationV1)}
        for value in advertised:
            if (
                isinstance(value, EmbeddingOperationV1)
                and value.id not in known_ids
                and value.scope_id == scope_id
                and value.provider_operation == provider_operation
                and value.build_manifest_hash == build_manifest_hash
            ):
                output.append(value)
                known_ids.add(value.id)
    getter = getattr(control, "get", None)
    if callable(getter):
        # Refresh a stale projection only when its immutable request identity
        # still agrees with the durable row.  A caller-supplied hash/scope
        # mutation remains visible and is rejected by validation below.
        for index, value in enumerate(output):
            if not isinstance(value, EmbeddingOperationV1):
                continue
            current = getter(value.id)
            if isinstance(current, EmbeddingOperationV1) and _same_request_identity(value, current):
                output[index] = current
    return tuple(output)


def _same_request_identity(left: EmbeddingOperationV1, right: EmbeddingOperationV1) -> bool:
    return (
        left.id == right.id
        and left.scope_id == right.scope_id
        and left.provider_operation == right.provider_operation
        and left.logical_item_id == right.logical_item_id
        and left.attempt_no == right.attempt_no
        and left.request_hash == right.request_hash
        and left.max_tokens == right.max_tokens
        and left.max_cost_cny == right.max_cost_cny
        and left.build_manifest_hash == right.build_manifest_hash
        and left.batch_index == right.batch_index
        and left.staged_response_hash == right.staged_response_hash
    )


def _resolve_stages(
    stage_store: EmbeddingStagePort,
    stages: (Sequence[AcceptedEmbeddingStageV1] | Mapping[str, AcceptedEmbeddingStageV1] | None),
    operations: Sequence[EmbeddingOperationV1],
) -> dict[str, AcceptedEmbeddingStageV1]:
    from .runtime import AcceptedEmbeddingStageV1, SnapshotEmbeddingRuntimeError

    if isinstance(stages, Mapping):
        mapping_values = dict(stages)
        if any(
            not isinstance(key, str)
            or not isinstance(value, AcceptedEmbeddingStageV1)
            or key != value.operation_id
            for key, value in mapping_values.items()
        ):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation stage set is corrupt", code="embedding_stage_invalid"
            )
        return mapping_values
    if stages is not None:
        values = tuple(stages)
        if any(not isinstance(value, AcceptedEmbeddingStageV1) for value in values):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation stage set is corrupt", code="embedding_stage_invalid"
            )
        if len({value.operation_id for value in values}) != len(values):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation stage set is duplicated", code="embedding_stage_invalid"
            )
        return {value.operation_id: value for value in values}
    output: dict[str, AcceptedEmbeddingStageV1] = {}
    getter = getattr(stage_store, "get", None)
    if not callable(getter):
        return output
    for operation in operations:
        value = getter(operation.id)
        if value is not None:
            output[operation.id] = value
    return output


def _validate_state(
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    stages: Mapping[str, AcceptedEmbeddingStageV1],
    *,
    scope_id: str,
    provider_operation: str,
    price_cny_per_million: Decimal | float | int | str,
) -> _ContinuationValidationV1:
    from .runtime import AcceptedEmbeddingStageV1, SnapshotEmbeddingRuntimeError, _response_hash

    expected = {f"batch-{batch.batch_index}": batch for batch in plan.batches}
    if not operations:
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation operations are missing", code="embedding_operation_missing"
        )
    by_item: dict[str, list[EmbeddingOperationV1]] = {}
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str, int]] = set()
    for operation in operations:
        if not isinstance(operation, EmbeddingOperationV1):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation operation is invalid", code="embedding_operation_invalid"
            )
        if operation.id in seen_ids or operation.idempotency_key in seen_keys:
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation operation is duplicated",
                code="embedding_operation_duplicate",
            )
        seen_ids.add(operation.id)
        seen_keys.add(operation.idempotency_key)
        batch = expected.get(operation.logical_item_id)
        if batch is None:
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation operation is outside the plan",
                code="embedding_operation_mismatch",
            )
        if (
            operation.scope_id != scope_id
            or operation.provider_operation != provider_operation
            or operation.attempt_no < 1
            or isinstance(operation.attempt_no, bool)
            or operation.attempt_no > MAX_EMBEDDING_ATTEMPTS
            or operation.batch_index not in {0, batch.batch_index}
        ):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation operation scope is invalid",
                code="embedding_operation_scope_mismatch",
            )
        request = _request_for_batch(
            batch,
            scope_id=scope_id,
            attempt_no=operation.attempt_no,
            provider_operation=provider_operation,
            price_cny_per_million=price_cny_per_million,
        )
        if (
            operation.request_hash != request.request_hash
            or operation.build_manifest_hash != batch.build_manifest_hash
            or operation.max_tokens != request.max_tokens
            or abs(operation.max_cost_cny - request.max_cost_cny) > 1e-12
        ):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation request identity does not match the plan",
                code="embedding_request_mismatch",
            )
        by_item.setdefault(operation.logical_item_id, []).append(operation)
    if set(by_item) != set(expected):
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation operation set is incomplete",
            code="embedding_operation_missing",
        )

    accepted: list[
        tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
    ] = []
    missing: list[tuple[EmbeddingBatchV1, EmbeddingOperationV1]] = []
    latest_operations: list[EmbeddingOperationV1] = []
    complete_stage_ids: set[str] = set()
    for batch in plan.batches:
        history = sorted(by_item[f"batch-{batch.batch_index}"], key=lambda item: item.attempt_no)
        bad_states = {
            "acceptance_unknown",
            "prepared",
            "export_confirmed",
            "reserved",
            "sending",
            "failed",
            "abandoned",
        }
        if any(operation.state in bad_states for operation in history):
            state = next(operation.state for operation in history if operation.state in bad_states)
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation contains a non-recoverable operation",
                code="acceptance_unknown"
                if state == "acceptance_unknown"
                else "embedding_operation_not_recoverable",
            )
        complete = [item for item in history if item.state in {"accepted", "succeeded"}]
        not_sent = [item for item in history if item.state == "not_sent"]
        if len(complete) > 1:
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation has duplicate accepted attempts",
                code="embedding_operation_duplicate",
            )
        if complete and any(item.attempt_no > complete[0].attempt_no for item in not_sent):
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation retries an accepted batch",
                code="embedding_operation_scope_mismatch",
            )
        latest = history[-1]
        latest_operations.append(latest)
        if complete:
            operation = complete[0]
            stage = stages.get(operation.id)
            if not isinstance(stage, AcceptedEmbeddingStageV1):
                raise SnapshotEmbeddingRuntimeError(
                    "embedding continuation accepted stage is missing",
                    code="embedding_stage_missing",
                )
            _assert_stage(stage, operation, batch)
            try:
                value = ValidatedEmbeddingBatchV1(
                    build_id=stage.build_id,
                    build_manifest_hash=stage.build_manifest_hash,
                    batch_index=stage.batch_index,
                    chunk_ids=stage.chunk_ids,
                    vectors=stage.vectors,
                    model_key=stage.model_key,
                    dimension=stage.dimension,
                    embedding_provider=stage.embedding_provider,
                    embedding_region=stage.embedding_region,
                    policy_version=stage.policy_version,
                )
            except Exception as error:
                raise SnapshotEmbeddingRuntimeError(
                    "embedding continuation accepted stage is invalid",
                    code="embedding_stage_invalid",
                ) from error
            if _response_hash(value) != stage.response_hash:
                raise SnapshotEmbeddingRuntimeError(
                    "embedding continuation accepted stage hash is invalid",
                    code="embedding_stage_hash_mismatch",
                )
            complete_stage_ids.add(operation.id)
            accepted.append((operation, value, stage))
        elif not_sent and latest.state == "not_sent":
            missing.append((batch, latest))
        else:
            raise SnapshotEmbeddingRuntimeError(
                "embedding continuation batch has no retryable operation",
                code="embedding_operation_not_recoverable",
            )
    if set(stages) != complete_stage_ids:
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation stage set does not match accepted operations",
            code="embedding_stage_mismatch",
        )
    return _ContinuationValidationV1(
        accepted=tuple(accepted),
        missing=tuple(missing),
        latest_operations=tuple(latest_operations),
        stages=dict(stages),
    )


def _request_for_batch(
    batch: EmbeddingBatchV1,
    *,
    scope_id: str,
    attempt_no: int,
    provider_operation: str,
    price_cny_per_million: Decimal | float | int | str,
) -> ReservationRequestV1:
    from .operations import reservation_request_for_batch

    request = reservation_request_for_batch(
        batch,
        scope_id=scope_id,
        attempt_no=attempt_no,
        provider_operation=provider_operation,
        price_cny_per_million=float(str(price_cny_per_million)),
    )
    identity_hash = sha256_hex(
        canonical_json_bytes(
            {
                "base_request_hash": request.request_hash,
                "build_manifest_hash": batch.build_manifest_hash,
                "batch_index": batch.batch_index,
                "chunk_ids": list(batch.chunk_ids),
                "token_counts": [item.token_count for item in batch.items],
                "provider": batch.embedding_provider,
                "model_key": batch.model_key,
                "region": batch.embedding_region,
                "dimension": batch.dimension,
                "policy_version": batch.policy_version,
                "parameters": {"dimension": batch.dimension},
            }
        )
    )
    return replace(request, request_hash=identity_hash)


def _assert_stage(
    stage: AcceptedEmbeddingStageV1,
    operation: EmbeddingOperationV1,
    batch: EmbeddingBatchV1,
) -> None:
    from .runtime import AcceptedEmbeddingStageV1, SnapshotEmbeddingRuntimeError

    if not isinstance(stage, AcceptedEmbeddingStageV1):
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation stage is invalid", code="embedding_stage_invalid"
        )
    if (
        stage.operation_id != operation.id
        or stage.build_id != batch.build_id
        or stage.build_manifest_hash != batch.build_manifest_hash
        or stage.batch_index != batch.batch_index
        or stage.chunk_ids != batch.chunk_ids
        or stage.embedding_provider != batch.embedding_provider
        or stage.embedding_region != batch.embedding_region
        or stage.model_key != batch.model_key
        or stage.dimension != batch.dimension
        or stage.policy_version != batch.policy_version
        or operation.staged_response_hash != stage.response_hash
        or len(stage.vectors) != len(batch.items)
    ):
        raise SnapshotEmbeddingRuntimeError(
            "embedding continuation stage does not match the planned batch",
            code="embedding_stage_invalid",
        )


def _continue_missing(
    runtime: SnapshotEmbeddingRuntime,
    *,
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    validation: _ContinuationValidationV1,
    scope_id: str,
    attempt_no: int | None,
    current_build: SnapshotBuildV1 | None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None,
    current_persona_spec_hash: str | None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None,
    existing_snapshot_ids: Sequence[str],
) -> SnapshotEmbeddingRunV1:
    from .runtime import (
        SnapshotBuildDriftError,
        SnapshotEmbeddingRuntimeError,
        _abort_pending_operations,
        _batch_index_from_operation,
        _mark_pre_provider_failure,
        _publish_candidate,
        _run_result,
        _safe_code,
        _stage_accepted_atomic,
    )

    control = runtime.control
    publisher = runtime.publisher
    provider_operation = runtime.provider_operation
    price = runtime.price_cny_per_million
    abort_pending = _abort_pending_operations
    mark_pre_provider_failure = _mark_pre_provider_failure
    publish_candidate = _publish_candidate
    run_result = _run_result
    safe_code = _safe_code
    stage_accepted_atomic = _stage_accepted_atomic
    batch_index_from_operation = _batch_index_from_operation
    resolved_existing = _known_snapshot_ids(publisher, existing_snapshot_ids)
    latest_by_index = {
        _batch_index(operation, batch_index_from_operation): operation
        for operation in validation.latest_operations
    }
    stage_values = dict(validation.stages)
    accepted_by_index = {
        stage.batch_index: (operation, value, stage)
        for operation, value, stage in validation.accepted
    }

    if validation.missing:
        next_attempts = {operation.attempt_no + 1 for _, operation in validation.missing}
        next_attempt = next(iter(next_attempts)) if len(next_attempts) == 1 else None
        if next_attempt is None or (attempt_no is not None and attempt_no != next_attempt):
            return _fail_closed(
                control,
                build=build,
                plan=plan,
                operations=validation.latest_operations,
                stages=stage_values,
                safe_error_code="embedding_attempt_mismatch",
            )
        if next_attempt > MAX_EMBEDDING_ATTEMPTS:
            return _fail_closed(
                control,
                build=build,
                plan=plan,
                operations=validation.latest_operations,
                stages=stage_values,
                safe_error_code="embedding_attempt_exhausted",
            )
        new_batches: list[EmbeddingBatchV1] = []
        new_operations: list[EmbeddingOperationV1] = []
        try:
            for batch, previous in validation.missing:
                request = _request_for_batch(
                    batch,
                    scope_id=scope_id,
                    attempt_no=next_attempt,
                    provider_operation=provider_operation,
                    price_cny_per_million=price,
                )
                if request.request_hash != previous.request_hash:
                    raise SnapshotEmbeddingRuntimeError(
                        "embedding continuation request hash changed",
                        code="embedding_request_mismatch",
                    )
                operation = control.create_prepared(request)
                if operation.state != "prepared" or operation.request_hash != request.request_hash:
                    raise SnapshotEmbeddingRuntimeError(
                        "embedding continuation control changed request identity",
                        code="embedding_request_mismatch",
                    )
                new_batches.append(batch)
                new_operations.append(operation)
        except Exception as error:
            abort_pending(control, new_operations)
            return _failure(
                build,
                plan,
                validation.latest_operations,
                new_operations,
                validation.accepted,
                stage_values,
                safe_code(getattr(error, "code", None), default="embedding_reservation_failed"),
            )
        for index, operation in enumerate(new_operations):
            try:
                control.reserve(operation)
                new_operations[index] = control.get(operation.id) or operation
            except Exception:
                new_operations[index] = mark_pre_provider_failure(control, operation)
                abort_pending(control, new_operations)
                return _failure(
                    build,
                    plan,
                    validation.latest_operations,
                    new_operations,
                    validation.accepted,
                    stage_values,
                    new_operations[index].safe_error_code or "embedding_reservation_failed",
                )
        new_accepted: list[
            tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
        ] = []
        for index, batch in enumerate(new_batches):
            operation = new_operations[index]
            try:
                _assert_current(
                    build,
                    current_build=current_build,
                    current_documents=current_documents,
                    current_persona_spec_hash=current_persona_spec_hash,
                    current_build_verifier=current_build_verifier,
                )
            except SnapshotBuildDriftError:
                new_operations[index] = mark_pre_provider_failure(control, operation)
                abort_pending(control, new_operations)
                return _failure(
                    build,
                    plan,
                    validation.latest_operations,
                    new_operations,
                    validation.accepted,
                    stage_values,
                    "snapshot_build_drift",
                )
            result = _send_batch(runtime, batch, operation, stage_accepted_atomic)
            new_operations[index] = result.operation
            latest_by_index[batch.batch_index] = result.operation
            if result.status != "accepted":
                abort_pending(control, new_operations)
                return _failure(
                    build,
                    plan,
                    validation.latest_operations,
                    new_operations,
                    validation.accepted + tuple(new_accepted),
                    stage_values,
                    result.safe_error_code or "embedding_failed",
                    status=result.status,
                )
            if result.validated_batch is None or result.stage is None:
                abort_pending(control, new_operations)
                return _failure(
                    build,
                    plan,
                    validation.latest_operations,
                    new_operations,
                    validation.accepted + tuple(new_accepted),
                    stage_values,
                    "embedding_stage_invalid",
                )
            new_accepted.append((result.operation, result.validated_batch, result.stage))
            stage_values[result.operation.id] = result.stage
            accepted_by_index[batch.batch_index] = (
                result.operation,
                result.validated_batch,
                result.stage,
            )
        accepted = validation.accepted + tuple(new_accepted)
    else:
        accepted = validation.accepted

    vectors = tuple(
        vector
        for _, value, _ in sorted(accepted, key=lambda item: item[2].batch_index)
        for vector in value.vectors
    )
    has_existing = build.knowledge_snapshot_id in resolved_existing
    candidate: SnapshotPublishCandidateV1
    publication: object | None = None
    try:
        candidate = build.publish_candidate(
            vectors,
            build_manifest_hash=plan.build_manifest_hash,
            model_key=plan.model_key,
            dimension=plan.dimension,
            existing_snapshot_ids=() if has_existing else resolved_existing,
        )
        if not has_existing:
            publication = publish_candidate(
                publisher,
                candidate,
                operation_ids=tuple(operation.id for operation, _, _ in accepted),
            )
    except Exception as error:
        code = safe_code(getattr(error, "code", None), default="snapshot_publication_failed")
        latest = tuple(latest_by_index[index] for index in range(len(plan.batches)))
        for index, operation in enumerate(latest):
            try:
                latest = (
                    latest[:index]
                    + (control.mark_failed(operation.id, safe_error_code=code),)
                    + latest[index + 1 :]
                )
            except Exception:
                pass
        return run_result(
            status="failed",
            build=build,
            plan=plan,
            operations=latest,
            outcomes=_outcomes(
                plan, latest, accepted_by_index, status_override="failed", code=code
            ),
            candidate=locals().get("candidate"),
            publication=publication,
            safe_error_code=code,
        )

    latest = tuple(latest_by_index[index] for index in range(len(plan.batches)))
    try:
        if bool(getattr(publisher, "atomic_operation_success", False)):
            latest = tuple(replace(operation, state="succeeded") for operation in latest)
        else:
            latest = tuple(_mark_succeeded(control, operation) for operation in latest)
    except Exception:
        return run_result(
            status="failed",
            build=build,
            plan=plan,
            operations=latest,
            outcomes=_outcomes(
                plan,
                latest,
                accepted_by_index,
                status_override="failed",
                code="embedding_success_commit_failed",
            ),
            candidate=candidate,
            publication=publication,
            safe_error_code="embedding_success_commit_failed",
        )
    return run_result(
        status="succeeded",
        build=build,
        plan=plan,
        operations=latest,
        outcomes=_outcomes(plan, latest, accepted_by_index),
        candidate=candidate,
        publication=publication,
    )


def _send_batch(
    runtime: SnapshotEmbeddingRuntime,
    batch: EmbeddingBatchV1,
    operation: EmbeddingOperationV1,
    stage_accepted_atomic: Callable[
        [EmbeddingStagePort, AcceptedEmbeddingStageV1], AcceptedEmbeddingStageV1
    ],
) -> _ContinuationBatchResultV1:
    from .runtime import AcceptedEmbeddingStageV1, _assert_result_matches_batch, _response_hash

    control = runtime.control
    provider = runtime.provider
    stage_store = runtime.stage_store
    try:
        operation = control.mark_sending(operation.id)
        value = provider.embed_batch(batch)
    except EmbeddingTransportNotSent:
        return _ContinuationBatchResultV1(
            "not_sent", control.mark_not_sent(operation.id), safe_error_code="provider_not_sent"
        )
    except EmbeddingAcceptanceUnknown:
        return _ContinuationBatchResultV1(
            "acceptance_unknown",
            control.mark_acceptance_unknown(operation.id),
            safe_error_code="acceptance_unknown",
        )
    except EmbeddingProviderError as error:
        code = _provider_error_code(error)
        if code == "provider_not_sent":
            return _ContinuationBatchResultV1(
                "not_sent", control.mark_not_sent(operation.id), safe_error_code=code
            )
        if code == "acceptance_unknown":
            return _ContinuationBatchResultV1(
                "acceptance_unknown",
                control.mark_acceptance_unknown(operation.id),
                safe_error_code=code,
            )
        return _ContinuationBatchResultV1(
            "failed", control.mark_failed(operation.id, safe_error_code=code), safe_error_code=code
        )
    except (TimeoutError, ConnectionError):
        return _ContinuationBatchResultV1(
            "acceptance_unknown",
            control.mark_acceptance_unknown(operation.id),
            safe_error_code="acceptance_unknown",
        )
    except Exception as error:
        code = _provider_error_code(error)
        return _ContinuationBatchResultV1(
            "failed", control.mark_failed(operation.id, safe_error_code=code), safe_error_code=code
        )
    if not isinstance(value, ValidatedEmbeddingBatchV1):
        return _ContinuationBatchResultV1(
            "failed",
            control.mark_failed(operation.id, safe_error_code="embedding_result_invalid"),
            safe_error_code="embedding_result_invalid",
        )
    try:
        _assert_result_matches_batch(value, batch)
        expected = AcceptedEmbeddingStageV1.from_result(
            operation.id, value, response_hash=_response_hash(value)
        )
        stage = stage_accepted_atomic(stage_store, expected)
        if stage != expected:
            raise ValueError("accepted stage changed")
        operation = control.get(operation.id) or operation
        if operation.state != "accepted":
            raise ValueError("accepted operation transition was not committed")
    except Exception as error:
        code = _safe_code(getattr(error, "code", None), "embedding_response_invalid")
        try:
            operation = control.mark_failed(operation.id, safe_error_code=code)
        except Exception:
            pass
        return _ContinuationBatchResultV1("failed", operation, safe_error_code=code)
    return _ContinuationBatchResultV1("accepted", operation, value, stage)


def _provider_error_code(error: object) -> str:
    from .runtime import _provider_error_code as provider_error_code

    return provider_error_code(error)


def _safe_code(value: object, default: str) -> str:
    if (
        isinstance(value, str)
        and value
        and len(value) <= 64
        and all(
            character.isascii() and (character.isalnum() or character in "_.:-")
            for character in value
        )
    ):
        return value
    return default


def _batch_index(
    operation: EmbeddingOperationV1,
    fallback: Callable[[EmbeddingOperationV1], int] | None = None,
) -> int:
    if operation.logical_item_id.startswith("batch-"):
        try:
            return int(operation.logical_item_id[6:])
        except ValueError:
            pass
    return fallback(operation) if fallback is not None else operation.batch_index


def _known_snapshot_ids(
    publisher: SnapshotPublicationPort, explicit: Sequence[str]
) -> tuple[str, ...]:
    values = list(explicit)
    advertised = getattr(publisher, "existing_snapshot_ids", ())
    if callable(advertised):
        advertised = advertised()
    if isinstance(advertised, (tuple, list, set, frozenset)):
        values.extend(str(item) for item in advertised)
    return tuple(dict.fromkeys(values))


def _mark_succeeded(
    control: EmbeddingControlPort, operation: EmbeddingOperationV1
) -> EmbeddingOperationV1:
    current = control.get(operation.id) or operation
    if current.state == "succeeded":
        return current
    if current.state != "accepted":
        raise RuntimeError("embedding operation is not accepted for success")
    return control.mark_succeeded(operation.id)


def _outcomes(
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    accepted: Mapping[
        int, tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
    ],
    *,
    status_override: Literal["accepted", "succeeded", "not_sent", "acceptance_unknown", "failed"]
    | None = None,
    code: str | None = None,
) -> tuple[EmbeddingBatchOutcomeV1, ...]:
    from .runtime import EmbeddingBatchOutcomeV1

    by_index = {
        _batch_index(operation, lambda value: value.batch_index): operation
        for operation in operations
        if isinstance(operation, EmbeddingOperationV1)
    }
    output: list[EmbeddingBatchOutcomeV1] = []
    for batch in plan.batches:
        operation = by_index.get(batch.batch_index)
        if operation is None:
            continue
        staged = accepted.get(batch.batch_index)
        status = status_override
        if status is None:
            if operation.state == "succeeded":
                status = "succeeded"
            elif operation.state == "accepted" and staged is not None:
                status = "accepted"
            elif operation.state == "not_sent":
                status = "not_sent"
            elif operation.state == "acceptance_unknown":
                status = "acceptance_unknown"
            else:
                status = "failed"
        output.append(
            EmbeddingBatchOutcomeV1(
                batch_index=batch.batch_index,
                status=status,
                operation=operation,
                validated_batch=staged[1] if staged else None,
                stage=staged[2] if staged else None,
                safe_error_code=code,
            )
        )
    return tuple(output)


def _failure(
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    latest_operations: Sequence[EmbeddingOperationV1],
    new_operations: Sequence[EmbeddingOperationV1],
    accepted: Sequence[
        tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
    ],
    stages: Mapping[str, AcceptedEmbeddingStageV1],
    code: str,
    *,
    status: Literal["failed", "not_sent", "acceptance_unknown"] = "failed",
) -> SnapshotEmbeddingRunV1:
    from .runtime import _run_result

    by_index = {_batch_index(value): value for value in latest_operations}
    for operation in new_operations:
        by_index[_batch_index(operation)] = operation
    latest = tuple(by_index[index] for index in sorted(by_index))
    accepted_by_index = {
        stage.batch_index: (operation, value, stage) for operation, value, stage in accepted
    }
    return _run_result(
        status=status,
        build=build,
        plan=plan,
        operations=latest,
        outcomes=_outcomes(plan, latest, accepted_by_index, code=code),
        safe_error_code=code,
    )


def _fail_closed(
    control: EmbeddingControlPort,
    *,
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    stages: Mapping[str, AcceptedEmbeddingStageV1],
    safe_error_code: str,
) -> SnapshotEmbeddingRunV1:
    from .runtime import _run_result

    updated = list(operations)
    for index, operation in enumerate(updated):
        if isinstance(operation, EmbeddingOperationV1) and operation.state == "accepted":
            try:
                updated[index] = control.mark_acceptance_unknown(
                    operation.id, safe_error_code=safe_error_code
                )
            except Exception:
                pass
    return _run_result(
        status="acceptance_unknown",
        build=build,
        plan=plan,
        operations=updated,
        outcomes=_outcomes(
            plan, updated, {}, status_override="acceptance_unknown", code=safe_error_code
        ),
        safe_error_code=safe_error_code,
    )


__all__ = [
    "MAX_EMBEDDING_ATTEMPTS",
    "continue_from_stages",
    "continue_snapshot_embedding",
]
