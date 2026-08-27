"""FastAPI routes for the M10 Debate draft surface.

Playback and generation routes remain owned by Wave 2 peers.  These endpoints
only expose the teacher-scoped create/list/get/update/start setup boundary.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.debates.schemas import (
    DebateDetail,
    DebateDraftRequest,
    DebateDraftUpdateRequest,
    DebateSummary,
)
from app.modules.debates.setup.service import (
    create_debate_draft,
    get_debate,
    list_debates,
    update_debate_draft,
)

router = APIRouter(tags=["Debates"])


@router.get(
    "/courses/{course_id}/debates",
    response_model=list[DebateSummary],
    operation_id="listDebates",
    responses={
        200: {"model": list[DebateSummary]},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def list_debates_route(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[DebateSummary]:
    return list_debates(db, actor_user_id=context.user.id, course_id=str(course_id))


@router.post(
    "/courses/{course_id}/debates",
    response_model=DebateDetail,
    status_code=201,
    operation_id="createDebate",
    responses={
        201: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
def create_debate_route(
    course_id: UUID,
    payload: DebateDraftRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DebateDetail:
    return create_debate_draft(
        db,
        actor_user_id=context.user.id,
        course_id=str(course_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/debates/{debate_id}",
    response_model=DebateDetail,
    operation_id="getDebate",
    responses={
        200: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
    },
)
def get_debate_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DebateDetail:
    return get_debate(db, actor_user_id=context.user.id, debate_id=str(debate_id))


@router.patch(
    "/debates/{debate_id}",
    response_model=DebateDetail,
    operation_id="updateDebateDraft",
    responses={
        200: {"model": DebateDetail},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
def update_debate_route(
    debate_id: UUID,
    payload: DebateDraftUpdateRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DebateDetail:
    return update_debate_draft(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        payload=payload,
        expected_revision=payload.expected_revision,
    )


__all__ = ["router"]
