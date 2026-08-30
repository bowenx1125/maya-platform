"""Injected SnapshotBuild embedding runtime.

This module is the small orchestration seam for W4-EMBED.  It deliberately
does not know about the Knowledge ORM, provider selection, environment
configuration or a real HTTP client.  A caller supplies:

* an immutable :class:`SnapshotBuildV1` and optional current-input verifier;
* a durable reservation/control port;
* an embedding adapter over an injected transport; and
* an atomic snapshot publication port.

The included in-memory stage/publication stores are deterministic test doubles.
The main window can replace them with adapters that commit the accepted
response, immutable snapshot rows and operation success in one local
transaction.  No supplier response body or credential is persisted here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from threading import RLock
from typing import Literal, Protocol
from urllib.parse import urlsplit

from app.modules.knowledge.markdown import MarkdownDocument

from .adapters import (
    DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingAcceptanceUnknown,
    EmbeddingProviderError,
    EmbeddingTransport,
    EmbeddingTransportNotSent,
)
from .embedding import (
    EmbeddingProvider,
    EmbeddingValidationError,
    ValidatedEmbeddingBatchV1,
)
from .manifest import canonical_json_bytes, sha256_hex
from .operations import (
    EmbeddingOperationV1,
    EmbeddingReservationV1,
    ReservationRequestV1,
)
from .packing import (
    DEFAULT_EMBEDDING_COST_CAP_CNY,
    DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    EmbeddingBatchV1,
    EmbeddingPlanV1,
    plan_embedding_batches,
)
from .snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_REGION,
    SnapshotBuildDocumentV1,
    SnapshotBuildInputDocument,
    SnapshotBuildV1,
    SnapshotPublishCandidateV1,
    embedding_identity_for,
    prepare_snapshot_build,
)
from .tokenizer import PinnedTokenizer

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

RuntimeStatus = Literal["succeeded", "not_sent", "acceptance_unknown", "failed"]
BatchStatus = Literal["accepted", "succeeded", "not_sent", "acceptance_unknown", "failed"]
SnapshotBuildDocumentInput = (
    SnapshotBuildInputDocument | SnapshotBuildDocumentV1 | MarkdownDocument | Mapping[str, object]
)


class SnapshotEmbeddingRuntimeError(RuntimeError):
    """A runtime preflight, staging or publication boundary failed safely."""

    def __init__(self, message: str, *, code: str = "embedding_runtime_invalid") -> None:
        super().__init__(message)
        self.code = code


class SnapshotBuildDriftError(SnapshotEmbeddingRuntimeError):
    """The frozen source/persona build no longer matches current inputs."""

    def __init__(self, message: str = "SnapshotBuild source or Persona drifted") -> None:
        super().__init__(message, code="snapshot_build_drift")


class SnapshotPublicationError(SnapshotEmbeddingRuntimeError):
    """Atomic snapshot publication was rejected or could not be committed."""

    def __init__(self, message: str = "snapshot publication failed") -> None:
        super().__init__(message, code="snapshot_publication_failed")


class EmbeddingControlPort(Protocol):
    """Durable control port required by the runtime.

    The implementation must durably commit ``reserved`` before ``sending``
    and must keep ``acceptance_unknown``/``accepted`` allowance consumed.  A
    production adapter may wrap the generic ProviderDataCall ORM repository;
    this embedding-specific protocol avoids coupling the pure runtime to ORM
    row names or browser DTOs.
    """

    def create_prepared(self, request: ReservationRequestV1) -> EmbeddingOperationV1:
        """Insert one unique prepared attempt."""

    def reserve(self, operation: EmbeddingOperationV1) -> EmbeddingReservationV1:
        """Atomically reserve the scope allowance before provider I/O."""

    def mark_sending(self, operation_id: str) -> EmbeddingOperationV1:
        """CAS ``reserved`` to ``sending`` immediately before I/O."""

    def mark_accepted(self, operation_id: str, *, response_hash: str) -> EmbeddingOperationV1:
        """Durably stage the accepted response hash."""

    def mark_succeeded(self, operation_id: str) -> EmbeddingOperationV1:
        """Commit operation success after publication."""

    def mark_not_sent(
        self, operation_id: str, *, safe_error_code: str = "provider_not_sent"
    ) -> EmbeddingOperationV1:
        """Release the allowance only when no supplier acceptance is proven."""

    def mark_acceptance_unknown(
        self, operation_id: str, *, safe_error_code: str = "acceptance_unknown"
    ) -> EmbeddingOperationV1:
        """Retain the allowance and prohibit automatic retry."""

    def mark_failed(
        self, operation_id: str, *, safe_error_code: str = "embedding_failed"
    ) -> EmbeddingOperationV1:
        """Record a terminal validation/provider failure."""

    def get(self, operation_id: str) -> EmbeddingOperationV1 | None:
        """Read one operation by opaque local identifier."""


@dataclass(frozen=True, slots=True)
class AcceptedEmbeddingStageV1:
    """Sanitized, validated vector stage for one accepted batch.

    Only vectors and immutable local identities are retained.  The supplier
    JSON envelope and any credential never cross this stage boundary.
    """

    operation_id: str
    build_id: str
    build_manifest_hash: str
    batch_index: int
    chunk_ids: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]
    model_key: str
    dimension: int
    response_hash: str
    embedding_provider: str = ""
    embedding_region: str = ""
    policy_version: str = ""

    def __post_init__(self) -> None:
        if (
            not self.operation_id
            or not self.build_id
            or not _SHA256_RE.fullmatch(self.build_manifest_hash)
        ):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage identity is invalid", code="embedding_stage_invalid"
            )
        if (
            self.batch_index < 0
            or isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
        ):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage metadata is invalid", code="embedding_stage_invalid"
            )
        identity = embedding_identity_for(
            self.model_key,
            self.dimension,
            provider=self.embedding_provider or None,
            region=self.embedding_region or None,
            policy_version=self.policy_version or None,
        )
        if identity is None or not _SHA256_RE.fullmatch(self.response_hash):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage model/hash is invalid", code="embedding_stage_invalid"
            )
        object.__setattr__(self, "embedding_provider", identity.provider)
        object.__setattr__(self, "embedding_region", identity.region)
        object.__setattr__(self, "policy_version", identity.policy_version)
        if len(self.chunk_ids) != len(self.vectors) or not self.chunk_ids:
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage vector count is invalid", code="embedding_stage_invalid"
            )
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage chunk identity is duplicated", code="embedding_stage_invalid"
            )
        frozen_vectors: list[tuple[float, ...]] = []
        for vector in self.vectors:
            try:
                valid = len(vector) == self.dimension and all(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                    for value in vector
                )
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted stage vector shape is invalid",
                    code="embedding_stage_invalid",
                )
            frozen_vectors.append(tuple(float(value) for value in vector))
        object.__setattr__(self, "vectors", tuple(frozen_vectors))

    @classmethod
    def from_result(
        cls,
        operation_id: str,
        result: ValidatedEmbeddingBatchV1,
        *,
        response_hash: str,
    ) -> AcceptedEmbeddingStageV1:
        return cls(
            operation_id=operation_id,
            build_id=result.build_id,
            build_manifest_hash=result.build_manifest_hash,
            batch_index=result.batch_index,
            chunk_ids=result.chunk_ids,
            vectors=result.vectors,
            model_key=result.model_key,
            dimension=result.dimension,
            response_hash=response_hash,
            embedding_provider=result.embedding_provider,
            embedding_region=result.embedding_region,
            policy_version=result.policy_version,
        )


class EmbeddingStagePort(Protocol):
    """Durable accepted-response read/stage port."""

    def stage(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        """Persist one immutable sanitized stage idempotently."""

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        """Atomically persist the stage and accept its operation."""

    def get(self, operation_id: str) -> AcceptedEmbeddingStageV1 | None:
        """Load one stage for local recovery/publication."""


class AtomicAcceptedStagePort(Protocol):
    """Production boundary for one stage plus ``accepted`` transition.

    Implementations own the transaction joining the sanitized stage rows and
    provider-operation row.  The runtime intentionally has no two-step
    ``mark_accepted`` fallback.
    """

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        """Persist the stage and commit its operation as accepted atomically."""


@dataclass
class InMemoryEmbeddingStageStore:
    """Thread-safe local stage double; it never stores raw supplier JSON."""

    _values: dict[str, AcceptedEmbeddingStageV1] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _control: EmbeddingControlPort | None = field(default=None, init=False, repr=False)

    def bind_control(self, control: EmbeddingControlPort) -> None:
        """Bind the deterministic fake to the runtime's control double."""

        self._control = control

    def stage(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        with self._lock:
            existing = self._values.get(value.operation_id)
            if existing is not None and existing != value:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted embedding stage changed", code="embedding_stage_conflict"
                )
            self._values[value.operation_id] = value
            return value

    # Descriptive alias for adapters that name the transaction boundary by
    # its action rather than the resulting operation state.
    def stage_and_accept(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        return self.stage_accepted(value)

    def get(self, operation_id: str) -> AcceptedEmbeddingStageV1 | None:
        with self._lock:
            return self._values.get(operation_id)

    def stage_accepted(self, value: AcceptedEmbeddingStageV1) -> AcceptedEmbeddingStageV1:
        """Exercise the atomic boundary with one lock-scoped fake operation."""

        if self._control is None:
            raise SnapshotEmbeddingRuntimeError(
                "accepted-stage control is not bound",
                code="embedding_atomic_stage_unavailable",
            )
        with self._lock:
            existing = self._values.get(value.operation_id)
            if existing is not None and existing != value:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted embedding stage changed", code="embedding_stage_conflict"
                )
            operation = self._control.get(value.operation_id)
            if operation is None:
                raise SnapshotEmbeddingRuntimeError(
                    "accepted-stage operation does not exist",
                    code="embedding_atomic_stage_unavailable",
                )
            if operation.state == "accepted":
                if operation.staged_response_hash != value.response_hash:
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted-stage response hash changed",
                        code="embedding_stage_conflict",
                    )
                self._values[value.operation_id] = value
                return value
            if operation.state != "sending":
                raise SnapshotEmbeddingRuntimeError(
                    "accepted-stage operation is not sending",
                    code="embedding_atomic_stage_unavailable",
                )
            accepted = self._control.mark_accepted(
                value.operation_id,
                response_hash=value.response_hash,
            )
            if accepted.state != "accepted":
                raise SnapshotEmbeddingRuntimeError(
                    "accepted-stage operation transition failed",
                    code="embedding_atomic_stage_unavailable",
                )
            self._values[value.operation_id] = value
            return value

    def values(self) -> tuple[AcceptedEmbeddingStageV1, ...]:
        with self._lock:
            return tuple(self._values.values())


@dataclass(frozen=True, slots=True)
class SnapshotPublicationReceiptV1:
    """Safe receipt returned after one atomic immutable snapshot write."""

    snapshot_id: str
    build_manifest_hash: str
    chunk_ids: tuple[str, ...]


class SnapshotPublicationPort(Protocol):
    """Main-window seam for atomic immutable Snapshot/vector publication."""

    def publish_atomic(
        self,
        candidate: SnapshotPublishCandidateV1,
        *,
        operation_ids: tuple[str, ...] = (),
    ) -> object:
        """Persist the candidate without overwriting an existing snapshot."""


@dataclass
class InMemorySnapshotPublicationStore:
    """Deterministic publication fake used by runtime tests only."""

    _values: dict[str, SnapshotPublishCandidateV1] = field(default_factory=dict, init=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def publish_atomic(
        self,
        candidate: SnapshotPublishCandidateV1,
        *,
        operation_ids: tuple[str, ...] = (),
    ) -> SnapshotPublicationReceiptV1:
        del operation_ids
        with self._lock:
            if candidate.knowledge_snapshot_id in self._values:
                raise SnapshotPublicationError("snapshot already exists")
            self._values[candidate.knowledge_snapshot_id] = candidate
            return SnapshotPublicationReceiptV1(
                snapshot_id=candidate.knowledge_snapshot_id,
                build_manifest_hash=candidate.build_manifest_hash,
                chunk_ids=candidate.chunk_ids,
            )

    publish = publish_atomic

    def get(self, snapshot_id: str) -> SnapshotPublishCandidateV1 | None:
        with self._lock:
            return self._values.get(snapshot_id)

    @property
    def published_snapshot_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._values)

    @property
    def existing_snapshot_ids(self) -> tuple[str, ...]:
        """Alias used by publication adapters that expose existing IDs."""

        return self.published_snapshot_ids


@dataclass(frozen=True, slots=True)
class EmbeddingBatchOutcomeV1:
    """Safe outcome for one planned batch."""

    batch_index: int
    status: BatchStatus
    operation: EmbeddingOperationV1
    validated_batch: ValidatedEmbeddingBatchV1 | None = None
    stage: AcceptedEmbeddingStageV1 | None = None
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class SnapshotEmbeddingRunV1:
    """Complete result of one build orchestration attempt."""

    status: RuntimeStatus
    build: SnapshotBuildV1
    plan: EmbeddingPlanV1
    operations: tuple[EmbeddingOperationV1, ...]
    outcomes: tuple[EmbeddingBatchOutcomeV1, ...]
    candidate: SnapshotPublishCandidateV1 | None = None
    publication: object | None = None
    failed_batch_index: int | None = None
    safe_error_code: str | None = None
    retry_allowed: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def snapshot_id(self) -> str | None:
        return self.candidate.knowledge_snapshot_id if self.candidate is not None else None


class SnapshotEmbeddingRuntime:
    """Run one exact SnapshotBuild through injected provider/control/publication ports."""

    def __init__(
        self,
        *,
        control: EmbeddingControlPort,
        provider: EmbeddingProvider,
        publisher: SnapshotPublicationPort,
        stage_store: EmbeddingStagePort | None = None,
        tokenizer: PinnedTokenizer | object | None = None,
        price_cny_per_million: Decimal | float | int | str = (
            DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION
        ),
        cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
        provider_operation: str = "embedding_snapshot",
    ) -> None:
        self.control = control
        self.provider = provider
        self.publisher = publisher
        self.stage_store = stage_store or InMemoryEmbeddingStageStore()
        bind_control = getattr(self.stage_store, "bind_control", None)
        if callable(bind_control):
            bind_control(control)
        self.tokenizer = tokenizer
        self.price_cny_per_million = price_cny_per_million
        self.cost_cap_cny = cost_cap_cny
        self.provider_operation = provider_operation

    @classmethod
    def with_dashscope(
        cls,
        *,
        control: EmbeddingControlPort,
        publisher: SnapshotPublicationPort,
        config: DashScopeEmbeddingConfig,
        transport: EmbeddingTransport,
        stage_store: EmbeddingStagePort | None = None,
        tokenizer: PinnedTokenizer | object | None = None,
        price_cny_per_million: Decimal | float | int | str = (
            DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION
        ),
        cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
        provider_operation: str = "embedding_snapshot",
        timeout_seconds: float = 30.0,
    ) -> SnapshotEmbeddingRuntime:
        """Build a runtime with the fixed DashScope adapter over injected HTTP."""

        _assert_fixed_dashscope_config(config)
        provider = DashScopeEmbeddingAdapter(
            config,
            transport,
            timeout_seconds=timeout_seconds,
        )
        return cls(
            control=control,
            provider=provider,
            publisher=publisher,
            stage_store=stage_store,
            tokenizer=tokenizer,
            price_cny_per_million=price_cny_per_million,
            cost_cap_cny=cost_cap_cny,
            provider_operation=provider_operation,
        )

    def run(
        self,
        build: SnapshotBuildV1,
        *,
        scope_id: str,
        attempt_no: int = 1,
        current_build: SnapshotBuildV1 | None = None,
        current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
        current_persona_spec_hash: str | None = None,
        current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
        existing_snapshot_ids: Sequence[str] = (),
    ) -> SnapshotEmbeddingRunV1:
        """Execute all planned batches, stopping safely at the first failure.

        ``current_build``/``current_documents``/``current_persona_spec_hash``
        are optional because some callers already hold a transactionally
        captured build.  When supplied, each is compared before planning or
        provider control calls.  A production caller should supply one of
        these current-input checks whenever source rows can change during the
        build lifecycle.
        """

        _assert_fixed_build(build)
        assert_snapshot_build_current(
            build,
            current_build=current_build,
            current_documents=current_documents,
            current_persona_spec_hash=current_persona_spec_hash,
            current_build_verifier=current_build_verifier,
        )
        _assert_fixed_provider(self.provider, build)
        _assert_fixed_control(self.control, build)
        resolved_existing_snapshot_ids = _known_snapshot_ids(
            self.publisher, explicit=existing_snapshot_ids
        )
        if build.knowledge_snapshot_id in resolved_existing_snapshot_ids:
            raise SnapshotPublicationError("snapshot already exists")
        plan = plan_embedding_batches(
            build,
            tokenizer=self.tokenizer,
            price_cny_per_million=self.price_cny_per_million,
            cost_cap_cny=self.cost_cap_cny,
        )

        planned: list[tuple[EmbeddingBatchV1, EmbeddingOperationV1]] = []
        operations: list[EmbeddingOperationV1] = []
        outcomes: list[EmbeddingBatchOutcomeV1] = []
        accepted: list[
            tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
        ] = []

        for batch in plan.batches:
            request = _reservation_request(
                batch,
                scope_id=scope_id,
                attempt_no=attempt_no,
                provider_operation=self.provider_operation,
                price_cny_per_million=self.price_cny_per_million,
            )
            operation = self.control.create_prepared(request)
            planned.append((batch, operation))
            operations.append(operation)

        # Reserve every planned batch before the first provider call.  This
        # makes a scope-cap failure a zero-network outcome even when a later
        # batch would otherwise be the first one to exceed the cap.
        for index, (_, operation) in enumerate(planned):
            try:
                self.control.reserve(operation)
                operation = self.control.get(operation.id) or operation
            except Exception:
                operation = _mark_pre_provider_failure(self.control, operation)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=planned[index][0].batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=operation.safe_error_code or "embedding_reservation_failed",
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=planned[index][0].batch_index,
                    safe_error_code=operation.safe_error_code or "embedding_reservation_failed",
                )
            operations[index] = operation

        for index, (batch, _) in enumerate(planned):
            operation = operations[index]
            if (
                current_build_verifier is not None
                or current_build is not None
                or current_documents is not None
                or current_persona_spec_hash is not None
            ):
                try:
                    assert_snapshot_build_current(
                        build,
                        current_build=current_build,
                        current_documents=current_documents,
                        current_persona_spec_hash=current_persona_spec_hash,
                        current_build_verifier=current_build_verifier,
                    )
                except SnapshotBuildDriftError:
                    operation = _mark_pre_provider_failure(self.control, operation)
                    operations[index] = operation
                    _abort_pending_operations(self.control, operations)
                    outcomes.append(
                        EmbeddingBatchOutcomeV1(
                            batch_index=batch.batch_index,
                            status="failed",
                            operation=operation,
                            safe_error_code="snapshot_build_drift",
                        )
                    )
                    return _run_result(
                        status="failed",
                        build=build,
                        plan=plan,
                        operations=operations,
                        outcomes=outcomes,
                        failed_batch_index=batch.batch_index,
                        safe_error_code="snapshot_build_drift",
                    )
            try:
                operation = self.control.mark_sending(operation.id)
                operations[index] = operation
            except Exception:
                operation = _mark_pre_provider_failure(self.control, operation)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=operation.safe_error_code
                        or "embedding_sending_transition_failed",
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code=operation.safe_error_code
                    or "embedding_sending_transition_failed",
                )

            try:
                value = self.provider.embed_batch(batch)
            except EmbeddingTransportNotSent:
                operation = self.control.mark_not_sent(operation.id)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="not_sent",
                        operation=operation,
                        safe_error_code="provider_not_sent",
                    )
                )
                return _run_result(
                    status="not_sent",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code="provider_not_sent",
                    retry_allowed=True,
                )
            except EmbeddingAcceptanceUnknown:
                operation = self.control.mark_acceptance_unknown(operation.id)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="acceptance_unknown",
                        operation=operation,
                        safe_error_code="acceptance_unknown",
                    )
                )
                return _run_result(
                    status="acceptance_unknown",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code="acceptance_unknown",
                )
            except EmbeddingProviderError as error:
                code = _provider_error_code(error)
                if code == "provider_not_sent":
                    operation = self.control.mark_not_sent(operation.id)
                    operations[index] = operation
                    _abort_pending_operations(self.control, operations)
                    outcomes.append(
                        EmbeddingBatchOutcomeV1(
                            batch_index=batch.batch_index,
                            status="not_sent",
                            operation=operation,
                            safe_error_code=code,
                        )
                    )
                    return _run_result(
                        status="not_sent",
                        build=build,
                        plan=plan,
                        operations=operations,
                        outcomes=outcomes,
                        failed_batch_index=batch.batch_index,
                        safe_error_code=code,
                        retry_allowed=True,
                    )
                if code == "acceptance_unknown":
                    operation = self.control.mark_acceptance_unknown(operation.id)
                    operations[index] = operation
                    _abort_pending_operations(self.control, operations)
                    outcomes.append(
                        EmbeddingBatchOutcomeV1(
                            batch_index=batch.batch_index,
                            status="acceptance_unknown",
                            operation=operation,
                            safe_error_code=code,
                        )
                    )
                    return _run_result(
                        status="acceptance_unknown",
                        build=build,
                        plan=plan,
                        operations=operations,
                        outcomes=outcomes,
                        failed_batch_index=batch.batch_index,
                        safe_error_code=code,
                    )
                operation = self.control.mark_failed(operation.id, safe_error_code=code)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=code,
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code=code,
                )
            except (TimeoutError, ConnectionError):
                operation = self.control.mark_acceptance_unknown(operation.id)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="acceptance_unknown",
                        operation=operation,
                        safe_error_code="acceptance_unknown",
                    )
                )
                return _run_result(
                    status="acceptance_unknown",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code="acceptance_unknown",
                )
            except Exception as error:
                code = _provider_error_code(error)
                operation = self.control.mark_failed(operation.id, safe_error_code=code)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=code,
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code=code,
                )

            if not isinstance(value, ValidatedEmbeddingBatchV1):
                code = "embedding_result_invalid"
                operation = self.control.mark_failed(operation.id, safe_error_code=code)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=code,
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code=code,
                )

            try:
                _assert_result_matches_batch(value, batch)
                response_hash = _response_hash(value)
                expected_stage = AcceptedEmbeddingStageV1.from_result(
                    operation.id,
                    value,
                    response_hash=response_hash,
                )
                stage = _stage_accepted_atomic(self.stage_store, expected_stage)
                if stage != expected_stage:
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted embedding stage changed",
                        code="embedding_stage_conflict",
                    )
                operation = self.control.get(operation.id) or operation
                if operation.state != "accepted":
                    raise SnapshotEmbeddingRuntimeError(
                        "accepted-stage control transition was not committed",
                        code="embedding_atomic_stage_unavailable",
                    )
            except Exception as error:
                code = _safe_code(
                    getattr(error, "code", None), default="embedding_response_invalid"
                )
                operation = self.control.mark_failed(operation.id, safe_error_code=code)
                operations[index] = operation
                _abort_pending_operations(self.control, operations)
                outcomes.append(
                    EmbeddingBatchOutcomeV1(
                        batch_index=batch.batch_index,
                        status="failed",
                        operation=operation,
                        safe_error_code=code,
                    )
                )
                return _run_result(
                    status="failed",
                    build=build,
                    plan=plan,
                    operations=operations,
                    outcomes=outcomes,
                    failed_batch_index=batch.batch_index,
                    safe_error_code=code,
                )

            operations[index] = operation
            accepted.append((operation, value, stage))
            outcomes.append(
                EmbeddingBatchOutcomeV1(
                    batch_index=batch.batch_index,
                    status="accepted",
                    operation=operation,
                    validated_batch=value,
                    stage=stage,
                )
            )

        vectors = tuple(vector for _, value, _ in accepted for vector in value.vectors)
        try:
            assert_snapshot_build_current(
                build,
                current_build=current_build,
                current_documents=current_documents,
                current_persona_spec_hash=current_persona_spec_hash,
                current_build_verifier=current_build_verifier,
            )
            candidate = build.publish_candidate(
                vectors,
                build_manifest_hash=plan.build_manifest_hash,
                model_key=plan.model_key,
                dimension=plan.dimension,
                existing_snapshot_ids=resolved_existing_snapshot_ids,
            )
            operation_ids = tuple(operation.id for operation in operations)
            publication = _publish_candidate(
                self.publisher,
                candidate,
                operation_ids=operation_ids,
            )
        except Exception as error:
            code = _safe_code(getattr(error, "code", None), default="snapshot_publication_failed")
            for index, operation in enumerate(operations):
                try:
                    operations[index] = self.control.mark_failed(operation.id, safe_error_code=code)
                except Exception:
                    # Keep the accepted operation if the durable control port
                    # itself is unavailable; it remains consumed and requires
                    # startup reconciliation rather than a retry.
                    operations[index] = operation
            outcomes = [
                EmbeddingBatchOutcomeV1(
                    batch_index=stage.batch_index,
                    status="failed",
                    operation=operations[index],
                    validated_batch=value,
                    stage=stage,
                    safe_error_code=code,
                )
                for index, (_, value, stage) in enumerate(accepted)
            ]
            return _run_result(
                status="failed",
                build=build,
                plan=plan,
                operations=operations,
                outcomes=outcomes,
                failed_batch_index=None,
                safe_error_code=code,
            )

        try:
            if bool(getattr(self.publisher, "atomic_operation_success", False)):
                operations = [replace(operation, state="succeeded") for operation in operations]
            else:
                for index, operation in enumerate(operations):
                    operations[index] = self.control.mark_succeeded(operation.id)
        except Exception:
            code = "embedding_success_commit_failed"
            return _run_result(
                status="failed",
                build=build,
                plan=plan,
                operations=operations,
                outcomes=tuple(
                    EmbeddingBatchOutcomeV1(
                        batch_index=stage.batch_index,
                        status="failed",
                        operation=operations[index],
                        validated_batch=value,
                        stage=stage,
                        safe_error_code=code,
                    )
                    for _, (operation, value, stage) in enumerate(accepted)
                ),
                candidate=candidate,
                publication=publication,
                safe_error_code=code,
            )
        outcomes = [
            EmbeddingBatchOutcomeV1(
                batch_index=stage.batch_index,
                status="succeeded",
                operation=operations[index],
                validated_batch=value,
                stage=stage,
            )
            for index, (_, value, stage) in enumerate(accepted)
        ]
        return _run_result(
            status="succeeded",
            build=build,
            plan=plan,
            operations=operations,
            outcomes=outcomes,
            candidate=candidate,
            publication=publication,
        )

    execute = run

    def continue_from_stages(
        self,
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
        """Delegate bounded multi-batch restart continuation."""

        from .continuation import continue_from_stages

        return continue_from_stages(
            self,
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

    continue_missing_batches = continue_from_stages
    resume_missing_batches = continue_from_stages

    def resume_from_stages(
        self,
        build: SnapshotBuildV1,
        *,
        operations: Sequence[EmbeddingOperationV1] | None = None,
        stages: (
            Sequence[AcceptedEmbeddingStageV1] | Mapping[str, AcceptedEmbeddingStageV1] | None
        ) = None,
        scope_id: str | None = None,
        existing_snapshot_ids: Sequence[str] = (),
    ) -> SnapshotEmbeddingRunV1:
        """Publish complete accepted stages without touching the provider.

        Startup recovery supplies accepted operation projections and sanitized
        stages.  The method validates the complete plan/build relationship
        before publication; a missing or corrupt stage becomes an
        ``acceptance_unknown`` result and is never retried automatically.
        """

        _assert_fixed_build(build)
        plan = plan_embedding_batches(
            build,
            tokenizer=self.tokenizer,
            price_cny_per_million=self.price_cny_per_million,
            cost_cap_cny=self.cost_cap_cny,
        )
        resolved_scope_id = scope_id or build.build_id
        operation_values = _resolve_resume_operations(
            self.control,
            operations=operations,
            scope_id=resolved_scope_id,
        )
        try:
            stage_values = _resolve_resume_stages(
                self.stage_store,
                stages=stages,
                operation_values=operation_values,
            )
        except Exception as error:
            return _mark_resume_unknown(
                self.control,
                build=build,
                plan=plan,
                operations=operation_values,
                safe_error_code=_safe_code(
                    getattr(error, "code", None), default="embedding_stage_invalid"
                ),
            )
        resolved_existing_snapshot_ids = _known_snapshot_ids(
            self.publisher, explicit=existing_snapshot_ids
        )
        if build.knowledge_snapshot_id in resolved_existing_snapshot_ids:
            return _resume_result(
                status="failed",
                build=build,
                plan=plan,
                operations=operation_values,
                safe_error_code="snapshot_publication_failed",
            )

        accepted: list[
            tuple[EmbeddingOperationV1, ValidatedEmbeddingBatchV1, AcceptedEmbeddingStageV1]
        ] = []
        invalid_code: str | None = None
        operations_by_item: dict[str, EmbeddingOperationV1] = {}
        for operation_value in operation_values:
            if operation_value.logical_item_id in operations_by_item:
                invalid_code = "embedding_operation_duplicate"
                break
            operations_by_item[operation_value.logical_item_id] = operation_value
        expected_items = {f"batch-{batch.batch_index}" for batch in plan.batches}
        if invalid_code is None and set(operations_by_item) != expected_items:
            invalid_code = "embedding_operation_missing"
        if invalid_code is None:
            expected_stage_ids = {operation.id for operation in operations_by_item.values()}
            if set(stage_values) != expected_stage_ids:
                invalid_code = "embedding_stage_missing"
        for batch in plan.batches:
            operation = operations_by_item.get(f"batch-{batch.batch_index}")
            stage = stage_values.get(operation.id) if operation is not None else None
            if operation is None:
                invalid_code = "embedding_operation_missing"
                break
            expected_request = _reservation_request(
                batch,
                scope_id=resolved_scope_id,
                attempt_no=operation.attempt_no,
                provider_operation=self.provider_operation,
                price_cny_per_million=self.price_cny_per_million,
            )
            if (
                operation.scope_id != resolved_scope_id
                or operation.provider_operation != self.provider_operation
                or operation.batch_index != batch.batch_index
                or operation.build_manifest_hash != batch.build_manifest_hash
                or operation.request_hash != expected_request.request_hash
                or operation.max_tokens != expected_request.max_tokens
                or abs(operation.max_cost_cny - expected_request.max_cost_cny) > 1e-12
            ):
                invalid_code = "embedding_operation_scope_mismatch"
                break
            if operation.state != "accepted":
                invalid_code = "embedding_operation_not_accepted"
                break
            if stage is None:
                invalid_code = "embedding_stage_missing"
                break
            try:
                _assert_stage_matches_batch(stage, operation, batch)
            except SnapshotEmbeddingRuntimeError as error:
                invalid_code = _safe_code(error.code, default="embedding_stage_invalid")
                break
            try:
                validated = ValidatedEmbeddingBatchV1(
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
                if _response_hash(validated) != stage.response_hash:
                    invalid_code = "embedding_stage_invalid"
                    break
            except Exception:
                invalid_code = "embedding_stage_invalid"
                break
            accepted.append((operation, validated, stage))

        if invalid_code is not None:
            return _mark_resume_unknown(
                self.control,
                build=build,
                plan=plan,
                operations=operation_values,
                safe_error_code=invalid_code,
            )

        vectors = tuple(vector for _, value, _ in accepted for vector in value.vectors)
        try:
            candidate = build.publish_candidate(
                vectors,
                build_manifest_hash=plan.build_manifest_hash,
                model_key=plan.model_key,
                dimension=plan.dimension,
                existing_snapshot_ids=resolved_existing_snapshot_ids,
            )
            publication = _publish_candidate(
                self.publisher,
                candidate,
                operation_ids=tuple(operation.id for operation, _, _ in accepted),
            )
        except Exception as error:
            code = _safe_code(getattr(error, "code", None), default="snapshot_publication_failed")
            updated = list(operation_values)
            for index, operation in enumerate(updated):
                try:
                    updated[index] = self.control.mark_failed(
                        operation.id,
                        safe_error_code=code,
                    )
                except Exception:
                    pass
            return _run_result(
                status="failed",
                build=build,
                plan=plan,
                operations=updated,
                outcomes=tuple(
                    EmbeddingBatchOutcomeV1(
                        batch_index=stage.batch_index,
                        status="failed",
                        operation=_operation_for_id(updated, operation.id),
                        validated_batch=value,
                        stage=stage,
                        safe_error_code=code,
                    )
                    for _, (operation, value, stage) in enumerate(accepted)
                ),
                candidate=candidate if "candidate" in locals() else None,
                publication=publication if "publication" in locals() else None,
                safe_error_code=code,
            )

        updated = list(operation_values)
        try:
            if bool(getattr(self.publisher, "atomic_operation_success", False)):
                updated = [replace(operation, state="succeeded") for operation in updated]
            else:
                for index, operation in enumerate(updated):
                    updated[index] = self.control.mark_succeeded(operation.id)
        except Exception:
            return _run_result(
                status="failed",
                build=build,
                plan=plan,
                operations=updated,
                outcomes=tuple(
                    EmbeddingBatchOutcomeV1(
                        batch_index=stage.batch_index,
                        status="failed",
                        operation=_operation_for_id(updated, operation.id),
                        validated_batch=value,
                        stage=stage,
                        safe_error_code="embedding_success_commit_failed",
                    )
                    for _, (operation, value, stage) in enumerate(accepted)
                ),
                candidate=candidate,
                publication=publication,
                safe_error_code="embedding_success_commit_failed",
            )
        return _run_result(
            status="succeeded",
            build=build,
            plan=plan,
            operations=updated,
            outcomes=tuple(
                EmbeddingBatchOutcomeV1(
                    batch_index=stage.batch_index,
                    status="succeeded",
                    operation=_operation_for_id(updated, operation.id),
                    validated_batch=value,
                    stage=stage,
                )
                for _, (operation, value, stage) in enumerate(accepted)
            ),
            candidate=candidate,
            publication=publication,
        )


def assert_snapshot_build_current(
    build: SnapshotBuildV1,
    *,
    current_build: SnapshotBuildV1 | None = None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
    current_persona_spec_hash: str | None = None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
) -> None:
    """Fail closed if source/persona inputs differ from the frozen build."""

    try:
        if current_build is not None:
            build.assert_compatible(current_build)
        if current_persona_spec_hash is not None and (
            current_persona_spec_hash != build.persona_spec_hash
        ):
            raise SnapshotBuildDriftError()
        if current_documents is not None:
            persona_hash = current_persona_spec_hash or build.persona_spec_hash
            rebuilt = prepare_snapshot_build(
                agent_version_id=build.agent_version_id,
                knowledge_snapshot_id=build.knowledge_snapshot_id,
                draft_revision=build.draft_revision,
                persona_spec_hash=persona_hash,
                documents=_coerce_current_documents(current_documents),
                build_id=build.build_id,
                chunking_version=build.chunking_version,
                embedding_model_key=build.embedding_model_key,
                embedding_dimension=build.embedding_dimension,
                embedding_provider=build.embedding_provider,
                embedding_region=build.embedding_region,
                embedding_policy_version=build.embedding_policy_version,
            )
            build.assert_compatible(rebuilt)
        if current_build_verifier is not None:
            value = current_build_verifier(build)
            if value is False:
                raise SnapshotBuildDriftError()
            if isinstance(value, SnapshotBuildV1):
                build.assert_compatible(value)
            elif value is not None and value is not True:
                raise SnapshotBuildDriftError()
    except SnapshotBuildDriftError:
        raise
    except Exception as error:
        raise SnapshotBuildDriftError() from error


def _coerce_current_documents(
    documents: Sequence[SnapshotBuildDocumentInput],
) -> tuple[SnapshotBuildInputDocument | MarkdownDocument | Mapping[str, object], ...]:
    """Turn frozen build documents into the raw input shape used for rebuilds.

    A caller commonly has either current source rows or the immutable document
    projections from the build itself.  Supporting the latter keeps the
    verifier useful for a transaction that captured the build before calling
    the runtime, without teaching :func:`prepare_snapshot_build` about its
    frozen output type.
    """

    output: list[SnapshotBuildInputDocument | MarkdownDocument | Mapping[str, object]] = []
    for document in documents:
        if isinstance(document, SnapshotBuildDocumentV1):
            output.append(
                SnapshotBuildInputDocument(
                    document_id=document.document_id,
                    source_filename=document.source_filename,
                    text=document.normalized_text,
                    order_index=document.order_index,
                    source_sha256=document.source_sha256,
                )
            )
        else:
            output.append(document)
    return tuple(output)


def _resolve_resume_operations(
    control: EmbeddingControlPort,
    *,
    operations: Sequence[EmbeddingOperationV1] | None,
    scope_id: str,
) -> tuple[EmbeddingOperationV1, ...]:
    if operations is not None:
        return tuple(operations)
    method = getattr(control, "operations", None)
    if not callable(method):
        return ()
    try:
        values = method(scope_id=scope_id)
    except TypeError:
        values = method()
    return tuple(value for value in values if isinstance(value, EmbeddingOperationV1))


def _resolve_resume_stages(
    stage_store: EmbeddingStagePort,
    *,
    stages: Sequence[AcceptedEmbeddingStageV1] | Mapping[str, AcceptedEmbeddingStageV1] | None,
    operation_values: Sequence[EmbeddingOperationV1],
) -> dict[str, AcceptedEmbeddingStageV1]:
    if isinstance(stages, Mapping):
        mapping_values: dict[str, AcceptedEmbeddingStageV1] = {}
        for key, stage in stages.items():
            if not isinstance(key, str) or not isinstance(stage, AcceptedEmbeddingStageV1):
                raise SnapshotEmbeddingRuntimeError(
                    "accepted stage set is corrupt", code="embedding_stage_invalid"
                )
            mapping_values[key] = stage
        if any(
            not isinstance(stage, AcceptedEmbeddingStageV1) or key != stage.operation_id
            for key, stage in mapping_values.items()
        ):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage set is corrupt", code="embedding_stage_invalid"
            )
        return mapping_values
    if stages is not None:
        list_values: tuple[AcceptedEmbeddingStageV1, ...] = tuple(stages)
        if any(not isinstance(stage, AcceptedEmbeddingStageV1) for stage in list_values):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage set is corrupt", code="embedding_stage_invalid"
            )
        if len({stage.operation_id for stage in list_values}) != len(list_values):
            raise SnapshotEmbeddingRuntimeError(
                "accepted stage set has duplicate operations", code="embedding_stage_invalid"
            )
        return {stage.operation_id: stage for stage in list_values}
    output: dict[str, AcceptedEmbeddingStageV1] = {}
    for operation in operation_values:
        value = stage_store.get(operation.id)
        if value is not None:
            output[operation.id] = value
    return output


def _assert_stage_matches_batch(
    stage: AcceptedEmbeddingStageV1,
    operation: EmbeddingOperationV1,
    batch: EmbeddingBatchV1,
) -> None:
    if (
        not isinstance(stage, AcceptedEmbeddingStageV1)
        or stage.operation_id != operation.id
        or stage.build_id != batch.build_id
        or stage.build_manifest_hash != batch.build_manifest_hash
        or stage.batch_index != batch.batch_index
        or stage.chunk_ids != batch.chunk_ids
        or stage.embedding_provider != batch.embedding_provider
        or stage.model_key != batch.model_key
        or stage.embedding_region != batch.embedding_region
        or stage.dimension != batch.dimension
        or stage.policy_version != batch.policy_version
        or len(stage.vectors) != len(batch.items)
    ):
        raise SnapshotEmbeddingRuntimeError(
            "accepted embedding stage does not match the planned batch",
            code="embedding_stage_invalid",
        )
    if operation.build_manifest_hash and operation.build_manifest_hash != batch.build_manifest_hash:
        raise SnapshotEmbeddingRuntimeError(
            "accepted operation belongs to a different SnapshotBuild",
            code="embedding_build_mismatch",
        )
    if (
        operation.staged_response_hash is not None
        and operation.staged_response_hash != stage.response_hash
    ):
        raise SnapshotEmbeddingRuntimeError(
            "accepted operation hash does not match its stage",
            code="embedding_stage_invalid",
        )


def _operation_for_id(
    operations: Sequence[EmbeddingOperationV1], operation_id: str
) -> EmbeddingOperationV1:
    for operation in operations:
        if operation.id == operation_id:
            return operation
    raise SnapshotEmbeddingRuntimeError(
        "accepted operation disappeared during publication",
        code="embedding_operation_missing",
    )


def _resume_result(
    *,
    status: RuntimeStatus,
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    safe_error_code: str,
) -> SnapshotEmbeddingRunV1:
    return _run_result(
        status=status,
        build=build,
        plan=plan,
        operations=operations,
        outcomes=tuple(
            EmbeddingBatchOutcomeV1(
                batch_index=_batch_index_from_operation(operation),
                status="failed" if status == "failed" else "acceptance_unknown",
                operation=operation,
                safe_error_code=safe_error_code,
            )
            for operation in operations
        ),
        safe_error_code=safe_error_code,
    )


def _batch_index_from_operation(operation: EmbeddingOperationV1) -> int:
    prefix = "batch-"
    if operation.logical_item_id.startswith(prefix):
        try:
            return int(operation.logical_item_id[len(prefix) :])
        except ValueError:
            pass
    return operation.batch_index


def _mark_resume_unknown(
    control: EmbeddingControlPort,
    *,
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    safe_error_code: str,
) -> SnapshotEmbeddingRunV1:
    updated = list(operations)
    for index, operation in enumerate(updated):
        if operation.state == "accepted":
            try:
                updated[index] = control.mark_acceptance_unknown(
                    operation.id,
                    safe_error_code=safe_error_code,
                )
            except Exception:
                pass
    return _resume_result(
        status="acceptance_unknown",
        build=build,
        plan=plan,
        operations=updated,
        safe_error_code=safe_error_code,
    )


def run_snapshot_embedding(
    build: SnapshotBuildV1,
    *,
    scope_id: str,
    control: EmbeddingControlPort,
    provider: EmbeddingProvider,
    publisher: SnapshotPublicationPort,
    stage_store: EmbeddingStagePort | None = None,
    tokenizer: PinnedTokenizer | object | None = None,
    price_cny_per_million: Decimal | float | int | str = (DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION),
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
    provider_operation: str = "embedding_snapshot",
    attempt_no: int = 1,
    current_build: SnapshotBuildV1 | None = None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
    current_persona_spec_hash: str | None = None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
    existing_snapshot_ids: Sequence[str] = (),
) -> SnapshotEmbeddingRunV1:
    """Functional convenience wrapper around :class:`SnapshotEmbeddingRuntime`."""

    return SnapshotEmbeddingRuntime(
        control=control,
        provider=provider,
        publisher=publisher,
        stage_store=stage_store,
        tokenizer=tokenizer,
        price_cny_per_million=price_cny_per_million,
        cost_cap_cny=cost_cap_cny,
        provider_operation=provider_operation,
    ).run(
        build,
        scope_id=scope_id,
        attempt_no=attempt_no,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
        existing_snapshot_ids=existing_snapshot_ids,
    )


def run_dashscope_snapshot_embedding(
    build: SnapshotBuildV1,
    *,
    scope_id: str,
    control: EmbeddingControlPort,
    publisher: SnapshotPublicationPort,
    config: DashScopeEmbeddingConfig,
    transport: EmbeddingTransport,
    stage_store: EmbeddingStagePort | None = None,
    tokenizer: PinnedTokenizer | object | None = None,
    price_cny_per_million: Decimal | float | int | str = (DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION),
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
    provider_operation: str = "embedding_snapshot",
    attempt_no: int = 1,
    current_build: SnapshotBuildV1 | None = None,
    current_documents: Sequence[SnapshotBuildDocumentInput] | None = None,
    current_persona_spec_hash: str | None = None,
    current_build_verifier: Callable[[SnapshotBuildV1], object] | None = None,
    existing_snapshot_ids: Sequence[str] = (),
    timeout_seconds: float = 30.0,
) -> SnapshotEmbeddingRunV1:
    """Run with the fixed Beijing DashScope adapter and injected transport."""

    return SnapshotEmbeddingRuntime.with_dashscope(
        control=control,
        publisher=publisher,
        config=config,
        transport=transport,
        stage_store=stage_store,
        tokenizer=tokenizer,
        price_cny_per_million=price_cny_per_million,
        cost_cap_cny=cost_cap_cny,
        provider_operation=provider_operation,
        timeout_seconds=timeout_seconds,
    ).run(
        build,
        scope_id=scope_id,
        attempt_no=attempt_no,
        current_build=current_build,
        current_documents=current_documents,
        current_persona_spec_hash=current_persona_spec_hash,
        current_build_verifier=current_build_verifier,
        existing_snapshot_ids=existing_snapshot_ids,
    )


def _assert_fixed_build(build: SnapshotBuildV1) -> None:
    try:
        identity = build.embedding_identity
        if not identity.provider or not identity.model_key:
            raise SnapshotEmbeddingRuntimeError(
                "SnapshotBuild identity is incomplete", code="embedding_resource_invalid"
            )
    except Exception as error:
        raise SnapshotEmbeddingRuntimeError(
            "SnapshotBuild is not a supported Mock/real embedding resource",
            code="embedding_resource_invalid",
        ) from error


def _publish_candidate(
    publisher: SnapshotPublicationPort,
    candidate: SnapshotPublishCandidateV1,
    *,
    operation_ids: tuple[str, ...],
) -> object:
    method = getattr(publisher, "publish_atomic", None)
    if not callable(method):
        method = getattr(publisher, "publish", None)
    if not callable(method):
        raise SnapshotPublicationError("snapshot publication port is unavailable")
    try:
        if bool(getattr(publisher, "atomic_operation_success", False)):
            return method(candidate, operation_ids=operation_ids)
        return method(candidate)
    except SnapshotEmbeddingRuntimeError:
        raise
    except Exception as error:
        raise SnapshotPublicationError() from error


def _stage_accepted_atomic(
    stage_store: EmbeddingStagePort,
    value: AcceptedEmbeddingStageV1,
) -> AcceptedEmbeddingStageV1:
    """Use only the production-capable atomic accepted-stage boundary."""

    method = getattr(stage_store, "stage_accepted", None)
    if not callable(method):
        method = getattr(stage_store, "stage_and_accept", None)
    if not callable(method):
        raise SnapshotEmbeddingRuntimeError(
            "accepted-stage atomic port is unavailable",
            code="embedding_atomic_stage_unavailable",
        )
    result = method(value)
    if not isinstance(result, AcceptedEmbeddingStageV1):
        raise SnapshotEmbeddingRuntimeError(
            "accepted-stage atomic port returned an invalid stage",
            code="embedding_stage_invalid",
        )
    return result


def _assert_fixed_provider(provider: EmbeddingProvider, build: SnapshotBuildV1) -> None:
    identity = build.embedding_identity
    if (
        getattr(provider, "model_key", None) != identity.model_key
        or getattr(provider, "dimension", None) != identity.dimension
    ):
        raise SnapshotEmbeddingRuntimeError(
            "embedding provider does not match the selected fixed embedding resource",
            code="embedding_resource_invalid",
        )
    expected_policy = identity.policy_version
    provider_policy = getattr(provider, "policy_version", None)
    if provider_policy is not None and provider_policy != expected_policy:
        raise SnapshotEmbeddingRuntimeError(
            "embedding provider policy does not match the selected resource",
            code="embedding_policy_mismatch",
        )
    provider_name = getattr(provider, "provider", None)
    if provider_name is not None and provider_name != identity.provider:
        raise SnapshotEmbeddingRuntimeError(
            "embedding provider does not match the selected fixed embedding resource",
            code="embedding_provider_mismatch",
        )
    provider_region = getattr(provider, "region", None)
    if provider_region is not None and provider_region != identity.region:
        raise SnapshotEmbeddingRuntimeError(
            "embedding provider region does not match the selected resource",
            code="embedding_region_mismatch",
        )
    config = getattr(provider, "config", None)
    if isinstance(config, DashScopeEmbeddingConfig):
        _assert_fixed_dashscope_config(config)


def _assert_fixed_control(control: EmbeddingControlPort, build: SnapshotBuildV1) -> None:
    """Reject a durable adapter configured for a different model before I/O."""

    configured_model = getattr(control, "model_key", None)
    if configured_model is not None and configured_model != build.embedding_model_key:
        raise SnapshotEmbeddingRuntimeError(
            "embedding control does not match the selected fixed resource",
            code="embedding_resource_invalid",
        )


def _assert_fixed_dashscope_config(config: DashScopeEmbeddingConfig) -> None:
    """Keep the injected DashScope adapter bound to the Beijing workspace."""

    if (
        config.region != REAL_EMBEDDING_REGION
        or config.model_key != REAL_EMBEDDING_MODEL
        or config.dimension != REAL_EMBEDDING_DIMENSION
        or config.policy_version != REAL_EMBEDDING_POLICY_VERSION
        or not config.workspace_id
    ):
        raise SnapshotEmbeddingRuntimeError(
            "DashScope embedding resource is not the fixed Beijing 1024 workspace",
            code="embedding_resource_invalid",
        )
    try:
        endpoint = config.resolved_endpoint
    except Exception as error:
        raise SnapshotEmbeddingRuntimeError(
            "DashScope embedding endpoint is invalid",
            code="embedding_resource_invalid",
        ) from error
    parsed = urlsplit(endpoint)
    expected_host = f"{config.workspace_id}.cn-beijing.maas.aliyuncs.com".lower()
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != expected_host
        or parsed.path != DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise SnapshotEmbeddingRuntimeError(
            "DashScope embedding endpoint is not the fixed Beijing workspace endpoint",
            code="embedding_resource_invalid",
        )


def _known_snapshot_ids(
    publisher: SnapshotPublicationPort,
    *,
    explicit: Sequence[str],
) -> tuple[str, ...]:
    """Collect only opaque local IDs exposed by a publication test/adapter."""

    values = list(explicit)
    advertised = getattr(publisher, "existing_snapshot_ids", ())
    if callable(advertised):
        advertised = advertised()
    if isinstance(advertised, (tuple, list, set, frozenset)):
        values.extend(str(item) for item in advertised)
    return tuple(dict.fromkeys(values))


def _reservation_request(
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
    # The older embedding reservation value is intentionally kept backward
    # compatible.  Runtime requests add the real resource/policy parameters to
    # the frozen hash without changing that shared DTO's shape.
    request_hash = sha256_hex(
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
    return replace(request, request_hash=request_hash)


def _assert_result_matches_batch(
    value: ValidatedEmbeddingBatchV1,
    batch: EmbeddingBatchV1,
) -> None:
    if (
        value.build_manifest_hash != batch.build_manifest_hash
        or value.build_id != batch.build_id
        or value.batch_index != batch.batch_index
        or value.chunk_ids != batch.chunk_ids
        or value.embedding_provider != batch.embedding_provider
        or value.model_key != batch.model_key
        or value.embedding_region != batch.embedding_region
        or value.dimension != batch.dimension
        or value.policy_version != batch.policy_version
        or value.count != len(batch.items)
    ):
        raise SnapshotEmbeddingRuntimeError(
            "embedding result does not match the planned batch",
            code="embedding_build_mismatch",
        )


def _response_hash(value: ValidatedEmbeddingBatchV1) -> str:
    payload: dict[str, object] = {
        "build_id": value.build_id,
        "build_manifest_hash": value.build_manifest_hash,
        "batch_index": value.batch_index,
        "chunk_ids": list(value.chunk_ids),
        "provider": value.embedding_provider,
        "model_key": value.model_key,
        "region": value.embedding_region,
        "dimension": value.dimension,
        "policy_version": value.policy_version,
        "vectors": [list(vector) for vector in value.vectors],
    }
    return sha256_hex(canonical_json_bytes(payload))


def _provider_error_code(error: object) -> str:
    if isinstance(error, EmbeddingValidationError):
        return _safe_code(error.code, default="embedding_response_invalid")
    if isinstance(error, EmbeddingProviderError):
        return _safe_code(error.code, default="embedding_failed")
    return "embedding_failed"


def _safe_code(value: object, *, default: str) -> str:
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


def _abort_pending_operations(
    control: EmbeddingControlPort,
    operations: list[EmbeddingOperationV1],
) -> None:
    """Close never-sent reservations without touching accepted attempts."""

    for index, operation in enumerate(operations):
        try:
            if operation.state == "reserved":
                operations[index] = control.mark_not_sent(
                    operation.id,
                    safe_error_code="embedding_not_started",
                )
            elif operation.state == "prepared":
                operations[index] = control.mark_failed(
                    operation.id,
                    safe_error_code="embedding_reservation_aborted",
                )
        except Exception:
            # A control-port outage is itself a durable recovery condition.  Do
            # not issue another Provider request or hide the original outcome.
            continue


def _mark_pre_provider_failure(
    control: EmbeddingControlPort,
    operation: EmbeddingOperationV1,
) -> EmbeddingOperationV1:
    """Release a reservation when sending could not be durably entered."""

    try:
        if operation.state == "reserved":
            return control.mark_not_sent(
                operation.id,
                safe_error_code="embedding_sending_transition_failed",
            )
        return control.mark_failed(operation.id, safe_error_code="embedding_reservation_failed")
    except Exception:
        return operation


def _run_result(
    *,
    status: RuntimeStatus,
    build: SnapshotBuildV1,
    plan: EmbeddingPlanV1,
    operations: Sequence[EmbeddingOperationV1],
    outcomes: Sequence[EmbeddingBatchOutcomeV1],
    candidate: SnapshotPublishCandidateV1 | None = None,
    publication: object | None = None,
    failed_batch_index: int | None = None,
    safe_error_code: str | None = None,
    retry_allowed: bool = False,
) -> SnapshotEmbeddingRunV1:
    return SnapshotEmbeddingRunV1(
        status=status,
        build=build,
        plan=plan,
        operations=tuple(operations),
        outcomes=tuple(outcomes),
        candidate=candidate,
        publication=publication,
        failed_batch_index=failed_batch_index,
        safe_error_code=safe_error_code,
        retry_allowed=retry_allowed,
    )


# Integration-friendly aliases.
EmbeddingRuntime = SnapshotEmbeddingRuntime
SnapshotEmbeddingResultV1 = SnapshotEmbeddingRunV1
EmbeddingReservationControlPort = EmbeddingControlPort
AcceptedResponseStagePort = EmbeddingStagePort
EmbeddingAcceptedStagePort = EmbeddingStagePort
AtomicSnapshotPublicationPort = SnapshotPublicationPort
SnapshotPublisherPort = SnapshotPublicationPort
InMemorySnapshotPublisher = InMemorySnapshotPublicationStore
AtomicSnapshotPublicationStore = InMemorySnapshotPublicationStore
execute_snapshot_embedding = run_snapshot_embedding
execute_embedding_snapshot = run_snapshot_embedding
orchestrate_snapshot_embedding = run_snapshot_embedding


__all__ = [
    "AcceptedEmbeddingStageV1",
    "AcceptedResponseStagePort",
    "AtomicAcceptedStagePort",
    "AtomicSnapshotPublicationPort",
    "AtomicSnapshotPublicationStore",
    "BatchStatus",
    "EmbeddingBatchOutcomeV1",
    "EmbeddingControlPort",
    "EmbeddingAcceptedStagePort",
    "EmbeddingReservationControlPort",
    "EmbeddingRuntime",
    "EmbeddingStagePort",
    "InMemoryEmbeddingStageStore",
    "InMemorySnapshotPublicationStore",
    "InMemorySnapshotPublisher",
    "RuntimeStatus",
    "SnapshotBuildDriftError",
    "SnapshotBuildDocumentInput",
    "SnapshotEmbeddingResultV1",
    "SnapshotEmbeddingRunV1",
    "SnapshotEmbeddingRuntime",
    "SnapshotEmbeddingRuntimeError",
    "SnapshotPublicationError",
    "SnapshotPublicationPort",
    "SnapshotPublicationReceiptV1",
    "SnapshotPublisherPort",
    "assert_snapshot_build_current",
    "execute_snapshot_embedding",
    "execute_embedding_snapshot",
    "orchestrate_snapshot_embedding",
    "run_dashscope_snapshot_embedding",
    "run_snapshot_embedding",
]
