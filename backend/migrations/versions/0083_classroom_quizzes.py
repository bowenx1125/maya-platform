"""Parallel Classroom Quiz tables (questionnaire assessments).

Quiz attempts must not use assessment_attempts or conversation FKs.
See docs/adr/ADR-011-classroom-quiz-parallel-domain.md.

Revision ID: 0083_classroom_quizzes
Revises: 0082_teacher_visit_expiry
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083_classroom_quizzes"
down_revision: str | Sequence[str] | None = "0082_teacher_visit_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "classroom_quizzes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("document_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("content_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name="ck_classroom_quizzes_status",
        ),
    )
    op.create_index(
        "ix_classroom_quizzes_course_status",
        "classroom_quizzes",
        ["course_id", "status"],
    )
    op.create_index(
        "ix_classroom_quizzes_course_updated",
        "classroom_quizzes",
        ["course_id", "updated_at"],
    )

    op.create_table(
        "classroom_quiz_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "quiz_id",
            sa.String(36),
            sa.ForeignKey("classroom_quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("document_snapshot_json", sa.Text(), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("score_objective", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_max_objective", sa.Float(), nullable=False, server_default="0"),
        sa.Column("grading_status", sa.String(16), nullable=False, server_default="complete"),
        sa.Column("status", sa.String(16), nullable=False, server_default="submitted"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("teacher_hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "grading_status IN ('complete', 'pending', 'mixed')",
            name="ck_classroom_quiz_attempts_grading",
        ),
        sa.CheckConstraint(
            "status IN ('submitted')",
            name="ck_classroom_quiz_attempts_status",
        ),
        sa.UniqueConstraint(
            "quiz_id",
            "actor_user_id",
            name="ux_classroom_quiz_attempts_quiz_actor",
        ),
    )
    op.create_index(
        "ix_classroom_quiz_attempts_course_actor",
        "classroom_quiz_attempts",
        ["course_id", "actor_user_id"],
    )
    op.create_index(
        "ix_classroom_quiz_attempts_quiz",
        "classroom_quiz_attempts",
        ["quiz_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_classroom_quiz_attempts_quiz", table_name="classroom_quiz_attempts")
    op.drop_index(
        "ix_classroom_quiz_attempts_course_actor",
        table_name="classroom_quiz_attempts",
    )
    op.drop_table("classroom_quiz_attempts")
    op.drop_index("ix_classroom_quizzes_course_updated", table_name="classroom_quizzes")
    op.drop_index("ix_classroom_quizzes_course_status", table_name="classroom_quizzes")
    op.drop_table("classroom_quizzes")
