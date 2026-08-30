"""Add the server-only ProviderDataCallV1 control ledger.

The migration is additive and intentionally performs no legacy backfill.  The
tables contain policy/export hashes, conservative allowance metadata and safe
operation states only; provider keys, request payloads and supplier response
bodies never have a column here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_provider_control_ledger"
down_revision: str | Sequence[str] | None = "0009_persona_structured_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = (
    "provider_policy_snapshots",
    "provider_export_manifests",
    "provider_export_confirmations",
    "provider_scope_budgets",
    "provider_operations",
    "provider_reservations",
)


def upgrade() -> None:
    op.create_table(
        "provider_policy_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("policy_id", sa.String(length=120), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("supplier", sa.String(length=160), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("account_product", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("privacy_notice_url", sa.String(length=500), nullable=False),
        sa.Column("privacy_notice_retrieved_at", sa.String(length=64), nullable=False),
        sa.Column("privacy_notice_sha256", sa.String(length=64), nullable=False),
        sa.Column("service_terms_url", sa.String(length=500), nullable=False),
        sa.Column("service_terms_retrieved_at", sa.String(length=64), nullable=False),
        sa.Column("service_terms_sha256", sa.String(length=64), nullable=False),
        sa.Column("faq_url", sa.String(length=500), nullable=False),
        sa.Column("faq_retrieved_at", sa.String(length=64), nullable=False),
        sa.Column("faq_sha256", sa.String(length=64), nullable=False),
        sa.Column("no_training_basis", sa.Text(), nullable=False),
        sa.Column("prompt_response_logging_disabled", sa.Boolean(), nullable=False),
        sa.Column("inference_log_backflow_disabled", sa.Boolean(), nullable=False),
        sa.Column("optional_content_logging_disabled", sa.Boolean(), nullable=False),
        sa.Column("service_improvement_disabled", sa.Boolean(), nullable=False),
        sa.Column("storage_disclosed", sa.Boolean(), nullable=False),
        sa.Column("retention_setting", sa.String(length=160), nullable=True),
        sa.Column("snapshot_revision", sa.Integer(), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "policy_id", "snapshot_revision", name="uq_provider_policy_snapshots_revision"
        ),
        sa.CheckConstraint(
            "contract_version = 'ProviderDataCallV1'",
            name="ck_provider_policy_snapshots_contract",
        ),
        sa.CheckConstraint("region = 'cn-beijing'", name="ck_provider_policy_snapshots_region"),
        sa.CheckConstraint(
            "account_product IN ('payg_api', 'pay-as-you-go api', 'pay-as-you-go API', "
            "'token_plan_team', 'Token Plan Team')",
            name="ck_provider_policy_snapshots_account_product",
        ),
        sa.CheckConstraint(
            "prompt_response_logging_disabled = 1 "
            "AND inference_log_backflow_disabled = 1 "
            "AND optional_content_logging_disabled = 1 "
            "AND service_improvement_disabled = 1",
            name="ck_provider_policy_snapshots_controls",
        ),
        sa.CheckConstraint("storage_disclosed = 1", name="ck_provider_policy_snapshots_storage"),
        sa.CheckConstraint("snapshot_revision >= 1", name="ck_provider_policy_snapshots_revision"),
    )
    op.create_index(
        "ix_provider_policy_snapshots_policy",
        "provider_policy_snapshots",
        ["policy_id", "snapshot_revision"],
        unique=False,
    )

    op.create_table(
        "provider_export_manifests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("policy_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("provider_operation", sa.String(length=80), nullable=False),
        sa.Column("model_key", sa.String(length=120), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("build_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("persona_spec_hash", sa.String(length=64), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("operation_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("contains_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("contains_identity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "contains_private_audio", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("contains_teacher_note", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"],
            ["provider_policy_snapshots.id"],
            name="fk_provider_export_manifests_policy",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("operation_revision >= 1", name="ck_provider_export_manifests_revision"),
        sa.CheckConstraint(
            "contains_secret = 0 AND contains_identity = 0 "
            "AND contains_private_audio = 0 AND contains_teacher_note = 0",
            name="ck_provider_export_manifests_no_forbidden_data",
        ),
    )
    op.create_index(
        "ix_provider_export_manifests_scope",
        "provider_export_manifests",
        ["scope_id", "provider_operation"],
        unique=False,
    )
    op.create_index(
        "ix_provider_export_manifests_policy",
        "provider_export_manifests",
        ["policy_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "provider_export_confirmations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("manifest_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("policy_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmed_at", sa.String(length=64), nullable=False),
        sa.Column("confirmation_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["manifest_id"],
            ["provider_export_manifests.id"],
            name="fk_provider_export_confirmations_manifest",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_snapshot_id"],
            ["provider_policy_snapshots.id"],
            name="fk_provider_export_confirmations_policy",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "confirmation_revision >= 1", name="ck_provider_export_confirmations_revision"
        ),
    )
    op.create_index(
        "ix_provider_export_confirmations_policy",
        "provider_export_confirmations",
        ["policy_snapshot_id"],
        unique=False,
    )

    op.create_table(
        "provider_scope_budgets",
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

    op.create_table(
        "provider_operations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("provider_operation", sa.String(length=80), nullable=False),
        sa.Column("logical_item_id", sa.String(length=255), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("max_cost_cny", sa.Numeric(12, 6), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("export_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("build_manifest_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model_key", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="prepared"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("charged_request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("staged_response_hash", sa.String(length=64), nullable=True),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope_id",
            "provider_operation",
            "logical_item_id",
            "attempt_no",
            name="uq_provider_operations_attempt",
        ),
        sa.CheckConstraint("attempt_no >= 1", name="ck_provider_operations_attempt"),
        sa.CheckConstraint("max_tokens >= 0", name="ck_provider_operations_max_tokens"),
        sa.CheckConstraint("max_cost_cny >= 0", name="ck_provider_operations_max_cost"),
        sa.CheckConstraint(
            "state IN ('prepared', 'reserved', 'sending', 'accepted', 'succeeded', "
            "'not_sent', 'acceptance_unknown', 'failed', 'abandoned')",
            name="ck_provider_operations_state",
        ),
        sa.CheckConstraint(
            "request_count >= 0 AND charged_request_count >= 0",
            name="ck_provider_operations_counters",
        ),
    )
    op.create_index(
        "ix_provider_operations_scope_state",
        "provider_operations",
        ["scope_id", "state"],
        unique=False,
    )
    op.create_index("ix_provider_operations_state", "provider_operations", ["state"], unique=False)

    op.create_table(
        "provider_reservations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("operation_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("scope_id", sa.String(length=255), nullable=False),
        sa.Column("provider_operation", sa.String(length=80), nullable=False),
        sa.Column("logical_item_id", sa.String(length=255), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("max_cost_cny", sa.Numeric(12, 6), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False, server_default="prepared"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["provider_operations.id"],
            name="fk_provider_reservations_operation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("attempt_no >= 1", name="ck_provider_reservations_attempt"),
        sa.CheckConstraint("max_tokens >= 0", name="ck_provider_reservations_max_tokens"),
        sa.CheckConstraint("max_cost_cny >= 0", name="ck_provider_reservations_max_cost"),
        sa.CheckConstraint(
            "state IN ('prepared', 'reserved', 'sending', 'accepted', 'succeeded', "
            "'not_sent', 'acceptance_unknown', 'failed', 'abandoned')",
            name="ck_provider_reservations_state",
        ),
    )
    op.create_index(
        "ix_provider_reservations_scope_state",
        "provider_reservations",
        ["scope_id", "state"],
        unique=False,
    )


def _assert_empty_for_downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError(
                f"Cannot downgrade 0010 while {table} contains ProviderDataCallV1 data."
            )


def downgrade() -> None:
    """Drop only an unused ledger; never delete provider-control history."""

    _assert_empty_for_downgrade()
    op.drop_index("ix_provider_reservations_scope_state", table_name="provider_reservations")
    op.drop_table("provider_reservations")
    op.drop_index("ix_provider_operations_state", table_name="provider_operations")
    op.drop_index("ix_provider_operations_scope_state", table_name="provider_operations")
    op.drop_table("provider_operations")
    op.drop_table("provider_scope_budgets")
    op.drop_index(
        "ix_provider_export_confirmations_policy",
        table_name="provider_export_confirmations",
    )
    op.drop_table("provider_export_confirmations")
    op.drop_index("ix_provider_export_manifests_policy", table_name="provider_export_manifests")
    op.drop_index("ix_provider_export_manifests_scope", table_name="provider_export_manifests")
    op.drop_table("provider_export_manifests")
    op.drop_index("ix_provider_policy_snapshots_policy", table_name="provider_policy_snapshots")
    op.drop_table("provider_policy_snapshots")
