"""Withdraw Chats without deleting their evidence or Provider history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_chat_withdrawal"
down_revision: str | Sequence[str] | None = "0045_assessment_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    op.add_column(
        "agent_conversations", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and not bind.connection.driver_connection.in_transaction:
        # SQLite DDL and Alembic's revision write must succeed or roll back together.
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    if (
        op.get_bind()
        .exec_driver_sql("SELECT 1 FROM agent_conversations WHERE withdrawn_at IS NOT NULL LIMIT 1")
        .first()
    ):
        raise RuntimeError("Cannot discard retained Chat withdrawal history.")
    op.drop_column("agent_conversations", "withdrawn_at")
