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
    ProviderOperation,
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
    authorized_provider_model,
    confirm_export_manifest,
    validate_provider_preflight,
)
from app.providers.control_repository import ProviderRepository

from .schemas import (
    DisclosureFieldClass,
    ProviderDataCallConfirmationRequestV1,
    ProviderDataCallDebateManifestListResponseV1,
    ProviderDataCallDebateManifestSummaryV1,
    ProviderDataCallDisclosureResponseV1,
    ProviderDataCallDisclosureV1,
    ProviderDataCallManifestListResponseV1,
    ProviderDataCallManifestSummaryV1,
    ProviderDataCallPublicationManifestListResponseV1,
    ProviderDataCallPublicationManifestSummaryV1,
    ProviderDataCallReportManifestListResponseV1,
    ProviderDataCallReportManifestSummaryV1,
)

PROVIDER_DISCLOSURE_VERSION = "ProviderDataCallV1"
SUPPLIER_DISPLAY_NAME = "Alibaba Cloud Model Studio"
STORAGE_FACT = "The supplier stores call data as required by applicable law."
EMBEDDING_OPERATION = "embedding"
EMBEDDING_QUERY_OPERATION = "embedding_query"
LLM_DEBATE_OPERATION = "llm_debate_turn"
LLM_REPORT_OPERATION = "llm_maya_report"

_PURPOSES: Mapping[str, str] = {
    "embedding": "Build an evidence search index from an approved immutable snapshot.",
    "embedding_query": (
        "Embed approved retrieval questions to search one immutable evidence snapshot."
    ),
    "llm_debate": "Generate the teacher-approved classroom debate speech.",
    "llm_debate_turn": "Generate the teacher-approved classroom debate speech.",
    "llm_maya_report": "Generate the teacher-approved civilization mutual-learning report.",
    "tts": "Synthesize the current classroom speech for teacher-controlled playback.",
    "voice_enrollment": "Enroll an approved voice sample for a separate voice operation.",
}
_MODEL_KEYS: Mapping[str, str] = {
    "llm_debate_turn": "llm_debate",
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
_SAFE_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


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

    def is_teacher_for_scope(self, user_id: str, scope_id: str) -> bool:
        """Return whether the account teaches the exact scope owner course."""

    def agent_version_exists(self, agent_version_id: str) -> bool:
        """Return whether an AgentVersion exists, independent of manifests."""

    def is_teacher_for_agent_version(self, user_id: str, agent_version_id: str) -> bool:
        """Return whether the account teaches the AgentVersion's exact course."""

    def list_export_manifests(
        self,
        *,
        scope_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Return immutable manifests for one scope and operation."""

    def get_turn_id_for_manifest(self, manifest_hash: str) -> str | None:
        """Return a safe opaque turn identity when the ledger provides one."""

    def list_export_manifests_for_agent_version(
        self,
        *,
        agent_version_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Return owner-bound manifests for one AgentVersion and operation."""

    def debate_exists(self, debate_id: str) -> bool:
        """Return whether an opaque Debate row exists."""

    def is_teacher_for_debate(self, user_id: str, debate_id: str) -> bool:
        """Authorize through the exact Debate -> Course membership chain."""

    def list_export_manifests_for_debate(
        self,
        *,
        debate_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Return owner-bound manifests for one Debate and operation."""

    def list_report_manifests_for_debate(
        self,
        *,
        debate_id: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Return prepared report manifests scoped to one Debate."""


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

    def list_embedding_query_manifests(
        self,
        actor_user_id: str,
        *,
        scope_id: str,
    ) -> ProviderDataCallManifestListResponseV1:
        """List exact query manifests visible to the owning course teacher.

        The lookup is deliberately separate from :meth:`disclose`: dynamic
        query manifests are created per turn, while the normal disclosure
        endpoint addresses one already-known hash.  Every returned row is
        checked against its own course owner before any status is projected.
        A generic "is any teacher" check is never used for a non-empty scope.
        """

        if not isinstance(scope_id, str) or not _SAFE_OPAQUE_ID_RE.fullmatch(scope_id):
            raise ProviderDisclosureError("not_found", "The provider export scope was not found.")
        list_manifests = getattr(self.store, "list_export_manifests", None)
        if not callable(list_manifests):
            raise _blocked("provider_manifest_listing_unavailable")
        try:
            manifests = tuple(
                list_manifests(
                    scope_id=scope_id,
                    provider_operation=EMBEDDING_QUERY_OPERATION,
                )
            )
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_manifest_listing_unavailable") from exc

        if not manifests:
            # With no row there is no course relation to authorize against.
            # Durable stores therefore expose a scope-level owner check.  A
            # legacy injected fake may only provide the old teacher callback;
            # that fallback is retained for an empty result and never for a
            # returned manifest.
            self._assert_teacher_for_scope(actor_user_id, scope_id)
            return ProviderDataCallManifestListResponseV1(scope_id=scope_id, items=())

        summaries: list[ProviderDataCallManifestSummaryV1] = []
        for manifest in manifests:
            if not isinstance(manifest, ExportManifestV1):
                raise _blocked("provider_manifest_invalid")
            if (
                manifest.scope_id != scope_id
                or manifest.provider_operation != EMBEDDING_QUERY_OPERATION
            ):
                raise _blocked("provider_manifest_listing_invalid")
            self._assert_teacher_for_manifest_scope(actor_user_id, manifest.manifest_hash)

            # Load the policy explicitly by this immutable manifest's hash.
            # Using the service's configured "current" policy here could turn
            # an otherwise reviewable pending manifest into an accidental
            # cross-row disclosure or hide policy drift incorrectly.
            policy, exact_manifest = self._load(
                policy_ref=manifest.policy_hash,
                manifest_ref=manifest.manifest_hash,
            )
            if exact_manifest != manifest:
                raise _blocked("provider_manifest_listing_invalid")
            try:
                confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
            except Exception as exc:
                raise _blocked("provider_confirmation_unavailable") from exc
            revision = self._revision(manifest)
            turn_id = self._turn_id_for_manifest(manifest.manifest_hash)
            summaries.append(
                ProviderDataCallManifestSummaryV1(
                    manifest_hash=manifest.manifest_hash,
                    turn_id=turn_id,
                    confirmation_revision=revision,
                    confirmed=confirmation is not None
                    and self._confirmation_matches(confirmation, policy, manifest, revision),
                )
            )
        return ProviderDataCallManifestListResponseV1(
            scope_id=scope_id,
            items=tuple(summaries),
        )

    def list_llm_manifests_for_debate(
        self,
        actor_user_id: str,
        *,
        debate_id: str,
    ) -> ProviderDataCallDebateManifestListResponseV1:
        """List exact teacher-visible LLM turn manifests for one Debate.

        Authorization is deliberately resolved before manifest enumeration:
        an existing Debate owned by another course is ``forbidden`` while a
        missing Debate is ``not_found``.  The store is the only component that
        knows the ORM shape; this service consumes its narrow owner/list ports
        so migration 0014 can land independently.
        """

        if not isinstance(debate_id, str) or not _SAFE_OPAQUE_ID_RE.fullmatch(debate_id):
            raise ProviderDisclosureError("not_found", "The Debate was not found.")
        exists = getattr(self.store, "debate_exists", None)
        if not callable(exists):
            raise _blocked("provider_debate_lookup_unavailable")
        try:
            if not bool(exists(debate_id)):
                raise ProviderDisclosureError("not_found", "The Debate was not found.")
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_debate_lookup_unavailable") from exc

        authorizer = getattr(self.store, "is_teacher_for_debate", None)
        if not callable(authorizer):
            raise _blocked("provider_debate_authorization_unavailable")
        try:
            if not bool(authorizer(actor_user_id, debate_id)):
                raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_debate_authorization_unavailable") from exc

        listing = getattr(self.store, "list_export_manifests_for_debate", None)
        if not callable(listing):
            raise _blocked("provider_manifest_listing_unavailable")
        try:
            manifests = tuple(
                listing(
                    debate_id=debate_id,
                    provider_operation=LLM_DEBATE_OPERATION,
                )
            )
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_manifest_listing_unavailable") from exc

        summaries: list[ProviderDataCallDebateManifestSummaryV1] = []
        for manifest in manifests:
            if not isinstance(manifest, ExportManifestV1):
                raise _blocked("provider_manifest_invalid")
            if manifest.provider_operation != LLM_DEBATE_OPERATION:
                raise _blocked("provider_manifest_listing_invalid")
            # An owner-aware store filters by Debate; when the owner fields are
            # exposed by a future domain value, validate them a second time at
            # this boundary to prevent accidental cross-Debate enumeration.
            owner_debate = getattr(manifest, "debate_id", None)
            if owner_debate is not None and str(owner_debate) != debate_id:
                raise _blocked("provider_manifest_listing_invalid")
            self._assert_teacher_for_manifest_scope(actor_user_id, manifest.manifest_hash)
            policy, exact_manifest = self._load(
                policy_ref=manifest.policy_hash,
                manifest_ref=manifest.manifest_hash,
            )
            if exact_manifest != manifest:
                raise _blocked("provider_manifest_listing_invalid")
            try:
                confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
            except Exception as exc:
                raise _blocked("provider_confirmation_unavailable") from exc
            turn_id = self._turn_id_for_manifest(manifest.manifest_hash)
            if not turn_id:
                raise _blocked("provider_manifest_listing_invalid")
            revision = self._revision(manifest)
            summaries.append(
                ProviderDataCallDebateManifestSummaryV1(
                    turn_id=turn_id,
                    manifest_hash=manifest.manifest_hash,
                    confirmation_revision=revision,
                    confirmed=confirmation is not None
                    and self._confirmation_matches(confirmation, policy, manifest, revision),
                )
            )
        summaries.sort(key=lambda item: (item.turn_id, item.manifest_hash))
        return ProviderDataCallDebateManifestListResponseV1(
            debate_id=debate_id,
            items=tuple(summaries),
        )

    # Short aliases keep the integration seam discoverable without creating a
    # second DTO or a second authorization implementation.
    list_debate_llm_manifests = list_llm_manifests_for_debate
    list_llm_turn_manifests = list_llm_manifests_for_debate

    def list_report_manifests_for_debate(
        self,
        actor_user_id: str,
        *,
        debate_id: str,
    ) -> ProviderDataCallReportManifestListResponseV1:
        """List prepared Real Report manifests without exposing operations."""

        if not isinstance(debate_id, str) or not _SAFE_OPAQUE_ID_RE.fullmatch(debate_id):
            raise ProviderDisclosureError("not_found", "The Debate was not found.")
        exists = getattr(self.store, "debate_exists", None)
        authorizer = getattr(self.store, "is_teacher_for_debate", None)
        listing = getattr(self.store, "list_report_manifests_for_debate", None)
        if not callable(exists) or not callable(authorizer) or not callable(listing):
            raise _blocked("provider_report_manifest_listing_unavailable")
        try:
            if not bool(exists(debate_id)):
                raise ProviderDisclosureError("not_found", "The Debate was not found.")
            if not bool(authorizer(actor_user_id, debate_id)):
                raise ProviderDisclosureError("forbidden", "A teacher account is required.")
            manifests = tuple(listing(debate_id=debate_id))
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_report_manifest_listing_unavailable") from exc

        summaries: list[ProviderDataCallReportManifestSummaryV1] = []
        for manifest in manifests:
            if not isinstance(manifest, ExportManifestV1):
                raise _blocked("provider_manifest_invalid")
            if manifest.provider_operation != LLM_REPORT_OPERATION:
                raise _blocked("provider_manifest_listing_invalid")
            policy, exact_manifest = self._load(
                policy_ref=manifest.policy_hash,
                manifest_ref=manifest.manifest_hash,
            )
            if exact_manifest != manifest:
                raise _blocked("provider_manifest_listing_invalid")
            try:
                confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
            except Exception as exc:
                raise _blocked("provider_confirmation_unavailable") from exc
            operation_lookup = getattr(self.store, "get_report_operation_id", None)
            revision_id = (
                str(operation_lookup(manifest.manifest_hash))
                if callable(operation_lookup)
                else None
            )
            if revision_id is not None and not _SAFE_OPAQUE_ID_RE.fullmatch(revision_id):
                raise _blocked("provider_manifest_listing_invalid")
            revision = self._revision(manifest)
            summaries.append(
                ProviderDataCallReportManifestSummaryV1(
                    report_revision_id=revision_id,
                    manifest_hash=manifest.manifest_hash,
                    confirmation_revision=revision,
                    confirmed=confirmation is not None
                    and self._confirmation_matches(confirmation, policy, manifest, revision),
                )
            )
        summaries.sort(key=lambda item: (item.report_revision_id or "", item.manifest_hash))
        return ProviderDataCallReportManifestListResponseV1(
            debate_id=debate_id,
            items=tuple(summaries),
        )

    def list_embedding_manifests_for_agent_version(
        self,
        actor_user_id: str,
        *,
        agent_version_id: str,
    ) -> ProviderDataCallPublicationManifestListResponseV1:
        """List teacher-visible publication manifests for one AgentVersion.

        Publication manifests are durable before the first embedding operation
        is created.  The lookup therefore starts from the exact AgentVersion
        owner relation and never joins ``ProviderOperation``; an unconfirmed
        manifest remains discoverable so the teacher can review and confirm it.
        """

        if not isinstance(agent_version_id, str) or not _SAFE_OPAQUE_ID_RE.fullmatch(
            agent_version_id
        ):
            raise ProviderDisclosureError("not_found", "The requested AgentVersion was not found.")

        exists = getattr(self.store, "agent_version_exists", None)
        if not callable(exists):
            raise _blocked("provider_agent_version_lookup_unavailable")
        try:
            version_exists = bool(exists(agent_version_id))
        except Exception as exc:
            raise _blocked("provider_agent_version_lookup_unavailable") from exc
        if not version_exists:
            raise ProviderDisclosureError("not_found", "The requested AgentVersion was not found.")

        authorizer = getattr(self.store, "is_teacher_for_agent_version", None)
        if not callable(authorizer):
            raise _blocked("provider_manifest_authorization_unavailable")
        try:
            allowed = bool(authorizer(actor_user_id, agent_version_id))
        except Exception as exc:
            raise _blocked("provider_manifest_authorization_unavailable") from exc
        if not allowed:
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")

        list_manifests = getattr(self.store, "list_export_manifests_for_agent_version", None)
        if not callable(list_manifests):
            raise _blocked("provider_manifest_listing_unavailable")
        try:
            manifests = tuple(
                list_manifests(
                    agent_version_id=agent_version_id,
                    provider_operation=EMBEDDING_OPERATION,
                )
            )
        except ProviderDisclosureError:
            raise
        except Exception as exc:
            raise _blocked("provider_manifest_listing_unavailable") from exc

        summaries: list[ProviderDataCallPublicationManifestSummaryV1] = []
        for manifest in manifests:
            if not isinstance(manifest, ExportManifestV1):
                raise _blocked("provider_manifest_invalid")
            if manifest.provider_operation != EMBEDDING_OPERATION:
                raise _blocked("provider_manifest_listing_invalid")

            # Resolve every row by its own immutable policy and manifest hash.
            # This keeps a publication listing correct when the configured
            # current policy has advanced since the manifest was created.
            policy, exact_manifest = self._load(
                policy_ref=manifest.policy_hash,
                manifest_ref=manifest.manifest_hash,
            )
            if exact_manifest != manifest:
                raise _blocked("provider_manifest_listing_invalid")
            try:
                confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
            except Exception as exc:
                raise _blocked("provider_confirmation_unavailable") from exc
            revision = self._revision(manifest)
            summaries.append(
                ProviderDataCallPublicationManifestSummaryV1(
                    manifest_hash=manifest.manifest_hash,
                    confirmation_revision=revision,
                    confirmed=confirmation is not None
                    and self._confirmation_matches(confirmation, policy, manifest, revision),
                )
            )

        summaries.sort(key=lambda item: item.manifest_hash)
        return ProviderDataCallPublicationManifestListResponseV1(
            agent_version_id=agent_version_id,
            items=tuple(summaries),
        )

    # Descriptive alias used by callers that name the operation rather than
    # the underlying AgentVersion lookup.
    list_embedding_publication_manifests = list_embedding_manifests_for_agent_version

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

    def _assert_teacher_for_manifest_scope(self, actor_user_id: str, manifest_hash: str) -> None:
        """Authorize a manifest through its exact course owner relation."""

        if not isinstance(actor_user_id, str) or not actor_user_id.strip():
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        authorizer = getattr(self.store, "is_teacher_for_manifest", None)
        if not callable(authorizer):
            # A generic authorizer is intentionally not sufficient here: the
            # list endpoint must not let a teacher enumerate another course.
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        try:
            allowed = bool(authorizer(actor_user_id, manifest_hash))
        except Exception as exc:
            raise _blocked("provider_manifest_authorization_unavailable") from exc
        if not allowed:
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")

    def _assert_teacher_for_scope(self, actor_user_id: str, scope_id: str) -> None:
        """Authorize an empty listing without widening course visibility."""

        if not isinstance(actor_user_id, str) or not actor_user_id.strip():
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        authorizer = getattr(self.store, "is_teacher_for_scope", None)
        if callable(authorizer):
            try:
                allowed = bool(authorizer(actor_user_id, scope_id))
            except Exception as exc:
                raise _blocked("provider_manifest_authorization_unavailable") from exc
        else:
            # Compatibility for a pre-listing fake store only.  Production
            # SQL stores implement the scope-aware authorizer above.
            allowed = (
                bool(self.teacher_authorizer(actor_user_id)) if self.teacher_authorizer else False
            )
        if not allowed:
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")

    def _turn_id_for_manifest(self, manifest_hash: str) -> str | None:
        """Read only the opaque turn token, when durable ledger metadata has one."""

        resolver = getattr(self.store, "get_turn_id_for_manifest", None)
        if not callable(resolver):
            return None
        try:
            turn_id = resolver(manifest_hash)
        except Exception as exc:
            raise _blocked("provider_manifest_listing_unavailable") from exc
        if turn_id is None:
            return None
        if not isinstance(turn_id, str) or not _SAFE_OPAQUE_ID_RE.fullmatch(turn_id):
            raise _blocked("provider_manifest_listing_invalid")
        return turn_id

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
                # An explicitly selected manifest carries its own immutable
                # policy binding.  Never substitute the store's newest
                # policy (which may belong to another provider operation).
                # Only the legacy no-reference path may use current policy.
                policy = (
                    self.store.get_policy_snapshot(manifest.policy_hash)
                    if resolved_manifest_ref is not None
                    else (
                        current_policy()
                        if callable(current_policy)
                        else self.store.get_policy_snapshot(manifest.policy_hash)
                    )
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
        model_operation = _MODEL_KEYS.get(manifest.provider_operation, manifest.provider_operation)
        if manifest.model_key != authorized_provider_model(model_operation):
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
        agent_version_id: str | None = None,
        publication_manifests: tuple[ExportManifestV1, ...] = (),
        debate_id: str | None = None,
        debate_manifests: tuple[ExportManifestV1, ...] = (),
        turn_ids_by_manifest: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy
        self.manifest = manifest
        self.teacher_ids = frozenset(teacher_ids)
        self.agent_version_id = agent_version_id
        self.publication_manifests = tuple(publication_manifests)
        self.debate_id = debate_id
        self.debate_manifests = tuple(debate_manifests)
        self.turn_ids_by_manifest = dict(turn_ids_by_manifest or {})
        self.manifests: dict[str, ExportManifestV1] = {manifest.manifest_hash: manifest}
        self.manifests.update({item.manifest_hash: item for item in self.publication_manifests})
        self.manifests.update({item.manifest_hash: item for item in self.debate_manifests})
        self.confirmations: dict[str, ExportConfirmationV1] = {}
        self.confirmation_manifest_ids: dict[str, str] = {
            item.manifest_hash: f"manifest-{index}"
            for index, item in enumerate(self.manifests.values(), start=1)
        }
        self._lock = RLock()

    def get_policy_snapshot(self, reference: str | None = None) -> ProviderPolicySnapshotV1 | None:
        if reference is None or reference in {self.policy.policy_id, self.policy.policy_hash}:
            return self.policy
        return None

    def get_current_policy_snapshot(self) -> ProviderPolicySnapshotV1:
        return self.policy

    def get_export_manifest(self, reference: str | None = None) -> ExportManifestV1 | None:
        if reference is None:
            return self.manifest
        if reference in {self.manifest.scope_id, self.manifest.manifest_hash}:
            return self.manifest
        return self.manifests.get(reference)

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
        manifest = self.manifests.get(confirmation.manifest_hash)
        if manifest is None or expected_revision != manifest.operation_revision:
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
        return user_id in self.teacher_ids and manifest_hash in self.manifests

    def is_teacher_for_scope(self, user_id: str, scope_id: str) -> bool:
        return (
            user_id in self.teacher_ids
            and self.manifest.scope_id == scope_id
            and self.manifest.provider_operation == EMBEDDING_QUERY_OPERATION
        )

    def agent_version_exists(self, agent_version_id: str) -> bool:
        return self.agent_version_id == agent_version_id

    def is_teacher_for_agent_version(self, user_id: str, agent_version_id: str) -> bool:
        return user_id in self.teacher_ids and self.agent_version_id == agent_version_id

    def list_export_manifests(
        self,
        *,
        scope_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        if (
            self.manifest.scope_id != scope_id
            or self.manifest.provider_operation != provider_operation
        ):
            return ()
        return (self.manifest,)

    def list_export_manifests_for_agent_version(
        self,
        *,
        agent_version_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        if self.agent_version_id != agent_version_id:
            return ()
        candidates = (self.manifest, *self.publication_manifests)
        seen: set[str] = set()
        manifests: list[ExportManifestV1] = []
        for item in candidates:
            if item.provider_operation != provider_operation or item.manifest_hash in seen:
                continue
            seen.add(item.manifest_hash)
            manifests.append(item)
        return tuple(manifests)

    def list_report_manifests_for_debate(
        self,
        *,
        debate_id: str,
    ) -> tuple[ExportManifestV1, ...]:
        candidates = (self.manifest, *self.debate_manifests)
        return tuple(
            item
            for item in candidates
            if item.provider_operation == LLM_REPORT_OPERATION
            and (
                item.scope_id == debate_id or getattr(item, "debate_id", None) in {None, debate_id}
            )
        )

    def get_report_operation_id(self, manifest_hash: str) -> str | None:
        """Optional fake hook for exposing only the report revision token."""

        return self.turn_ids_by_manifest.get(manifest_hash)

    def get_turn_id_for_manifest(self, manifest_hash: str) -> str | None:
        explicit = self.turn_ids_by_manifest.get(manifest_hash)
        if explicit is not None:
            return explicit
        manifest = self.manifests.get(manifest_hash)
        value = getattr(manifest, "turn_id", None) if manifest is not None else None
        return str(value) if value else None

    def debate_exists(self, debate_id: str) -> bool:
        if self.debate_id == debate_id:
            return True
        return any(getattr(item, "debate_id", None) == debate_id for item in self.debate_manifests)

    def is_teacher_for_debate(self, user_id: str, debate_id: str) -> bool:
        return user_id in self.teacher_ids and self.debate_exists(debate_id)

    def list_export_manifests_for_debate(
        self,
        *,
        debate_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        if self.debate_id != debate_id and not any(
            getattr(item, "debate_id", None) == debate_id for item in self.debate_manifests
        ):
            return ()
        values = self.debate_manifests
        if not values and self.debate_id == debate_id:
            values = (self.manifest,)
        # A fake may use one explicit debate id for all supplied manifests;
        # otherwise honor a future value-level owner field when available.
        return tuple(
            item
            for item in values
            if item.provider_operation == provider_operation
            and (
                getattr(item, "debate_id", None) is None
                or getattr(item, "debate_id", None) == debate_id
            )
        )

    def replace_current(
        self,
        policy: ProviderPolicySnapshotV1,
        manifest: ExportManifestV1,
    ) -> None:
        with self._lock:
            self.policy = policy
            self.manifest = manifest
            self.manifests[manifest.manifest_hash] = manifest
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

    def agent_version_exists(self, agent_version_id: str) -> bool:
        return (
            self.db.scalar(select(AgentVersion.id).where(AgentVersion.id == agent_version_id))
            is not None
        )

    def is_teacher_for_agent_version(self, user_id: str, agent_version_id: str) -> bool:
        """Authorize through the exact AgentVersion -> course ownership chain."""

        return (
            self.db.scalar(
                select(AgentVersion.id)
                .join(Agent, Agent.id == AgentVersion.agent_id)
                .join(Group, Group.id == Agent.group_id)
                .join(CourseMember, CourseMember.course_id == Group.course_id)
                .where(
                    AgentVersion.id == agent_version_id,
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

    def is_teacher_for_scope(self, user_id: str, scope_id: str) -> bool:
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
                    ProviderExportManifest.scope_id == scope_id,
                    ProviderExportManifest.provider_operation == EMBEDDING_QUERY_OPERATION,
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

    def list_export_manifests(
        self,
        *,
        scope_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Load only the hash/model-independent domain rows for one scope."""

        hashes = self.db.scalars(
            select(ProviderExportManifest.manifest_hash)
            .where(
                ProviderExportManifest.scope_id == scope_id,
                ProviderExportManifest.provider_operation == provider_operation,
            )
            .order_by(
                ProviderExportManifest.created_at.asc(),
                ProviderExportManifest.manifest_hash.asc(),
            )
        ).all()
        manifests: list[ExportManifestV1] = []
        for manifest_hash in hashes:
            try:
                manifest = self._control.get_export_manifest(str(manifest_hash))
            except Exception as exc:
                raise ProviderDisclosureStoreError("provider manifest row is invalid") from exc
            if manifest is None:
                raise ProviderDisclosureStoreError("provider manifest row is missing")
            manifests.append(manifest)
        return tuple(manifests)

    def list_export_manifests_for_agent_version(
        self,
        *,
        agent_version_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Load only owner-bound manifests for one AgentVersion.

        The query intentionally does not join ``ProviderOperation``.  The
        publication manifest is persisted before its first embedding batch,
        so requiring an operation row would hide the exact unconfirmed item a
        teacher must discover and review.
        """

        hashes = self.db.scalars(
            select(ProviderExportManifest.manifest_hash)
            .join(
                AgentVersion,
                AgentVersion.id == ProviderExportManifest.agent_version_id,
            )
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .join(Group, Group.id == Agent.group_id)
            .where(
                ProviderExportManifest.agent_version_id == agent_version_id,
                ProviderExportManifest.provider_operation == provider_operation,
                ProviderExportManifest.course_id.is_not(None),
                ProviderExportManifest.group_id.is_not(None),
                ProviderExportManifest.agent_version_id.is_not(None),
                ProviderExportManifest.group_id == Agent.group_id,
                ProviderExportManifest.course_id == Group.course_id,
            )
            .order_by(
                ProviderExportManifest.created_at.asc(),
                ProviderExportManifest.manifest_hash.asc(),
            )
        ).all()
        manifests: list[ExportManifestV1] = []
        for manifest_hash in hashes:
            try:
                manifest = self._control.get_export_manifest(str(manifest_hash))
            except Exception as exc:
                raise ProviderDisclosureStoreError("provider manifest row is invalid") from exc
            if manifest is None:
                raise ProviderDisclosureStoreError("provider manifest row is missing")
            manifests.append(manifest)
        return tuple(manifests)

    def list_report_manifests_for_debate(
        self,
        *,
        debate_id: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Load Real Report manifests by their Debate scope.

        Report manifests intentionally have no Debate/Turn owner pair: a
        report revision is not a turn.  The immutable Debate scope plus the
        exact course authorization above is the narrow discovery boundary.
        """

        hashes = self.db.scalars(
            select(ProviderExportManifest.manifest_hash)
            .where(
                ProviderExportManifest.scope_id == debate_id,
                ProviderExportManifest.provider_operation == LLM_REPORT_OPERATION,
            )
            .order_by(
                ProviderExportManifest.created_at.asc(),
                ProviderExportManifest.manifest_hash.asc(),
            )
        ).all()
        manifests: list[ExportManifestV1] = []
        for manifest_hash in hashes:
            try:
                manifest = self._control.get_export_manifest(str(manifest_hash))
            except Exception as exc:
                raise ProviderDisclosureStoreError(
                    "provider report manifest row is invalid"
                ) from exc
            if manifest is None or manifest.provider_operation != LLM_REPORT_OPERATION:
                raise ProviderDisclosureStoreError("provider report manifest row is missing")
            manifests.append(manifest)
        return tuple(manifests)

    def get_report_operation_id(self, manifest_hash: str) -> str | None:
        """Return the opaque report revision token for disclosure only."""

        return self.db.scalar(
            select(ProviderOperation.logical_item_id)
            .where(
                ProviderOperation.provider_operation == LLM_REPORT_OPERATION,
                ProviderOperation.export_manifest_hash == manifest_hash,
            )
            .order_by(ProviderOperation.created_at.asc(), ProviderOperation.id.asc())
            .limit(1)
        )

    def get_turn_id_for_manifest(self, manifest_hash: str) -> str | None:
        # Migration 0014 gives LLM manifests a direct Turn owner.  Resolve it
        # without importing the future ORM field at module import time so this
        # adapter remains readable against the 0001-0013 test schema.
        turn_column = getattr(ProviderExportManifest, "turn_id", None)
        operation_column = getattr(ProviderExportManifest, "provider_operation", None)
        if turn_column is not None and operation_column is not None:
            direct = self.db.scalar(
                select(turn_column).where(
                    ProviderExportManifest.manifest_hash == manifest_hash,
                    operation_column == LLM_DEBATE_OPERATION,
                )
            )
            if direct is not None:
                value = str(direct)
                return value if _SAFE_OPAQUE_ID_RE.fullmatch(value) else None
        row = self.db.scalar(
            select(ProviderOperation.logical_item_id)
            .join(
                ProviderExportManifest,
                ProviderExportManifest.manifest_hash == ProviderOperation.export_manifest_hash,
            )
            .where(
                ProviderOperation.provider_operation.in_(
                    (EMBEDDING_QUERY_OPERATION, LLM_DEBATE_OPERATION)
                ),
                ProviderOperation.export_manifest_hash == manifest_hash,
                ProviderOperation.scope_id == ProviderExportManifest.scope_id,
            )
            .order_by(ProviderOperation.created_at.asc(), ProviderOperation.id.asc())
            .limit(1)
        )
        value = str(row) if row is not None else ""
        if value.startswith("turn:") and value[5:]:
            return value[5:]
        return None

    def debate_exists(self, debate_id: str) -> bool:
        """Check one Debate identity without revealing another course's rows."""

        from app.modules.debates.models import Debate

        return self.db.scalar(select(Debate.id).where(Debate.id == debate_id)) is not None

    def is_teacher_for_debate(self, user_id: str, debate_id: str) -> bool:
        """Authorize a teacher through the exact Debate -> Course edge."""

        from app.modules.debates.models import Debate

        return (
            self.db.scalar(
                select(CourseMember.user_id)
                .join(Debate, Debate.course_id == CourseMember.course_id)
                .where(
                    Debate.id == debate_id,
                    CourseMember.user_id == user_id,
                    CourseMember.role == "teacher",
                )
            )
            is not None
        )

    def list_export_manifests_for_debate(
        self,
        *,
        debate_id: str,
        provider_operation: str,
    ) -> tuple[ExportManifestV1, ...]:
        """Load LLM manifests using migration-0014's direct Debate owner."""

        debate_column = getattr(ProviderExportManifest, "debate_id", None)
        operation_column = getattr(ProviderExportManifest, "provider_operation", None)
        if debate_column is None or operation_column is None:
            # A pre-0014 database cannot prove Turn -> Debate ownership and
            # must fail closed rather than treating scope_id as an owner.
            return ()
        hashes = self.db.scalars(
            select(ProviderExportManifest.manifest_hash)
            .where(
                debate_column == debate_id,
                operation_column == provider_operation,
            )
            .order_by(
                ProviderExportManifest.created_at.asc(),
                ProviderExportManifest.manifest_hash.asc(),
            )
        ).all()
        manifests: list[ExportManifestV1] = []
        for manifest_hash in hashes:
            try:
                manifest = self._control.get_export_manifest(str(manifest_hash))
            except Exception as exc:
                raise ProviderDisclosureStoreError("provider manifest row is invalid") from exc
            if manifest is None:
                raise ProviderDisclosureStoreError("provider manifest row is missing")
            owner_debate = getattr(manifest, "debate_id", None)
            if owner_debate is not None and str(owner_debate) != debate_id:
                raise ProviderDisclosureStoreError("provider manifest Debate owner is invalid")
            manifests.append(manifest)
        return tuple(manifests)


__all__ = [
    "EMBEDDING_OPERATION",
    "EMBEDDING_QUERY_OPERATION",
    "LLM_DEBATE_OPERATION",
    "LLM_REPORT_OPERATION",
    "InMemoryProviderDisclosureStore",
    "PROVIDER_DISCLOSURE_VERSION",
    "ProviderDisclosureError",
    "ProviderDisclosureService",
    "ProviderDisclosureStore",
    "ProviderDisclosureStoreError",
    "SqlAlchemyProviderDisclosureStore",
]
