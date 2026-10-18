"""Voice resolution and short-lived preview resources.

Enrollment and deletion have materially different failure semantics from a
preview: preview bytes are disposable, same-group resources while effective
voice resolution is a read-only, fail-closed projection.  Keeping those
boundaries here prevents the enrollment service from becoming a second
monolithic state machine.
"""

from __future__ import annotations

import io
import logging
import wave
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core.config import Settings
from app.core.errors import PlatformError, invalid_state, not_found
from app.core.models import (
    CourseMember,
    Group,
    StoredFile,
    VoicePreview,
    VoicePreviewCounter,
    VoiceProfile,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.org.access import WorkspaceMember
from app.modules.voices.crypto import VoiceEncryptionError
from app.modules.voices.schemas import PlaybackResource, VoiceProfileResponse
from app.modules.voices.service import (
    PREVIEW_TTL,
    EffectiveVoice,
    _profile_external_id,
    _utc,
    groupmate_ready_voice,
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
from app.providers.voice import VoiceProviderError
from app.seed import COURSE_ID

LOGGER = logging.getLogger("maya.voices")
# Preview samples rotate in the order previews are generated, across every
# user and voice: the 1st generation reads line 1, the 13th reads line 1 again.
# Lines 1-11 tell the 龙脉长歌 story in order (one Chinese sentence, then the
# next English sentence of the story); line 12 closes the rotation.
VOICE_PREVIEW_LINES: tuple[str, ...] = (
    "龙脉长歌是罗登家族搜集大量考古数据后，杜撰的神明爱情歌剧。"
    "The first act describes the birth of Helius from the fires of Ignis.",
    "他为烛龙授命，于虚空看望群山，漂泊亿万年为孤独折磨。"
    "One day, he was drawn in by a mysterious voice.",
    "有歌的地方，你就会找到我。"
    "Terra, one of the gods, gazed at Helius from afar, hoping to save him with her song.",
    "终于乙皇为她降世，彼此相恋。Together they established the Myrian Empire.",
    "由于后土的歌声使龙脉不灭，众道不死，破坏了烛龙的法则。"
    "In fear of divine retribution, six gods rebelled, "
    "sacrificing Terra to Ignis and sparking the holy war.",
    "我记得艾妲看完后，始终呢喃着后土死前对乙皇的话语。"
    "Should we find each other in the next life, let us live on a planet of our own.",
    "若来世再遇，就找一个无人的行星生活。"
    "I will plant flowers among the valleys, and sing for you into old age and death.",
    "而我只记得艾妲的侧脸。At the end of the story, Helius slays the gods who killed Terra.",
    "他试图用龙脉生长的花卉让后土复活，然而烛龙却警告他。"
    "If Terra were resurrected, the fires of heaven would destroy Thousand Peaks.",
    "乙皇不允，反将爱人的尸首藏于大荒，目送后土于虚空离去。"
    "His last words before sending his lover into the void were these.",
    "花开有时，来世再遇。"
    "The heavens erupted and Helius was blown away by wind storms, scattered among the stars.",
    "如果遇见你不是奇迹，灵魂便不曾言语。"
    "If meeting you wasn't a miracle, then the souls have never whispered.",
)
# Kept for callers that want a stable sample; it is the first line.
VOICE_PREVIEW_TEXT = VOICE_PREVIEW_LINES[0]
_PREVIEW_COUNTER_KEY = "global"


def next_preview_line(db: Session) -> str:
    """Atomically advance the shared counter and return that click's line.

    The increment commits on its own short transaction (never around the TTS
    call), so concurrent clicks on any backend replica each get the next
    line in turn.
    """

    session = Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    try:
        for _ in range(2):
            value = session.execute(
                update(VoicePreviewCounter)
                .where(VoicePreviewCounter.key == _PREVIEW_COUNTER_KEY)
                .values(value=VoicePreviewCounter.value + 1)
                .returning(VoicePreviewCounter.value)
            ).scalar_one_or_none()
            if value is not None:
                session.commit()
                return VOICE_PREVIEW_LINES[(value - 1) % len(VOICE_PREVIEW_LINES)]
            session.rollback()
            # First generation ever: create the row, then increment it.
            try:
                session.add(VoicePreviewCounter(key=_PREVIEW_COUNTER_KEY, value=0))
                session.commit()
            except IntegrityError:
                session.rollback()
        raise invalid_state("The preview counter is unavailable.")
    finally:
        session.close()


_SAFE_PREVIEW_ERRORS = frozenset(
    {
        "tts_http_rejected",
        "tts_response_invalid",
        "tts_result_url_rejected",
        "tts_result_dns_failed",
        "tts_result_download_failed",
        "tts_audio_invalid",
        "tts_timeout",
    }
)


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
    owner_user_id: str | None = None,
) -> EffectiveVoice:
    """Resolve a ready same-group or owner's personal profile, otherwise fallback."""

    if bound_profile_id:
        owned = (
            and_(
                VoiceProfile.scope == "group",
                VoiceProfile.group_id == group_id,
            )
            if group_id is not None
            else and_(
                VoiceProfile.scope == "personal",
                VoiceProfile.group_id.is_(None),
                VoiceProfile.consent_actor_user_id == owner_user_id,
            )
        )
        custom = db.scalar(
            select(VoiceProfile).where(
                VoiceProfile.id == bound_profile_id,
                owned,
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
        LOGGER.warning(
            "Voice preview failed profile_id=%s safe_code=voice_mapping_unavailable", profile.id
        )
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

    # Own voice first, exactly as before; a groupmate's ready voice only when
    # the caller owns no such voice.
    try:
        profile = visible_student_voice(db, context, profile_id).profile
        owner_preview = True
    except PlatformError:
        profile = groupmate_ready_voice(db, context, profile_id)
        owner_preview = False
    if profile.status not in {"preview_ready", "ready"}:
        raise not_found()
    try:
        tts = provider or tts_provider(settings)
    except (RuntimeError, OSError) as exc:
        LOGGER.warning(
            "Voice preview failed profile_id=%s safe_code=tts_configuration_unavailable", profile.id
        )
        raise PlatformError(
            "provider_unavailable", "The voice service is temporarily unavailable.", 503
        ) from exc
    external_id = _tts_external_id(profile, settings)
    preview_text = next_preview_line(db)
    try:
        output = tts.synthesize(
            preview_text,
            external_id,
            language="auto",
            target_model_key=profile.target_model_key,
        )
        raw = read_pcm16_wav_bytes(output.audio_bytes)
        validate_technical_audio(raw)
    except (TTSProviderError, AudioValidationError, OSError) as exc:
        code = getattr(exc, "safe_code", None)
        if not isinstance(code, str) or code not in _SAFE_PREVIEW_ERRORS:
            code = "tts_audio_invalid" if isinstance(exc, AudioValidationError) else "tts_failed"
        LOGGER.warning("Voice preview failed profile_id=%s safe_code=%s", profile.id, code)
        raise PlatformError(
            "provider_unavailable", "The preview could not be generated.", 503
        ) from exc
    except VoiceProviderError as exc:
        LOGGER.warning(
            "Voice preview failed profile_id=%s safe_code=tts_configuration_unavailable", profile.id
        )
        raise PlatformError(
            "provider_unavailable", "The voice service is temporarily unavailable.", 503
        ) from exc
    preview_id = str(uuid4())
    owner_dir = (
        f"groups/{profile.group_id}"
        if profile.group_id
        else f"personal/{profile.consent_actor_user_id}"
    )
    relative_path = f"{owner_dir}/voices/previews/{preview_id}.wav"
    data_root = settings.resolved_data_root
    try:
        digest, size = write_atomic(data_root, relative_path, raw)
        timestamp = now_utc()
        # The owner's new preview replaces their earlier one (confirmation
        # uses the latest). A groupmate's preview replaces nothing, so it
        # never cuts off audio someone else is playing; it expires on its TTL.
        if owner_preview:
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
        LOGGER.warning(
            "Voice preview failed profile_id=%s safe_code=voice_preview_storage_failed", profile.id
        )
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
    """Authorize and resolve one active, unexpired preview.

    System fallback previews have no group scope.  They are readable only by
    a teacher in the frozen Demo course; student and cross-course sessions
    receive the same not-found response as other out-of-scope voice media.
    Group previews are playable by the uploading student and, for a ready
    voice, by the student groupmates who may preview it.
    """

    scoped_group_member = aliased(WorkspaceMember)
    scoped_course_member = aliased(CourseMember)
    teacher_course_member = aliased(CourseMember)
    teacher_exists = exists(
        select(teacher_course_member.user_id).where(
            teacher_course_member.course_id == COURSE_ID,
            teacher_course_member.user_id == context.user.id,
            teacher_course_member.role == "teacher",
        )
    )
    row = db.execute(
        select(VoicePreview, VoiceProfile)
        .join(VoiceProfile, VoiceProfile.id == VoicePreview.profile_id)
        .outerjoin(Group, Group.id == VoiceProfile.group_id)
        .outerjoin(scoped_group_member, scoped_group_member.group_id == Group.id)
        .outerjoin(scoped_course_member, scoped_course_member.course_id == Group.course_id)
        .where(
            VoicePreview.id == preview_id,
            or_(
                and_(
                    VoiceProfile.scope == "system",
                    VoiceProfile.group_id.is_(None),
                    VoicePreview.group_id.is_(None),
                    teacher_exists,
                ),
                and_(
                    VoiceProfile.scope == "group",
                    Group.id == VoicePreview.group_id,
                    # A preview is only playable by the uploading student;
                    # a profile with a missing owner fails closed.
                    VoiceProfile.consent_actor_user_id == context.user.id,
                    scoped_group_member.user_id == context.user.id,
                    scoped_course_member.user_id == context.user.id,
                ),
                and_(
                    VoiceProfile.scope == "personal",
                    VoiceProfile.group_id.is_(None),
                    VoicePreview.group_id.is_(None),
                    VoiceProfile.consent_actor_user_id == context.user.id,
                ),
            ),
        )
    ).first()
    if row is None:
        # A groupmate's ready voice: the same rule that let them create it.
        shared = db.execute(
            select(VoicePreview, VoiceProfile)
            .join(VoiceProfile, VoiceProfile.id == VoicePreview.profile_id)
            .where(
                VoicePreview.id == preview_id,
                VoiceProfile.scope == "group",
                VoicePreview.group_id == VoiceProfile.group_id,
            )
        ).first()
        if shared is not None:
            try:
                groupmate_ready_voice(db, context, shared[1].id)
            except PlatformError:
                shared = None
        row = shared
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
