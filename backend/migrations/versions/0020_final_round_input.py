"""Bind classroom messages to turns and freeze the live final-round input."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_final_round_input"
down_revision: str | Sequence[str] | None = "0019_debate_output_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("debates", sa.Column("final_input_json", sa.Text(), nullable=True))
    op.add_column("debates", sa.Column("final_input_hash", sa.String(64), nullable=True))
    op.add_column(
        "debates", sa.Column("final_frozen_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Inline REFERENCES preserves existing SQLite tables and their triggers.
    op.execute(
        "ALTER TABLE barrage_messages ADD COLUMN turn_id VARCHAR(36) "
        "REFERENCES debate_turns(id) ON DELETE RESTRICT"
    )
    for action in ("INSERT", "UPDATE"):
        op.execute(
            f"CREATE TRIGGER barrage_turn_scope_{action.lower()} BEFORE {action} "
            "ON barrage_messages WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM debate_turns WHERE id=NEW.turn_id AND debate_id=NEW.debate_id) "
            "BEGIN SELECT RAISE(ABORT, 'barrage_turn_scope'); END"
        )
    op.execute(
        "CREATE TRIGGER debate_final_input_immutable BEFORE UPDATE ON debates "
        "WHEN OLD.final_input_json IS NOT NULL AND "
        "(NEW.final_input_json IS NOT OLD.final_input_json OR "
        "NEW.final_input_hash IS NOT OLD.final_input_hash OR "
        "NEW.final_frozen_at IS NOT OLD.final_frozen_at) "
        "BEGIN SELECT RAISE(ABORT, 'final_input_immutable'); END"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM debates WHERE final_input_json IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM barrage_messages WHERE turn_id IS NOT NULL)"
        )
    ).scalar():
        raise RuntimeError("Cannot discard retained final-round inputs or turn-bound messages.")
    for name in (
        "barrage_turn_scope_insert",
        "barrage_turn_scope_update",
        "debate_final_input_immutable",
    ):
        op.execute(f"DROP TRIGGER {name}")
    op.drop_column("barrage_messages", "turn_id")
    for name in ("final_frozen_at", "final_input_hash", "final_input_json"):
        op.drop_column("debates", name)
