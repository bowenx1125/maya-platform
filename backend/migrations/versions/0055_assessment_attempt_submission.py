"""Record when a learner submits an unfinished Assessment attempt early."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055_assessment_attempt_submission"
down_revision: str | Sequence[str] | None = "0054_assessment_attempt_question_selection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.add_column(
        "assessment_attempts",
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("ALTER TABLE assessment_attempts DROP COLUMN submitted_at")
    else:
        op.drop_column("assessment_attempts", "submitted_at")
