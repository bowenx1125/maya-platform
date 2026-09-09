"""Add the writable credential source used by student self-registration.

The seven fixed Demo identities keep resolving through the read-only
``accounts.private.md`` catalog.  This additive migration introduces the
second credential source so a student can create an account without a
teacher pre-provisioning it.  No existing row is modified: an account that
predates this table simply has no ``user_credentials`` row and continues to
authenticate through the catalog.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_student_self_registration"
down_revision: str | Sequence[str] | None = "0027_frozen_teaching_markdown"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "user_credentials"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_credentials_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_credentials"),
    )
    op.create_index("ix_user_credentials_username", _TABLE, ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_credentials_username", table_name=_TABLE)
    op.drop_table(_TABLE)
