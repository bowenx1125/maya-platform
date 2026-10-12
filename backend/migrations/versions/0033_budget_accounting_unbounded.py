"""Keep provider accounting without request, token or cost ceilings."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_budget_accounting_unbounded"
down_revision: str | Sequence[str] | None = "0032_recovery_input_unbounded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS = (
    ("requests", "allocated_requests", "max_requests"),
    ("tokens", "allocated_total_tokens", "max_total_tokens"),
    ("cost", "allocated_cost_cny", "max_cost_cny"),
)


def _rebuild(operation: Callable[[], None]) -> None:
    """Preserve the operation ledger's child rows while replacing its checks."""

    if op.get_bind().dialect.name != "sqlite":
        operation()
        return
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            before = set(connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall())
            operation()
            after = set(connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall())
            if after - before:
                raise RuntimeError("Budget migration introduced foreign-key violations.")
            connection.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                connection.exec_driver_sql("ROLLBACK")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("Budget migration did not restore foreign-key enforcement.")


def _change_checks(*, bounded: bool) -> None:
    with op.batch_alter_table("provider_scope_budgets", recreate="always") as batch:
        for suffix, allocated, maximum in _CONSTRAINTS:
            name = f"ck_provider_scope_budgets_allocated_{suffix}"
            batch.drop_constraint(name, type_="check")
            expression = f"{allocated} >= 0"
            if bounded:
                expression += f" AND {allocated} <= {maximum}"
            batch.create_check_constraint(name, expression)
    with op.batch_alter_table("provider_operations", recreate="always") as batch:
        batch.drop_constraint("ck_provider_operations_call_no", type_="check")
        expression = (
            "call_no IS NULL OR (call_no >= 1 AND call_no <= 8)"
            if bounded
            else "call_no IS NULL OR call_no >= 1"
        )
        batch.create_check_constraint("ck_provider_operations_call_no", expression)


def upgrade() -> None:
    _rebuild(lambda: _change_checks(bounded=False))


def downgrade() -> None:
    condition = " OR ".join(f"{allocated} > {maximum}" for _, allocated, maximum in _CONSTRAINTS)
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT 1 FROM provider_scope_budgets WHERE {condition} LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot restore budget ceilings below recorded allocations.")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM provider_operations WHERE call_no > 8 LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot restore call ceilings below recorded ordinals.")
    _rebuild(lambda: _change_checks(bounded=True))
