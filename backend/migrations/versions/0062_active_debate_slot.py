"""Archived Debates keep their history without occupying the live course slot."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062_active_debate_slot"
down_revision: str | Sequence[str] | None = "0061_personal_agent_debaters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.drop_index("uq_debates_one_running_per_course", table_name="debates")
    op.create_index(
        "uq_debates_one_running_per_course",
        "debates",
        ["course_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    _begin()
    # Restoring the old constraint may conflict with retained archived rows.
    # Reject before changing the index rather than rewriting classroom history.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM debates WHERE status='running' "
                "GROUP BY course_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
        is not None
    ):
        raise RuntimeError("Cannot restore the old slot while archived running Debates coexist")
    op.drop_index("uq_debates_one_running_per_course", table_name="debates")
    op.create_index(
        "uq_debates_one_running_per_course",
        "debates",
        ["course_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )
