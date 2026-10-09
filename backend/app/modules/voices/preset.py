"""Supplier preset voices.

A preset is a ready system profile whose supplier voice id is a published
name, not an enrolled clone. It has no group and no consent, and clone
existence or delete calls must not be made for it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import VoiceProfile
from app.modules.voices.crypto import (
    VoiceEncryptionError,
    decrypt_external_voice_id,
    encrypt_external_voice_id,
)
from app.providers.dashscope import PRESET_TTS_MODEL_KEY
from app.seed import seed_uuid

PRESET_KIND = "preset"
ELDRIC_SAGE_VOICE = "Eldric Sage"
ELDRIC_SAGE_DISPLAY_NAME = "Eldric Sage"
ELDRIC_SAGE_RECOVERY_NAME = "preseteldricsage"
# uuid5(SEED_NAMESPACE, "preset-voice-eldricsage"). Stable across reseeds.
ELDRIC_SAGE_PROFILE_ID = "1591eac5-25cf-5eaf-9c79-d639f69d2263"
PRESET_PROVENANCE = json.dumps({"kind": PRESET_KIND}, sort_keys=True, separators=(",", ":"))


class PresetVoiceError(RuntimeError):
    """Safe operator error. The supplier voice id and secret stay private."""


def is_preset_profile(profile: VoiceProfile) -> bool:
    """True only for a row explicitly marked as a supplier preset."""

    raw = profile.provenance_json
    if not isinstance(raw, str) or not raw:
        return False
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("kind") == PRESET_KIND


def _matches(profile: VoiceProfile, settings: Settings) -> bool:
    if (
        profile.id != ELDRIC_SAGE_PROFILE_ID
        or profile.scope != "system"
        or profile.group_id is not None
        or profile.status != "ready"
        or profile.provider_key != "dashscope"
        or profile.target_model_key != PRESET_TTS_MODEL_KEY
        or profile.recovery_name != ELDRIC_SAGE_RECOVERY_NAME
        or profile.display_name != ELDRIC_SAGE_DISPLAY_NAME
        or profile.source_filename is not None
        or profile.source_sha256 is not None
        or profile.consent_copy_version is not None
        or profile.consent_actor_user_id is not None
        or profile.consent_accepted_at is not None
        or not is_preset_profile(profile)
        or not profile.external_id_encrypted
    ):
        return False
    try:
        voice = decrypt_external_voice_id(
            profile.external_id_encrypted,
            settings.secret_bytes,
            profile_id=profile.id,
            scope=profile.scope,
            group_id=profile.group_id,
            provider_key=profile.provider_key,
            target_model_key=profile.target_model_key,
        )
    except VoiceEncryptionError:
        return False
    return voice == ELDRIC_SAGE_VOICE


def ensure_eldricsage_preset(session: Session, settings: Settings) -> str:
    """Insert the Eldric Sage preset, or return it when the same row exists.

    A conflicting row is an error. The function does not call a provider and
    does not rewrite an envelope that already decrypts to the preset voice.
    """

    if seed_uuid("preset-voice-eldricsage") != ELDRIC_SAGE_PROFILE_ID:
        raise PresetVoiceError("preset voice profile id is not the documented value")
    existing = session.get(VoiceProfile, ELDRIC_SAGE_PROFILE_ID)
    if existing is not None:
        if not _matches(existing, settings):
            raise PresetVoiceError("preset voice profile conflicts with an existing row")
        return existing.id
    occupied = session.scalar(
        select(VoiceProfile.id).where(VoiceProfile.recovery_name == ELDRIC_SAGE_RECOVERY_NAME)
    )
    if occupied is not None:
        raise PresetVoiceError("preset voice profile conflicts with an existing row")
    timestamp = datetime.now(UTC)
    profile = VoiceProfile(
        id=ELDRIC_SAGE_PROFILE_ID,
        scope="system",
        group_id=None,
        display_name=ELDRIC_SAGE_DISPLAY_NAME,
        status="ready",
        provider_key="dashscope",
        target_model_key=PRESET_TTS_MODEL_KEY,
        external_id_encrypted=None,
        recovery_name=ELDRIC_SAGE_RECOVERY_NAME,
        provenance_json=PRESET_PROVENANCE,
        source_filename=None,
        source_sha256=None,
        consent_copy_version=None,
        consent_actor_user_id=None,
        consent_accepted_at=None,
        safe_error_code=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    profile.external_id_encrypted = encrypt_external_voice_id(
        ELDRIC_SAGE_VOICE,
        settings.secret_bytes,
        profile_id=profile.id,
        scope=profile.scope,
        group_id=profile.group_id,
        provider_key=profile.provider_key,
        target_model_key=profile.target_model_key,
    )
    session.add(profile)
    try:
        session.flush()
    except IntegrityError as exc:
        raise PresetVoiceError("preset voice profile conflicts with an existing row") from exc
    return profile.id
