"""Voice resolution and short-lived preview resources.

Enrollment and deletion have materially different failure semantics from a
preview: preview bytes are disposable, same-group resources while effective
voice resolution is a read-only, fail-closed projection.  Keeping those
boundaries here prevents the enrollment service from becoming a second
monolithic state machine.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, invalid_state, not_found
from app.core.models import CourseMember, Group, GroupMember, StoredFile, VoicePreview, VoiceProfile
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.voices.crypto import VoiceEncryptionError
from app.modules.voices.schemas import PlaybackResource, VoiceProfileResponse
from app.modules.voices.service import (
    PREVIEW_TEXT,
    PREVIEW_TTL,
    EffectiveVoice,
    _profile_external_id,
    _utc,
    now_utc,
    visible_student_voice,
    voice_profile_dto,
)
from app.providers.audio import (
    MAX_PREVIEW_BYTES,
    NORMALIZED_CHANNELS,
    NORMALIZED_SAMPLE_RATE,
    NORMALIZED_SAMPLE_WIDTH,
    AudioValidationError,
    validate_technical_audio,
)
from app.providers.factory import tts_provider
from app.providers.tts import TTSProvider, TTSProviderError


def _configured_fallback(db: Session, settings: Settings) -> VoiceProfile | None:
    """Return a usable configured system fallback, or ``None`` fail-closed."""

    configured = getattr(settings, "fallback_voice_profile_id", None)
    if not configured:
        return None
    try:
        UUID(configured)
    except (TypeError, ValueError):
        return None
    profile = db.scalar(
        select(VoiceProfile).where(
            VoiceProfile.id == configured,
            VoiceProfile.scope == "system",
            VoiceProfile.group_id.is_(None),
            VoiceProfile.status == "ready",
        )
    )
    if profile is None:
        return None
    try:
        _profile_external_id(profile, settings)
    except VoiceEncryptionError:
        return None
    return profile


def resolve_effective_voice_profile(
    db: Session,
    bound_profile_id: str | None,
    group_id: str | None,
    settings: Settings,
) -> EffectiveVoice:
    """Resolve a ready same-group custom profile, otherwise system fallback."""

    if bound_profile_id:
        custom = db.scalar(
            select(VoiceProfile).where(
                VoiceProfile.id == bound_profile_id,
                VoiceProfile.scope == "group",
                VoiceProfile.group_id == group_id,
                VoiceProfile.status == "ready",
            )
        )
        if custom is not None and custom.external_id_encrypted:
            try:
                _profile_external_id(custom, settings)
            except VoiceEncryptionError:
                custom = None
            if custom is not None:
                return EffectiveVoice(custom.id, False, custom)
    fallback = _configured_fallback(db, settings)
    if fallback is None:
        return EffectiveVoice(None, True, None)
    return EffectiveVoice(fallback.id, True, fallback)


def _tts_external_id(profile: VoiceProfile, settings: object) -> str:
    try:
        return _profile_external_id(profile, settings)  # type: ignore[arg-type]
    except VoiceEncryptionError as exc:
        raise PlatformError(
            "provider_unavailable", "The voice service is temporarily unavailable.", 503
        ) from exc


def create_voice_preview(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
    *,
    provider: TTSProvider | None = None,
) -> PlaybackResource:
    """Generate bounded server-side preview bytes and return an opaque URL."""

    scoped = visible_student_voice(db, context, profile_id)
    profile = scoped.profile
    if profile.status not in {"preview_ready", "ready"}:
        raise not_found()
    tts = provider or tts_provider(settings)
    external_id = _tts_external_id(profile, settings)
    try:
        output = tts.synthesize(PREVIEW_TEXT, external_id, language="en")
        raw = read_pcm16_wav_bytes(output.audio_bytes)
        validate_technical_audio(raw)
    except (TTSProviderError, AudioValidationError, OSError) as exc:
        raise PlatformError(
            "provider_unavailable", "The preview could not be generated.", 503
        ) from exc
    preview_id = str(uuid4())
    relative_path = f"groups/{profile.group_id}/voices/previews/{preview_id}.wav"
    data_root = settings.resolved_data_root
    try:
        digest, size = write_atomic(data_root, relative_path, raw)
        timestamp = now_utc()
        expire_profile_previews(db, data_root, profile.id)
        stored = StoredFile(
            id=str(uuid4()),
            kind="voice_preview",
            relative_path=relative_path,
            sha256=digest,
            size_bytes=size,
            state="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        preview = VoicePreview(
            id=preview_id,
            profile_id=profile.id,
            group_id=profile.group_id,
            stored_file_id=stored.id,
            relative_path=relative_path,
            state="active",
            expires_at=timestamp + PREVIEW_TTL,
            created_at=timestamp,
        )
        db.add_all([stored, preview])
        db.commit()
    except Exception as exc:
        try:
            path = contained_path(data_root, relative_path)
            if path.exists() or path.is_symlink():
                path.unlink()
        except (ValueError, OSError):
            pass
        db.rollback()
        raise PlatformError(
            "file_operation_failed", "The preview could not be stored.", 503
        ) from exc
    return PlaybackResource(
        playback_url=f"/api/v1/voice-previews/{preview_id}/media",
        expires_at=preview.expires_at,
    )


def read_pcm16_wav_bytes(raw: bytes) -> bytes:
    """Validate bounded provider bytes while keeping audio server-side."""

    if len(raw) > MAX_PREVIEW_BYTES:
        raise AudioValidationError("audio_invalid")
    try:
        with wave.open(io.BytesIO(raw), "rb") as stream:
            if (
                stream.getnchannels() != NORMALIZED_CHANNELS
                or stream.getsampwidth() != NORMALIZED_SAMPLE_WIDTH
                or stream.getframerate() != NORMALIZED_SAMPLE_RATE
            ):
                raise AudioValidationError("audio_invalid")
            if stream.getnframes() <= 0:
                raise AudioValidationError("audio_invalid")
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioValidationError("audio_invalid") from exc
    return raw


def delete_preview_bytes(db: Session, data_root: Path, preview: VoicePreview) -> None:
    """Delete one contained preview file and clear its DB reference."""

    if preview.relative_path:
        try:
            # ``contained_path`` resolves symlinks and therefore cannot return
            # an escaping link for deletion.  Unlink a final symlink through
            # its lexical in-root path instead, while refusing ``..`` or
            # symlinked parents; this removes the link but never its target.
            lexical = data_root / preview.relative_path
            if (
                not Path(preview.relative_path).is_absolute()
                and ".." not in Path(preview.relative_path).parts
                and lexical.is_symlink()
            ):
                lexical.unlink()
                path = None
            else:
                path = contained_path(data_root, preview.relative_path)
            if (
                path is not None
                and path != data_root.resolve()
                and (path.exists() or path.is_symlink())
                and not path.is_dir()
            ):
                path.unlink()
        except (ValueError, OSError):
            pass
    if preview.stored_file_id:
        stored = db.get(StoredFile, preview.stored_file_id)
        if stored is not None:
            stored.state = "deleted"
            stored.updated_at = now_utc()
    preview.relative_path = None
    preview.stored_file_id = None


def expire_profile_previews(db: Session, data_root: Path, profile_id: str) -> None:
    """Expire old active previews, removing bytes before returning."""

    previews = db.scalars(
        select(VoicePreview).where(
            VoicePreview.profile_id == profile_id,
            VoicePreview.state == "active",
        )
    ).all()
    timestamp = now_utc()
    for preview in previews:
        preview.state = "expired" if _utc(preview.expires_at) <= timestamp else "replaced"
        delete_preview_bytes(db, data_root, preview)


def media_path_for_preview(
    db: Session,
    context: AuthContext,
    preview_id: str,
    settings: Settings,
) -> tuple[Path, str]:
    """Authorize and resolve one active, unexpired same-group preview."""

    row = db.execute(
        select(VoicePreview, VoiceProfile)
        .join(VoiceProfile, VoiceProfile.id == VoicePreview.profile_id)
        .join(Group, Group.id == VoiceProfile.group_id)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(
            VoicePreview.id == preview_id,
            VoiceProfile.scope == "group",
            Group.id == VoicePreview.group_id,
            GroupMember.user_id == context.user.id,
            CourseMember.user_id == context.user.id,
            CourseMember.role == "student",
        )
    ).first()
    if row is None:
        raise not_found()
    preview, _profile = row
    if (
        preview.state != "active"
        or _utc(preview.expires_at) <= now_utc()
        or not preview.relative_path
    ):
        if preview.state == "active":
            preview.state = "expired"
            delete_preview_bytes(db, settings.resolved_data_root, preview)
            db.commit()
        raise not_found()
    try:
        path = contained_path(settings.resolved_data_root, preview.relative_path)
    except (ValueError, OSError) as exc:
        preview.state = "expired"
        delete_preview_bytes(db, settings.resolved_data_root, preview)
        db.commit()
        raise not_found() from exc
    if path.is_symlink() or not path.is_file():
        raise not_found()
    return path, "audio/wav"


def confirm_voice_profile(
    db: Session,
    context: AuthContext,
    profile_id: str,
    settings: Settings,
) -> VoiceProfileResponse:
    """Promote preview-ready profile only while live preview bytes exist."""

    scoped = visible_student_voice(db, context, profile_id)
    profile = scoped.profile
    if profile.status != "preview_ready":
        raise invalid_state("Only a preview-ready voice profile can be confirmed.")
    preview = db.scalar(
        select(VoicePreview)
        .where(VoicePreview.profile_id == profile.id, VoicePreview.state == "active")
        .order_by(VoicePreview.created_at.desc())
    )
    if preview is None or _utc(preview.expires_at) <= now_utc():
        if preview is not None:
            preview.state = "expired"
            delete_preview_bytes(db, settings.resolved_data_root, preview)
            db.commit()
        raise invalid_state("A live preview is required before confirmation.")
    if not preview.relative_path:
        raise invalid_state("A live preview is required before confirmation.")
    try:
        preview_path = contained_path(settings.resolved_data_root, preview.relative_path)
    except (ValueError, OSError) as exc:
        preview.state = "expired"
        delete_preview_bytes(db, settings.resolved_data_root, preview)
        db.commit()
        raise invalid_state("A live preview is required before confirmation.") from exc
    if preview_path.is_symlink() or not preview_path.is_file():
        preview.state = "expired"
        delete_preview_bytes(db, settings.resolved_data_root, preview)
        db.commit()
        raise invalid_state("A live preview is required before confirmation.")
    profile.status = "ready"
    profile.updated_at = now_utc()
    preview.state = "confirmed"
    preview.confirmed_at = now_utc()
    delete_preview_bytes(db, settings.resolved_data_root, preview)
    db.commit()
    return voice_profile_dto(profile)
