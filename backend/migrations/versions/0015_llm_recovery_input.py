"""Persist the canonical LLM input needed for zero-network recovery.

The accepted LLM stage created by 0014 intentionally stores sanitized output
and usage facts only.  This additive migration stores the exact canonical
input JSON beside that stage so local validation/publication can resume after
restart without another provider request.  Existing 0014 rows are left
untouched; there is no safe input to backfill for them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_llm_recovery_input"
down_revision: str | Sequence[str] | None = "0014_llm_runtime_budget_buckets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "llm_recovery_inputs"
_TRIGGERS = (
    "trg_llm_recovery_inputs_immutable_update",
    "trg_llm_recovery_inputs_immutable_delete",
)


def _create_immutable_triggers() -> None:
    """Prevent SQL callers from changing or deleting a recovery input row."""

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_llm_recovery_inputs_immutable_update "
            "BEFORE UPDATE ON llm_recovery_inputs "
            "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_llm_recovery_inputs_immutable_delete "
            "BEFORE DELETE ON llm_recovery_inputs "
            "BEGIN SELECT RAISE(ABORT, 'llm recovery input is immutable'); END"
        )
    )


def _drop_immutable_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    for trigger in _TRIGGERS:
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("input_version", sa.String(length=80), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["provider_operations.id"],
            name="fk_llm_recovery_inputs_operation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["debate_turns.id"],
            name="fk_llm_recovery_inputs_turn",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint(
            "turn_id",
            "attempt_no",
            name="uq_llm_recovery_inputs_turn_attempt",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1 AND attempt_no <= 2",
            name="ck_llm_recovery_inputs_attempt",
        ),
        sa.CheckConstraint(
            "input_version = 'llm_recovery_input_v1'",
            name="ck_llm_recovery_inputs_version",
        ),
        sa.CheckConstraint(
            "length(CAST(input_json AS BLOB)) > 0 AND length(CAST(input_json AS BLOB)) <= 262144",
            name="ck_llm_recovery_inputs_size",
        ),
        sa.CheckConstraint(
            "length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_llm_recovery_inputs_hash",
        ),
    )
    op.create_index(
        "ix_llm_recovery_inputs_turn",
        _TABLE,
        ["turn_id", "attempt_no"],
        unique=False,
    )
    _create_immutable_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT 1 FROM {_TABLE} LIMIT 1")).first() is not None:
        raise RuntimeError("Cannot downgrade 0015 while LLM recovery inputs are retained.")
    _drop_immutable_triggers()
    op.drop_index("ix_llm_recovery_inputs_turn", table_name=_TABLE)
    op.drop_table(_TABLE)
