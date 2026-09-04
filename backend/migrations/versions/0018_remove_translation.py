"""Remove the translation feature's tables and the Job column that owned them.

The Mock translation slice is deleted from the product: its routes, module,
provider selector, panel and events are gone, so the three tables it filled can
only accumulate rows nothing reads and force every future reader of the Job
ledger to work out that one of its four owner columns is dead.

``jobs`` needs a rewrite rather than a column drop: SQLite cannot alter a CHECK
constraint in place, and ``ck_jobs_wave3_typed_owner`` names the translation
operation and its column. The rebuild runs inside the same foreign-key fence
migration 0016 and 0017 use -- enforcement off for the rebuild, and the
migration fails closed if it introduced any new violation.

The data loss is intended and reaches nothing else: translation output was
always derived from a public turn or a report revision that both survive.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_remove_translation"
down_revision: str | Sequence[str] | None = "0017_one_shot_llm_turn_manifest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWNER_CONSTRAINT = "ck_jobs_wave3_typed_owner"

_WITH_TRANSLATION = (
    "(operation = 'barrage_insight.generate' AND insight_snapshot_id IS NOT NULL "
    "AND report_revision_id IS NULL AND translation_batch_id IS NULL) OR "
    "(operation = 'report.generate' AND insight_snapshot_id IS NULL "
    "AND report_revision_id IS NOT NULL AND translation_batch_id IS NULL) OR "
    "(operation = 'translation.generate' AND insight_snapshot_id IS NULL "
    "AND report_revision_id IS NULL AND translation_batch_id IS NOT NULL) OR "
    "(operation NOT IN ('barrage_insight.generate', 'report.generate', "
    "'translation.generate') AND insight_snapshot_id IS NULL "
    "AND report_revision_id IS NULL AND translation_batch_id IS NULL)"
)

_WITHOUT_TRANSLATION = (
    "(operation = 'barrage_insight.generate' AND insight_snapshot_id IS NOT NULL "
    "AND report_revision_id IS NULL) OR "
    "(operation = 'report.generate' AND insight_snapshot_id IS NULL "
    "AND report_revision_id IS NOT NULL) OR "
    "(operation NOT IN ('barrage_insight.generate', 'report.generate') "
    "AND insight_snapshot_id IS NULL AND report_revision_id IS NULL)"
)

_TRANSLATION_TABLES = (
    "translation_entries",
    "translation_batch_items",
    "translation_batches",
)


def _violation_counts(connection: object) -> Counter[tuple[str, str, int]]:
    """Foreign-key violations by (table, parent table, constraint), not by row."""

    rows = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()  # type: ignore[attr-defined]
    return Counter((str(row[0]), str(row[2]), int(row[3])) for row in rows)


def _fenced(operation: Callable[[], None]) -> None:
    """Run a table rebuild without cascading deletes into unrelated children."""

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
            # Compare violations by kind, not by rowid. Rebuilding a table
            # renumbers its rows, so an identical pre-existing violation comes
            # back with a different rowid and would read as new.
            existing_violations = _violation_counts(sqlite)
            operation()
            violations = _violation_counts(sqlite)
            new_violations = violations - existing_violations
            if new_violations:
                raise RuntimeError(f"0018 left new foreign-key violations: {new_violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0018 failed to restore SQLite foreign-key enforcement")


def _drop_translation_owner() -> None:
    # Any surviving translation Job loses its owner with its table, so it is
    # removed here rather than left to fail the narrower constraint.
    op.get_bind().execute(sa.text("DELETE FROM jobs WHERE operation = 'translation.generate'"))
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint(_OWNER_CONSTRAINT, type_="check")
        batch.drop_index("uq_jobs_translation_batch")
        batch.drop_column("translation_batch_id")
        batch.create_check_constraint(_OWNER_CONSTRAINT, _WITHOUT_TRANSLATION)


def _restore_translation_owner() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("translation_batch_id", sa.String(length=36), nullable=True))
        batch.drop_constraint(_OWNER_CONSTRAINT, type_="check")
        batch.create_check_constraint(_OWNER_CONSTRAINT, _WITH_TRANSLATION)
        batch.create_index(
            "uq_jobs_translation_batch",
            ["translation_batch_id"],
            unique=True,
            sqlite_where=sa.text("translation_batch_id IS NOT NULL"),
        )


def upgrade() -> None:
    _fenced(_drop_translation_owner)
    for table in _TRANSLATION_TABLES:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))


def downgrade() -> None:
    # The tables come back empty and without their foreign key to jobs: the
    # rows are gone, and inventing a schema that claims otherwise would be
    # worse than an honest empty one.
    op.create_table(
        "translation_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("debate_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "translation_batch_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=True),
    )
    op.create_table(
        "translation_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("report_revision_id", sa.String(length=36), nullable=True),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column("target_language", sa.String(length=16), nullable=False),
        sa.Column("policy_key", sa.String(length=64), nullable=False),
        sa.Column("quality_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
    )
    _fenced(_restore_translation_owner)
