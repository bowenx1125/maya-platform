"""Persist optional teacher context without changing the displayed topic."""

import sqlalchemy as sa
from alembic import op

revision = "0026_debate_background"
down_revision = "0025_report_prompt_only_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("debates", sa.Column("background", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.execute("ALTER TABLE debates DROP COLUMN background")
