"""Wave 1A agents, Markdown knowledge and immutable snapshot tables.

Revision ID: 0002_wave1_agents_rag
Revises: 0001_wave0_baseline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_wave1_agents_rag"
down_revision = "0001_wave0_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("current_published_version_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_agents_status"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agents_group_id", "agents", ["group_id"], unique=False)
    op.create_index("ix_agents_group_status", "agents", ["group_id", "status"], unique=False)

    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("version_seq", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agent_md", sa.Text, nullable=False, server_default=""),
        sa.Column("avatar_config_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("voice_profile_id", sa.String(36), nullable=True),
        sa.Column("knowledge_snapshot_id", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_seq >= 0", name="ck_agent_versions_seq_nonnegative"),
        sa.CheckConstraint("revision >= 0", name="ck_agent_versions_revision_nonnegative"),
        sa.CheckConstraint(
            "state IN ('draft', 'published', 'superseded')", name="ck_agent_versions_state"
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "version_seq", name="uq_agent_versions_agent_seq"),
    )
    op.create_index("ix_agent_versions_agent_state", "agent_versions", ["agent_id", "state"])
    op.create_index(
        "uq_agent_versions_one_draft",
        "agent_versions",
        ["agent_id"],
        unique=True,
        sqlite_where=sa.text("state = 'draft'"),
    )

    op.create_table(
        "stored_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False, server_default="markdown"),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="staged"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('staged', 'active', 'trash', 'deleted')", name="ck_stored_files_state"
        ),
        sa.CheckConstraint("size >= 0", name="ck_stored_files_size"),
        sa.UniqueConstraint("relative_path", name="uq_stored_files_relative_path"),
    )

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("stored_file_id", sa.String(36), nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False),
        sa.Column("index_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("index_revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("workspace_state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("char_count >= 1", name="ck_knowledge_documents_char_count"),
        sa.CheckConstraint("index_revision >= 0", name="ck_knowledge_documents_index_revision"),
        sa.CheckConstraint(
            "index_status IN ('pending', 'indexing', 'ready', 'failed')",
            name="ck_knowledge_documents_index_status",
        ),
        sa.CheckConstraint(
            "workspace_state IN ('active', 'hidden')", name="ck_knowledge_documents_workspace_state"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_knowledge_documents_group_state", "knowledge_documents", ["group_id", "workspace_state"]
    )

    op.create_table(
        "knowledge_document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("start_offset", sa.Integer, nullable=False),
        sa.Column("end_offset", sa.Integer, nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary, nullable=False),
        sa.Column("embedding_dimension", sa.Integer, nullable=False),
        sa.Column("embedding_key", sa.String(80), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_knowledge_document_chunks_index"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_knowledge_document_chunks_offsets",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_knowledge_document_chunks_order"
        ),
    )
    op.create_index(
        "ix_knowledge_document_chunks_document", "knowledge_document_chunks", ["document_id"]
    )

    op.create_table(
        "agent_version_documents",
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_agent_version_documents_order"),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_version_id", "document_id"),
    )
    op.create_index(
        "uq_agent_version_documents_enabled_order",
        "agent_version_documents",
        ["agent_version_id", "order_index"],
        unique=True,
        sqlite_where=sa.text("enabled = 1"),
    )
    op.create_index(
        "ix_agent_version_documents_document", "agent_version_documents", ["document_id"]
    )

    op.create_table(
        "knowledge_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_version_id", sa.String(36), nullable=False),
        sa.Column("combined_file_id", sa.String(36), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("total_char_count", sa.Integer, nullable=False),
        sa.Column("embedding_model_key", sa.String(80), nullable=False),
        sa.Column("chunking_config_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "total_char_count >= 1 AND total_char_count <= 100000",
            name="ck_knowledge_snapshots_total_chars",
        ),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["combined_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("agent_version_id", name="uq_knowledge_snapshots_agent_version"),
    )

    op.create_table(
        "snapshot_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("frozen_file_id", sa.String(36), nullable=False),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("char_count", sa.Integer, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False),
        sa.CheckConstraint("order_index >= 0", name="ck_snapshot_documents_order"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["knowledge_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["frozen_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("snapshot_id", "document_id", name="uq_snapshot_documents_source"),
        sa.UniqueConstraint("snapshot_id", "order_index", name="uq_snapshot_documents_order"),
    )
    # A unique index gives SQLite a parent key for the composite chunk FK
    # without changing the two frozen public uniqueness constraints.
    op.create_index(
        "uq_snapshot_documents_identity",
        "snapshot_documents",
        ["id", "snapshot_id", "document_id"],
        unique=True,
    )
    op.create_index("ix_snapshot_documents_snapshot", "snapshot_documents", ["snapshot_id"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("snapshot_document_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("start_offset", sa.Integer, nullable=False),
        sa.Column("end_offset", sa.Integer, nullable=False),
        sa.Column("embedding_blob", sa.LargeBinary, nullable=False),
        sa.Column("embedding_dimension", sa.Integer, nullable=False),
        sa.Column("embedding_key", sa.String(80), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index"),
        sa.CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_knowledge_chunks_offsets",
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["knowledge_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_document_id"], ["snapshot_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["snapshot_document_id", "snapshot_id", "document_id"],
            [
                "snapshot_documents.id",
                "snapshot_documents.snapshot_id",
                "snapshot_documents.document_id",
            ],
            ondelete="CASCADE",
            name="fk_knowledge_chunks_snapshot_source",
        ),
        sa.UniqueConstraint(
            "snapshot_id", "snapshot_document_id", "chunk_index", name="uq_knowledge_chunks_order"
        ),
    )
    op.create_index("ix_knowledge_chunks_snapshot", "knowledge_chunks", ["snapshot_id"])

    op.create_table(
        "file_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("stored_file_id", sa.String(36), nullable=False),
        sa.Column("owner_type", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_file_references_owner", "file_references", ["owner_type", "owner_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("claim_token", sa.String(64), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("response_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'completed', 'abandoned')", name="ck_idempotency_state"
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "actor_user_id",
            "operation",
            "key",
            name="uq_idempotency_actor_operation_key",
        ),
    )
    op.create_index("ix_idempotency_lease", "idempotency_records", ["lease_expires_at"])

    op.create_table(
        "file_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_record_id", sa.String(36), nullable=True),
        sa.Column("operation_type", sa.String(60), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("source_relative_path", sa.String(500), nullable=True),
        sa.Column("target_relative_path", sa.String(500), nullable=True),
        sa.Column("expected_sha256", sa.String(64), nullable=True),
        sa.Column("state", sa.String(24), nullable=False, server_default="prepared"),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('prepared', 'staged', 'promoted', 'committed', "
            "'cleanup_required', 'recovered')",
            name="ck_file_operations_state",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_record_id"], ["idempotency_records.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_file_operations_state", "file_operations", ["state"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("safe_error_code", sa.String(64), nullable=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'completed', 'failed', 'interrupted')",
            name="ck_jobs_state",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_jobs_document", "jobs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_document", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_file_operations_state", table_name="file_operations")
    op.drop_table("file_operations")
    op.drop_index("ix_idempotency_lease", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_file_references_owner", table_name="file_references")
    op.drop_table("file_references")
    op.drop_index("ix_knowledge_chunks_snapshot", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_snapshot_documents_snapshot", table_name="snapshot_documents")
    op.drop_index("uq_snapshot_documents_identity", table_name="snapshot_documents")
    op.drop_table("snapshot_documents")
    op.drop_table("knowledge_snapshots")
    op.drop_index("ix_agent_version_documents_document", table_name="agent_version_documents")
    op.drop_index("uq_agent_version_documents_enabled_order", table_name="agent_version_documents")
    op.drop_table("agent_version_documents")
    op.drop_index("ix_knowledge_document_chunks_document", table_name="knowledge_document_chunks")
    op.drop_table("knowledge_document_chunks")
    op.drop_index("ix_knowledge_documents_group_state", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_table("stored_files")
    op.drop_index("ix_agent_versions_agent_state", table_name="agent_versions")
    op.drop_index("uq_agent_versions_one_draft", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index("ix_agents_group_status", table_name="agents")
    op.drop_index("ix_agents_group_id", table_name="agents")
    op.drop_table("agents")
