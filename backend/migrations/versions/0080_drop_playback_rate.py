"""Drop the browser playback rate: speech speed is the TTS rate now.

Every Debate plays at 1.0; the speaking rate is frozen per Debate as
``voice_params.rate`` and sent to the cloned-voice TTS. Old rows need no
conversion: they simply play at 1.0.

Revision ID: 0080_drop_playback_rate
Revises: 0079_playback_media_tickets
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080_drop_playback_rate"
down_revision: str | Sequence[str] | None = "0079_playback_media_tickets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE playback_states DROP CONSTRAINT IF EXISTS ck_playback_states_rate")
    op.drop_column("playback_states", "playback_rate")


def downgrade() -> None:
    op.add_column(
        "playback_states",
        sa.Column("playback_rate", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.create_check_constraint(
        "ck_playback_states_rate",
        "playback_states",
        "playback_rate >= 0.95 AND playback_rate <= 1.25",
    )
