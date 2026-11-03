"""The voice a Debate keeps: a copied sample and the supplier voice ID.

Owner decision (2026-10-24, replaces the independent clone): creating a
Debate copies each participant Voice's recording into the Debate's own
storage and records that Voice's supplier voice ID (encrypted, bound to the
snapshot row) in ``debate_voice_clones``. Nothing is enrolled, so nothing is
charged. Playback and new speech use only this snapshot.

The supplier voice is shared by the Voice and every Debate that copied it,
so it is deleted at the supplier only when none of them is left:

* Deleting the Voice removes its row and files, and skips the supplier call
  while any live Debate snapshot names the same voice.
* Deleting a Debate leaves its snapshot rows without a Debate; the sweeper
  removes them and their files, and calls the supplier once per voice only
  when no Voice row and no live Debate still holds it.

Both decisions take the same PostgreSQL advisory lock per voice, keyed by an
HMAC of the supplier voice ID, so a concurrent Debate create, Debate delete
and Voice delete see each other's committed rows.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.locks import xact_lock
from app.core.models import StoredFile, VoiceProfile
from app.modules.debates.models import Debate, DebateParticipant, DebateVoiceClone
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.voices.crypto import (
    VoiceEncryptionError,
    decrypt_external_voice_id,
    encrypt_external_voice_id,
)

logger = logging.getLogger(__name__)

CLONE_SCOPE = "debate"


def _now() -> datetime:
    return datetime.now(UTC)


def clone_recovery_name(clone_id: str) -> str:
    return f"d{clone_id.replace('-', '')[:8]}"


def voice_ref_hash(settings: Any, provider_key: str, model: str, voice_id: str) -> str:
    """A keyed fingerprint of one supplier voice, safe to store and compare."""

    message = f"{provider_key}\0{model}\0{voice_id}".encode()
    return hmac.new(settings.secret_bytes, message, hashlib.sha256).hexdigest()


def lock_voice(db: Session, ref_hash: str) -> None:
    """Serialize every reference decision about one supplier voice."""

    xact_lock(db, f"maya-supplier-voice:{ref_hash}")


def profile_voice_id(profile: VoiceProfile, settings: Any) -> str | None:
    if not profile.external_id_encrypted:
        return None
    try:
        return decrypt_external_voice_id(
            profile.external_id_encrypted,
            settings.secret_bytes,
            profile_id=profile.id,
            scope=profile.scope,
            group_id=profile.group_id,
            provider_key=profile.provider_key,
            target_model_key=profile.target_model_key,
        )
    except VoiceEncryptionError:
        return None


def _participant_voice_id(row: Any, settings: Any) -> str | None:
    """The supplier ID frozen into a participant before snapshot rows existed."""

    raw = getattr(row, "voice_snapshot_json", None)
    cipher = getattr(row, "voice_external_id_encrypted", None)
    if not raw or not cipher:
        return None
    try:
        snapshot = json.loads(raw)
        return decrypt_external_voice_id(
            bytes(cipher),
            settings.secret_bytes,
            profile_id=str(snapshot.get("voice_profile_id") or ""),
            scope=str(snapshot.get("scope") or ""),
            group_id=snapshot.get("group_id"),
            provider_key=str(snapshot.get("provider_key") or ""),
            target_model_key=str(snapshot.get("target_model_key") or ""),
        )
    except (ValueError, VoiceEncryptionError):
        return None


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


def snapshot_debate_voices(
    db: Session,
    debate_id: str,
    participants: list[Any],
    *,
    settings: Any,
    origin: str = "create",
    data_root: Path | None = None,
) -> list[DebateVoiceClone]:
    """Copy each voiced participant's sample and supplier ID (idempotent, free)."""

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
        supplier_id = profile_voice_id(profile, settings) if profile is not None else None
        supplier_id = supplier_id or _participant_voice_id(row, settings)
        ref_hash = (
            voice_ref_hash(settings, str(provider_key), str(model), supplier_id)
            if supplier_id
            else None
        )
        if ref_hash is not None:
            lock_voice(db, ref_hash)
            if profile is not None:
                db.refresh(profile)
                # A Voice whose delete already committed may be leaving the
                # supplier right now; a new Debate does not copy it.
                if origin == "create" and profile.status != "ready":
                    continue
        clone_id = str(uuid4())
        now = _now()
        clone = DebateVoiceClone(
            id=clone_id,
            debate_id=debate_id,
            source_voice_profile_id=voice_id,
            origin=origin,
            status="ready",
            provider_key=str(provider_key),
            target_model_key=str(model),
            sample_file_id=(_owned_sample(db, profile, data_root) if profile is not None else None),
            sample_language=profile.sample_language if profile is not None else None,
            recovery_name=clone_recovery_name(clone_id),
            provider_voice_hash=ref_hash,
            external_id_encrypted=(
                encrypt_external_voice_id(
                    supplier_id,
                    settings.secret_bytes,
                    profile_id=clone_id,
                    scope=CLONE_SCOPE,
                    group_id=None,
                    provider_key=str(provider_key),
                    target_model_key=str(model),
                )
                if supplier_id
                else None
            ),
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
    """(supplier voice ID, model) from the Debate's own snapshot, else None."""

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
    """(supplier ID, model) frozen into a participant that has no snapshot row yet."""

    from app.providers.dashscope import LEGACY_CLONE_MODEL_KEY

    raw = getattr(participant, "voice_snapshot_json", None)
    if not raw or not getattr(participant, "voice_external_id_encrypted", None):
        return None
    try:
        snapshot = json.loads(raw)
    except ValueError:
        return None
    profile_id = snapshot.get("voice_profile_id")
    model = snapshot.get("target_model_key")
    if not profile_id or not isinstance(model, str) or not model:
        return None
    if model == LEGACY_CLONE_MODEL_KEY:
        return None
    if getattr(settings, "tts_provider", "mock") == "mock":
        return str(profile_id), model
    if snapshot.get("provider_key") != "dashscope":
        return None
    token = _participant_voice_id(participant, settings)
    return (token, model) if token else None


def _live_debate_refs(db: Session, ref_hash: str, *, exclude: set[str] | None = None) -> bool:
    query = select(DebateVoiceClone.id).where(
        DebateVoiceClone.provider_voice_hash == ref_hash,
        DebateVoiceClone.debate_id.in_(select(Debate.id)),
    )
    if exclude:
        query = query.where(DebateVoiceClone.id.not_in(exclude))
    return db.scalar(query.limit(1)) is not None


def debates_hold_supplier_voice(db: Session, profile: VoiceProfile, settings: Any) -> bool:
    """True while a live Debate still speaks with this Voice's supplier voice.

    Takes the voice lock; the caller's next commit (the Voice delete) releases
    it, so a Debate create waiting on the lock then sees the Voice deleted.
    """

    supplier_id = profile_voice_id(profile, settings)
    if supplier_id is not None:
        ref_hash = voice_ref_hash(
            settings, profile.provider_key, profile.target_model_key, supplier_id
        )
        lock_voice(db, ref_hash)
        if _live_debate_refs(db, ref_hash):
            return True
    # A Debate made before snapshot rows existed and not yet backfilled.
    covered = select(DebateVoiceClone.debate_id).where(
        DebateVoiceClone.source_voice_profile_id == profile.id
    )
    return (
        db.scalar(
            select(DebateParticipant.id)
            .where(
                DebateParticipant.effective_voice_profile_id == profile.id,
                DebateParticipant.voice_external_id_encrypted.is_not(None),
                DebateParticipant.debate_id.not_in(covered),
            )
            .limit(1)
        )
        is not None
    )


def _drop_snapshot(db: Session, clone: DebateVoiceClone, data_root: Path | None) -> None:
    from app.modules.real_delete import release_stored_file

    sample = clone.sample_file_id
    db.delete(clone)
    db.flush()
    release_stored_file(db, data_root, sample)


def release_orphan_voices(
    db: Session, *, data_root: Path | None, settings: Any, provider: Any
) -> dict[str, int]:
    """Remove snapshot rows of deleted Debates; free each supplier voice once."""

    counts = {"released": 0, "supplier_deleted": 0, "kept": 0}
    orphans = list(
        db.scalars(
            select(DebateVoiceClone).where(DebateVoiceClone.debate_id.not_in(select(Debate.id)))
        ).all()
    )
    groups: dict[str | None, list[DebateVoiceClone]] = {}
    for clone in orphans:
        groups.setdefault(clone.provider_voice_hash, []).append(clone)
    for ref_hash, rows in groups.items():
        try:
            if ref_hash is None:
                for clone in rows:
                    _drop_snapshot(db, clone, data_root)
                db.commit()
                counts["released"] += len(rows)
                continue
            lock_voice(db, ref_hash)
            ids = {clone.id for clone in rows}
            fresh = list(
                db.scalars(select(DebateVoiceClone).where(DebateVoiceClone.id.in_(ids))).all()
            )
            if not fresh:
                db.commit()
                continue
            source_ids = {clone.source_voice_profile_id for clone in fresh}
            voice_row_left = (
                db.scalar(select(VoiceProfile.id).where(VoiceProfile.id.in_(source_ids)).limit(1))
                is not None
            )
            if not voice_row_left and not _live_debate_refs(db, ref_hash, exclude=ids):
                first = fresh[0]
                if first.external_id_encrypted:
                    supplier_id = decrypt_external_voice_id(
                        first.external_id_encrypted,
                        settings.secret_bytes,
                        profile_id=first.id,
                        scope=CLONE_SCOPE,
                        group_id=None,
                        provider_key=first.provider_key,
                        target_model_key=first.target_model_key,
                    )
                    # Still under the lock: no new reference can appear before
                    # the rows go, and a failed call keeps them for a retry.
                    provider.delete(supplier_id, target_model_key=first.target_model_key)
                    counts["supplier_deleted"] += 1
            else:
                counts["kept"] += 1
            for clone in fresh:
                _drop_snapshot(db, clone, data_root)
            db.commit()
            counts["released"] += len(fresh)
        except Exception:  # noqa: BLE001 - keep the rows, retry next sweep
            db.rollback()
            logger.warning("debate_voice_release_failed rows=%d", len(rows))
    return counts


def sweep_debate_voice_clones(
    db: Session, *, data_root: Path, settings: Any, provider: Any
) -> dict[str, int]:
    """Startup and periodic: release the voices of deleted Debates. Never enrolls.

    Two sweepers (two replicas) may run at once: each voice is decided under
    its own lock and its rows are re-read there, so the second finds nothing.
    """

    return release_orphan_voices(db, data_root=data_root, settings=settings, provider=provider)


def sync_debate_clones(
    db: Session, debate_id: str, *, settings: Any, data_root: Path | None = None
) -> None:
    """Match snapshot rows to the Debate's current voiced participants.

    A row no longer needed (a draft changed its participants) is detached to a
    random Debate id, so the sweeper releases it like a deleted Debate's.
    """

    participants = participants_of(db, debate_id)
    needed = {voice for row in participants if (voice := source_voice_id(row))}
    for clone in db.scalars(
        select(DebateVoiceClone).where(DebateVoiceClone.debate_id == debate_id)
    ).all():
        if clone.source_voice_profile_id not in needed:
            clone.debate_id = str(uuid4())
            clone.updated_at = _now()
    db.flush()
    snapshot_debate_voices(db, debate_id, participants, settings=settings, data_root=data_root)


def participants_of(db: Session, debate_id: str) -> list[DebateParticipant]:
    return list(
        db.scalars(select(DebateParticipant).where(DebateParticipant.debate_id == debate_id)).all()
    )
