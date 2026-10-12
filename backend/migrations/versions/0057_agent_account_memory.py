"""Store one account's Agent notes apart from assessment records.

Debate generation does not read this table. A note is readable only by the
account that wrote it, for that Agent.

Revision ID: 0057_agent_account_memory
Revises: 0056_preset_voice_profiles
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057_agent_account_memory"
down_revision: str | Sequence[str] | None = "0056_preset_voice_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "agent_account_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(body) >= 1 AND length(body) <= 2000",
            name="ck_agent_account_memory_body",
        ),
    )
    op.create_index(
        "ix_agent_account_memory_owner_agent",
        "agent_account_memories",
        ["owner_user_id", "agent_id"],
    )


def downgrade() -> None:
    _begin()
    op.drop_index("ix_agent_account_memory_owner_agent", table_name="agent_account_memories")
    op.drop_table("agent_account_memories")
