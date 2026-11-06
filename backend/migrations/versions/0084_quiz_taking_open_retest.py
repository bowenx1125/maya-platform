"""Separate quiz publishing from taking (retest epochs).

Publish now only freezes the paper. Taking opens through start-taking, so
attempts must be unique per (quiz, actor, taking_epoch) instead of per
(quiz, actor). Existing attempts keep epoch 0 and stay unique per actor.

Revision ID: 0084_quiz_taking_open_retest
Revises: 0083_classroom_quizzes
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084_quiz_taking_open_retest"
down_revision: str | Sequence[str] | None = "0083_classroom_quizzes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classroom_quizzes",
        sa.Column(
            "taking_open",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "classroom_quizzes",
        sa.Column("taking_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "classroom_quiz_attempts",
        sa.Column("taking_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint(
        "ux_classroom_quiz_attempts_quiz_actor",
        "classroom_quiz_attempts",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_classroom_quiz_attempts_quiz_actor_epoch",
        "classroom_quiz_attempts",
        ["quiz_id", "actor_user_id", "taking_epoch"],
    )


def downgrade() -> None:
    # Per-actor uniqueness can only be restored when no retest rows exist.
    op.drop_constraint(
        "ux_classroom_quiz_attempts_quiz_actor_epoch",
        "classroom_quiz_attempts",
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_classroom_quiz_attempts_quiz_actor",
        "classroom_quiz_attempts",
        ["quiz_id", "actor_user_id"],
    )
    op.drop_column("classroom_quiz_attempts", "taking_epoch")
    op.drop_column("classroom_quizzes", "taking_epoch")
    op.drop_column("classroom_quizzes", "taking_open")
