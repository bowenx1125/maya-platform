"""FastAPI routes for teacher and anonymous classroom interaction."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from app.core.config import Settings, get_settings
from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import (
    BarrageRequest,
    BarrageSubmitted,
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
    _db: Any = Depends(get_db),
    service: InteractionService = Depends(get_interaction_service),
) -> PublicInteractionForm:
    _no_store(response)
    return service.public_form(access_token=access_token)


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
    },
)
def submit_vote(
    access_token: str,
    payload: VoteRequest,
    response: Response,
    _db: Any = Depends(get_db),
    service: InteractionService = Depends(get_interaction_service),
) -> VoteSubmitted:
    _no_store(response)
    return service.submit_vote(access_token=access_token, payload=payload)


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
    },
)
def submit_barrage(
    access_token: str,
    payload: BarrageRequest,
    response: Response,
    _db: Any = Depends(get_db),
    service: InteractionService = Depends(get_interaction_service),
) -> BarrageSubmitted:
    _no_store(response)
    return service.submit_barrage(access_token=access_token, payload=payload)


__all__ = ["get_interaction_service", "router"]
