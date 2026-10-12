"""Let a teacher's personal Agent, which has no group, take part in a Debate."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0061_personal_agent_debaters"
down_revision: str | Sequence[str] | None = "0060_legacy_data_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _begin() -> set[tuple[object, ...]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("The Debate participant migration requires the SQLite database.")
    # Turns, sources and votes reference participants, so the rebuilt table
    # cannot be dropped with enforcement on. migrations/env.py restores it
    # after the enclosing transaction.
    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError("Cannot safely rebuild participants inside an existing transaction.")
    bind.exec_driver_sql("BEGIN IMMEDIATE")
    return {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}


def _rebuild(nullable: bool, initial: set[tuple[object, ...]]) -> None:
    bind = op.get_bind()
    try:
        with op.batch_alter_table("debate_participants", recreate="always") as batch:
            batch.alter_column("group_id", existing_type=sa.String(36), nullable=nullable)
        current = {tuple(row) for row in bind.exec_driver_sql("PRAGMA foreign_key_check")}
        if current - initial:
            raise RuntimeError("0061 introduced invalid Debate participant relationships.")
    except Exception:
        bind.exec_driver_sql("ROLLBACK")
        raise


def upgrade() -> None:
    # The group foreign keys stay: a NULL group simply leaves them unchecked,
    # while a group participant is still held to its own group and course.
    _rebuild(True, _begin())


def downgrade() -> None:
    initial = _begin()
    personal = op.get_bind().exec_driver_sql(
        "SELECT 1 FROM debate_participants WHERE group_id IS NULL LIMIT 1"
    )
    if personal.first() is not None:
        op.get_bind().exec_driver_sql("ROLLBACK")
        raise RuntimeError("Cannot downgrade while a Debate has a personal Agent participant")
    _rebuild(False, initial)
