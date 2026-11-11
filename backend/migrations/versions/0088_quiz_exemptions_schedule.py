"""Per-student extended time and one-shot Quiz taking schedules."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088_quiz_exemptions_schedule"
down_revision: str | Sequence[str] | None = "0087_account_author_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("start", "end"):
        op.add_column(
            "classroom_quizzes",
            sa.Column(f"scheduled_{name}_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            f"ix_classroom_quizzes_scheduled_{name}", "classroom_quizzes", [f"scheduled_{name}_at"]
        )
    op.create_table(
        "classroom_quiz_exemptions",
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
            "student_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("taking_epoch", sa.Integer(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "quiz_id",
            "student_user_id",
            "taking_epoch",
            name="ux_classroom_quiz_exemptions_quiz_student_epoch",
        ),
    )
    op.create_index("ix_classroom_quiz_exemptions_quiz", "classroom_quiz_exemptions", ["quiz_id"])


def downgrade() -> None:
    for name in ("end", "start"):
        op.drop_index(f"ix_classroom_quizzes_scheduled_{name}", table_name="classroom_quizzes")
        op.drop_column("classroom_quizzes", f"scheduled_{name}_at")
    op.drop_index("ix_classroom_quiz_exemptions_quiz", table_name="classroom_quiz_exemptions")
    op.drop_table("classroom_quiz_exemptions")
