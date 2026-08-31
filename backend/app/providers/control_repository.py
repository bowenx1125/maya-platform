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
from decimal import Decimal
from typing import cast
from uuid import uuid4

from sqlalchemy import Engine, Table, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.core.db import Database
from app.core.models import (
    LlmAcceptedStage,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    ProviderPolicySnapshot,
    ProviderReservation,
    ProviderScopeBudget,
)
from app.providers.control import (
    EMBEDDING_SNAPSHOT_BUCKET,
    BudgetExceeded,
    DuplicateOperation,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    LLMAcceptedStageV1,
    OperationState,
    OperationStateError,
    ProviderOperationV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderReservationV1,
    ProviderScopeBudgetV1,
    ReservationState,
    budget_bucket_for_operation,
    can_transition,
    startup_recovery_state,
    validate_budget_bucket,
)

_POLICY_TABLE = cast(Table, ProviderPolicySnapshot.__table__)
_MANIFEST_TABLE = cast(Table, ProviderExportManifest.__table__)
_CONFIRMATION_TABLE = cast(Table, ProviderExportConfirmation.__table__)
_BUDGET_TABLE = cast(Table, ProviderScopeBudget.__table__)
_OPERATION_TABLE = cast(Table, ProviderOperation.__table__)
_RESERVATION_TABLE = cast(Table, ProviderReservation.__table__)
_LLM_STAGE_TABLE = cast(Table, LlmAcceptedStage.__table__)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProviderRepositoryError(RuntimeError):
    """A durable ProviderDataCall operation cannot proceed safely."""


class ScopeBudgetMissing(ProviderRepositoryError):
    """A scope has no explicitly frozen request/token/cost budget."""


class ScopeBudgetAmbiguous(ProviderRepositoryError):
    """A legacy scope maps to more than one closed budget bucket."""


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

    def _read_all(self, statement: Executable) -> list[Mapping[str, object]]:
        with self.engine.connect() as connection:
            return [
                cast(Mapping[str, object], row) for row in connection.execute(statement).mappings()
            ]

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
        debate_id: str | None = None,
        turn_id: str | None = None,
    ) -> str:
        manifest_debate_id, manifest_turn_id = _resolve_manifest_owners(
            manifest,
            debate_id=debate_id,
            turn_id=turn_id,
        )
        persisted_manifest = replace(
            manifest,
            debate_id=manifest_debate_id,
            turn_id=manifest_turn_id,
        )
        persisted_manifest.validate()
        _validate_manifest_operation_owners(
            persisted_manifest,
            debate_id=manifest_debate_id,
            turn_id=manifest_turn_id,
        )
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
            "scope_id": persisted_manifest.scope_id,
            "provider_operation": persisted_manifest.provider_operation,
            "model_key": persisted_manifest.model_key,
            "policy_hash": persisted_manifest.policy_hash,
            "build_manifest_hash": persisted_manifest.build_manifest_hash,
            "persona_spec_hash": persisted_manifest.persona_spec_hash,
            "fields_json": fields_json,
            "operation_revision": persisted_manifest.operation_revision,
            "contains_secret": persisted_manifest.contains_secret,
            "contains_identity": persisted_manifest.contains_identity,
            "contains_private_audio": persisted_manifest.contains_private_audio,
            "contains_teacher_note": persisted_manifest.contains_teacher_note,
            "manifest_hash": persisted_manifest.manifest_hash,
            "course_id": course_id,
            "group_id": group_id,
            "agent_version_id": agent_version_id,
            "debate_id": manifest_debate_id,
            "turn_id": manifest_turn_id,
            "max_attempts": persisted_manifest.max_attempts,
            "max_total_tokens": persisted_manifest.max_total_tokens,
            "max_cost_cny": persisted_manifest.max_cost_cny,
            "repair_policy_version": persisted_manifest.repair_policy_version,
            "repair_policy_hash": persisted_manifest.repair_policy_hash,
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
        debate_id: str | None = None,
        turn_id: str | None = None,
    ) -> str:
        """Insert once or verify the exact immutable manifest and owner tuple."""

        resolved_debate_id, resolved_turn_id = _resolve_manifest_owners(
            manifest,
            debate_id=debate_id,
            turn_id=turn_id,
        )
        effective_manifest = replace(
            manifest,
            debate_id=resolved_debate_id,
            turn_id=resolved_turn_id,
        )

        try:
            return self.save_export_manifest(
                effective_manifest,
                policy_snapshot_id=policy_snapshot_id,
                manifest_id=manifest_id,
                course_id=course_id,
                group_id=group_id,
                agent_version_id=agent_version_id,
                debate_id=resolved_debate_id,
                turn_id=resolved_turn_id,
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
                persisted != effective_manifest
                or str(row["policy_snapshot_id"]) != policy_snapshot_id
                or _optional_string(row["course_id"]) != course_id
                or _optional_string(row["group_id"]) != group_id
                or _optional_string(row["agent_version_id"]) != agent_version_id
                or _optional_string(row["debate_id"]) != resolved_debate_id
                or _optional_string(row["turn_id"]) != resolved_turn_id
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
                manifest_table.c.debate_id,
                manifest_table.c.turn_id,
                manifest_table.c.max_attempts,
                manifest_table.c.max_total_tokens,
                manifest_table.c.max_cost_cny,
                manifest_table.c.repair_policy_version,
                manifest_table.c.repair_policy_hash,
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
        if request.provider_operation == "llm_debate_turn":
            if (
                row["debate_id"] != request.scope_id
                or row["turn_id"] != request.logical_item_id
                or _as_int(row["max_attempts"] or 0) != 2
                or row["repair_policy_version"] != "repair_feedback_v1"
                or row["repair_policy_hash"]
                != "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
            ):
                raise PolicyExportStale("LLM turn export owner or retry policy is stale")

    validate_hashes_current = assert_hashes_current

    # ------------------------------------------------------------------
    # Scope budgets and operation lifecycle
    # ------------------------------------------------------------------
    def save_scope_budget(
        self,
        scope_id: str,
        budget_or_bucket: ProviderScopeBudgetV1 | str | None = None,
        budget: ProviderScopeBudgetV1 | None = None,
        *,
        budget_bucket: str | None = None,
        replace_empty: bool = False,
    ) -> None:
        if not scope_id:
            raise ProviderRepositoryError("scope id is required")
        if isinstance(budget_or_bucket, str):
            if budget is None:
                raise ProviderRepositoryError("scope budget value is required")
            if budget_bucket is not None and budget_bucket != budget_or_bucket:
                raise ProviderRepositoryError("scope budget bucket is specified twice")
            selected_bucket = budget_or_bucket
            selected_budget = budget
        elif isinstance(budget_or_bucket, ProviderScopeBudgetV1):
            if budget is not None:
                raise ProviderRepositoryError("scope budget value is specified twice")
            selected_budget = budget_or_bucket
            selected_bucket = budget_bucket or selected_budget.budget_bucket
        elif budget is not None:
            selected_budget = budget
            selected_bucket = budget_bucket or selected_budget.budget_bucket
        else:
            raise ProviderRepositoryError("scope budget value is required")
        validate_budget_bucket(selected_bucket)
        if (
            selected_budget.budget_bucket != selected_bucket
            and selected_budget.budget_bucket != EMBEDDING_SNAPSHOT_BUCKET
        ):
            raise ProviderRepositoryError("scope budget bucket does not match its value")
        budget_row = {
            "scope_id": scope_id,
            "budget_bucket": selected_bucket,
            "max_requests": selected_budget.max_requests,
            "max_total_tokens": selected_budget.max_total_tokens,
            "max_cost_cny": selected_budget.max_cost_cny,
            "allocated_requests": 0,
            "allocated_total_tokens": 0,
            "allocated_cost_cny": 0,
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        table = _BUDGET_TABLE
        with self._write_connection() as connection:
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.scope_id == scope_id,
                        table.c.budget_bucket == selected_bucket,
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(table.insert().values(**budget_row))
                return
            if not replace_empty:
                if (
                    _as_int(existing["max_requests"]) != selected_budget.max_requests
                    or _as_int(existing["max_total_tokens"]) != selected_budget.max_total_tokens
                    or _as_float(existing["max_cost_cny"]) != float(selected_budget.max_cost_cny)
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
                .where(
                    table.c.scope_id == scope_id,
                    table.c.budget_bucket == selected_bucket,
                )
                .values(
                    max_requests=selected_budget.max_requests,
                    max_total_tokens=selected_budget.max_total_tokens,
                    max_cost_cny=selected_budget.max_cost_cny,
                    updated_at=self._now(),
                )
            )

    ensure_scope_budget = save_scope_budget

    def get_scope_budget(
        self,
        scope_id: str,
        budget_bucket: str | None = None,
    ) -> ProviderScopeBudgetV1 | None:
        table = _BUDGET_TABLE
        if budget_bucket is not None:
            validate_budget_bucket(budget_bucket)
        rows = self._read_all(
            select(table)
            .where(
                table.c.scope_id == scope_id,
                *((table.c.budget_bucket == budget_bucket,) if budget_bucket else ()),
            )
            .order_by(table.c.budget_bucket)
        )
        if not rows:
            return None
        if budget_bucket is None and len(rows) > 1:
            raise ScopeBudgetAmbiguous("scope has more than one budget bucket")
        row = rows[0]
        return ProviderScopeBudgetV1(
            max_requests=_as_int(row["max_requests"]),
            max_total_tokens=_as_int(row["max_total_tokens"]),
            max_cost_cny=_as_float(row["max_cost_cny"]),
            budget_bucket=str(row["budget_bucket"]),
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
                    select(budget_table).where(
                        budget_table.c.scope_id == operation_row["scope_id"],
                        budget_table.c.budget_bucket
                        == budget_bucket_for_operation(str(operation_row["provider_operation"])),
                    )
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
                    .where(
                        budget_table.c.scope_id == row["scope_id"],
                        budget_table.c.budget_bucket
                        == budget_bucket_for_operation(str(row["provider_operation"])),
                    )
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

    def stage_llm_accepted(self, stage: LLMAcceptedStageV1) -> LLMAcceptedStageV1:
        """Persist one accepted LLM result and mark its operation accepted.

        Insertion and the ``sending -> accepted`` CAS share one transaction so
        a restart can never observe an accepted operation without its stage.
        Local output validation happens after this method returns.
        """

        stage.__post_init__()
        operation_table = _OPERATION_TABLE
        stage_table = _LLM_STAGE_TABLE
        reservation_table = _RESERVATION_TABLE
        with self._write_connection() as connection:
            operation_row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == stage.operation_id)
                )
                .mappings()
                .first()
            )
            if operation_row is None:
                raise ProviderRepositoryError("LLM accepted stage operation does not exist")
            if (
                operation_row["provider_operation"] != "llm_debate_turn"
                or operation_row["logical_item_id"] != stage.turn_id
                or _as_int(operation_row["attempt_no"]) != stage.attempt_no
                or operation_row["request_hash"] != stage.request_hash
                or operation_row["policy_hash"] != stage.policy_hash
                or operation_row["export_manifest_hash"] != stage.export_manifest_hash
                or operation_row["build_manifest_hash"] != stage.build_manifest_hash
                or operation_row["model_key"] != stage.model_key
            ):
                raise ProviderRepositoryError("LLM accepted stage does not match operation")
            if stage.completion_tokens > _as_int(operation_row["max_tokens"]):
                raise ProviderRepositoryError("LLM accepted stage exceeds reserved output tokens")
            if stage.actual_cost_cny is not None and Decimal(str(stage.actual_cost_cny)) > Decimal(
                str(operation_row["max_cost_cny"])
            ):
                raise ProviderRepositoryError("LLM accepted stage exceeds reserved cost")
            existing_row = (
                connection.execute(
                    select(stage_table).where(stage_table.c.operation_id == stage.operation_id)
                )
                .mappings()
                .first()
            )
            if existing_row is not None:
                existing = _llm_stage_from_row(cast(Mapping[str, object], existing_row))
                if not _stages_equal(existing, stage):
                    raise ProviderRepositoryError("LLM accepted stage is immutable")
                if operation_row["state"] not in {"accepted", "succeeded"}:
                    raise ProviderRepositoryError("LLM accepted stage operation state is invalid")
                return existing
            if operation_row["state"] not in {"sending", "accepted"}:
                raise ProviderRepositoryError("LLM accepted stage requires an accepted response")
            if (
                operation_row["state"] == "accepted"
                and operation_row["staged_response_hash"] != stage.output_hash
            ):
                raise ProviderRepositoryError("LLM accepted stage response hash is stale")
            now = self._now()
            values = stage.as_record()
            values["created_at"] = now
            connection.execute(stage_table.insert().values(**values))
            if operation_row["state"] == "sending":
                changed = connection.execute(
                    update(operation_table)
                    .where(
                        operation_table.c.id == stage.operation_id,
                        operation_table.c.state == "sending",
                    )
                    .values(
                        state="accepted",
                        staged_response_hash=stage.output_hash,
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:
                    raise OperationStateError("LLM accepted operation transition failed")
                connection.execute(
                    update(reservation_table)
                    .where(
                        reservation_table.c.operation_id == stage.operation_id,
                        reservation_table.c.state == "sending",
                    )
                    .values(state="accepted", updated_at=now)
                )
        return stage

    save_llm_accepted_stage = stage_llm_accepted
    save_llm_stage = stage_llm_accepted
    persist_llm_stage = stage_llm_accepted
    persist_llm_accepted_stage = stage_llm_accepted
    record_llm_accepted_stage = stage_llm_accepted
    record_llm_usage = stage_llm_accepted

    def get_llm_accepted_stage(self, operation_id: str) -> LLMAcceptedStageV1 | None:
        row = self._read_one(
            select(_LLM_STAGE_TABLE).where(_LLM_STAGE_TABLE.c.operation_id == operation_id)
        )
        return _llm_stage_from_row(row) if row is not None else None

    get_accepted_llm_stage = get_llm_accepted_stage
    get_llm_stage = get_llm_accepted_stage

    def mark_succeeded(self, operation_id: str) -> ProviderOperationV1:
        current = self.operation(operation_id)
        if current.provider_operation == "llm_debate_turn":
            stage = self.get_llm_accepted_stage(operation_id)
            if stage is None:
                raise ProviderRepositoryError("LLM operation has no accepted stage")
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
        if current.provider_operation == "llm_debate_turn":
            complete = (
                self._read_one(
                    select(_LLM_STAGE_TABLE.c.operation_id).where(
                        _LLM_STAGE_TABLE.c.operation_id == operation_id
                    )
                )
                is not None
            )
        else:
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

    def recover_llm_startup(self) -> tuple[ProviderOperationV1, ...]:
        return tuple(
            operation
            for operation in self.recover_startup()
            if operation.provider_operation == "llm_debate_turn"
        )

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


def _resolve_manifest_owners(
    manifest: ExportManifestV1,
    *,
    debate_id: str | None,
    turn_id: str | None,
) -> tuple[str | None, str | None]:
    """Merge typed manifest owner fields with repository call-site bindings."""

    resolved_debate_id = debate_id if debate_id is not None else manifest.debate_id
    resolved_turn_id = turn_id if turn_id is not None else manifest.turn_id
    if (resolved_debate_id is None) != (resolved_turn_id is None):
        raise ProviderRepositoryError(
            "Debate and Turn manifest owners must be both present or absent"
        )
    if manifest.debate_id is not None and manifest.debate_id != resolved_debate_id:
        raise ProviderRepositoryError("provider export Debate owner changed")
    if manifest.turn_id is not None and manifest.turn_id != resolved_turn_id:
        raise ProviderRepositoryError("provider export Turn owner changed")
    return resolved_debate_id, resolved_turn_id


def _validate_manifest_operation_owners(
    manifest: ExportManifestV1,
    *,
    debate_id: str | None,
    turn_id: str | None,
) -> None:
    if manifest.provider_operation == "llm_debate_turn" and (debate_id is None or turn_id is None):
        raise ProviderRepositoryError("LLM turn export requires Debate and Turn owners")
    if manifest.provider_operation != "llm_debate_turn" and (
        manifest.repair_policy_hash is not None or manifest.repair_policy_version is not None
    ):
        raise ProviderRepositoryError("repair policy is only valid for LLM turn exports")


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
        debate_id=_optional_string(row.get("debate_id")),
        turn_id=_optional_string(row.get("turn_id")),
        max_attempts=_as_int(row.get("max_attempts", 1) or 1),
        max_total_tokens=_as_int(row.get("max_total_tokens", 0) or 0),
        max_cost_cny=_as_float(row.get("max_cost_cny", 0) or 0),
        repair_policy_version=_optional_string(row.get("repair_policy_version")),
        repair_policy_hash=_optional_string(row.get("repair_policy_hash")),
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


def _llm_stage_from_row(row: Mapping[str, object]) -> LLMAcceptedStageV1:
    return LLMAcceptedStageV1(
        operation_id=str(row["operation_id"]),
        turn_id=str(row["turn_id"]),
        attempt_no=_as_int(row["attempt_no"]),
        request_hash=str(row["request_hash"]),
        prompt_hash=str(row["prompt_hash"]),
        prompt_contract_version=str(row["prompt_contract_version"]),
        schema_hash=str(row["schema_hash"]),
        tokenizer_id=str(row["tokenizer_id"]),
        tokenizer_hash=str(row["tokenizer_hash"]),
        rule_set_hash=str(row["rule_set_hash"]),
        persona_spec_hash=str(row["persona_spec_hash"]),
        transcript_hash=str(row["transcript_hash"]),
        receipt_hash=str(row["receipt_hash"]),
        policy_hash=str(row["policy_hash"]),
        export_manifest_hash=str(row["export_manifest_hash"]),
        build_manifest_hash=str(row["build_manifest_hash"]),
        repair_policy_hash=_optional_string(row["repair_policy_hash"]),
        generation_fence=str(row["generation_fence"] or ""),
        model_key=str(row["model_key"]),
        output_json=str(row["output_json"]),
        output_hash=str(row["output_hash"]),
        prompt_tokens=_as_int(row["prompt_tokens"]),
        cached_input_tokens=_as_int(row["cached_input_tokens"]),
        completion_tokens=_as_int(row["completion_tokens"]),
        total_tokens=_as_int(row["total_tokens"]),
        price_card_version=str(row["price_card_version"]),
        input_price_cny_per_million=Decimal(str(row["input_price_cny_per_million"])),
        cached_input_price_cny_per_million=Decimal(str(row["cached_input_price_cny_per_million"])),
        output_price_cny_per_million=Decimal(str(row["output_price_cny_per_million"])),
        estimated_cost_cny=Decimal(str(row["estimated_cost_cny"])),
        actual_cost_cny=(
            Decimal(str(row["actual_cost_cny"])) if row["actual_cost_cny"] is not None else None
        ),
        retrieval_reused=bool(row["retrieval_reused"]),
        safe_error_code=_optional_string(row["safe_error_code"]),
        repair_policy_version=_optional_string(row["repair_policy_version"]),
    )


def _stages_equal(left: LLMAcceptedStageV1, right: LLMAcceptedStageV1) -> bool:
    """Compare normalized records so SQLite Decimal values are deterministic."""

    return left.as_record() == right.as_record()


# Explicit integration aliases.
ProviderOperationRepository = ProviderRepository
ProviderOperationRepositoryPort = ProviderRepository
ProviderOperationRepositoryV1 = ProviderRepository
ProviderControlRepository = ProviderRepository


__all__ = [
    "PolicyExportStale",
    "ScopeBudgetAmbiguous",
    "ProviderControlRepository",
    "ProviderOperationRepository",
    "ProviderOperationRepositoryPort",
    "ProviderOperationRepositoryV1",
    "ProviderRepository",
    "ProviderRepositoryError",
    "ScopeBudgetMissing",
]
