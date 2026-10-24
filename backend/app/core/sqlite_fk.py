"""Drop unnamed SQLite foreign keys while Alembic rebuilds a table.

SQLite foreign keys created without a name are copied into the replacement
table. A prefixed drop name tells the batch rebuild to remove the matching
key, named or not, before the new one is added.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from alembic.operations.batch import ApplyBatchImpl


def unnamed_fk_token(columns: list[str]) -> str:
    return "__cols__:" + ",".join(columns)


@contextmanager
def dropping_unnamed_foreign_keys() -> Iterator[None]:
    original = ApplyBatchImpl.drop_constraint

    def drop_constraint(self: ApplyBatchImpl, const: sa.Constraint) -> None:
        name = const.name or ""
        if isinstance(name, str) and name.startswith("__cols__:"):
            columns = name.removeprefix("__cols__:").split(",")
            self.named_constraints = {
                key: item
                for key, item in self.named_constraints.items()
                if not (
                    isinstance(item, sa.ForeignKeyConstraint)
                    and [col.name for col in item.columns] == columns
                )
            }
            self.unnamed_constraints = [
                item
                for item in self.unnamed_constraints
                if not (
                    isinstance(item, sa.ForeignKeyConstraint)
                    and [col.name for col in item.columns] == columns
                )
            ]
            if len(columns) == 1 and columns[0] in self.columns:
                reflected = self.columns[columns[0]]
                for fk in list(reflected.foreign_keys):
                    reflected.foreign_keys.remove(fk)
            return
        original(self, const)

    ApplyBatchImpl.drop_constraint = drop_constraint  # type: ignore[method-assign]
    try:
        yield
    finally:
        ApplyBatchImpl.drop_constraint = original  # type: ignore[method-assign]


def _trigger_rows(table: str) -> list[tuple[str, str]]:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return []
    rows = bind.execute(
        sa.text(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = :table AND sql IS NOT NULL"
        ),
        {"table": table},
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


@contextmanager
def preserving_table_triggers(table: str) -> Iterator[None]:
    """Recreate triggers a SQLite table rebuild drops with the old table."""

    saved = _trigger_rows(table)
    try:
        yield
    finally:
        if saved:
            current = {name for name, _sql in _trigger_rows(table)}
            for name, sql in saved:
                if name not in current:
                    op.execute(sql)
