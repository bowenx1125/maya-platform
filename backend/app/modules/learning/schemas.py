"""Closed learning-record and versioned Assessment service contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerRecordRequest(StrictModel):
    kind: Literal["answer"]
    client_event_id: UUID
    question_version_id: UUID | None = None
    answer_text: str = Field(min_length=1)


class SkipRecordRequest(StrictModel):
    kind: Literal["skip"]
    client_event_id: UUID
    question_version_id: UUID | None = None
    reason: str | None = None


class HintRecordRequest(StrictModel):
    kind: Literal["hint"]
    client_event_id: UUID
    question_version_id: UUID | None = None
    hint_ref: str = Field(min_length=1)


class LearningEvidenceRequest(StrictModel):
    kind: Literal["evidence"]
    client_event_id: UUID
    evidence_kind: str = Field(min_length=1)
    payload: dict[str, Any]


LearningRecordRequest = Annotated[
    AnswerRecordRequest | SkipRecordRequest | HintRecordRequest | LearningEvidenceRequest,
    Field(discriminator="kind"),
]


class LearningProvenance(StrictModel):
    actor_user_id: UUID
    course_id: UUID
    conversation_id: UUID
    team_id: UUID | None
    team_version_id: UUID | None
    origin: Literal["single_agent", "custom_team", "published_course_team"]
    chat_visibility: Literal["private", "public"]
    activity_id: UUID | None = None
    attempt_id: UUID | None = None


class LearningRecordDTO(StrictModel):
    id: UUID
    client_event_id: UUID
    kind: Literal["answer", "skip", "hint", "evidence"]
    payload: dict[str, Any]
    provenance: LearningProvenance
    created_at: datetime


class CreateAssessmentRequest(StrictModel):
    client_event_id: UUID
    content: dict[str, Any] = Field(min_length=1)


class EditAssessmentRequest(CreateAssessmentRequest):
    expected_revision: int = Field(ge=1)


class AssessmentRevisionDTO(StrictModel):
    id: UUID
    revision_seq: int = Field(ge=1)
    previous_revision_id: UUID | None
    content: dict[str, Any]
    content_hash: str
    revision_source: Literal["user_authored", "model_evaluation", "practice_agent_edit"]
    provenance: LearningProvenance
    created_at: datetime


class AssessmentDTO(StrictModel):
    id: UUID
    owner_user_id: UUID
    course_id: UUID
    current_revision_seq: int = Field(ge=1)
    current: AssessmentRevisionDTO
    revisions: list[AssessmentRevisionDTO]
    created_at: datetime
    updated_at: datetime


class AssessmentWriteReceipt(StrictModel):
    assessment_id: UUID
    revision: AssessmentRevisionDTO


AssessmentClassification = Literal[
    "start_request",
    "restart_request",
    "answer_only",
    "answer_with_restricted_request",
    "skip_request",
    "pause_request",
    "resume_request",
    "complete_request",
    "abandon_request",
    "redo_request",
    "progress_request",
    "answers_request",
    "restricted_request",
    "off_topic",
]


class AssessmentRuntimeDecision(StrictModel):
    """Closed classifier result; answer spans are verified against saved user text."""

    client_event_id: UUID
    classification: AssessmentClassification
    answer_span: str | None = None
    question_version_id: UUID | None = None


class AssessmentStudentAction(StrictModel):
    """Only a semantic action and an exact span from the stored user message."""

    classification: AssessmentClassification
    answer_span: str | None = None
    # Free questions: the model's category and confidence (0-1). Only input to
    # the server's guard; never decides recording by itself.
    category: Literal["answer", "off_topic", "other"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    # Deprecated (pre-2026-10-20 prompt): True maps to category answer.
    relevant: bool | None = None
    # Student-facing sentence when that message is not saved.
    guidance: str | None = None


class AssessmentEvaluationQuestion(StrictModel):
    question_ordinal: int = Field(ge=0)
    feedback: str = Field(min_length=1)
    points_awarded: float | None = Field(default=None, ge=0)


class AssessmentEvaluationContent(StrictModel):
    overall_feedback: str = Field(min_length=1)
    questions: list[AssessmentEvaluationQuestion] = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class BoundarySummaryContent(StrictModel):
    summary: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    areas_to_explore: list[str] = Field(default_factory=list)
    not_yet_verified: list[str] = Field(default_factory=list)
    next_step: str | None = None


class AssessmentAttemptSummary(StrictModel):
    id: UUID
    activity_id: UUID
    conversation_id: UUID
    chat_visibility: Literal["private", "public"]
    status: Literal["in_progress", "paused", "completed", "abandoned"]
    revision: int = Field(ge=0)


class AssessmentProgressProjection(StrictModel):
    """Student-safe progress contains counts and states, never answers or scores."""

    attempt_id: UUID
    status: Literal["in_progress", "paused", "completed", "abandoned"]
    question_count: int = Field(ge=0)
    presented_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    answered_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    current_ordinal: int | None = Field(default=None, ge=0)
    current_question_version_id: UUID | None = None


class AssessmentRuntimeQuestion(StrictModel):
    """The visible question projection intentionally omits Rubric and reference answer."""

    ordinal: int = Field(ge=0)
    question_version_id: UUID
    prompt: str = Field(min_length=1)


class AssessmentRuntimeContext(StrictModel):
    attempt: AssessmentAttemptSummary
    progress: AssessmentProgressProjection
    current_question: AssessmentRuntimeQuestion | None
    canonical_conversation_id: UUID
    redirect_to_original_conversation: bool


AssessmentRuntimeResponseKey = Literal[
    "assessment.started",
    "assessment.answer_recorded",
    "assessment.answer_recorded_restricted_request",
    "assessment.paused",
    "assessment.resumed",
    "assessment.completed",
    "assessment.abandoned",
    "assessment.abandoned_and_restarted",
    "assessment.progress",
    "assessment.answers",
    "assessment.results_pending",
    "assessment.restart_requires_choice",
    "assessment.redirect",
]


class AssessmentAnswerDTO(StrictModel):
    question_ordinal: int = Field(ge=0)
    # Nullable: older/partial attempt rows may lack a frozen version id; Record
    # still lists those answers (prod 2026-10-27 my-assessment-attempts 500).
    question_version_id: UUID | None = None
    answer_text: str = Field(min_length=1)
    created_at: datetime


class AssessmentOwnerAnswerDTO(StrictModel):
    answer_text: str = Field(min_length=1)
    created_at: datetime


class AssessmentRuntimeResult(StrictModel):
    disposition: Literal["recorded", "transitioned", "read", "redirected"]
    response_key: AssessmentRuntimeResponseKey
    context: AssessmentRuntimeContext
    answers: list[AssessmentOwnerAnswerDTO] = Field(default_factory=list)
    # Spoken when the message was not saved. Absent on older receipts.
    guidance: str | None = None


class AssessmentActorReport(StrictModel):
    student_name: str = Field(min_length=1)
    learner_ref: str = Field(min_length=1)
    attempt_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    abandoned_count: int = Field(ge=0)
    in_progress_count: int = Field(ge=0)
    paused_count: int = Field(ge=0)
    effective_answer_count: int = Field(ge=0)
    raw_answer_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    boundary_summary: str | None = None
    mastery_evidence: list[str] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    not_yet_verified: list[str] = Field(default_factory=list)


class AssessmentReportContent(StrictModel):
    course_name: str = Field(min_length=1)
    team_name: str = Field(min_length=1)
    activity_name: str = Field(min_length=1)
    generated_at: datetime
    student_count: int = Field(ge=0)
    attempt_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    abandoned_count: int = Field(ge=0)
    in_progress_count: int = Field(ge=0)
    paused_count: int = Field(ge=0)
    effective_answer_count: int = Field(ge=0)
    raw_answer_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    actors: list[AssessmentActorReport]


class AssessmentCourseReportDTO(StrictModel):
    id: UUID
    course_id: UUID
    activity_id: UUID
    revision_id: UUID
    revision_seq: int = Field(ge=1)
    source_hash: str
    content: AssessmentReportContent
    created_at: datetime


class AssessmentCourseReportReceipt(StrictModel):
    report: AssessmentCourseReportDTO


class AssessmentActivityListItem(StrictModel):
    id: UUID
    name: str = Field(min_length=1)
    team_name: str = Field(min_length=1)
    created_at: datetime


class AssessmentReportDownload(StrictModel):
    filename: str
    content_type: Literal["text/markdown; charset=utf-8"]
    content: str


__all__ = [
    "AnswerRecordRequest",
    "AssessmentDTO",
    "AssessmentAnswerDTO",
    "AssessmentActorReport",
    "AssessmentActivityListItem",
    "AssessmentAttemptSummary",
    "AssessmentEvaluationContent",
    "AssessmentEvaluationQuestion",
    "BoundarySummaryContent",
    "AssessmentCourseReportDTO",
    "AssessmentCourseReportReceipt",
    "AssessmentReportContent",
    "AssessmentReportDownload",
    "AssessmentClassification",
    "AssessmentProgressProjection",
    "AssessmentRevisionDTO",
    "AssessmentRuntimeContext",
    "AssessmentRuntimeDecision",
    "AssessmentStudentAction",
    "AssessmentRuntimeQuestion",
    "AssessmentRuntimeResult",
    "AssessmentWriteReceipt",
    "CreateAssessmentRequest",
    "EditAssessmentRequest",
    "HintRecordRequest",
    "LearningEvidenceRequest",
    "LearningProvenance",
    "LearningRecordDTO",
    "LearningRecordRequest",
    "SkipRecordRequest",
    "StrictModel",
]
