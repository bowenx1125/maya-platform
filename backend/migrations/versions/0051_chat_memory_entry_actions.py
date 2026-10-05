"""Persist idempotent Brainform Memory navigation intents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_chat_memory_entry_actions"
down_revision: str | Sequence[str] | None = "0050_chat_provider_standing_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NORMAL_MESSAGE = "你目前记得我们之前聊过什么？"
_ASSESSMENT_MESSAGE = (
    "请列出本测评回合中我已经提交的作答记录和当前进度，不要提供答案、评分依据或提示。"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "chat_memory_entry_actions",
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("action_id", sa.String(36), primary_key=True),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("agent_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False, unique=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('conversation','agent','team','maya_team')",
            name="ck_chat_memory_action_source_kind",
        ),
        sa.CheckConstraint(
            "message IN ('" + _NORMAL_MESSAGE + "','" + _ASSESSMENT_MESSAGE + "')",
            name="ck_chat_memory_action_message",
        ),
    )
    op.create_index(
        "ix_chat_memory_action_conversation",
        "chat_memory_entry_actions",
        ["conversation_id"],
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            """CREATE TRIGGER chat_memory_entry_action_immutable
            BEFORE UPDATE ON chat_memory_entry_actions
            BEGIN SELECT RAISE(ABORT, 'chat_memory_action_immutable'); END"""
        )
        op.execute(
            """CREATE TRIGGER chat_memory_entry_action_no_delete
            BEFORE DELETE ON chat_memory_entry_actions
            BEGIN SELECT RAISE(ABORT, 'chat_memory_action_immutable'); END"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if bind.exec_driver_sql("SELECT 1 FROM chat_memory_entry_actions LIMIT 1").first():
        raise RuntimeError("Cannot discard durable Brainform Memory action identities.")
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER chat_memory_entry_action_no_delete")
        op.execute("DROP TRIGGER chat_memory_entry_action_immutable")
    op.drop_index("ix_chat_memory_action_conversation", table_name="chat_memory_entry_actions")
    op.drop_table("chat_memory_entry_actions")
