"""Classroom Quiz DTOs — teacher payloads keep answers; student payloads strip them."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

QuizStatus = Literal["draft", "published"]
ItemType = Literal["single", "multiple", "short_text", "long_text"]
GradingStatus = Literal["complete", "pending", "mixed"]
RecordSource = Literal["quiz", "chat"]


class QuizChoice(BaseModel):
    id: str
    label: str


class QuizAnswerKey(BaseModel):
    choice_ids: list[str] | None = None
    rubric: str | None = None


class QuizItemGrading(BaseModel):
    mode: Literal["manual", "ai"] = "manual"
    score_min: float | None = None
    score_max: float | None = None
    rules: str | None = None


class QuizItemTeacher(BaseModel):
    id: str
    type: ItemType
    required: bool = True
    prompt: str
    choices: list[QuizChoice] = Field(default_factory=list)
    answer: QuizAnswerKey | None = None
    points: float = 1
    grading: QuizItemGrading | None = None


class QuizItemStudent(BaseModel):
    """Student-facing item: answer / rubric must never appear."""

    id: str
    type: ItemType
    required: bool = True
    prompt: str
    choices: list[QuizChoice] = Field(default_factory=list)
    points: float = 1


class QuizSettings(BaseModel):
    shuffle_questions: bool = False
    shuffle_choices: bool = False
    allow_skip: bool = False
    time_limit_sec: int | None = None


class QuizDocumentTeacher(BaseModel):
    schema_version: int = 1
    quiz_id: UUID | None = None
    group_id: UUID | None = None
    title: str
    locale: str = "en"
    status: QuizStatus = "draft"
    settings: QuizSettings = Field(default_factory=QuizSettings)
    items: list[QuizItemTeacher] = Field(default_factory=list)


class QuizDocumentStudent(BaseModel):
    schema_version: int = 1
    quiz_id: UUID
    group_id: UUID | None = None
    title: str
    locale: str = "en"
    status: Literal["published"] = "published"
    settings: QuizSettings = Field(default_factory=QuizSettings)
    items: list[QuizItemStudent] = Field(default_factory=list)


class CreateQuizRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    group_id: UUID | None = None
    settings: QuizSettings | None = None
    items: list[QuizItemTeacher] = Field(default_factory=list)
    locale: str = "en"

    @field_validator("title")
    @classmethod
    def _title_strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title is required")
        return cleaned


class PatchQuizRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    group_id: UUID | None = None
    settings: QuizSettings | None = None
    items: list[QuizItemTeacher] | None = None
    locale: str | None = None

    @field_validator("title")
    @classmethod
    def _title_strip(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title is required")
        return cleaned


class QuizSummaryDTO(BaseModel):
    id: UUID
    course_id: UUID
    group_id: UUID | None = None
    title: str
    status: QuizStatus
    schema_version: int
    content_revision: int
    attempt_count: int = 0
    taking_open: bool = False
    taking_epoch: int = 0
    created_by_user_id: UUID
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class TeacherQuizDTO(QuizSummaryDTO):
    settings: QuizSettings
    locale: str = "en"
    items: list[QuizItemTeacher] = Field(default_factory=list)


class StudentQuizDTO(BaseModel):
    id: UUID
    course_id: UUID
    group_id: UUID | None = None
    title: str
    status: Literal["published"]
    schema_version: int
    content_revision: int
    taking_open: bool = False
    taking_epoch: int = 0
    settings: QuizSettings
    locale: str = "en"
    items: list[QuizItemStudent] = Field(default_factory=list)
    published_at: datetime | None = None


class QuizAnswerSubmission(BaseModel):
    item_id: str
    choice_ids: list[str] | None = None
    text: str | None = None

    @model_validator(mode="after")
    def _one_payload(self) -> QuizAnswerSubmission:
        has_choices = self.choice_ids is not None
        has_text = self.text is not None
        if has_choices == has_text:
            # Exactly one of choice_ids / text should be provided (text may be "").
            if not has_choices and not has_text:
                raise ValueError("each answer needs choice_ids or text")
        return self


class SubmitQuizAttemptRequest(BaseModel):
    answers: list[QuizAnswerSubmission] = Field(min_length=1)


class QuizAttemptDTO(BaseModel):
    id: UUID
    quiz_id: UUID
    course_id: UUID
    actor_user_id: UUID
    content_revision: int
    taking_epoch: int = 0
    status: Literal["submitted"]
    grading_status: GradingStatus
    score_objective: float
    score_max_objective: float
    answers: list[dict[str, Any]] = Field(default_factory=list)
    submitted_at: datetime


class RecordAttemptDTO(BaseModel):
    """Unified Record row for Quiz and legacy chat attempts."""

    source: RecordSource
    attempt_id: UUID
    user_id: UUID
    student_name: str
    title: str
    status: str
    submitted_at: datetime | None = None
    score_objective: float | None = None
    score_max_objective: float | None = None
    grading_status: GradingStatus | None = None
    quiz_id: UUID | None = None
    conversation_id: UUID | None = None
    points_awarded: float | None = None
    points_total: float | None = None
    phase: str | None = None
    team_name: str | None = None
    taking_epoch: int | None = None
    content_revision: int | None = None


class QuizAttemptItemStudent(BaseModel):
    """One item of the paper as it was frozen at submit, with the response.

    No answer key or rubric: a student sees their own choices, whether a
    choice item was right, and the teacher's grade and feedback.
    """

    id: str
    type: ItemType | Literal["unknown"]
    required: bool = True
    prompt: str = ""
    choices: list[QuizChoice] = Field(default_factory=list)
    points: float = 0
    response_choice_ids: list[str] | None = None
    response_text: str | None = None
    correct: bool | None = None
    points_awarded: float | None = None
    graded: bool = False
    feedback: str | None = None


class QuizAttemptItemTeacher(QuizAttemptItemStudent):
    answer: QuizAnswerKey | None = None


class StudentQuizAttemptDetailDTO(BaseModel):
    # The route returns either shape; a distinct literal keeps a student's
    # payload from ever validating as the teacher one (which adds the key).
    view: Literal["student"] = "student"
    id: UUID
    quiz_id: UUID
    course_id: UUID
    user_id: UUID
    student_name: str
    title: str
    content_revision: int
    taking_epoch: int
    status: Literal["submitted"]
    grading_status: GradingStatus
    score_objective: float
    score_max_objective: float
    score_manual: float
    score_max_manual: float
    points_awarded: float
    points_total: float
    submitted_at: datetime
    graded_at: datetime | None = None
    items: list[QuizAttemptItemStudent] = Field(default_factory=list)


class TeacherQuizAttemptDetailDTO(StudentQuizAttemptDetailDTO):
    view: Literal["teacher"] = "teacher"  # type: ignore[assignment]
    items: list[QuizAttemptItemTeacher] = Field(default_factory=list)  # type: ignore[assignment]


class QuizItemGrade(BaseModel):
    item_id: str = Field(min_length=1, max_length=200)
    points_awarded: float = Field(ge=0, allow_inf_nan=False)
    feedback: str = Field(default="", max_length=4000)


class GradeQuizAttemptRequest(BaseModel):
    grades: list[QuizItemGrade] = Field(min_length=1, max_length=500)
