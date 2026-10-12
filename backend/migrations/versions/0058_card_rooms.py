"""Add online card rooms, joined by a four-digit code.

A room's table state, deck included, is stored as JSON and only ever sent to
players as a per-player view. Play chips only; nothing is kept per account.

Revision ID: 0058_card_rooms
Revises: 0057_agent_account_memory
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058_card_rooms"
down_revision: str | Sequence[str] | None = "0057_agent_account_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "card_rooms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(4), nullable=False),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "host_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(code) = 4 AND code GLOB '[0-9][0-9][0-9][0-9]'",
            name="ck_card_rooms_code",
        ),
    )
    op.create_index(
        "ux_card_rooms_open_code",
        "card_rooms",
        ["code"],
        unique=True,
        sqlite_where=sa.text("closed_at IS NULL"),
    )
    op.create_index("ix_card_rooms_course_id", "card_rooms", ["course_id"])


def downgrade() -> None:
    _begin()
    op.drop_index("ix_card_rooms_course_id", table_name="card_rooms")
    op.drop_index("ux_card_rooms_open_code", table_name="card_rooms")
    op.drop_table("card_rooms")
