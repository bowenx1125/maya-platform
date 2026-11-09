"""Keep a catalog student's explicitly selected group across startup."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086_student_group_choice"
down_revision: str | Sequence[str] | None = "0085_quiz_manual_grading"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "demo_account_bindings", sa.Column("selected_group_id", sa.String(36), nullable=True)
    )
    op.create_foreign_key(
        "fk_demo_accounts_selected_group",
        "demo_account_bindings",
        "groups",
        ["selected_group_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_demo_accounts_selected_group", "demo_account_bindings", type_="foreignkey"
    )
    op.drop_column("demo_account_bindings", "selected_group_id")
