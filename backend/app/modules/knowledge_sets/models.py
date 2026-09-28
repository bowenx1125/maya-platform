"""Persistence models for manual, versioned Knowledge Sets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base


class KnowledgeSet(Base):
    __tablename__ = "knowledge_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ownership_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "ownership_scope IN ('group', 'personal')",
            name="ck_knowledge_sets_ownership_scope",
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_knowledge_sets_visibility",
        ),
        CheckConstraint(
            "((ownership_scope = 'group' AND group_id IS NOT NULL) OR "
            "(ownership_scope = 'personal' AND group_id IS NULL))",
            name="ck_knowledge_sets_owner_scope",
        ),
        CheckConstraint("length(trim(display_name)) > 0", name="ck_knowledge_sets_name"),
        CheckConstraint(
            "metadata_revision >= 0 AND content_revision >= 0 AND authorization_epoch >= 0",
            name="ck_knowledge_sets_revisions",
        ),
        ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_knowledge_sets_group_course",
            ondelete="CASCADE",
        ),
        Index("ix_knowledge_sets_course_owner", "course_id", "owner_user_id", "deleted_at"),
        Index("ix_knowledge_sets_group_visibility", "group_id", "visibility", "deleted_at"),
    )


class KnowledgeSetSource(Base):
    __tablename__ = "knowledge_set_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sets.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), nullable=False
    )
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_index_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("knowledge_set_id", "id", name="uq_knowledge_set_sources_set_id"),
        CheckConstraint("length(source_content_hash) = 64", name="ck_knowledge_set_source_hash"),
        CheckConstraint("length(source_file_sha256) = 64", name="ck_knowledge_set_file_hash"),
        CheckConstraint(
            "source_authorization_epoch >= 0 AND source_index_revision >= 0 AND order_index >= 0",
            name="ck_knowledge_set_source_counters",
        ),
        Index(
            "uq_knowledge_set_sources_active_document",
            "knowledge_set_id",
            "document_id",
            unique=True,
            sqlite_where=(is_active.is_(True)),
            postgresql_where=(is_active.is_(True)),
        ),
        Index(
            "ix_knowledge_set_sources_set_active", "knowledge_set_id", "is_active", "order_index"
        ),
    )


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sets.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    generation_lineage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_version_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('concept', 'question', 'note')",
            name="ck_knowledge_assets_kind",
        ),
        CheckConstraint("current_version_seq >= 0", name="ck_knowledge_assets_version_seq"),
        UniqueConstraint("id", "knowledge_set_id", name="uq_knowledge_assets_set_id"),
        Index("ix_knowledge_assets_set_kind", "knowledge_set_id", "kind", "created_at"),
        Index(
            "uq_knowledge_assets_set_lineage",
            "knowledge_set_id",
            "generation_lineage_key",
            unique=True,
            sqlite_where=(generation_lineage_key.is_not(None)),
            postgresql_where=(generation_lineage_key.is_not(None)),
        ),
    )


class KnowledgeAssetVersion(Base):
    __tablename__ = "knowledge_asset_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_assets.id", ondelete="CASCADE"), nullable=False
    )
    version_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_dependency_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dependency_authorization_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    set_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    generator_agent_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=True
    )
    generation_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("asset_id", "version_seq", name="uq_knowledge_asset_version_seq"),
        CheckConstraint("version_seq >= 1", name="ck_knowledge_asset_version_seq"),
        CheckConstraint("length(content_hash) = 64", name="ck_knowledge_asset_version_hash"),
        CheckConstraint(
            "source_dependency_hash IS NULL OR length(source_dependency_hash) = 64",
            name="ck_knowledge_asset_dependency_hash",
        ),
        CheckConstraint(
            "dependency_authorization_epoch IS NULL OR dependency_authorization_epoch >= 0",
            name="ck_knowledge_asset_dependency_epoch",
        ),
        CheckConstraint(
            "set_authorization_epoch >= 0",
            name="ck_knowledge_asset_set_epoch",
        ),
        CheckConstraint("origin IN ('manual', 'ai')", name="ck_knowledge_asset_origin"),
        Index("ix_knowledge_asset_versions_asset", "asset_id", "version_seq"),
    )


class KnowledgeAssetVersionSource(Base):
    __tablename__ = "knowledge_asset_version_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_asset_versions.id", ondelete="CASCADE"), nullable=False
    )
    source_binding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_set_sources.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), nullable=False
    )
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_location_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_location_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "asset_version_id",
            "source_binding_id",
            "source_location_hash",
            name="uq_knowledge_asset_version_source_location",
        ),
        CheckConstraint("length(source_content_hash) = 64", name="ck_knowledge_asset_source_hash"),
        CheckConstraint(
            "length(source_file_sha256) = 64", name="ck_knowledge_asset_source_file_hash"
        ),
        CheckConstraint(
            "source_authorization_epoch >= 0",
            name="ck_knowledge_asset_source_epoch",
        ),
        CheckConstraint(
            "length(source_location_hash) = 64",
            name="ck_knowledge_asset_source_location_hash",
        ),
        Index("ix_knowledge_asset_version_sources_version", "asset_version_id"),
    )


class AgentKnowledgeSet(Base):
    __tablename__ = "agent_knowledge_sets"

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    knowledge_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sets.id", ondelete="RESTRICT"), primary_key=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("order_index >= 0", name="ck_agent_knowledge_sets_order"),
        UniqueConstraint("agent_id", "order_index", name="uq_agent_knowledge_sets_order"),
        Index("ix_agent_knowledge_sets_set", "knowledge_set_id"),
    )


class KnowledgeGenerationRun(Base):
    """Durable, permission-fenced intent to prepare one Agent's Knowledge."""

    __tablename__ = "knowledge_generation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    input_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    agent_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    knowledge_set_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_sets.id", ondelete="RESTRICT"), nullable=False
    )
    provider_operation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("provider_operations.id", ondelete="RESTRICT"), nullable=True
    )
    provider_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_md_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    set_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("length(input_key) = 64", name="ck_knowledge_generation_input_key"),
        CheckConstraint("length(agent_md_hash) = 64", name="ck_knowledge_generation_agent_hash"),
        CheckConstraint(
            "request_hash IS NULL OR length(request_hash) = 64",
            name="ck_knowledge_generation_request_hash",
        ),
        CheckConstraint(
            "agent_authorization_epoch >= 0 AND set_authorization_epoch >= 0",
            name="ck_knowledge_generation_epochs",
        ),
        CheckConstraint(
            "length(source_manifest_hash) = 64",
            name="ck_knowledge_generation_source_hash",
        ),
        CheckConstraint(
            "state IN ('pending', 'running', 'blocked', 'completed', 'failed', 'interrupted')",
            name="ck_knowledge_generation_state",
        ),
        Index("ix_knowledge_generation_owner_created", "owner_user_id", "created_at"),
        Index("ix_knowledge_generation_state_lease", "state", "lease_expires_at"),
        Index("ix_knowledge_generation_agent", "agent_id", "created_at"),
    )


class KnowledgeGenerationTargetSnapshot(Base):
    """Immutable generated-Asset heads captured when a run is created."""

    __tablename__ = "knowledge_generation_target_snapshots"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_generation_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    asset_heads_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(asset_heads_json) > 0",
            name="ck_knowledge_generation_target_snapshot_json",
        ),
        Index("ix_knowledge_generation_target_snapshot_created", "created_at"),
    )


class KnowledgeGenerationAcceptedStage(Base):
    """Sanitized canonical provider output bound to one generation operation.

    The supplier envelope and credentials are never stored. A null stage body
    represents a charged response whose content was suppressed after an
    authorization fence changed while the request was in flight.
    """

    __tablename__ = "knowledge_generation_accepted_stages"

    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_generation_runs.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    operation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("provider_operations.id", ondelete="RESTRICT"), nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_stage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_stage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_knowledge_generation_stage_operation"),
        CheckConstraint("length(request_hash) = 64", name="ck_knowledge_generation_stage_request"),
        CheckConstraint(
            "length(manifest_hash) = 64",
            name="ck_knowledge_generation_stage_manifest",
        ),
        CheckConstraint("length(policy_hash) = 64", name="ck_knowledge_generation_stage_policy"),
        CheckConstraint("length(schema_hash) = 64", name="ck_knowledge_generation_stage_schema"),
        CheckConstraint(
            "length(canonical_stage_hash) = 64",
            name="ck_knowledge_generation_stage_hash",
        ),
        CheckConstraint("item_count >= 0", name="ck_knowledge_generation_stage_item_count"),
        CheckConstraint(
            "(canonical_stage_json IS NULL AND item_count = 0 AND safe_error_code IS NOT NULL) "
            "OR (canonical_stage_json IS NOT NULL AND safe_error_code IS NULL)",
            name="ck_knowledge_generation_stage_suppression",
        ),
        Index("ix_knowledge_generation_stage_operation", "operation_id"),
    )


class KnowledgeGenerationSourceReceipt(Base):
    """Opaque run-scoped handles for authorized, immutable source bindings."""

    __tablename__ = "knowledge_generation_source_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_generation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_binding_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_set_sources.id", ondelete="RESTRICT"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), nullable=False
    )
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source_index_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "source_binding_id", name="uq_generation_receipt_binding"),
        CheckConstraint(
            "length(source_content_hash) = 64",
            name="ck_generation_receipt_content_hash",
        ),
        CheckConstraint(
            "length(source_file_sha256) = 64",
            name="ck_generation_receipt_file_hash",
        ),
        CheckConstraint(
            "source_authorization_epoch >= 0 AND source_index_revision >= 0",
            name="ck_generation_receipt_counters",
        ),
        Index("ix_generation_receipts_run", "run_id", "created_at"),
    )


class KnowledgeGenerationItem(Base):
    """Per-candidate materialization journal for an accepted Provider stage."""

    __tablename__ = "knowledge_generation_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_generation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    lineage_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    candidate_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_receipt_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    citation_unverified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_assets.id", ondelete="RESTRICT"), nullable=True
    )
    asset_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_asset_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    expected_asset_version_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "item_key", name="uq_knowledge_generation_item_key"),
        UniqueConstraint("run_id", "item_index", name="uq_knowledge_generation_item_index"),
        UniqueConstraint("asset_version_id", name="uq_knowledge_generation_item_version"),
        CheckConstraint("length(stage_hash) = 64", name="ck_knowledge_generation_item_stage"),
        CheckConstraint("length(item_key) = 64", name="ck_knowledge_generation_item_key"),
        CheckConstraint("item_index >= 0", name="ck_knowledge_generation_item_index"),
        CheckConstraint(
            "kind IN ('concept', 'question', 'note', 'invalid')",
            name="ck_knowledge_generation_item_kind",
        ),
        CheckConstraint(
            "lineage_key IS NULL OR length(lineage_key) = 64",
            name="ck_knowledge_generation_item_lineage",
        ),
        CheckConstraint("length(candidate_hash) = 64", name="ck_knowledge_generation_item_hash"),
        CheckConstraint(
            "citation_unverified_count >= 0",
            name="ck_knowledge_generation_item_citation_count",
        ),
        CheckConstraint(
            "state IN ('pending', 'applied', 'failed', 'skipped')",
            name="ck_knowledge_generation_item_state",
        ),
        CheckConstraint(
            "expected_asset_version_seq IS NULL OR expected_asset_version_seq >= 1",
            name="ck_knowledge_generation_item_expected_seq",
        ),
        CheckConstraint(
            "(state = 'applied' AND asset_id IS NOT NULL AND asset_version_id IS NOT NULL) OR "
            "(state != 'applied' AND asset_version_id IS NULL)",
            name="ck_knowledge_generation_item_applied_version",
        ),
        Index("ix_knowledge_generation_items_run_state", "run_id", "state", "item_index"),
        Index("ix_knowledge_generation_items_lineage", "lineage_key", "updated_at"),
    )
