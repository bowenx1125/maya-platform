"""Allow the bounded one-shot LLM turn export manifest.

``ExportManifestV1`` already refuses a one-shot LLM turn manifest that
discloses a repair-feedback policy, because no second attempt can consume it.
The table constraint, however, still required every ``llm_debate_turn``
manifest to be the two-attempt envelope with the exact repair policy pair.
The two rules were mutually exclusive, so the reviewed Real-Core Demo
composition could never persist a manifest and every real Debate LLM turn
failed before its provider operation existed.

This migration widens the constraint to accept exactly the second, bounded
shape: one attempt and no repair policy. Nothing else is relaxed. The
two-attempt envelope keeps its exact frozen policy version and hash, and the
existing pair constraint continues to forbid a half-populated repair policy.

SQLite rewrites a table to change a CHECK constraint, so the rebuild runs
inside the same foreign-key fence the 0016 migration uses: enforcement is
disabled for the rebuild and the migration fails closed if it introduced any
new foreign-key violation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_one_shot_llm_turn_manifest"
down_revision: str | Sequence[str] | None = "0016_real_core_acceptance_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "provider_export_manifests"
_CONSTRAINT = "ck_provider_export_manifests_llm_retry_policy"
_REPAIR_POLICY_VERSION = "repair_feedback_v1"
_REPAIR_POLICY_HASH = "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"

_TWO_ATTEMPT = (
    f"(max_attempts = 2 AND repair_policy_version = '{_REPAIR_POLICY_VERSION}' "
    f"AND repair_policy_hash = '{_REPAIR_POLICY_HASH}')"
)
_ONE_SHOT = "(max_attempts = 1 AND repair_policy_version IS NULL AND repair_policy_hash IS NULL)"

_OLD = f"provider_operation <> 'llm_debate_turn' OR {_TWO_ATTEMPT}"
_NEW = f"provider_operation <> 'llm_debate_turn' OR {_TWO_ATTEMPT} OR {_ONE_SHOT}"


def _rebuild_manifests(operation: Callable[[], None]) -> None:
    """Rebuild the manifest table without cascading into its children."""

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
                raise RuntimeError(f"0017 left new foreign-key violations: {new_violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0017 failed to restore SQLite foreign-key enforcement")


def _swap_constraint(condition: str) -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_CONSTRAINT, type_="check")
        batch.create_check_constraint(_CONSTRAINT, condition)


def upgrade() -> None:
    _rebuild_manifests(lambda: _swap_constraint(_NEW))


def downgrade() -> None:
    # Refuse rather than delete.  A one-shot manifest is referenced by its
    # confirmation and operation rows, so removing it to satisfy the narrower
    # rule would break provider lineage that an audit still needs.
    remaining = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT count(*) FROM {_TABLE} WHERE provider_operation = 'llm_debate_turn' "
                "AND max_attempts = 1 AND repair_policy_version IS NULL "
                "AND repair_policy_hash IS NULL"
            )
        )
        .scalar_one()
    )
    if int(remaining or 0):
        raise RuntimeError(
            "one-shot LLM turn manifests exist; quarantine the Demo runtime before downgrading"
        )
    _rebuild_manifests(lambda: _swap_constraint(_OLD))
