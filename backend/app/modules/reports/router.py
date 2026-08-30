"""Teacher-only M14 report and anonymous insight read routes."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .schemas import Report, ReportRevision, ReportRevisionSummary
from .service import (
    download_current_report,
    get_current_report,
    get_report_revision,
    list_report_revisions,
    regenerate_report,
)

router = APIRouter(tags=["Reports"])


@router.get(
    "/debates/{debate_id}/report",
    response_model=Report,
    operation_id="getCurrentReport",
    responses={403: {"model": Error}, 404: {"model": Error}},
)
def get_current_report_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Report:
    return get_current_report(db, actor_user_id=context.user.id, debate_id=str(debate_id))


@router.post(
    "/debates/{debate_id}/report/generate",
    response_model=Report,
    status_code=202,
    operation_id="regenerateReport",
    responses={403: {"model": Error}, 404: {"model": Error}, 409: {"model": Error}},
)
def regenerate_report_route(
    debate_id: UUID,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=16),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Report:
    result = regenerate_report(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        idempotency_key=idempotency_key,
    )
    manager = getattr(request.app.state, "report_task_manager", None)
    wake = getattr(manager, "wake", None)
    if callable(wake):
        wake(str(debate_id))
    return result


@router.get(
    "/debates/{debate_id}/report/revisions",
    response_model=list[ReportRevisionSummary],
    operation_id="listReportRevisions",
    responses={403: {"model": Error}, 404: {"model": Error}},
)
def list_report_revisions_route(
    debate_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[ReportRevisionSummary]:
    return list_report_revisions(db, actor_user_id=context.user.id, debate_id=str(debate_id))


@router.get(
    "/debates/{debate_id}/report/revisions/{revision_id}",
    response_model=ReportRevision,
    operation_id="getReportRevision",
    responses={403: {"model": Error}, 404: {"model": Error}},
)
def get_report_revision_route(
    debate_id: UUID,
    revision_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ReportRevision:
    return get_report_revision(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        revision_id=str(revision_id),
    )


@router.get(
    "/debates/{debate_id}/report/download",
    operation_id="downloadCurrentReport",
    response_class=Response,
    responses={
        200: {
            "content": {"text/markdown; charset=utf-8": {"schema": {"type": "string"}}},
            "headers": {
                "Content-Disposition": {"schema": {"type": "string"}},
                "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
                "X-Content-Type-Options": {"schema": {"type": "string", "const": "nosniff"}},
            },
        },
        403: {"model": Error},
        404: {"model": Error},
    },
)
def download_current_report_route(
    debate_id: UUID,
    language: Literal["en", "zh-Hans"] = Query(default="en"),
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    content, filename = download_current_report(
        db,
        actor_user_id=context.user.id,
        debate_id=str(debate_id),
        language=language,
    )
    # Keep the filename entirely server-generated and use the common safe
    # RFC-5987 helper in the route owner when the main window wires this panel
    # into its shared download utility.  UUID-only names are already safe.
    from app.modules.knowledge.files import content_disposition

    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown",
        headers={
            "Content-Type": "text/markdown; charset=utf-8",
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
