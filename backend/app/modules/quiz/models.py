"""Parallel Quiz tables — never wired to assessment_attempts / conversations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class ClassroomQuiz(Base):
    """One course-scoped questionnaire paper (draft or published)."""

    __tablename__ = "classroom_quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    document_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    show_results: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Publish only freezes the paper; taking opens via start-taking epochs.
    taking_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    taking_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_classroom_quizzes_status"),
        Index("ix_classroom_quizzes_course_status", "course_id", "status"),
        Index("ix_classroom_quizzes_course_updated", "course_id", "updated_at"),
        Index("ix_classroom_quizzes_scheduled_start", "scheduled_start_at"),
        Index("ix_classroom_quizzes_scheduled_end", "scheduled_end_at"),
    )


class ClassroomQuizAttempt(Base):
    """One student's submitted answers for a published quiz revision."""

    __tablename__ = "classroom_quiz_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("classroom_quizzes.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    document_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    score_objective: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_max_objective: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    grading_status: Mapped[str] = mapped_column(String(16), nullable=False, default="complete")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    taking_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teacher_hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Teacher-entered grades for text items: {item_id: {points_awarded,
    # feedback, graded_by_user_id, graded_at}}. score_objective stays the
    # automatic part so a manual grade can never rewrite the key's result.
    manual_grades_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    score_manual: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "grading_status IN ('complete', 'pending', 'mixed')",
            name="ck_classroom_quiz_attempts_grading",
        ),
        CheckConstraint(
            "status IN ('submitted')",
            name="ck_classroom_quiz_attempts_status",
        ),
        UniqueConstraint(
            "quiz_id",
            "actor_user_id",
            "taking_epoch",
            name="ux_classroom_quiz_attempts_quiz_actor_epoch",
        ),
        Index("ix_classroom_quiz_attempts_course_actor", "course_id", "actor_user_id"),
        Index("ix_classroom_quiz_attempts_quiz", "quiz_id"),
    )


class ClassroomQuizExemption(Base):
    """Teacher-granted time for one student in one taking epoch."""

    __tablename__ = "classroom_quiz_exemptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("classroom_quizzes.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    student_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    taking_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "quiz_id",
            "student_user_id",
            "taking_epoch",
            name="ux_classroom_quiz_exemptions_quiz_student_epoch",
        ),
        Index("ix_classroom_quiz_exemptions_quiz", "quiz_id"),
    )
