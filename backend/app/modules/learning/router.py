"""Authorized assessment activity listing and persisted report routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext
from app.modules.org.schemas import OverviewResult

from .reports import (
    download_assessment_course_report,
    hide_course_assessment_attempt,
    list_course_assessment_attempts,
    list_my_assessment_attempts,
)

router = APIRouter(prefix="/learning", tags=["learning"])


@router.get(
    "/courses/{course_id}/assessment-attempts",
    response_model=list[OverviewResult],
    operation_id="listCourseAssessmentAttempts",
    responses={404: {"model": Error}},
)
def list_course_assessment_attempts_route(
    course_id: UUID,
    group_id: UUID | None = Query(default=None),
    attempt_id: UUID | None = Query(default=None),
    conversation_id: UUID | None = Query(default=None),
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[OverviewResult]:
    """Formal attempts for a course teacher, with no group visit required."""

    return [
        OverviewResult.model_validate(row)
        for row in list_course_assessment_attempts(
            db,
            actor,
            course_id=str(course_id),
            group_id=str(group_id) if group_id is not None else None,
            attempt_id=str(attempt_id) if attempt_id is not None else None,
            conversation_id=str(conversation_id) if conversation_id is not None else None,
        )
    ]


@router.get(
    "/courses/{course_id}/my-assessment-attempts",
    response_model=list[OverviewResult],
    operation_id="listMyAssessmentAttempts",
    responses={404: {"model": Error}},
)
def list_my_assessment_attempts_route(
    course_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[OverviewResult]:
    """The signed-in student's own formal attempts, for the student's Record."""

    return [
        OverviewResult.model_validate(row)
        for row in list_my_assessment_attempts(db, actor, course_id=str(course_id))
    ]


@router.delete(
    "/courses/{course_id}/assessment-attempts/{attempt_id}",
    status_code=204,
    operation_id="deleteCourseAssessmentAttempt",
    response_class=Response,
    responses={404: {"model": Error}},
)
def delete_course_assessment_attempt_route(
    course_id: UUID,
    attempt_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Response:
    """A course teacher deletes an attempt from Record. It is only hidden."""

    hide_course_assessment_attempt(db, actor, course_id=str(course_id), attempt_id=str(attempt_id))
    return Response(status_code=204)


@router.get(
    "/reports/{report_id}/download",
    operation_id="downloadAssessmentCourseReport",
    response_class=Response,
    responses={404: {"model": Error}, 409: {"model": Error}},
)
def download_assessment_report_route(
    report_id: UUID,
    revision_id: UUID | None = Query(default=None),
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    download = download_assessment_course_report(
        db,
        actor,
        report_id=str(report_id),
        revision_id=str(revision_id) if revision_id is not None else None,
    )
    return Response(
        content=download.content,
        media_type=download.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["router"]
