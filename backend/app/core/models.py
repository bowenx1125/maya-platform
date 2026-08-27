"""SQLAlchemy models for the identity, organization and Wave 1A/1B domains.

Voice resources deliberately keep supplier identifiers and provider metadata
inside the server-side database model.  The API projections in
``app.modules.voices`` never expose those columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative metadata for the checked-in Wave 1A migration head."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    sessions: Mapped[list[SessionRecord]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    course_memberships: Mapped[list[CourseMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    group_memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_users_status", "status"),)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    # Debate is a later-wave table; this pointer intentionally has no FK in
    # the minimal migration and is managed by the later domain migration.
    current_audio_debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    memberships: Mapped[list[CourseMember]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )
    groups: Mapped[list[Group]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_courses_code", "code", unique=True),)


class CourseMember(Base):
    __tablename__ = "course_members"

    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course: Mapped[Course] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="course_memberships")

    __table_args__ = (
        CheckConstraint("role IN ('teacher', 'student')", name="ck_course_members_role"),
        Index("ix_course_members_user_id", "user_id"),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course: Mapped[Course] = relationship(back_populates="groups")
    memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_groups_course_name"),
        Index("ix_groups_course_id", "course_id"),
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="group_memberships")

    __table_args__ = (
        CheckConstraint("role IN ('leader', 'admin', 'member')", name="ck_group_members_role"),
        Index("ix_group_members_user_id", "user_id"),
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # This pointer is deliberately validated by the service against the same
    # agent and a published state.  A direct FK would create a migration cycle
    # with agent_versions on SQLite.
    current_published_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group] = relationship()
    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentVersion.version_seq"
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_agents_status"),
        Index("ix_agents_group_id", "group_id"),
        Index("ix_agents_group_status", "group_id", "status"),
    )


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    knowledge_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="versions")
    documents: Mapped[list[AgentVersionDocument]] = relationship(
        back_populates="agent_version",
        cascade="all, delete-orphan",
        order_by="AgentVersionDocument.order_index",
    )

    __table_args__ = (
        CheckConstraint("version_seq >= 0", name="ck_agent_versions_seq_nonnegative"),
        CheckConstraint("revision >= 0", name="ck_agent_versions_revision_nonnegative"),
        CheckConstraint(
            "state IN ('draft', 'published', 'superseded')", name="ck_agent_versions_state"
        ),
        UniqueConstraint("agent_id", "version_seq", name="uq_agent_versions_agent_seq"),
        Index("ix_agent_versions_agent_state", "agent_id", "state"),
        Index(
            "uq_agent_versions_one_draft",
            "agent_id",
            unique=True,
            sqlite_where=(state == "draft"),
        ),
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    index_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    index_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workspace_state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group] = relationship()
    stored_file: Mapped[StoredFile] = relationship()
    chunks: Mapped[list[KnowledgeDocumentChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeDocumentChunk.chunk_index",
    )
    agent_versions: Mapped[list[AgentVersionDocument]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("char_count >= 1", name="ck_knowledge_documents_char_count"),
        CheckConstraint("index_revision >= 0", name="ck_knowledge_documents_index_revision"),
        CheckConstraint(
            "index_status IN ('pending', 'indexing', 'ready', 'failed')",
            name="ck_knowledge_documents_index_status",
        ),
        CheckConstraint(
            "workspace_state IN ('active', 'hidden')", name="ck_knowledge_documents_workspace_state"
        ),
        Index("ix_knowledge_documents_group_state", "group_id", "workspace_state"),
    )


class KnowledgeDocumentChunk(Base):
    __tablename__ = "knowledge_document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column("text", Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_key: Mapped[str] = mapped_column(String(80), nullable=False)

    @property
    def text(self) -> str:
        return self.chunk_text

    @text.setter
    def text(self, value: str) -> None:
        self.chunk_text = value

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_document_chunks_order"),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_document_chunks_index"),
        CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_knowledge_document_chunks_offsets",
        ),
        Index("ix_knowledge_document_chunks_document", "document_id"),
    )


class AgentVersionDocument(Base):
    __tablename__ = "agent_version_documents"

    agent_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    agent_version: Mapped[AgentVersion] = relationship(back_populates="documents")
    document: Mapped[KnowledgeDocument] = relationship(back_populates="agent_versions")

    __table_args__ = (
        CheckConstraint("order_index >= 0", name="ck_agent_version_documents_order"),
        Index(
            "uq_agent_version_documents_enabled_order",
            "agent_version_id",
            "order_index",
            unique=True,
            sqlite_where=(enabled.is_(True)),
        ),
        Index("ix_agent_version_documents_document", "document_id"),
    )


class KnowledgeSnapshot(Base):
    __tablename__ = "knowledge_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stored_file_id: Mapped[str] = mapped_column(
        "combined_file_id",
        String(36),
        ForeignKey("stored_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    total_char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_key: Mapped[str] = mapped_column("embedding_model_key", String(80), nullable=False)
    chunking_json: Mapped[str] = mapped_column("chunking_config_json", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    agent_version: Mapped[AgentVersion] = relationship()
    stored_file: Mapped[StoredFile] = relationship()
    documents: Mapped[list[SnapshotDocument]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="SnapshotDocument.order_index",
    )
    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
    )

    __table_args__ = (
        CheckConstraint(
            "total_char_count >= 1 AND total_char_count <= 100000",
            name="ck_knowledge_snapshots_total_chars",
        ),
        UniqueConstraint("agent_version_id", name="uq_knowledge_snapshots_agent_version"),
    )

    @property
    def combined_file_id(self) -> str:
        return self.stored_file_id

    @combined_file_id.setter
    def combined_file_id(self, value: str) -> None:
        self.stored_file_id = value

    @property
    def embedding_model_key(self) -> str:
        return self.embedding_key

    @embedding_model_key.setter
    def embedding_model_key(self, value: str) -> None:
        self.embedding_key = value

    @property
    def chunking_config_json(self) -> str:
        return self.chunking_json

    @chunking_config_json.setter
    def chunking_config_json(self, value: str) -> None:
        self.chunking_json = value


class SnapshotDocument(Base):
    __tablename__ = "snapshot_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), nullable=False
    )
    stored_file_id: Mapped[str] = mapped_column(
        "frozen_file_id",
        String(36),
        ForeignKey("stored_files.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    snapshot: Mapped[KnowledgeSnapshot] = relationship(back_populates="documents")

    @property
    def frozen_file_id(self) -> str:
        return self.stored_file_id

    @frozen_file_id.setter
    def frozen_file_id(self, value: str) -> None:
        self.stored_file_id = value

    __table_args__ = (
        UniqueConstraint("snapshot_id", "document_id", name="uq_snapshot_documents_source"),
        UniqueConstraint("snapshot_id", "order_index", name="uq_snapshot_documents_order"),
        # SQLite composite foreign keys require an explicitly unique parent
        # key.  Keep this as an index (rather than another UniqueConstraint)
        # so the two public uniqueness constraints above remain stable while
        # chunks can prove they belong to the same snapshot/document pair.
        Index(
            "uq_snapshot_documents_identity",
            "id",
            "snapshot_id",
            "document_id",
            unique=True,
        ),
        CheckConstraint("order_index >= 0", name="ck_snapshot_documents_order"),
        Index("ix_snapshot_documents_snapshot", "snapshot_id"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("snapshot_documents.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="RESTRICT"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column("text", Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_key: Mapped[str] = mapped_column(String(80), nullable=False)

    @property
    def text(self) -> str:
        return self.chunk_text

    @text.setter
    def text(self, value: str) -> None:
        self.chunk_text = value

    snapshot: Mapped[KnowledgeSnapshot] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "snapshot_document_id",
            "chunk_index",
            name="uq_knowledge_chunks_order",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_index"),
        CheckConstraint(
            "start_offset >= 0 AND end_offset >= start_offset",
            name="ck_knowledge_chunks_offsets",
        ),
        # In addition to the individual IDs, this composite relationship
        # prevents a chunk from joining a snapshot document from another
        # snapshot or source document.
        ForeignKeyConstraint(
            ["snapshot_document_id", "snapshot_id", "document_id"],
            [
                "snapshot_documents.id",
                "snapshot_documents.snapshot_id",
                "snapshot_documents.document_id",
            ],
            ondelete="CASCADE",
            name="fk_knowledge_chunks_snapshot_source",
        ),
        Index("ix_knowledge_chunks_snapshot", "snapshot_id"),
    )


class StoredFile(Base):
    __tablename__ = "stored_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="markdown")
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column("size", Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="staged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def size(self) -> int:
        return self.size_bytes

    @size.setter
    def size(self, value: int) -> None:
        self.size_bytes = value

    __table_args__ = (
        CheckConstraint(
            "state IN ('staged', 'active', 'trash', 'deleted')",
            name="ck_stored_files_state",
        ),
        CheckConstraint("size >= 0", name="ck_stored_files_size"),
    )


class FileReference(Base):
    __tablename__ = "file_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_file_references_owner", "owner_type", "owner_id"),)


class FileOperation(Base):
    __tablename__ = "file_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_record_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("idempotency_records.id", ondelete="SET NULL"), nullable=True
    )
    operation_kind: Mapped[str] = mapped_column("operation_type", String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_relative_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_relative_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Wave 2 audio replacement journal metadata.  These columns deliberately
    # remain nullable so the Wave 0/1 upload and snapshot journals keep their
    # existing shape; ``debate_audio_swap`` rows fill the old pointer,
    # staging path and new Debate identity before any filesystem rename.
    old_audio_debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    staging_relative_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    new_debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expected_old_debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared")
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def operation_type(self) -> str:
        return self.operation_kind

    @operation_type.setter
    def operation_type(self, value: str) -> None:
        self.operation_kind = value

    __table_args__ = (
        CheckConstraint(
            "state IN ('prepared', 'staged', 'promoted', 'committed', "
            "'cleanup_required', 'recovered')",
            name="ck_file_operations_state",
        ),
        Index("ix_file_operations_state", "state"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=True
    )
    # Debate work is added in Wave 2 without changing existing knowledge and
    # voice job callers.  The migration adds the matching foreign keys after
    # the Debate tables exist; keeping the ORM columns nullable preserves
    # ``create_all`` for the earlier isolated Wave 1 test databases.
    debate_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancellation_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'running', 'completed', 'failed', 'interrupted')",
            name="ck_jobs_state",
        ),
        Index("ix_jobs_document", "document_id"),
        Index("ix_jobs_debate", "debate_id"),
        Index("ix_jobs_turn", "turn_id"),
        Index(
            "uq_jobs_operation_idempotency_key",
            "operation",
            "idempotency_key",
            unique=True,
            sqlite_where=idempotency_key.is_not(None),
        ),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    claim_token: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "actor_user_id",
            "operation",
            "key",
            name="uq_idempotency_actor_operation_key",
        ),
        CheckConstraint(
            "state IN ('pending', 'completed', 'abandoned')",
            name="ck_idempotency_state",
        ),
        Index("ix_idempotency_lease", "lease_expires_at"),
    )


class VoiceProfile(Base):
    """A platform voice mapping, scoped either to a group or the system.

    ``external_id_encrypted`` is an AEAD envelope, never a supplier voice ID
    in plaintext.  ``recovery_name`` is a deterministic, non-secret name used
    only by the server when reconciling an ambiguous provider operation.
    """

    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="RESTRICT", name="fk_voice_profiles_group"),
        nullable=True,
    )
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="validating")
    provider_key: Mapped[str] = mapped_column(String(32), nullable=False)
    target_model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    external_id_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    recovery_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_copy_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consent_actor_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_voice_profiles_consent_actor"),
        nullable=True,
    )
    consent_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group | None] = relationship()

    @property
    def external_id_envelope(self) -> bytes | None:
        """Compatibility name for code that calls the AEAD value an envelope."""

        return self.external_id_encrypted

    @external_id_envelope.setter
    def external_id_envelope(self, value: bytes | None) -> None:
        self.external_id_encrypted = value

    __table_args__ = (
        CheckConstraint("scope IN ('system', 'group')", name="ck_voice_profiles_scope"),
        CheckConstraint(
            "status IN ('validating', 'enrolling', 'preview_ready', 'ready', 'deleting', "
            "'outcome_unknown', 'failed', 'deleted')",
            name="ck_voice_profiles_status",
        ),
        CheckConstraint(
            "(scope = 'system' AND group_id IS NULL) OR (scope = 'group' AND group_id IS NOT NULL)",
            name="ck_voice_profiles_scope_group",
        ),
        Index("ix_voice_profiles_group_status", "group_id", "status"),
        Index(
            "uq_voice_profiles_one_system",
            "scope",
            unique=True,
            sqlite_where=(scope == "system"),
        ),
    )


class VoiceProviderOperation(Base):
    """Durable ledger for a potentially charged voice provider operation."""

    __tablename__ = "voice_provider_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "voice_profiles.id",
            ondelete="RESTRICT",
            name="fk_voice_provider_operations_profile",
        ),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(24), nullable=False)
    profile_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    claim_token: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charged_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "idempotency_records.id",
            ondelete="SET NULL",
            name="fk_voice_provider_operations_idempotency",
        ),
        nullable=True,
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    profile: Mapped[VoiceProfile] = relationship()

    @property
    def operation_kind(self) -> str:
        return self.operation_type

    @operation_kind.setter
    def operation_kind(self, value: str) -> None:
        self.operation_type = value

    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('enroll', 'delete', 'exists', 'tts_preview')",
            name="ck_voice_provider_operations_type",
        ),
        CheckConstraint(
            "profile_scope IN ('system', 'group')",
            name="ck_voice_provider_operations_scope",
        ),
        CheckConstraint(
            "state IN ('prepared', 'dispatched', 'reconciling', 'succeeded', 'failed', "
            "'outcome_unknown')",
            name="ck_voice_provider_operations_state",
        ),
        CheckConstraint("attempt >= 1", name="ck_voice_provider_operations_attempt"),
        CheckConstraint(
            "request_count >= 0 AND charged_request_count >= 0 AND input_bytes >= 0 "
            "AND output_bytes >= 0",
            name="ck_voice_provider_operations_counters",
        ),
        Index("ix_voice_provider_operations_profile", "profile_id", "operation_type"),
        Index("ix_voice_provider_operations_state_deadline", "state", "provider_deadline"),
        Index(
            "uq_voice_provider_operations_system_enroll_active",
            "profile_scope",
            "operation_type",
            unique=True,
            sqlite_where=(
                (profile_scope == "system")
                & (operation_type == "enroll")
                & state.in_(("prepared", "dispatched", "reconciling", "outcome_unknown"))
            ),
        ),
        Index(
            "uq_voice_provider_operations_profile_delete",
            "profile_id",
            unique=True,
            sqlite_where=(operation_type == "delete"),
        ),
    )


class VoicePreview(Base):
    """Short-lived, platform-owned preview resource."""

    __tablename__ = "voice_previews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("voice_profiles.id", ondelete="CASCADE", name="fk_voice_previews_profile"),
        nullable=False,
    )
    group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE", name="fk_voice_previews_group"),
        nullable=True,
    )
    stored_file_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("stored_files.id", ondelete="SET NULL", name="fk_voice_previews_stored_file"),
        nullable=True,
    )
    relative_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped[VoiceProfile] = relationship()
    stored_file: Mapped[StoredFile | None] = relationship()

    __table_args__ = (
        CheckConstraint(
            "state IN ('active', 'expired', 'confirmed', 'replaced')",
            name="ck_voice_previews_state",
        ),
        Index("ix_voice_previews_profile_state", "profile_id", "state"),
        Index("ix_voice_previews_expiry", "expires_at"),
    )


# Keep a small helper available to fingerprint/serialization code without
# exposing ORM internals in route modules.
def model_dict(instance: Any, *fields: str) -> dict[str, Any]:
    return {field: getattr(instance, field) for field in fields}
