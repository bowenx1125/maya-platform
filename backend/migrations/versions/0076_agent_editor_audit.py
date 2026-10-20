"""Public Agents: record who last edited and who deleted.

Same-group students and the course teachers may now edit and delete a public
Agent, so a side table remembers the last editor (open-button tooltip
「最新编辑：…，Version：1.X」) and who soft-deleted it. New table only; no
existing row is touched.

Revision ID: 0076_agent_editor_audit
Revises: 0075_answer_guard_state
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_agent_editor_audit"
down_revision: str | Sequence[str] | None = "0075_answer_guard_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_edit_audit",
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("last_edited_by_user_id", sa.String(36), nullable=True),
        sa.Column("last_edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_edit_audit")
