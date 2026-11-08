"""Course-scoped Classroom Quiz HTTP routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from . import export as quiz_export
from . import service
from .schemas import (
    CreateQuizRequest,
    GradeQuizAttemptRequest,
    PatchQuizRequest,
    QuizAttemptDTO,
    QuizSummaryDTO,
    RecordAttemptDTO,
    StudentQuizAttemptDetailDTO,
    StudentQuizDTO,
    SubmitQuizAttemptRequest,
    TeacherQuizAttemptDetailDTO,
    TeacherQuizDTO,
)

router = APIRouter(tags=["Classroom Quiz"])

CsrfHeader = Annotated[str, Header(alias="X-CSRF-Token", min_length=32)]


@router.get(
    "/courses/{course_id}/quizzes",
    response_model=list[QuizSummaryDTO],
    operation_id="listCourseQuizzes",
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def list_course_quizzes(
    course_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[QuizSummaryDTO]:
    return service.list_quizzes_for_actor(db, actor, str(course_id))


@router.post(
    "/courses/{course_id}/quizzes",
    response_model=TeacherQuizDTO,
    status_code=201,
    operation_id="createCourseQuiz",
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def create_course_quiz(
    course_id: UUID,
    body: CreateQuizRequest,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.create_quiz(db, actor, str(course_id), body)


@router.get(
    "/courses/{course_id}/quizzes/{quiz_id}",
    response_model=TeacherQuizDTO | StudentQuizDTO,
    operation_id="getCourseQuiz",
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def get_course_quiz(
    course_id: UUID,
    quiz_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO | StudentQuizDTO:
    return service.get_quiz_for_actor(db, actor, str(course_id), str(quiz_id))


@router.patch(
    "/courses/{course_id}/quizzes/{quiz_id}",
    response_model=TeacherQuizDTO,
    operation_id="patchCourseQuiz",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def patch_course_quiz(
    course_id: UUID,
    quiz_id: UUID,
    body: PatchQuizRequest,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.patch_quiz(db, actor, str(course_id), str(quiz_id), body)


@router.post(
    "/courses/{course_id}/quizzes/{quiz_id}/publish",
    response_model=TeacherQuizDTO,
    operation_id="publishCourseQuiz",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
        422: {"model": Error},
    },
)
def publish_course_quiz(
    course_id: UUID,
    quiz_id: UUID,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.publish_quiz(db, actor, str(course_id), str(quiz_id))


@router.post(
    "/courses/{course_id}/quizzes/{quiz_id}/unpublish",
    response_model=TeacherQuizDTO,
    operation_id="unpublishCourseQuiz",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def unpublish_course_quiz(
    course_id: UUID,
    quiz_id: UUID,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.unpublish_quiz(db, actor, str(course_id), str(quiz_id))


@router.post(
    "/courses/{course_id}/quizzes/{quiz_id}/start-taking",
    response_model=TeacherQuizDTO,
    operation_id="startCourseQuizTaking",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def start_course_quiz_taking(
    course_id: UUID,
    quiz_id: UUID,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.start_taking(db, actor, str(course_id), str(quiz_id))


@router.post(
    "/courses/{course_id}/quizzes/{quiz_id}/pause-taking",
    response_model=TeacherQuizDTO,
    operation_id="pauseCourseQuizTaking",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def pause_course_quiz_taking(
    course_id: UUID,
    quiz_id: UUID,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizDTO:
    return service.pause_taking(db, actor, str(course_id), str(quiz_id))


@router.post(
    "/courses/{course_id}/quizzes/{quiz_id}/attempts",
    response_model=QuizAttemptDTO,
    status_code=201,
    operation_id="submitCourseQuizAttempt",
    responses={
        401: {"model": Error},
        403: {"model": Error},
        404: {"model": Error},
        409: {"model": Error},
    },
)
def submit_course_quiz_attempt(
    course_id: UUID,
    quiz_id: UUID,
    body: SubmitQuizAttemptRequest,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> QuizAttemptDTO:
    return service.submit_attempt(db, actor, str(course_id), str(quiz_id), body)


@router.get(
    "/courses/{course_id}/quizzes/{quiz_id}/attempts/export",
    operation_id="exportCourseQuizAttempts",
    response_class=Response,
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def export_course_quiz_attempts(
    course_id: UUID,
    quiz_id: UUID,
    taking_epoch: int | None = Query(default=None),
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    download = quiz_export.export_quiz_attempts(
        db,
        actor,
        str(course_id),
        str(quiz_id),
        taking_epoch=taking_epoch,
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


# Declared after /attempts/export: Starlette matches paths in order, and
# "export" would otherwise reach the UUID parameter and fail validation.
@router.get(
    "/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}",
    response_model=TeacherQuizAttemptDetailDTO | StudentQuizAttemptDetailDTO,
    operation_id="getCourseQuizAttempt",
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def get_course_quiz_attempt(
    course_id: UUID,
    quiz_id: UUID,
    attempt_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> TeacherQuizAttemptDetailDTO | StudentQuizAttemptDetailDTO:
    return service.get_attempt_for_actor(db, actor, str(course_id), str(quiz_id), str(attempt_id))


@router.delete(
    "/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}",
    status_code=204,
    operation_id="hideCourseQuizAttempt",
    response_class=Response,
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def hide_course_quiz_attempt(
    course_id: UUID,
    quiz_id: UUID,
    attempt_id: UUID,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> Response:
    service.hide_attempt(db, actor, str(course_id), str(quiz_id), str(attempt_id))
    return Response(status_code=204)


@router.put(
    "/courses/{course_id}/quizzes/{quiz_id}/attempts/{attempt_id}/grades",
    response_model=TeacherQuizAttemptDetailDTO,
    operation_id="gradeCourseQuizAttempt",
    responses={401: {"model": Error}, 404: {"model": Error}, 422: {"model": Error}},
)
def grade_course_quiz_attempt(
    course_id: UUID,
    quiz_id: UUID,
    attempt_id: UUID,
    body: GradeQuizAttemptRequest,
    _csrf: CsrfHeader,
    actor: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> TeacherQuizAttemptDetailDTO:
    return service.grade_attempt(db, actor, str(course_id), str(quiz_id), str(attempt_id), body)


@router.get(
    "/courses/{course_id}/my-record-attempts",
    response_model=list[RecordAttemptDTO],
    operation_id="listMyRecordAttempts",
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def list_my_record_attempts(
    course_id: UUID,
    quiz_id: UUID | None = Query(default=None),
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RecordAttemptDTO]:
    return service.list_my_record_attempts(
        db, actor, str(course_id), quiz_id=str(quiz_id) if quiz_id else None
    )


@router.get(
    "/courses/{course_id}/record-attempts",
    response_model=list[RecordAttemptDTO],
    operation_id="listCourseRecordAttempts",
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def list_course_record_attempts(
    course_id: UUID,
    quiz_id: UUID | None = Query(default=None),
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RecordAttemptDTO]:
    return service.list_course_record_attempts(
        db, actor, str(course_id), quiz_id=str(quiz_id) if quiz_id else None
    )
