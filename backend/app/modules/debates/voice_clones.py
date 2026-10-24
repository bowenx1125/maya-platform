"""Debate-owned provider voice clones (2026-10-20).

A Debate speaks with its own independent clone, created from the platform
Voice's retained enrollment sample, so deleting or changing the platform
Voice never changes a Debate's audio.

* ``request_debate_clones`` (in the create transaction) adds one ``pending``
  row per distinct voiced participant voice. Debate creation never waits for
  or fails on the provider.
* ``sweep_debate_voice_clones`` (startup + periodic, advisory lock) enrolls
  pending ``create`` rows with bounded retries and deletes the provider voice
  of clones whose Debate row is gone. ``backfill`` rows are only enrolled by
  the explicit backfill script.
* Until a clone is ready, audio uses the platform Voice it was copied from
  while it still exists (the same voice); see ``resolve_debate_clone``.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.models import StoredFile, VoiceProfile
from app.modules.debates.models import Debate, DebateParticipant, DebateVoiceClone
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.voices.crypto import (
    VoiceEncryptionError,
    decrypt_external_voice_id,
    encrypt_external_voice_id,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
_SWEEP_LOCK_KEY = 0x6D617961_766F6963  # "mayavoic"
CLONE_SCOPE = "debate"


def _now() -> datetime:
    return datetime.now(UTC)


def clone_recovery_name(clone_id: str) -> str:
    # Provider prefixes accept lowercase letters/digits, fewer than ten.
    return f"d{clone_id.replace('-', '')[:8]}"


def source_voice_id(row: Any) -> str | None:
    """The platform Voice a participant was frozen with, even after delete."""

    if getattr(row, "effective_voice_kind", None) != "platform_profile":
        return None
    if getattr(row, "effective_voice_profile_id", None):
        return str(row.effective_voice_profile_id)
    raw = getattr(row, "voice_snapshot_json", None)
    if raw:
        value = json.loads(raw).get("voice_profile_id")
        return str(value) if value else None
    return None


def retain_voice_sample(
    db: Session, data_root: Path, profile: VoiceProfile, wav: bytes, language: str
) -> None:
    """Keep the normalized enrollment sample for Debate clones."""

    relative = f"voice-samples/{profile.id}.wav"
    digest, size = write_atomic(data_root, relative, wav)
    now = _now()
    stored = StoredFile(
        id=str(uuid4()),
        kind="voice_sample",
        relative_path=relative,
        sha256=digest,
        size_bytes=size,
        state="active",
        created_at=now,
        updated_at=now,
    )
    db.add(stored)
    db.flush()
    profile.sample_file_id = stored.id
    profile.sample_language = language


def _owned_sample(db: Session, profile: VoiceProfile, data_root: Path | None) -> str | None:
    """Copy the enrollment sample so deleting the platform Voice can remove its file."""

    if data_root is None or not profile.sample_file_id:
        return None
    source = db.get(StoredFile, profile.sample_file_id)
    if source is None:
        return None
    try:
        wav = contained_path(data_root, source.relative_path).read_bytes()
    except OSError:
        logger.warning("debate_voice_clone_sample_unreadable profile=%s", profile.id)
        return None
    file_id = str(uuid4())
    relative = f"debate-voice-samples/{file_id}.wav"
    digest, size = write_atomic(data_root, relative, wav)
    now = _now()
    db.add(
        StoredFile(
            id=file_id,
            kind="voice_sample",
            relative_path=relative,
            sha256=digest,
            size_bytes=size,
            state="active",
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    return file_id


def request_debate_clones(
    db: Session,
    debate_id: str,
    participants: list[Any],
    *,
    origin: str = "create",
    data_root: Path | None = None,
) -> list[DebateVoiceClone]:
    """Add pending clone rows for a Debate's voiced participants (idempotent)."""

    created: list[DebateVoiceClone] = []
    existing = set(
        db.scalars(
            select(DebateVoiceClone.source_voice_profile_id).where(
                DebateVoiceClone.debate_id == debate_id
            )
        ).all()
    )
    for row in participants:
        voice_id = source_voice_id(row)
        if voice_id is None or voice_id in existing:
            continue
        existing.add(voice_id)
        profile = db.get(VoiceProfile, voice_id)
        snapshot = json.loads(getattr(row, "voice_snapshot_json", None) or "{}")
        provider_key = profile.provider_key if profile else snapshot.get("provider_key")
        model = profile.target_model_key if profile else snapshot.get("target_model_key")
        if not provider_key or not model:
            continue
        sample = _owned_sample(db, profile, data_root) if profile is not None else None
        clone_id = str(uuid4())
        now = _now()
        clone = DebateVoiceClone(
            id=clone_id,
            debate_id=debate_id,
            source_voice_profile_id=voice_id,
            origin=origin,
            status="pending" if sample else "no_sample",
            provider_key=str(provider_key),
            target_model_key=str(model),
            sample_file_id=sample,
            sample_language=profile.sample_language if profile is not None else None,
            recovery_name=clone_recovery_name(clone_id),
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        db.add(clone)
        created.append(clone)
    db.flush()
    return created


def resolve_debate_clone(
    db: Any, debate_id: str, voice_id: str, settings: Any
) -> tuple[str, str] | None:
    """(provider token, model) of a ready Debate clone, else None."""

    row = (
        db.execute(
            text(
                "SELECT id, provider_key, target_model_key, external_id_encrypted "
                "FROM debate_voice_clones WHERE debate_id=:d AND "
                "source_voice_profile_id=:v AND status='ready'"
            ),
            {"d": debate_id, "v": voice_id},
        )
        .mappings()
        .first()
    )
    if row is None or not row["external_id_encrypted"]:
        return None
    try:
        token = decrypt_external_voice_id(
            row["external_id_encrypted"],
            settings.secret_bytes,
            profile_id=str(row["id"]),
            scope=CLONE_SCOPE,
            group_id=None,
            provider_key=row["provider_key"],
            target_model_key=row["target_model_key"],
        )
    except VoiceEncryptionError:
        return None
    return token, str(row["target_model_key"])


def resolve_snapshot_voice(participant: Any, settings: Any) -> tuple[str, str] | None:
    """(provider token, model) from the supplier id frozen into the participant.

    A Voice uploaded before samples were kept cannot be cloned for a Debate.
    Its Debates speak with the supplier voice the snapshot names; deleting the
    platform Voice keeps that supplier voice while they need it.
    """

    from app.providers.dashscope import LEGACY_CLONE_MODEL_KEY

    raw = getattr(participant, "voice_snapshot_json", None)
    cipher = getattr(participant, "voice_external_id_encrypted", None)
    if not raw or not cipher:
        return None
    try:
        snapshot = json.loads(raw)
    except ValueError:
        return None
    profile_id = snapshot.get("voice_profile_id")
    model = snapshot.get("target_model_key")
    provider_key = snapshot.get("provider_key")
    if not profile_id or not isinstance(model, str) or not model:
        return None
    if model == LEGACY_CLONE_MODEL_KEY:
        return None
    if getattr(settings, "tts_provider", "mock") == "mock":
        return str(profile_id), model
    if provider_key != "dashscope":
        return None
    try:
        token = decrypt_external_voice_id(
            bytes(cipher),
            settings.secret_bytes,
            profile_id=str(profile_id),
            scope=str(snapshot.get("scope") or ""),
            group_id=snapshot.get("group_id"),
            provider_key=provider_key,
            target_model_key=model,
        )
    except VoiceEncryptionError:
        return None
    return token, model


def debates_need_supplier_voice(db: Session, profile_id: str) -> bool:
    """True while a Debate without its own clone still speaks with this Voice."""

    covered = select(DebateVoiceClone.debate_id).where(
        DebateVoiceClone.source_voice_profile_id == profile_id,
        DebateVoiceClone.status.in_(("ready", "pending")),
    )
    return (
        db.scalar(
            select(DebateParticipant.id)
            .where(
                DebateParticipant.effective_voice_profile_id == profile_id,
                DebateParticipant.voice_external_id_encrypted.is_not(None),
                DebateParticipant.debate_id.not_in(covered),
            )
            .limit(1)
        )
        is not None
    )


def enroll_clone(
    db: Session, clone: DebateVoiceClone, *, data_root: Path, settings: Any, provider: Any
) -> bool:
    """One enrollment attempt; True when the clone became ready."""

    from app.providers.voice import VoiceCloneRefusedError

    sample = db.get(StoredFile, clone.sample_file_id) if clone.sample_file_id else None
    if sample is None:
        clone.status = "no_sample"
        clone.updated_at = _now()
        return False
    clone.attempts += 1
    clone.updated_at = _now()
    try:
        wav = contained_path(data_root, sample.relative_path).read_bytes()
        data_uri = "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii")
        result = provider.enroll(
            data_uri,
            recovery_name=clone.recovery_name,
            target_model_key=clone.target_model_key,
            language=clone.sample_language or "en",
        )
    except VoiceCloneRefusedError:
        clone.status = "failed"
        clone.safe_error_code = "voice_clone_refused"
        return False
    except Exception:  # noqa: BLE001 - provider/file errors retry, bounded
        logger.warning("debate_voice_clone_enroll_failed clone=%s", clone.id)
        clone.safe_error_code = "provider_unavailable"
        if clone.attempts >= MAX_ATTEMPTS:
            clone.status = "failed"
        return False
    if not result.external_voice_id or result.degraded:
        clone.safe_error_code = "voice_clone_degraded"
        if clone.attempts >= MAX_ATTEMPTS:
            clone.status = "failed"
        return False
    clone.external_id_encrypted = encrypt_external_voice_id(
        result.external_voice_id,
        settings.secret_bytes,
        profile_id=clone.id,
        scope=CLONE_SCOPE,
        group_id=None,
        provider_key=clone.provider_key,
        target_model_key=clone.target_model_key,
    )
    clone.status = "ready"
    clone.safe_error_code = None
    return True


def _delete_orphan(db: Session, clone: DebateVoiceClone, *, settings: Any, provider: Any) -> None:
    if clone.status == "ready" and clone.external_id_encrypted:
        external = decrypt_external_voice_id(
            clone.external_id_encrypted,
            settings.secret_bytes,
            profile_id=clone.id,
            scope=CLONE_SCOPE,
            group_id=None,
            provider_key=clone.provider_key,
            target_model_key=clone.target_model_key,
        )
        provider.delete(external, target_model_key=clone.target_model_key)
    db.delete(clone)


def sweep_debate_voice_clones(
    db: Session, *, data_root: Path, settings: Any, provider: Any, origin: str = "create"
) -> dict[str, int]:
    """Enroll pending clones and delete clones of deleted Debates."""

    counts = {"ready": 0, "pending": 0, "deleted": 0}
    if db.get_bind().dialect.name == "postgresql":
        if not db.execute(
            text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _SWEEP_LOCK_KEY}
        ).scalar():
            return counts
    orphans = db.scalars(
        select(DebateVoiceClone).where(DebateVoiceClone.debate_id.not_in(select(Debate.id)))
    ).all()
    for clone in orphans:
        try:
            _delete_orphan(db, clone, settings=settings, provider=provider)
            counts["deleted"] += 1
        except Exception:  # noqa: BLE001 - keep the row, retry next sweep
            logger.warning("debate_voice_clone_delete_failed clone=%s", clone.id)
    db.commit()
    pending = db.scalars(
        select(DebateVoiceClone).where(
            DebateVoiceClone.status == "pending", DebateVoiceClone.origin == origin
        )
    ).all()
    for clone in pending:
        if enroll_clone(db, clone, data_root=data_root, settings=settings, provider=provider):
            counts["ready"] += 1
        else:
            counts["pending"] += 1
        db.commit()
    return counts


def sync_debate_clones(db: Session, debate_id: str, *, data_root: Path | None = None) -> None:
    """Match clone rows to the Debate's current voiced participants.

    A clone no longer needed (a draft changed its participants) is detached
    to a random id, so the sweeper deletes its provider voice like a deleted
    Debate's.
    """

    participants = participants_of(db, debate_id)
    needed = {voice for row in participants if (voice := source_voice_id(row))}
    for clone in db.scalars(
        select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
    ).all():
        if clone.source_voice_profile_id not in needed:
            if clone.status == "ready":
                clone.debate_id = str(uuid4())
                clone.updated_at = _now()
            else:
                db.delete(clone)
    db.flush()
    request_debate_clones(db, debate_id, participants, data_root=data_root)


def participants_of(db: Session, debate_id: str) -> list[DebateParticipant]:
    return list(
        db.scalars(select(DebateParticipant).where(DebateParticipant.debate_id == debate_id)).all()
    )
