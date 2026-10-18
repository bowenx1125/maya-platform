"""M08 voice enrollment, fallback resolution and preview lifecycle services."""

from __future__ import annotations

import base64
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, false, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, invalid_state, not_found, validation_failure
from app.core.models import (
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    VoiceProfile,
    VoiceProviderOperation,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    assert_claim_owned,
    claim_idempotency,
    finish_idempotency,
    renew_idempotency_lease,
    request_hash,
)
from app.modules.org.access import WorkspaceMember
from app.modules.voices.crypto import (
    VoiceEncryptionError,
    decrypt_external_voice_id,
    encrypt_external_voice_id,
)
from app.modules.voices.schemas import PlaybackResource, VoiceProfileResponse
from app.modules.voices.uploads import StreamedVoiceUpload, cleanup_voice_temp_dirs
from app.providers.audio import (
    AudioProcessError,
    AudioValidationError,
    audio_quality_metrics,
    read_pcm16_wav,
    run_ffmpeg_normalize,
    validate_source_audio,
)
from app.providers.dashscope import DEFAULT_TARGET_MODEL_KEY, FLASH_TTS_MODEL_KEY
from app.providers.factory import voice_provider
from app.providers.tts import TTSProvider
from app.providers.voice import (
    VoiceCloneProvider,
    VoiceCloneRefusedError,
    VoiceEnrollmentResult,
    VoiceProviderError,
    VoiceProviderTimeout,
)

LOGGER = logging.getLogger(__name__)

CONSENT_COPY_VERSION = "voice-consent-v1"
# Enrollment holds its idempotency claim across upload, create and the
# supplier review wait; renew it well past the slowest observed call.
ENROLL_LEASE_SECONDS = 120
TARGET_MODEL_KEY = DEFAULT_TARGET_MODEL_KEY
PREVIEW_TEXT = (
    "I will listen carefully, respond with evidence, and explain what different "
    "perspectives can learn from one another."
)
PREVIEW_TTL = timedelta(minutes=10)
SAFE_VOICE_ERRORS = {
    "audio_invalid",
    "voice_clone_refused",
    "voice_enrollment_failed",
    "voice_provider_unavailable",
    "voice_mapping_unavailable",
    "provider_unavailable",
}

# A refusal this deterministic is decided before any charged dispatch: the
# flash model never accepts enrollment. Retrying the same request or falling
# back to another provider cannot change the answer.
CLONE_REFUSED_ERROR = PlatformError(
    "voice_clone_refused",
    "This voice path does not support cloning a custom voice.",
    422,
)


@dataclass(frozen=True)
class ScopedVoice:
    profile: VoiceProfile
    role: str


@dataclass(frozen=True)
class EffectiveVoice:
    profile_id: str | None
    fallback_active: bool
    profile: VoiceProfile | None


def now_utc() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _safe_error_code(value: str | None) -> str | None:
    return value if value in SAFE_VOICE_ERRORS else None


def voice_profile_dto(profile: VoiceProfile, *, can_manage: bool = True) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        can_manage=can_manage,
        id=UUID(profile.id),
        scope=profile.scope,  # type: ignore[arg-type]
        group_id=UUID(profile.group_id) if profile.group_id else None,
        status=profile.status,  # type: ignore[arg-type]
        source_filename=profile.source_filename or "",
        safe_error_code=_safe_error_code(profile.safe_error_code),
        created_at=profile.created_at,
    )


def _scoped_voice_query(
    context: AuthContext, profile_id: str, *, former_member: bool = False
) -> Any:
    """A cloned voice belongs to the student who uploaded it, not the group.

    Membership is still required, but a group-scope profile is only visible to
    the uploading student recorded in ``consent_actor_user_id``.  A profile
    with a missing owner fails closed: nobody can read or act on it.

    ``former_member`` drops the current-membership requirement (course
    membership stays): a student moved to another group can still withdraw
    their own clone, though not read or rename it.
    """

    query = (
        select(VoiceProfile)
        .join(Group, Group.id == VoiceProfile.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
    )
    if not former_member:
        query = query.join(
            WorkspaceMember,
            and_(WorkspaceMember.group_id == Group.id, WorkspaceMember.user_id == context.user.id),
        )
    return query.where(
        VoiceProfile.id == profile_id,
        VoiceProfile.scope == "group",
        VoiceProfile.consent_actor_user_id == context.user.id,
        CourseMember.user_id == context.user.id,
    )


def _personal_voice_query(context: AuthContext, profile_id: str) -> Any:
    """A teacher's personal voice is theirs alone; an ownerless one is nobody's."""

    return select(VoiceProfile).where(
        VoiceProfile.id == profile_id,
        VoiceProfile.scope == "personal",
        VoiceProfile.group_id.is_(None),
        VoiceProfile.consent_actor_user_id == context.user.id,
    )


def visible_student_voice(
    db: Session, context: AuthContext, profile_id: str, *, former_member: bool = False
) -> ScopedVoice:
    """The voice its creator may manage: their group clone or their personal voice."""

    row = db.execute(_scoped_voice_query(context, profile_id, former_member=former_member)).first()
    if row is None:
        row = db.execute(_personal_voice_query(context, profile_id)).first()
    if row is None:
        raise not_found()
    return ScopedVoice(row[0], "student")


def rename_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    source_filename: str,
) -> VoiceProfileResponse:
    profile = visible_student_voice(db, context, profile_id).profile
    profile.source_filename = source_filename
    profile.updated_at = now_utc()
    db.flush()
    return voice_profile_dto(profile)


def _groupmate_owner_ids(db: Session, group_id: str) -> Any:
    """Students of this group: whose ready voices a groupmate may choose."""

    return (
        select(WorkspaceMember.user_id)
        .join(Group, Group.id == WorkspaceMember.group_id)
        .join(
            CourseMember,
            and_(
                CourseMember.course_id == Group.course_id,
                CourseMember.user_id == WorkspaceMember.user_id,
            ),
        )
        .where(Group.id == group_id, CourseMember.role == "student")
    )


def _student_in_group(db: Session, context: AuthContext, group_id: str) -> bool:
    """Whether the caller is a student member of this group, never a visiting teacher."""

    return (
        db.execute(
            select(WorkspaceMember.user_id)
            .join(Group, Group.id == WorkspaceMember.group_id)
            .join(CourseMember, CourseMember.course_id == Group.course_id)
            .where(
                Group.id == group_id,
                WorkspaceMember.user_id == context.user.id,
                CourseMember.user_id == context.user.id,
                CourseMember.role == "student",
            )
        ).first()
        is not None
    )


def groupmate_ready_voice(db: Session, context: AuthContext, profile_id: str) -> VoiceProfile:
    """A groupmate's ready group voice the calling student may play; else not found.

    Owner decision (2026-10-18): students of one group hear each other's ready
    voices in Brainform. A teacher, even one who entered the group, is not a
    groupmate and plays no student voice.
    """

    profile = db.scalar(
        select(VoiceProfile).where(
            VoiceProfile.id == profile_id,
            VoiceProfile.scope == "group",
            VoiceProfile.status == "ready",
        )
    )
    if (
        profile is None
        or profile.group_id is None
        or profile.consent_actor_user_id is None
        or not _student_in_group(db, context, profile.group_id)
        or profile.consent_actor_user_id
        not in set(db.scalars(_groupmate_owner_ids(db, profile.group_id)).all())
    ):
        raise not_found()
    return profile


def list_group_voices(
    db: Session, context: AuthContext, group_id: str
) -> list[VoiceProfileResponse]:
    # A student sees their own voices and the ready voices of the group's other
    # students, which they may choose but not manage. A teacher on an Accounts
    # visit is not a groupmate and sees only their own (none).
    authorized = db.execute(
        select(WorkspaceMember.user_id, CourseMember.role)
        .join(Group, Group.id == WorkspaceMember.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            Group.id == group_id,
            WorkspaceMember.user_id == context.user.id,
            CourseMember.user_id == context.user.id,
        )
    ).first()
    if authorized is None:
        raise not_found()
    shared = (
        and_(
            VoiceProfile.status == "ready",
            VoiceProfile.consent_actor_user_id.in_(_groupmate_owner_ids(db, group_id)),
        )
        if authorized.role == "student"
        else false()
    )
    profiles = db.scalars(
        select(VoiceProfile)
        .where(
            VoiceProfile.scope == "group",
            VoiceProfile.group_id == group_id,
            # A missing owner fails closed and is shown to nobody.
            or_(VoiceProfile.consent_actor_user_id == context.user.id, shared),
        )
        .order_by(VoiceProfile.created_at, VoiceProfile.id)
    ).all()
    return [
        voice_profile_dto(profile, can_manage=profile.consent_actor_user_id == context.user.id)
        for profile in profiles
    ]


def list_personal_voices(
    db: Session, context: AuthContext, course_id: str
) -> list[VoiceProfileResponse]:
    """A teacher's own voices, which only that teacher may choose."""

    _assert_course_teacher(db, context, course_id)
    profiles = db.scalars(
        select(VoiceProfile)
        .where(
            VoiceProfile.scope == "personal",
            VoiceProfile.group_id.is_(None),
            VoiceProfile.consent_actor_user_id == context.user.id,
        )
        .order_by(VoiceProfile.created_at, VoiceProfile.id)
    ).all()
    return [voice_profile_dto(profile) for profile in profiles]


def _assert_course_teacher(db: Session, context: AuthContext, course_id: str) -> None:
    role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == course_id, CourseMember.user_id == context.user.id
        )
    )
    if role != "teacher":
        raise not_found()


def baseline_configured_voice_id(settings: Settings, agent_id: str) -> str | None:
    """The operator's voice for one immutable baseline character, if configured."""

    try:
        mapping = settings.parsed_baseline_default_voices()
    except RuntimeError:
        return None
    if not mapping:
        return None
    from app.modules.demo_baseline.service import BASELINE_SPECS

    key = next((spec.key for spec in BASELINE_SPECS if spec.agent_id == str(agent_id)), None)
    if key is None:
        return None
    return mapping.get(key)


def ready_chat_voice(db: Session, profile_id: str, settings: Settings) -> str | None:
    """Return the decrypted external id for one ready profile.

    A missing, unfinished or undecryptable profile returns None.  The caller
    turns that into a safe TTS error and does not guess an id.
    """

    profile = db.get(VoiceProfile, profile_id)
    if profile is None or profile.status != "ready":
        return None
    try:
        return _profile_external_id(profile, settings)
    except VoiceEncryptionError:
        return None


def _profile_external_id(profile: VoiceProfile, settings: Settings) -> str:
    if not profile.external_id_encrypted:
        raise VoiceEncryptionError("voice mapping unavailable")
    return decrypt_external_voice_id(
        profile.external_id_encrypted,
        settings.secret_bytes,
        profile_id=profile.id,
        scope=profile.scope,
        group_id=profile.group_id,
        provider_key=profile.provider_key,
        target_model_key=profile.target_model_key,
    )


def validate_voice_binding(
    db: Session,
    context: AuthContext,
    version: AgentVersion,
    voice_profile_id: str | None,
    settings: Settings,
) -> None:
    """Validate a draft binding without exposing whether another group has a profile."""

    if voice_profile_id is None:
        return
    agent = db.scalar(
        select(Agent)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .where(AgentVersion.id == version.id)
    )
    if agent is not None and agent.group_id is None:
        # A teacher's personal Agent takes only that teacher's personal voice.
        if agent.owner_user_id != context.user.id:
            raise not_found()
        _assert_course_teacher(db, context, agent.course_id)
        profile = db.scalar(
            _personal_voice_query(context, voice_profile_id).where(VoiceProfile.status == "ready")
        )
        _require_bindable(profile, settings)
        return
    target_group = db.scalar(
        select(Agent.group_id)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .join(WorkspaceMember, WorkspaceMember.group_id == Agent.group_id)
        .join(Group, Group.id == Agent.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            AgentVersion.id == version.id,
            WorkspaceMember.user_id == context.user.id,
            CourseMember.user_id == context.user.id,
        )
    )
    if target_group is None:
        raise not_found()
    # The caller's own clone or, for a student, a groupmate's; a teacher who
    # entered the group never takes a student's voice. A missing owner fails
    # closed.
    shared = (
        VoiceProfile.consent_actor_user_id.in_(_groupmate_owner_ids(db, target_group))
        if _student_in_group(db, context, target_group)
        else false()
    )
    profile = db.scalar(
        select(VoiceProfile).where(
            VoiceProfile.id == voice_profile_id,
            VoiceProfile.scope == "group",
            VoiceProfile.group_id == target_group,
            VoiceProfile.status == "ready",
            or_(VoiceProfile.consent_actor_user_id == context.user.id, shared),
        )
    )
    _require_bindable(profile, settings)


def _require_bindable(profile: VoiceProfile | None, settings: Settings) -> None:
    if profile is None:
        raise validation_failure(
            "The selected voice profile is not ready for this group.",
            code="voice_enrollment_failed",
        )
    try:
        _profile_external_id(profile, settings)
    except VoiceEncryptionError as exc:
        raise validation_failure(
            "The selected voice profile is not available.",
            code="voice_enrollment_failed",
        ) from exc


def _sample_language(value: str | None) -> tuple[str, str]:
    """Map the upload's sample language to the DashScope enrollment code.

    Omitted stays ``en`` so existing clients keep their previous request.
    ``zh-CN`` is the chat language; the supplier field is ``zh``.
    """

    token = (value or "").strip() or "en"
    if token == "en":
        return "en", "en"
    if token == "zh-CN":
        return "zh-CN", "zh"
    raise validation_failure(
        "The sample language is not supported.",
        code="voice_enrollment_failed",
    )


def _voice_request_hash(
    context: AuthContext,
    group_id: str,
    source_filename: str,
    source_sha256: str,
    consent_copy_version: str,
    sample_language: str,
) -> str:
    return request_hash(
        "enrollVoice",
        context.user.id,
        [group_id],
        {
            "source_filename": source_filename,
            "source_sha256": source_sha256,
            "consent_accepted": True,
            "consent_copy_version": consent_copy_version,
            "language": sample_language,
        },
    )


def _new_recovery_name(profile_id: str) -> str:
    # The enrollment prefix accepts only lowercase letters and digits, fewer
    # than ten. The platform UUID keeps this deterministic for provider-side
    # reconciliation without exposing an external identifier.
    return f"m{profile_id.replace('-', '')[:8]}"


def _safe_provider_error(exc: Exception) -> PlatformError:
    """Classify one provider failure without copying its message.

    A typed clone refusal is deterministic and must stay distinguishable from
    a supplier outage, so the browser can tell "this voice path cannot clone"
    apart from "try again later". Everything ambiguous stays conservative.
    """

    if isinstance(exc, VoiceCloneRefusedError):
        return PlatformError(
            "voice_clone_refused",
            "This voice path does not support cloning a custom voice.",
            422,
        )
    return PlatformError(
        "provider_unavailable",
        "The voice service is temporarily unavailable.",
        503,
    )


def _create_profile_and_operation(
    db: Session,
    *,
    context: AuthContext,
    group_id: str | None,
    display_name: str,
    source_filename: str | None,
    source_sha256: str | None,
    consent_copy_version: str | None,
    provider: VoiceCloneProvider,
    request_hash_value: str,
    idempotency_record_id: str | None,
    operation_type: str,
    claim_token: str | None = None,
    personal: bool = False,
) -> tuple[VoiceProfile, VoiceProviderOperation]:
    timestamp = now_utc()
    profile_id = str(uuid4())
    owned = group_id is not None or personal
    profile = VoiceProfile(
        id=profile_id,
        scope="group" if group_id is not None else "personal" if personal else "system",
        group_id=group_id,
        display_name=display_name,
        status="enrolling",
        provider_key=provider.key,
        target_model_key=provider.target_model_key,
        external_id_encrypted=None,
        recovery_name=_new_recovery_name(profile_id),
        provenance_json=json.dumps(
            {
                "source_filename": source_filename,
                "source_sha256": source_sha256,
                "consent_copy_version": consent_copy_version,
                "consent_actor_user_id": context.user.id if owned else None,
                "consent_accepted": owned,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        source_filename=source_filename,
        source_sha256=source_sha256,
        consent_copy_version=consent_copy_version,
        consent_actor_user_id=context.user.id if owned else None,
        consent_accepted_at=timestamp if owned else None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    operation = VoiceProviderOperation(
        id=str(uuid4()),
        profile_id=profile_id,
        operation_type=operation_type,
        profile_scope=profile.scope,
        state="prepared",
        attempt=1,
        claim_token=claim_token or secrets.token_urlsafe(32),
        request_hash=request_hash_value,
        provider_deadline=timestamp + timedelta(seconds=35),
        request_count=0,
        charged_request_count=0,
        idempotency_record_id=idempotency_record_id,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add_all([profile, operation])
    db.flush()
    return profile, operation


def _dispatch_operation(db: Session, operation: VoiceProviderOperation) -> None:
    """Commit the charged-operation ledger before crossing the provider boundary."""

    timestamp = now_utc()
    changed = db.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.state == "prepared",
            VoiceProviderOperation.claim_token == operation.claim_token,
            VoiceProviderOperation.attempt == operation.attempt,
        )
        .values(
            state="dispatched",
            request_count=VoiceProviderOperation.request_count + 1,
            charged_request_count=(
                VoiceProviderOperation.charged_request_count
                + (1 if operation.operation_type == "enroll" else 0)
            ),
            dispatched_at=timestamp,
            updated_at=timestamp,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise invalid_state("The voice provider operation is no longer available.")
    db.commit()


def _finish_operation(
    db: Session,
    operation: VoiceProviderOperation,
    *,
    state: str,
    safe_error_code: str | None = None,
    output_bytes: int = 0,
) -> None:
    timestamp = now_utc()
    changed = db.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.state.in_(("dispatched", "reconciling", "prepared")),
            VoiceProviderOperation.claim_token == operation.claim_token,
            VoiceProviderOperation.attempt == operation.attempt,
        )
        .values(
            state=state,
            safe_error_code=_safe_error_code(safe_error_code),
            output_bytes=output_bytes,
            completed_at=timestamp if state in {"succeeded", "failed"} else None,
            updated_at=timestamp,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        raise invalid_state("The voice provider operation is no longer owned by this request.")
    db.commit()


def _record_reconciliation_request(db: Session, operation: VoiceProviderOperation) -> None:
    changed = db.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.claim_token == operation.claim_token,
            VoiceProviderOperation.attempt == operation.attempt,
            VoiceProviderOperation.state.in_(("dispatched", "reconciling", "outcome_unknown")),
        )
        .values(
            state="reconciling",
            request_count=VoiceProviderOperation.request_count + 1,
            updated_at=now_utc(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        raise invalid_state("The voice provider operation is no longer available.")
    db.commit()


def _claim_provider_operation(
    db: Session,
    operation: VoiceProviderOperation,
    claim_token: str,
) -> None:
    """Fence a provider worker before it reconciles or dispatches.

    The idempotency lease protects the public command; this second CAS protects
    the charged-operation row from an expired/stale worker that is still
    returning from a provider call.  A worker can only replace the exact
    operation token and attempt it observed.
    """

    if operation.claim_token == claim_token:
        return
    changed = db.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.claim_token == operation.claim_token,
            VoiceProviderOperation.attempt == operation.attempt,
            VoiceProviderOperation.state.in_(
                ("prepared", "dispatched", "reconciling", "outcome_unknown")
            ),
        )
        .values(claim_token=claim_token, updated_at=now_utc())
    )
    if getattr(changed, "rowcount", 0) != 1:
        db.rollback()
        raise invalid_state("The voice provider operation is no longer owned by this request.")
    db.commit()
    db.refresh(operation)


def _settle_profile_status(
    db: Session, profile: VoiceProfile, status: str, safe_error_code: str | None
) -> bool:
    """Write an enrollment outcome unless the card was deleted meanwhile.

    A delete may commit on another replica while the supplier call runs. A
    delete is final, so the write is conditional on the stored row; when it
    finds the profile deleted, the in-memory profile is left deleted too and
    False is returned.
    """

    changed = db.execute(
        update(VoiceProfile)
        .where(VoiceProfile.id == profile.id, VoiceProfile.status != "deleted")
        .values(status=status, safe_error_code=safe_error_code, updated_at=now_utc())
        .execution_options(synchronize_session=False)
    )
    if getattr(changed, "rowcount", 0) == 1:
        profile.status = status
        profile.safe_error_code = safe_error_code
        return True
    profile.status = "deleted"
    profile.safe_error_code = None
    return False


def _cleanup_deleted_enrollment(profile: VoiceProfile, provider: VoiceCloneProvider | None) -> None:
    """Best effort: remove a voice the supplier may have created for a deleted card."""

    if provider is None:
        return
    try:
        found = provider.exists(profile.recovery_name, target_model_key=profile.target_model_key)
        # More than one match is ambiguous; never delete a voice that may
        # belong to another profile.
        if found.visibility_known and len(found.matches) == 1:
            provider.delete(found.matches[0], target_model_key=profile.target_model_key)
            return
        if not found.matches and found.visibility_known:
            return
    except VoiceProviderError:
        pass
    LOGGER.warning(
        "Deleted voice may be left at the supplier for later cleanup profile_id=%s",
        profile.id,
    )


def _store_enrollment_success(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    result: VoiceEnrollmentResult,
    settings: Settings,
    *,
    provider: VoiceCloneProvider | None = None,
) -> VoiceProfile:
    operation.safe_request_id = result.request_id
    operation.input_bytes = result.input_bytes
    operation.output_bytes = result.output_bytes
    # Created means the provider returned a usable external id. A degraded
    # result or an empty id is a failed profile, and the operation fails with
    # it: a 202 "success" whose card says failed is exactly the lie that
    # made a broken clone look Created.
    valid_external_id = bool(result.external_voice_id)
    succeeded = not result.degraded and valid_external_id
    if valid_external_id:
        profile.external_id_encrypted = encrypt_external_voice_id(
            result.external_voice_id,
            settings.secret_bytes,
            profile_id=profile.id,
            scope=profile.scope,
            group_id=profile.group_id,
            provider_key=profile.provider_key,
            target_model_key=profile.target_model_key,
        )
    # The teacher may have deleted the card while the supplier was still
    # creating the voice. A delete is final: keep the profile deleted and
    # remove the new supplier voice instead of bringing the card back. The
    # status write is conditional, so a delete that commits after any read
    # here is still honoured.
    if not _settle_profile_status(
        db,
        profile,
        "preview_ready" if succeeded else "failed",
        None if succeeded else "voice_enrollment_failed",
    ):
        profile.updated_at = now_utc()
        _finish_operation(
            db,
            operation,
            state="succeeded" if succeeded else "failed",
            safe_error_code=None if succeeded else "voice_enrollment_failed",
            output_bytes=result.output_bytes,
        )
        if valid_external_id and provider is not None:
            try:
                provider.delete(result.external_voice_id, target_model_key=profile.target_model_key)
            except VoiceProviderError:
                LOGGER.warning(
                    "Deleted voice left at the supplier for later cleanup profile_id=%s",
                    profile.id,
                )
        return profile
    profile.updated_at = now_utc()
    _finish_operation(
        db,
        operation,
        state="succeeded" if succeeded else "failed",
        safe_error_code=None if succeeded else "voice_enrollment_failed",
        output_bytes=result.output_bytes,
    )
    if not succeeded:
        raise PlatformError(
            "voice_enrollment_failed",
            "The voice enrollment could not be completed.",
            502,
        )
    return profile


def _reconcile_enrollment(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    provider: VoiceCloneProvider,
    settings: Settings,
) -> bool:
    """Reconcile an ambiguous create before permitting any second charged call."""

    from app.modules.voices.preset import is_preset_profile

    if is_preset_profile(profile):
        raise not_found()
    _record_reconciliation_request(db, operation)
    try:
        result = provider.exists(profile.recovery_name, target_model_key=profile.target_model_key)
    except VoiceProviderError as exc:
        _settle_profile_status(db, profile, "outcome_unknown", "provider_unavailable")
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
        )
        raise _safe_provider_error(exc) from exc
    if not result.visibility_known or len(result.matches) > 1:
        _settle_profile_status(db, profile, "outcome_unknown", "voice_enrollment_failed")
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_enrollment_failed"
        )
        raise PlatformError(
            "voice_enrollment_failed",
            "The voice enrollment outcome needs reconciliation.",
            503,
        )
    if len(result.matches) == 1:
        stored = VoiceEnrollmentResult(result.matches[0], charged=False)
        _store_enrollment_success(db, profile, operation, stored, settings, provider=provider)
        return True
    # Zero visible matches are safe to retry only after the provider deadline.
    if now_utc() < _utc(operation.provider_deadline) or operation.attempt >= 2:
        _settle_profile_status(db, profile, "outcome_unknown", "voice_enrollment_failed")
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_enrollment_failed"
        )
        raise PlatformError(
            "voice_enrollment_failed",
            "The voice enrollment outcome needs reconciliation.",
            503,
        )
    if not _settle_profile_status(db, profile, "enrolling", None):
        # A deleted card is never enrolled again, not even by a same-key retry.
        _finish_operation(db, operation, state="failed", safe_error_code="voice_enrollment_failed")
        raise not_found()
    operation.state = "prepared"
    profile.updated_at = now_utc()
    operation.attempt += 1
    operation.claim_token = secrets.token_urlsafe(32)
    operation.provider_deadline = now_utc() + timedelta(seconds=35)
    operation.updated_at = now_utc()
    db.commit()
    return False


def enroll_voice(
    db: Session,
    context: AuthContext,
    settings: Settings,
    upload: StreamedVoiceUpload,
    *,
    group_id: str | None,
    consent_accepted: bool,
    consent_copy_version: str | None,
    idempotency_key: str,
    language: str | None = None,
    provider: VoiceCloneProvider | None = None,
    personal_course_id: str | None = None,
) -> VoiceProfileResponse | Any:
    """Validate, normalize and enroll one temporary upload.

    A student enrolls into a group; a teacher, who has no group, enrolls a
    personal voice under ``personal_course_id``.
    """

    if not consent_accepted:
        upload.cleanup()
        raise validation_failure(
            "Voice enrollment requires consent.", code="voice_enrollment_failed"
        )
    copy_version = (consent_copy_version or CONSENT_COPY_VERSION).strip() or CONSENT_COPY_VERSION
    try:
        sample_language, provider_language = _sample_language(language)
    except PlatformError:
        upload.cleanup()
        raise
    try:
        provider_instance = provider or voice_provider(settings)
    except BaseException:
        upload.cleanup()
        raise
    try:
        if (group_id is None) == (personal_course_id is None):
            raise not_found()
        if group_id is not None:
            _assert_student_group_access(db, context, group_id)
        else:
            assert personal_course_id is not None
            _assert_course_teacher(db, context, personal_course_id)
    except BaseException:
        upload.cleanup()
        raise
    # Content probing happens before the database claim.  The source remains in
    # the UUID temp directory and is deleted by the route's finally block.
    try:
        validate_source_audio(upload.source_path, upload.source_filename)
    except AudioValidationError as exc:
        upload.cleanup()
        raise validation_failure("The voice file is not valid.", code="audio_invalid") from exc
    body_hash = _voice_request_hash(
        context,
        group_id if group_id is not None else f"personal:{personal_course_id}",
        upload.source_filename,
        upload.sha256,
        copy_version,
        sample_language,
    )
    try:
        record, replay = claim_idempotency(
            db,
            context,
            "enrollVoice",
            idempotency_key,
            body_hash,
            data_root=settings.resolved_data_root,
        )
    except PlatformError as exc:
        upload.cleanup()
        if exc.status_code == 409 and exc.code == "idempotency_conflict":
            raise validation_failure(
                "The idempotency key was used for a different voice upload.",
                code="idempotency_conflict",
            ) from exc
        if exc.status_code == 409:
            raise PlatformError(
                "provider_unavailable",
                "The voice enrollment is already in progress.",
                503,
            ) from exc
        raise
    except BaseException:
        upload.cleanup()
        raise
    if replay is not None:
        upload.cleanup()
        return replay
    try:
        assert_claim_owned(db, record)
        # Upload, create and the supplier review wait (VOICE_REVIEW_WAIT_SECONDS)
        # take 9-35 s; the default 10 s lease would expire mid-call and turn a
        # created voice into outcome_unknown, dropping its supplier id.
        renew_idempotency_lease(db, record, lease_seconds=ENROLL_LEASE_SECONDS)
    except BaseException:
        upload.cleanup()
        raise
    profile: VoiceProfile | None = None
    operation: VoiceProviderOperation | None = None
    normalized_path = upload.request_directory / "normalized.wav"
    try:
        try:
            run_ffmpeg_normalize(upload.source_path, normalized_path)
            normalized = read_pcm16_wav(normalized_path)
            normalized_info = audio_quality_metrics(normalized)
            if not 10.0 <= normalized_info["duration_seconds"] <= 20.0:
                raise AudioValidationError("audio_invalid")
        except (AudioValidationError, AudioProcessError) as exc:
            from app.modules.knowledge.services import abandon_claim

            abandon_claim(db, record)
            raise validation_failure(
                "The voice file could not be normalized.", code="audio_invalid"
            ) from exc
        existing_operation = db.scalar(
            select(VoiceProviderOperation)
            .where(
                VoiceProviderOperation.idempotency_record_id == record.id,
                VoiceProviderOperation.operation_type == "enroll",
            )
            .order_by(VoiceProviderOperation.created_at)
        )
        if existing_operation is not None:
            existing_profile = db.get(VoiceProfile, existing_operation.profile_id)
            if existing_profile is None:
                raise invalid_state("The voice enrollment record is unavailable.")
            profile = existing_profile
            operation = existing_operation
            # A same-key retry must reconcile every potentially charged
            # operation before it can issue another create request.
            if operation.state in {"dispatched", "reconciling", "outcome_unknown"}:
                _claim_provider_operation(db, operation, record.claim_token)
                if _reconcile_enrollment(db, profile, operation, provider_instance, settings):
                    result = voice_profile_dto(profile)
                    finish_idempotency(db, record, 202, result.model_dump(mode="json"))
                    db.commit()
                    return result
                _claim_provider_operation(db, operation, record.claim_token)
            elif operation.state == "succeeded":
                result = voice_profile_dto(profile)
                finish_idempotency(db, record, 202, result.model_dump(mode="json"))
                db.commit()
                return result
            elif operation.state == "failed" and operation.safe_error_code == "voice_clone_refused":
                # A refused clone never becomes retryable, not even with the
                # same key: the answer was decided before any charged call.
                raise CLONE_REFUSED_ERROR
            elif operation.state == "prepared":
                _claim_provider_operation(db, operation, record.claim_token)
            else:
                # A deterministic, pre-charge failure abandoned its claim;
                # create a fresh prepared operation under this explicit retry.
                profile, operation = _create_profile_and_operation(
                    db,
                    context=context,
                    group_id=group_id,
                    display_name=upload.source_filename.rsplit(".", 1)[0][:240] or "Voice Profile",
                    source_filename=upload.source_filename,
                    source_sha256=upload.sha256,
                    consent_copy_version=copy_version,
                    provider=provider_instance,
                    request_hash_value=body_hash,
                    idempotency_record_id=record.id,
                    operation_type="enroll",
                    claim_token=record.claim_token,
                    personal=group_id is None,
                )
                db.commit()
        else:
            profile, operation = _create_profile_and_operation(
                db,
                context=context,
                group_id=group_id,
                display_name=upload.source_filename.rsplit(".", 1)[0][:240] or "Voice Profile",
                source_filename=upload.source_filename,
                source_sha256=upload.sha256,
                consent_copy_version=copy_version,
                provider=provider_instance,
                request_hash_value=body_hash,
                idempotency_record_id=record.id,
                operation_type="enroll",
                claim_token=record.claim_token,
                personal=group_id is None,
            )
            db.commit()
        assert profile is not None and operation is not None
        assert_claim_owned(db, record)
        # A known-local refusal is decided before the durable charged
        # dispatch, and it stays a durable failed card: the teacher must see
        # that this upload did not become a voice, and the same key cannot
        # re-issue it.
        if getattr(provider_instance, "target_model_key", None) == FLASH_TTS_MODEL_KEY:
            profile.status = "failed"
            profile.safe_error_code = "voice_clone_refused"
            profile.updated_at = now_utc()
            _finish_operation(db, operation, state="failed", safe_error_code="voice_clone_refused")
            raise CLONE_REFUSED_ERROR
        _dispatch_operation(db, operation)
        assert_claim_owned(db, record)
        encoded = base64.b64encode(normalized).decode("ascii")
        data_uri = f"data:audio/wav;base64,{encoded}"
        try:
            provider_result = provider_instance.enroll(
                data_uri,
                recovery_name=profile.recovery_name,
                target_model_key=profile.target_model_key,
                language=provider_language,
            )
        except VoiceProviderTimeout as exc:
            if not _settle_profile_status(db, profile, "outcome_unknown", "provider_unavailable"):
                _cleanup_deleted_enrollment(profile, provider_instance)
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        except VoiceCloneRefusedError as exc:
            # A typed refusal is deterministic, never ambiguous: the profile
            # fails closed and no provider fallback or automatic retry may
            # re-issue this enrollment.
            _settle_profile_status(db, profile, "failed", "voice_clone_refused")
            _finish_operation(db, operation, state="failed", safe_error_code="voice_clone_refused")
            raise _safe_provider_error(exc) from exc
        except VoiceProviderError as exc:
            # Once the durable dispatch row is committed, a generic provider
            # error is conservatively ambiguous: the request may have been
            # accepted/charged even when the client saw an error.  Keep the
            # operation in reconciliation rather than allowing a same-key
            # retry to issue a second create blindly.
            if not _settle_profile_status(db, profile, "outcome_unknown", "provider_unavailable"):
                _cleanup_deleted_enrollment(profile, provider_instance)
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        try:
            assert_claim_owned(db, record)
            claim_lost = False
        except PlatformError:
            claim_lost = True
        # The supplier returned a voice id, so the voice exists there whether
        # or not this request still owns its claim (or the review wait ran
        # out). Keep the id and treat it as created rather than unknown;
        # dropping it would orphan a charged voice.
        _store_enrollment_success(
            db, profile, operation, provider_result, settings, provider=provider_instance
        )
        result = voice_profile_dto(profile)
        if not claim_lost:
            finish_idempotency(db, record, 202, result.model_dump(mode="json"))
        db.commit()
        return result
    except PlatformError:
        raise
    except VoiceEncryptionError as exc:
        if profile is not None:
            _settle_profile_status(db, profile, "failed", "voice_mapping_unavailable")
            if operation is not None:
                _finish_operation(
                    db, operation, state="failed", safe_error_code="voice_mapping_unavailable"
                )
        raise PlatformError(
            "provider_unavailable", "The voice service is temporarily unavailable.", 503
        ) from exc
    finally:
        # The route also guards this cleanup; this local finally covers direct
        # service callers and guarantees Base64/source references are released.
        encoded = ""
        data_uri = ""
        if normalized_path.exists() or normalized_path.is_symlink():
            try:
                normalized_path.unlink()
            except OSError:
                pass
        # Removing the UUID request tree also removes the original upload and
        # the active marker.  ``cleanup`` is intentionally idempotent because
        # the FastAPI route has its own outer finally guard.
        try:
            upload.cleanup()
        except (OSError, ValueError):
            pass


def _assert_student_group_access(db: Session, context: AuthContext, group_id: str) -> None:
    row = db.execute(
        select(Group.id)
        .join(WorkspaceMember, WorkspaceMember.group_id == Group.id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            Group.id == group_id,
            WorkspaceMember.user_id == context.user.id,
            CourseMember.user_id == context.user.id,
        )
        .order_by(Group.id)
    ).first()
    if row is None:
        raise not_found()


def _configured_fallback(db: Session, settings: Settings) -> VoiceProfile | None:
    """Compatibility export for the preview/resolution boundary."""

    from app.modules.voices.preview import _configured_fallback as implementation

    return implementation(db, settings)


def resolve_effective_voice_profile(
    db: Session,
    bound_profile_id: str | None,
    group_id: str | None,
    settings: Settings,
) -> EffectiveVoice:
    """Resolve the dynamic custom-or-system voice projection."""

    from app.modules.voices.preview import (
        resolve_effective_voice_profile as implementation,
    )

    return implementation(db, bound_profile_id, group_id, settings)


def create_voice_preview(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
    *,
    provider: TTSProvider | None = None,
) -> PlaybackResource:
    """Compatibility export for the disposable preview boundary."""

    from app.modules.voices.preview import create_voice_preview as implementation

    return implementation(db, context, profile_id, settings, provider=provider)


def read_pcm16_wav_bytes(raw: bytes) -> bytes:
    from app.modules.voices.preview import read_pcm16_wav_bytes as implementation

    return implementation(raw)


def media_path_for_preview(
    db: Session,
    context: AuthContext,
    preview_id: str,
    settings: Settings,
) -> tuple[Path, str]:
    from app.modules.voices.preview import media_path_for_preview as implementation

    return implementation(db, context, preview_id, settings)


def confirm_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
) -> VoiceProfileResponse:
    from app.modules.voices.preview import confirm_voice_profile as implementation

    return implementation(db, context, profile_id, settings)


def _tts_external_id(profile: VoiceProfile, settings: Settings) -> str:
    from app.modules.voices.preview import _tts_external_id as implementation

    return implementation(profile, settings)


def _delete_operation_hash(context: AuthContext, profile_id: str) -> str:
    from app.modules.voices.deletion import _delete_operation_hash as implementation

    return implementation(context, profile_id)


def _reconcile_delete(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    provider: VoiceCloneProvider,
) -> bool:
    from app.modules.voices.deletion import _reconcile_delete as implementation

    return implementation(db, profile, operation, provider)


def delete_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
    *,
    idempotency_key: str,
    provider: VoiceCloneProvider | None = None,
) -> VoiceProfileResponse | Any:
    from app.modules.voices.deletion import delete_voice_profile as implementation

    return implementation(
        db,
        context,
        profile_id,
        settings,
        idempotency_key=idempotency_key,
        provider=provider,
    )


def startup_voice_cleanup(data_root: Path) -> list[str]:
    """Run safe startup cleanup for stale request trees."""

    return cleanup_voice_temp_dirs(data_root)
