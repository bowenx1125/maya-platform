"""Store the latest derived debate card per Agent."""

import sqlalchemy as sa
from alembic import op

revision = "0094_agent_debate_cards"
down_revision = "0093_default_group_no_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_debate_cards",
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "agent_version_id",
            sa.String(36),
            sa.ForeignKey("agent_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_md_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("card_status", sa.String(16), nullable=False),
        sa.Column("card_json", sa.Text(), nullable=True),
        sa.Column("card_safe_error_code", sa.String(80), nullable=True),
        sa.Column("salvaged", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compiled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "card_status IN ('compiling', 'ready', 'fallback')", name="ck_agent_card_status"
        ),
        sa.CheckConstraint("language IN ('zh', 'en')", name="ck_agent_card_language"),
        sa.CheckConstraint("NOT salvaged OR card_status = 'ready'", name="ck_agent_card_salvaged"),
    )


def downgrade() -> None:
    op.drop_table("agent_debate_cards")
