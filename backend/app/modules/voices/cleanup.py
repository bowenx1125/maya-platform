"""Drop a voice upload that failed before it became a usable library card.

Owner decision (2026-10-24): a failed Voice upload does not stay in the
library. The upload response already carries the error the owner reads, so
the card is not needed to explain it. An uncharged failure never created a
billed voice, so the profile and its operation rows go away. A charged
failure keeps its operation ledger and only leaves the library (status
``deleted``). A failed card that holds a supplier voice id is left alone: the
supplier voice must be removed through the normal delete first.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import AgentVersion, VoicePreview, VoiceProfile, VoiceProviderOperation
from app.modules.knowledge.recovery import _remove_owned_path

LOGGER = logging.getLogger(__name__)


def discard_failed_voice(
    db: Session,
    profile: VoiceProfile,
    *,
    data_root: Path | None = None,
    safe_error_code: str | None = None,
) -> str:
    """Hide or delete one failed profile. Returns ``deleted``, ``hidden`` or ``kept``."""

    if profile.external_id_encrypted:
        return "kept"
    operations = list(
        db.scalars(
            select(VoiceProviderOperation).where(VoiceProviderOperation.profile_id == profile.id)
        ).all()
    )
    charged = any(operation.charged_request_count > 0 for operation in operations)
    referenced = db.scalar(
        select(AgentVersion.id).where(AgentVersion.voice_profile_id == profile.id).limit(1)
    )
    if charged or referenced is not None:
        _hide(profile, safe_error_code)
        return "hidden"
    nested = db.begin_nested()
    try:
        _unlink_previews(db, profile.id, data_root)
        for operation in operations:
            db.delete(operation)
        db.flush()
        db.delete(profile)
        db.flush()
        nested.commit()
    except IntegrityError:
        nested.rollback()
        LOGGER.info("failed_voice_delete_blocked profile_id=%s", profile.id)
        _hide(profile, safe_error_code)
        return "hidden"
    return "deleted"


def sweep_failed_voices(db: Session, data_root: Path | None = None) -> int:
    """Remove failed voice cards left behind by an earlier request or process."""

    profiles = list(
        db.scalars(
            select(VoiceProfile).where(
                VoiceProfile.status == "failed",
                VoiceProfile.external_id_encrypted.is_(None),
            )
        ).all()
    )
    removed = 0
    for profile in profiles:
        if discard_failed_voice(db, profile, data_root=data_root) in {"deleted", "hidden"}:
            removed += 1
    db.commit()
    if removed:
        LOGGER.info("failed_voice_sweep removed=%d", removed)
    return removed


def _hide(profile: VoiceProfile, safe_error_code: str | None) -> None:
    profile.status = "deleted"
    code = safe_error_code or profile.safe_error_code
    profile.safe_error_code = code or "voice_enrollment_failed"
    profile.updated_at = datetime.now(UTC)


def _unlink_previews(db: Session, profile_id: str, data_root: Path | None) -> None:
    if data_root is None:
        return
    for preview in db.scalars(select(VoicePreview).where(VoicePreview.profile_id == profile_id)):
        _remove_owned_path(data_root, preview.relative_path)
