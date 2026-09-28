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
