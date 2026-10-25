"""Store playback media tickets by hash so every backend replica honors them.

Revision ID: 0079_playback_media_tickets
Revises: 0078_chat_answer_decouple
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079_playback_media_tickets"
down_revision: str | Sequence[str] | None = "0078_chat_answer_decouple"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "playback_media_tickets",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_hash", sa.String(128), nullable=False),
        sa.Column("controller_epoch", sa.String(36), nullable=False),
        sa.Column("debate_id", sa.String(36), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("control_version", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_playback_media_tickets_item", "playback_media_tickets", ["debate_id", "turn_id"]
    )
    op.create_index(
        "ix_playback_media_tickets_epoch", "playback_media_tickets", ["controller_epoch"]
    )
    op.create_index("ix_playback_media_tickets_expires", "playback_media_tickets", ["expires_at"])


def downgrade() -> None:
    # Tickets live for minutes; dropping them only makes open tabs ask again.
    op.drop_table("playback_media_tickets")
