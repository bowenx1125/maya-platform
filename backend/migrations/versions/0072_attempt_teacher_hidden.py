"""Teacher soft delete of an assessment attempt in Record.

Revision ID: 0072_attempt_teacher_hidden
Revises: 0071_chat_reports
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072_attempt_teacher_hidden"
down_revision: str | Sequence[str] | None = "0071_chat_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    bind = op.get_bind()
    # Two nullable columns with no CHECK, so SQLite can drop them again.
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE assessment_attempts ADD COLUMN teacher_hidden_at DATETIME"
        )
        bind.exec_driver_sql(
            "ALTER TABLE assessment_attempts ADD COLUMN teacher_hidden_by_user_id VARCHAR(36)"
        )
        return
    op.add_column(
        "assessment_attempts",
        sa.Column("teacher_hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "assessment_attempts",
        sa.Column("teacher_hidden_by_user_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            "ALTER TABLE assessment_attempts DROP COLUMN teacher_hidden_by_user_id"
        )
        bind.exec_driver_sql("ALTER TABLE assessment_attempts DROP COLUMN teacher_hidden_at")
        return
    op.drop_column("assessment_attempts", "teacher_hidden_by_user_id")
    op.drop_column("assessment_attempts", "teacher_hidden_at")
