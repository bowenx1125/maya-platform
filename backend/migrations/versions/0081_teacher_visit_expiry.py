"""Add an expiry to a teacher's temporary group visit.

Existing visits are kept and given a window measured from when they were
created, matching ``TEACHER_GROUP_VISIT_TTL`` (2 hours). Downgrade drops only
the new column and its index.

Revision ID: 0081_teacher_visit_expiry
Revises: 0080_drop_playback_rate
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081_teacher_visit_expiry"
down_revision: str | Sequence[str] | None = "0080_drop_playback_rate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "teacher_group_access",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Keep every existing visit. A row older than the window simply expires
    # on the next read and is removed by the sweep, rather than being deleted
    # inside the migration.
    op.execute(
        "UPDATE teacher_group_access "
        "SET expires_at = created_at + interval '2 hours' "
        "WHERE expires_at IS NULL"
    )
    op.alter_column("teacher_group_access", "expires_at", nullable=False)
    op.create_index(
        "ix_teacher_group_access_expires_at",
        "teacher_group_access",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_teacher_group_access_expires_at", table_name="teacher_group_access")
    op.drop_column("teacher_group_access", "expires_at")
