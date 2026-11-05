"""Parallel Quiz tables — never wired to assessment_attempts / conversations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published')", name="ck_classroom_quizzes_status"),
        Index("ix_classroom_quizzes_course_status", "course_id", "status"),
        Index("ix_classroom_quizzes_course_updated", "course_id", "updated_at"),
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
    teacher_hidden_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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
            name="ux_classroom_quiz_attempts_quiz_actor",
        ),
        Index("ix_classroom_quiz_attempts_course_actor", "course_id", "actor_user_id"),
        Index("ix_classroom_quiz_attempts_quiz", "quiz_id"),
    )
