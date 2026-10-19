"""FastAPI routes for teacher and anonymous classroom interaction."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.debate_gate import PublicCopy, interaction_slot
from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import (
    BarrageRequest,
    BarrageSubmitted,
    FreezeFinalRequest,
    FrozenFinalInput,
    PublicInteractionForm,
    TeacherInteraction,
    VoteRequest,
    VoteSubmitted,
)
from .service import InteractionService, service_from_context

router = APIRouter(tags=["Interaction"])


def get_interaction_service(
    request: Request, settings: Settings = Depends(get_settings)
) -> InteractionService:
    configured = getattr(request.app.state, "interaction_service", None)
    if isinstance(configured, InteractionService):
        return configured
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError("interaction service is not configured")
    return service_from_context(
        session_factory=database.session_factory,
        settings=settings,
        event_publisher=getattr(request.app.state, "interaction_event_publisher", None),
        insight_enqueuer=getattr(request.app.state, "insight_enqueuer", None),
    )


@router.post(
    "/debates/{debate_id}/final-input",
    response_model=FrozenFinalInput,
    operation_id="freezeFinalInput",
    responses={
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
async def freeze_final_input_route(
    debate_id: UUID,
    payload: FreezeFinalRequest,
    request: Request,
    context: AuthContext = Depends(require_authenticated_mutation),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    service: InteractionService = Depends(get_interaction_service),
    db: Session = Depends(get_db),
) -> FrozenFinalInput:
    result = service.freeze_final(
        actor_user_id=str(context.user.id),
        debate_id=str(debate_id),
        expected_control_version=payload.expected_control_version,
    )
    from app.modules.debates.playback.router import get_playback_service

    # freeze_final commits through its own writer session; enqueue from that
    # committed state rather than this request's earlier authentication read.
    db.rollback()
    await get_playback_service(request).enqueue_frozen_final(db, str(debate_id))
    return result


# The anonymous form's last answers per token (fresh 2 s; stale under pressure).
_PUBLIC_FORMS = PublicCopy()


def audience_key(request: Request, access_token: str) -> str:
    """Per-person key for anonymous votes and barrages (never stored raw).

    Classroom devices usually share one NAT address, so the browser's own
    audience id (``X-Maya-Audience``, kept in its local storage) comes first;
    without it, address and user agent stand in. Scoped to the token's window.
    """

    audience = (request.headers.get("x-maya-audience") or "").strip()[:128]
    if not audience:
        client = request.client.host if request.client else ""
        audience = f"addr:{client}|ua:{request.headers.get('user-agent', '')[:256]}"
    # The token names one window (a new window issues a new token).
    return hashlib.sha256(f"{access_token}\n{audience}".encode()).hexdigest()


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


@router.get(
    "/debates/{debate_id}/interaction",
    response_model=TeacherInteraction,
    operation_id="getTeacherInteraction",
    responses={403: {"model": Error}, 404: {"model": Error}},
)
def get_teacher_interaction(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    _db: Any = Depends(get_db),
    service: InteractionService = Depends(get_interaction_service),
) -> TeacherInteraction:
    return service.get_teacher_interaction(
        actor_user_id=str(context.user.id), debate_id=str(debate_id)
    )


@router.post(
    "/debates/{debate_id}/interaction/open",
    response_model=TeacherInteraction,
    operation_id="openInteraction",
    responses={
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        503: {"model": Error},
    },
)
def open_interaction(
    debate_id: UUID,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    context: AuthContext = Depends(require_authenticated_mutation),
    _db: Any = Depends(get_db),
    service: InteractionService = Depends(get_interaction_service),
) -> TeacherInteraction:
    del request
    return service.open_interaction(
        actor_user_id=str(context.user.id),
        debate_id=str(debate_id),
        idempotency_key=idempotency_key,
    )


@router.post(
    "/debates/{debate_id}/interaction/close",
    response_model=TeacherInteraction,
    status_code=202,
    operation_id="closeInteraction",
    responses={403: {"model": Error}, 404: {"model": Error}, 409: {"model": Error}},
)
def close_interaction(
    debate_id: UUID,
    context: AuthContext = Depends(require_authenticated_mutation),
    _db: Any = Depends(get_db),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    service: InteractionService = Depends(get_interaction_service),
) -> TeacherInteraction:
    return service.close_interaction(
        actor_user_id=str(context.user.id),
        debate_id=str(debate_id),
        idempotency_key=idempotency_key,
    )


@router.get(
    "/classroom-interactions/{access_token}",
    response_model=PublicInteractionForm,
    operation_id="getClassroomInteractionForm",
    responses={404: {"model": Error}, 410: {"model": Error}},
)
def get_classroom_interaction_form(
    access_token: str,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: InteractionService = Depends(get_interaction_service),
) -> PublicInteractionForm:
    _no_store(response)
    # Every viewer polls this; under pressure a recent copy (or a 503 with
    # retry_after_seconds) answers instead of a database read.
    form: PublicInteractionForm = _PUBLIC_FORMS.read(
        access_token,
        settings,
        lambda: service.public_form(access_token=access_token),
        what="interaction_form",
    )
    return form


@router.post(
    "/classroom-interactions/{access_token}/votes",
    response_model=VoteSubmitted,
    status_code=201,
    operation_id="submitVote",
    responses={
        400: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        410: {"model": Error},
        422: {"model": Error},
        503: {"model": Error},
    },
)
async def submit_vote(
    access_token: str,
    payload: VoteRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: InteractionService = Depends(get_interaction_service),
) -> VoteSubmitted:
    _no_store(response)
    voter_key = audience_key(request, access_token)
    async with interaction_slot(settings):
        result: VoteSubmitted = await run_in_threadpool(
            lambda: service.submit_vote(
                access_token=access_token, payload=payload, voter_key=voter_key
            )
        )
    return result


@router.post(
    "/classroom-interactions/{access_token}/barrages",
    response_model=BarrageSubmitted,
    status_code=201,
    operation_id="submitBarrage",
    responses={
        400: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        410: {"model": Error},
        422: {"model": Error},
        429: {"model": Error},
        503: {"model": Error},
    },
)
async def submit_barrage(
    access_token: str,
    payload: BarrageRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    service: InteractionService = Depends(get_interaction_service),
) -> BarrageSubmitted:
    _no_store(response)
    voter_key = audience_key(request, access_token)
    async with interaction_slot(settings):
        result: BarrageSubmitted = await run_in_threadpool(
            lambda: service.submit_barrage(
                access_token=access_token, payload=payload, voter_key=voter_key
            )
        )
    return result


__all__ = ["get_interaction_service", "router"]
