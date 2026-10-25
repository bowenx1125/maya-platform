"""Provider deletion saga for group VoiceProfiles.

Deletion is kept separate from enrollment because an external delete is
irreversible while enrollment must reconcile a potentially charged create.
The durable ledger and claim-token helpers remain the single persistence
boundary used by both operations.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, not_found
from app.core.models import IdempotencyRecord, VoiceProfile, VoiceProviderOperation
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    abandon_claim,
    assert_claim_owned,
    claim_idempotency,
    finish_idempotency,
    renew_idempotency_lease,
    request_hash,
)
from app.modules.voices.preset import is_preset_profile
from app.modules.voices.preview import expire_profile_previews
from app.modules.voices.service import (
    _dispatch_operation,
    _finish_operation,
    _record_reconciliation_request,
    _safe_provider_error,
    _tts_external_id,
    _utc,
    log_course_teacher_voice_action,
    now_utc,
    visible_student_voice,
    voice_profile_dto,
)
from app.providers.voice import VoiceCloneProvider, VoiceProviderError

LOGGER = logging.getLogger(__name__)


def _delete_operation_hash(context: AuthContext, profile_id: str) -> str:
    return request_hash(
        "deleteVoiceProfile", context.user.id, [profile_id], {"profile_id": profile_id}
    )


def _reconcile_delete(
    db: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    provider: VoiceCloneProvider,
) -> bool:
    """Reconcile an ambiguous delete before permitting its one retry."""

    if is_preset_profile(profile):
        raise not_found()
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
        profile.safe_error_code = "voice_provider_unavailable"
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_provider_unavailable"
        )
        raise PlatformError(
            "provider_unavailable",
            "The delete outcome needs reconciliation.",
            503,
        )
    if len(result.matches) == 0:
        profile.status = "deleted"
        profile.safe_error_code = None
        profile.updated_at = now_utc()
        _finish_operation(db, operation, state="succeeded")
        return True
    if now_utc() < _utc(operation.provider_deadline) or operation.attempt >= 2:
        profile.status = "outcome_unknown"
        profile.safe_error_code = "voice_provider_unavailable"
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_provider_unavailable"
        )
        raise PlatformError(
            "provider_unavailable",
            "The delete outcome needs reconciliation.",
            503,
        )
    operation.state = "prepared"
    operation.attempt += 1
    operation.profile_scope = profile.scope
    operation.updated_at = now_utc()
    profile.status = "deleting"
    profile.safe_error_code = None
    db.commit()
    return False


DELETE_LEASE_SECONDS = 120


def _owner_is_live(db: Session, operation: VoiceProviderOperation) -> bool:
    """True when another request still holds the lease on this delete."""

    if operation.idempotency_record_id is None:
        return False
    owner = db.get(IdempotencyRecord, operation.idempotency_record_id)
    if owner is None or owner.state != "pending":
        return False
    return _utc(owner.lease_expires_at) > now_utc()


def _soft_delete(db: Session, profile: VoiceProfile, settings: Settings) -> None:
    """The card goes now, whatever state the voice was in."""

    if profile.status != "deleted":
        profile.status = "deleted"
        profile.safe_error_code = None
        profile.updated_at = now_utc()
    expire_profile_previews(db, settings.resolved_data_root, profile.id)
    db.commit()


def _enrollment_may_have_reached_provider(db: Session, profile: VoiceProfile) -> bool:
    return (
        db.scalar(
            select(VoiceProviderOperation.id).where(
                VoiceProviderOperation.profile_id == profile.id,
                VoiceProviderOperation.operation_type == "enroll",
                (VoiceProviderOperation.request_count > 0)
                | VoiceProviderOperation.state.in_(
                    ("dispatched", "reconciling", "outcome_unknown")
                ),
            )
        )
        is not None
    )


def _enrollment_unresolved(db: Session, profile: VoiceProfile) -> bool:
    """An enrollment whose supplier outcome is still unknown.

    A delete that ran while the supplier was still creating the voice can
    succeed with nothing to find; the voice may appear afterwards. While the
    enrollment stays unresolved, a later delete must look again.
    """

    return (
        db.scalar(
            select(VoiceProviderOperation.id).where(
                VoiceProviderOperation.profile_id == profile.id,
                VoiceProviderOperation.operation_type == "enroll",
                VoiceProviderOperation.state.in_(("dispatched", "reconciling")),
            )
        )
        is not None
    )


def _remote_voice_ids(
    db: Session,
    profile: VoiceProfile,
    provider: VoiceCloneProvider,
    settings: Settings,
) -> tuple[list[str], bool]:
    """The supplier voices to delete, and whether that list is complete.

    A stored id is used directly. Without one (an enrollment whose outcome was
    never learned, or an id that cannot be decrypted), the supplier is asked
    for voices carrying this profile's recovery name.
    """

    if profile.external_id_encrypted:
        try:
            return [_tts_external_id(profile, settings)], True
        except PlatformError:
            pass
    elif not _enrollment_may_have_reached_provider(db, profile):
        # Refused or failed before the supplier returned a voice: nothing
        # exists remotely, only the card goes.
        return [], True
    result = provider.exists(profile.recovery_name, target_model_key=profile.target_model_key)
    if len(result.matches) > 1:
        # The recovery name is a short prefix of the profile id and the
        # supplier matches it as a substring, so several matches may include
        # another profile's voice. Delete none and leave the outcome unknown.
        return [], False
    return list(result.matches), result.visibility_known


def _delete_is_settled(db: Session, profile: VoiceProfile) -> bool:
    """True once no later supplier create can resurrect this voice.

    An unresolved enrollment, or a delete the supplier has not confirmed, keeps
    the row so a later delete can finish the cleanup. A confirmed delete removes
    the row and its sample.
    """

    if _enrollment_unresolved(db, profile):
        return False
    operation = db.scalar(
        select(VoiceProviderOperation.id).where(
            VoiceProviderOperation.profile_id == profile.id,
            VoiceProviderOperation.operation_type == "delete",
            VoiceProviderOperation.state != "succeeded",
        )
    )
    return operation is None


def delete_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
    *,
    idempotency_key: str,
    provider: VoiceCloneProvider | None = None,
) -> Any:
    """Delete one voice in any state: soft-delete locally, then clean up remotely.

    Every status can be deleted, including enrolling, failed, refused,
    outcome_unknown and a delete already in progress. The profile becomes
    ``deleted`` before any supplier call, so a slow or failing supplier never
    keeps the card on screen. The supplier delete is best effort: a stored id
    is deleted directly; an unknown id is looked up by recovery name. When the
    supplier cannot confirm, the delete operation stays ``outcome_unknown`` so
    a later delete (or enrollment completion) can finish the cleanup.
    """

    # Claim before the lookup so a completed delete still replays after the
    # row is gone. A new key for a missing voice abandons the claim and 404s.
    body_hash = _delete_operation_hash(context, profile_id)
    try:
        record, replay = claim_idempotency(
            db,
            context,
            "deleteVoiceProfile",
            idempotency_key,
            body_hash,
            data_root=settings.resolved_data_root,
        )
    except PlatformError as exc:
        if exc.status_code == 409:
            raise PlatformError(
                "provider_unavailable", "The delete is already in progress.", 503
            ) from exc
        raise
    if replay is not None:
        return replay
    assert_claim_owned(db, record)
    try:
        scoped = visible_student_voice(db, context, profile_id)
    except PlatformError:
        abandon_claim(db, record)
        raise
    log_course_teacher_voice_action(scoped, context, "delete")
    profile = scoped.profile
    # A preset is a published supplier name, not an enrolled clone. Students
    # cannot delete it, and this path must not ask the clone API about it.
    if is_preset_profile(profile) or profile.scope not in {"group", "personal"}:
        abandon_claim(db, record)
        raise not_found()
    # A supplier lookup plus delete can outlast the default 10 s lease.
    renew_idempotency_lease(db, record, lease_seconds=DELETE_LEASE_SECONDS)
    profile_id = profile.id
    current = db.get(VoiceProfile, profile_id)
    if current is None:
        raise not_found()
    profile = current
    from app.providers.factory import voice_provider

    provider_instance = provider or voice_provider(settings)
    from app.modules.agents.cascade import affected_agents, bump_agent

    for item in affected_agents(db, voice_profile_ids=[profile.id]):
        try:
            bump_agent(db, settings, item.agent_id, drop_voice_profile_ids=[profile.id])
        except Exception:
            LOGGER.exception("voice_delete_cascade_failed agent_id=%s", item.agent_id)
            db.rollback()
    current = db.get(VoiceProfile, profile_id)
    if current is None:
        raise not_found()
    profile = current

    def finish(result_profile: VoiceProfile, *, remove: bool = True) -> Any:
        result = voice_profile_dto(result_profile)
        if remove and _delete_is_settled(db, result_profile):
            from app.modules.real_delete import hard_delete_voice

            hard_delete_voice(db, result_profile, settings.resolved_data_root)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.commit()
        return result

    operation = db.scalar(
        select(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.profile_id == profile.id,
            VoiceProviderOperation.operation_type == "delete",
        )
        .order_by(VoiceProviderOperation.created_at)
    )
    enrollment_unknown = (
        db.scalar(
            select(VoiceProviderOperation.id).where(
                VoiceProviderOperation.profile_id == profile.id,
                VoiceProviderOperation.operation_type == "enroll",
                VoiceProviderOperation.state == "outcome_unknown",
            )
        )
        is not None
    )
    if (
        operation is not None
        and operation.state == "succeeded"
        and not _enrollment_unresolved(db, profile)
        and not enrollment_unknown
    ):
        # A delete that succeeded while enrollment was still in flight found
        # nothing. Once that enrollment is outcome_unknown the supplier voice
        # may exist, so a later delete has to look again.
        _soft_delete(db, profile, settings)
        return finish(profile)
    if operation is None and profile.status == "deleted":
        return finish(profile)
    if (
        operation is not None
        and operation.idempotency_record_id != record.id
        and _owner_is_live(db, operation)
    ):
        # Another request is deleting this voice at the supplier right now. A
        # repeat delete is idempotent: the card goes, and the live request
        # keeps the single supplier command.
        _soft_delete(db, profile, settings)
        return finish(profile, remove=False)

    timestamp = now_utc()
    if operation is None:
        operation = VoiceProviderOperation(
            id=str(uuid4()),
            profile_id=profile.id,
            operation_type="delete",
            profile_scope=profile.scope,
            state="prepared",
            attempt=1,
            claim_token=record.claim_token,
            request_hash=body_hash,
            provider_deadline=timestamp + timedelta(seconds=35),
            created_at=timestamp,
            updated_at=timestamp,
            idempotency_record_id=record.id,
        )
        db.add(operation)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent delete created the operation first and owns the
            # supplier command; this one only removes the card.
            db.rollback()
            current = db.get(VoiceProfile, profile_id)
            if current is None:
                raise not_found() from None
            _soft_delete(db, current, settings)
            return finish(current, remove=False)
    else:
        # Take over an abandoned delete (its request died or timed out),
        # including one stuck in outcome_unknown.
        operation.state = "prepared"
        operation.attempt += 1
        operation.claim_token = record.claim_token
        operation.idempotency_record_id = record.id
        operation.profile_scope = profile.scope
        operation.provider_deadline = timestamp + timedelta(seconds=35)
        operation.safe_error_code = None
        operation.updated_at = timestamp
        db.commit()

    from app.modules.debates.voice_clones import debates_hold_supplier_voice

    # Decided under the voice lock, which the soft delete's commit releases:
    # a Debate create waiting on it then sees this Voice gone and copies none.
    held = debates_hold_supplier_voice(db, profile, settings)
    _soft_delete(db, profile, settings)
    if held:
        # The supplier voice now belongs to the Debates that copied it; the
        # last of them to be deleted removes it at the supplier.
        LOGGER.info("Voice delete kept the supplier voice for Debates profile_id=%s", profile.id)
        _finish_operation(db, operation, state="succeeded")
        return finish(profile)

    try:
        voice_ids, complete = _remote_voice_ids(db, profile, provider_instance, settings)
    except VoiceProviderError:
        LOGGER.warning(
            "Voice delete left the supplier voice for later cleanup profile_id=%s "
            "safe_code=voice_provider_unavailable",
            profile.id,
        )
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_provider_unavailable"
        )
        return finish(profile)
    remote_failed = False
    if voice_ids:
        _dispatch_operation(db, operation)
        for voice_id in voice_ids:
            try:
                provider_instance.delete(voice_id, target_model_key=profile.target_model_key)
            except VoiceProviderError:
                remote_failed = True
        voice_ids = []
    if remote_failed or not complete:
        LOGGER.warning(
            "Voice delete left the supplier voice for later cleanup profile_id=%s "
            "safe_code=voice_provider_unavailable",
            profile.id,
        )
        _finish_operation(
            db, operation, state="outcome_unknown", safe_error_code="voice_provider_unavailable"
        )
    else:
        _finish_operation(db, operation, state="succeeded")
    return finish(profile)
