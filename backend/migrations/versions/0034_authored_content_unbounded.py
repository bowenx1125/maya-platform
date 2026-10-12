"""Remove authored Markdown length ceilings from immutable snapshots.

The table is a parent of snapshot documents and chunks. Rebuilding it with
SQLite foreign-key enforcement enabled would cascade-delete those immutable
children, so the migration copies its original DDL and rows inside one writer
transaction while preserving explicit indexes and triggers.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_authored_content_unbounded"
down_revision: str | Sequence[str] | None = "0033_budget_accounting_unbounded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "knowledge_snapshots"
_TEMP_TABLE = "knowledge_snapshots__0034_rebuild"
_CONSTRAINT = "ck_knowledge_snapshots_total_chars"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _replace_total_check(table_sql: str, *, bounded: bool) -> str:
    if not bounded:
        pattern = re.compile(
            rf"(CONSTRAINT\s+{_CONSTRAINT}\s+CHECK\s*\(\s*"
            r"total_char_count\s*>=\s*1)\s+AND\s+"
            r"total_char_count\s*<=\s*100000(\s*\))",
            re.IGNORECASE,
        )
        replacement = r"\1\2"
    else:
        pattern = re.compile(
            rf"(CONSTRAINT\s+{_CONSTRAINT}\s+CHECK\s*\(\s*"
            r"total_char_count\s*>=\s*1)(\s*\))",
            re.IGNORECASE,
        )
        replacement = r"\1 AND total_char_count <= 100000\2"
    result, count = pattern.subn(replacement, table_sql, count=1)
    if count != 1:
        raise RuntimeError(f"Could not locate the expected {_CONSTRAINT} definition.")
    return result


def _sqlite_rebuild(*, bounded: bool) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    began = False
    completed = False
    try:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        began = True
        before_violations = {
            tuple(row) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")
        }
        row = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).first()
        if row is None or not isinstance(row[0], str):
            raise RuntimeError("knowledge_snapshots has no SQLite table definition.")

        create_sql = _replace_total_check(row[0], bounded=bounded)
        table_pattern = re.compile(
            r'^(\s*CREATE\s+TABLE\s+)(?:"knowledge_snapshots"|'
            r"`knowledge_snapshots`|\[knowledge_snapshots\]|knowledge_snapshots)(?=\s|\()",
            re.IGNORECASE,
        )
        create_sql, renamed = table_pattern.subn(
            f"CREATE TABLE {_identifier(_TEMP_TABLE)}", create_sql, count=1
        )
        if renamed != 1:
            raise RuntimeError("Could not prepare the knowledge_snapshots rebuild table.")

        schema_objects = (
            connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master "
                "WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL "
                "ORDER BY CASE type WHEN 'index' THEN 0 ELSE 1 END, name",
                (_TABLE,),
            )
            .scalars()
            .all()
        )
        columns = [
            str(item[1])
            for item in connection.exec_driver_sql(
                f"PRAGMA table_info({_identifier(_TABLE)})"
            ).fetchall()
        ]
        if not columns:
            raise RuntimeError("knowledge_snapshots has no columns to preserve.")
        quoted_columns = ", ".join(_identifier(column) for column in columns)
        original_count = connection.exec_driver_sql(
            f"SELECT count(*) FROM {_identifier(_TABLE)}"
        ).scalar_one()

        connection.exec_driver_sql(create_sql)
        connection.exec_driver_sql(
            f"INSERT INTO {_identifier(_TEMP_TABLE)} ({quoted_columns}) "
            f"SELECT {quoted_columns} FROM {_identifier(_TABLE)}"
        )
        copied_count = connection.exec_driver_sql(
            f"SELECT count(*) FROM {_identifier(_TEMP_TABLE)}"
        ).scalar_one()
        if copied_count != original_count:
            raise RuntimeError("knowledge_snapshots rows were not copied completely.")

        connection.exec_driver_sql(f"DROP TABLE {_identifier(_TABLE)}")
        connection.exec_driver_sql(
            f"ALTER TABLE {_identifier(_TEMP_TABLE)} RENAME TO {_identifier(_TABLE)}"
        )
        for statement in schema_objects:
            connection.exec_driver_sql(str(statement))

        violations = {tuple(row) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")}
        if violations - before_violations:
            raise RuntimeError(
                f"0034 introduced foreign-key violations: {violations - before_violations}"
            )
        completed = True
    finally:
        if began and not completed:
            connection.exec_driver_sql("ROLLBACK")


def _change_check(*, bounded: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _sqlite_rebuild(bounded=bounded)
        return

    expression = "total_char_count >= 1"
    if bounded:
        expression += " AND total_char_count <= 100000"
    with op.batch_alter_table(_TABLE, recreate="always") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, expression)


def upgrade() -> None:
    _change_check(bounded=False)


def downgrade() -> None:
    bind = op.get_bind()
    oversized = bind.execute(
        sa.text("SELECT 1 FROM knowledge_snapshots WHERE total_char_count > 100000 LIMIT 1")
    ).first()
    if oversized is not None:
        raise RuntimeError(
            "Cannot restore the 100000 character snapshot ceiling while larger snapshots exist."
        )
    _change_check(bounded=True)
