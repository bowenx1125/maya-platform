"""Course-scoped Classroom Quiz HTTP routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.errors import Error
from app.modules.auth.dependencies import get_db, require_auth, require_authenticated_mutation
from app.modules.auth.service import AuthContext

from . import service
from .schemas import (
    CreateQuizRequest,
    PatchQuizRequest,
    QuizAttemptDTO,
    QuizSummaryDTO,
    RecordAttemptDTO,
    StudentQuizDTO,
    SubmitQuizAttemptRequest,
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
    "/courses/{course_id}/my-record-attempts",
    response_model=list[RecordAttemptDTO],
    operation_id="listMyRecordAttempts",
    responses={401: {"model": Error}, 404: {"model": Error}},
)
def list_my_record_attempts(
    course_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RecordAttemptDTO]:
    return service.list_my_record_attempts(db, actor, str(course_id))


@router.get(
    "/courses/{course_id}/record-attempts",
    response_model=list[RecordAttemptDTO],
    operation_id="listCourseRecordAttempts",
    responses={401: {"model": Error}, 403: {"model": Error}, 404: {"model": Error}},
)
def list_course_record_attempts(
    course_id: UUID,
    actor: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RecordAttemptDTO]:
    return service.list_course_record_attempts(db, actor, str(course_id))
