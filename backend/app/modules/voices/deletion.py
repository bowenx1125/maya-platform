"""Provider deletion saga for group VoiceProfiles.

Deletion is kept separate from enrollment because an external delete is
irreversible while enrollment must reconcile a potentially charged create.
The durable ledger and claim-token helpers remain the single persistence
boundary used by both operations.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, invalid_state, not_found
from app.core.models import VoiceProfile, VoiceProviderOperation
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import (
    abandon_claim,
    assert_claim_owned,
    claim_idempotency,
    finish_idempotency,
    request_hash,
)
from app.modules.voices.preset import is_preset_profile
from app.modules.voices.preview import expire_profile_previews
from app.modules.voices.service import (
    _claim_provider_operation,
    _dispatch_operation,
    _finish_operation,
    _record_reconciliation_request,
    _safe_provider_error,
    _tts_external_id,
    _utc,
    now_utc,
    visible_student_voice,
    voice_profile_dto,
)
from app.providers.voice import VoiceCloneProvider, VoiceProviderError, VoiceProviderTimeout


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
    operation.profile_scope = "group"
    operation.updated_at = now_utc()
    profile.status = "deleting"
    profile.safe_error_code = None
    db.commit()
    return False


def delete_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
    *,
    idempotency_key: str,
    provider: VoiceCloneProvider | None = None,
) -> Any:
    """Delete one group voice with durable dispatch and reconciliation."""

    scoped = visible_student_voice(db, context, profile_id)
    profile = scoped.profile
    # A preset is a published supplier name, not an enrolled clone. Students
    # cannot delete it, and this path must not ask the clone API about it.
    if is_preset_profile(profile) or profile.scope != "group":
        raise not_found()
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
                "provider_unavailable", "The delete outcome needs reconciliation.", 503
            ) from exc
        raise
    if replay is not None:
        return replay
    assert_claim_owned(db, record)
    from app.providers.factory import voice_provider

    provider_instance = provider or voice_provider(settings)
    profile_operation = db.scalar(
        select(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.profile_id == profile.id,
            VoiceProviderOperation.operation_type == "delete",
        )
        .order_by(VoiceProviderOperation.created_at)
    )
    if profile_operation is not None and profile_operation.idempotency_record_id != record.id:
        if profile_operation.state == "succeeded" or profile.status == "deleted":
            result = voice_profile_dto(profile)
            finish_idempotency(db, record, 200, result.model_dump(mode="json"))
            db.commit()
            return result
        abandon_claim(db, record)
        raise PlatformError("provider_unavailable", "The delete outcome needs reconciliation.", 503)
    existing_operation = profile_operation
    operation: VoiceProviderOperation
    if existing_operation is not None:
        operation = existing_operation
        existing_profile = db.get(VoiceProfile, operation.profile_id)
        if existing_profile is None:
            raise invalid_state("The voice deletion record is unavailable.")
        profile = existing_profile
        if operation.state == "succeeded":
            result = voice_profile_dto(profile)
            finish_idempotency(db, record, 200, result.model_dump(mode="json"))
            db.commit()
            return result
        if operation.state in {"dispatched", "reconciling", "outcome_unknown"}:
            _claim_provider_operation(db, operation, record.claim_token)
            if _reconcile_delete(db, profile, operation, provider_instance):
                result = voice_profile_dto(profile)
                finish_idempotency(db, record, 200, result.model_dump(mode="json"))
                db.commit()
                return result
            _claim_provider_operation(db, operation, record.claim_token)
        elif operation.state == "failed":
            if operation.request_count != 0:
                abandon_claim(db, record)
                raise PlatformError(
                    "provider_unavailable", "The delete outcome needs reconciliation.", 503
                )
            timestamp = now_utc()
            operation.state = "prepared"
            operation.attempt += 1
            operation.claim_token = record.claim_token
            operation.provider_deadline = timestamp + timedelta(seconds=35)
            operation.updated_at = timestamp
            profile.status = "deleting"
            profile.updated_at = timestamp
            db.commit()
    else:
        if profile.status == "deleted":
            result = voice_profile_dto(profile)
            finish_idempotency(db, record, 200, result.model_dump(mode="json"))
            db.commit()
            return result
        if profile.status in {"deleting", "outcome_unknown"}:
            abandon_claim(db, record)
            raise PlatformError(
                "provider_unavailable", "The delete outcome needs reconciliation.", 503
            )
        timestamp = now_utc()
        previous_status = profile.status
        changed = db.execute(
            update(VoiceProfile)
            .where(
                VoiceProfile.id == profile.id,
                VoiceProfile.status == previous_status,
                VoiceProfile.status.not_in(("deleting", "outcome_unknown", "deleted")),
            )
            .values(status="deleting", updated_at=timestamp)
        )
        if getattr(changed, "rowcount", 0) != 1:
            db.rollback()
            current = db.get(VoiceProfile, profile.id)
            concurrent_operation = db.scalar(
                select(VoiceProviderOperation).where(
                    VoiceProviderOperation.profile_id == profile.id,
                    VoiceProviderOperation.operation_type == "delete",
                )
            )
            if current is not None and (
                current.status == "deleted"
                or (concurrent_operation is not None and concurrent_operation.state == "succeeded")
            ):
                result = voice_profile_dto(current)
                finish_idempotency(db, record, 200, result.model_dump(mode="json"))
                db.commit()
                return result
            abandon_claim(db, record)
            raise PlatformError(
                "provider_unavailable", "The delete outcome needs reconciliation.", 503
            )
        operation = VoiceProviderOperation(
            id=str(uuid4()),
            profile_id=profile.id,
            operation_type="delete",
            profile_scope="group",
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
        except IntegrityError as exc:
            db.rollback()
            abandon_claim(db, record)
            raise PlatformError(
                "provider_unavailable", "The delete outcome needs reconciliation.", 503
            ) from exc
    try:
        external_id = _tts_external_id(profile, settings)
    except PlatformError:
        # No provider request was made, so this is a deterministic local
        # mapping failure rather than an ambiguous delete.
        profile.status = "failed"
        profile.safe_error_code = "voice_mapping_unavailable"
        try:
            _finish_operation(
                db,
                operation,
                state="failed",
                safe_error_code="voice_mapping_unavailable",
            )
        except PlatformError:
            db.rollback()
        try:
            abandon_claim(db, record)
        except PlatformError:
            db.rollback()
        raise
    try:
        _dispatch_operation(db, operation)
        try:
            provider_instance.delete(external_id, target_model_key=profile.target_model_key)
        except VoiceProviderTimeout as exc:
            profile.status = "outcome_unknown"
            profile.safe_error_code = "provider_unavailable"
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        except VoiceProviderError as exc:
            profile.status = "outcome_unknown"
            profile.safe_error_code = "voice_provider_unavailable"
            _finish_operation(
                db, operation, state="outcome_unknown", safe_error_code="voice_provider_unavailable"
            )
            raise _safe_provider_error(exc) from exc
        profile.status = "deleted"
        profile.safe_error_code = None
        profile.updated_at = now_utc()
        expire_profile_previews(db, settings.resolved_data_root, profile.id)
        _finish_operation(db, operation, state="succeeded")
        result = voice_profile_dto(profile)
        finish_idempotency(db, record, 200, result.model_dump(mode="json"))
        db.commit()
        return result
    except PlatformError:
        raise
    finally:
        external_id = ""
