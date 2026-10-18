"""Files a Chat owner attaches to one conversation.

Revision ID: 0070_conversation_attachments
Revises: 0069_barrage_sequence
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070_conversation_attachments"
down_revision: str | Sequence[str] | None = "0069_barrage_sequence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        bind.exec_driver_sql("BEGIN IMMEDIATE")


def upgrade() -> None:
    _begin()
    op.create_table(
        "conversation_attachments",
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
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False, unique=True),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes >= 0 AND text_chars >= 0", name="ck_conversation_attachment_sizes"
        ),
    )
    op.create_index(
        "ix_conversation_attachments_conversation",
        "conversation_attachments",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    _begin()
    op.drop_index("ix_conversation_attachments_conversation", table_name="conversation_attachments")
    op.drop_table("conversation_attachments")
