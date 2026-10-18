"""HTML reports a Team member saves for the Chat owner.

Revision ID: 0071_chat_reports
Revises: 0070_conversation_attachments
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0071_chat_reports"
down_revision: str | Sequence[str] | None = "0070_conversation_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "chat_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_event_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_chat_reports_conversation", "chat_reports", ["conversation_id", "created_at"]
    )


def downgrade() -> None:
    _begin()
    op.drop_index("ix_chat_reports_conversation", table_name="chat_reports")
    op.drop_table("chat_reports")
