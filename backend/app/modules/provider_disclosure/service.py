"""Teacher-only ProviderDataCallV1 disclosure and confirmation service.

This module is a deliberately small seam between the public teacher screen and
the server-only provider-control ledger.  It never selects a provider and
never performs network I/O.  A main-window adapter supplies the durable policy,
manifest and confirmation rows through :class:`ProviderDisclosureStore`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderPolicySnapshot,
)
from app.providers.control import (
    ALLOWED_ACCOUNT_PRODUCTS,
    FIXED_MODELS,
    FIXED_REGION,
    ExportConfirmationV1,
    ExportManifestV1,
    ProviderControlError,
    ProviderPolicySnapshotV1,
    ProviderPreflightV1,
    confirm_export_manifest,
    validate_provider_preflight,
)
from app.providers.control_repository import ProviderRepository

from .schemas import (
    DisclosureFieldClass,
    ProviderDataCallConfirmationRequestV1,
    ProviderDataCallDisclosureResponseV1,
    ProviderDataCallDisclosureV1,
)

PROVIDER_DISCLOSURE_VERSION = "ProviderDataCallV1"
SUPPLIER_DISPLAY_NAME = "Alibaba Cloud Model Studio"
STORAGE_FACT = "The supplier stores call data as required by applicable law."

_PURPOSES: Mapping[str, str] = {
    "embedding": "Build an evidence search index from an approved immutable snapshot.",
    "embedding_query": (
        "Embed approved retrieval questions to search one immutable evidence snapshot."
    ),
    "llm_debate": "Generate the teacher-approved classroom debate speech.",
    "tts": "Synthesize the current classroom speech for teacher-controlled playback.",
    "voice_enrollment": "Enroll an approved voice sample for a separate voice operation.",
}
_PUBLIC_FORBIDDEN_TERMS = (
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "workspace",
    "resource_id",
    "endpoint",
    "http://",
    "https://",
    "private",
    "ledger",
    "payload",
    "student_id",
    "student_name",
    "user_id",
    "user_name",
    "identity",
    "nickname",
    "teacher_note",
    "source_filename",
    "chunk_id",
    "source_path",
    "absolute_path",
)
_FORBIDDEN_MODEL_TERMS = tuple(value.casefold() for value in FIXED_MODELS.values()) + (
    "qwen",
    "text-embedding",
)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class ProviderDisclosureError(Exception):
    """Safe domain error mapped by the standalone Provider router."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


class ProviderDisclosureStoreError(RuntimeError):
    """A durable disclosure lookup or CAS cannot be completed safely."""


class ProviderDisclosureStore(Protocol):
    """Persistence and teacher-membership port for the disclosure service."""

    def get_policy_snapshot(self, reference: str | None = None) -> ProviderPolicySnapshotV1 | None:
        """Return a policy by immutable ID/hash, or the configured current row."""

    def get_export_manifest(self, reference: str | None = None) -> ExportManifestV1 | None:
        """Return a manifest by immutable ID/hash, or the configured current row."""

    def get_export_manifest_id(self, manifest_hash: str) -> str | None:
        """Resolve the server-only durable row ID for a manifest hash."""

    def get_export_confirmation(self, manifest_hash: str) -> ExportConfirmationV1 | None:
        """Read the immutable confirmation bound to a manifest, if any."""

    def save_export_confirmation(
        self,
        manifest_id: str,
        confirmation: ExportConfirmationV1,
        *,
        expected_revision: int,
    ) -> str:
        """Persist a confirmation only when the exact revision still matches."""

    def is_teacher(self, user_id: str) -> bool:
        """Return whether the account is a current teacher."""

    def is_teacher_for_manifest(self, user_id: str, manifest_hash: str) -> bool:
        """Return whether the account teaches the exact manifest owner course."""


def _blocked(code: str = "provider_preflight_blocked") -> ProviderDisclosureError:
    return ProviderDisclosureError(
        code,
        "Provider disclosure is unavailable until every account and privacy control is verified.",
    )


def _stale(message: str = "Provider disclosure confirmation is stale.") -> ProviderDisclosureError:
    return ProviderDisclosureError("provider_preflight_stale", message)


def _safe_public_text(value: str, *, allow_supplier_name: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _blocked()
    folded = value.casefold()
    if any(term in folded for term in _PUBLIC_FORBIDDEN_TERMS):
        raise _blocked()
    if any(term in folded for term in _FORBIDDEN_MODEL_TERMS):
        raise _blocked()
    if _UUID_RE.search(value):
        raise _blocked()
    if not allow_supplier_name and ("/" in value or "\\" in value):
        raise _blocked()
    return value


class ProviderDisclosureService:
    """Build the exact disclosure and bind teacher confirmation by CAS."""

    def __init__(
        self,
        store: ProviderDisclosureStore,
        *,
        policy_ref: str | None = None,
        manifest_ref: str | None = None,
        teacher_authorizer: Callable[[str], bool] | None = None,
    ) -> None:
        self.store = store
        self.policy_ref = policy_ref
        self.manifest_ref = manifest_ref
        self.teacher_authorizer = teacher_authorizer

    def disclose(
        self,
        actor_user_id: str,
        *,
        policy_ref: str | None = None,
        manifest_ref: str | None = None,
    ) -> ProviderDataCallDisclosureResponseV1:
        policy, manifest = self._load(policy_ref=policy_ref, manifest_ref=manifest_ref)
        self._assert_teacher(actor_user_id, manifest.manifest_hash)
        return self._response(policy, manifest)

    def confirm(
        self,
        request: ProviderDataCallConfirmationRequestV1,
        *,
        actor_user_id: str,
        policy_ref: str | None = None,
        manifest_ref: str | None = None,
    ) -> ProviderDataCallDisclosureResponseV1:
        policy, manifest = self._load(policy_ref=policy_ref, manifest_ref=manifest_ref)
        self._assert_teacher(actor_user_id, manifest.manifest_hash)
        revision = self._revision(manifest)
        if request.policy_hash != policy.policy_hash:
            raise _stale("The provider policy changed; review the current disclosure again.")
        if request.manifest_hash != manifest.manifest_hash:
            raise _stale("The export manifest changed; review the current disclosure again.")
        if request.expected_revision != revision:
            raise _stale("The provider disclosure revision changed; review it again.")

        try:
            existing = self.store.get_export_confirmation(manifest.manifest_hash)
        except Exception as exc:
            raise _blocked("provider_confirmation_unavailable") from exc
        if existing is not None:
            if self._confirmation_matches(existing, policy, manifest, revision):
                return self._response(policy, manifest)
            raise _stale("A previous provider confirmation no longer matches this disclosure.")

        try:
            confirmation = confirm_export_manifest(
                manifest,
                policy,
                confirmed_at=datetime.now(UTC).isoformat(),
                expected_manifest_hash=request.manifest_hash,
                expected_policy_hash=request.policy_hash,
            )
            confirmation = ExportConfirmationV1(
                manifest_hash=confirmation.manifest_hash,
                policy_hash=confirmation.policy_hash,
                confirmed_at=confirmation.confirmed_at,
                confirmation_revision=revision,
            )
            manifest_id = self.store.get_export_manifest_id(manifest.manifest_hash)
            if manifest_id is None:
                raise ProviderDisclosureError(
                    "not_found", "The provider export manifest was not found."
                )
            self.store.save_export_confirmation(
                manifest_id,
                confirmation,
                expected_revision=revision,
            )
        except ProviderDisclosureError:
            raise
        except ProviderDisclosureStoreError as exc:
            raise _stale() from exc
        except ProviderControlError as exc:
            raise _stale() from exc
        except Exception as exc:
            # A concurrent confirmation is safe only if the durable row now
            # matches the exact request.  Never turn an unknown write outcome
            # into a second confirmation or a provider call.
            try:
                current = self.store.get_export_confirmation(manifest.manifest_hash)
            except Exception:
                current = None
            if current is not None and self._confirmation_matches(
                current, policy, manifest, revision
            ):
                return self._response(policy, manifest)
            raise ProviderDisclosureError(
                "provider_confirmation_unavailable",
                "The provider disclosure confirmation could not be saved safely.",
            ) from exc
        return self._response(policy, manifest)

    def preflight(
        self,
        *,
        actor_user_id: str,
        provider_operation: str,
        model_key: str,
        scope_id: str,
        region: str = FIXED_REGION,
        payload: object | None = None,
        policy_ref: str | None = None,
        manifest_ref: str | None = None,
    ) -> ProviderPreflightV1:
        """Validate a confirmed operation without invoking a transport."""

        policy, manifest = self._load(policy_ref=policy_ref, manifest_ref=manifest_ref)
        self._assert_teacher(actor_user_id, manifest.manifest_hash)
        revision = self._revision(manifest)
        try:
            confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
        except ProviderDisclosureStoreError as exc:
            raise _blocked("provider_confirmation_unavailable") from exc
        if confirmation is None or not self._confirmation_matches(
            confirmation, policy, manifest, revision
        ):
            raise ProviderDisclosureError(
                "provider_confirmation_required",
                "Confirm the exact provider disclosure before any external request.",
            )
        try:
            return validate_provider_preflight(
                policy,
                manifest,
                confirmation,
                scope_id=scope_id,
                provider_operation=provider_operation,
                model_key=model_key,
                region=region,
                payload=payload,
            )
        except ProviderControlError as exc:
            if exc.code in {"policy_hash_stale", "export_hash_stale"}:
                raise _stale() from exc
            raise _blocked() from exc

    def _assert_teacher(self, actor_user_id: str, manifest_hash: str) -> None:
        if not isinstance(actor_user_id, str) or not actor_user_id.strip():
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        authorizer = self.teacher_authorizer
        if authorizer is None:
            manifest_authorizer = getattr(self.store, "is_teacher_for_manifest", None)
            allowed = (
                bool(manifest_authorizer(actor_user_id, manifest_hash))
                if callable(manifest_authorizer)
                else False
            )
        else:
            allowed = bool(authorizer(actor_user_id))
        if not allowed:
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")

    def _load(
        self,
        *,
        policy_ref: str | None,
        manifest_ref: str | None,
    ) -> tuple[ProviderPolicySnapshotV1, ExportManifestV1]:
        resolved_manifest_ref = manifest_ref if manifest_ref is not None else self.manifest_ref
        try:
            manifest = self.store.get_export_manifest(resolved_manifest_ref)
        except Exception as exc:
            raise _blocked("provider_manifest_unavailable") from exc
        if manifest is None:
            raise ProviderDisclosureError(
                "not_found", "The provider export manifest was not found."
            )
        resolved_policy_ref = policy_ref if policy_ref is not None else self.policy_ref
        if resolved_policy_ref is None:
            current_policy = getattr(self.store, "get_current_policy_snapshot", None)
            try:
                policy = (
                    current_policy()
                    if callable(current_policy)
                    else self.store.get_policy_snapshot(manifest.policy_hash)
                )
            except Exception as exc:
                raise _blocked("provider_policy_unavailable") from exc
        else:
            try:
                policy = self.store.get_policy_snapshot(resolved_policy_ref)
            except Exception as exc:
                raise _blocked("provider_policy_unavailable") from exc
        if policy is None:
            raise ProviderDisclosureError("not_found", "The provider policy was not found.")
        try:
            policy.validate()
            manifest.validate()
        except ProviderControlError as exc:
            raise _blocked(getattr(exc, "code", "provider_policy_invalid")) from exc
        controls = (
            policy.prompt_response_logging_disabled,
            policy.inference_log_backflow_disabled,
            policy.optional_content_logging_disabled,
            policy.service_improvement_disabled,
        )
        if (
            policy.region != FIXED_REGION
            or policy.account_product not in ALLOWED_ACCOUNT_PRODUCTS
            or any(value is not True for value in controls)
            or policy.storage_disclosed is not True
            or not isinstance(policy.no_training_basis, str)
            or not policy.no_training_basis.strip()
        ):
            raise _blocked("provider_policy_controls_unknown")
        if manifest.policy_hash != policy.policy_hash:
            raise _stale("The export manifest is bound to a different provider policy.")
        purpose = _PURPOSES.get(manifest.provider_operation)
        if purpose is None:
            raise _blocked("provider_operation_invalid")
        if manifest.model_key != FIXED_MODELS[manifest.provider_operation]:
            raise _blocked("provider_model_invalid")
        if policy.supplier != SUPPLIER_DISPLAY_NAME:
            raise _blocked("provider_supplier_invalid")
        # Validate every text that will be copied to the teacher-facing DTO;
        # this is a second boundary in addition to the server-side dataclass.
        _safe_public_text(policy.supplier, allow_supplier_name=True)
        _safe_public_text(policy.no_training_basis)
        if policy.retention_setting is not None:
            _safe_public_text(policy.retention_setting)
        _safe_public_text(purpose)
        return policy, manifest

    @staticmethod
    def _revision(manifest: ExportManifestV1) -> int:
        revision = manifest.operation_revision
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise _blocked("provider_revision_invalid")
        return revision

    @staticmethod
    def _confirmation_matches(
        confirmation: ExportConfirmationV1,
        policy: ProviderPolicySnapshotV1,
        manifest: ExportManifestV1,
        revision: int,
    ) -> bool:
        try:
            return (
                confirmation.policy_hash == policy.policy_hash
                and confirmation.manifest_hash == manifest.manifest_hash
                and confirmation.confirmation_revision == revision
            )
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def _response(
        policy: ProviderPolicySnapshotV1,
        manifest: ExportManifestV1,
    ) -> ProviderDataCallDisclosureResponseV1:
        purpose = _PURPOSES.get(manifest.provider_operation)
        if purpose is None:  # pragma: no cover - guarded by _load
            raise _blocked("provider_operation_invalid")
        fields = tuple(cast(DisclosureFieldClass, field.field_class) for field in manifest.fields)
        disclosure = ProviderDataCallDisclosureV1(
            supplier_display_name=policy.supplier,
            region=policy.region,  # type: ignore[arg-type]
            purpose=purpose,
            outbound_field_classes=fields,
            storage_fact=STORAGE_FACT,
            no_training_basis=policy.no_training_basis,
            retention_setting=policy.retention_setting or "unknown",
        )
        return ProviderDataCallDisclosureResponseV1(
            disclosure=disclosure,
            policy_hash=policy.policy_hash,
            manifest_hash=manifest.manifest_hash,
            confirmation_revision=ProviderDisclosureService._revision(manifest),
        )


class InMemoryProviderDisclosureStore:
    """Thread-safe deterministic store used by service/router tests."""

    def __init__(
        self,
        policy: ProviderPolicySnapshotV1,
        manifest: ExportManifestV1,
        *,
        teacher_ids: tuple[str, ...] = ("teacher",),
    ) -> None:
        self.policy = policy
        self.manifest = manifest
        self.teacher_ids = frozenset(teacher_ids)
        self.confirmations: dict[str, ExportConfirmationV1] = {}
        self.confirmation_manifest_ids: dict[str, str] = {manifest.manifest_hash: "manifest-1"}
        self._lock = RLock()

    def get_policy_snapshot(self, reference: str | None = None) -> ProviderPolicySnapshotV1 | None:
        if reference is None or reference in {self.policy.policy_id, self.policy.policy_hash}:
            return self.policy
        return None

    def get_current_policy_snapshot(self) -> ProviderPolicySnapshotV1:
        return self.policy

    def get_export_manifest(self, reference: str | None = None) -> ExportManifestV1 | None:
        if reference is None or reference in {self.manifest.scope_id, self.manifest.manifest_hash}:
            return self.manifest
        return None

    def get_current_export_manifest(self) -> ExportManifestV1:
        return self.manifest

    def get_export_manifest_id(self, manifest_hash: str) -> str | None:
        return self.confirmation_manifest_ids.get(manifest_hash)

    def get_export_confirmation(self, manifest_hash: str) -> ExportConfirmationV1 | None:
        with self._lock:
            return self.confirmations.get(manifest_hash)

    def save_export_confirmation(
        self,
        manifest_id: str,
        confirmation: ExportConfirmationV1,
        *,
        expected_revision: int,
    ) -> str:
        del manifest_id
        if expected_revision != self.manifest.operation_revision:
            raise ProviderDisclosureStoreError("provider disclosure revision is stale")
        with self._lock:
            existing = self.confirmations.get(confirmation.manifest_hash)
            if existing is not None:
                raise ProviderDisclosureStoreError("provider confirmation already exists")
            self.confirmations[confirmation.manifest_hash] = confirmation
            confirmation_id = f"confirmation-{len(self.confirmations)}"
            return confirmation_id

    def is_teacher(self, user_id: str) -> bool:
        return user_id in self.teacher_ids

    def is_teacher_for_manifest(self, user_id: str, manifest_hash: str) -> bool:
        return user_id in self.teacher_ids and manifest_hash == self.manifest.manifest_hash

    def replace_current(
        self,
        policy: ProviderPolicySnapshotV1,
        manifest: ExportManifestV1,
    ) -> None:
        with self._lock:
            self.policy = policy
            self.manifest = manifest
            self.confirmation_manifest_ids[manifest.manifest_hash] = (
                f"manifest-{len(self.confirmation_manifest_ids) + 1}"
            )


class SqlAlchemyProviderDisclosureStore:
    """Adapter over the existing provider-control ORM tables.

    Confirmation writes stay in the request Session so the caller's normal
    transaction commits the CAS.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._control = ProviderRepository(db)

    def get_policy_snapshot(self, reference: str | None = None) -> ProviderPolicySnapshotV1 | None:
        if reference is None:
            identifier = self.db.scalar(
                select(ProviderPolicySnapshot.id)
                .order_by(
                    ProviderPolicySnapshot.created_at.desc(),
                    ProviderPolicySnapshot.id.desc(),
                )
                .limit(1)
            )
            if identifier is None:
                return None
            reference = str(identifier)
        try:
            return self._control.get_policy_snapshot(reference)
        except Exception as exc:
            raise ProviderDisclosureStoreError("provider policy row is invalid") from exc

    def get_current_policy_snapshot(self) -> ProviderPolicySnapshotV1 | None:
        return self.get_policy_snapshot()

    def get_export_manifest(self, reference: str | None = None) -> ExportManifestV1 | None:
        if reference is None:
            identifier = self.db.scalar(
                select(ProviderExportManifest.manifest_hash)
                .order_by(
                    ProviderExportManifest.created_at.desc(),
                    ProviderExportManifest.manifest_hash.desc(),
                )
                .limit(1)
            )
            if identifier is None:
                return None
            reference = str(identifier)
        try:
            return self._control.get_export_manifest(reference)
        except Exception as exc:
            raise ProviderDisclosureStoreError("provider manifest row is invalid") from exc

    def get_current_export_manifest(self) -> ExportManifestV1 | None:
        return self.get_export_manifest()

    def get_export_manifest_id(self, manifest_hash: str) -> str | None:
        return self.db.scalar(
            select(ProviderExportManifest.id).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )

    def get_export_confirmation(self, manifest_hash: str) -> ExportConfirmationV1 | None:
        row = self.db.scalar(
            select(ProviderExportConfirmation).where(
                ProviderExportConfirmation.manifest_hash == manifest_hash
            )
        )
        if row is None:
            return None
        try:
            return ExportConfirmationV1(
                manifest_hash=row.manifest_hash,
                policy_hash=row.policy_hash,
                confirmed_at=row.confirmed_at,
                confirmation_revision=row.confirmation_revision,
            )
        except Exception as exc:
            raise ProviderDisclosureStoreError("provider confirmation row is invalid") from exc

    def save_export_confirmation(
        self,
        manifest_id: str,
        confirmation: ExportConfirmationV1,
        *,
        expected_revision: int,
    ) -> str:
        manifest = self.db.get(ProviderExportManifest, manifest_id)
        if manifest is None:
            raise ProviderDisclosureStoreError("provider export manifest does not exist")
        if (
            manifest.manifest_hash != confirmation.manifest_hash
            or manifest.policy_hash != confirmation.policy_hash
            or manifest.operation_revision != expected_revision
            or confirmation.confirmation_revision != expected_revision
        ):
            raise ProviderDisclosureStoreError("provider disclosure CAS is stale")
        existing = self.db.scalar(
            select(ProviderExportConfirmation).where(
                ProviderExportConfirmation.manifest_id == manifest_id
            )
        )
        if existing is not None:
            raise ProviderDisclosureStoreError("provider confirmation already exists")
        policy = self.db.get(ProviderPolicySnapshot, manifest.policy_snapshot_id)
        if policy is None or policy.policy_hash != confirmation.policy_hash:
            raise ProviderDisclosureStoreError("provider policy binding is stale")
        row = ProviderExportConfirmation(
            id=str(uuid4()),
            manifest_id=manifest_id,
            policy_snapshot_id=manifest.policy_snapshot_id,
            manifest_hash=confirmation.manifest_hash,
            policy_hash=confirmation.policy_hash,
            confirmed_at=confirmation.confirmed_at,
            confirmation_revision=confirmation.confirmation_revision,
            created_at=datetime.now(UTC),
        )
        self.db.add(row)
        self.db.flush()
        return row.id

    def is_teacher(self, user_id: str) -> bool:
        return (
            self.db.scalar(
                select(CourseMember.user_id).where(
                    CourseMember.user_id == user_id,
                    CourseMember.role == "teacher",
                )
            )
            is not None
        )

    def is_teacher_for_manifest(self, user_id: str, manifest_hash: str) -> bool:
        return (
            self.db.scalar(
                select(ProviderExportManifest.id)
                .join(
                    AgentVersion,
                    AgentVersion.id == ProviderExportManifest.agent_version_id,
                )
                .join(Agent, Agent.id == AgentVersion.agent_id)
                .join(Group, Group.id == Agent.group_id)
                .join(
                    CourseMember,
                    CourseMember.course_id == ProviderExportManifest.course_id,
                )
                .where(
                    ProviderExportManifest.manifest_hash == manifest_hash,
                    ProviderExportManifest.course_id.is_not(None),
                    ProviderExportManifest.group_id.is_not(None),
                    ProviderExportManifest.agent_version_id.is_not(None),
                    ProviderExportManifest.group_id == Agent.group_id,
                    ProviderExportManifest.group_id == Group.id,
                    ProviderExportManifest.course_id == Group.course_id,
                    CourseMember.user_id == user_id,
                    CourseMember.role == "teacher",
                )
            )
            is not None
        )


__all__ = [
    "InMemoryProviderDisclosureStore",
    "PROVIDER_DISCLOSURE_VERSION",
    "ProviderDisclosureError",
    "ProviderDisclosureService",
    "ProviderDisclosureStore",
    "ProviderDisclosureStoreError",
    "SqlAlchemyProviderDisclosureStore",
]
