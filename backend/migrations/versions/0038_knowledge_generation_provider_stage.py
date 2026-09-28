"""Bind exact Provider authorization and accepted stages to Knowledge runs."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_knowledge_generation_provider_stage"
down_revision: str | Sequence[str] | None = "0037_knowledge_generation_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite otherwise autocommits table/column DDL before Alembic's head
        # update, leaving a partial schema that cannot be safely retried.
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.add_column(
        "knowledge_generation_runs",
        sa.Column("provider_manifest_hash", sa.String(64), nullable=True),
    )
    op.create_table(
        "knowledge_generation_accepted_stages",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("model_key", sa.String(120), nullable=False),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("canonical_stage_json", sa.Text(), nullable=True),
        sa.Column("canonical_stage_hash", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(request_hash) = 64", name="ck_knowledge_generation_stage_request"
        ),
        sa.CheckConstraint(
            "length(manifest_hash) = 64", name="ck_knowledge_generation_stage_manifest"
        ),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_knowledge_generation_stage_policy"),
        sa.CheckConstraint("length(schema_hash) = 64", name="ck_knowledge_generation_stage_schema"),
        sa.CheckConstraint(
            "length(canonical_stage_hash) = 64", name="ck_knowledge_generation_stage_hash"
        ),
        sa.CheckConstraint("item_count >= 0", name="ck_knowledge_generation_stage_item_count"),
        sa.CheckConstraint(
            "(canonical_stage_json IS NULL AND item_count = 0 AND safe_error_code IS NOT NULL) "
            "OR (canonical_stage_json IS NOT NULL AND safe_error_code IS NULL)",
            name="ck_knowledge_generation_stage_suppression",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_generation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operation_id"], ["provider_operations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("operation_id", name="uq_knowledge_generation_stage_operation"),
    )
    op.create_index(
        "ix_knowledge_generation_stage_operation",
        "knowledge_generation_accepted_stages",
        ["operation_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    has_stage = (
        bind.exec_driver_sql("SELECT 1 FROM knowledge_generation_accepted_stages LIMIT 1").first()
        is not None
    )
    has_bound_manifest = (
        bind.exec_driver_sql(
            "SELECT 1 FROM knowledge_generation_runs "
            "WHERE provider_manifest_hash IS NOT NULL LIMIT 1"
        ).first()
        is not None
    )
    has_operation = (
        bind.exec_driver_sql(
            "SELECT 1 FROM provider_operations "
            "WHERE provider_operation = 'llm_knowledge_generate' LIMIT 1"
        ).first()
        is not None
    )
    if has_stage or has_bound_manifest or has_operation:
        raise RuntimeError("Knowledge Provider history exists; refusing to discard it.")
    op.drop_index(
        "ix_knowledge_generation_stage_operation",
        table_name="knowledge_generation_accepted_stages",
    )
    op.drop_table("knowledge_generation_accepted_stages")
    op.drop_column("knowledge_generation_runs", "provider_manifest_hash")
