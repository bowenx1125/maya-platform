"""Provider-operation and reservation ports for W4-EMBED.

The production application owns its ORM implementation.  These immutable
values and protocols define the durable boundary without adding a migration or
silently reusing the older voice-operation rows.  ``InMemoryEmbeddingLedger``
is a deterministic test double only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4

from .embedding import ValidatedEmbeddingBatchV1
from .packing import EmbeddingBatchV1

OperationState = Literal[
    "prepared",
    "export_confirmed",
    "reserved",
    "sending",
    "accepted",
    "succeeded",
    "not_sent",
    "acceptance_unknown",
    "failed",
    "abandoned",
]
ReservationState = Literal[
    "prepared",
    "reserved",
    "sending",
    "accepted",
    "succeeded",
    "not_sent",
    "acceptance_unknown",
    "failed",
    "abandoned",
]


class OperationStateError(RuntimeError):
    """A durable operation transition or budget invariant was violated."""


class ReservationConflict(OperationStateError):
    """Another operation already consumed the available scope allowance."""


class BudgetExceeded(ReservationConflict):
    """The atomic scope request/token/cost cap would be exceeded."""


class DuplicateOperation(ReservationConflict):
    """The idempotency tuple already exists in the operation ledger."""


@dataclass(frozen=True, slots=True)
class ReservationRequestV1:
    """One atomic allowance request for a fixed batch attempt."""

    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    request_hash: str
    max_tokens: int
    max_cost_cny: float
    build_manifest_hash: str = ""
    operation_id: str = ""

    def __post_init__(self) -> None:
        if not self.scope_id or not self.provider_operation or not self.logical_item_id:
            raise ValueError("reservation scope and item identity are required")
        if self.attempt_no < 1 or self.max_tokens < 0:
            raise ValueError("reservation attempt/tokens are invalid")
        try:
            cost = Decimal(str(self.max_cost_cny))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("reservation cost is invalid") from exc
        if not cost.is_finite() or cost < 0:
            raise ValueError("reservation cost is invalid")

    @property
    def idempotency_key(self) -> tuple[str, str, str, int]:
        return (
            self.scope_id,
            self.provider_operation,
            self.logical_item_id,
            self.attempt_no,
        )


@dataclass(frozen=True, slots=True)
class EmbeddingOperationV1:
    """Persistable operation record with no supplier secret or response body."""

    id: str
    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    request_hash: str
    max_tokens: int
    max_cost_cny: float
    state: OperationState = "prepared"
    build_manifest_hash: str = ""
    batch_index: int = 0
    request_count: int = 0
    charged_request_count: int = 0
    safe_error_code: str | None = None
    staged_response_hash: str | None = None
    reservation_id: str | None = None
    acceptance_run_id: str | None = None
    call_no: int | None = None

    @property
    def idempotency_key(self) -> tuple[str, str, str, int]:
        return (
            self.scope_id,
            self.provider_operation,
            self.logical_item_id,
            self.attempt_no,
        )

    @property
    def operation_kind(self) -> str:
        return self.provider_operation

    def as_record(self) -> dict[str, object]:
        """Return only safe, persistable operation metadata."""

        return {
            "id": self.id,
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "logical_item_id": self.logical_item_id,
            "attempt_no": self.attempt_no,
            "request_hash": self.request_hash,
            "max_tokens": self.max_tokens,
            "max_cost_cny": self.max_cost_cny,
            "state": self.state,
            "build_manifest_hash": self.build_manifest_hash,
            "batch_index": self.batch_index,
            "request_count": self.request_count,
            "charged_request_count": self.charged_request_count,
            "safe_error_code": self.safe_error_code,
            "staged_response_hash": self.staged_response_hash,
            "reservation_id": self.reservation_id,
            "acceptance_run_id": self.acceptance_run_id,
            "call_no": self.call_no,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingReservationV1:
    """Persistable pre-send allowance reservation."""

    id: str
    operation_id: str
    scope_id: str
    provider_operation: str
    logical_item_id: str
    attempt_no: int
    max_tokens: int
    max_cost_cny: float
    state: ReservationState = "prepared"

    def as_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "operation_id": self.operation_id,
            "scope_id": self.scope_id,
            "provider_operation": self.provider_operation,
            "logical_item_id": self.logical_item_id,
            "attempt_no": self.attempt_no,
            "max_tokens": self.max_tokens,
            "max_cost_cny": self.max_cost_cny,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingSuccessResult:
    status: Literal["succeeded"]
    operation: EmbeddingOperationV1
    batch: ValidatedEmbeddingBatchV1


@dataclass(frozen=True, slots=True)
class EmbeddingNotSentResult:
    status: Literal["not_sent"]
    operation: EmbeddingOperationV1
    safe_error_code: str = "provider_not_sent"


@dataclass(frozen=True, slots=True)
class EmbeddingAcceptanceUnknownResult:
    """A charged/possibly accepted attempt that must never auto-retry."""

    status: Literal["acceptance_unknown"]
    operation: EmbeddingOperationV1
    safe_error_code: str = "acceptance_unknown"
    retry_allowed: Literal[False] = False

    @property
    def requires_reconciliation(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class EmbeddingFailureResult:
    status: Literal["failed"]
    operation: EmbeddingOperationV1
    safe_error_code: str = "embedding_failed"


AcceptanceUnknownResult = EmbeddingAcceptanceUnknownResult
EmbeddingCallResult = (
    EmbeddingSuccessResult
    | EmbeddingNotSentResult
    | EmbeddingAcceptanceUnknownResult
    | EmbeddingFailureResult
)


class ProviderOperationStore(Protocol):
    """Durable operation port implemented by the main window's ORM adapter."""

    def create_prepared(self, request: ReservationRequestV1) -> EmbeddingOperationV1:
        """Insert one unique prepared operation."""

    def transition(
        self,
        operation_id: str,
        *,
        expected: OperationState,
        state: OperationState,
        safe_error_code: str | None = None,
    ) -> EmbeddingOperationV1:
        """CAS a state transition and return the new record."""

    def get(self, operation_id: str) -> EmbeddingOperationV1 | None:
        """Read one operation by opaque local ID."""


class ReservationStore(Protocol):
    """Atomic scope-budget reservation port."""

    def reserve(self, operation: EmbeddingOperationV1) -> EmbeddingReservationV1:
        """Atomically verify scope caps and commit ``reserved`` before I/O."""

    def release_not_sent(self, operation_id: str) -> EmbeddingReservationV1:
        """Release request/cost allowance only after no acceptance is proven."""


def can_transition_operation(current: OperationState, target: OperationState) -> bool:
    """Return whether a durable operation state transition is contract-valid."""

    allowed: dict[OperationState, frozenset[OperationState]] = {
        "prepared": frozenset({"export_confirmed", "reserved", "not_sent", "failed"}),
        "export_confirmed": frozenset({"reserved", "not_sent", "failed"}),
        "reserved": frozenset({"sending", "not_sent"}),
        "sending": frozenset({"accepted", "not_sent", "acceptance_unknown", "failed"}),
        "accepted": frozenset({"succeeded", "failed", "acceptance_unknown", "not_sent"}),
        "succeeded": frozenset(),
        "not_sent": frozenset({"prepared"}),
        "acceptance_unknown": frozenset({"accepted", "not_sent", "abandoned", "failed"}),
        "failed": frozenset({"prepared", "accepted", "abandoned"}),
        "abandoned": frozenset(),
    }
    return target in allowed[current]


def recover_operation_state(state: OperationState) -> OperationState:
    """Map startup-stranded states to the contract's idempotent recovery state."""

    if state == "reserved":
        return "not_sent"
    if state in {"sending", "accepted"}:
        return "acceptance_unknown"
    return state


def _safe_code(value: str | None, default: str = "embedding_failed") -> str:
    if not value:
        return default
    if len(value) > 64 or not all(32 <= ord(char) < 127 for char in value):
        return default
    return value


class InMemoryEmbeddingLedger(ProviderOperationStore, ReservationStore):
    """Thread-safe deterministic ledger for focused contract tests.

    This class is not a production persistence implementation.  Its purpose
    is to make the atomic reservation and acceptance-unknown rules executable
    without adding Wave 4 database tables in the worker branch.
    """

    def __init__(
        self,
        *,
        max_requests: int = 20,
        max_total_tokens: int = 120_000,
        max_cost_cny: float = 0.10,
    ) -> None:
        if max_requests < 1 or max_total_tokens < 0 or max_cost_cny < 0:
            raise ValueError("ledger caps are invalid")
        self.max_requests = max_requests
        self.max_total_tokens = max_total_tokens
        self.max_cost_cny = float(max_cost_cny)
        self._operations: dict[str, EmbeddingOperationV1] = {}
        self._reservations: dict[str, EmbeddingReservationV1] = {}
        self._by_key: dict[tuple[str, str, str, int], str] = {}
        self._lock = RLock()

    def create_prepared(self, request: ReservationRequestV1) -> EmbeddingOperationV1:
        with self._lock:
            if request.idempotency_key in self._by_key:
                raise DuplicateOperation("embedding attempt already exists")
            operation = EmbeddingOperationV1(
                id=request.operation_id or str(uuid4()),
                scope_id=request.scope_id,
                provider_operation=request.provider_operation,
                logical_item_id=request.logical_item_id,
                attempt_no=request.attempt_no,
                request_hash=request.request_hash,
                max_tokens=request.max_tokens,
                max_cost_cny=float(request.max_cost_cny),
                build_manifest_hash=request.build_manifest_hash,
            )
            self._operations[operation.id] = operation
            self._by_key[operation.idempotency_key] = operation.id
            return operation

    def create(self, request: ReservationRequestV1) -> EmbeddingOperationV1:
        return self.create_prepared(request)

    def get(self, operation_id: str) -> EmbeddingOperationV1 | None:
        with self._lock:
            return self._operations.get(operation_id)

    def operation(self, operation_id: str) -> EmbeddingOperationV1:
        value = self.get(operation_id)
        if value is None:
            raise OperationStateError("embedding operation does not exist")
        return value

    def _replace_operation(self, operation: EmbeddingOperationV1) -> EmbeddingOperationV1:
        self._operations[operation.id] = operation
        return operation

    def transition(
        self,
        operation_id: str,
        *,
        expected: OperationState,
        state: OperationState,
        safe_error_code: str | None = None,
    ) -> EmbeddingOperationV1:
        with self._lock:
            operation = self.operation(operation_id)
            if operation.state != expected:
                raise OperationStateError("embedding operation state fence failed")
            if not can_transition_operation(expected, state):
                raise OperationStateError(
                    f"invalid embedding state transition: {expected}->{state}"
                )
            return self._replace_operation(
                replace(
                    operation,
                    state=state,
                    safe_error_code=(
                        _safe_code(safe_error_code)
                        if safe_error_code
                        else operation.safe_error_code
                    ),
                )
            )

    def export_confirm(self, operation_id: str) -> EmbeddingOperationV1:
        return self.transition(operation_id, expected="prepared", state="export_confirmed")

    def _scope_totals(self, scope_id: str) -> tuple[int, int, float]:
        # ``not_sent`` is the only state that releases its reservation.  A
        # failed validation remains consumed, and acceptance-unknown remains
        # reserved until operator reconciliation.
        rows = [
            operation
            for operation in self._operations.values()
            if operation.scope_id == scope_id
            and operation.state
            in {"reserved", "sending", "accepted", "succeeded", "acceptance_unknown"}
            or operation.scope_id == scope_id
            and operation.state == "failed"
            and operation.reservation_id is not None
        ]
        return (
            len(rows),
            sum(row.max_tokens for row in rows),
            sum(row.max_cost_cny for row in rows),
        )

    def reserve(self, operation: EmbeddingOperationV1) -> EmbeddingReservationV1:
        with self._lock:
            current = self.operation(operation.id)
            if current.state not in {"prepared", "export_confirmed"}:
                raise OperationStateError("embedding operation is not reservable")
            reservation = EmbeddingReservationV1(
                id=str(uuid4()),
                operation_id=current.id,
                scope_id=current.scope_id,
                provider_operation=current.provider_operation,
                logical_item_id=current.logical_item_id,
                attempt_no=current.attempt_no,
                max_tokens=current.max_tokens,
                max_cost_cny=current.max_cost_cny,
                state="reserved",
            )
            self._reservations[reservation.id] = reservation
            self._replace_operation(
                replace(
                    current,
                    state="reserved",
                    reservation_id=reservation.id,
                    request_count=current.request_count + 1,
                    charged_request_count=current.charged_request_count + 1,
                )
            )
            return reservation

    def reservation(self, operation_id: str) -> EmbeddingReservationV1:
        operation = self.operation(operation_id)
        if operation.reservation_id is None:
            raise OperationStateError("embedding operation has no reservation")
        return self._reservations[operation.reservation_id]

    def _set_reservation(self, operation_id: str, state: ReservationState) -> None:
        reservation = self.reservation(operation_id)
        self._reservations[reservation.id] = replace(reservation, state=state)

    def mark_sending(self, operation_id: str) -> EmbeddingOperationV1:
        with self._lock:
            result = self.transition(operation_id, expected="reserved", state="sending")
            self._set_reservation(operation_id, "sending")
            return result

    def mark_accepted(
        self,
        operation_id: str,
        *,
        response_hash: str | None = None,
    ) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            if current.state == "failed" and (
                not response_hash or response_hash != current.staged_response_hash
            ):
                raise OperationStateError("failed accept restore requires the stored stage hash")
            result = self.transition(operation_id, expected=current.state, state="accepted")
            self._set_reservation(operation_id, "accepted")
            if response_hash is not None:
                result = self._replace_operation(
                    replace(result, staged_response_hash=response_hash)
                )
            return result

    def mark_succeeded(self, operation_id: str) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            result = self.transition(operation_id, expected=current.state, state="succeeded")
            self._set_reservation(operation_id, "succeeded")
            return result

    def mark_not_sent(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "provider_not_sent",
    ) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            result = self.transition(
                operation_id,
                expected=current.state,
                state="not_sent",
                safe_error_code=safe_error_code,
            )
            if current.reservation_id is not None:
                self._set_reservation(operation_id, "not_sent")
            return result

    def release_not_sent(self, operation_id: str) -> EmbeddingReservationV1:
        self.mark_not_sent(operation_id)
        return self.reservation(operation_id)

    def mark_acceptance_unknown(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "acceptance_unknown",
    ) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            result = self.transition(
                operation_id,
                expected=current.state,
                state="acceptance_unknown",
                safe_error_code=safe_error_code,
            )
            if current.reservation_id is not None:
                self._set_reservation(operation_id, "acceptance_unknown")
            return result

    def mark_failed(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "embedding_failed",
    ) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            result = self.transition(
                operation_id,
                expected=current.state,
                state="failed",
                safe_error_code=safe_error_code,
            )
            if current.reservation_id is not None:
                self._set_reservation(operation_id, "failed")
            return result

    def abandon(self, operation_id: str) -> EmbeddingOperationV1:
        with self._lock:
            current = self.operation(operation_id)
            result = self.transition(operation_id, expected=current.state, state="abandoned")
            if current.reservation_id is not None:
                self._set_reservation(operation_id, "abandoned")
            return result

    def recover(self, operation_id: str) -> EmbeddingOperationV1:
        """Recover one stranded record without issuing a provider request."""

        with self._lock:
            current = self.operation(operation_id)
            target = recover_operation_state(current.state)
            if target == current.state:
                return current
            if target == "not_sent":
                return self.mark_not_sent(operation_id, safe_error_code="recovered_not_sent")
            return self.mark_acceptance_unknown(
                operation_id, safe_error_code="recovered_acceptance_unknown"
            )

    def recover_all(self) -> tuple[EmbeddingOperationV1, ...]:
        with self._lock:
            ids = tuple(
                operation.id
                for operation in self._operations.values()
                if operation.state
                in {"prepared", "export_confirmed", "reserved", "sending", "accepted"}
            )
            return tuple(self.recover(operation_id) for operation_id in ids)

    def operations(self, *, scope_id: str | None = None) -> tuple[EmbeddingOperationV1, ...]:
        with self._lock:
            rows: Iterable[EmbeddingOperationV1] = self._operations.values()
            if scope_id is not None:
                rows = (row for row in rows if row.scope_id == scope_id)
            return tuple(rows)


def reservation_request_for_batch(
    batch: EmbeddingBatchV1,
    *,
    scope_id: str,
    attempt_no: int = 1,
    provider_operation: str = "embedding_snapshot",
    price_cny_per_million: float = 0.5,
) -> ReservationRequestV1:
    """Create the stable allowance request for one planned batch."""

    request_hash = hashlib.sha256(
        (
            batch.build_manifest_hash
            + ":"
            + str(batch.batch_index)
            + ":"
            + ",".join(batch.chunk_ids)
        ).encode("utf-8")
    ).hexdigest()
    return ReservationRequestV1(
        scope_id=scope_id,
        provider_operation=provider_operation,
        logical_item_id=f"batch-{batch.batch_index}",
        attempt_no=attempt_no,
        request_hash=request_hash,
        max_tokens=batch.total_tokens,
        max_cost_cny=(batch.total_tokens * price_cny_per_million) / 1_000_000,
        build_manifest_hash=batch.build_manifest_hash,
    )


def execute_embedding_batch(
    batch: EmbeddingBatchV1,
    provider: object,
    ledger: InMemoryEmbeddingLedger,
    *,
    scope_id: str,
    attempt_no: int = 1,
    provider_operation: str = "embedding_snapshot",
    price_cny_per_million: float = 0.5,
) -> EmbeddingCallResult:
    """Exercise the durable reservation boundary around one injected provider."""

    request = reservation_request_for_batch(
        batch,
        scope_id=scope_id,
        attempt_no=attempt_no,
        provider_operation=provider_operation,
        price_cny_per_million=price_cny_per_million,
    )
    operation = ledger.create_prepared(request)
    try:
        ledger.reserve(operation)
        ledger.mark_sending(operation.id)
    except OperationStateError:
        current = ledger.mark_failed(operation.id, safe_error_code="embedding_reservation_failed")
        return EmbeddingFailureResult("failed", current, "embedding_reservation_failed")
    try:
        method = getattr(provider, "embed_batch", None)
        if not callable(method):
            raise TypeError("embedding provider does not implement embed_batch")
        value = method(batch)
    except Exception as exc:
        # These imports are local to keep the ports usable without the adapter.
        from .adapters import EmbeddingAcceptanceUnknown, EmbeddingTransportNotSent
        from .embedding import EmbeddingValidationError

        if isinstance(exc, EmbeddingTransportNotSent):
            current = ledger.mark_not_sent(operation.id)
            return EmbeddingNotSentResult("not_sent", current)
        if isinstance(exc, EmbeddingAcceptanceUnknown):
            current = ledger.mark_acceptance_unknown(operation.id)
            return EmbeddingAcceptanceUnknownResult("acceptance_unknown", current)
        code = exc.code if isinstance(exc, EmbeddingValidationError) else "embedding_failed"
        current = ledger.mark_failed(operation.id, safe_error_code=_safe_code(code))
        return EmbeddingFailureResult("failed", current, _safe_code(code))
    if not isinstance(value, ValidatedEmbeddingBatchV1):
        current = ledger.mark_failed(operation.id, safe_error_code="embedding_result_invalid")
        return EmbeddingFailureResult("failed", current, "embedding_result_invalid")
    if value.build_manifest_hash != batch.build_manifest_hash or value.chunk_ids != batch.chunk_ids:
        current = ledger.mark_failed(operation.id, safe_error_code="embedding_build_mismatch")
        return EmbeddingFailureResult("failed", current, "embedding_build_mismatch")
    response_hash = hashlib.sha256(repr(value.vectors).encode("utf-8")).hexdigest()
    ledger.mark_accepted(operation.id, response_hash=response_hash)
    current = ledger.mark_succeeded(operation.id)
    return EmbeddingSuccessResult("succeeded", current, value)


__all__ = [
    "AcceptanceUnknownResult",
    "BudgetExceeded",
    "DuplicateOperation",
    "EmbeddingAcceptanceUnknownResult",
    "EmbeddingCallResult",
    "EmbeddingFailureResult",
    "EmbeddingNotSentResult",
    "EmbeddingOperationV1",
    "EmbeddingReservationV1",
    "EmbeddingSuccessResult",
    "InMemoryEmbeddingLedger",
    "OperationState",
    "OperationStateError",
    "ProviderOperationStore",
    "ReservationConflict",
    "ReservationRequestV1",
    "ReservationState",
    "ReservationStore",
    "can_transition_operation",
    "execute_embedding_batch",
    "recover_operation_state",
    "reservation_request_for_batch",
]
