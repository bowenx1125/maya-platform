"""Add operation-isolated budgets and the durable accepted LLM stage.

The pre-0014 budget table keyed only by ``scope_id`` could let an Embedding
query consume a Debate LLM allowance.  This migration recreates that table
with the closed ``(scope_id, budget_bucket)`` identity and backfills existing
rows only when their associated operations/manifests identify one bucket.  A
scope with no evidence or with mixed operation buckets fails closed instead of
guessing.

The migration also binds LLM export manifests to their Debate and Turn owner,
and adds one immutable, hash-only accepted-stage row containing the sanitized
structured output and usage/price facts needed for local recovery and audit.
No raw provider response, request body, header, credential or student data is
added to the ledger.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0014_llm_runtime_budget_buckets"
down_revision: str | Sequence[str] | None = "0013_embedding_identity_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BUCKETS = (
    "embedding_snapshot",
    "embedding_query",
    "llm_debate_turn",
    "llm_barrage_insight",
    "llm_maya_report",
    "tts_synthesis",
    "voice_enrollment",
)
_OPERATION_BUCKETS = {
    "embedding": "embedding_snapshot",
    "embedding_snapshot": "embedding_snapshot",
    "embedding_query": "embedding_query",
    "llm_debate": "llm_debate_turn",
    "llm_debate_turn": "llm_debate_turn",
    "llm_barrage_insight": "llm_barrage_insight",
    "llm_maya_report": "llm_maya_report",
    "tts_synthesis": "tts_synthesis",
    "voice_enrollment": "voice_enrollment",
}
_REPAIR_POLICY_VERSION = "repair_feedback_v1"
_REPAIR_POLICY_HASH = "d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b"


def _bucket_for_operation(operation: object) -> str:
    try:
        return _OPERATION_BUCKETS[str(operation)]
    except KeyError as exc:
        raise RuntimeError("0014 cannot map provider operation to a closed budget bucket") from exc


def _legacy_budget_rows() -> list[dict[str, object]]:
    """Read and classify old rows before changing their primary key."""

    bind = op.get_bind()
    rows = [
        dict(row)
        for row in bind.execute(
            sa.text(
                "SELECT scope_id, max_requests, max_total_tokens, max_cost_cny, "
                "allocated_requests, allocated_total_tokens, allocated_cost_cny, "
                "created_at, updated_at FROM provider_scope_budgets ORDER BY scope_id"
            )
        ).mappings()
    ]
    if not rows:
        return []
    evidence: defaultdict[str, set[str]] = defaultdict(set)
    for row in bind.execute(
        sa.text(
            "SELECT scope_id, provider_operation FROM provider_operations ORDER BY scope_id, id"
        )
    ).mappings():
        evidence[str(row["scope_id"])].add(_bucket_for_operation(row["provider_operation"]))
    # A prepared manifest may have a budget before its first operation is
    # created.  It is valid evidence when it names exactly one operation.
    for row in bind.execute(
        sa.text(
            "SELECT scope_id, provider_operation FROM provider_export_manifests "
            "ORDER BY scope_id, id"
        )
    ).mappings():
        evidence[str(row["scope_id"])].add(_bucket_for_operation(row["provider_operation"]))

    classified: list[dict[str, object]] = []
    for row in rows:
        scope_id = str(row["scope_id"])
        candidates = evidence.get(scope_id, set())
        if len(candidates) != 1:
            reason = "no operation evidence" if not candidates else "multiple operation buckets"
            raise RuntimeError(f"0014 cannot backfill scope {scope_id!r}: {reason}")
        value = dict(row)
        value["budget_bucket"] = next(iter(candidates))
        classified.append(value)
    return classified


def _budget_table(name: str) -> sa.Table:
    return op.create_table(
        name,
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("budget_bucket", sa.String(length=40), nullable=False),
        sa.Column("max_requests", sa.Integer(), nullable=False),
        sa.Column("max_total_tokens", sa.Integer(), nullable=False),
        sa.Column("max_cost_cny", sa.Numeric(12, 6), nullable=False),
        sa.Column("allocated_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allocated_total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allocated_cost_cny", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_id", "budget_bucket", name="pk_provider_scope_budgets"),
        sa.CheckConstraint(
            "budget_bucket IN ('embedding_snapshot', 'embedding_query', 'llm_debate_turn', "
            "'llm_barrage_insight', 'llm_maya_report', 'tts_synthesis', 'voice_enrollment')",
            name="ck_provider_scope_budgets_bucket",
        ),
        sa.CheckConstraint("max_requests >= 0", name="ck_provider_scope_budgets_max_requests"),
        sa.CheckConstraint("max_total_tokens >= 0", name="ck_provider_scope_budgets_max_tokens"),
        sa.CheckConstraint("max_cost_cny >= 0", name="ck_provider_scope_budgets_max_cost"),
        sa.CheckConstraint(
            "allocated_requests >= 0 AND allocated_requests <= max_requests",
            name="ck_provider_scope_budgets_allocated_requests",
        ),
        sa.CheckConstraint(
            "allocated_total_tokens >= 0 AND allocated_total_tokens <= max_total_tokens",
            name="ck_provider_scope_budgets_allocated_tokens",
        ),
        sa.CheckConstraint(
            "allocated_cost_cny >= 0 AND allocated_cost_cny <= max_cost_cny",
            name="ck_provider_scope_budgets_allocated_cost",
        ),
    )


def _rebuild_budget_table(rows: list[dict[str, object]]) -> None:
    """Replace the scope-only PK without dropping any allocation counters."""

    bind = op.get_bind()

    def operation() -> None:
        new_table = _budget_table("provider_scope_budgets_0014")
        if rows:
            bind.execute(
                new_table.insert(),
                [
                    {
                        **row,
                        "budget_bucket": str(row["budget_bucket"]),
                        "created_at": _coerce_datetime(row["created_at"]),
                        "updated_at": _coerce_datetime(row["updated_at"]),
                    }
                    for row in rows
                ],
            )
        op.drop_table("provider_scope_budgets")
        op.rename_table("provider_scope_budgets_0014", "provider_scope_budgets")

    _sqlite_parent_rebuild(operation)


def _rebuild_budget_to_legacy(rows: list[Mapping[str, object]]) -> None:
    """Collapse one bucket per scope back to the 0013 representation."""

    bind = op.get_bind()
    legacy_rows: list[dict[str, object]] = []
    for row in rows:
        value = dict(row)
        value.pop("budget_bucket", None)
        value["created_at"] = _coerce_datetime(value["created_at"])
        value["updated_at"] = _coerce_datetime(value["updated_at"])
        legacy_rows.append(value)

    def operation() -> None:
        table = op.create_table(
            "provider_scope_budgets_0013",
            sa.Column("scope_id", sa.String(length=255), primary_key=True),
            sa.Column("max_requests", sa.Integer(), nullable=False),
            sa.Column("max_total_tokens", sa.Integer(), nullable=False),
            sa.Column("max_cost_cny", sa.Numeric(12, 6), nullable=False),
            sa.Column("allocated_requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("allocated_total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("allocated_cost_cny", sa.Numeric(12, 6), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("max_requests >= 0", name="ck_provider_scope_budgets_max_requests"),
            sa.CheckConstraint(
                "max_total_tokens >= 0", name="ck_provider_scope_budgets_max_tokens"
            ),
            sa.CheckConstraint("max_cost_cny >= 0", name="ck_provider_scope_budgets_max_cost"),
            sa.CheckConstraint(
                "allocated_requests >= 0 AND allocated_requests <= max_requests",
                name="ck_provider_scope_budgets_allocated_requests",
            ),
            sa.CheckConstraint(
                "allocated_total_tokens >= 0 AND allocated_total_tokens <= max_total_tokens",
                name="ck_provider_scope_budgets_allocated_tokens",
            ),
            sa.CheckConstraint(
                "allocated_cost_cny >= 0 AND allocated_cost_cny <= max_cost_cny",
                name="ck_provider_scope_budgets_allocated_cost",
            ),
        )
        if legacy_rows:
            bind.execute(table.insert(), legacy_rows)
        op.drop_table("provider_scope_budgets")
        op.rename_table("provider_scope_budgets_0013", "provider_scope_budgets")

    _sqlite_parent_rebuild(operation)


def _coerce_datetime(value: object) -> object:
    """Convert SQLite's textual DateTime result for SQLAlchemy inserts."""

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value


def _sqlite_parent_rebuild(operation: object) -> None:
    """Run a table replacement while preserving SQLite foreign-key checks."""

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        cast_operation = operation
        cast_operation()  # type: ignore[operator]
        return
    with op.get_context().autocommit_block():
        sqlite = op.get_bind()
        sqlite.exec_driver_sql("PRAGMA foreign_keys=OFF")
        sqlite.exec_driver_sql("BEGIN IMMEDIATE")
        committed = False
        try:
            cast_operation = operation
            cast_operation()  # type: ignore[operator]
            violations = sqlite.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(f"0014 left foreign-key violations: {violations}")
            sqlite.exec_driver_sql("COMMIT")
            committed = True
        finally:
            if not committed:
                sqlite.exec_driver_sql("ROLLBACK")
            sqlite.exec_driver_sql("PRAGMA foreign_keys=ON")
            if sqlite.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
                raise RuntimeError("0014 failed to restore SQLite foreign-key enforcement")


def _add_manifest_fields() -> None:
    def operation() -> None:
        with op.batch_alter_table("provider_export_manifests", recreate="always") as batch:
            batch.add_column(sa.Column("debate_id", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("turn_id", sa.String(length=36), nullable=True))
            batch.add_column(
                sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1")
            )
            batch.add_column(
                sa.Column("max_total_tokens", sa.Integer(), nullable=False, server_default="0")
            )
            batch.add_column(
                sa.Column(
                    "max_cost_cny",
                    sa.Numeric(12, 6),
                    nullable=False,
                    server_default="0",
                )
            )
            batch.add_column(
                sa.Column("repair_policy_version", sa.String(length=80), nullable=True)
            )
            batch.add_column(sa.Column("repair_policy_hash", sa.String(length=64), nullable=True))
            batch.create_foreign_key(
                "fk_provider_export_manifests_debate",
                "debates",
                ["debate_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_provider_export_manifests_turn",
                "debate_turns",
                ["turn_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch.create_foreign_key(
                "fk_provider_export_manifests_turn_debate",
                "debate_turns",
                ["turn_id", "debate_id"],
                ["id", "debate_id"],
                ondelete="RESTRICT",
            )
            batch.create_check_constraint(
                "ck_provider_export_manifests_owner_pair",
                "(debate_id IS NULL AND turn_id IS NULL) OR "
                "(debate_id IS NOT NULL AND turn_id IS NOT NULL)",
            )
            batch.create_check_constraint(
                "ck_provider_export_manifests_llm_owner",
                "provider_operation <> 'llm_debate_turn' OR "
                "(debate_id IS NOT NULL AND turn_id IS NOT NULL)",
            )
            batch.create_check_constraint(
                "ck_provider_export_manifests_llm_retry_policy",
                "provider_operation <> 'llm_debate_turn' OR "
                "(max_attempts = 2 AND repair_policy_version = 'repair_feedback_v1' "
                "AND repair_policy_hash = "
                "'d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b')",
            )
            batch.create_check_constraint(
                "ck_provider_export_manifests_attempts",
                "max_attempts >= 1 AND max_attempts <= 2",
            )
            batch.create_check_constraint(
                "ck_provider_export_manifests_tokens", "max_total_tokens >= 0"
            )
            batch.create_check_constraint("ck_provider_export_manifests_cost", "max_cost_cny >= 0")
            batch.create_check_constraint(
                "ck_provider_export_manifests_repair_policy_pair",
                "(repair_policy_version IS NULL AND repair_policy_hash IS NULL) OR "
                "(repair_policy_version IS NOT NULL AND repair_policy_hash IS NOT NULL)",
            )
            batch.create_index("ix_provider_export_manifests_debate", ["debate_id"], unique=False)
            batch.create_index("ix_provider_export_manifests_turn", ["turn_id"], unique=False)

    _sqlite_parent_rebuild(operation)


def _create_llm_stage_table() -> None:
    op.create_table(
        "llm_accepted_stages",
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_contract_version", sa.String(length=80), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("tokenizer_id", sa.String(length=160), nullable=False),
        sa.Column("tokenizer_hash", sa.String(length=64), nullable=False),
        sa.Column("rule_set_hash", sa.String(length=64), nullable=False),
        sa.Column("persona_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("transcript_hash", sa.String(length=64), nullable=False),
        sa.Column("receipt_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("export_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("build_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("repair_policy_hash", sa.String(length=64), nullable=True),
        sa.Column("generation_fence", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("output_json", sa.Text(), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("price_card_version", sa.String(length=120), nullable=False),
        sa.Column("input_price_cny_per_million", sa.Numeric(20, 9), nullable=False),
        sa.Column("cached_input_price_cny_per_million", sa.Numeric(20, 9), nullable=False),
        sa.Column("output_price_cny_per_million", sa.Numeric(20, 9), nullable=False),
        sa.Column("estimated_cost_cny", sa.Numeric(12, 6), nullable=False),
        sa.Column("actual_cost_cny", sa.Numeric(12, 6), nullable=True),
        sa.Column("retrieval_reused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("repair_policy_version", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["provider_operations.id"],
            name="fk_llm_accepted_stages_operation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["debate_turns.id"],
            name="fk_llm_accepted_stages_turn",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("operation_id"),
        sa.UniqueConstraint("turn_id", "attempt_no", name="uq_llm_accepted_stages_turn_attempt"),
        sa.CheckConstraint("attempt_no >= 1 AND attempt_no <= 2", name="ck_llm_stages_attempt"),
        sa.CheckConstraint(
            "length(request_hash) = 64 AND length(prompt_hash) = 64 "
            "AND length(schema_hash) = 64 "
            "AND length(tokenizer_hash) = 64 AND length(rule_set_hash) = 64 "
            "AND length(persona_spec_hash) = 64 AND length(transcript_hash) = 64 "
            "AND length(receipt_hash) = 64 AND length(policy_hash) = 64 "
            "AND length(export_manifest_hash) = 64 AND length(build_manifest_hash) = 64 "
            "AND length(output_hash) = 64",
            name="ck_llm_stages_hashes",
        ),
        sa.CheckConstraint(
            "repair_policy_hash IS NULL OR length(repair_policy_hash) = 64",
            name="ck_llm_stages_repair_hash",
        ),
        sa.CheckConstraint(
            "(repair_policy_version IS NULL AND repair_policy_hash IS NULL) OR "
            "(repair_policy_version IS NOT NULL AND repair_policy_hash IS NOT NULL)",
            name="ck_llm_stages_repair_policy_pair",
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND cached_input_tokens >= 0 AND completion_tokens >= 0 "
            "AND total_tokens >= 0 AND cached_input_tokens <= prompt_tokens "
            "AND total_tokens = prompt_tokens + completion_tokens",
            name="ck_llm_stages_usage",
        ),
        sa.CheckConstraint(
            "input_price_cny_per_million >= 0 "
            "AND cached_input_price_cny_per_million >= 0 "
            "AND output_price_cny_per_million >= 0 "
            "AND estimated_cost_cny >= 0 "
            "AND (actual_cost_cny IS NULL OR actual_cost_cny >= 0)",
            name="ck_llm_stages_costs",
        ),
        sa.CheckConstraint("length(output_json) > 0", name="ck_llm_stages_output"),
    )
    op.create_index("ix_llm_accepted_stages_turn", "llm_accepted_stages", ["turn_id", "attempt_no"])


def _manifest_has_new_data() -> bool:
    bind = op.get_bind()
    return (
        bind.execute(
            sa.text(
                "SELECT 1 FROM provider_export_manifests WHERE "
                "debate_id IS NOT NULL OR turn_id IS NOT NULL OR max_attempts <> 1 "
                "OR max_total_tokens <> 0 OR max_cost_cny <> 0 "
                "OR repair_policy_version IS NOT NULL OR repair_policy_hash IS NOT NULL LIMIT 1"
            )
        ).first()
        is not None
    )


def _budget_rows_for_downgrade() -> list[Mapping[str, object]]:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text(
                "SELECT scope_id, budget_bucket, max_requests, max_total_tokens, max_cost_cny, "
                "allocated_requests, allocated_total_tokens, allocated_cost_cny, "
                "created_at, updated_at "
                "FROM provider_scope_budgets ORDER BY scope_id, budget_bucket"
            )
        ).mappings()
    )
    by_scope: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        by_scope[str(row["scope_id"])] += 1
    if any(count > 1 for count in by_scope.values()):
        raise RuntimeError("Cannot downgrade 0014 while a scope has multiple budget buckets.")
    return rows


def _drop_manifest_fields() -> None:
    def operation() -> None:
        with op.batch_alter_table("provider_export_manifests", recreate="always") as batch:
            batch.drop_index("ix_provider_export_manifests_turn")
            batch.drop_index("ix_provider_export_manifests_debate")
            batch.drop_constraint("ck_provider_export_manifests_repair_policy_pair", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_cost", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_tokens", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_attempts", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_llm_retry_policy", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_llm_owner", type_="check")
            batch.drop_constraint("ck_provider_export_manifests_owner_pair", type_="check")
            batch.drop_constraint("fk_provider_export_manifests_turn_debate", type_="foreignkey")
            batch.drop_constraint("fk_provider_export_manifests_turn", type_="foreignkey")
            batch.drop_constraint("fk_provider_export_manifests_debate", type_="foreignkey")
            batch.drop_column("repair_policy_hash")
            batch.drop_column("repair_policy_version")
            batch.drop_column("max_cost_cny")
            batch.drop_column("max_total_tokens")
            batch.drop_column("max_attempts")
            batch.drop_column("turn_id")
            batch.drop_column("debate_id")

    _sqlite_parent_rebuild(operation)


def upgrade() -> None:
    rows = _legacy_budget_rows()
    _rebuild_budget_table(rows)
    _add_manifest_fields()
    _create_llm_stage_table()


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM llm_accepted_stages LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade 0014 while accepted LLM stages are retained.")
    if _manifest_has_new_data():
        raise RuntimeError("Cannot downgrade 0014 while LLM owner/retry manifest data is retained.")
    budget_rows = _budget_rows_for_downgrade()
    op.drop_index("ix_llm_accepted_stages_turn", table_name="llm_accepted_stages")
    op.drop_table("llm_accepted_stages")
    _drop_manifest_fields()
    _rebuild_budget_to_legacy(budget_rows)
