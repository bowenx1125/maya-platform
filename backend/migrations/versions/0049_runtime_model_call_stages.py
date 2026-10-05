"""Preserve exact Single SDK request and accepted envelopes for Tool recovery."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_runtime_model_call_stages"
down_revision: str | Sequence[str] | None = "0048_runtime_tool_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.create_table(
        "runtime_model_call_stages",
        sa.Column(
            "operation_id",
            sa.String(36),
            sa.ForeignKey("provider_operations.id", ondelete="RESTRICT"),
            primary_key=True,
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
            "executor_agent_version_id",
            sa.String(36),
            sa.ForeignKey("agent_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("dispatch_ordinal", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("accepted_response_json", sa.Text(), nullable=True),
        sa.Column("accepted_response_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "turn_id", "executor_agent_version_id", "ordinal", name="uq_runtime_model_stage_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_runtime_model_stage_ordinal"),
        sa.CheckConstraint("dispatch_ordinal >= 0", name="ck_runtime_model_stage_dispatch_ordinal"),
        sa.CheckConstraint("length(request_hash)=64", name="ck_runtime_model_stage_request_hash"),
        sa.CheckConstraint(
            "(accepted_response_json IS NULL AND accepted_response_hash IS NULL "
            "AND accepted_at IS NULL) OR "
            "(accepted_response_json IS NOT NULL AND accepted_response_hash IS NOT NULL "
            "AND length(accepted_response_hash)=64 AND accepted_at IS NOT NULL)",
            name="ck_runtime_model_stage_accepted_pair",
        ),
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER runtime_model_stage_request_immutable
            BEFORE UPDATE ON runtime_model_call_stages
            WHEN NEW.operation_id IS NOT OLD.operation_id
              OR NEW.conversation_id IS NOT OLD.conversation_id
              OR NEW.turn_id IS NOT OLD.turn_id
              OR NEW.executor_agent_version_id IS NOT OLD.executor_agent_version_id
              OR NEW.ordinal IS NOT OLD.ordinal
              OR NEW.dispatch_ordinal IS NOT OLD.dispatch_ordinal
              OR NEW.request_hash IS NOT OLD.request_hash
              OR NEW.request_json IS NOT OLD.request_json
              OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'runtime_model_request_immutable'); END""")
        op.execute("""CREATE TRIGGER runtime_model_stage_accepted_immutable
            BEFORE UPDATE ON runtime_model_call_stages
            WHEN OLD.accepted_response_json IS NOT NULL
              AND (NEW.accepted_response_json IS NOT OLD.accepted_response_json
                OR NEW.accepted_response_hash IS NOT OLD.accepted_response_hash
                OR NEW.accepted_at IS NOT OLD.accepted_at)
            BEGIN SELECT RAISE(ABORT, 'runtime_model_accepted_immutable'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if op.get_bind().exec_driver_sql("SELECT 1 FROM runtime_model_call_stages LIMIT 1").first():
        raise RuntimeError("Cannot discard accepted-call or dispatch evidence.")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER runtime_model_stage_accepted_immutable")
        op.execute("DROP TRIGGER runtime_model_stage_request_immutable")
    op.drop_table("runtime_model_call_stages")
