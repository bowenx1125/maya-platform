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
    Agent,
    AgentVersion,
    CourseMember,
    Group,
    StoredFile,
    VoicePreview,
    VoicePreviewCounter,
    VoiceProfile,
)
from app.core.prefetch import prefetched
from app.modules.auth.service import AuthContext
from app.modules.knowledge.files import contained_path, write_atomic
from app.modules.org.access import WorkspaceMember
from app.modules.voices.crypto import VoiceEncryptionError
from app.modules.voices.schemas import PlaybackResource, VoiceProfileResponse
from app.modules.voices.service import (
    PREVIEW_TTL,
    EffectiveVoice,
    _groupmate_owner_ids,
    _profile_external_id,
    _utc,
    course_teacher_can_access_voice,
    groupmate_ready_voice,
    log_course_teacher_voice_action,
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
# user and voice: the 1st generation reads line 1, the 10th reads line 1 again.
VOICE_PREVIEW_LINES: tuple[str, ...] = (
    (
        "如果遇见你不是奇迹，灵魂便不曾言语。"
        "If meeting you was not a miracle, then my soul has never spoken."
    ),
    "不管需要多少年，我都要再见你一面。No matter how many years it takes, I will see you again.",
    (
        "重铸 Mayaform 荣光，吾辈义不容辞！"
        "To restore Mayaform to its former glory is our duty, and we shall not turn away!"
    ),
    "过得了我，再谈未来。Get past me first. Then we can talk about the future.",
    "我是要成为海贼王的男人！海賊王に、俺はなる！",
    "真相永远只有一个！真実はいつもひとつ！",
    (
        "或许是不知梦的缘故，流离之人追逐幻影。"
        "Perhaps because they do not know it is a dream, wandering souls keep chasing illusions."
    ),
    (
        "这一路上我们将不彼此抛弃，不彼此出卖，直到死亡的尽头。"
        "We will neither abandon nor betray each other, not even at the very edge of death."
    ),
    "从这里开始吧。从一开始，不，从零开始！ここから始めましょう。一から、いいえ、ゼロから！",
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


def prefetch_bound_voices(db: Session, pairs: list[tuple[AgentVersion, Agent]]) -> None:
    """Batch what ``resolve_effective_voice_profile`` reads for these versions.

    The same rule as its query: a ready group clone whose owner is still a
    student of the Agent's group, or the owner's ready personal voice.
    """

    from app.core.prefetch import store

    wanted = {
        (version.voice_profile_id, agent.group_id, agent.owner_user_id)
        for version, agent in pairs
        if version.voice_profile_id
    }
    if not wanted:
        return
    profiles = {
        profile.id: profile
        for profile in db.scalars(
            select(VoiceProfile).where(
                VoiceProfile.id.in_({key[0] for key in wanted}),
                VoiceProfile.status == "ready",
            )
        ).all()
    }
    group_ids = {key[1] for key in wanted if key[1] is not None}
    students: dict[str, set[str]] = {group_id: set() for group_id in group_ids}
    if group_ids:
        for group_id, user_id in db.execute(
            select(WorkspaceMember.group_id, WorkspaceMember.user_id)
            .join(Group, Group.id == WorkspaceMember.group_id)
            .join(
                CourseMember,
                and_(
                    CourseMember.course_id == Group.course_id,
                    CourseMember.user_id == WorkspaceMember.user_id,
                ),
            )
            .where(WorkspaceMember.group_id.in_(group_ids), CourseMember.role == "student")
        ).all():
            students[group_id].add(user_id)
    resolved: dict[tuple[str, str | None, str | None], VoiceProfile | None] = {}
    for profile_id, group_id, owner_user_id in wanted:
        profile = profiles.get(profile_id)
        if profile is not None and group_id is not None:
            usable = (
                profile.scope == "group"
                and profile.group_id == group_id
                and profile.consent_actor_user_id in students[group_id]
            )
        elif profile is not None:
            usable = (
                profile.scope == "personal"
                and profile.group_id is None
                and profile.consent_actor_user_id == owner_user_id
            )
        else:
            usable = False
        resolved[(profile_id, group_id, owner_user_id)] = profile if usable else None
    store(db, "bound_voice", resolved)


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
                # A clone speaks only while its owner is still a student of
                # this group; once they leave, the Agent falls back.
                VoiceProfile.consent_actor_user_id.in_(_groupmate_owner_ids(db, group_id)),
            )
            if group_id is not None
            else and_(
                VoiceProfile.scope == "personal",
                VoiceProfile.group_id.is_(None),
                VoiceProfile.consent_actor_user_id == owner_user_id,
            )
        )
        custom = prefetched(
            db,
            "bound_voice",
            (bound_profile_id, group_id, owner_user_id),
            lambda: db.scalar(
                select(VoiceProfile).where(
                    VoiceProfile.id == bound_profile_id,
                    owned,
                    VoiceProfile.status == "ready",
                )
            ),
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
        scoped = visible_student_voice(db, context, profile_id)
        profile = scoped.profile
        # A course teacher's preview (owner decision 2026-10-26) leaves the
        # student's own preview playing, like a groupmate's.
        owner_preview = scoped.role == "student"
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
        if shared is not None and not course_teacher_can_access_voice(db, context, shared[1]):
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
    log_course_teacher_voice_action(scoped, context, "confirm")
    profile = scoped.profile
    if profile.status == "ready":
        # Uploads are ready at once now; an older client's confirm is a no-op.
        return voice_profile_dto(db, profile)
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
    return voice_profile_dto(db, profile)
