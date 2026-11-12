"""Keep existing Quiz results visible; hide results for new quizzes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0091_quiz_show_results"
down_revision: str | Sequence[str] | None = "0090_bowen_identity_choice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classroom_quizzes",
        sa.Column("show_results", sa.Boolean(), nullable=True, server_default=sa.true()),
    )
    op.alter_column("classroom_quizzes", "show_results", server_default=sa.false(), nullable=False)


def downgrade() -> None:
    op.drop_column("classroom_quizzes", "show_results")
