"""Retain transactional Tool receipts tied to actual accepted Provider operations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_runtime_tool_receipts"
down_revision: str | Sequence[str] | None = "0047_brainform_markdown"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "runtime_tool_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("agent_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "turn_id",
            sa.String(36),
            sa.ForeignKey("agent_conversation_turns.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "model_operation_id",
            sa.String(36),
            sa.ForeignKey("provider_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tool_call_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "model_operation_id", "tool_call_id", name="uq_runtime_tool_call_receipt"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if op.get_bind().exec_driver_sql("SELECT 1 FROM runtime_tool_receipts LIMIT 1").first():
        raise RuntimeError("Cannot discard retained Tool effects and accepted-call receipts.")
    op.drop_table("runtime_tool_receipts")
