"""Teacher-only ProviderDataCallV1 disclosure and confirmation service.

This module is a deliberately small seam between the public teacher screen and
the server-only provider-control ledger.  It never selects a provider and
never performs network I/O.  A main-window adapter supplies the durable policy,
manifest and confirmation rows through :class:`ProviderDisclosureStore`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.links import live_link
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    KnowledgeSnapshot,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    ProviderPolicySnapshot,
)
from app.modules.agents.markdown import markdown_hash
from app.modules.knowledge.providers.query_embedding import persisted_snapshot_identity
from app.modules.knowledge.services import (
    can_invoke_version,
    scoped_group_role_for_user,
    snapshot_sources_are_readable,
)
from app.modules.knowledge.vector import REAL_EMBEDDING_IDENTITY
from app.modules.knowledge_sets.generation import _current_generation_authorized
from app.modules.knowledge_sets.models import KnowledgeGenerationRun, KnowledgeSet
from app.providers.control import (
    ALLOWED_ACCOUNT_PRODUCTS,
    FIXED_MODELS,
    FIXED_REGION,
    ExportConfirmationV1,
    ExportFieldV1,
    ExportManifestV1,
    ProviderControlError,
    ProviderPolicySnapshotV1,
    ProviderPreflightV1,
    authorized_provider_model,
    canonical_json_bytes,
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

LOGGER = logging.getLogger(__name__)

PROVIDER_DISCLOSURE_VERSION = "ProviderDataCallV1"
SUPPLIER_DISPLAY_NAME = "Alibaba Cloud Model Studio"
STORAGE_FACT = "The supplier stores call data as required by applicable law."
EMBEDDING_OPERATION = "embedding"
EMBEDDING_QUERY_OPERATION = "embedding_query"
LLM_DEBATE_OPERATION = "llm_debate_turn"
LLM_REPORT_OPERATION = "llm_maya_report"
LLM_KNOWLEDGE_OPERATION = "llm_knowledge_generate"
TEAM_RESULT_SCOPE_PREFIX = "team-result:"
CHAT_STANDING_SCOPE_PREFIX = "chat-course:"
CHAT_STANDING_FIELD_CLASSES = (
    "authorized_courseware_text",
    "private_conversation_messages",
    "teacher_agent_instructions",
    "topic_and_platform_rules",
)
CHAT_STANDING_OPERATION_FIELD_CLASSES: Mapping[str, tuple[str, ...]] = {
    "llm_agent_chat": CHAT_STANDING_FIELD_CLASSES,
    "embedding_query": ("current_evidence_excerpt",),
}


def chat_field_classes_hash(field_classes: tuple[str, ...]) -> str:
    """Hash a closed, order-independent set of outbound Chat disclosure classes."""

    canonical = json.dumps(sorted(set(field_classes)), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def confirm_chat_manifest_from_standing_grant(
    db: Session,
    manifest: ExportManifestV1,
    *,
    actor_user_id: str,
    conversation_id: str,
    turn_id: str,
    claim_revision: int | None = None,
    current_policy_hash: str | None = None,
    operator_consent: bool = False,
) -> bool:
    """Persist exact Chat consent under the current operation's course grant."""

    return SqlAlchemyProviderDisclosureStore(db).confirm_chat_manifest_from_standing_grant(
        manifest,
        actor_user_id=actor_user_id,
        conversation_id=conversation_id,
        turn_id=turn_id,
        claim_revision=claim_revision,
        current_policy_hash=current_policy_hash,
        operator_consent=operator_consent,
    )


def prepare_chat_standing_disclosure(
    db: Session,
    *,
    actor_user_id: str,
    course_id: str,
    policy_hash: str,
    provider_operation: Literal["llm_agent_chat", "embedding_query"] = "llm_agent_chat",
) -> ProviderDataCallDisclosureResponseV1:
    """Build one static course Chat or retrieval disclosure without Chat data."""

    manifest = _ensure_chat_standing_manifest(
        db,
        course_id=course_id,
        policy_hash=policy_hash,
        provider_operation=provider_operation,
    )
    service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
    return service.disclose(
        actor_user_id,
        policy_ref=policy_hash,
        manifest_ref=manifest.manifest_hash,
    )


def _ensure_chat_standing_manifest(
    db: Session,
    *,
    course_id: str,
    policy_hash: str,
    provider_operation: Literal["llm_agent_chat", "embedding_query"] = "llm_agent_chat",
) -> ExportManifestV1:
    repository = ProviderRepository(db)
    policy = repository.get_policy_snapshot(policy_hash)
    policy_id = db.scalar(
        select(ProviderPolicySnapshot.id).where(ProviderPolicySnapshot.policy_hash == policy_hash)
    )
    if policy is None or policy_id is None or policy.policy_hash != policy_hash:
        raise ProviderDisclosureError(
            "provider_policy_unavailable", "The reviewed Provider policy is unavailable."
        )
    field_classes = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(provider_operation)
    if field_classes is None:
        raise ProviderDisclosureError(
            "provider_operation_invalid", "This Provider operation is unavailable."
        )
    field_salt = (
        "maya-chat-standing-v1"
        if provider_operation == "llm_agent_chat"
        else "maya-team-query-standing-v1"
    )
    field_values = tuple(
        ExportFieldV1(
            field_class,
            hashlib.sha256(f"{field_salt}:{field_class}".encode()).hexdigest(),
        )
        for field_class in field_classes
    )
    model_key = authorized_provider_model(provider_operation)
    if model_key is None:
        raise ProviderDisclosureError(
            "provider_model_invalid", "The Provider model is unavailable."
        )
    contract = {
        "contract": (
            "maya-chat-course-standing-v1"
            if provider_operation == "llm_agent_chat"
            else "maya-team-query-standing-v1"
        ),
        "policy_hash": policy_hash,
        "field_classes": list(field_classes),
    }
    manifest = ExportManifestV1(
        scope_id=f"{CHAT_STANDING_SCOPE_PREFIX}{course_id}",
        provider_operation=provider_operation,
        model_key=model_key,
        policy_hash=policy_hash,
        build_manifest_hash=hashlib.sha256(canonical_json_bytes(contract)).hexdigest(),
        persona_spec_hash=hashlib.sha256(b"maya-chat-course-standing-v1").hexdigest(),
        fields=field_values,
        max_total_tokens=0,
        max_cost_cny=0.0,
    )
    repository.ensure_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=course_id,
        group_id=None,
        agent_version_id=None,
    )
    return manifest


def single_chat_consent_is_current(
    connection: Any,
    *,
    manifest_hash: str,
    conversation_id: str,
    actor_user_id: str,
    course_id: str,
    policy_hash: str,
    field_classes: tuple[str, ...],
    provider_operation: Literal["llm_agent_chat", "embedding_query"] = "llm_agent_chat",
) -> bool:
    """Recheck a recorded Chat consent at stage creation and Provider send."""

    from app.core.models import (
        CourseMember,
        ProviderExportConfirmation,
        ProviderExportManifest,
        User,
    )
    from app.modules.workspace.models import (
        ChatProviderConsentBinding,
        ChatProviderStandingGrant,
        Conversation,
    )

    binding_table = ChatProviderConsentBinding.__table__
    binding = (
        connection.execute(
            select(binding_table).where(binding_table.c.manifest_hash == manifest_hash)
        )
        .mappings()
        .first()
    )
    expected_fields = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(provider_operation)
    if expected_fields is None or tuple(sorted(set(field_classes))) != tuple(
        sorted(expected_fields)
    ):
        return False
    conversation_table = Conversation.__table__
    current = (
        connection.execute(
            select(conversation_table.c.user_id, conversation_table.c.course_id).where(
                conversation_table.c.entry_kind == "agent",
                conversation_table.c.id == conversation_id,
                conversation_table.c.withdrawn_at.is_(None),
            )
        )
        .mappings()
        .first()
    )
    course_member_table = CourseMember.__table__
    active_owner = connection.execute(
        select(User.__table__.c.id)
        .join(
            course_member_table,
            course_member_table.c.user_id == User.__table__.c.id,
        )
        .where(
            User.__table__.c.id == actor_user_id,
            User.__table__.c.status == "active",
            course_member_table.c.course_id == course_id,
            course_member_table.c.role.in_(("student", "teacher")),
        )
    ).first()
    if (
        current is None
        or current["user_id"] != actor_user_id
        or current["course_id"] != course_id
        or active_owner is None
    ):
        return False
    if binding is None:
        return provider_operation == "llm_agent_chat"

    classes_hash = chat_field_classes_hash(field_classes)
    confirm_table = ProviderExportConfirmation.__table__
    confirmation = connection.execute(
        select(confirm_table.c.id).where(
            confirm_table.c.id == binding["confirmation_id"],
            confirm_table.c.manifest_hash == manifest_hash,
            confirm_table.c.policy_hash == policy_hash,
        )
    ).first()
    manifest_table = ProviderExportManifest.__table__
    manifest = connection.execute(
        select(manifest_table.c.manifest_hash).where(
            manifest_table.c.manifest_hash == manifest_hash,
            manifest_table.c.scope_id == conversation_id,
            manifest_table.c.course_id == course_id,
            manifest_table.c.policy_hash == policy_hash,
            manifest_table.c.provider_operation == provider_operation,
        )
    ).first()
    teacher = connection.execute(
        select(User.__table__.c.id)
        .join(
            course_member_table,
            course_member_table.c.user_id == User.__table__.c.id,
        )
        .where(
            User.__table__.c.id == binding["confirmed_by_user_id"],
            User.__table__.c.status == "active",
            course_member_table.c.course_id == course_id,
            course_member_table.c.role == "teacher",
        )
    ).first()
    if (
        binding["conversation_id"] != conversation_id
        or binding["course_id"] != course_id
        or binding["actor_user_id"] != actor_user_id
        or confirmation is None
        or manifest is None
        or teacher is None
        or (provider_operation == "embedding_query" and active_owner is None)
    ):
        return False
    grant_id = binding["standing_grant_id"]
    if grant_id is None:
        return provider_operation == "llm_agent_chat"
    grant_table = ChatProviderStandingGrant.__table__
    grant = (
        connection.execute(
            select(grant_table).where(
                grant_table.c.id == grant_id,
                grant_table.c.course_id == course_id,
                grant_table.c.provider_operation == provider_operation,
                grant_table.c.policy_hash == policy_hash,
                grant_table.c.field_classes_hash == classes_hash,
                grant_table.c.confirmed_by_user_id == binding["confirmed_by_user_id"],
                grant_table.c.revoked_at.is_(None),
            )
        )
        .mappings()
        .first()
    )
    if grant is None:
        return False
    try:
        persisted_classes = tuple(json.loads(grant["field_classes_json"]))
    except (json.JSONDecodeError, TypeError, ValueError):
        return False
    return persisted_classes == tuple(sorted(set(field_classes)))


_PURPOSES: Mapping[str, str] = {
    "llm_agent_chat": (
        "Generate a reply from the selected Team member using the authorized "
        "conversation and teaching material."
    ),
    "embedding": "Build an evidence search index from an approved immutable snapshot.",
    "embedding_query": (
        "Embed approved retrieval questions to search one immutable evidence snapshot."
    ),
    "llm_debate": "Generate the teacher-approved classroom debate speech.",
    "llm_debate_turn": "Generate the teacher-approved classroom debate speech.",
    "llm_maya_report": "Generate the teacher-approved civilization mutual-learning report.",
    LLM_KNOWLEDGE_OPERATION: (
        "Derive editable teaching concepts, questions with rubrics, and notes "
        "from the selected teaching instructions and courseware."
    ),
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
        self._assert_teacher(
            actor_user_id,
            manifest.manifest_hash,
            provider_operation=manifest.provider_operation,
            scope_id=manifest.scope_id,
        )
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
        if scope_id.startswith(TEAM_RESULT_SCOPE_PREFIX):
            raise ProviderDisclosureError("forbidden", "The provider export scope is unavailable.")
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
        self._assert_teacher(
            actor_user_id,
            manifest.manifest_hash,
            provider_operation=manifest.provider_operation,
            scope_id=manifest.scope_id,
        )
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
                self._bind_team_consent(actor_user_id, manifest)
                self._bind_chat_consent(actor_user_id, manifest)
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
            self._bind_team_consent(actor_user_id, manifest)
            self._bind_chat_consent(actor_user_id, manifest)
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
                self._bind_chat_consent(actor_user_id, manifest)
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
        self._assert_teacher(
            actor_user_id,
            manifest.manifest_hash,
            provider_operation=manifest.provider_operation,
            scope_id=manifest.scope_id,
        )
        revision = self._revision(manifest)
        try:
            confirmation = self.store.get_export_confirmation(manifest.manifest_hash)
        except ProviderDisclosureStoreError as exc:
            raise _blocked("provider_confirmation_unavailable") from exc
        if confirmation is None or not self._confirmation_matches(
            confirmation, policy, manifest, revision
        ):
            raise ProviderDisclosureError(
                "provider_confirmation_unavailable",
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

    def _bind_team_consent(self, actor_user_id: str, manifest: ExportManifestV1) -> None:
        if not manifest.scope_id.startswith(TEAM_RESULT_SCOPE_PREFIX):
            return
        bind = getattr(self.store, "bind_team_confirmation", None)
        if not callable(bind):
            raise _blocked("provider_confirmation_unavailable")
        bind(actor_user_id, manifest.manifest_hash)

    def _bind_chat_consent(self, actor_user_id: str, manifest: ExportManifestV1) -> None:
        if manifest.provider_operation in {
            "llm_agent_chat",
            EMBEDDING_QUERY_OPERATION,
        } and manifest.scope_id.startswith(CHAT_STANDING_SCOPE_PREFIX):
            bind_standing = getattr(self.store, "bind_chat_standing_confirmation", None)
            if not callable(bind_standing):
                raise _blocked("provider_confirmation_unavailable")
            bind_standing(actor_user_id, manifest.manifest_hash)
            return
        if manifest.provider_operation != "llm_agent_chat":
            return
        if manifest.scope_id.startswith(TEAM_RESULT_SCOPE_PREFIX):
            return
        bind = getattr(self.store, "bind_chat_confirmation", None)
        if not callable(bind):
            return
        bind(actor_user_id, manifest.manifest_hash)

    def _assert_teacher(
        self, actor_user_id: str, manifest_hash: str, *, provider_operation: str, scope_id: str
    ) -> None:
        if provider_operation in {LLM_KNOWLEDGE_OPERATION, "llm_agent_chat"} or scope_id.startswith(
            TEAM_RESULT_SCOPE_PREFIX
        ):
            self._assert_teacher_for_manifest_scope(actor_user_id, manifest_hash)
            return
        if provider_operation == EMBEDDING_QUERY_OPERATION:
            if scope_id.startswith(CHAT_STANDING_SCOPE_PREFIX):
                self._assert_teacher_for_manifest_scope(actor_user_id, manifest_hash)
                return
            self._assert_teacher_for_query_scope(actor_user_id, scope_id)
            return
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

    def _assert_teacher_for_query_scope(self, actor_user_id: str, scope_id: str) -> None:
        """Authorize a non-Chat query scope through its exact owning course."""

        if (
            not isinstance(actor_user_id, str)
            or not actor_user_id.strip()
            or scope_id.startswith((CHAT_STANDING_SCOPE_PREFIX, TEAM_RESULT_SCOPE_PREFIX))
        ):
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        authorizer = getattr(self.store, "is_teacher_for_scope", None)
        if not callable(authorizer):
            raise ProviderDisclosureError("forbidden", "A teacher account is required.")
        try:
            allowed = bool(authorizer(actor_user_id, scope_id))
        except Exception as exc:
            raise _blocked("provider_manifest_authorization_unavailable") from exc
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

    def _is_knowledge_owner_for_manifest(
        self, user_id: str, manifest: ProviderExportManifest
    ) -> bool:
        run = self.db.scalar(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.id == manifest.scope_id,
                KnowledgeGenerationRun.provider_manifest_hash == manifest.manifest_hash,
                KnowledgeGenerationRun.owner_user_id == user_id,
                KnowledgeGenerationRun.course_id == manifest.course_id,
                KnowledgeGenerationRun.agent_version_id == manifest.agent_version_id,
            )
        )
        if run is None:
            return False
        agent = self.db.get(Agent, run.agent_id)
        set_row = self.db.get(KnowledgeSet, run.knowledge_set_id)
        if (
            agent is None
            or set_row is None
            or manifest.group_id != agent.group_id
            or manifest.debate_id is not None
            or manifest.turn_id is not None
        ):
            return False
        # A course Teacher outside a Group has only its public summary view,
        # which cannot authorize writes to that Group's generation target.
        if set_row.ownership_scope == "group" and (
            set_row.group_id is None
            or scoped_group_role_for_user(self.db, user_id, set_row.group_id) != "student"
        ):
            return False
        return _current_generation_authorized(self.db, run)

    def _is_team_confirmer_for_manifest(
        self, user_id: str, manifest: ProviderExportManifest
    ) -> bool:
        from app.core.errors import PlatformError
        from app.core.models import User
        from app.modules.teams.models import CourseTeamPublication, TeamMemberInvokeGrant
        from app.modules.teams.service import resolve_frozen_chat_selection
        from app.modules.workspace.models import (
            Conversation,
            ConversationParticipant,
            ConversationTurn,
            TeamTurnResult,
        )
        from app.modules.workspace.schemas import TeamRouting
        from app.modules.workspace.team_conversation import frozen_team_selection

        if manifest.provider_operation not in {"llm_agent_chat", EMBEDDING_QUERY_OPERATION}:
            return False
        try:
            result_id = str(UUID(manifest.scope_id.removeprefix(TEAM_RESULT_SCOPE_PREFIX)))
        except ValueError:
            return False
        result = self.db.get(TeamTurnResult, result_id)
        if result is None:
            return False
        conversation = self.db.get(Conversation, result.conversation_id)
        participant = self.db.get(ConversationParticipant, result.participant_id)
        turn = self.db.get(ConversationTurn, result.turn_id)
        confirmer = self.db.get(User, user_id)
        if (
            conversation is None
            or participant is None
            or turn is None
            or confirmer is None
            or confirmer.status != "active"
            or conversation.entry_kind not in {"team", "maya_team"}
            or turn.conversation_id != conversation.id
            or participant.conversation_id != conversation.id
            or participant.team_version_id != conversation.team_version_id
            or manifest.course_id != conversation.course_id
            or manifest.agent_version_id != participant.agent_version_id
            or manifest.debate_id is not None
            or manifest.turn_id is not None
        ):
            return False
        role = self.db.scalar(
            select(CourseMember.role).where(
                CourseMember.course_id == conversation.course_id,
                CourseMember.user_id == user_id,
            )
        )
        publication = (
            self.db.get(CourseTeamPublication, conversation.publication_id)
            if conversation.publication_id is not None
            else None
        )
        chat_owner = self.db.get(User, conversation.user_id)
        agent = self.db.get(Agent, participant.agent_id)
        agent_version = self.db.get(AgentVersion, participant.agent_version_id)
        if (
            chat_owner is None
            or chat_owner.status != "active"
            or agent is None
            or agent_version is None
            or agent_version.agent_id != participant.agent_id
            or agent_version.knowledge_snapshot_id != participant.snapshot_id
            or agent.authorization_epoch != participant.agent_authorization_epoch
            or manifest.group_id != agent.group_id
        ):
            return False
        if conversation.entry_kind == "team":
            if (
                conversation.origin != "custom_team"
                or conversation.publication_id is not None
                or conversation.user_id != user_id
                or role is None
            ):
                return False
            try:
                routing = TeamRouting.model_validate_json(turn.routing_json or "{}")
                participants = list(
                    self.db.scalars(
                        select(ConversationParticipant).where(
                            ConversationParticipant.conversation_id == conversation.id
                        )
                    )
                )
                requested = {str(value) for value in routing.participant_ids}
                selected = (
                    [member for member in participants if member.id in requested]
                    if routing.mode == "selected"
                    else participants
                )
                if (
                    not selected
                    or participant.id not in {member.id for member in selected}
                    or any(member.invoke_grant_id is not None for member in selected)
                    or (routing.mode == "selected" and len(selected) != len(requested))
                ):
                    return False
                for member in selected:
                    current_agent = self.db.get(Agent, member.agent_id)
                    current_version = self.db.get(AgentVersion, member.agent_version_id)
                    if (
                        current_agent is None
                        or current_version is None
                        or current_version.agent_id != member.agent_id
                        or current_version.knowledge_snapshot_id != member.snapshot_id
                        or current_agent.authorization_epoch != member.agent_authorization_epoch
                    ):
                        return False
                # A Custom Chat owner confirms only their own currently readable
                # inputs. Team authorship never supplies the confirmer's role.
                resolve_frozen_chat_selection(
                    self.db,
                    user_id,
                    frozen_team_selection(self.db, conversation),
                    {live_link(member.team_member_id, "Team member") for member in selected},
                )
            except (PlatformError, ValueError, TypeError):
                return False
            return True
        grant = (
            self.db.get(TeamMemberInvokeGrant, participant.invoke_grant_id)
            if participant.invoke_grant_id
            else None
        )
        if (
            role != "teacher"
            or conversation.origin != "published_course_team"
            or publication is None
            or grant is None
            or publication.publisher_user_id != user_id
            or conversation.team_owner_user_id != user_id
            or publication.course_id != conversation.course_id
            or publication.team_id != conversation.team_id
            or publication.team_version_id != conversation.team_version_id
            or publication.authorization_epoch != conversation.publication_epoch
            or publication.state not in {"published", "retained"}
            or grant.publication_id != publication.id
            or grant.team_version_id != conversation.team_version_id
            or grant.team_member_id != participant.team_member_id
            or grant.agent_id != participant.agent_id
            or grant.agent_version_id != participant.agent_version_id
            or grant.authorization_epoch != conversation.team_authorization_epoch
        ):
            return False
        try:
            # Consent belongs to the publisher, but invocation rights and data
            # remain scoped to the real Chat owner, never the Teacher's role.
            resolve_frozen_chat_selection(
                self.db,
                conversation.user_id,
                frozen_team_selection(self.db, conversation),
                {participant.team_member_id},
            )
        except (PlatformError, ValueError, TypeError):
            return False
        return True

    def _is_chat_confirmer_for_manifest(
        self, user_id: str, manifest: ProviderExportManifest
    ) -> bool:
        from app.core.models import User
        from app.modules.knowledge.services import can_invoke_version
        from app.modules.workspace.models import Conversation

        expected_fields = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(manifest.provider_operation)
        if expected_fields is None:
            return False
        if manifest.scope_id.startswith(CHAT_STANDING_SCOPE_PREFIX):
            scoped_course_id = manifest.scope_id.removeprefix(CHAT_STANDING_SCOPE_PREFIX)
            try:
                UUID(scoped_course_id)
                fields = tuple(
                    sorted(
                        {
                            item["field_class"]
                            for item in json.loads(manifest.fields_json)
                            if isinstance(item, dict)
                        }
                    )
                )
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return False
            confirmer = self.db.get(User, user_id)
            return bool(
                scoped_course_id == manifest.course_id
                and manifest.group_id is None
                and manifest.agent_version_id is None
                and manifest.debate_id is None
                and manifest.turn_id is None
                and fields == tuple(sorted(expected_fields))
                and confirmer is not None
                and confirmer.status == "active"
                and self.db.scalar(
                    select(CourseMember.user_id).where(
                        CourseMember.course_id == scoped_course_id,
                        CourseMember.user_id == user_id,
                        CourseMember.role == "teacher",
                    )
                )
                is not None
            )
        if manifest.provider_operation != "llm_agent_chat":
            return False
        if manifest.scope_id.startswith(TEAM_RESULT_SCOPE_PREFIX):
            return False
        try:
            conversation_id = str(UUID(manifest.scope_id))
        except ValueError:
            return False
        conversation = self.db.get(Conversation, conversation_id)
        confirmer = self.db.get(User, user_id)
        if (
            conversation is None
            or confirmer is None
            or confirmer.status != "active"
            or conversation.entry_kind != "agent"
            or conversation.withdrawn_at is not None
            or manifest.course_id != conversation.course_id
            or manifest.agent_version_id != conversation.agent_version_id
            or manifest.debate_id is not None
            or manifest.turn_id is not None
        ):
            return False
        if (
            self.db.scalar(
                select(CourseMember.user_id).where(
                    CourseMember.course_id == conversation.course_id,
                    CourseMember.user_id == user_id,
                    CourseMember.role == "teacher",
                )
            )
            is None
        ):
            return False
        owner = self.db.get(User, conversation.user_id)
        version = self.db.get(AgentVersion, conversation.agent_version_id)
        agent = self.db.get(Agent, version.agent_id) if version is not None else None
        if (
            owner is None
            or owner.status != "active"
            or agent is None
            or version is None
            or version.agent_id != agent.id
            or version.knowledge_snapshot_id != conversation.snapshot_id
            or manifest.group_id != agent.group_id
            or agent.deleted_at is not None
            or agent.status != "active"
            or not can_invoke_version(self.db, conversation.user_id, version, agent)
        ):
            return False
        return True

    def _chat_conversation_for_manifest(self, manifest: ExportManifestV1) -> Any | None:
        from app.modules.workspace.models import Conversation

        if manifest.provider_operation != "llm_agent_chat" or manifest.scope_id.startswith(
            TEAM_RESULT_SCOPE_PREFIX
        ):
            return None
        try:
            conversation_id = str(UUID(manifest.scope_id))
        except ValueError:
            return None
        conversation = self.db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.entry_kind != "agent"
            or conversation.withdrawn_at is not None
        ):
            return None
        return conversation

    def _active_chat_grant(
        self,
        *,
        course_id: str,
        provider_operation: str,
        policy_hash: str,
        field_classes: tuple[str, ...],
    ) -> Any | None:
        from app.modules.workspace.models import ChatProviderStandingGrant

        expected_classes = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(provider_operation)
        if expected_classes is None or tuple(sorted(set(field_classes))) != tuple(
            sorted(expected_classes)
        ):
            return None
        classes_hash = chat_field_classes_hash(field_classes)
        grants = self.db.scalars(
            select(ChatProviderStandingGrant)
            .join(
                CourseMember,
                CourseMember.user_id == ChatProviderStandingGrant.confirmed_by_user_id,
            )
            .where(
                ChatProviderStandingGrant.course_id == course_id,
                ChatProviderStandingGrant.provider_operation == provider_operation,
                ChatProviderStandingGrant.policy_hash == policy_hash,
                ChatProviderStandingGrant.field_classes_hash == classes_hash,
                ChatProviderStandingGrant.revoked_at.is_(None),
                CourseMember.course_id == course_id,
                CourseMember.role == "teacher",
            )
            .order_by(ChatProviderStandingGrant.confirmed_at.desc(), ChatProviderStandingGrant.id)
        )
        from app.core.models import User

        for grant in grants:
            teacher = self.db.get(User, grant.confirmed_by_user_id)
            try:
                persisted_classes = tuple(json.loads(grant.field_classes_json))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if (
                teacher is not None
                and teacher.status == "active"
                and persisted_classes == tuple(sorted(set(field_classes)))
            ):
                return grant
        return None

    def _operator_chat_grant(
        self,
        *,
        course_id: str,
        provider_operation: str,
        policy_hash: str,
        field_classes: tuple[str, ...],
    ) -> Any | None:
        """Record the operator's standing consent as the course's Chat grant.

        The grant table binds consent to an active course teacher, so the
        operator's decision is recorded on that teacher's behalf; the exact
        per-turn binding and every later currency check stay unchanged.
        """

        from app.core.models import User
        from app.modules.workspace.models import ChatProviderStandingGrant

        teacher_id = self.db.scalar(
            select(CourseMember.user_id)
            .join(User, User.id == CourseMember.user_id)
            .where(
                CourseMember.course_id == course_id,
                CourseMember.role == "teacher",
                User.status == "active",
            )
            .order_by(CourseMember.user_id)
            .limit(1)
        )
        if teacher_id is None:
            return None
        classes = tuple(sorted(set(field_classes)))
        self.db.add(
            ChatProviderStandingGrant(
                id=str(uuid4()),
                course_id=course_id,
                provider_operation=provider_operation,
                policy_hash=policy_hash,
                field_classes_json=json.dumps(classes, separators=(",", ":")),
                field_classes_hash=chat_field_classes_hash(classes),
                confirmed_by_user_id=teacher_id,
                confirmed_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        self.db.flush()
        LOGGER.warning(
            "Chat Provider grant recorded by standing operator consent operation=%s",
            provider_operation,
        )
        return self._active_chat_grant(
            course_id=course_id,
            provider_operation=provider_operation,
            policy_hash=policy_hash,
            field_classes=field_classes,
        )

    def bind_chat_standing_confirmation(self, user_id: str, manifest_hash: str) -> None:
        from app.modules.workspace.models import ChatProviderStandingGrant

        manifest = self.db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )
        confirmation = self.db.scalar(
            select(ProviderExportConfirmation).where(
                ProviderExportConfirmation.manifest_hash == manifest_hash
            )
        )
        if (
            manifest is None
            or confirmation is None
            or manifest.course_id is None
            or not manifest.scope_id.startswith(CHAT_STANDING_SCOPE_PREFIX)
            or not self._is_chat_confirmer_for_manifest(user_id, manifest)
        ):
            raise ProviderDisclosureError("forbidden", "The confirmation subject is unavailable.")
        fields = tuple(
            sorted(
                item["field_class"]
                for item in json.loads(manifest.fields_json)
                if isinstance(item, dict)
            )
        )
        expected_fields = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(manifest.provider_operation)
        if expected_fields is None or fields != tuple(sorted(expected_fields)):
            raise ProviderDisclosureError("provider_preflight_stale", "The disclosure changed.")
        if (
            self._active_chat_grant(
                course_id=manifest.course_id,
                provider_operation=manifest.provider_operation,
                policy_hash=manifest.policy_hash,
                field_classes=fields,
            )
            is not None
        ):
            return
        self.db.add(
            ChatProviderStandingGrant(
                id=str(uuid4()),
                course_id=manifest.course_id,
                provider_operation=manifest.provider_operation,
                policy_hash=manifest.policy_hash,
                field_classes_json=json.dumps(fields, separators=(",", ":")),
                field_classes_hash=chat_field_classes_hash(fields),
                confirmed_by_user_id=user_id,
                confirmed_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        self.db.flush()

    def bind_chat_confirmation(self, user_id: str, manifest_hash: str) -> None:
        from app.modules.workspace.models import (
            ChatProviderConsentBinding,
        )

        manifest = self._control.get_export_manifest(manifest_hash)
        conversation = self._chat_conversation_for_manifest(manifest) if manifest else None
        manifest_row = self.db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )
        confirmation = self.db.scalar(
            select(ProviderExportConfirmation).where(
                ProviderExportConfirmation.manifest_hash == manifest_hash
            )
        )
        version = (
            self.db.get(AgentVersion, conversation.agent_version_id)
            if conversation is not None and conversation.agent_version_id is not None
            else None
        )
        agent = self.db.get(Agent, version.agent_id) if version is not None else None
        if (
            manifest is None
            or conversation is None
            or manifest_row is None
            or confirmation is None
            or manifest_row.course_id != conversation.course_id
            or manifest_row.agent_version_id != conversation.agent_version_id
            or version is None
            or agent is None
            or manifest_row.group_id != agent.group_id
            or not self._is_chat_confirmer_for_manifest(user_id, manifest_row)
        ):
            raise ProviderDisclosureError("forbidden", "The confirmation subject is unavailable.")
        values = {
            "confirmation_id": confirmation.id,
            "conversation_id": conversation.id,
            "course_id": conversation.course_id,
            "actor_user_id": conversation.user_id,
            "confirmed_by_user_id": user_id,
            "standing_grant_id": None,
        }
        existing = self.db.get(ChatProviderConsentBinding, manifest_hash)
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in values.items()):
                raise ProviderDisclosureError(
                    "provider_preflight_stale", "The recorded Chat consent changed."
                )
            return
        self.db.add(
            ChatProviderConsentBinding(
                manifest_hash=manifest_hash,
                **values,
                created_at=datetime.now(UTC),
            )
        )
        self.db.flush()

    def confirm_chat_manifest_from_standing_grant(
        self,
        manifest: ExportManifestV1,
        *,
        actor_user_id: str,
        conversation_id: str,
        turn_id: str,
        claim_revision: int | None,
        current_policy_hash: str | None,
        operator_consent: bool = False,
    ) -> bool:
        from app.core.models import User
        from app.modules.workspace.models import (
            ChatProviderConsentBinding,
            Conversation,
            ConversationTurn,
        )
        from app.providers.control import confirm_export_manifest

        provider_operation = manifest.provider_operation
        expected_fields = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(provider_operation)
        fields = tuple(sorted({field.field_class for field in manifest.fields}))
        if (
            expected_fields is None
            or fields != tuple(sorted(expected_fields))
            or manifest.scope_id != conversation_id
        ):
            return False
        if provider_operation == "embedding_query":
            expected_current_policy_hash = current_policy_hash or ""
            if (
                not isinstance(claim_revision, int)
                or isinstance(claim_revision, bool)
                or claim_revision < 0
                or not expected_current_policy_hash
                or manifest.policy_hash != expected_current_policy_hash
                or manifest.model_key != authorized_provider_model("embedding_query")
            ):
                return False
        elif provider_operation != "llm_agent_chat":
            return False
        query_agent: Agent | None = None
        conversation = self.db.get(Conversation, conversation_id)
        turn = self.db.get(ConversationTurn, turn_id)
        owner = self.db.get(User, actor_user_id)
        if (
            conversation is None
            or turn is None
            or owner is None
            or owner.status != "active"
            or conversation.user_id != actor_user_id
            or conversation.entry_kind != "agent"
            or conversation.withdrawn_at is not None
            or turn.conversation_id != conversation_id
            or turn.state != "pending"
            or conversation.active_request_id != turn_id
            or conversation.course_id is None
        ):
            return False
        if provider_operation == "embedding_query":
            if conversation.revision != claim_revision:
                return False
            member_role = self.db.scalar(
                select(CourseMember.role).where(
                    CourseMember.course_id == conversation.course_id,
                    CourseMember.user_id == actor_user_id,
                )
            )
            version = (
                self.db.get(AgentVersion, conversation.agent_version_id)
                if conversation.agent_version_id is not None
                else None
            )
            query_agent = self.db.get(Agent, version.agent_id) if version is not None else None
            snapshot = (
                self.db.get(KnowledgeSnapshot, conversation.snapshot_id)
                if conversation.snapshot_id is not None
                else None
            )
            if (
                member_role not in {"student", "teacher"}
                or conversation.snapshot_id is None
                or conversation.agent_version_id is None
                or manifest.debate_id is not None
                or manifest.turn_id is not None
                or version is None
                or query_agent is None
                or snapshot is None
                or version.agent_id != query_agent.id
                or version.knowledge_snapshot_id != snapshot.id
                or snapshot.agent_version_id != version.id
                or version.state not in {"published", "superseded"}
                or query_agent.course_id != conversation.course_id
                or query_agent.deleted_at is not None
                or query_agent.status != "active"
                or (
                    query_agent.owner_user_id != actor_user_id
                    and conversation.agent_authorization_epoch != query_agent.authorization_epoch
                )
                or not can_invoke_version(self.db, actor_user_id, version, query_agent)
                or not snapshot_sources_are_readable(
                    self.db,
                    actor_user_id,
                    snapshot.id,
                    agent=query_agent,
                    allow_historical_epoch_for_owner=True,
                )
            ):
                return False
            try:
                identity = persisted_snapshot_identity(snapshot)
            except (TypeError, ValueError):
                return False
            query_text = turn.user_text.strip()
            if not query_text or "\x00" in query_text or identity != REAL_EMBEDDING_IDENTITY:
                return False
            persona_hash = markdown_hash(version.agent_md)
            transcript_hash = hashlib.sha256(
                json.dumps(turn.user_text, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            query_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
            expected_field_hash = hashlib.sha256(canonical_json_bytes([query_text])).hexdigest()
            expected_build_hash = hashlib.sha256(
                canonical_json_bytes(
                    {
                        "version": "embedding-query-export-v1",
                        "scope_id": conversation.id,
                        "turn_id": turn.id,
                        "snapshot_id": snapshot.id,
                        "identity": {
                            "provider": identity.provider,
                            "model_key": identity.model_key,
                            "region": identity.region,
                            "dimension": identity.dimension,
                            "policy_version": identity.policy_version,
                        },
                        "transcript_hash": transcript_hash,
                        "persona_spec_hash": persona_hash,
                        "subqueries": [
                            {
                                "kind": "viewpoint",
                                "text": query_text,
                                "query_hash": query_hash,
                            }
                        ],
                    }
                )
            ).hexdigest()
            if (
                manifest.persona_spec_hash != persona_hash
                or manifest.build_manifest_hash != expected_build_hash
                or manifest.fields
                != (ExportFieldV1("current_evidence_excerpt", expected_field_hash),)
                or manifest.max_attempts != 1
                or manifest.contains_secret
                or manifest.contains_identity
                or manifest.contains_private_audio
                or manifest.contains_teacher_note
            ):
                return False
            policy = self._control.get_policy_snapshot(expected_current_policy_hash)
            if policy is None or policy.policy_hash != expected_current_policy_hash:
                return False
            try:
                policy.validate()
            except ProviderControlError:
                return False
        else:
            policy = self._control.get_policy_snapshot(manifest.policy_hash)
            if policy is None or policy.policy_hash != manifest.policy_hash:
                return False
        manifest_row = self.db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest.manifest_hash
            )
        )
        if (
            manifest_row is None
            or manifest_row.scope_id != conversation_id
            or manifest_row.course_id != conversation.course_id
            or manifest_row.agent_version_id != conversation.agent_version_id
            or manifest_row.provider_operation != provider_operation
            or manifest_row.build_manifest_hash != manifest.build_manifest_hash
            or manifest_row.policy_hash != manifest.policy_hash
            or (
                provider_operation == "embedding_query"
                and (query_agent is None or manifest_row.group_id != query_agent.group_id)
            )
        ):
            return False
        grant = self._active_chat_grant(
            course_id=conversation.course_id,
            provider_operation=provider_operation,
            policy_hash=manifest.policy_hash,
            field_classes=fields,
        )
        if grant is None and operator_consent:
            grant = self._operator_chat_grant(
                course_id=conversation.course_id,
                provider_operation=provider_operation,
                policy_hash=manifest.policy_hash,
                field_classes=fields,
            )
        if grant is None:
            return False
        if self.get_export_confirmation(manifest.manifest_hash) is not None:
            return False
        confirmation = confirm_export_manifest(
            manifest,
            policy,
            confirmed_at=datetime.now(UTC).isoformat(),
            expected_manifest_hash=manifest.manifest_hash,
            expected_policy_hash=manifest.policy_hash,
        )
        confirmation_id = self.save_export_confirmation(
            str(manifest_row.id),
            confirmation,
            expected_revision=manifest.operation_revision,
        )
        self.db.add(
            ChatProviderConsentBinding(
                manifest_hash=manifest.manifest_hash,
                confirmation_id=confirmation_id,
                conversation_id=conversation.id,
                course_id=conversation.course_id,
                actor_user_id=actor_user_id,
                confirmed_by_user_id=grant.confirmed_by_user_id,
                standing_grant_id=grant.id,
                created_at=datetime.now(UTC),
            )
        )
        self.db.flush()
        self.db.commit()
        return True

    def bind_team_confirmation(self, user_id: str, manifest_hash: str) -> None:
        from app.modules.workspace.models import (
            Conversation,
            TeamProviderConsentBinding,
            TeamTurnResult,
        )

        manifest = self.db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )
        confirmation = self.db.scalar(
            select(ProviderExportConfirmation).where(
                ProviderExportConfirmation.manifest_hash == manifest_hash
            )
        )
        if (
            manifest is None
            or confirmation is None
            or not self._is_team_confirmer_for_manifest(user_id, manifest)
        ):
            raise ProviderDisclosureError("forbidden", "The confirmation subject is unavailable.")
        result = self.db.get(
            TeamTurnResult, manifest.scope_id.removeprefix(TEAM_RESULT_SCOPE_PREFIX)
        )
        conversation = self.db.get(Conversation, result.conversation_id) if result else None
        if conversation is None or result is None or conversation.team_authorization_epoch is None:
            raise _blocked()
        expected = {
            "confirmation_id": confirmation.id,
            "result_id": result.id,
            "actor_user_id": conversation.user_id,
            "confirmer_user_id": user_id,
            "confirmer_kind": (
                "custom_owner" if conversation.entry_kind == "team" else "publisher_teacher"
            ),
            "team_epoch": conversation.team_authorization_epoch,
            "publication_epoch": conversation.publication_epoch,
        }
        existing = self.db.get(TeamProviderConsentBinding, manifest_hash)
        if existing is not None:
            if any(getattr(existing, key) != value for key, value in expected.items()):
                raise _stale("The recorded confirmation subject changed.")
            return
        self.db.add(
            TeamProviderConsentBinding(
                manifest_hash=manifest_hash, **expected, created_at=datetime.now(UTC)
            )
        )
        self.db.flush()

    def is_teacher_for_manifest(self, user_id: str, manifest_hash: str) -> bool:
        manifest = self.db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest_hash
            )
        )
        if manifest is not None and manifest.scope_id.startswith(TEAM_RESULT_SCOPE_PREFIX):
            return self._is_team_confirmer_for_manifest(user_id, manifest)
        if manifest is not None and manifest.provider_operation == "llm_agent_chat":
            return self._is_chat_confirmer_for_manifest(user_id, manifest)
        if (
            manifest is not None
            and manifest.provider_operation == EMBEDDING_QUERY_OPERATION
            and manifest.scope_id.startswith(CHAT_STANDING_SCOPE_PREFIX)
        ):
            return self._is_chat_standing_teacher_for_manifest(user_id, manifest)
        if manifest is not None and manifest.provider_operation == EMBEDDING_QUERY_OPERATION:
            return self._is_query_teacher_for_manifest(user_id, manifest)
        if manifest is not None and manifest.provider_operation == LLM_KNOWLEDGE_OPERATION:
            return self._is_knowledge_owner_for_manifest(user_id, manifest)
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

    def _is_chat_standing_teacher_for_manifest(
        self, user_id: str, manifest: ProviderExportManifest
    ) -> bool:
        course_id = manifest.course_id
        expected_fields = CHAT_STANDING_OPERATION_FIELD_CLASSES.get(manifest.provider_operation)
        try:
            fields = tuple(
                sorted(
                    item["field_class"]
                    for item in json.loads(manifest.fields_json)
                    if isinstance(item, dict)
                )
            )
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            return False
        if (
            course_id is None
            or expected_fields is None
            or fields != tuple(sorted(expected_fields))
            or manifest.scope_id != f"{CHAT_STANDING_SCOPE_PREFIX}{course_id}"
            or manifest.group_id is not None
            or manifest.debate_id is not None
            or manifest.turn_id is not None
            or manifest.agent_version_id is not None
        ):
            return False
        from app.core.models import User

        return (
            self.db.scalar(
                select(CourseMember.user_id)
                .join(User, User.id == CourseMember.user_id)
                .where(
                    CourseMember.course_id == course_id,
                    CourseMember.user_id == user_id,
                    CourseMember.role == "teacher",
                    User.status == "active",
                )
            )
            is not None
        )

    def _is_query_teacher_for_manifest(
        self, user_id: str, manifest: ProviderExportManifest
    ) -> bool:
        """Authorize one non-Chat query manifest through its exact Agent course."""

        if (
            manifest.scope_id.startswith((CHAT_STANDING_SCOPE_PREFIX, TEAM_RESULT_SCOPE_PREFIX))
            or manifest.course_id is None
            or manifest.group_id is None
            or manifest.agent_version_id is None
        ):
            return False
        from app.modules.workspace.models import Conversation

        # A Single-Agent Chat scope is private to its owner even when the
        # selected Agent happens to belong to a course group.
        if (
            self.db.scalar(
                select(Conversation.id).where(
                    Conversation.id == manifest.scope_id,
                    Conversation.entry_kind == "agent",
                )
            )
            is not None
        ):
            return False
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
                    ProviderExportManifest.manifest_hash == manifest.manifest_hash,
                    ProviderExportManifest.scope_id == manifest.scope_id,
                    ProviderExportManifest.provider_operation == EMBEDDING_QUERY_OPERATION,
                    ProviderExportManifest.course_id == manifest.course_id,
                    ProviderExportManifest.group_id == manifest.group_id,
                    ProviderExportManifest.agent_version_id == manifest.agent_version_id,
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
        if (
            scope_id.startswith((CHAT_STANDING_SCOPE_PREFIX, TEAM_RESULT_SCOPE_PREFIX))
            or self.db.scalar(
                select(ProviderExportManifest.id)
                .where(
                    ProviderExportManifest.scope_id == scope_id,
                    ProviderExportManifest.provider_operation == EMBEDDING_QUERY_OPERATION,
                )
                .limit(1)
            )
            is None
        ):
            return False
        from app.modules.workspace.models import Conversation

        if (
            self.db.scalar(
                select(Conversation.id).where(
                    Conversation.id == scope_id,
                    Conversation.entry_kind == "agent",
                )
            )
            is not None
        ):
            return False
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
    "LLM_KNOWLEDGE_OPERATION",
    "InMemoryProviderDisclosureStore",
    "PROVIDER_DISCLOSURE_VERSION",
    "ProviderDisclosureError",
    "ProviderDisclosureService",
    "ProviderDisclosureStore",
    "ProviderDisclosureStoreError",
    "SqlAlchemyProviderDisclosureStore",
]
