"""SQL adapter from the generic ProviderDataCall ledger to W4-EMBED.

The pure embedding runtime owns request planning but intentionally knows
nothing about policy/export hashes or SQLAlchemy rows.  This adapter binds
every embedding attempt to one already-confirmed ProviderDataCallV1 manifest
and maps the generic durable repository into the runtime's narrow port.
"""

from __future__ import annotations

from typing import cast

from app.core.db import Database
from app.providers.control import (
    ProviderOperationV1,
    ProviderReservationRequestV1,
    ProviderReservationV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository

from .operations import (
    EmbeddingOperationV1,
    EmbeddingReservationV1,
    OperationState,
    ReservationRequestV1,
)
from .snapshot_build import FIXED_EMBEDDING_MODEL

EMBEDDING_PROVIDER_OPERATION = "embedding"
EMBEDDING_MAX_REQUESTS = 20
EMBEDDING_MAX_TOTAL_TOKENS = 120_000
EMBEDDING_MAX_COST_CNY = 0.10


def _batch_index(logical_item_id: str) -> int:
    prefix = "batch-"
    if not logical_item_id.startswith(prefix):
        return 0
    try:
        value = int(logical_item_id[len(prefix) :])
    except ValueError:
        return 0
    return max(value, 0)


def _operation(value: ProviderOperationV1) -> EmbeddingOperationV1:
    return EmbeddingOperationV1(
        id=value.id,
        scope_id=value.scope_id,
        provider_operation=value.provider_operation,
        logical_item_id=value.logical_item_id,
        attempt_no=value.attempt_no,
        request_hash=value.request_hash,
        max_tokens=value.max_tokens,
        max_cost_cny=float(value.max_cost_cny),
        state=cast(OperationState, value.state),
        build_manifest_hash=value.build_manifest_hash,
        batch_index=_batch_index(value.logical_item_id),
        request_count=value.request_count,
        charged_request_count=value.charged_request_count,
        safe_error_code=value.safe_error_code,
        staged_response_hash=value.staged_response_hash,
        reservation_id=value.reservation_id,
    )


def _reservation(value: ProviderReservationV1) -> EmbeddingReservationV1:
    return EmbeddingReservationV1(
        id=value.id,
        operation_id=value.operation_id,
        scope_id=value.scope_id,
        provider_operation=value.provider_operation,
        logical_item_id=value.logical_item_id,
        attempt_no=value.attempt_no,
        max_tokens=value.max_tokens,
        max_cost_cny=float(value.max_cost_cny),
        state=value.state,
    )


class SqlAlchemyEmbeddingControlAdapter:
    """Bind embedding runtime attempts to a confirmed generic ledger pair."""

    def __init__(
        self,
        database: Database | object,
        *,
        policy_hash: str,
        export_manifest_hash: str,
        build_manifest_hash: str,
        model_key: str = FIXED_EMBEDDING_MODEL,
    ) -> None:
        self.repository = ProviderRepository(database)  # type: ignore[arg-type]
        self.policy_hash = policy_hash
        self.export_manifest_hash = export_manifest_hash
        self.build_manifest_hash = build_manifest_hash
        self.model_key = model_key

    def create_prepared(self, request: ReservationRequestV1) -> EmbeddingOperationV1:
        if (
            request.provider_operation != EMBEDDING_PROVIDER_OPERATION
            or request.build_manifest_hash != self.build_manifest_hash
            or self.model_key != FIXED_EMBEDDING_MODEL
        ):
            raise ValueError("embedding operation does not match the confirmed manifest")
        self.repository.save_scope_budget(
            request.scope_id,
            ProviderScopeBudgetV1(
                max_requests=EMBEDDING_MAX_REQUESTS,
                max_total_tokens=EMBEDDING_MAX_TOTAL_TOKENS,
                max_cost_cny=EMBEDDING_MAX_COST_CNY,
            ),
        )
        value = self.repository.create_prepared(
            ProviderReservationRequestV1(
                scope_id=request.scope_id,
                provider_operation=request.provider_operation,
                logical_item_id=request.logical_item_id,
                attempt_no=request.attempt_no,
                request_hash=request.request_hash,
                max_tokens=request.max_tokens,
                max_cost_cny=request.max_cost_cny,
                policy_hash=self.policy_hash,
                export_manifest_hash=self.export_manifest_hash,
                build_manifest_hash=request.build_manifest_hash,
                model_key=self.model_key,
                operation_id=request.operation_id,
            )
        )
        return _operation(value)

    def reserve(self, operation: EmbeddingOperationV1) -> EmbeddingReservationV1:
        return _reservation(self.repository.reserve(operation.id))

    def mark_sending(self, operation_id: str) -> EmbeddingOperationV1:
        current = self.repository.operation(operation_id)
        return _operation(
            self.repository.transition(
                operation_id,
                expected=current.state,
                state="sending",
            )
        )

    def mark_accepted(self, operation_id: str, *, response_hash: str) -> EmbeddingOperationV1:
        return _operation(self.repository.mark_accepted(operation_id, response_hash=response_hash))

    def mark_succeeded(self, operation_id: str) -> EmbeddingOperationV1:
        current = self.repository.operation(operation_id)
        if current.state == "succeeded":
            return _operation(current)
        return _operation(self.repository.mark_succeeded(operation_id))

    def mark_not_sent(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "provider_not_sent",
    ) -> EmbeddingOperationV1:
        return _operation(
            self.repository.mark_not_sent(
                operation_id,
                safe_error_code=safe_error_code,
            )
        )

    def mark_acceptance_unknown(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "acceptance_unknown",
    ) -> EmbeddingOperationV1:
        return _operation(
            self.repository.mark_acceptance_unknown(
                operation_id,
                safe_error_code=safe_error_code,
            )
        )

    def mark_failed(
        self,
        operation_id: str,
        *,
        safe_error_code: str = "embedding_failed",
    ) -> EmbeddingOperationV1:
        return _operation(
            self.repository.mark_failed(
                operation_id,
                safe_error_code=safe_error_code,
            )
        )

    def get(self, operation_id: str) -> EmbeddingOperationV1 | None:
        value = self.repository.get(operation_id)
        return _operation(value) if value is not None else None


__all__ = [
    "EMBEDDING_MAX_COST_CNY",
    "EMBEDDING_MAX_REQUESTS",
    "EMBEDDING_MAX_TOTAL_TOKENS",
    "EMBEDDING_PROVIDER_OPERATION",
    "SqlAlchemyEmbeddingControlAdapter",
]
