"""Teacher-only local routes for the bounded Real-Core Demo run ledger."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import (
    DemoAcceptanceCallRequest,
    DemoAcceptanceRunBindDebateRequest,
    DemoAcceptanceRunBindReportRequest,
    DemoAcceptanceRunCreateRequest,
    DemoAcceptanceRunResponse,
)
from .service import (
    attach_acceptance_call,
    bind_acceptance_run_debate,
    bind_acceptance_run_report,
    create_acceptance_run,
    get_acceptance_run,
)

router = APIRouter(
    prefix="/demo/acceptance-runs",
    tags=["Demo"],
    include_in_schema=False,
)


@router.post(
    "",
    response_model=DemoAcceptanceRunResponse,
    status_code=201,
    responses={401: {"model": Error}, 403: {"model": Error}, 409: {"model": Error}},
)
def create_demo_acceptance_run(
    payload: DemoAcceptanceRunCreateRequest,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return create_acceptance_run(db, actor_user_id=str(context.user.id), request=payload)


@router.get(
    "/{run_id}",
    response_model=DemoAcceptanceRunResponse,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def get_demo_acceptance_run(
    run_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return get_acceptance_run(db, actor_user_id=str(context.user.id), run_id=str(run_id))


@router.post(
    "/{run_id}/debate",
    response_model=DemoAcceptanceRunResponse,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def bind_demo_acceptance_debate(
    run_id: UUID,
    payload: DemoAcceptanceRunBindDebateRequest,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return bind_acceptance_run_debate(
        db,
        actor_user_id=str(context.user.id),
        run_id=str(run_id),
        request=payload,
    )


@router.post(
    "/{run_id}/report",
    response_model=DemoAcceptanceRunResponse,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def bind_demo_acceptance_report(
    run_id: UUID,
    payload: DemoAcceptanceRunBindReportRequest,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return bind_acceptance_run_report(
        db,
        actor_user_id=str(context.user.id),
        run_id=str(run_id),
        request=payload,
    )


@router.post(
    "/{run_id}/calls",
    response_model=DemoAcceptanceRunResponse,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def attach_demo_acceptance_call(
    run_id: UUID,
    payload: DemoAcceptanceCallRequest,
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return attach_acceptance_call(
        db,
        actor_user_id=str(context.user.id),
        run_id=str(run_id),
        request=payload,
    )


@router.get(
    "/{run_id}/summary",
    response_model=DemoAcceptanceRunResponse,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def get_demo_acceptance_summary(
    run_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DemoAcceptanceRunResponse:
    return get_acceptance_run(db, actor_user_id=str(context.user.id), run_id=str(run_id))


__all__ = ["router"]
