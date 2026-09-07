"""Remove automatic length padding from versioned segment reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_segment_report_wordcount"
down_revision: str | Sequence[str] | None = "0022_segment_turn_wordcount"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _foreign_key_violation_kinds(connection: sa.Connection) -> Counter[tuple[object, ...]]:
    """Compare logical keys because a rebuild can reorder FK indexes and rowids."""

    result: Counter[tuple[object, ...]] = Counter()
    quote = connection.dialect.identifier_preparer.quote
    for table, rowid, parent, constraint in connection.exec_driver_sql("PRAGMA foreign_key_check"):
        table_sql = quote(str(table))
        foreign_keys = connection.exec_driver_sql(
            f"PRAGMA foreign_key_list({table_sql})"
        ).fetchall()
        columns = tuple(
            sorted(
                (int(item[1]), str(item[3]), str(item[4]))
                for item in foreign_keys
                if int(item[0]) == int(constraint)
            )
        )
        info = connection.exec_driver_sql(f"PRAGMA table_info({table_sql})").fetchall()
        primary = [str(item[1]) for item in sorted(info, key=lambda item: int(item[5])) if item[5]]
        selected = primary or [item[1] for item in columns]
        selected_sql = ", ".join(quote(name) for name in selected)
        identity = (
            connection.exec_driver_sql(
                f"SELECT {selected_sql} FROM {table_sql} WHERE rowid=?",
                (rowid,),
            ).first()
            if selected and rowid is not None
            else None
        )
        result[(str(table), str(parent), columns, tuple(identity) if identity else None)] += 1
    return result


def _fenced(operation: Callable[[], None]) -> None:
    """Run the SQLite DDL rebuild behind a checked foreign-key fence.

    Recreating ``civilization_report_revisions`` is the only portable SQLite way to replace its
    CHECK constraints.  Existing child rows reference that table, so SQLite's
    normal ``DROP TABLE`` enforcement rejects the rebuild.  Foreign-key
    enforcement is relaxed only for this schema-copy transaction, then every
    constraint is checked before commit and enforcement is restored before any
    caller can write data.  This follows the established 0018 migration fence.
    """

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
            existing_violations = _foreign_key_violation_kinds(sqlite)
            operation()
            violations = _foreign_key_violation_kinds(sqlite)
            new_violations = violations - existing_violations
            if new_violations:
                raise RuntimeError(f"0023 left new foreign-key violations: {new_violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0023 failed to restore SQLite foreign-key enforcement")


def _replace_check(*, legacy: bool) -> None:
    minimum = (
        "word_count >= 600"
        if legacy
        else (
            "word_count >= 1 AND (word_count >= 600 OR "
            "COALESCE(json_extract(input_manifest_json, '$.manifest_version'), '') "
            "= 'report_input_manifest_v2')"
        )
    )
    with op.batch_alter_table("civilization_report_revisions", recreate="always") as batch:
        batch.drop_constraint("ck_civilization_report_revisions_ready_shape", type_="check")
        batch.create_check_constraint(
            "ck_civilization_report_revisions_ready_shape",
            "status != 'ready' OR (english_markdown IS NOT NULL AND "
            + minimum
            + " AND word_count <= 900 AND safe_error_code IS NULL)",
        )


def upgrade() -> None:
    _fenced(lambda: _replace_check(legacy=False))


def downgrade() -> None:
    # Short ready reports cannot be silently padded or deleted to restore v1.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM civilization_report_revisions "
                "WHERE status='ready' AND word_count < 600"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Cannot downgrade while short segment reports are retained")
    _fenced(lambda: _replace_check(legacy=True))
