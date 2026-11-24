"""Per-account optional learning-data research consent.

Stores only the authenticated choice from login. Missing row means not
consented. No research-export gate is wired in this revision.
"""

import sqlalchemy as sa
from alembic import op

revision = "0096_learning_research_consent"
down_revision = "0095_llm_stage_attempt_cap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_learning_research_consents",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("consented", sa.Boolean(), nullable=False),
        sa.Column("consent_copy_version", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_learning_research_consents_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_learning_research_consents")
