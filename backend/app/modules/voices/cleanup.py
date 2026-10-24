"""Drop a voice upload that failed before it became a usable library card.

Owner decision (2026-10-24): a failed Voice upload does not stay in the
library. The upload response already carries the error the owner reads, so
the card is not needed to explain it. Deletion is real (#242): the profile,
its operation rows and its stored sample go. A failed card that holds a
supplier voice id is left alone: the supplier voice must be removed through
the normal delete first.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import VoicePreview, VoiceProfile
from app.modules.deferred_files import unlink_after_commit

LOGGER = logging.getLogger(__name__)


def discard_failed_voice(
    db: Session,
    profile: VoiceProfile,
    *,
    data_root: Path | None = None,
) -> str:
    """Delete one failed profile. Returns ``deleted`` or ``kept``."""

    if profile.external_id_encrypted:
        return "kept"
    from app.modules.real_delete import hard_delete_voice

    nested = db.begin_nested()
    try:
        _unlink_previews(db, profile.id, data_root)
        hard_delete_voice(db, profile, data_root)
        nested.commit()
    except IntegrityError:
        nested.rollback()
        LOGGER.warning("failed_voice_delete_blocked profile_id=%s", profile.id)
        return "kept"
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
        if discard_failed_voice(db, profile, data_root=data_root) == "deleted":
            removed += 1
    db.commit()
    if removed:
        LOGGER.info("failed_voice_sweep removed=%d", removed)
    return removed


def _unlink_previews(db: Session, profile_id: str, data_root: Path | None) -> None:
    for preview in db.scalars(select(VoicePreview).where(VoicePreview.profile_id == profile_id)):
        unlink_after_commit(db, data_root, preview.relative_path)
