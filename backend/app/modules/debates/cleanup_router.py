"""Teacher deletion commands expose only the bounded cleanup outcome."""

import hashlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, not_found
from app.modules.auth.dependencies import get_db, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.debates.cleanup import DebateCleanupError, delete_all, delete_voice
from app.modules.debates.models import Debate, DebateParticipant
from app.modules.debates.playback.audio_regeneration import CachedSegmentTurn, regenerate_turn_audio
from app.modules.debates.playback.protocols import ResolvedTurnVoice
from app.modules.debates.playback.router import get_playback_service
from app.modules.debates.schemas import (
    DebateCleanupRequest,
    DebateCleanupResult,
    RegenerateTurnAudioRequest,
    RegenerateTurnAudioResult,
)
from app.modules.debates.setup.service import require_teacher_course

router = APIRouter(tags=["Debates"])
_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": Error},
    404: {"model": Error},
    409: {"model": Error},
    422: {"model": Error},
    503: {"model": Error},
}


async def _cleanup(
    *,
    request: Request,
    context: AuthContext,
    db: Session,
    settings: Settings,
    debate_id: UUID,
    payload: DebateCleanupRequest,
    remove_all: bool,
    key: str,
) -> DebateCleanupResult:
    service = get_playback_service(request)
    action = delete_all if remove_all else delete_voice
    try:
        result = await action(
            db,
            actor_user_id=str(context.user.id),
            debate_id=str(debate_id),
            expected_revision=payload.expected_revision,
            expected_control_version=payload.expected_control_version,
            data_root=settings.resolved_data_root,
            playback_service=service,
            report_task_manager=getattr(request.app.state, "report_task_manager", None),
            idempotency_key=key,
        )
    except DebateCleanupError as exc:
        raise PlatformError(
            "cleanup_failed", "Cleanup could not finish. Retry this action.", 503
        ) from exc
    scheduler = getattr(request.app.state, "prewarm_scheduler", None)
    if scheduler is not None:
        scheduler.release(str(debate_id))
    return DebateCleanupResult.model_validate(
        {
            "debate_id": result.debate_id,
            "cleanup_status": result.cleanup_status,
            "revision": result.revision,
            "control_version": result.control_version,
            "deleted_file_count": result.deleted_file_count,
            "pending_file_count": result.pending_file_count,
            "regenerable_turn_ids": list(getattr(result, "regenerable_turn_ids", ())),
        }
    )


@router.delete(
    "/debates/{debate_id}/audio",
    response_model=DebateCleanupResult,
    operation_id="deleteDebateVoice",
    responses=_RESPONSES,
)
async def delete_voice_route(
    debate_id: UUID,
    payload: DebateCleanupRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DebateCleanupResult:
    return await _cleanup(
        request=request,
        context=context,
        db=db,
        settings=settings,
        debate_id=debate_id,
        payload=payload,
        remove_all=False,
        key=idempotency_key,
    )


@router.delete(
    "/debates/{debate_id}",
    response_model=DebateCleanupResult,
    operation_id="deleteDebateAll",
    responses=_RESPONSES,
)
async def delete_all_route(
    debate_id: UUID,
    payload: DebateCleanupRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DebateCleanupResult:
    return await _cleanup(
        request=request,
        context=context,
        db=db,
        settings=settings,
        debate_id=debate_id,
        payload=payload,
        remove_all=True,
        key=idempotency_key,
    )


@router.post(
    "/debates/{debate_id}/audio/{turn_id}/regenerate",
    response_model=RegenerateTurnAudioResult,
    operation_id="regenerateDebateTurnAudio",
    responses=_RESPONSES,
)
def regenerate_audio_route(
    debate_id: UUID,
    turn_id: UUID,
    payload: RegenerateTurnAudioRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> RegenerateTurnAudioResult:
    debate = db.get(Debate, str(debate_id))
    if debate is None:
        raise not_found()
    require_teacher_course(db, str(context.user.id), str(debate.course_id))
    playback = get_playback_service(request)

    def resolve_voice(cached: CachedSegmentTurn) -> ResolvedTurnVoice:
        participant = db.get(DebateParticipant, cached.participant_id)
        if participant is None:
            raise not_found()
        return playback._resolve_voice(db, participant)

    scoped_key = hashlib.sha256(
        f"{context.user.id}:debate-turn-tts:{idempotency_key}".encode()
    ).hexdigest()
    result = regenerate_turn_audio(
        db,
        str(debate_id),
        str(turn_id),
        payload.expected_revision,
        scoped_key,
        playback_service=playback,
        voice_resolver=resolve_voice,
    )
    return RegenerateTurnAudioResult.model_validate(result.to_public_dict())
