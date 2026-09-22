"""Private conversation history, local provider preferences and Live leases."""

import sqlalchemy as sa
from alembic import op

revision = "0030_workspace_chat_live"
down_revision = "0029_account_keys_teacher_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_version_id",
            sa.String(36),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("active_request_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0"),
    )
    op.create_index("ix_agent_conversations_user_id", "agent_conversations", ["user_id"])
    op.create_table(
        "agent_conversation_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("user_text", sa.Text, nullable=False),
        sa.Column("assistant_text", sa.Text, nullable=True),
        sa.Column("sources_json", sa.Text, nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('real', 'mock')"),
        sa.CheckConstraint("state IN ('pending', 'ready', 'failed', 'acceptance_unknown')"),
    )
    op.create_index(
        "ix_agent_conversation_turns_conversation_id",
        "agent_conversation_turns",
        ["conversation_id"],
    )
    op.create_table(
        "provider_preferences",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("modes_json", sa.Text, nullable=False),
        sa.Column("encrypted_key", sa.Text, nullable=True),
        sa.Column("checks_json", sa.Text, nullable=False),
        sa.CheckConstraint("id = 1 AND revision >= 0"),
    )
    op.create_table(
        "classroom_live_presence",
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "debate_id",
            sa.String(36),
            sa.ForeignKey("debates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("classroom_live_presence")
    op.drop_table("provider_preferences")
    op.drop_table("agent_conversation_turns")
    op.drop_table("agent_conversations")
