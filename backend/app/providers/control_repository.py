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
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Engine, Table, func, select, text, update
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    DemoAcceptanceRun,
    Job,
    LlmAcceptedStage,
    LlmRecoveryInput,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    ProviderPolicySnapshot,
    ProviderReservation,
    ProviderScopeBudget,
)
from app.modules.knowledge_sets.models import (
    KnowledgeGenerationAcceptedStage,
    KnowledgeGenerationRun,
)
from app.providers.control import (
    EMBEDDING_SNAPSHOT_BUCKET,
    DuplicateOperation,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    KnowledgeGenerationAcceptedStageV1,
    LLMAcceptedBundleV1,
    LLMAcceptedStageV1,
    LLMRecoveryInputV1,
    OperationState,
    OperationStateError,
    ProviderControlError,
    ProviderOperationV1,
    ProviderPolicySnapshotV1,
    ProviderReservationRequestV1,
    ProviderReservationV1,
    ProviderScopeBudgetV1,
    ReservationState,
    budget_bucket_for_operation,
    can_transition,
    canonical_json_bytes,
    sha256_hex,
    startup_recovery_state,
    validate_budget_bucket,
    validate_demo_acceptance_call_no,
)
from app.providers.llm_segments import SegmentAcceptedBundleV2, SegmentRecoveryInputV2

_POLICY_TABLE = cast(Table, ProviderPolicySnapshot.__table__)
_MANIFEST_TABLE = cast(Table, ProviderExportManifest.__table__)
_CONFIRMATION_TABLE = cast(Table, ProviderExportConfirmation.__table__)
_BUDGET_TABLE = cast(Table, ProviderScopeBudget.__table__)
_OPERATION_TABLE = cast(Table, ProviderOperation.__table__)
_JOB_TABLE = cast(Table, Job.__table__)
_ACCEPTANCE_RUN_TABLE = cast(Table, DemoAcceptanceRun.__table__)
_AGENT_TABLE = cast(Table, Agent.__table__)
_AGENT_VERSION_TABLE = cast(Table, AgentVersion.__table__)
_RESERVATION_TABLE = cast(Table, ProviderReservation.__table__)
_LLM_STAGE_TABLE = cast(Table, LlmAcceptedStage.__table__)
_LLM_RECOVERY_INPUT_TABLE = cast(Table, LlmRecoveryInput.__table__)
_KNOWLEDGE_GENERATION_RUN_TABLE = cast(Table, KnowledgeGenerationRun.__table__)
_KNOWLEDGE_GENERATION_STAGE_TABLE = cast(Table, KnowledgeGenerationAcceptedStage.__table__)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProviderRepositoryError(RuntimeError):
    """A durable ProviderDataCall operation cannot proceed safely."""


class ScopeBudgetMissing(ProviderRepositoryError):
    """A scope has no explicitly frozen request/token/cost budget."""


class ScopeBudgetAmbiguous(ProviderRepositoryError):
    """A legacy scope maps to more than one closed budget bucket."""


class PolicyExportStale(ProviderRepositoryError):
    """An operation does not match a confirmed policy/export hash pair."""


class ProviderDispatchRejected(ProviderRepositoryError):
    """A Chat-specific request fence rejected an operation before dispatch."""

    code = "chat_request_stale"


ProviderSendingGuard = Callable[[Connection, RowMapping], bool]


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
        if manifest.provider_operation == "llm_debate":
            raise ProviderRepositoryError(
                "legacy llm_debate manifests cannot be persisted",
            )
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

    def get_export_manifest_id(self, manifest_hash: str) -> str | None:
        """Resolve a stored manifest's row id, which save_export_confirmation needs."""

        table = _MANIFEST_TABLE
        row = self._read_one(select(table).where(table.c.manifest_hash == manifest_hash))
        return str(row["id"]) if row is not None else None

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

        if request.provider_operation == "llm_debate":
            raise ProviderRepositoryError(
                "legacy llm_debate operations cannot enter new preflight",
            )

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
            max_attempts = _as_int(row["max_attempts"] or 0)
            retry_policy_matches = (
                row["repair_policy_version"] == "repair_feedback_v1"
                and row["repair_policy_hash"]
                == "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"
            )
            one_shot_policy_matches = (
                row["repair_policy_version"] is None and row["repair_policy_hash"] is None
            )
            if (
                row["debate_id"] != request.scope_id
                or row["turn_id"] != request.logical_item_id
                or max_attempts not in {1, 2}
                or (max_attempts == 2 and not retry_policy_matches)
                or (max_attempts == 1 and not one_shot_policy_matches)
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
                # Existing estimates are historical accounting metadata, not quotas.
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

    def raise_scope_budget(self, scope_id: str, budget: ProviderScopeBudgetV1) -> None:
        """Create a scope budget, or widen an existing one to these caps.

        A budget row is written once and never grows, which is right for a cap
        the product never exceeds. It is wrong for a row an earlier release
        sized too small: the Maya report bucket allowed a single request per
        Debate, so the second attempt -- and every use of Regenerate after it
        -- failed with BudgetExceeded and no report could ever be produced for
        that Debate again.

        Caps only ever move up, and only to the value the current code derives.
        Nothing here can lower a cap or spend past one.
        """

        table = _BUDGET_TABLE
        validate_budget_bucket(budget.budget_bucket)
        with self._write_connection() as connection:
            existing = (
                connection.execute(
                    select(table).where(
                        table.c.scope_id == scope_id,
                        table.c.budget_bucket == budget.budget_bucket,
                    )
                )
                .mappings()
                .first()
            )
            if existing is None:
                connection.execute(
                    table.insert().values(
                        scope_id=scope_id,
                        budget_bucket=budget.budget_bucket,
                        max_requests=budget.max_requests,
                        max_total_tokens=budget.max_total_tokens,
                        max_cost_cny=budget.max_cost_cny,
                        allocated_requests=0,
                        allocated_total_tokens=0,
                        allocated_cost_cny=0,
                        created_at=self._now(),
                        updated_at=self._now(),
                    )
                )
                return
            widened = {
                "max_requests": max(_as_int(existing["max_requests"]), budget.max_requests),
                "max_total_tokens": max(
                    _as_int(existing["max_total_tokens"]), budget.max_total_tokens
                ),
                "max_cost_cny": max(
                    _as_float(existing["max_cost_cny"]), float(budget.max_cost_cny)
                ),
            }
            connection.execute(
                update(table)
                .where(
                    table.c.scope_id == scope_id,
                    table.c.budget_bucket == budget.budget_bucket,
                )
                .values(updated_at=self._now(), **widened)
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

    def _inherit_acceptance_binding(
        self,
        connection: Any,
        request: ProviderReservationRequestV1,
    ) -> tuple[str, int] | None:
        """Bind a structure-repair attempt to its first attempt's run ordinal.

        A repair is not a new teacher decision: it re-sends the same authorized
        manifest once with frozen feedback. Requiring a separate confirmation
        would be impossible mid-turn, and leaving the attempt unbound would hide
        a charged request from the acceptance ledger. So attempt two inherits
        the run of the attempt that the teacher already confirmed and takes the
        next free ordinal, which keeps the derived budget honest.
        """

        if request.attempt_no <= 1:
            return None
        row = connection.execute(
            text(
                "SELECT acceptance_run_id FROM provider_operations "
                "WHERE export_manifest_hash=:manifest_hash AND scope_id=:scope_id "
                "AND logical_item_id=:logical_item_id AND attempt_no=:previous_attempt "
                "AND acceptance_run_id IS NOT NULL"
            ),
            {
                "manifest_hash": request.export_manifest_hash,
                "scope_id": request.scope_id,
                "logical_item_id": request.logical_item_id,
                "previous_attempt": request.attempt_no - 1,
            },
        ).first()
        if row is None or row[0] is None:
            return None
        run_id = str(row[0])
        highest = connection.execute(
            text(
                "SELECT COALESCE(MAX(call_no), 0) FROM provider_operations "
                "WHERE acceptance_run_id=:run_id"
            ),
            {"run_id": run_id},
        ).scalar_one()
        return run_id, int(highest or 0) + 1

    def create_prepared(self, request: ProviderReservationRequestV1) -> ProviderOperationV1:
        if request.provider_operation == "llm_debate":
            raise ProviderRepositoryError(
                "legacy llm_debate operations cannot be created",
            )
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
            "acceptance_run_id": None,
            "call_no": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self._write_connection() as connection:
                inherited = self._inherit_acceptance_binding(connection, request)
                if inherited is not None:
                    values["acceptance_run_id"], values["call_no"] = inherited
                connection.execute(_OPERATION_TABLE.insert().values(**values))
        except IntegrityError as exc:
            raise DuplicateOperation("provider attempt already exists") from exc
        return self.operation(operation_id)

    create = create_prepared

    def create_knowledge_generation_prepared(
        self,
        request: ProviderReservationRequestV1,
        *,
        run_id: str,
        claim_token: str,
    ) -> ProviderOperationV1:
        """Create and bind one exact Knowledge operation in the same transaction."""

        if (
            request.provider_operation != "llm_knowledge_generate"
            or request.scope_id != run_id
            or request.logical_item_id != run_id
            or request.attempt_no != 1
            or not claim_token
        ):
            raise ProviderRepositoryError("Knowledge Provider operation identity is invalid")

        run_table = _KNOWLEDGE_GENERATION_RUN_TABLE
        agent_table = _AGENT_TABLE
        operation_table = _OPERATION_TABLE
        with self._write_connection() as connection:
            run_row = (
                connection.execute(select(run_table).where(run_table.c.id == run_id))
                .mappings()
                .first()
            )
            if (
                run_row is None
                or run_row["state"] != "running"
                or run_row["claim_token"] != claim_token
                or run_row["provider_manifest_hash"] != request.export_manifest_hash
                or run_row["agent_version_id"] is None
            ):
                raise ProviderRepositoryError("Knowledge run claim or manifest is stale")
            agent_row = (
                connection.execute(
                    select(agent_table.c.group_id).where(agent_table.c.id == run_row["agent_id"])
                )
                .mappings()
                .first()
            )
            manifest = (
                connection.execute(
                    select(_MANIFEST_TABLE).where(
                        _MANIFEST_TABLE.c.manifest_hash == request.export_manifest_hash
                    )
                )
                .mappings()
                .first()
            )
            if (
                agent_row is None
                or manifest is None
                or manifest["provider_operation"] != request.provider_operation
                or manifest["scope_id"] != run_id
                or manifest["course_id"] != run_row["course_id"]
                or manifest["group_id"]
                != (str(agent_row["group_id"]) if agent_row["group_id"] is not None else None)
                or manifest["agent_version_id"] != run_row["agent_version_id"]
                or manifest["model_key"] != request.model_key
                or manifest["policy_hash"] != request.policy_hash
                or manifest["build_manifest_hash"] != request.build_manifest_hash
            ):
                raise ProviderRepositoryError("Knowledge Provider manifest ownership is stale")

            confirmation = (
                connection.execute(
                    select(
                        _CONFIRMATION_TABLE.c.manifest_hash,
                        _CONFIRMATION_TABLE.c.policy_hash,
                        _CONFIRMATION_TABLE.c.confirmation_revision,
                        _POLICY_TABLE.c.policy_hash.label("current_policy_hash"),
                    )
                    .join(
                        _CONFIRMATION_TABLE,
                        _CONFIRMATION_TABLE.c.manifest_id == _MANIFEST_TABLE.c.id,
                    )
                    .join(
                        _POLICY_TABLE,
                        _POLICY_TABLE.c.id == _MANIFEST_TABLE.c.policy_snapshot_id,
                    )
                    .where(
                        _MANIFEST_TABLE.c.id == manifest["id"],
                        _CONFIRMATION_TABLE.c.manifest_hash == request.export_manifest_hash,
                        _CONFIRMATION_TABLE.c.policy_hash == request.policy_hash,
                    )
                )
                .mappings()
                .first()
            )
            if (
                confirmation is None
                or confirmation["manifest_hash"] != request.export_manifest_hash
                or confirmation["policy_hash"] != request.policy_hash
                or confirmation["current_policy_hash"] != request.policy_hash
                or confirmation["confirmation_revision"] != manifest["operation_revision"]
            ):
                raise PolicyExportStale("Knowledge Provider manifest is not exactly confirmed")

            linked_operation_id = run_row["provider_operation_id"]
            if linked_operation_id is not None:
                existing = (
                    connection.execute(
                        select(operation_table).where(operation_table.c.id == linked_operation_id)
                    )
                    .mappings()
                    .first()
                )
                if (
                    existing is None
                    or existing["provider_operation"] != request.provider_operation
                    or existing["scope_id"] != request.scope_id
                    or existing["logical_item_id"] != request.logical_item_id
                    or existing["attempt_no"] != request.attempt_no
                    or existing["request_hash"] != request.request_hash
                    or existing["policy_hash"] != request.policy_hash
                    or existing["export_manifest_hash"] != request.export_manifest_hash
                    or existing["build_manifest_hash"] != request.build_manifest_hash
                    or existing["model_key"] != request.model_key
                    or existing["state"] != "prepared"
                ):
                    raise ProviderRepositoryError("Knowledge Provider operation cannot be reused")
                operation_id = str(linked_operation_id)
            else:
                operation_id = request.operation_id or str(uuid4())
                now = self._now()
                connection.execute(
                    operation_table.insert().values(
                        id=operation_id,
                        scope_id=request.scope_id,
                        provider_operation=request.provider_operation,
                        logical_item_id=request.logical_item_id,
                        attempt_no=request.attempt_no,
                        request_hash=request.request_hash,
                        max_tokens=request.max_tokens,
                        max_cost_cny=request.max_cost_cny,
                        policy_hash=request.policy_hash,
                        export_manifest_hash=request.export_manifest_hash,
                        build_manifest_hash=request.build_manifest_hash,
                        model_key=request.model_key,
                        state="prepared",
                        request_count=0,
                        charged_request_count=0,
                        staged_response_hash=None,
                        safe_error_code=None,
                        acceptance_run_id=None,
                        call_no=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
                changed = connection.execute(
                    update(run_table)
                    .where(
                        run_table.c.id == run_id,
                        run_table.c.state == "running",
                        run_table.c.claim_token == claim_token,
                        run_table.c.provider_operation_id.is_(None),
                        run_table.c.provider_manifest_hash == request.export_manifest_hash,
                    )
                    .values(
                        provider_operation_id=operation_id,
                        request_hash=request.request_hash,
                        updated_at=now,
                    )
                )
                if changed.rowcount != 1:
                    raise ProviderRepositoryError("Knowledge Provider run binding CAS failed")
        return self.operation(operation_id)

    def create_snapshot_prepared(
        self,
        request: ProviderReservationRequestV1,
        *,
        acceptance_run_id: str,
        call_no: int,
        target_agent_id: str,
        target_version_id: str,
    ) -> ProviderOperationV1:
        """Create the bound Snapshot Call1 operation in one guarded transaction.

        Snapshot publication is the only caller of this seam.  The run,
        publish target, exact export manifest and the zero-use Call1 slot are
        checked while the same writer transaction is held as the operation
        insert.  In particular, a failed binding cannot leave a prepared row
        for a later unbound attach to reuse.
        """

        validate_demo_acceptance_call_no(call_no)
        if call_no != 1:
            raise ProviderRepositoryError("Snapshot acceptance binding requires Call1")
        if not acceptance_run_id or not target_agent_id or not target_version_id:
            raise ProviderRepositoryError("Snapshot acceptance binding is incomplete")
        if request.provider_operation != "embedding":
            raise ProviderRepositoryError("Snapshot acceptance binding has an invalid operation")
        if request.attempt_no != 1 or request.logical_item_id != "batch-0":
            raise ProviderRepositoryError("Snapshot Call1 requires one batch attempt")
        if not request.scope_id or not request.build_manifest_hash:
            raise ProviderRepositoryError("Snapshot acceptance binding has an invalid scope")
        if self.require_export_confirmation:
            # The full owner check below is intentionally performed on the
            # same connection so a confirmation cannot drift between the
            # preflight read and this operation insert.
            pass

        run_table = _ACCEPTANCE_RUN_TABLE
        operation_table = _OPERATION_TABLE
        manifest_table = _MANIFEST_TABLE
        with self._write_connection() as connection:
            run_row = (
                connection.execute(select(run_table).where(run_table.c.id == acceptance_run_id))
                .mappings()
                .first()
            )
            if run_row is None:
                raise ProviderRepositoryError("Demo acceptance run does not exist")
            if run_row["plan_version"] != "real_core_demo_v2" or run_row["state"] not in {
                "prepared",
                "executing",
            }:
                raise ProviderRepositoryError("Demo acceptance run is not open")
            if (
                run_row["target_agent_id"] != target_agent_id
                or run_row["target_version_id"] != target_version_id
            ):
                raise ProviderRepositoryError("Demo acceptance run target does not match publish")

            target = (
                connection.execute(
                    select(
                        _AGENT_VERSION_TABLE.c.id,
                        _AGENT_VERSION_TABLE.c.agent_id,
                        _AGENT_VERSION_TABLE.c.state,
                        _AGENT_VERSION_TABLE.c.knowledge_snapshot_id,
                        _AGENT_TABLE.c.id.label("target_agent_id"),
                        _AGENT_TABLE.c.status,
                    )
                    .join(
                        _AGENT_TABLE,
                        _AGENT_TABLE.c.id == _AGENT_VERSION_TABLE.c.agent_id,
                    )
                    .where(
                        _AGENT_VERSION_TABLE.c.id == target_version_id,
                        _AGENT_TABLE.c.id == target_agent_id,
                    )
                )
                .mappings()
                .first()
            )
            if (
                target is None
                or target["state"] != "draft"
                or target["status"] != "active"
                or target["knowledge_snapshot_id"] is not None
            ):
                raise ProviderRepositoryError("Snapshot publish target is no longer publishable")

            manifest = (
                connection.execute(
                    select(manifest_table).where(
                        manifest_table.c.manifest_hash == request.export_manifest_hash
                    )
                )
                .mappings()
                .first()
            )
            if (
                manifest is None
                or manifest["provider_operation"] != "embedding"
                or manifest["scope_id"] != request.scope_id
                or manifest["agent_version_id"] != target_version_id
                or manifest["policy_hash"] != request.policy_hash
            ):
                raise ProviderRepositoryError("Snapshot export manifest owner does not match")

            if self.require_export_confirmation:
                confirmation = (
                    connection.execute(
                        select(
                            _CONFIRMATION_TABLE.c.manifest_hash,
                            _CONFIRMATION_TABLE.c.policy_hash,
                            _CONFIRMATION_TABLE.c.confirmation_revision,
                            _POLICY_TABLE.c.policy_hash.label("current_policy_hash"),
                        )
                        .join(
                            _CONFIRMATION_TABLE,
                            _CONFIRMATION_TABLE.c.manifest_id == manifest_table.c.id,
                        )
                        .join(
                            _POLICY_TABLE,
                            _POLICY_TABLE.c.id == manifest_table.c.policy_snapshot_id,
                        )
                        .where(
                            manifest_table.c.id == manifest["id"],
                            _CONFIRMATION_TABLE.c.manifest_hash == request.export_manifest_hash,
                            _CONFIRMATION_TABLE.c.policy_hash == request.policy_hash,
                        )
                    )
                    .mappings()
                    .first()
                )
                if (
                    confirmation is None
                    or confirmation["manifest_hash"] != request.export_manifest_hash
                    or confirmation["policy_hash"] != request.policy_hash
                    or confirmation["current_policy_hash"] != request.policy_hash
                    or confirmation["confirmation_revision"] != manifest["operation_revision"]
                ):
                    raise PolicyExportStale("provider policy/export confirmation is stale")
                if (
                    manifest["model_key"] != request.model_key
                    or manifest["build_manifest_hash"] != request.build_manifest_hash
                ):
                    raise PolicyExportStale("provider export build or model is stale")

            bound_count = connection.execute(
                select(func.count())
                .select_from(operation_table)
                .where(operation_table.c.acceptance_run_id == acceptance_run_id)
            ).scalar_one()
            if int(bound_count) != 0:
                raise ProviderRepositoryError("Demo acceptance run already has a call")
            ordinal = connection.execute(
                select(operation_table.c.id).where(
                    operation_table.c.acceptance_run_id == acceptance_run_id,
                    operation_table.c.call_no == 1,
                )
            ).first()
            if ordinal is not None:
                raise ProviderRepositoryError("Demo acceptance Call1 is already bound")
            existing = connection.execute(
                select(operation_table.c.id).where(
                    operation_table.c.scope_id == request.scope_id,
                    operation_table.c.provider_operation == request.provider_operation,
                    operation_table.c.logical_item_id == request.logical_item_id,
                    operation_table.c.attempt_no == request.attempt_no,
                )
            ).first()
            if existing is not None:
                raise ProviderRepositoryError("Snapshot operation already exists")

            operation_id = request.operation_id or str(uuid4())
            now = self._now()
            connection.execute(
                operation_table.insert().values(
                    id=operation_id,
                    scope_id=request.scope_id,
                    provider_operation=request.provider_operation,
                    logical_item_id=request.logical_item_id,
                    attempt_no=request.attempt_no,
                    request_hash=request.request_hash,
                    max_tokens=request.max_tokens,
                    max_cost_cny=request.max_cost_cny,
                    policy_hash=request.policy_hash,
                    export_manifest_hash=request.export_manifest_hash,
                    build_manifest_hash=request.build_manifest_hash,
                    model_key=request.model_key,
                    state="prepared",
                    request_count=0,
                    charged_request_count=0,
                    staged_response_hash=None,
                    safe_error_code=None,
                    acceptance_run_id=acceptance_run_id,
                    call_no=call_no,
                    created_at=now,
                    updated_at=now,
                )
            )
            if run_row["state"] == "prepared":
                changed = connection.execute(
                    update(run_table)
                    .where(
                        run_table.c.id == acceptance_run_id,
                        run_table.c.state == "prepared",
                    )
                    .values(state="executing", updated_at=now)
                )
                if changed.rowcount != 1:
                    raise ProviderRepositoryError("Demo acceptance run state CAS failed")
        return self.operation(operation_id)

    def stage_knowledge_generation_accepted(
        self,
        stage: KnowledgeGenerationAcceptedStageV1,
        *,
        content_authorized: Callable[[Connection, str, str], bool],
    ) -> KnowledgeGenerationAcceptedStageV1:
        """Atomically persist the sanitized stage and accept its operation.

        The supplied authorization callback runs inside this same database
        transaction. If current source or actor permission has changed since
        send, the accepted response is represented only by a safe receipt
        hash; its generated content is suppressed.
        """

        stage.__post_init__()
        if not callable(content_authorized):
            raise ProviderRepositoryError("Knowledge accepted stage requires an ACL fence")
        operation_table = _OPERATION_TABLE
        run_table = _KNOWLEDGE_GENERATION_RUN_TABLE
        stage_table = _KNOWLEDGE_GENERATION_STAGE_TABLE
        reservation_table = _RESERVATION_TABLE
        job_table = _JOB_TABLE
        with self._write_connection() as connection:
            operation_row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == stage.operation_id)
                )
                .mappings()
                .first()
            )
            run_row = (
                connection.execute(select(run_table).where(run_table.c.id == stage.run_id))
                .mappings()
                .first()
            )
            existing_row = (
                connection.execute(select(stage_table).where(stage_table.c.run_id == stage.run_id))
                .mappings()
                .first()
            )
            if operation_row is None or run_row is None:
                raise ProviderRepositoryError("Knowledge accepted stage owner does not exist")
            if (
                operation_row["provider_operation"] != "llm_knowledge_generate"
                or operation_row["scope_id"] != stage.run_id
                or operation_row["logical_item_id"] != stage.run_id
                or operation_row["attempt_no"] != 1
                or operation_row["request_hash"] != stage.request_hash
                or operation_row["export_manifest_hash"] != stage.manifest_hash
                or operation_row["policy_hash"] != stage.policy_hash
                or operation_row["model_key"] != stage.model_key
                or run_row["provider_operation_id"] != stage.operation_id
                or run_row["request_hash"] != stage.request_hash
                or run_row["provider_manifest_hash"] != stage.manifest_hash
            ):
                raise ProviderRepositoryError("Knowledge accepted stage does not match its run")

            if existing_row is not None:
                if (
                    existing_row["operation_id"] != stage.operation_id
                    or existing_row["request_hash"] != stage.request_hash
                    or existing_row["manifest_hash"] != stage.manifest_hash
                    or existing_row["policy_hash"] != stage.policy_hash
                    or existing_row["model_key"] != stage.model_key
                    or existing_row["schema_hash"] != stage.schema_hash
                    or existing_row["canonical_stage_json"] != stage.canonical_stage_json
                    or existing_row["canonical_stage_hash"] != stage.canonical_stage_hash
                    or existing_row["item_count"] != stage.item_count
                    or existing_row["usage_json"] != stage.usage_json
                    or existing_row["safe_error_code"] != stage.safe_error_code
                    or operation_row["state"] != "accepted"
                    or operation_row["staged_response_hash"] != stage.canonical_stage_hash
                ):
                    raise ProviderRepositoryError("Knowledge accepted stage is immutable")
                return stage

            if operation_row["state"] != "sending":
                raise ProviderRepositoryError("Knowledge stage requires a sending operation")
            reservation_row = (
                connection.execute(
                    select(reservation_table).where(
                        reservation_table.c.operation_id == stage.operation_id
                    )
                )
                .mappings()
                .first()
            )
            if reservation_row is None or reservation_row["state"] != "sending":
                raise ProviderRepositoryError("Knowledge stage reservation is not sending")

            claim_is_current = (
                run_row["state"] == "running" and run_row["claim_token"] == stage.claim_token
            )
            authorized = False
            if claim_is_current:
                try:
                    authorized = bool(
                        content_authorized(connection, stage.run_id, stage.claim_token)
                    )
                except Exception:
                    authorized = False

            accepted_stage = stage
            if not authorized:
                safe_code = (
                    "authorization_revoked_after_send"
                    if claim_is_current
                    else "knowledge_generation_claim_stale"
                )
                suppressed_json = canonical_json_bytes(
                    {"safe_error_code": safe_code, "suppressed": True}
                ).decode("utf-8")
                accepted_stage = replace(
                    stage,
                    canonical_stage_json=None,
                    canonical_stage_hash=sha256_hex(suppressed_json.encode("utf-8")),
                    item_count=0,
                    safe_error_code=safe_code,
                )

            now = self._now()
            connection.execute(
                stage_table.insert().values(
                    run_id=accepted_stage.run_id,
                    operation_id=accepted_stage.operation_id,
                    request_hash=accepted_stage.request_hash,
                    manifest_hash=accepted_stage.manifest_hash,
                    policy_hash=accepted_stage.policy_hash,
                    model_key=accepted_stage.model_key,
                    schema_hash=accepted_stage.schema_hash,
                    canonical_stage_json=accepted_stage.canonical_stage_json,
                    canonical_stage_hash=accepted_stage.canonical_stage_hash,
                    item_count=accepted_stage.item_count,
                    usage_json=accepted_stage.usage_json,
                    safe_error_code=accepted_stage.safe_error_code,
                    accepted_at=now,
                    created_at=now,
                )
            )
            accepted = connection.execute(
                update(operation_table)
                .where(
                    operation_table.c.id == stage.operation_id,
                    operation_table.c.state == "sending",
                    operation_table.c.request_hash == stage.request_hash,
                )
                .values(
                    state="accepted",
                    staged_response_hash=accepted_stage.canonical_stage_hash,
                    safe_error_code=accepted_stage.safe_error_code,
                    updated_at=now,
                )
            )
            reserved = connection.execute(
                update(reservation_table)
                .where(
                    reservation_table.c.operation_id == stage.operation_id,
                    reservation_table.c.state == "sending",
                )
                .values(state="accepted", updated_at=now)
            )
            if accepted.rowcount != 1 or reserved.rowcount != 1:
                raise ProviderRepositoryError("Knowledge accepted stage CAS failed")

            if claim_is_current:
                safe_error_code = (
                    accepted_stage.safe_error_code
                    if accepted_stage.safe_error_code is not None
                    else "accepted_stage_ready"
                )
                job_state = "failed" if accepted_stage.safe_error_code is not None else "pending"
                run_changed = connection.execute(
                    update(run_table)
                    .where(
                        run_table.c.id == stage.run_id,
                        run_table.c.state == "running",
                        run_table.c.claim_token == stage.claim_token,
                        run_table.c.provider_operation_id == stage.operation_id,
                    )
                    .values(
                        state="blocked",
                        safe_error_code=safe_error_code,
                        claim_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                job_changed = connection.execute(
                    update(job_table)
                    .where(
                        job_table.c.id == run_row["job_id"],
                        job_table.c.claim_token == stage.claim_token,
                    )
                    .values(
                        state=job_state,
                        safe_error_code=safe_error_code,
                        claim_token=None,
                        updated_at=now,
                    )
                )
                if run_changed.rowcount != 1 or job_changed.rowcount != 1:
                    raise ProviderRepositoryError("Knowledge run accepted-stage fence failed")
        return accepted_stage

    def knowledge_generation_stage(self, run_id: str) -> Mapping[str, object] | None:
        row = self._read_one(
            select(_KNOWLEDGE_GENERATION_STAGE_TABLE).where(
                _KNOWLEDGE_GENERATION_STAGE_TABLE.c.run_id == run_id
            )
        )
        return row

    # Keep naming discoverable for callers that describe this as a bound
    # prepared operation while retaining one implementation and one seam.
    create_bound_snapshot_prepared = create_snapshot_prepared

    def attach_acceptance_call(
        self,
        operation_id: str,
        *,
        acceptance_run_id: str,
        call_no: int,
    ) -> ProviderOperationV1:
        """Atomically bind a zero-use operation to one frozen Demo ordinal."""

        validate_demo_acceptance_call_no(call_no)
        if not isinstance(acceptance_run_id, str) or not acceptance_run_id.strip():
            raise ProviderRepositoryError("Demo acceptance run is required")
        operation_table = _OPERATION_TABLE
        run_table = _ACCEPTANCE_RUN_TABLE
        with self._write_connection() as connection:
            run_row = (
                connection.execute(select(run_table).where(run_table.c.id == acceptance_run_id))
                .mappings()
                .first()
            )
            if run_row is None:
                raise ProviderRepositoryError("Demo acceptance run does not exist")
            if run_row["state"] not in {"prepared", "executing"}:
                raise ProviderRepositoryError("Demo acceptance run is already terminal")

            operation_row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == operation_id)
                )
                .mappings()
                .first()
            )
            if operation_row is None:
                raise OperationStateError("provider operation does not exist")
            bound_run = operation_row.get("acceptance_run_id")
            bound_call = operation_row.get("call_no")
            if bound_run is not None or bound_call is not None:
                if str(bound_run) != acceptance_run_id:
                    raise ProviderRepositoryError("provider operation belongs to another Demo run")
                raise ProviderRepositoryError("provider operation already has a Demo call ordinal")
            if (
                operation_row["state"] != "prepared"
                or _as_int(operation_row["request_count"] or 0) != 0
                or _as_int(operation_row["charged_request_count"] or 0) != 0
                or operation_row["staged_response_hash"] is not None
            ):
                raise ProviderRepositoryError("provider operation is no longer pre-send")
            owner_manifest = (
                connection.execute(
                    select(_MANIFEST_TABLE).where(
                        _MANIFEST_TABLE.c.manifest_hash == operation_row["export_manifest_hash"]
                    )
                )
                .mappings()
                .first()
            )
            target_version_matches = operation_row["scope_id"] == run_row["target_version_id"]
            target_manifest_matches = (
                owner_manifest is not None
                and owner_manifest["agent_version_id"] == run_row["target_version_id"]
            )
            debate_matches = (
                run_row["debate_id"] is not None
                and operation_row["scope_id"] == run_row["debate_id"]
            )
            debate_manifest_matches = (
                owner_manifest is not None
                and run_row["debate_id"] is not None
                and owner_manifest["debate_id"] == run_row["debate_id"]
            )
            if not (
                target_version_matches
                or target_manifest_matches
                or debate_matches
                or debate_manifest_matches
            ):
                raise ProviderRepositoryError("provider operation does not belong to Demo run")
            duplicate = connection.execute(
                select(operation_table.c.id).where(
                    operation_table.c.acceptance_run_id == acceptance_run_id,
                    operation_table.c.call_no == call_no,
                )
            ).first()
            if duplicate is not None:
                raise ProviderRepositoryError("Demo acceptance call ordinal is already bound")
            now = self._now()
            changed = connection.execute(
                update(operation_table)
                .where(
                    operation_table.c.id == operation_id,
                    operation_table.c.state == "prepared",
                    operation_table.c.request_count == 0,
                    operation_table.c.charged_request_count == 0,
                    operation_table.c.acceptance_run_id.is_(None),
                    operation_table.c.call_no.is_(None),
                )
                .values(
                    acceptance_run_id=acceptance_run_id,
                    call_no=call_no,
                    updated_at=now,
                )
            )
            if changed.rowcount != 1:
                raise ProviderRepositoryError("provider operation attach CAS failed")
            if run_row["state"] == "prepared":
                run_changed = connection.execute(
                    update(run_table)
                    .where(run_table.c.id == acceptance_run_id, run_table.c.state == "prepared")
                    .values(state="executing", updated_at=now)
                )
                if run_changed.rowcount != 1:
                    raise ProviderRepositoryError("Demo acceptance run state CAS failed")
        return self.operation(operation_id)

    # Descriptive aliases keep the narrow seam easy to find for generation
    # callers without creating another persistence path.
    attach_acceptance_call_no = attach_acceptance_call
    bind_acceptance_call = attach_acceptance_call

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
        """Atomically record one reservation before provider I/O, without quota checks."""

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
            budget_bucket = budget_bucket_for_operation(str(operation_row["provider_operation"]))
            budget_row = (
                connection.execute(
                    select(budget_table).where(
                        budget_table.c.scope_id == operation_row["scope_id"],
                        budget_table.c.budget_bucket == budget_bucket,
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
            reservation_id = str(uuid4())
            now = self._now()
            budget_changed = connection.execute(
                update(budget_table)
                .where(
                    budget_table.c.scope_id == operation_row["scope_id"],
                    budget_table.c.budget_bucket == budget_bucket,
                )
                .values(
                    allocated_requests=allocated_requests + 1,
                    allocated_total_tokens=allocated_tokens + _as_int(operation_row["max_tokens"]),
                    allocated_cost_cny=allocated_cost + _as_float(operation_row["max_cost_cny"]),
                    updated_at=now,
                )
            )
            if budget_changed.rowcount != 1:
                raise ScopeBudgetMissing("scope budget changed during reservation")
            existing_reservation = (
                connection.execute(
                    select(reservation_table.c.id).where(
                        reservation_table.c.operation_id == operation_id
                    )
                )
                .mappings()
                .first()
            )
            if existing_reservation is None:
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
            else:
                connection.execute(
                    update(reservation_table)
                    .where(reservation_table.c.operation_id == operation_id)
                    .values(state="reserved", updated_at=now)
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
        sending_guard: ProviderSendingGuard | None = None,
    ) -> ProviderOperationV1:
        operation_table = _OPERATION_TABLE
        reservation_table = _RESERVATION_TABLE
        budget_table = _BUDGET_TABLE
        dispatch_rejected = False
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
            target_state = state
            target_safe_error_code = safe_error_code
            if sending_guard is not None:
                if expected != "reserved" or state != "sending":
                    raise ProviderRepositoryError(
                        "a provider sending guard is only valid for reserved-to-sending"
                    )
                if not sending_guard(connection, row):
                    target_state = "not_sent"
                    target_safe_error_code = "provider_dispatch_rejected"
                    dispatch_rejected = True
            if not can_transition(expected, target_state):
                raise OperationStateError(
                    f"invalid provider operation transition: {expected}->{target_state}"
                )
            if (
                expected == "failed"
                and state == "accepted"
                and (response_hash is None or response_hash != row["staged_response_hash"])
            ):
                raise OperationStateError("failed accept restore requires the stored stage hash")
            if state == "accepted" and response_hash is None:
                raise ProviderRepositoryError("accepted operation needs staged response hash")
            if response_hash is not None and not _SHA256_RE.fullmatch(response_hash):
                raise ProviderRepositoryError("staged response hash is invalid")
            now = self._now()
            values: dict[str, object] = {
                "state": target_state,
                "safe_error_code": _safe_code(target_safe_error_code)
                if target_safe_error_code
                else row["safe_error_code"],
                "updated_at": now,
            }
            if dispatch_rejected:
                values["request_count"] = 0
                values["charged_request_count"] = 0
            elif (
                str(row["provider_operation"]) == "llm_knowledge_generate"
                and target_state == "not_sent"
            ):
                # K2b1 is a one-shot operation. A proved-not-sent call has
                # consumed neither supplier acceptance nor a billable request.
                values["request_count"] = 0
                values["charged_request_count"] = 0
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
                    .values(state=target_state, updated_at=now)
                )
            if target_state == "not_sent" and reservation_row is not None:
                # Releasing is part of the same transaction as the state CAS.
                budget_changed = connection.execute(
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
                if budget_changed.rowcount != 1:
                    raise ProviderRepositoryError("scope budget release CAS failed")
        if dispatch_rejected:
            raise ProviderDispatchRejected("the Chat request is no longer active")
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

    def stage_llm_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: LLMRecoveryInputV1 | SegmentRecoveryInputV2,
    ) -> LLMAcceptedStageV1:
        """Persist the accepted stage/input pair in one SQL transaction."""

        if isinstance(recovery_input, SegmentRecoveryInputV2):
            return self.stage_segment_accepted_with_recovery(stage, recovery_input)

        stage.__post_init__()
        recovery_input.__post_init__()
        if (
            recovery_input.operation_id != stage.operation_id
            or recovery_input.turn_id != stage.turn_id
            or recovery_input.attempt_no != stage.attempt_no
        ):
            raise ProviderRepositoryError("LLM recovery input does not match accepted stage")

        operation_table = _OPERATION_TABLE
        stage_table = _LLM_STAGE_TABLE
        recovery_table = _LLM_RECOVERY_INPUT_TABLE
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
            try:
                recovery_input.assert_stage_identity(
                    stage,
                    _operation_from_row(cast(Mapping[str, object], operation_row)),
                )
            except ProviderControlError as exc:
                raise ProviderRepositoryError(
                    "LLM recovery input identity does not match accepted stage"
                ) from exc
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

            existing_stage_row = (
                connection.execute(
                    select(stage_table).where(stage_table.c.operation_id == stage.operation_id)
                )
                .mappings()
                .first()
            )
            existing_input_row = (
                connection.execute(
                    select(recovery_table).where(
                        recovery_table.c.operation_id == recovery_input.operation_id
                    )
                )
                .mappings()
                .first()
            )
            if existing_stage_row is not None or existing_input_row is not None:
                if existing_stage_row is None or existing_input_row is None:
                    raise ProviderRepositoryError("LLM accepted bundle is partial")
                existing_stage = _llm_stage_from_row(cast(Mapping[str, object], existing_stage_row))
                existing_input = _llm_recovery_input_from_row(
                    cast(Mapping[str, object], existing_input_row)
                )
                if not _stages_equal(existing_stage, stage) or existing_input != recovery_input:
                    raise ProviderRepositoryError("LLM accepted bundle is immutable")
                if operation_row["state"] not in {"accepted", "succeeded"}:
                    raise ProviderRepositoryError("LLM accepted bundle operation state is invalid")
                return existing_stage

            operation_state = str(operation_row["state"])
            if operation_state not in {"sending", "accepted"}:
                raise ProviderRepositoryError("LLM accepted bundle requires an accepted response")
            if (
                operation_state == "accepted"
                and operation_row["staged_response_hash"] != stage.output_hash
            ):
                raise ProviderRepositoryError("LLM accepted stage response hash is stale")
            now = self._now()
            connection.execute(
                recovery_table.insert().values(
                    **recovery_input.as_record(),
                    created_at=now,
                )
            )
            connection.execute(stage_table.insert().values(**stage.as_record(), created_at=now))
            if operation_state == "sending":
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
                reservation_changed = connection.execute(
                    update(reservation_table)
                    .where(
                        reservation_table.c.operation_id == stage.operation_id,
                        reservation_table.c.state == "sending",
                    )
                    .values(state="accepted", updated_at=now)
                )
                if changed.rowcount != 1 or reservation_changed.rowcount != 1:
                    raise ProviderRepositoryError("LLM accepted bundle transition failed")
        return stage

    def stage_segment_accepted_with_recovery(
        self,
        stage: LLMAcceptedStageV1,
        recovery_input: SegmentRecoveryInputV2,
    ) -> LLMAcceptedStageV1:
        """Persist a v2 stage and its typed frozen request atomically."""

        stage.__post_init__()
        recovery_input.__post_init__()
        if (
            recovery_input.operation_id != stage.operation_id
            or recovery_input.turn_id != stage.turn_id
            or recovery_input.attempt_no != stage.attempt_no
        ):
            raise ProviderRepositoryError("segment recovery input does not match accepted stage")
        operation_table = _OPERATION_TABLE
        stage_table = _LLM_STAGE_TABLE
        recovery_table = _LLM_RECOVERY_INPUT_TABLE
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
            operation = _operation_from_row(cast(Mapping[str, object], operation_row))
            try:
                recovery_input.assert_stage_identity(stage, operation)
            except Exception as exc:
                raise ProviderRepositoryError(
                    "segment recovery input identity does not match accepted stage"
                ) from exc
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
            existing_stage_row = (
                connection.execute(
                    select(stage_table).where(stage_table.c.operation_id == stage.operation_id)
                )
                .mappings()
                .first()
            )
            existing_input_row = (
                connection.execute(
                    select(recovery_table).where(
                        recovery_table.c.operation_id == recovery_input.operation_id
                    )
                )
                .mappings()
                .first()
            )
            if existing_stage_row is not None or existing_input_row is not None:
                if existing_stage_row is None or existing_input_row is None:
                    raise ProviderRepositoryError("LLM accepted bundle is partial")
                existing_stage = _llm_stage_from_row(cast(Mapping[str, object], existing_stage_row))
                existing_input = _llm_recovery_input_from_row(
                    cast(Mapping[str, object], existing_input_row)
                )
                if not isinstance(existing_input, SegmentRecoveryInputV2):
                    raise ProviderRepositoryError("LLM accepted bundle has the wrong version")
                if not _stages_equal(existing_stage, stage) or existing_input != recovery_input:
                    raise ProviderRepositoryError("LLM accepted bundle is immutable")
                if operation_row["state"] not in {"accepted", "succeeded"}:
                    raise ProviderRepositoryError("LLM accepted bundle operation state is invalid")
                return existing_stage
            operation_state = str(operation_row["state"])
            if operation_state not in {"sending", "accepted"}:
                raise ProviderRepositoryError("LLM accepted bundle requires an accepted response")
            if (
                operation_state == "accepted"
                and operation_row["staged_response_hash"] != stage.output_hash
            ):
                raise ProviderRepositoryError("LLM accepted stage response hash is stale")
            now = self._now()
            connection.execute(
                recovery_table.insert().values(
                    **recovery_input.as_record(),
                    created_at=now,
                )
            )
            connection.execute(stage_table.insert().values(**stage.as_record(), created_at=now))
            if operation_state == "sending":
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
                reservation_changed = connection.execute(
                    update(reservation_table)
                    .where(
                        reservation_table.c.operation_id == stage.operation_id,
                        reservation_table.c.state == "sending",
                    )
                    .values(state="accepted", updated_at=now)
                )
                if changed.rowcount != 1 or reservation_changed.rowcount != 1:
                    raise ProviderRepositoryError("LLM accepted bundle transition failed")
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

    def load_llm_accepted_bundle(
        self, operation_id: str
    ) -> LLMAcceptedBundleV1 | SegmentAcceptedBundleV2 | None:
        """Load and validate one exact accepted stage/input recovery bundle."""

        operation_table = _OPERATION_TABLE
        with self.engine.connect() as connection:
            operation_row = (
                connection.execute(
                    select(operation_table).where(operation_table.c.id == operation_id)
                )
                .mappings()
                .first()
            )
            stage_row = (
                connection.execute(
                    select(_LLM_STAGE_TABLE).where(_LLM_STAGE_TABLE.c.operation_id == operation_id)
                )
                .mappings()
                .first()
            )
            input_row = (
                connection.execute(
                    select(_LLM_RECOVERY_INPUT_TABLE).where(
                        _LLM_RECOVERY_INPUT_TABLE.c.operation_id == operation_id
                    )
                )
                .mappings()
                .first()
            )
        if stage_row is None and input_row is None:
            return None
        if stage_row is None:
            raise ProviderRepositoryError("LLM recovery input has no accepted stage")
        # Accepted rows written before 0015 remain readable through the old
        # stage accessor, but cannot be resumed without their missing input.
        if input_row is None:
            return None
        if operation_row is None:
            raise ProviderRepositoryError("LLM accepted bundle operation does not exist")
        stage = _llm_stage_from_row(cast(Mapping[str, object], stage_row))
        recovery_input = _llm_recovery_input_from_row(cast(Mapping[str, object], input_row))
        if isinstance(recovery_input, SegmentRecoveryInputV2):
            try:
                recovery_input.assert_stage_identity(
                    stage,
                    _operation_from_row(cast(Mapping[str, object], operation_row)),
                )
            except Exception as exc:
                raise ProviderRepositoryError("LLM accepted bundle identity is corrupt") from exc
            if (
                operation_row["provider_operation"] != "llm_debate_turn"
                or operation_row["logical_item_id"] != stage.turn_id
                or _as_int(operation_row["attempt_no"]) != stage.attempt_no
                or operation_row["request_hash"] != stage.request_hash
                or operation_row["policy_hash"] != stage.policy_hash
                or operation_row["export_manifest_hash"] != stage.export_manifest_hash
                or operation_row["build_manifest_hash"] != stage.build_manifest_hash
                or operation_row["model_key"] != stage.model_key
                or operation_row["state"] not in {"accepted", "succeeded"}
                or operation_row["staged_response_hash"] != stage.output_hash
                or recovery_input.operation_id != stage.operation_id
                or recovery_input.turn_id != stage.turn_id
                or recovery_input.attempt_no != stage.attempt_no
            ):
                raise ProviderRepositoryError("LLM accepted bundle identity is corrupt")
            return SegmentAcceptedBundleV2(stage=stage, recovery_input=recovery_input)
        try:
            recovery_input.assert_stage_identity(
                stage,
                _operation_from_row(cast(Mapping[str, object], operation_row)),
            )
        except ProviderControlError as exc:
            raise ProviderRepositoryError("LLM accepted bundle identity is corrupt") from exc
        if (
            operation_row["provider_operation"] != "llm_debate_turn"
            or operation_row["logical_item_id"] != stage.turn_id
            or _as_int(operation_row["attempt_no"]) != stage.attempt_no
            or operation_row["request_hash"] != stage.request_hash
            or operation_row["policy_hash"] != stage.policy_hash
            or operation_row["export_manifest_hash"] != stage.export_manifest_hash
            or operation_row["build_manifest_hash"] != stage.build_manifest_hash
            or operation_row["model_key"] != stage.model_key
            or operation_row["state"] not in {"accepted", "succeeded"}
            or operation_row["staged_response_hash"] != stage.output_hash
            or recovery_input.operation_id != stage.operation_id
            or recovery_input.turn_id != stage.turn_id
            or recovery_input.attempt_no != stage.attempt_no
        ):
            raise ProviderRepositoryError("LLM accepted bundle identity is corrupt")
        return LLMAcceptedBundleV1(stage=stage, recovery_input=recovery_input)

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

    def complete_report_in_session(
        self,
        db: Session,
        operation_id: str,
        *,
        response_hash: str,
    ) -> ProviderOperation:
        """Stage Real Report success on the caller's transaction.

        Reserve/send are intentionally committed by the narrow control
        repository before transport.  The report revision, current-success
        pointer, Job and this final operation/reservation promotion must share
        the caller Session so a publication rollback cannot leave ``succeeded``.
        """

        if not _SHA256_RE.fullmatch(response_hash):
            raise ProviderRepositoryError("staged response hash is invalid")
        operation = db.get(ProviderOperation, operation_id)
        if operation is None:
            raise OperationStateError("provider operation does not exist")
        # The operation may have been read before the independent reserve/send
        # CAS. Refresh it before applying the caller-owned final CAS fence.
        db.refresh(operation)
        if (
            operation.provider_operation != "llm_maya_report"
            or operation.state != "sending"
            or operation.request_count != 1
            or operation.charged_request_count != 1
            or operation.staged_response_hash is not None
        ):
            raise OperationStateError("Real Report operation is not sending")
        reservation = db.scalar(
            select(ProviderReservation).where(
                ProviderReservation.operation_id == operation_id,
            )
        )
        if reservation is None or reservation.state != "sending":
            raise OperationStateError("Real Report reservation is not sending")
        now = self._now()
        operation.staged_response_hash = response_hash
        operation.state = "succeeded"
        operation.safe_error_code = None
        operation.updated_at = now
        reservation.state = "succeeded"
        reservation.updated_at = now
        return operation

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
        legacy_accepted_stage = False
        if current.provider_operation == "llm_debate_turn":
            if current.state == "accepted":
                try:
                    legacy_accepted_stage = (
                        self.get_llm_accepted_stage(operation_id) is not None
                        and self._read_one(
                            select(_LLM_RECOVERY_INPUT_TABLE.c.operation_id).where(
                                _LLM_RECOVERY_INPUT_TABLE.c.operation_id == operation_id
                            )
                        )
                        is None
                    )
                except ProviderControlError:
                    legacy_accepted_stage = False
            try:
                complete = self.load_llm_accepted_bundle(operation_id) is not None
            except ProviderRepositoryError:
                complete = False
            if legacy_accepted_stage:
                # 0014 accepted rows are authoritative output stages, but
                # cannot be resumed without the additive 0015 input.  Keep
                # their acceptance state and let callers surface the blocked
                # recovery explicitly instead of relabeling it uncertain.
                return current
        elif current.provider_operation == "llm_knowledge_generate":
            stage_row = self._read_one(
                select(_KNOWLEDGE_GENERATION_STAGE_TABLE.c.run_id).where(
                    _KNOWLEDGE_GENERATION_STAGE_TABLE.c.operation_id == operation_id
                )
            )
            complete = stage_row is not None
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
        table = _OPERATION_TABLE
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(table.c.id).where(
                    table.c.provider_operation.in_(("llm_debate_turn", "llm_knowledge_generate")),
                    table.c.state.in_(("reserved", "sending", "accepted")),
                )
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
        acceptance_run_id=(
            str(row["acceptance_run_id"]) if row.get("acceptance_run_id") is not None else None
        ),
        call_no=(_as_int(row["call_no"]) if row.get("call_no") is not None else None),
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


def _llm_recovery_input_from_row(
    row: Mapping[str, object],
) -> LLMRecoveryInputV1 | SegmentRecoveryInputV2:
    try:
        input_version = str(row["input_version"])
        if input_version == "segment_recovery_input_v2":
            return SegmentRecoveryInputV2(
                operation_id=str(row["operation_id"]),
                turn_id=str(row["turn_id"]),
                attempt_no=_as_int(row["attempt_no"]),
                input_version=input_version,  # type: ignore[arg-type]
                input_json=str(row["input_json"]),
                input_hash=str(row["input_hash"]),
            )
        return LLMRecoveryInputV1(
            operation_id=str(row["operation_id"]),
            turn_id=str(row["turn_id"]),
            attempt_no=_as_int(row["attempt_no"]),
            input_version=input_version,
            input_json=str(row["input_json"]),
            input_hash=str(row["input_hash"]),
        )
    except Exception as exc:
        raise ProviderRepositoryError("LLM recovery input is corrupt") from exc


def _stages_equal(left: LLMAcceptedStageV1, right: LLMAcceptedStageV1) -> bool:
    """Compare normalized records so SQLite Decimal values are deterministic."""

    left_record = left.as_record()
    right_record = right.as_record()
    for key in (
        "input_price_cny_per_million",
        "cached_input_price_cny_per_million",
        "output_price_cny_per_million",
        "estimated_cost_cny",
        "actual_cost_cny",
    ):
        left_value = left_record[key]
        right_value = right_record[key]
        if left_value is None or right_value is None:
            if left_value != right_value:
                return False
            continue
        if Decimal(str(left_value)) != Decimal(str(right_value)):
            return False
        left_record[key] = right_record[key] = None
    return left_record == right_record


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
