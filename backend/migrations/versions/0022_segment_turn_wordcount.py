"""Allow short paragraph turns under the explicit segments_v2 marker."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_segment_turn_wordcount"
down_revision: str | Sequence[str] | None = "0021_segment_recovery_input"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WORD_COUNT_CHECK = (
    "word_count IS NULL OR (word_count >= 80 AND word_count <= 200) OR "
    "(json_extract(structured_json, '$.schema_version') = 'segment_turn_v2' "
    "AND word_count >= 0)"
)
_FINAL_READY_CHECK = (
    "generation_status != 'final_ready' OR "
    "(preparation_stage = 'ready' AND speech IS NOT NULL AND structured_json IS NOT NULL "
    "AND transcript_hash IS NOT NULL AND cutoff_turn_index IS NOT NULL "
    "AND retrieval_status IS NOT NULL AND grounding_mode IS NOT NULL "
    "AND word_count IS NOT NULL AND ((word_count >= 80 AND word_count <= 200) OR "
    "(json_extract(structured_json, '$.schema_version') = 'segment_turn_v2' "
    "AND word_count >= 0)))"
)


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

    Recreating ``debate_turns`` is the only portable SQLite way to replace its
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
                raise RuntimeError(f"0022 left new foreign-key violations: {new_violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0022 failed to restore SQLite foreign-key enforcement")


def _drop_barrage_scope_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for name in ("barrage_turn_scope_insert", "barrage_turn_scope_update"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))


def _create_barrage_scope_triggers() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    op.execute(
        sa.text(
            "CREATE TRIGGER barrage_turn_scope_insert BEFORE INSERT ON barrage_messages "
            "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM debate_turns WHERE id=NEW.turn_id AND debate_id=NEW.debate_id) "
            "BEGIN SELECT RAISE(ABORT, 'barrage_turn_scope'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER barrage_turn_scope_update BEFORE UPDATE ON barrage_messages "
            "WHEN NEW.turn_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM debate_turns WHERE id=NEW.turn_id AND debate_id=NEW.debate_id) "
            "BEGIN SELECT RAISE(ABORT, 'barrage_turn_scope'); END"
        )
    )


def upgrade() -> None:
    _drop_barrage_scope_triggers()
    try:
        _fenced(_replace_checks)
    finally:
        _create_barrage_scope_triggers()


def downgrade() -> None:
    _drop_barrage_scope_triggers()
    try:
        _fenced(_restore_checks)
    finally:
        _create_barrage_scope_triggers()


def _replace_checks() -> None:
    with op.batch_alter_table("debate_turns", recreate="always") as batch:
        batch.drop_constraint("ck_debate_turns_word_count", type_="check")
        batch.drop_constraint("ck_debate_turns_final_ready_shape", type_="check")
        batch.create_check_constraint("ck_debate_turns_word_count", _WORD_COUNT_CHECK)
        batch.create_check_constraint("ck_debate_turns_final_ready_shape", _FINAL_READY_CHECK)


def _restore_checks() -> None:
    with op.batch_alter_table("debate_turns", recreate="always") as batch:
        batch.drop_constraint("ck_debate_turns_word_count", type_="check")
        batch.drop_constraint("ck_debate_turns_final_ready_shape", type_="check")
        batch.create_check_constraint(
            "ck_debate_turns_word_count",
            "word_count IS NULL OR (word_count >= 80 AND word_count <= 200)",
        )
        batch.create_check_constraint(
            "ck_debate_turns_final_ready_shape",
            "generation_status != 'final_ready' OR "
            "(preparation_stage = 'ready' AND speech IS NOT NULL AND structured_json IS NOT NULL "
            "AND transcript_hash IS NOT NULL AND cutoff_turn_index IS NOT NULL "
            "AND retrieval_status IS NOT NULL AND grounding_mode IS NOT NULL "
            "AND word_count IS NOT NULL AND word_count >= 80 AND word_count <= 200)",
        )
