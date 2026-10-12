"""Add per-item Knowledge generation receipts and materialization history."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_knowledge_generation_materialization"
down_revision: str | Sequence[str] | None = "0038_knowledge_generation_provider_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.add_column(
        "knowledge_assets",
        sa.Column("generation_lineage_key", sa.String(64), nullable=True),
    )
    op.create_table(
        "knowledge_generation_target_snapshots",
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("asset_heads_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(asset_heads_json) > 0",
            name="ck_knowledge_generation_target_snapshot_json",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_generation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "ix_knowledge_generation_target_snapshot_created",
        "knowledge_generation_target_snapshots",
        ["created_at"],
    )
    op.execute(
        sa.text(
            "INSERT INTO knowledge_generation_target_snapshots "
            "(run_id, asset_heads_json, created_at) "
            "SELECT id, '[]', created_at FROM knowledge_generation_runs"
        )
    )
    op.create_index(
        "uq_knowledge_assets_set_lineage",
        "knowledge_assets",
        ["knowledge_set_id", "generation_lineage_key"],
        unique=True,
        sqlite_where=sa.text("generation_lineage_key IS NOT NULL"),
        postgresql_where=sa.text("generation_lineage_key IS NOT NULL"),
    )

    op.create_table(
        "knowledge_generation_source_receipts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("source_binding_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("stored_file_id", sa.String(36), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("source_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("source_index_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(source_content_hash) = 64",
            name="ck_generation_receipt_content_hash",
        ),
        sa.CheckConstraint(
            "length(source_file_sha256) = 64",
            name="ck_generation_receipt_file_hash",
        ),
        sa.CheckConstraint(
            "source_authorization_epoch >= 0 AND source_index_revision >= 0",
            name="ck_generation_receipt_counters",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_generation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_binding_id"], ["knowledge_set_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_binding_id", name="uq_generation_receipt_binding"),
    )
    op.create_index(
        "ix_generation_receipts_run",
        "knowledge_generation_source_receipts",
        ["run_id", "created_at"],
    )

    op.create_table(
        "knowledge_generation_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("stage_hash", sa.String(64), nullable=False),
        sa.Column("item_key", sa.String(64), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("lineage_key", sa.String(64), nullable=True),
        sa.Column("candidate_hash", sa.String(64), nullable=False),
        sa.Column("source_receipt_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("citation_unverified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("asset_id", sa.String(36), nullable=True),
        sa.Column("asset_version_id", sa.String(36), nullable=True),
        sa.Column("expected_asset_version_seq", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(stage_hash) = 64", name="ck_knowledge_generation_item_stage"),
        sa.CheckConstraint("length(item_key) = 64", name="ck_knowledge_generation_item_key"),
        sa.CheckConstraint("item_index >= 0", name="ck_knowledge_generation_item_index"),
        sa.CheckConstraint(
            "kind IN ('concept', 'question', 'note', 'invalid')",
            name="ck_knowledge_generation_item_kind",
        ),
        sa.CheckConstraint(
            "lineage_key IS NULL OR length(lineage_key) = 64",
            name="ck_knowledge_generation_item_lineage",
        ),
        sa.CheckConstraint("length(candidate_hash) = 64", name="ck_knowledge_generation_item_hash"),
        sa.CheckConstraint(
            "citation_unverified_count >= 0",
            name="ck_knowledge_generation_item_citation_count",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'applied', 'failed', 'skipped')",
            name="ck_knowledge_generation_item_state",
        ),
        sa.CheckConstraint(
            "expected_asset_version_seq IS NULL OR expected_asset_version_seq >= 1",
            name="ck_knowledge_generation_item_expected_seq",
        ),
        sa.CheckConstraint(
            "(state = 'applied' AND asset_id IS NOT NULL AND asset_version_id IS NOT NULL) OR "
            "(state != 'applied' AND asset_version_id IS NULL)",
            name="ck_knowledge_generation_item_applied_version",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["knowledge_generation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["knowledge_asset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_key", name="uq_knowledge_generation_item_key"),
        sa.UniqueConstraint("run_id", "item_index", name="uq_knowledge_generation_item_index"),
        sa.UniqueConstraint("asset_version_id", name="uq_knowledge_generation_item_version"),
    )
    op.create_index(
        "ix_knowledge_generation_items_run_state",
        "knowledge_generation_items",
        ["run_id", "state", "item_index"],
    )
    op.create_index(
        "ix_knowledge_generation_items_lineage",
        "knowledge_generation_items",
        ["lineage_key", "updated_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    has_items = (
        bind.exec_driver_sql("SELECT 1 FROM knowledge_generation_items LIMIT 1").first() is not None
    )
    has_receipts = (
        bind.exec_driver_sql("SELECT 1 FROM knowledge_generation_source_receipts LIMIT 1").first()
        is not None
    )
    has_lineage = (
        bind.exec_driver_sql(
            "SELECT 1 FROM knowledge_assets WHERE generation_lineage_key IS NOT NULL LIMIT 1"
        ).first()
        is not None
    )
    has_target_snapshots = (
        bind.exec_driver_sql("SELECT 1 FROM knowledge_generation_target_snapshots LIMIT 1").first()
        is not None
    )
    if has_items or has_receipts or has_lineage or has_target_snapshots:
        raise RuntimeError("Knowledge materialization history exists; refusing to discard it.")

    op.drop_index("ix_knowledge_generation_items_lineage", table_name="knowledge_generation_items")
    op.drop_index(
        "ix_knowledge_generation_items_run_state", table_name="knowledge_generation_items"
    )
    op.drop_table("knowledge_generation_items")
    op.drop_index(
        "ix_knowledge_generation_target_snapshot_created",
        table_name="knowledge_generation_target_snapshots",
    )
    op.drop_table("knowledge_generation_target_snapshots")
    op.drop_index("ix_generation_receipts_run", table_name="knowledge_generation_source_receipts")
    op.drop_table("knowledge_generation_source_receipts")
    op.drop_index("uq_knowledge_assets_set_lineage", table_name="knowledge_assets")
    op.drop_column("knowledge_assets", "generation_lineage_key")
