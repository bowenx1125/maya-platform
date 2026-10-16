"""Shared login admission queue.

Revision ID: 0065_auth_login_admission
Revises: 0064_active_debate_slot
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_auth_login_admission"
down_revision: str | Sequence[str] | None = "0064_active_debate_slot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "auth_login_admissions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('waiting', 'admitted')",
            name="ck_auth_login_admissions_state",
        ),
    )
    op.create_index(
        "ix_auth_login_admissions_state_expires",
        "auth_login_admissions",
        ["state", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    _begin()
    op.drop_index(
        "ix_auth_login_admissions_state_expires",
        table_name="auth_login_admissions",
    )
    op.drop_table("auth_login_admissions")
