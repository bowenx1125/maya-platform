"""Hide quiz grading results from students by default.

Revision ID: 0090_quiz_hide_results
Revises: 0089_debate_cards
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0090_quiz_hide_results"
down_revision: str | Sequence[str] | None = "0089_debate_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classroom_quizzes",
        sa.Column(
            "hide_results_from_students",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("classroom_quizzes", "hide_results_from_students")
