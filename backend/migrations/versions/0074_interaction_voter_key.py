"""Debate audience: a per-person key on votes and barrages.

Load plan 2026-10-19: anonymous votes and barrages were deduplicated only by
the client's own submission id, so one browser could vote again and again and
flood barrages. ``voter_key`` is a server-side hash of the classroom window
and the browser's audience id (or address and user agent). One vote per
window per person is a partial unique index, so it holds across backends; the
barrage cooldown reads the person's latest barrage. Existing rows keep NULL
(no key, no limit). Nothing is rewritten.

Revision ID: 0074_interaction_voter_key
Revises: 0073_voice_ready_on_upload
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074_interaction_voter_key"
down_revision: str | Sequence[str] | None = "0073_voice_ready_on_upload"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("votes") as batch:
        batch.add_column(sa.Column("voter_key", sa.String(64), nullable=True))
    with op.batch_alter_table("barrage_messages") as batch:
        batch.add_column(sa.Column("voter_key", sa.String(64), nullable=True))
    op.create_index(
        "uq_votes_window_voter",
        "votes",
        ["window_id", "voter_key"],
        unique=True,
        sqlite_where=sa.text("voter_key IS NOT NULL"),
        postgresql_where=sa.text("voter_key IS NOT NULL"),
    )
    op.create_index(
        "ix_barrage_messages_window_voter",
        "barrage_messages",
        ["window_id", "voter_key", "submitted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_barrage_messages_window_voter", table_name="barrage_messages")
    op.drop_index("uq_votes_window_voter", table_name="votes")
    # A plain DROP COLUMN (PostgreSQL; SQLite >= 3.35): a batch table rebuild
    # trips the foreign keys that point at barrage_messages on SQLite.
    op.execute("ALTER TABLE barrage_messages DROP COLUMN voter_key")
    op.execute("ALTER TABLE votes DROP COLUMN voter_key")
