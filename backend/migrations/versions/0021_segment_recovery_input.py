"""Allow the explicit segments_v2 recovery envelope beside legacy input."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_segment_recovery_input"
down_revision: str | Sequence[str] | None = "0020_final_round_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_recovery_inputs"
_UPDATE_TRIGGER = "trg_llm_recovery_inputs_immutable_update"
_DELETE_TRIGGER = "trg_llm_recovery_inputs_immutable_delete"


def _drop_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_UPDATE_TRIGGER}"))
    op.execute(sa.text(f"DROP TRIGGER IF EXISTS {_DELETE_TRIGGER}"))


def _create_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        sa.text(
            f"CREATE TRIGGER {_UPDATE_TRIGGER} BEFORE UPDATE ON {_TABLE} "
            "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
        )
    )
    op.execute(
        sa.text(
            f"CREATE TRIGGER {_DELETE_TRIGGER} BEFORE DELETE ON {_TABLE} "
            "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
        )
    )


def upgrade() -> None:
    _drop_triggers()
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.drop_constraint("ck_llm_recovery_inputs_version", type_="check")
        batch.create_check_constraint(
            "ck_llm_recovery_inputs_version",
            "input_version IN ('llm_recovery_input_v1', 'segment_recovery_input_v2')",
        )
    _create_triggers()


def downgrade() -> None:
    connection = op.get_bind()
    if (
        connection.execute(
            sa.text(
                "SELECT 1 FROM llm_recovery_inputs "
                "WHERE input_version='segment_recovery_input_v2' LIMIT 1"
            )
        ).first()
        is not None
    ):
        raise RuntimeError("Cannot downgrade while segments_v2 recovery inputs are retained.")
    _drop_triggers()
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.drop_constraint("ck_llm_recovery_inputs_version", type_="check")
        batch.create_check_constraint(
            "ck_llm_recovery_inputs_version",
            "input_version = 'llm_recovery_input_v1'",
        )
    _create_triggers()
