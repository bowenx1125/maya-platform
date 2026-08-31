"""Add the bounded Real-Core Demo acceptance-run ledger.

The run row records only opaque local identities, the frozen fixture hash and
safe counters.  Existing ProviderOperation rows remain legacy rows with NULL
run/call bindings; no historical operation can be inferred into a new Demo
run.  The additive provider-operation columns are nullable for that reason.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_real_core_acceptance_run"
down_revision: str | Sequence[str] | None = "0015_llm_recovery_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUN_TABLE = "demo_acceptance_runs"
_OPERATION_TABLE = "provider_operations"


def _rebuild_provider_operations(operation: Callable[[], None]) -> None:
    """Rebuild the ProviderOperation parent without cascading its children."""

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        operation()
        return
    with op.get_context().autocommit_block():
        sqlite = op.get_bind()
        sqlite.exec_driver_sql("PRAGMA foreign_keys=OFF")
        sqlite.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            existing_violations = {
                tuple(row) for row in sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            }
            operation()
            violations = {
                tuple(row) for row in sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            }
            new_violations = violations - existing_violations
            if new_violations:
                raise RuntimeError(f"0016 left new foreign-key violations: {new_violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0016 failed to restore SQLite foreign-key enforcement")


def _create_run_table() -> None:
    op.create_table(
        _RUN_TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_version", sa.String(length=80), nullable=False),
        sa.Column("fixture_hash", sa.String(length=64), nullable=False),
        sa.Column("baseline_agent_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_version_id", sa.String(length=36), nullable=False),
        sa.Column("baseline_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("target_agent_id", sa.String(length=36), nullable=False),
        sa.Column("target_version_id", sa.String(length=36), nullable=False),
        sa.Column("debate_id", sa.String(length=36), nullable=True),
        sa.Column("report_revision_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="prepared"),
        sa.Column(
            "starting_charged_requests",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["baseline_agent_id"],
            ["agents.id"],
            name="fk_demo_acceptance_runs_baseline_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_version_id"],
            ["agent_versions.id"],
            name="fk_demo_acceptance_runs_baseline_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_snapshot_id"],
            ["knowledge_snapshots.id"],
            name="fk_demo_acceptance_runs_baseline_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_agent_id"],
            ["agents.id"],
            name="fk_demo_acceptance_runs_target_agent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"],
            ["agent_versions.id"],
            name="fk_demo_acceptance_runs_target_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debate_id"],
            ["debates.id"],
            name="fk_demo_acceptance_runs_debate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_revision_id"],
            ["civilization_report_revisions.id"],
            name="fk_demo_acceptance_runs_report_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "plan_version = 'real_core_demo_v2'",
            name="ck_demo_acceptance_runs_plan_version",
        ),
        sa.CheckConstraint(
            "length(fixture_hash) = 64 AND fixture_hash NOT GLOB '*[^0-9a-f]*'",
            name="ck_demo_acceptance_runs_fixture_hash",
        ),
        sa.CheckConstraint(
            "state IN ('prepared', 'executing', 'executed', 'verified')",
            name="ck_demo_acceptance_runs_state",
        ),
        sa.CheckConstraint(
            "starting_charged_requests = 0",
            name="ck_demo_acceptance_runs_initial_charged_zero",
        ),
    )
    op.create_index(
        "ix_demo_acceptance_runs_target",
        _RUN_TABLE,
        ["target_agent_id", "target_version_id"],
        unique=False,
    )
    op.create_index("ix_demo_acceptance_runs_debate", _RUN_TABLE, ["debate_id"], unique=False)


def _add_operation_binding() -> None:
    def operation() -> None:
        with op.batch_alter_table(_OPERATION_TABLE, recreate="always") as batch:
            batch.add_column(sa.Column("acceptance_run_id", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("call_no", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_provider_operations_acceptance_run",
                _RUN_TABLE,
                ["acceptance_run_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                "ck_provider_operations_acceptance_call_pair",
                "(acceptance_run_id IS NULL AND call_no IS NULL) OR "
                "(acceptance_run_id IS NOT NULL AND call_no IS NOT NULL)",
            )
            batch.create_check_constraint(
                "ck_provider_operations_call_no",
                "call_no IS NULL OR (call_no >= 1 AND call_no <= 8)",
            )
            batch.create_unique_constraint(
                "uq_provider_operations_acceptance_call",
                ["acceptance_run_id", "call_no"],
            )
            batch.create_index(
                "ix_provider_operations_acceptance_run",
                ["acceptance_run_id", "call_no"],
                unique=False,
            )

    _rebuild_provider_operations(operation)


def upgrade() -> None:
    _create_run_table()
    _add_operation_binding()


def _has_populated_runs() -> bool:
    bind = op.get_bind()
    return bind.execute(sa.text(f"SELECT 1 FROM {_RUN_TABLE} LIMIT 1")).first() is not None


def _has_populated_operation_bindings() -> bool:
    bind = op.get_bind()
    return (
        bind.execute(
            sa.text(
                f"SELECT 1 FROM {_OPERATION_TABLE} WHERE "
                "acceptance_run_id IS NOT NULL OR call_no IS NOT NULL LIMIT 1"
            )
        ).first()
        is not None
    )


def _drop_operation_binding() -> None:
    def operation() -> None:
        with op.batch_alter_table(_OPERATION_TABLE, recreate="always") as batch:
            batch.drop_index("ix_provider_operations_acceptance_run")
            batch.drop_constraint("uq_provider_operations_acceptance_call", type_="unique")
            batch.drop_constraint(
                "ck_provider_operations_call_no",
                type_="check",
            )
            batch.drop_constraint(
                "ck_provider_operations_acceptance_call_pair",
                type_="check",
            )
            batch.drop_constraint(
                "fk_provider_operations_acceptance_run",
                type_="foreignkey",
            )
            batch.drop_column("call_no")
            batch.drop_column("acceptance_run_id")

    _rebuild_provider_operations(operation)


def downgrade() -> None:
    """Downgrade only when no new run or operation binding would be lost."""

    if _has_populated_operation_bindings():
        raise RuntimeError(
            "Cannot downgrade 0016 while ProviderOperation call bindings are retained."
        )
    if _has_populated_runs():
        raise RuntimeError("Cannot downgrade 0016 while acceptance runs are retained.")
    _drop_operation_binding()
    op.drop_index("ix_demo_acceptance_runs_debate", table_name=_RUN_TABLE)
    op.drop_index("ix_demo_acceptance_runs_target", table_name=_RUN_TABLE)
    op.drop_table(_RUN_TABLE)
