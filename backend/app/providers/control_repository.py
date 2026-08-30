"""SQLite/SQLAlchemy persistence for the server-only ProviderDataCall ledger.

The repository is intentionally not wired to a selector, route or provider
adapter.  It persists only the immutable policy/export hashes, conservative
allowances and operation states defined in :mod:`app.providers.control`.
External callers should commit ``sending`` immediately before a provider
adapter is invoked; this module never performs that invocation itself.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import Engine, Table, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.core.db import Database
from app.core.models import (
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    ProviderPolicySnapshot,
    ProviderReservation,
    ProviderScopeBudget,
)
from app.providers.control import (
    BudgetExceeded,
    DuplicateOperation,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    OperationState,
    OperationStateError,
    ProviderOperationV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderReservationV1,
    ProviderScopeBudgetV1,
    ReservationState,
    can_transition,
    startup_recovery_state,
)

_POLICY_TABLE = cast(Table, ProviderPolicySnapshot.__table__)
_MANIFEST_TABLE = cast(Table, ProviderExportManifest.__table__)
_CONFIRMATION_TABLE = cast(Table, ProviderExportConfirmation.__table__)
_BUDGET_TABLE = cast(Table, ProviderScopeBudget.__table__)
_OPERATION_TABLE = cast(Table, ProviderOperation.__table__)
_RESERVATION_TABLE = cast(Table, ProviderReservation.__table__)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProviderRepositoryError(RuntimeError):
    """A durable ProviderDataCall operation cannot proceed safely."""


class ScopeBudgetMissing(ProviderRepositoryError):
    """A scope has no explicitly frozen request/token/cost budget."""


class PolicyExportStale(ProviderRepositoryError):
    """An operation does not match a confirmed policy/export hash pair."""


class ProviderRepository:
    """Durable ORM repository implementing the ProviderOperationRepository port."""

    def __init__(
        self,
        database: Database | Engine | Session,
        *,
        require_export_confirmation: bool = True,
    ) -> None:
        if isinstance(database, Database):
            self.engine = database.engine
        elif isinstance(database, Engine):
            self.engine = database
        elif isinstance(database, Session):
            bind = database.get_bind()
            if not isinstance(bind, Engine):
                raise TypeError("ProviderRepository requires a SQLAlchemy Engine")
            self.engine = bind
        else:
            raise TypeError("ProviderRepository requires Database, Engine or Session")
        self.require_export_confirmation = require_export_confirmation

    @contextmanager
    def _write_connection(self) -> Iterator[Connection]:
        """Open one independent transaction, serializing SQLite writers."""

        connection = self.engine.connect()
        committed = False
        try:
            if self.engine.dialect.name == "sqlite":
                # A scope budget update must not be a read-then-write race.
                # BEGIN IMMEDIATE acquires SQLite's RESERVED writer lock before
                # the budget row is read.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            yield connection
            connection.commit()
            committed = True
        finally:
            if not committed:
                connection.rollback()
            connection.close()

    def _read_one(self, statement: Executable) -> Mapping[str, object] | None:
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
            return cast(Mapping[str, object] | None, row)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ------------------------------------------------------------------
    # Policy/export persistence and hash CAS
    # ------------------------------------------------------------------
    def save_policy_snapshot(
        self,
        policy: ProviderPolicySnapshotV1,
        *,
        snapshot_id: str | None = None,
    ) -> str:
        policy.validate()
        row_id = snapshot_id or str(uuid4())
        values = {
            "id": row_id,
            "policy_id": policy.policy_id,
            "contract_version": "ProviderDataCallV1",
            "supplier": policy.supplier,
            "region": policy.region,
            "account_product": policy.account_product,
            "endpoint": policy.endpoint,
            "privacy_notice_url": policy.privacy_notice_url,
            "privacy_notice_retrieved_at": policy.privacy_notice_retrieved_at,
            "privacy_notice_sha256": policy.privacy_notice_sha256,
            "service_terms_url": policy.service_terms_url,
            "service_terms_retrieved_at": policy.service_terms_retrieved_at,
            "service_terms_sha256": policy.service_terms_sha256,
            "faq_url": policy.faq_url,
            "faq_retrieved_at": policy.faq_retrieved_at,
            "faq_sha256": policy.faq_sha256,
            "no_training_basis": policy.no_training_basis,
            "prompt_response_logging_disabled": policy.prompt_response_logging_disabled,
            "inference_log_backflow_disabled": policy.inference_log_backflow_disabled,
            "optional_content_logging_disabled": policy.optional_content_logging_disabled,
            "service_improvement_disabled": policy.service_improvement_disabled,
            "storage_disclosed": policy.storage_disclosed,
            "retention_setting": policy.retention_setting,
            "snapshot_revision": policy.snapshot_revision,
            "policy_hash": policy.policy_hash,
            "created_at": self._now(),
        }
        try:
            with self._write_connection() as connection:
                connection.execute(_POLICY_TABLE.insert().values(**values))
        except IntegrityError as exc:
            raise ProviderRepositoryError("provider policy snapshot already exists") from exc
        return row_id

    persist_policy_snapshot = save_policy_snapshot

    def get_policy_snapshot(self, policy_hash_or_id: str) -> ProviderPolicySnapshotV1 | None:
        table = _POLICY_TABLE
        row = self._read_one(
            select(table).where(
                (table.c.id == policy_hash_or_id) | (table.c.policy_hash == policy_hash_or_id)
            )
        )
        return _policy_from_row(row) if row is not None else None

    def save_export_manifest(
        self,
        manifest: ExportManifestV1,
        *,
        policy_snapshot_id: str,
        manifest_id: str | None = None,
        course_id: str | None = None,
        group_id: str | None = None,
        agent_version_id: str | None = None,
    ) -> str:
        manifest.validate()
        policy_table = _POLICY_TABLE
        policy_row = self._read_one(
            select(policy_table).where(policy_table.c.id == policy_snapshot_id)
        )
        if policy_row is None or policy_row["policy_hash"] != manifest.policy_hash:
            raise PolicyExportStale("export manifest policy hash is not current")
        row_id = manifest_id or str(uuid4())
        fields_json = json.dumps(
            [item.canonical_dict() for item in manifest.fields],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        values = {
            "id": row_id,
            "policy_snapshot_id": policy_snapshot_id,
            "scope_id": manifest.scope_id,
            "provider_operation": manifest.provider_operation,
            "model_key": manifest.model_key,
            "policy_hash": manifest.policy_hash,
            "build_manifest_hash": manifest.build_manifest_hash,
            "persona_spec_hash": manifest.persona_spec_hash,
            "fields_json": fields_json,
            "operation_revision": manifest.operation_revision,
            "contains_secret": manifest.contains_secret,
            "contains_identity": manifest.contains_identity,
            "contains_private_audio": manifest.contains_private_audio,
            "contains_teacher_note": manifest.contains_teacher_note,
            "manifest_hash": manifest.manifest_hash,
            "course_id": course_id,
            "group_id": group_id,
            "agent_version_id": agent_version_id,
            "created_at": self._now(),
        }
        try:
            with self._write_connection() as connection:
                connection.execute(_MANIFEST_TABLE.insert().values(**values))
        except IntegrityError as exc:
            raise ProviderRepositoryError("provider export manifest already exists") from exc
        return row_id

    persist_export_manifest = save_export_manifest

    def ensure_export_manifest(
        self,
        manifest: ExportManifestV1,
        *,
        policy_snapshot_id: str,
        manifest_id: str | None = None,
        course_id: str | None = None,
        group_id: str | None = None,
        agent_version_id: str | None = None,
    ) -> str:
        """Insert once or verify the exact immutable manifest and owner tuple."""

        try:
            return self.save_export_manifest(
                manifest,
                policy_snapshot_id=policy_snapshot_id,
                manifest_id=manifest_id,
                course_id=course_id,
                group_id=group_id,
                agent_version_id=agent_version_id,
            )
        except ProviderRepositoryError as error:
            row = self._read_one(
                select(_MANIFEST_TABLE).where(
                    _MANIFEST_TABLE.c.manifest_hash == manifest.manifest_hash
                )
            )
            if row is None:
                raise
            try:
                persisted = _manifest_from_row(row)
            except Exception as exc:
                raise ProviderRepositoryError("provider export manifest is corrupt") from exc
            if (
                persisted != manifest
                or str(row["policy_snapshot_id"]) != policy_snapshot_id
                or _optional_string(row["course_id"]) != course_id
                or _optional_string(row["group_id"]) != group_id
                or _optional_string(row["agent_version_id"]) != agent_version_id
            ):
                raise ProviderRepositoryError(
                    "provider export manifest already exists with different ownership"
                ) from error
            return str(row["id"])

    def get_export_manifest(self, manifest_hash_or_id: str) -> ExportManifestV1 | None:
        table = _MANIFEST_TABLE
        row = self._read_one(
            select(table).where(
                (table.c.id == manifest_hash_or_id) | (table.c.manifest_hash == manifest_hash_or_id)
            )
        )
        return _manifest_from_row(row) if row is not None else None

    def get_export_confirmation(self, manifest_hash: str) -> ExportConfirmationV1 | None:
        row = self._read_one(
            select(_CONFIRMATION_TABLE).where(_CONFIRMATION_TABLE.c.manifest_hash == manifest_hash)
        )
        return _confirmation_from_row(row) if row is not None else None

    def save_export_confirmation(
        self,
        manifest_id: str,
        confirmation: ExportConfirmationV1,
        *,
        confirmation_id: str | None = None,
    ) -> str:
        manifest_table = _MANIFEST_TABLE
        manifest_row = self._read_one(
            select(manifest_table).where(manifest_table.c.id == manifest_id)
        )
        if manifest_row is None:
            raise PolicyExportStale("export manifest does not exist")
        if (
            manifest_row["manifest_hash"] != confirmation.manifest_hash
            or manifest_row["policy_hash"] != confirmation.policy_hash
        ):
            raise PolicyExportStale("export confirmation hash is stale")
        row_id = confirmation_id or str(uuid4())
        values = {
            "id": row_id,
            "manifest_id": manifest_id,
            "policy_snapshot_id": manifest_row["policy_snapshot_id"],
            "manifest_hash": confirmation.manifest_hash,
            "policy_hash": confirmation.policy_hash,
            "confirmed_at": confirmation.confirmed_at,
            "confirmation_revision": confirmation.confirmation_revision,
            "created_at": self._now(),
        }
        try:
            with self._write_connection() as connection:
                connection.execute(_CONFIRMATION_TABLE.insert().values(**values))
        except IntegrityError as exc:
            raise ProviderRepositoryError("provider export confirmation already exists") from exc
        return row_id

    persist_export_confirmation = save_export_confirmation

    def assert_hashes_current(
        self,
        request: ProviderReservationRequestV1,
    ) -> None:
        """Require an exact confirmed policy/export pair for one operation."""

        manifest_table = _MANIFEST_TABLE
        confirmation_table = _CONFIRMATION_TABLE
        policy_table = _POLICY_TABLE
        row = self._read_one(
            select(
                manifest_table.c.scope_id,
                manifest_table.c.provider_operation,
                manifest_table.c.model_key,
                manifest_table.c.build_manifest_hash,
                manifest_table.c.policy_hash,
                confirmation_table.c.manifest_hash.label("confirmed_manifest_hash"),
                confirmation_table.c.policy_hash.label("confirmed_policy_hash"),
                policy_table.c.policy_hash.label("current_policy_hash"),
            )
            .join(
                confirmation_table,
                confirmation_table.c.manifest_id == manifest_table.c.id,
            )
            .join(
                policy_table,
                policy_table.c.id == manifest_table.c.policy_snapshot_id,
            )
            .where(
                manifest_table.c.scope_id == request.scope_id,
                manifest_table.c.provider_operation == request.provider_operation,
                manifest_table.c.manifest_hash == request.export_manifest_hash,
                confirmation_table.c.manifest_hash == request.export_manifest_hash,
                confirmation_table.c.policy_hash == request.policy_hash,
            )
        )
        if row is None or row["current_policy_hash"] != request.policy_hash:
            raise PolicyExportStale("provider policy/export confirmation is stale")
        if request.model_key and row["model_key"] != request.model_key:
            raise PolicyExportStale("provider export model is stale")
        if (
            request.build_manifest_hash
            and row["build_manifest_hash"] != request.build_manifest_hash
        ):
            raise PolicyExportStale("provider export build hash is stale")

    validate_hashes_current = assert_hashes_current

    # ------------------------------------------------------------------
    # Scope budgets and operation lifecycle
    # ------------------------------------------------------------------
    def save_scope_budget(
        self,
        scope_id: str,
        budget: ProviderScopeBudgetV1,
        *,
        replace_empty: bool = False,
    ) -> None:
        if not scope_id:
            raise ProviderRepositoryError("scope id is required")
        budget_row = {
            "scope_id": scope_id,
            "max_requests": budget.max_requests,
            "max_total_tokens": budget.max_total_tokens,
            "max_cost_cny": budget.max_cost_cny,
            "allocated_requests": 0,
            "allocated_total_tokens": 0,
            "allocated_cost_cny": 0,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        table = _BUDGET_TABLE
        with self._write_connection() as connection:
            existing = (
                connection.execute(select(table).where(table.c.scope_id == scope_id))
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(table.insert().values(**budget_row))
                return
            if not replace_empty:
                if (
                    _as_int(existing["max_requests"]) != budget.max_requests
                    or _as_int(existing["max_total_tokens"]) != budget.max_total_tokens
                    or _as_float(existing["max_cost_cny"]) != float(budget.max_cost_cny)
                ):
                    raise ProviderRepositoryError("scope budget already has different caps")
                return
            if (
                _as_int(existing["allocated_requests"] or 0) != 0
                or _as_int(existing["allocated_total_tokens"] or 0) != 0
                or _as_float(existing["allocated_cost_cny"] or 0) != 0
            ):
                raise ProviderRepositoryError("cannot replace a used scope budget")
            connection.execute(
                update(table)
                .where(table.c.scope_id == scope_id)
                .values(
                    max_requests=budget.max_requests,
                    max_total_tokens=budget.max_total_tokens,
                    max_cost_cny=budget.max_cost_cny,
                    updated_at=self._now(),
                )
            )

    ensure_scope_budget = save_scope_budget

    def get_scope_budget(self, scope_id: str) -> ProviderScopeBudgetV1 | None:
        table = _BUDGET_TABLE
        row = self._read_one(select(table).where(table.c.scope_id == scope_id))
        if row is None:
            return None
        return ProviderScopeBudgetV1(
            max_requests=_as_int(row["max_requests"]),
            max_total_tokens=_as_int(row["max_total_tokens"]),
            max_cost_cny=_as_float(row["max_cost_cny"]),
        )

    def create_prepared(self, request: ProviderReservationRequestV1) -> ProviderOperationV1:
        if self.require_export_confirmation:
            self.assert_hashes_current(request)
        operation_id = request.operation_id or str(uuid4())
        now = self._now()
        values = {
            "id": operation_id,
            "scope_id": request.scope_id,
            "provider_operation": request.provider_operation,
            "logical_item_id": request.logical_item_id,
            "attempt_no": request.attempt_no,
            "request_hash": request.request_hash,
            "max_tokens": request.max_tokens,
            "max_cost_cny": request.max_cost_cny,
            "policy_hash": request.policy_hash,
            "export_manifest_hash": request.export_manifest_hash,
            "build_manifest_hash": request.build_manifest_hash,
            "model_key": request.model_key,
            "state": "prepared",
            "request_count": 0,
            "charged_request_count": 0,
            "staged_response_hash": None,
            "safe_error_code": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self._write_connection() as connection:
                connection.execute(_OPERATION_TABLE.insert().values(**values))
        except IntegrityError as exc:
            raise DuplicateOperation("provider attempt already exists") from exc
        return self.operation(operation_id)

    create = create_prepared

    def get(self, operation_id: str) -> ProviderOperationV1 | None:
        table = _OPERATION_TABLE
        row = self._read_one(select(table).where(table.c.id == operation_id))
        if row is None:
            return None
        return self._hydrate_operation(_operation_from_row(row))

    def _hydrate_operation(self, operation: ProviderOperationV1) -> ProviderOperationV1:
        """Attach the durable reservation id to the domain projection."""

        reservation_row = self._read_one(
            select(_RESERVATION_TABLE.c.id).where(_RESERVATION_TABLE.c.operation_id == operation.id)
        )
        if reservation_row is None:
            return operation
        return replace(operation, reservation_id=str(reservation_row["id"]))

    def operation(self, operation_id: str) -> ProviderOperationV1:
        value = self.get(operation_id)
        if value is None:
            raise OperationStateError("provider operation does not exist")
        return value

    def reservation(self, operation_id: str) -> ProviderReservationV1:
        operation = self.operation(operation_id)
        table = _RESERVATION_TABLE
        row = self._read_one(select(table).where(table.c.operation_id == operation.id))
        if row is None:
            raise OperationStateError("provider reservation does not exist")
        return _reservation_from_row(row)

    def reserve(self, operation_id: str) -> ProviderReservationV1:
        """Atomically allocate one scope budget before any provider I/O."""

        operation_table = _OPERATION_TABLE
        budget_table = _BUDGET_TABLE
        reservation_table = _RESERVATION_TABLE
        with self._write_connection() as connection:
            operation_row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == operation_id)
                )
                .mappings()
                .first()
            )
            if operation_row is None:
                raise OperationStateError("provider operation does not exist")
            if operation_row["state"] != "prepared":
                raise OperationStateError("provider operation is not reservable")
            budget_row = (
                connection.execute(
                    select(budget_table).where(budget_table.c.scope_id == operation_row["scope_id"])
                )
                .mappings()
                .first()
            )
            if budget_row is None:
                raise ScopeBudgetMissing("scope budget is not prepared")
            allocated_requests = _as_int(budget_row["allocated_requests"] or 0)
            allocated_tokens = _as_int(budget_row["allocated_total_tokens"] or 0)
            allocated_cost = _as_float(budget_row["allocated_cost_cny"] or 0)
            if (
                allocated_requests + 1 > _as_int(budget_row["max_requests"])
                or allocated_tokens + _as_int(operation_row["max_tokens"])
                > _as_int(budget_row["max_total_tokens"])
                or allocated_cost + _as_float(operation_row["max_cost_cny"])
                > _as_float(budget_row["max_cost_cny"]) + 1e-12
            ):
                raise BudgetExceeded("provider scope allowance exceeded")
            reservation_id = str(uuid4())
            now = self._now()
            connection.execute(
                update(budget_table)
                .where(budget_table.c.scope_id == operation_row["scope_id"])
                .values(
                    allocated_requests=allocated_requests + 1,
                    allocated_total_tokens=allocated_tokens + _as_int(operation_row["max_tokens"]),
                    allocated_cost_cny=allocated_cost + _as_float(operation_row["max_cost_cny"]),
                    updated_at=now,
                )
            )
            connection.execute(
                reservation_table.insert().values(
                    id=reservation_id,
                    operation_id=operation_id,
                    scope_id=operation_row["scope_id"],
                    provider_operation=operation_row["provider_operation"],
                    logical_item_id=operation_row["logical_item_id"],
                    attempt_no=operation_row["attempt_no"],
                    max_tokens=operation_row["max_tokens"],
                    max_cost_cny=operation_row["max_cost_cny"],
                    state="reserved",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(operation_table)
                .where(operation_table.c.id == operation_id)
                .values(
                    state="reserved",
                    request_count=_as_int(operation_row["request_count"] or 0) + 1,
                    charged_request_count=_as_int(operation_row["charged_request_count"] or 0) + 1,
                    updated_at=now,
                )
            )
        return self.reservation(operation_id)

    def transition(
        self,
        operation_id: str,
        *,
        expected: OperationState,
        state: OperationState,
        safe_error_code: str | None = None,
        response_hash: str | None = None,
    ) -> ProviderOperationV1:
        operation_table = _OPERATION_TABLE
        reservation_table = _RESERVATION_TABLE
        budget_table = _BUDGET_TABLE
        with self._write_connection() as connection:
            row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == operation_id)
                )
                .mappings()
                .first()
            )
            if row is None:
                raise OperationStateError("provider operation does not exist")
            current = cast(OperationState, str(row["state"]))
            if current != expected:
                raise OperationStateError("provider operation CAS fence failed")
            if not can_transition(expected, state):
                raise OperationStateError(
                    f"invalid provider operation transition: {expected}->{state}"
                )
            if state == "accepted" and response_hash is None:
                raise ProviderRepositoryError("accepted operation needs staged response hash")
            if response_hash is not None and not _SHA256_RE.fullmatch(response_hash):
                raise ProviderRepositoryError("staged response hash is invalid")
            now = self._now()
            values: dict[str, object] = {
                "state": state,
                "safe_error_code": _safe_code(safe_error_code)
                if safe_error_code
                else row["safe_error_code"],
                "updated_at": now,
            }
            if response_hash is not None:
                values["staged_response_hash"] = response_hash
            connection.execute(
                update(operation_table)
                .where(operation_table.c.id == operation_id, operation_table.c.state == expected)
                .values(**values)
            )
            reservation_row = (
                connection.execute(
                    select(reservation_table).where(
                        reservation_table.c.operation_id == operation_id
                    )
                )
                .mappings()
                .first()
            )
            if reservation_row is not None:
                connection.execute(
                    update(reservation_table)
                    .where(reservation_table.c.operation_id == operation_id)
                    .values(state=state, updated_at=now)
                )
            if state == "not_sent" and reservation_row is not None:
                # Releasing is part of the same transaction as the state CAS.
                connection.execute(
                    update(budget_table)
                    .where(budget_table.c.scope_id == row["scope_id"])
                    .values(
                        allocated_requests=budget_table.c.allocated_requests - 1,
                        allocated_total_tokens=budget_table.c.allocated_total_tokens
                        - _as_int(row["max_tokens"]),
                        allocated_cost_cny=budget_table.c.allocated_cost_cny
                        - _as_float(row["max_cost_cny"]),
                        updated_at=now,
                    )
                )
        return self.operation(operation_id)

    def mark_not_sent(
        self, operation_id: str, *, safe_error_code: str = "provider_not_sent"
    ) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="not_sent",
            safe_error_code=safe_error_code,
        )

    def mark_acceptance_unknown(
        self, operation_id: str, *, safe_error_code: str = "acceptance_unknown"
    ) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="acceptance_unknown",
            safe_error_code=safe_error_code,
        )

    def mark_accepted(self, operation_id: str, *, response_hash: str) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="accepted",
            response_hash=response_hash,
        )

    def mark_succeeded(self, operation_id: str) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="succeeded",
        )

    def mark_failed(
        self, operation_id: str, *, safe_error_code: str = "provider_failed"
    ) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="failed",
            safe_error_code=safe_error_code,
        )

    def abandon(self, operation_id: str) -> ProviderOperationV1:
        current = self.operation(operation_id)
        return self.transition(
            operation_id,
            expected=current.state,
            state="abandoned",
        )

    def recover_one(
        self,
        operation_id: str,
        *,
        staged_response_complete: bool | None = None,
    ) -> ProviderOperationV1:
        current = self.operation(operation_id)
        complete = (
            current.staged_response_hash is not None
            if staged_response_complete is None
            else staged_response_complete
        )
        target = startup_recovery_state(current.state, staged_response_complete=complete)
        if target == current.state:
            return current
        if target == "not_sent":
            return self.mark_not_sent(operation_id, safe_error_code="recovered_not_sent")
        return self.mark_acceptance_unknown(
            operation_id,
            safe_error_code="recovered_acceptance_unknown",
        )

    def recover_startup(self) -> tuple[ProviderOperationV1, ...]:
        table = _OPERATION_TABLE
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(table.c.id).where(table.c.state.in_(("reserved", "sending", "accepted")))
            ).all()
        return tuple(self.recover_one(str(row[0])) for row in rows)

    def operations(self, *, scope_id: str | None = None) -> tuple[ProviderOperationV1, ...]:
        table = _OPERATION_TABLE
        statement = select(table).order_by(table.c.created_at, table.c.id)
        if scope_id is not None:
            statement = statement.where(table.c.scope_id == scope_id)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return tuple(
            self._hydrate_operation(_operation_from_row(cast(Mapping[str, object], row)))
            for row in rows
        )


def _safe_code(value: str, default: str = "provider_failed") -> str:
    if (
        len(value) > 64
        or not value
        or not all(char.isascii() and (char.isalnum() or char in "_.:-") for char in value)
    ):
        return default
    return value


def _as_int(value: object) -> int:
    return int(str(value))


def _as_float(value: object) -> float:
    return float(str(value))


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _policy_from_row(row: Mapping[str, object]) -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        policy_id=str(row["policy_id"]),
        supplier=str(row["supplier"]),
        region=str(row["region"]),
        account_product=str(row["account_product"]),
        endpoint=str(row["endpoint"]),
        privacy_notice_url=str(row["privacy_notice_url"]),
        privacy_notice_retrieved_at=str(row["privacy_notice_retrieved_at"]),
        privacy_notice_sha256=str(row["privacy_notice_sha256"]),
        service_terms_url=str(row["service_terms_url"]),
        service_terms_retrieved_at=str(row["service_terms_retrieved_at"]),
        service_terms_sha256=str(row["service_terms_sha256"]),
        faq_url=str(row["faq_url"]),
        faq_retrieved_at=str(row["faq_retrieved_at"]),
        faq_sha256=str(row["faq_sha256"]),
        no_training_basis=str(row["no_training_basis"]),
        prompt_response_logging_disabled=bool(row["prompt_response_logging_disabled"]),
        inference_log_backflow_disabled=bool(row["inference_log_backflow_disabled"]),
        optional_content_logging_disabled=bool(row["optional_content_logging_disabled"]),
        service_improvement_disabled=bool(row["service_improvement_disabled"]),
        storage_disclosed=bool(row["storage_disclosed"]),
        retention_setting=(
            str(row["retention_setting"]) if row["retention_setting"] is not None else None
        ),
        snapshot_revision=_as_int(row["snapshot_revision"]),
    )


def _manifest_from_row(row: Mapping[str, object]) -> ExportManifestV1:
    raw_fields = json.loads(str(row["fields_json"]))
    fields = tuple(
        # Imported lazily to keep this conversion function dependency-light.
        ExportFieldV1(str(item["field_class"]), str(item["value_sha256"]))
        for item in raw_fields
    )
    return ExportManifestV1(
        scope_id=str(row["scope_id"]),
        provider_operation=str(row["provider_operation"]),
        model_key=str(row["model_key"]),
        policy_hash=str(row["policy_hash"]),
        build_manifest_hash=str(row["build_manifest_hash"]),
        persona_spec_hash=str(row["persona_spec_hash"]),
        fields=fields,
        operation_revision=_as_int(row["operation_revision"]),
        contains_secret=bool(row["contains_secret"]),
        contains_identity=bool(row["contains_identity"]),
        contains_private_audio=bool(row["contains_private_audio"]),
        contains_teacher_note=bool(row["contains_teacher_note"]),
    )


def _confirmation_from_row(row: Mapping[str, object]) -> ExportConfirmationV1:
    return ExportConfirmationV1(
        manifest_hash=str(row["manifest_hash"]),
        policy_hash=str(row["policy_hash"]),
        confirmed_at=str(row["confirmed_at"]),
        confirmation_revision=_as_int(row["confirmation_revision"]),
    )


def _operation_from_row(row: Mapping[str, object]) -> ProviderOperationV1:
    return ProviderOperationV1(
        id=str(row["id"]),
        scope_id=str(row["scope_id"]),
        provider_operation=str(row["provider_operation"]),
        logical_item_id=str(row["logical_item_id"]),
        attempt_no=_as_int(row["attempt_no"]),
        request_hash=str(row["request_hash"]),
        max_tokens=_as_int(row["max_tokens"]),
        max_cost_cny=_as_float(row["max_cost_cny"]),
        policy_hash=str(row["policy_hash"]),
        export_manifest_hash=str(row["export_manifest_hash"]),
        build_manifest_hash=str(row["build_manifest_hash"]),
        model_key=str(row["model_key"]),
        state=cast(OperationState, str(row["state"])),
        reservation_id=None,
        request_count=_as_int(row["request_count"] or 0),
        charged_request_count=_as_int(row["charged_request_count"] or 0),
        staged_response_hash=(
            str(row["staged_response_hash"]) if row["staged_response_hash"] is not None else None
        ),
        safe_error_code=(
            str(row["safe_error_code"]) if row["safe_error_code"] is not None else None
        ),
    )


def _reservation_from_row(row: Mapping[str, object]) -> ProviderReservationV1:
    return ProviderReservationV1(
        id=str(row["id"]),
        operation_id=str(row["operation_id"]),
        scope_id=str(row["scope_id"]),
        provider_operation=str(row["provider_operation"]),
        logical_item_id=str(row["logical_item_id"]),
        attempt_no=_as_int(row["attempt_no"]),
        max_tokens=_as_int(row["max_tokens"]),
        max_cost_cny=_as_float(row["max_cost_cny"]),
        state=cast(ReservationState, str(row["state"])),
    )


# Explicit integration aliases.
ProviderOperationRepository = ProviderRepository
ProviderOperationRepositoryPort = ProviderRepository
ProviderOperationRepositoryV1 = ProviderRepository
ProviderControlRepository = ProviderRepository


__all__ = [
    "PolicyExportStale",
    "ProviderControlRepository",
    "ProviderOperationRepository",
    "ProviderOperationRepositoryPort",
    "ProviderOperationRepositoryV1",
    "ProviderRepository",
    "ProviderRepositoryError",
    "ScopeBudgetMissing",
]
