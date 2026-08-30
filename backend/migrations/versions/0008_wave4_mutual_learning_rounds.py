"""wave4_mutual_learning_rounds

Revision ID: 0008_wave4_mutual_learning_rounds
Revises: 0007_wave3_interaction_report
Authorized for W4-MUTUAL-LEARNING-RULESET: 2026-08-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_wave4_mutual_learning_rounds"
down_revision: str | Sequence[str] | None = "0007_wave3_interaction_report"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POSITIVE_ROUND_CHECK = "round_no >= 1"
_LEGACY_ROUND_CHECK = "round_no >= 1 AND round_no <= 2"


def _replace_round_check(expression: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        with op.batch_alter_table("debate_turns") as batch:
            batch.drop_constraint("ck_debate_turns_round", type_="check")
            batch.create_check_constraint("ck_debate_turns_round", expression)
        return

    # SQLite cannot drop a parent table while foreign-key enforcement is on.
    # Leave Alembic's outer transaction, disable enforcement before starting a
    # new explicit transaction, rebuild atomically, validate the complete graph,
    # then restore enforcement before returning.
    with op.get_context().autocommit_block():
        sqlite = op.get_bind()
        sqlite.exec_driver_sql("PRAGMA foreign_keys=OFF")
        sqlite.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            with op.batch_alter_table("debate_turns", recreate="always") as batch:
                batch.drop_constraint("ck_debate_turns_round", type_="check")
                batch.create_check_constraint("ck_debate_turns_round", expression)
            violations = sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"0008 left foreign-key violations: {violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            enabled = sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one()
            if enabled != 1:
                raise RuntimeError("0008 failed to restore SQLite foreign-key enforcement")


def upgrade() -> None:
    """Allow positive protocol rounds without changing any persisted row."""

    _replace_round_check(_POSITIVE_ROUND_CHECK)


def downgrade() -> None:
    """Restore the legacy bound only when doing so is lossless."""

    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM debate_turns WHERE round_no > 2 LIMIT 1")).first():
        raise RuntimeError(
            "Cannot downgrade 0008 while debate_turns contains rounds greater than two."
        )
    _replace_round_check(_LEGACY_ROUND_CHECK)
