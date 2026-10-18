"""Index formal attempts by activity for the teacher's Record list.

Revision ID: 0068_attempt_activity_index
Revises: 0067_voice_preview_counter
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068_attempt_activity_index"
down_revision: str | Sequence[str] | None = "0067_voice_preview_counter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_index(
        "ix_assessment_attempts_activity_started",
        "assessment_attempts",
        ["activity_id", "started_at"],
    )


def downgrade() -> None:
    _begin()
    op.drop_index("ix_assessment_attempts_activity_started", table_name="assessment_attempts")
