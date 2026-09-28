"""Add one shared, versioned Knowledge Set store."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_knowledge_sets_assets"
down_revision: str | Sequence[str] | None = "0035_w1_resource_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # pysqlite defers the physical BEGIN behind SQLAlchemy's logical
        # transaction. Start a real SQLite writer transaction so DDL and
        # Alembic's following version_num update commit or roll back together.
        # The environment owns COMMIT/ROLLBACK after the full migration body.
        bind.exec_driver_sql("BEGIN IMMEDIATE")

    op.create_table(
        "knowledge_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("group_id", sa.String(36), nullable=True),
        sa.Column("ownership_scope", sa.String(16), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("metadata_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authorization_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ownership_scope IN ('group', 'personal')",
            name="ck_knowledge_sets_ownership_scope",
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_knowledge_sets_visibility",
        ),
        sa.CheckConstraint(
            "((ownership_scope = 'group' AND group_id IS NOT NULL) OR "
            "(ownership_scope = 'personal' AND group_id IS NULL))",
            name="ck_knowledge_sets_owner_scope",
        ),
        sa.CheckConstraint("length(trim(display_name)) > 0", name="ck_knowledge_sets_name"),
        sa.CheckConstraint(
            "metadata_revision >= 0 AND content_revision >= 0 AND authorization_epoch >= 0",
            name="ck_knowledge_sets_revisions",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_knowledge_sets_group_course",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_sets_course_owner",
        "knowledge_sets",
        ["course_id", "owner_user_id", "deleted_at"],
    )
    op.create_index(
        "ix_knowledge_sets_group_visibility",
        "knowledge_sets",
        ["group_id", "visibility", "deleted_at"],
    )

    op.create_table(
        "knowledge_set_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("knowledge_set_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("stored_file_id", sa.String(36), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("source_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("source_index_revision", sa.Integer(), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(source_content_hash) = 64", name="ck_knowledge_set_source_hash"),
        sa.CheckConstraint("length(source_file_sha256) = 64", name="ck_knowledge_set_file_hash"),
        sa.CheckConstraint(
            "source_authorization_epoch >= 0 AND source_index_revision >= 0 AND order_index >= 0",
            name="ck_knowledge_set_source_counters",
        ),
        sa.ForeignKeyConstraint(["knowledge_set_id"], ["knowledge_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("knowledge_set_id", "id", name="uq_knowledge_set_sources_set_id"),
    )
    op.create_index(
        "uq_knowledge_set_sources_active_document",
        "knowledge_set_sources",
        ["knowledge_set_id", "document_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
        postgresql_where=sa.text("is_active IS TRUE"),
    )
    op.create_index(
        "ix_knowledge_set_sources_set_active",
        "knowledge_set_sources",
        ["knowledge_set_id", "is_active", "order_index"],
    )

    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("knowledge_set_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("current_version_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('concept', 'question', 'note')",
            name="ck_knowledge_assets_kind",
        ),
        sa.CheckConstraint("current_version_seq >= 0", name="ck_knowledge_assets_version_seq"),
        sa.ForeignKeyConstraint(["knowledge_set_id"], ["knowledge_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "knowledge_set_id", name="uq_knowledge_assets_set_id"),
    )
    op.create_index(
        "ix_knowledge_assets_set_kind",
        "knowledge_assets",
        ["knowledge_set_id", "kind", "created_at"],
    )

    op.create_table(
        "knowledge_asset_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("version_seq", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_dependency_hash", sa.String(64), nullable=True),
        sa.Column("dependency_authorization_epoch", sa.Integer(), nullable=True),
        sa.Column("set_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("generator_agent_version_id", sa.String(36), nullable=True),
        sa.Column("generation_job_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_seq >= 1", name="ck_knowledge_asset_version_seq"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_asset_version_hash"),
        sa.CheckConstraint(
            "source_dependency_hash IS NULL OR length(source_dependency_hash) = 64",
            name="ck_knowledge_asset_dependency_hash",
        ),
        sa.CheckConstraint(
            "dependency_authorization_epoch IS NULL OR dependency_authorization_epoch >= 0",
            name="ck_knowledge_asset_dependency_epoch",
        ),
        sa.CheckConstraint("set_authorization_epoch >= 0", name="ck_knowledge_asset_set_epoch"),
        sa.CheckConstraint("origin IN ('manual', 'ai')", name="ck_knowledge_asset_origin"),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["generator_agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "version_seq", name="uq_knowledge_asset_version_seq"),
    )
    op.create_index(
        "ix_knowledge_asset_versions_asset",
        "knowledge_asset_versions",
        ["asset_id", "version_seq"],
    )

    op.create_table(
        "knowledge_asset_version_sources",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("source_binding_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("stored_file_id", sa.String(36), nullable=False),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("source_authorization_epoch", sa.Integer(), nullable=False),
        sa.Column("source_location_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_location_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(source_content_hash) = 64", name="ck_knowledge_asset_source_hash"
        ),
        sa.CheckConstraint(
            "length(source_file_sha256) = 64", name="ck_knowledge_asset_source_file_hash"
        ),
        sa.CheckConstraint(
            "source_authorization_epoch >= 0",
            name="ck_knowledge_asset_source_epoch",
        ),
        sa.CheckConstraint(
            "length(source_location_hash) = 64",
            name="ck_knowledge_asset_source_location_hash",
        ),
        sa.ForeignKeyConstraint(
            ["asset_version_id"], ["knowledge_asset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_binding_id"], ["knowledge_set_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_version_id",
            "source_binding_id",
            "source_location_hash",
            name="uq_knowledge_asset_version_source_location",
        ),
    )
    op.create_index(
        "ix_knowledge_asset_version_sources_version",
        "knowledge_asset_version_sources",
        ["asset_version_id"],
    )

    op.create_table(
        "agent_knowledge_sets",
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("knowledge_set_id", sa.String(36), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_agent_knowledge_sets_order"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_set_id"], ["knowledge_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_id", "knowledge_set_id"),
        sa.UniqueConstraint("agent_id", "order_index", name="uq_agent_knowledge_sets_order"),
    )
    op.create_index(
        "ix_agent_knowledge_sets_set",
        "agent_knowledge_sets",
        ["knowledge_set_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("BEGIN IMMEDIATE")
    tables = (
        "agent_knowledge_sets",
        "knowledge_asset_version_sources",
        "knowledge_asset_versions",
        "knowledge_assets",
        "knowledge_set_sources",
        "knowledge_sets",
    )
    populated = [
        table
        for table in tables
        if bind.exec_driver_sql(f'SELECT 1 FROM "{table}" LIMIT 1').first() is not None
    ]
    if populated:
        raise RuntimeError(
            "Knowledge Set data exists; downgrade would discard user content in: "
            + ", ".join(populated)
        )
    op.drop_index("ix_agent_knowledge_sets_set", table_name="agent_knowledge_sets")
    op.drop_table("agent_knowledge_sets")
    op.drop_index(
        "ix_knowledge_asset_version_sources_version",
        table_name="knowledge_asset_version_sources",
    )
    op.drop_table("knowledge_asset_version_sources")
    op.drop_index("ix_knowledge_asset_versions_asset", table_name="knowledge_asset_versions")
    op.drop_table("knowledge_asset_versions")
    op.drop_index("ix_knowledge_assets_set_kind", table_name="knowledge_assets")
    op.drop_table("knowledge_assets")
    op.drop_index("ix_knowledge_set_sources_set_active", table_name="knowledge_set_sources")
    op.drop_index("uq_knowledge_set_sources_active_document", table_name="knowledge_set_sources")
    op.drop_table("knowledge_set_sources")
    op.drop_index("ix_knowledge_sets_group_visibility", table_name="knowledge_sets")
    op.drop_index("ix_knowledge_sets_course_owner", table_name="knowledge_sets")
    op.drop_table("knowledge_sets")
