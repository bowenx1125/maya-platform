"""Remove Agents from workspaces while retaining private conversation history."""

import sqlalchemy as sa
from alembic import op

revision = "0031_agent_deletion"
down_revision = "0030_workspace_chat_live"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "deleted_at")
