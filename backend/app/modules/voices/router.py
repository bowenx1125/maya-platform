"""FastAPI routes for provider-neutral M08 voice resources."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, validation_failure
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.voices.schemas import (
    PlaybackResource,
    RenameVoiceProfileRequest,
    SystemVoicePreviewRequest,
    SystemVoicePreviewResponse,
    SystemVoiceScriptResponse,
    VoiceProfileResponse,
)
from app.modules.voices.service import (
    confirm_voice_profile,
    create_voice_preview,
    delete_voice_profile,
    enroll_voice,
    list_group_voices,
    list_personal_voices,
    media_path_for_preview,
    rename_voice_profile,
    visible_student_voice,
    voice_profile_dto,
)
from app.modules.voices.system_voice_preview import (
    create_system_voice_preview,
    list_system_voice_scripts,
    media_path_for_system_voice_preview,
)
from app.modules.voices.uploads import (
    VoiceUploadDisconnected,
    VoiceUploadError,
    VoiceUploadTooLarge,
    stream_voice_upload,
)

router = APIRouter(tags=["Voices"])
LOGGER = logging.getLogger("maya.voices")

_VOICE_ENROLL_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "consent_accepted"],
                "properties": {
                    "file": {"type": "string", "format": "binary"},
                    "consent_accepted": {"type": "boolean", "const": True},
                    "consent_copy_version": {"type": "string"},
                    "language": {"type": "string", "enum": ["en", "zh-CN"]},
                },
            }
        }
    },
}


def _safe_provider_failure(operation: Literal["enroll", "delete", "preview"]) -> PlatformError:
    LOGGER.warning("Voice request failed operation=%s safe_code=provider_unavailable", operation)
    return PlatformError(
        "provider_unavailable",
        "The voice service is temporarily unavailable.",
        503,
    )


async def _enroll(
    request: Request,
    context: AuthContext,
    db: Session,
    settings: Settings,
    idempotency_key: str,
    *,
    group_id: str | None,
    personal_course_id: str | None = None,
) -> VoiceProfileResponse:
    upload = None
    try:
        try:
            upload = await stream_voice_upload(request, settings.resolved_data_root)
        except VoiceUploadTooLarge as exc:
            raise validation_failure("The voice file is too large.", code="audio_invalid") from exc
        except (VoiceUploadDisconnected, VoiceUploadError) as exc:
            raise validation_failure(
                "The voice file could not be received.", code="audio_invalid"
            ) from exc
        fields = upload.fields
        consent_raw = fields.get("consent_accepted", "").strip().lower()
        if consent_raw not in {"true", "1", "yes"}:
            raise validation_failure(
                "Voice enrollment requires consent.", code="voice_enrollment_failed"
            )
        try:
            result = enroll_voice(
                db,
                context,
                settings,
                upload,
                group_id=group_id,
                personal_course_id=personal_course_id,
                consent_accepted=True,
                consent_copy_version=fields.get("consent_copy_version"),
                language=fields.get("language"),
                idempotency_key=idempotency_key,
            )
        except PlatformError:
            raise
        except (RuntimeError, OSError) as exc:
            raise _safe_provider_failure("enroll") from exc
        return result
    finally:
        if upload is not None:
            upload.cleanup()


@router.get(
    "/groups/{group_id}/voice-profiles",
    response_model=list[VoiceProfileResponse],
    operation_id="listVoiceProfiles",
    responses={404: {"model": Error, "description": "Group not found."}},
)
def list_voice_profiles(
    group_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[VoiceProfileResponse]:
    return list_group_voices(db, context, str(group_id))


@router.post(
    "/groups/{group_id}/voice-profiles",
    response_model=VoiceProfileResponse,
    status_code=202,
    operation_id="enrollVoice",
    openapi_extra={"requestBody": _VOICE_ENROLL_BODY},
    responses={
        404: {"model": Error, "description": "Group not found."},
        422: {"model": Error, "description": "Invalid voice input."},
        503: {"model": Error, "description": "Voice provider unavailable."},
    },
)
async def enroll_voice_route(
    request: Request,
    group_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VoiceProfileResponse:
    return await _enroll(request, context, db, settings, idempotency_key, group_id=str(group_id))


@router.get(
    "/courses/{course_id}/voice-profiles",
    response_model=list[VoiceProfileResponse],
    operation_id="listPersonalVoiceProfiles",
    responses={404: {"model": Error, "description": "Course not found."}},
)
def list_personal_voice_profiles(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[VoiceProfileResponse]:
    return list_personal_voices(db, context, str(course_id))


@router.post(
    "/courses/{course_id}/voice-profiles",
    response_model=VoiceProfileResponse,
    status_code=202,
    operation_id="enrollPersonalVoice",
    openapi_extra={"requestBody": _VOICE_ENROLL_BODY},
    responses={
        404: {"model": Error, "description": "Course not found."},
        422: {"model": Error, "description": "Invalid voice input."},
        503: {"model": Error, "description": "Voice provider unavailable."},
    },
)
async def enroll_personal_voice_route(
    request: Request,
    course_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VoiceProfileResponse:
    """A teacher, who has no group, enrolls a voice only they may choose."""

    return await _enroll(
        request,
        context,
        db,
        settings,
        idempotency_key,
        group_id=None,
        personal_course_id=str(course_id),
    )


@router.get(
    "/voice-profiles/{voice_profile_id}",
    response_model=VoiceProfileResponse,
    operation_id="getVoiceProfile",
    responses={404: {"model": Error, "description": "Voice profile not found."}},
)
def get_voice_profile(
    voice_profile_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> VoiceProfileResponse:
    return voice_profile_dto(visible_student_voice(db, context, str(voice_profile_id)).profile)


@router.patch(
    "/voice-profiles/{voice_profile_id}",
    response_model=VoiceProfileResponse,
    operation_id="renameVoiceProfile",
    responses={
        404: {"model": Error, "description": "Voice profile not found."},
        400: {"model": Error, "description": "Invalid voice filename."},
    },
)
def rename_voice_profile_route(
    voice_profile_id: UUID,
    body: RenameVoiceProfileRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> VoiceProfileResponse:
    return rename_voice_profile(db, context, str(voice_profile_id), body.source_filename)


@router.delete(
    "/voice-profiles/{voice_profile_id}",
    response_model=VoiceProfileResponse,
    operation_id="deleteVoiceProfile",
    responses={
        404: {"model": Error, "description": "Voice profile not found."},
        503: {"model": Error, "description": "Voice provider unavailable."},
    },
)
def delete_voice_profile_route(
    voice_profile_id: UUID,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VoiceProfileResponse:
    try:
        result = delete_voice_profile(
            db,
            context,
            str(voice_profile_id),
            settings,
            idempotency_key=idempotency_key,
        )
    except PlatformError:
        raise
    except (RuntimeError, OSError) as exc:
        raise _safe_provider_failure("delete") from exc
    return result


@router.post(
    "/voice-profiles/{voice_profile_id}/preview",
    response_model=PlaybackResource,
    operation_id="createVoicePreview",
    responses={
        404: {"model": Error, "description": "Voice profile not found."},
        503: {"model": Error, "description": "Preview provider unavailable."},
    },
)
def create_voice_preview_route(
    voice_profile_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlaybackResource:
    try:
        return create_voice_preview(db, context, str(voice_profile_id), settings)
    except PlatformError:
        raise
    except (RuntimeError, OSError) as exc:
        raise _safe_provider_failure("preview") from exc


@router.post(
    "/voice-profiles/{voice_profile_id}/confirm",
    response_model=VoiceProfileResponse,
    operation_id="confirmVoiceProfile",
    responses={
        404: {"model": Error, "description": "Voice profile not found."},
        409: {"model": Error, "description": "Invalid confirmation transition."},
    },
)
def confirm_voice_profile_route(
    voice_profile_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VoiceProfileResponse:
    return confirm_voice_profile(db, context, str(voice_profile_id), settings)


@router.get(
    "/voice-previews/{preview_id}/media",
    include_in_schema=False,
    name="voicePreviewMedia",
)
def voice_preview_media(
    preview_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    path, media_type = media_path_for_preview(db, context, str(preview_id), settings)
    return FileResponse(
        Path(path),
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/system-voice-previews/scripts",
    response_model=list[SystemVoiceScriptResponse],
    operation_id="listSystemVoicePreviewScripts",
    include_in_schema=False,
)
def list_system_voice_preview_scripts(
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[SystemVoiceScriptResponse]:
    from app.modules.voices.system_voice_preview import require_system_voice_teacher

    require_system_voice_teacher(db, context)
    return [
        SystemVoiceScriptResponse(
            segment_id=script.segment_id,
            voice=script.voice,
            language=script.language,
            text=script.text,
            expected_reading=script.expected_reading,
        )
        for script in list_system_voice_scripts()
    ]


@router.post(
    "/system-voice-previews",
    response_model=SystemVoicePreviewResponse | list[SystemVoicePreviewResponse],
    operation_id="createSystemVoicePreview",
    include_in_schema=False,
    responses={
        403: {"model": Error, "description": "Teacher access required."},
        503: {"model": Error, "description": "Flash preview unavailable."},
    },
)
def create_system_voice_preview_route(
    payload: SystemVoicePreviewRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SystemVoicePreviewResponse | list[SystemVoicePreviewResponse]:
    try:
        result = create_system_voice_preview(db, context, settings, payload.segment_id)
    except PlatformError:
        raise
    except (RuntimeError, OSError) as exc:
        raise _safe_provider_failure("preview") from exc
    if isinstance(result, list):
        return [
            SystemVoicePreviewResponse(
                request_id=item.request_id,
                segment_id=item.segment_id,
                voice=item.voice,
                language=item.language,
                text=item.text,
                expected_reading=item.expected_reading,
                playback_url=item.playback_url,
                expires_at=item.expires_at,
                provider_request_id=item.provider_request_id,
                deduplicated=item.deduplicated,
            )
            for item in result
        ]
    return SystemVoicePreviewResponse(
        request_id=result.request_id,
        segment_id=result.segment_id,
        voice=result.voice,
        language=result.language,
        text=result.text,
        expected_reading=result.expected_reading,
        playback_url=result.playback_url,
        expires_at=result.expires_at,
        provider_request_id=result.provider_request_id,
        deduplicated=result.deduplicated,
    )


@router.get(
    "/system-voice-previews/{request_id}/media",
    include_in_schema=False,
    name="systemVoicePreviewMedia",
)
def system_voice_preview_media(
    request_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    path, media_type = media_path_for_system_voice_preview(db, context, str(request_id), settings)
    return FileResponse(
        Path(path),
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
