"""Withdraw a student's cloned voices when they leave a group.

Owner decision (2026-10-18): a student moved to another group no longer
lends their voice to the old group. Their group clones there are deleted,
locally in the same transaction as the move and then at the supplier, so the
old groupmates' Agents and Debates fall back to the default voice.

The local part (``withdraw_group_voices``) never calls the supplier: it runs
inside the move's transaction. The supplier part (``finish_withdrawn_voices``)
runs after that transaction commits and is best effort, exactly like a
manual delete: an unconfirmed supplier delete stays ``outcome_unknown``.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Iterable
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import VoiceProfile, VoiceProviderOperation
from app.modules.voices.service import _dispatch_operation, _finish_operation, now_utc
from app.providers.voice import VoiceCloneProvider, VoiceProviderError

LOGGER = logging.getLogger(__name__)


def withdraw_group_voices(db: Session, user_id: str, group_ids: Iterable[str]) -> list[str]:
    """Mark the user's clones in these groups deleted and queue their supplier delete."""

    groups = [group_id for group_id in group_ids if group_id]
    if not groups:
        return []
    profiles = db.scalars(
        select(VoiceProfile).where(
            VoiceProfile.scope == "group",
            VoiceProfile.group_id.in_(groups),
            VoiceProfile.consent_actor_user_id == user_id,
            VoiceProfile.status != "deleted",
        )
    ).all()
    timestamp = now_utc()
    withdrawn: list[str] = []
    for profile in profiles:
        profile.status = "deleted"
        profile.safe_error_code = None
        profile.updated_at = timestamp
        operation = db.scalar(
            select(VoiceProviderOperation).where(
                VoiceProviderOperation.profile_id == profile.id,
                VoiceProviderOperation.operation_type == "delete",
            )
        )
        if operation is None:
            db.add(
                VoiceProviderOperation(
                    id=str(uuid4()),
                    profile_id=profile.id,
                    operation_type="delete",
                    profile_scope=profile.scope,
                    state="prepared",
                    attempt=1,
                    claim_token=secrets.token_urlsafe(32),
                    request_hash=hashlib.sha256(f"withdraw:{profile.id}".encode()).hexdigest(),
                    provider_deadline=timestamp + timedelta(seconds=35),
                    created_at=timestamp,
                    updated_at=timestamp,
                    idempotency_record_id=None,
                )
            )
        else:
            # An earlier delete that never finished is taken over.
            operation.state = "prepared"
            operation.attempt += 1
            operation.claim_token = secrets.token_urlsafe(32)
            operation.idempotency_record_id = None
            operation.provider_deadline = timestamp + timedelta(seconds=35)
            operation.safe_error_code = None
            operation.updated_at = timestamp
        withdrawn.append(profile.id)
    db.flush()
    return withdrawn


def finish_withdrawn_voices(
    db: Session,
    settings: Settings,
    user_id: str,
    *,
    provider: VoiceCloneProvider | None = None,
    profile_ids: list[str] | None = None,
) -> None:
    """After the move commits: remove withdrawn voices at the supplier, best effort."""

    from app.modules.voices.deletion import _remote_voice_ids
    from app.modules.voices.preview import expire_profile_previews

    pending = db.execute(
        select(VoiceProfile, VoiceProviderOperation)
        .join(VoiceProviderOperation, VoiceProviderOperation.profile_id == VoiceProfile.id)
        .where(
            (VoiceProfile.consent_actor_user_id == user_id)
            if profile_ids is None
            else VoiceProfile.id.in_(profile_ids),
            VoiceProfile.scope == "group",
            VoiceProfile.status == "deleted",
            VoiceProviderOperation.operation_type == "delete",
            VoiceProviderOperation.state == "prepared",
            VoiceProviderOperation.idempotency_record_id.is_(None),
        )
    ).all()
    if not pending:
        return
    if provider is None:
        from app.providers.factory import voice_provider

        provider = voice_provider(settings)
    for profile, operation in pending:
        try:
            expire_profile_previews(db, settings.resolved_data_root, profile.id)
            db.commit()
            if profile_ids is not None:
                from app.modules.debates.voice_clones import debates_hold_supplier_voice
                from app.modules.real_delete import hard_delete_voice
                from app.modules.voices.deletion import _delete_is_settled

                if debates_hold_supplier_voice(db, profile, settings):
                    _finish_operation(db, operation, state="succeeded")
                    if _delete_is_settled(db, profile):
                        hard_delete_voice(db, profile, settings.resolved_data_root)
                    db.commit()
                    continue
            try:
                voice_ids, complete = _remote_voice_ids(db, profile, provider, settings)
            except VoiceProviderError:
                voice_ids, complete = [], False
            failed = False
            if voice_ids:
                _dispatch_operation(db, operation)
                for voice_id in voice_ids:
                    try:
                        provider.delete(voice_id, target_model_key=profile.target_model_key)
                    except VoiceProviderError:
                        failed = True
            if failed or not complete:
                LOGGER.warning(
                    "Withdrawn voice left at the supplier for later cleanup profile_id=%s",
                    profile.id,
                )
                _finish_operation(
                    db,
                    operation,
                    state="outcome_unknown",
                    safe_error_code="voice_provider_unavailable",
                )
            else:
                _finish_operation(db, operation, state="succeeded")
                if profile_ids is not None:
                    from app.modules.real_delete import hard_delete_voice
                    from app.modules.voices.deletion import _delete_is_settled

                    if _delete_is_settled(db, profile):
                        hard_delete_voice(db, profile, settings.resolved_data_root)
                        db.commit()
        except Exception:
            # The move itself already committed; never fail it over cleanup.
            db.rollback()
            LOGGER.warning("Voice withdrawal cleanup failed profile_id=%s", profile.id)


__all__ = ["finish_withdrawn_voices", "withdraw_group_voices"]
