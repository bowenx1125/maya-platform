"""Add the debate card columns to Debate participants.

Every existing row keeps a null card status: a Debate created before cards
never compiles one and keeps sending its original AGENT.md. No row is
rewritten.

Revision ID: 0088_debate_cards
Revises: 0087_account_author_links
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0088_debate_cards"
down_revision: str | Sequence[str] | None = "0087_account_author_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CARD_STATUS_CHECK = "card_status IS NULL OR card_status IN ('compiling', 'ready', 'fallback')"
CARD_JSON_CHECK = (
    "(card_status = 'ready' AND card_json IS NOT NULL) OR "
    "(card_status IS DISTINCT FROM 'ready' AND card_json IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "debate_participants", sa.Column("card_status", sa.String(length=16), nullable=True)
    )
    op.add_column("debate_participants", sa.Column("card_json", sa.Text(), nullable=True))
    op.add_column(
        "debate_participants",
        sa.Column("card_safe_error_code", sa.String(length=80), nullable=True),
    )
    op.create_check_constraint(
        "ck_debate_participants_card_status", "debate_participants", CARD_STATUS_CHECK
    )
    op.create_check_constraint(
        "ck_debate_participants_card_json", "debate_participants", CARD_JSON_CHECK
    )


def downgrade() -> None:
    op.drop_constraint("ck_debate_participants_card_json", "debate_participants", type_="check")
    op.drop_constraint("ck_debate_participants_card_status", "debate_participants", type_="check")
    op.drop_column("debate_participants", "card_safe_error_code")
    op.drop_column("debate_participants", "card_json")
    op.drop_column("debate_participants", "card_status")
