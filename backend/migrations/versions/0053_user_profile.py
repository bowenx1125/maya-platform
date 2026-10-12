"""Add the user-selected scholar avatar."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_user_profile"
down_revision: str | Sequence[str] | None = "0052_teacher_courseware"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.add_column("users", sa.Column("avatar", sa.String(64), nullable=True))


def downgrade() -> None:
    _begin()
    if (
        op.get_bind()
        .exec_driver_sql("SELECT 1 FROM users WHERE avatar IS NOT NULL LIMIT 1")
        .first()
    ):
        raise RuntimeError("Cannot discard saved user avatars.")
    op.drop_column("users", "avatar")
