"""Add the teacher-gated live playback waiting state.

The manual-advance delta is deliberately limited to ``playback_states``.  The
derived ``next_turn_ready`` value is a response/query concern and must not be
persisted.  SQLite cannot alter a CHECK constraint in place, so Alembic's
``recreate=\"always\"`` batch operation rebuilds this one table while copying
all existing rows and retaining its named foreign keys, unique constraint,
index, and existing checks.

Revision ID: 0005_wave2_manual_advance
Revises: 0004_wave2_debate_playback
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_wave2_manual_advance"
down_revision = "0004_wave2_debate_playback"
branch_labels = None
depends_on = None


_STATUS_CHECK = (
    "status IN ('preparing', 'ready', 'playing', 'paused', 'waiting_next', 'completed', 'stopped')"
)
_WAITING_NEXT_CHECK = (
    "status != 'waiting_next' OR "
    "(mode = 'live' AND current_turn_id IS NOT NULL "
    "AND replay_scope IS NULL AND replay_index IS NULL)"
)
_LEGACY_STATUS_CHECK = (
    "status IN ('preparing', 'ready', 'playing', 'paused', 'completed', 'stopped')"
)


def upgrade() -> None:
    with op.batch_alter_table("playback_states", recreate="always") as batch:
        batch.drop_constraint("ck_playback_states_status", type_="check")
        batch.create_check_constraint("ck_playback_states_status", _STATUS_CHECK)
        batch.create_check_constraint("ck_playback_states_waiting_next_live", _WAITING_NEXT_CHECK)


def downgrade() -> None:
    # ``waiting_next`` is a live-only command boundary introduced by 0005.
    # Before rebuilding the table with the 0004 status check, retain every
    # row and its current/replay/controller fields but move that boundary to
    # the conservative non-playing state.  This neither publishes audio nor
    # grants the next turn authority; a subsequent upgrade intentionally keeps
    # the row as ``paused`` because the waiting semantic is not reversible.
    op.execute(sa.text("UPDATE playback_states SET status='paused' WHERE status='waiting_next'"))
    with op.batch_alter_table("playback_states", recreate="always") as batch:
        batch.drop_constraint("ck_playback_states_waiting_next_live", type_="check")
        batch.drop_constraint("ck_playback_states_status", type_="check")
        batch.create_check_constraint("ck_playback_states_status", _LEGACY_STATUS_CHECK)
