"""Keep each formal attempt's student name beside its account id."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063_attempt_actor_name"
down_revision: str | Sequence[str] | None = "0062_teacher_personal_voices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    # Owner request (2026-10-13): the database shows who answered, not only an
    # account id. The name is the one the student had when the attempt began.
    op.add_column(
        "assessment_attempts",
        sa.Column("actor_display_name", sa.String(length=200), nullable=True),
    )
    op.execute(
        "UPDATE assessment_attempts SET actor_display_name = "
        "(SELECT users.display_name FROM users WHERE users.id = assessment_attempts.actor_user_id)"
    )


def downgrade() -> None:
    _begin()
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("ALTER TABLE assessment_attempts DROP COLUMN actor_display_name")
    else:
        op.drop_column("assessment_attempts", "actor_display_name")
