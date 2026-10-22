"""Drop a voice the supplier refused before it became a library card.

An uncharged refusal never created a billed voice, so the profile and its
operation rows go away. The idempotency record stays and still replays the
refusal. A charged refusal keeps its operation ledger and only leaves the
library (status ``deleted``).
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


def discard_rejected_voice(
    db: Session,
    profile: VoiceProfile,
    *,
    data_root: Path | None = None,
) -> str:
    """Hide or delete one refused profile. Returns ``deleted`` or ``hidden``."""

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
        _hide(profile)
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
        LOGGER.info("rejected_voice_delete_blocked profile_id=%s", profile.id)
        _hide(profile)
        return "hidden"
    return "deleted"


def sweep_rejected_voices(db: Session, data_root: Path | None = None) -> int:
    """Remove refused voice cards left behind by an earlier process."""

    profiles = list(
        db.scalars(
            select(VoiceProfile).where(
                VoiceProfile.status == "failed",
                VoiceProfile.safe_error_code == "voice_clone_refused",
            )
        ).all()
    )
    removed = 0
    for profile in profiles:
        if discard_rejected_voice(db, profile, data_root=data_root) in {"deleted", "hidden"}:
            removed += 1
    db.commit()
    return removed


def _hide(profile: VoiceProfile) -> None:
    profile.status = "deleted"
    profile.safe_error_code = profile.safe_error_code or "voice_clone_refused"
    profile.updated_at = datetime.now(UTC)


def _unlink_previews(db: Session, profile_id: str, data_root: Path | None) -> None:
    if data_root is None:
        return
    for preview in db.scalars(select(VoicePreview).where(VoicePreview.profile_id == profile_id)):
        _remove_owned_path(data_root, preview.relative_path)
