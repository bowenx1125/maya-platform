"""Shared counter that rotates the voice preview sample lines.

Revision ID: 0067_voice_preview_counter
Revises: 0066_postgres_column_widths
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067_voice_preview_counter"
down_revision: str | Sequence[str] | None = "0066_postgres_column_widths"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "voice_preview_counters",
        sa.Column("key", sa.String(length=32), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    _begin()
    op.drop_table("voice_preview_counters")
