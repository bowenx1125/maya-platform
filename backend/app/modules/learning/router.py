"""Authorized assessment activity listing and persisted report routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.errors import Error, not_found
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from .attempts import apply_attempt_lifecycle_action
from .models import AssessmentActivity
from .reports import (
    create_assessment_course_report,
    download_assessment_course_report,
    list_authorized_assessment_activities,
)
from .schemas import (
    AssessmentActivityListItem,
    AssessmentCourseReportReceipt,
    AssessmentLifecycleActionRequest,
    AssessmentRuntimeResult,
    CreateAssessmentReportRequest,
)

router = APIRouter(prefix="/learning", tags=["learning"])


@router.post(
    "/attempts/{attempt_id}/actions",
    response_model=AssessmentRuntimeResult,
    operation_id="applyAssessmentLifecycleAction",
    responses={404: {"model": Error}, 409: {"model": Error}},
)
def apply_assessment_lifecycle_action_route(
    attempt_id: UUID,
    payload: AssessmentLifecycleActionRequest,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AssessmentRuntimeResult:
    result = apply_attempt_lifecycle_action(
        db,
        actor,
        str(attempt_id),
        client_event_id=payload.client_event_id,
        action=payload.action,
    )
    if result is None:
        raise not_found()
    return result


@router.get(
    "/courses/{course_id}/assessment-activities",
    response_model=list[AssessmentActivityListItem],
    operation_id="listAuthorizedAssessmentActivities",
    responses={404: {"model": Error}},
)
def list_assessment_activities_route(
    course_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[AssessmentActivityListItem]:
    return list_authorized_assessment_activities(db, actor, course_id=str(course_id))


@router.post(
    "/activities/{activity_id}/reports",
    response_model=AssessmentCourseReportReceipt,
    status_code=201,
    operation_id="createAssessmentCourseReport",
    responses={404: {"model": Error}, 409: {"model": Error}},
)
def create_assessment_report_route(
    activity_id: UUID,
    payload: CreateAssessmentReportRequest,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> AssessmentCourseReportReceipt:
    activity = db.get(AssessmentActivity, str(activity_id))
    if activity is None:
        raise not_found()
    return create_assessment_course_report(
        db,
        actor,
        course_id=activity.course_id,
        activity_id=activity.id,
        client_event_id=payload.client_event_id,
    )


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
