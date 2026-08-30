"""Durable SQL control for identity-bound W4 query embeddings.

The query embedding service is deliberately provider-neutral.  This module
binds one preconfigured turn request to the server-only ProviderDataCall
ledger and an injected provider.  It never selects a provider, reads a
credential, or performs network I/O.  The application must construct and
confirm the exact export manifest before creating this adapter.

The current baseline ``SqlAlchemyEmbeddingStageStore`` still accepts only the
snapshot operation name (``embedding``).  The stage port below therefore
remains injectable; after the main window extends that store for
``embedding_query``, the same wrapper will persist query stages without any
query-text or provider-response payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from threading import RLock
from typing import Protocol, cast

from app.core.db import Database
from app.modules.knowledge.providers.embedding import ValidatedEmbeddingBatchV1
from app.modules.knowledge.providers.packing import MAX_BATCH_TOKENS, EmbeddingBatchV1
from app.modules.knowledge.providers.query_embedding import (
    QUERY_PROVIDER_OPERATION,
    QueryEmbeddingBatchProvider,
    QueryEmbeddingBudgetPort,
    QueryEmbeddingControlPort,
    QueryEmbeddingError,
    QueryEmbeddingManifestPort,
    QueryEmbeddingProviderError,
)
from app.modules.knowledge.providers.runtime import (
    AcceptedEmbeddingStageV1,
    EmbeddingStagePort,
    SnapshotEmbeddingRuntimeError,
)
from app.modules.knowledge.vector import REAL_EMBEDDING_IDENTITY, EmbeddingIdentityV1
from app.providers.control import (
    ProviderOperationV1,
    ProviderReservationRequestV1,
    ProviderScopeBudgetV1,
)
from app.providers.control_repository import ProviderRepository

SQL_QUERY_MAX_REQUESTS = 25
SQL_QUERY_MAX_TOTAL_TOKENS = 150_000
SQL_QUERY_MAX_COST_CNY = 0.10
SQL_QUERY_PRICE_CNY_PER_MILLION = Decimal("0.5")
SQL_QUERY_PROVIDER_OPERATION = QUERY_PROVIDER_OPERATION

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


class SqlQueryError(RuntimeError):
    """A durable query request cannot proceed safely."""

    def __init__(self, message: str, *, code: str = "embedding_query_invalid") -> None:
        super().__init__(message)
        self.code = code


class SqlQueryPreflightError(SqlQueryError):
    """The exact persisted policy/export/identity preflight is unavailable."""

    def __init__(
        self,
        message: str = "embedding query preflight is unavailable",
        *,
        code: str = "embedding_query_preflight_required",
    ) -> None:
        super().__init__(message, code=code)


class SqlQueryIdentityError(SqlQueryError):
    """The persisted Snapshot or injected provider has a different identity."""

    def __init__(self, message: str = "embedding query identity is invalid") -> None:
        super().__init__(message, code="embedding_query_identity_mismatch")


class SqlQueryBudgetError(SqlQueryError):
    """The per-debate query allowance or unique attempt fence rejected a call."""

    def __init__(
        self,
        message: str = "embedding query budget is unavailable",
        *,
        code: str = "embedding_query_budget_exceeded",
    ) -> None:
        super().__init__(message, code=code)


class SqlQueryStageError(SqlQueryError):
    """A sanitized accepted stage was missing, corrupt or not atomic."""

    def __init__(
        self,
        message: str = "embedding query accepted stage is unavailable",
        *,
        code: str = "embedding_query_stage_invalid",
    ) -> None:
        super().__init__(message, code=code)


class SqlQueryExecutionPort(Protocol):
    """Lifecycle methods used by the injected query provider wrapper."""

    def mark_sending(self, operation_id: str) -> ProviderOperationV1:
        """CAS ``reserved`` to ``sending`` immediately before provider I/O."""

    def execute_batch(
        self,
        batch: EmbeddingBatchV1,
        provider: object,
        stage_store: EmbeddingStagePort,
    ) -> ValidatedEmbeddingBatchV1:
        """Run, validate, sanitize-stage and complete one query request."""


@dataclass(frozen=True, slots=True)
class SqlQueryRequestV1:
    """Exact hash-only context for one turn's query batch.

    Query text is intentionally absent.  The query service passes the same
    ordered hashes to every port call, while the persisted export manifest
    and policy/confirmation rows are loaded by the SQL adapter.
    """

    scope_id: str
    snapshot_id: str
    identity: EmbeddingIdentityV1
    policy_hash: str
    export_manifest_hash: str
    build_manifest_hash: str
    query_hashes: tuple[str, ...]
    attempt_no: int = 1
    logical_item_id: str | None = None
    confirmation_revision: int | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.scope_id, "scope id"),
            (self.snapshot_id, "snapshot id"),
        ):
            if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
                raise ValueError(f"query {name} is required")
        for value, name in (
            (self.policy_hash, "policy hash"),
            (self.export_manifest_hash, "export manifest hash"),
            (self.build_manifest_hash, "build manifest hash"),
        ):
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError(f"query {name} must be a lowercase SHA-256 digest")
        if not isinstance(self.identity, EmbeddingIdentityV1):
            raise ValueError("query identity is invalid")
        if not self.query_hashes or len(set(self.query_hashes)) != len(self.query_hashes):
            raise ValueError("query hashes must be non-empty and unique")
        for value in self.query_hashes:
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ValueError("query hash must be a lowercase SHA-256 digest")
        if isinstance(self.attempt_no, bool) or self.attempt_no < 1:
            raise ValueError("query attempt is invalid")
        if self.logical_item_id is not None and (
            not isinstance(self.logical_item_id, str)
            or not _SAFE_ID_RE.fullmatch(self.logical_item_id)
        ):
            raise ValueError("query logical item is invalid")
        if self.confirmation_revision is not None and (
            isinstance(self.confirmation_revision, bool) or self.confirmation_revision < 1
        ):
            raise ValueError("query confirmation revision is invalid")


def _canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SqlQueryError("query request identity is invalid") from exc
    return hashlib.sha256(encoded).hexdigest()


def _logical_item_id(request: SqlQueryRequestV1) -> str:
    return "query-" + _canonical_hash(
        {
            "scope_id": request.scope_id,
            "snapshot_id": request.snapshot_id,
            "identity": {
                "provider": request.identity.provider,
                "model_key": request.identity.model_key,
                "region": request.identity.region,
                "dimension": request.identity.dimension,
                "policy_version": request.identity.policy_version,
            },
            "build_manifest_hash": request.build_manifest_hash,
            "query_hashes": request.query_hashes,
        }
    )


def _request_hash(
    request: SqlQueryRequestV1,
    *,
    logical_item_id: str,
    total_tokens: int,
) -> str:
    return _canonical_hash(
        {
            "version": "embedding-query-sql-v1",
            "scope_id": request.scope_id,
            "snapshot_id": request.snapshot_id,
            "provider_operation": SQL_QUERY_PROVIDER_OPERATION,
            "logical_item_id": logical_item_id,
            "attempt_no": request.attempt_no,
            "policy_hash": request.policy_hash,
            "export_manifest_hash": request.export_manifest_hash,
            "build_manifest_hash": request.build_manifest_hash,
            "query_hashes": request.query_hashes,
            "total_tokens": total_tokens,
            "identity": {
                "provider": request.identity.provider,
                "model_key": request.identity.model_key,
                "region": request.identity.region,
                "dimension": request.identity.dimension,
                "policy_version": request.identity.policy_version,
            },
        }
    )


def _query_cost(total_tokens: int) -> float:
    try:
        cost = (Decimal(total_tokens) * SQL_QUERY_PRICE_CNY_PER_MILLION) / Decimal(1_000_000)
        # ProviderOperation.max_cost_cny is a Numeric(12, 6) column.  Freeze
        # the same six-decimal representation before the SQL insert so a
        # restart computes an identical idempotency request.
        return float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise SqlQueryBudgetError("query cost estimate is invalid") from exc


def _response_hash(value: ValidatedEmbeddingBatchV1) -> str:
    return _canonical_hash(
        {
            "build_id": value.build_id,
            "build_manifest_hash": value.build_manifest_hash,
            "batch_index": value.batch_index,
            "chunk_ids": value.chunk_ids,
            "provider": value.embedding_provider,
            "model_key": value.model_key,
            "region": value.embedding_region,
            "dimension": value.dimension,
            "policy_version": value.policy_version,
            "vectors": value.vectors,
        }
    )


def _safe_provider_code(error: object) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", code):
        return code
    return "embedding_query_failed"


def _provider_matches_identity(provider: object, identity: EmbeddingIdentityV1) -> bool:
    return all(
        getattr(provider, field_name, None) == expected
        for field_name, expected in (
            ("provider", identity.provider),
            ("model_key", identity.model_key),
            ("region", identity.region),
            ("dimension", identity.dimension),
            ("policy_version", identity.policy_version),
        )
    )


class SqlAlchemyQueryControlAdapter(
    QueryEmbeddingManifestPort,
    QueryEmbeddingControlPort,
    QueryEmbeddingBudgetPort,
    SqlQueryExecutionPort,
):
    """Persist one exact query attempt through ``ProviderRepository``.

    This adapter is intentionally preconfigured for a single turn/request.
    A caller must create another instance with a new ``attempt_no`` after a
    proven ``not_sent`` outcome; acceptance-unknown attempts are never
    automatically retried.
    """

    def __init__(
        self,
        database: Database | object,
        *,
        scope_id: str,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        policy_hash: str,
        export_manifest_hash: str,
        build_manifest_hash: str,
        query_hashes: tuple[str, ...],
        attempt_no: int = 1,
        logical_item_id: str | None = None,
        confirmation_revision: int | None = None,
        repository: ProviderRepository | None = None,
    ) -> None:
        try:
            request = SqlQueryRequestV1(
                scope_id=scope_id,
                snapshot_id=snapshot_id,
                identity=identity,
                policy_hash=policy_hash,
                export_manifest_hash=export_manifest_hash,
                build_manifest_hash=build_manifest_hash,
                query_hashes=tuple(query_hashes),
                attempt_no=attempt_no,
                logical_item_id=logical_item_id,
                confirmation_revision=confirmation_revision,
            )
        except (TypeError, ValueError) as exc:
            raise SqlQueryPreflightError("query request context is invalid") from exc
        self.request = request
        self.repository = repository or ProviderRepository(database)  # type: ignore[arg-type]
        self._lock = RLock()
        self._active_operation: ProviderOperationV1 | None = None

    @property
    def context(self) -> SqlQueryRequestV1:
        """Return the immutable hash-only request context."""

        return self.request

    @property
    def operation(self) -> ProviderOperationV1 | None:
        """Return the operation selected by the latest reservation call."""

        return self._active_operation

    @property
    def logical_item_id(self) -> str:
        return self.request.logical_item_id or _logical_item_id(self.request)

    def _load_exact_manifest(self) -> object:
        request = self.request
        try:
            policy = self.repository.get_policy_snapshot(request.policy_hash)
            manifest = self.repository.get_export_manifest(request.export_manifest_hash)
            confirmation = self.repository.get_export_confirmation(request.export_manifest_hash)
        except Exception as exc:
            raise SqlQueryPreflightError() from exc
        if policy is None or manifest is None or confirmation is None:
            raise SqlQueryPreflightError("query policy/export confirmation is missing")
        try:
            policy.validate()
            manifest.validate()
        except Exception as exc:
            raise SqlQueryPreflightError("query policy/export manifest is corrupt") from exc
        if (
            policy.policy_hash != request.policy_hash
            or manifest.manifest_hash != request.export_manifest_hash
            or manifest.scope_id != request.scope_id
            or manifest.provider_operation != SQL_QUERY_PROVIDER_OPERATION
            or manifest.model_key != request.identity.model_key
            or manifest.policy_hash != request.policy_hash
            or manifest.build_manifest_hash != request.build_manifest_hash
            or confirmation.manifest_hash != request.export_manifest_hash
            or confirmation.policy_hash != request.policy_hash
            or (
                request.confirmation_revision is not None
                and confirmation.confirmation_revision != request.confirmation_revision
            )
        ):
            raise SqlQueryPreflightError("query policy/export confirmation is stale")
        if request.identity != REAL_EMBEDDING_IDENTITY:
            raise SqlQueryIdentityError("SQL query identity is not the fixed real resource")
        return manifest

    def _assert_context(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object:
        request = self.request
        if (
            snapshot_id != request.snapshot_id
            or identity != request.identity
            or tuple(query_hashes) != request.query_hashes
        ):
            raise SqlQueryPreflightError("query request context does not match the frozen turn")
        if any(not _SHA256_RE.fullmatch(value) for value in request.query_hashes):
            raise SqlQueryPreflightError("query hash context is invalid")
        return self._load_exact_manifest()

    def require_exact_manifest(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object:
        with self._lock:
            return self._assert_context(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
            )

    def require_query_preflight(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object:
        with self._lock:
            return self._assert_context(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
            )

    def _ensure_budget(self) -> None:
        try:
            self.repository.save_scope_budget(
                self.request.scope_id,
                ProviderScopeBudgetV1(
                    max_requests=SQL_QUERY_MAX_REQUESTS,
                    max_total_tokens=SQL_QUERY_MAX_TOTAL_TOKENS,
                    max_cost_cny=SQL_QUERY_MAX_COST_CNY,
                ),
            )
        except Exception as exc:
            raise SqlQueryBudgetError("query scope budget is missing or drifted") from exc

    def _existing_operations(self) -> tuple[ProviderOperationV1, ...]:
        try:
            return tuple(
                operation
                for operation in self.repository.operations(scope_id=self.request.scope_id)
                if operation.provider_operation == SQL_QUERY_PROVIDER_OPERATION
                and operation.logical_item_id == self.logical_item_id
            )
        except Exception as exc:
            raise SqlQueryBudgetError("query operation ledger is unavailable") from exc

    def _check_prior_attempts(self, operations: Sequence[ProviderOperationV1]) -> None:
        for operation in operations:
            if operation.attempt_no == self.request.attempt_no:
                continue
            if operation.attempt_no > self.request.attempt_no:
                raise SqlQueryBudgetError("query attempt is older than an existing attempt")
            if operation.state != "not_sent":
                raise SqlQueryBudgetError(
                    "query retry is forbidden after provider acceptance is possible",
                    code="embedding_query_retry_forbidden",
                )

    def _request(self, total_tokens: int) -> ProviderReservationRequestV1:
        logical_item_id = self.logical_item_id
        return ProviderReservationRequestV1(
            scope_id=self.request.scope_id,
            provider_operation=SQL_QUERY_PROVIDER_OPERATION,
            logical_item_id=logical_item_id,
            attempt_no=self.request.attempt_no,
            request_hash=_request_hash(
                self.request,
                logical_item_id=logical_item_id,
                total_tokens=total_tokens,
            ),
            max_tokens=total_tokens,
            max_cost_cny=_query_cost(total_tokens),
            policy_hash=self.request.policy_hash,
            export_manifest_hash=self.request.export_manifest_hash,
            build_manifest_hash=self.request.build_manifest_hash,
            model_key=self.request.identity.model_key,
        )

    def reserve_query(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
        request_count: int,
        total_tokens: int,
    ) -> object:
        with self._lock:
            self._assert_context(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
            )
            if request_count != 1:
                raise SqlQueryBudgetError("one query batch must reserve exactly one request")
            if (
                isinstance(total_tokens, bool)
                or not isinstance(total_tokens, int)
                or total_tokens < 1
                or total_tokens > MAX_BATCH_TOKENS
                or total_tokens > SQL_QUERY_MAX_TOTAL_TOKENS
            ):
                raise SqlQueryBudgetError("query token allowance is invalid")
            self._ensure_budget()
            operations = self._existing_operations()
            self._check_prior_attempts(operations)
            current = next(
                (
                    operation
                    for operation in operations
                    if operation.attempt_no == self.request.attempt_no
                ),
                None,
            )
            request = self._request(total_tokens)
            if current is not None:
                if (
                    current.request_hash != request.request_hash
                    or current.policy_hash != request.policy_hash
                    or current.export_manifest_hash != request.export_manifest_hash
                    or current.build_manifest_hash != request.build_manifest_hash
                    or current.model_key != request.model_key
                    or current.max_tokens != request.max_tokens
                    or abs(current.max_cost_cny - request.max_cost_cny) > 1e-12
                ):
                    raise SqlQueryBudgetError("existing query operation drifted")
                if current.state == "acceptance_unknown":
                    raise SqlQueryBudgetError(
                        "query retry is forbidden after provider acceptance is possible",
                        code="embedding_query_retry_forbidden",
                    )
                if current.state in {"accepted", "succeeded"}:
                    self._active_operation = current
                    try:
                        return self.repository.reservation(current.id)
                    except Exception:
                        return current
                raise SqlQueryBudgetError(
                    "query attempt already exists and cannot be reused",
                    code="embedding_query_attempt_duplicate",
                )
            try:
                current = self.repository.create_prepared(request)
                self.repository.reserve(current.id)
                current = self.repository.operation(current.id)
            except Exception as exc:
                if current is not None:
                    try:
                        self.repository.mark_failed(
                            current.id,
                            safe_error_code="embedding_query_reservation_failed",
                        )
                    except Exception:
                        pass
                raise SqlQueryBudgetError("query reservation failed") from exc
            if current.state != "reserved":
                raise SqlQueryBudgetError("query reservation did not commit")
            self._active_operation = current
            try:
                return self.repository.reservation(current.id)
            except Exception as exc:
                raise SqlQueryBudgetError("query reservation could not be reloaded") from exc

    def mark_sending(self, operation_id: str) -> ProviderOperationV1:
        with self._lock:
            current = self.repository.operation(operation_id)
            if current.provider_operation != SQL_QUERY_PROVIDER_OPERATION:
                raise SqlQueryPreflightError("operation kind does not belong to query embedding")
            if current.state == "reserved":
                current = self.repository.transition(
                    operation_id,
                    expected="reserved",
                    state="sending",
                )
            elif current.state not in {"accepted", "succeeded"}:
                raise SqlQueryError("query operation is not ready for provider call")
            self._active_operation = current
            return current

    def _mark_failed(self, operation_id: str, error: object) -> None:
        try:
            current = self.repository.operation(operation_id)
            if current.state in {"reserved", "sending"}:
                self.repository.mark_failed(
                    operation_id,
                    safe_error_code=_safe_provider_code(error),
                )
        except Exception:
            # The operation remains durably consumed if its failure CAS cannot
            # be observed; a later startup reconciliation must not retry it.
            pass

    def _validate_batch(self, batch: object) -> EmbeddingBatchV1:
        if not isinstance(batch, EmbeddingBatchV1):
            raise SqlQueryPreflightError("query batch metadata is incomplete")
        request = self.request
        if (
            batch.build_id != f"query:{request.snapshot_id}"
            or batch.build_manifest_hash != request.build_manifest_hash
            or batch.batch_index != 0
            or batch.chunk_ids != request.query_hashes
            or batch.model_key != request.identity.model_key
            or batch.dimension != request.identity.dimension
            or batch.embedding_provider != request.identity.provider
            or batch.embedding_region != request.identity.region
            or batch.policy_version != request.identity.policy_version
        ):
            raise SqlQueryPreflightError("query batch does not match the frozen request")
        if len(batch.items) != len(request.query_hashes):
            raise SqlQueryPreflightError("query batch item count does not match the request")
        if any(
            item.chunk_id != query_hash
            or item.chunk_sha256 != query_hash
            or not isinstance(item.text, str)
            or "\x00" in item.text
            or hashlib.sha256(item.text.strip().encode("utf-8")).hexdigest() != query_hash
            for item, query_hash in zip(batch.items, request.query_hashes, strict=True)
        ):
            raise SqlQueryPreflightError("query text hash does not match the frozen request")
        return batch

    def _stage_result(
        self,
        operation: ProviderOperationV1,
        batch: EmbeddingBatchV1,
        stage_store: EmbeddingStagePort,
    ) -> ValidatedEmbeddingBatchV1:
        try:
            stage = stage_store.get(operation.id)
        except Exception as exc:
            raise SqlQueryStageError("query accepted stage is corrupt") from exc
        if stage is None:
            raise SqlQueryStageError("query accepted stage is missing")
        if (
            not isinstance(stage, AcceptedEmbeddingStageV1)
            or stage.operation_id != operation.id
            or stage.build_id != batch.build_id
            or stage.build_manifest_hash != batch.build_manifest_hash
            or stage.batch_index != batch.batch_index
            or stage.chunk_ids != batch.chunk_ids
            or stage.model_key != self.request.identity.model_key
            or stage.dimension != self.request.identity.dimension
            or stage.embedding_provider != self.request.identity.provider
            or stage.embedding_region != self.request.identity.region
            or stage.policy_version != self.request.identity.policy_version
            or (
                operation.staged_response_hash is not None
                and operation.staged_response_hash != stage.response_hash
            )
        ):
            raise SqlQueryStageError("query accepted stage identity drifted")
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
            if _response_hash(value) != stage.response_hash:
                raise SqlQueryStageError("query accepted stage response hash is invalid")
            return value
        except Exception as exc:
            raise SqlQueryStageError("query accepted stage vectors are corrupt") from exc

    def _resume_if_staged(
        self,
        operation: ProviderOperationV1,
        batch: EmbeddingBatchV1,
        stage_store: EmbeddingStagePort,
    ) -> ValidatedEmbeddingBatchV1 | None:
        if operation.state not in {"accepted", "succeeded"}:
            return None
        value = self._stage_result(operation, batch, stage_store)
        if operation.state == "accepted":
            operation = self.repository.mark_succeeded(operation.id)
        self._active_operation = operation
        return value

    def execute_batch(
        self,
        batch: object,
        provider: object,
        stage_store: EmbeddingStagePort,
    ) -> ValidatedEmbeddingBatchV1:
        with self._lock:
            operation = self._active_operation
            if operation is None:
                raise SqlQueryError("query operation was not reserved")
            try:
                query_batch = self._validate_batch(batch)
            except SqlQueryError as exc:
                self._mark_failed(operation.id, exc)
                raise QueryEmbeddingProviderError() from exc
            if query_batch.total_tokens != operation.max_tokens:
                mismatch = SqlQueryPreflightError(
                    "query token allowance does not match the operation"
                )
                self._mark_failed(operation.id, mismatch)
                raise QueryEmbeddingProviderError() from mismatch
            resumed = self._resume_if_staged(operation, query_batch, stage_store)
            if resumed is not None:
                return resumed
            if operation.state != "reserved":
                raise SqlQueryError("query operation cannot issue a provider request")
            if not _provider_matches_identity(provider, self.request.identity):
                self._mark_failed(operation.id, SqlQueryIdentityError())
                raise QueryEmbeddingProviderError("query provider identity drifted")
            try:
                operation = self.mark_sending(operation.id)
            except Exception as exc:
                raise SqlQueryError("query sending transition failed") from exc
            try:
                method = getattr(provider, "embed_batch", None)
                if not callable(method):
                    raise TypeError("query provider does not implement embed_batch")
                result = method(query_batch)
            except Exception as exc:
                from app.modules.knowledge.providers.adapters import (
                    EmbeddingAcceptanceUnknown,
                    EmbeddingProviderError,
                    EmbeddingTransportNotSent,
                )

                if isinstance(exc, EmbeddingTransportNotSent) or (
                    isinstance(exc, EmbeddingProviderError)
                    and getattr(exc, "code", None) == "provider_not_sent"
                ):
                    self.repository.mark_not_sent(operation.id)
                    raise
                if isinstance(exc, EmbeddingAcceptanceUnknown) or (
                    isinstance(exc, EmbeddingProviderError)
                    and getattr(exc, "code", None) == "acceptance_unknown"
                ) or isinstance(
                    exc, (TimeoutError, ConnectionError)
                ):
                    self.repository.mark_acceptance_unknown(operation.id)
                    if isinstance(exc, EmbeddingAcceptanceUnknown):
                        raise
                    raise EmbeddingAcceptanceUnknown() from exc
                self._mark_failed(operation.id, exc)
                if isinstance(exc, QueryEmbeddingError):
                    raise
                raise QueryEmbeddingProviderError() from exc
            if not isinstance(result, ValidatedEmbeddingBatchV1):
                self._mark_failed(operation.id, QueryEmbeddingProviderError())
                raise QueryEmbeddingProviderError("query provider result is not validated")
            if (
                result.build_id != query_batch.build_id
                or result.build_manifest_hash != query_batch.build_manifest_hash
                or result.batch_index != query_batch.batch_index
                or result.chunk_ids != query_batch.chunk_ids
                or result.model_key != self.request.identity.model_key
                or result.dimension != self.request.identity.dimension
                or result.embedding_provider != self.request.identity.provider
                or result.embedding_region != self.request.identity.region
                or result.policy_version != self.request.identity.policy_version
            ):
                self._mark_failed(operation.id, QueryEmbeddingProviderError())
                raise QueryEmbeddingProviderError("query provider result identity drifted")
            try:
                response_hash = _response_hash(result)
            except Exception as exc:
                self._mark_failed(operation.id, exc)
                raise QueryEmbeddingProviderError(
                    "query provider response hash is invalid"
                ) from exc
            try:
                expected = AcceptedEmbeddingStageV1.from_result(
                    operation.id,
                    result,
                    response_hash=response_hash,
                )
                method = getattr(stage_store, "stage_accepted", None)
                if not callable(method):
                    method = getattr(stage_store, "stage_and_accept", None)
                if not callable(method):
                    raise SqlQueryStageError(
                        code="embedding_query_stage_extension_required",
                    )
                stage = method(expected)
                if not isinstance(stage, AcceptedEmbeddingStageV1) or stage != expected:
                    raise SqlQueryStageError("query accepted stage changed")
                operation = self.repository.operation(operation.id)
                if operation.state != "accepted":
                    raise SqlQueryStageError(
                        "query accepted stage did not atomically accept operation",
                        code="embedding_query_stage_extension_required",
                    )
                operation = self.repository.mark_succeeded(operation.id)
            except Exception as exc:
                self._mark_failed(operation.id, exc)
                if isinstance(exc, QueryEmbeddingError):
                    raise
                if isinstance(exc, SqlQueryError):
                    raise QueryEmbeddingProviderError() from exc
                if isinstance(exc, SnapshotEmbeddingRuntimeError):
                    raise QueryEmbeddingProviderError() from exc
                raise QueryEmbeddingProviderError() from exc
            self._active_operation = operation
            return result


class SqlQueryBatchProvider:
    """Controlled provider wrapper used by :class:`QueryEmbeddingService`."""

    def __init__(
        self,
        provider: QueryEmbeddingBatchProvider | object,
        *,
        control: SqlAlchemyQueryControlAdapter,
        stage_store: EmbeddingStagePort,
    ) -> None:
        if not callable(getattr(provider, "embed_batch", None)):
            raise SqlQueryPreflightError("query provider does not implement embed_batch")
        if stage_store is None or not callable(getattr(stage_store, "get", None)):
            raise SqlQueryStageError("query accepted stage store is unavailable")
        identity_values = tuple(
            getattr(provider, field_name, None)
            for field_name in ("provider", "model_key", "region", "dimension", "policy_version")
        )
        if any(value is None for value in identity_values):
            raise SqlQueryIdentityError("query provider identity is incomplete")
        self._provider = provider
        self.control = control
        self.stage_store = stage_store
        self.provider = cast(str, identity_values[0])
        self.model_key = cast(str, identity_values[1])
        self.region = cast(str, identity_values[2])
        self.dimension = cast(int, identity_values[3])
        self.policy_version = cast(str, identity_values[4])
        if (
            self.provider != control.request.identity.provider
            or self.model_key != control.request.identity.model_key
            or self.region != control.request.identity.region
            or self.dimension != control.request.identity.dimension
            or self.policy_version != control.request.identity.policy_version
        ):
            raise SqlQueryIdentityError("query provider identity does not match Snapshot")

    def embed_batch(self, batch: object) -> ValidatedEmbeddingBatchV1:
        return self.control.execute_batch(batch, self._provider, self.stage_store)

    embed = embed_batch


def controlled_query_provider(
    provider: QueryEmbeddingBatchProvider | object,
    *,
    control: SqlAlchemyQueryControlAdapter,
    stage_store: EmbeddingStagePort,
) -> SqlQueryBatchProvider:
    """Construct the provider wrapper without selecting or contacting a provider."""

    return SqlQueryBatchProvider(provider, control=control, stage_store=stage_store)


__all__ = [
    "SQL_QUERY_MAX_COST_CNY",
    "SQL_QUERY_MAX_REQUESTS",
    "SQL_QUERY_MAX_TOTAL_TOKENS",
    "SQL_QUERY_PRICE_CNY_PER_MILLION",
    "SQL_QUERY_PROVIDER_OPERATION",
    "SqlAlchemyQueryControlAdapter",
    "SqlQueryBatchProvider",
    "SqlQueryBudgetError",
    "SqlQueryControlAdapter",
    "SqlQueryError",
    "SqlQueryExecutionPort",
    "SqlQueryPreflightError",
    "SqlQueryProvider",
    "SqlQueryRequestV1",
    "SqlQueryStageError",
    "controlled_query_provider",
]


# Short descriptive aliases keep the seam easy to discover without a second
# implementation.  The SQLAlchemy-prefixed class remains canonical.
SqlQueryControlAdapter = SqlAlchemyQueryControlAdapter
SqlQueryProvider = SqlQueryBatchProvider
