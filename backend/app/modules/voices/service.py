"""M08 voice enrollment, fallback resolution and preview lifecycle services."""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, select, update
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
from app.providers.factory import voice_provider
from app.providers.tts import TTSProvider
from app.providers.voice import (
    VoiceCloneProvider,
    VoiceEnrollmentResult,
    VoiceProviderError,
    VoiceProviderTimeout,
)

CONSENT_COPY_VERSION = "voice-consent-v1"
TARGET_MODEL_KEY = "qwen3-tts-vc-2026-01-22"
PREVIEW_TEXT = (
    "I will listen carefully, respond with evidence, and explain what different "
    "perspectives can learn from one another."
)
PREVIEW_TTL = timedelta(minutes=10)
SAFE_VOICE_ERRORS = {
    "audio_invalid",
    "voice_enrollment_failed",
    "voice_provider_unavailable",
    "voice_mapping_unavailable",
    "provider_unavailable",
}


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


def voice_profile_dto(profile: VoiceProfile) -> VoiceProfileResponse:
    return VoiceProfileResponse(
        id=UUID(profile.id),
        scope=profile.scope,  # type: ignore[arg-type]
        group_id=UUID(profile.group_id) if profile.group_id else None,
        status=profile.status,  # type: ignore[arg-type]
        source_filename=profile.source_filename or "",
        safe_error_code=_safe_error_code(profile.safe_error_code),
        created_at=profile.created_at,
    )


def _scoped_voice_query(context: AuthContext, profile_id: str) -> Any:
    """A group's voices belong to the group, so membership is the whole test.

    A teacher who joined the group is a member like any other; one who has not
    joined is outside it.  See ``scoped_group_role`` for the shared rule.
    """

    return (
        select(VoiceProfile)
        .join(Group, Group.id == VoiceProfile.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .join(
            WorkspaceMember,
            and_(WorkspaceMember.group_id == Group.id, WorkspaceMember.user_id == context.user.id),
        )
        .where(
            VoiceProfile.id == profile_id,
            VoiceProfile.scope == "group",
            CourseMember.user_id == context.user.id,
        )
    )


def visible_student_voice(db: Session, context: AuthContext, profile_id: str) -> ScopedVoice:
    row = db.execute(_scoped_voice_query(context, profile_id)).first()
    if row is None:
        raise not_found()
    return ScopedVoice(row[0], "student")


def list_group_voices(
    db: Session, context: AuthContext, group_id: str
) -> list[VoiceProfileResponse]:
    authorized = db.scalar(
        select(WorkspaceMember.user_id)
        .join(Group, Group.id == WorkspaceMember.group_id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            Group.id == group_id,
            WorkspaceMember.user_id == context.user.id,
            CourseMember.user_id == context.user.id,
        )
    )
    if authorized is None:
        raise not_found()
    profiles = db.scalars(
        select(VoiceProfile)
        .where(VoiceProfile.scope == "group", VoiceProfile.group_id == group_id)
        .order_by(VoiceProfile.created_at, VoiceProfile.id)
    ).all()
    return [voice_profile_dto(profile) for profile in profiles]


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
    profile = db.scalar(
        select(VoiceProfile).where(
            VoiceProfile.id == voice_profile_id,
            VoiceProfile.scope == "group",
            VoiceProfile.group_id == target_group,
            VoiceProfile.status == "ready",
        )
    )
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


def _voice_request_hash(
    context: AuthContext,
    group_id: str,
    source_filename: str,
    source_sha256: str,
    consent_copy_version: str,
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
        },
    )


def _new_recovery_name(profile_id: str) -> str:
    # Qwen-TTS preferred_name accepts only letters/digits/underscore and at
    # most 16 characters. The platform UUID keeps this deterministic for
    # provider-side reconciliation without exposing an external identifier.
    return f"maya{profile_id.replace('-', '')[:12]}"


def _safe_provider_error(exc: Exception) -> PlatformError:
    del exc
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
) -> tuple[VoiceProfile, VoiceProviderOperation]:
    timestamp = now_utc()
    profile_id = str(uuid4())
    profile = VoiceProfile(
        id=profile_id,
        scope="group" if group_id is not None else "system",
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
                "consent_actor_user_id": context.user.id if group_id is not None else None,
                "consent_accepted": group_id is not None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        source_filename=source_filename,
        source_sha256=source_sha256,
        consent_copy_version=consent_copy_version,
        consent_actor_user_id=context.user.id if group_id is not None else None,
        consent_accepted_at=timestamp if group_id is not None else None,
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


def _store_enrollment_success(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    result: VoiceEnrollmentResult,
    settings: Settings,
) -> VoiceProfile:
    operation.safe_request_id = result.request_id
    operation.input_bytes = result.input_bytes
    operation.output_bytes = result.output_bytes
    profile.external_id_encrypted = encrypt_external_voice_id(
        result.external_voice_id,
        settings.secret_bytes,
        profile_id=profile.id,
        scope=profile.scope,
        group_id=profile.group_id,
        provider_key=profile.provider_key,
        target_model_key=profile.target_model_key,
    )
    profile.status = "failed" if result.degraded else "preview_ready"
    profile.safe_error_code = "voice_enrollment_failed" if result.degraded else None
    profile.updated_at = now_utc()
    _finish_operation(db, operation, state="succeeded", output_bytes=result.output_bytes)
    return profile


def _reconcile_enrollment(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    provider: VoiceCloneProvider,
    settings: Settings,
) -> bool:
    """Reconcile an ambiguous create before permitting any second charged call."""

    _record_reconciliation_request(db, operation)
    try:
        result = provider.exists(profile.recovery_name, target_model_key=profile.target_model_key)
    except VoiceProviderError as exc:
        profile.status = "outcome_unknown"
        profile.safe_error_code = "provider_unavailable"
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
        )
        raise _safe_provider_error(exc) from exc
    if not result.visibility_known or len(result.matches) > 1:
        profile.status = "outcome_unknown"
        profile.safe_error_code = "voice_enrollment_failed"
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
        _store_enrollment_success(db, profile, operation, stored, settings)
        return True
    # Zero visible matches are safe to retry only after the provider deadline.
    if now_utc() < _utc(operation.provider_deadline) or operation.attempt >= 2:
        profile.status = "outcome_unknown"
        profile.safe_error_code = "voice_enrollment_failed"
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_enrollment_failed"
        )
        raise PlatformError(
            "voice_enrollment_failed",
            "The voice enrollment outcome needs reconciliation.",
            503,
        )
    operation.state = "prepared"
    profile.status = "enrolling"
    profile.safe_error_code = None
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
    group_id: str,
    consent_accepted: bool,
    consent_copy_version: str | None,
    idempotency_key: str,
    provider: VoiceCloneProvider | None = None,
) -> VoiceProfileResponse | Any:
    """Validate, normalize and enroll one temporary upload."""

    if not consent_accepted:
        upload.cleanup()
        raise validation_failure(
            "Voice enrollment requires consent.", code="voice_enrollment_failed"
        )
    copy_version = (consent_copy_version or CONSENT_COPY_VERSION).strip() or CONSENT_COPY_VERSION
    try:
        provider_instance = provider or voice_provider(settings)
    except BaseException:
        upload.cleanup()
        raise
    try:
        _assert_student_group_access(db, context, group_id)
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
        group_id,
        upload.source_filename,
        upload.sha256,
        copy_version,
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
            )
            db.commit()
        assert profile is not None and operation is not None
        assert_claim_owned(db, record)
        _dispatch_operation(db, operation)
        assert_claim_owned(db, record)
        encoded = base64.b64encode(normalized).decode("ascii")
        data_uri = f"data:audio/wav;base64,{encoded}"
        try:
            provider_result = provider_instance.enroll(
                data_uri,
                recovery_name=profile.recovery_name,
                target_model_key=profile.target_model_key,
                language="en",
            )
        except VoiceProviderTimeout as exc:
            profile.status = "outcome_unknown"
            profile.safe_error_code = "provider_unavailable"
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        except VoiceProviderError as exc:
            # Once the durable dispatch row is committed, a generic provider
            # error is conservatively ambiguous: the request may have been
            # accepted/charged even when the client saw an error.  Keep the
            # operation in reconciliation rather than allowing a same-key
            # retry to issue a second create blindly.
            profile.status = "outcome_unknown"
            profile.safe_error_code = "provider_unavailable"
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        try:
            assert_claim_owned(db, record)
        except PlatformError as exc:
            profile.status = "outcome_unknown"
            profile.safe_error_code = "provider_unavailable"
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        _store_enrollment_success(db, profile, operation, provider_result, settings)
        result = voice_profile_dto(profile)
        finish_idempotency(db, record, 202, result.model_dump(mode="json"))
        db.commit()
        return result
    except PlatformError:
        raise
    except VoiceEncryptionError as exc:
        if profile is not None:
            profile.status = "failed"
            profile.safe_error_code = "voice_mapping_unavailable"
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
