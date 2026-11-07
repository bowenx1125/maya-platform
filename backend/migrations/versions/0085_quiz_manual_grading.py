"""Teacher grading of a quiz attempt's text items.

Text answers were stored with no score and stayed pending forever. A teacher
now grades them by hand (no model call); the grades live on the attempt next
to the frozen paper they were given against, and score_objective keeps
meaning the automatic part only.

Revision ID: 0085_quiz_manual_grading
Revises: 0084_quiz_taking_open_retest
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0085_quiz_manual_grading"
down_revision: str | Sequence[str] | None = "0084_quiz_taking_open_retest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classroom_quiz_attempts",
        sa.Column("manual_grades_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "classroom_quiz_attempts",
        sa.Column("score_manual", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "classroom_quiz_attempts",
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classroom_quiz_attempts", "graded_at")
    op.drop_column("classroom_quiz_attempts", "score_manual")
    op.drop_column("classroom_quiz_attempts", "manual_grades_json")
