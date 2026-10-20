"""SQLAlchemy models for the identity, organization and Wave 1A/1B domains.

Voice resources deliberately keep supplier identifiers and provider metadata
inside the server-side database model.  The API projections in
``app.modules.voices`` never expose those columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from app.core.identity import group_name_key, username_key
from app.core.sqlutil import portable_sql


def _course_id_from_group(context: object) -> str | None:
    parameters = context.get_current_parameters()  # type: ignore[attr-defined]
    group_id = parameters.get("group_id")
    if not group_id:
        return None
    result = context.connection.execute(  # type: ignore[attr-defined]
        sql_text("SELECT course_id FROM groups WHERE id = :g"), {"g": group_id}
    )
    return cast(str | None, result.scalar_one_or_none())


class Base(DeclarativeBase):
    """Declarative metadata for the checked-in Wave 1A migration head."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    username_key: Mapped[str] = mapped_column(String(240), nullable=False, server_default="")

    @validates("username")
    def _set_username(self, _key: str, value: str) -> str:
        self.username_key = username_key(value)
        return value

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(64), nullable=True)
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

    __table_args__ = (
        Index("ix_users_status", "status"),
        Index("uq_users_username_key", "username_key", unique=True),
    )


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
    name_key: Mapped[str] = mapped_column(String(400), nullable=False, server_default="")

    @validates("name")
    def _set_name(self, _key: str, value: str) -> str:
        self.name_key = group_name_key(value)
        return value

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    course: Mapped[Course] = relationship(back_populates="groups")
    memberships: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_groups_course_name"),
        Index("uq_groups_course_name_key", "course_id", "name_key", unique=True),
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


class TeacherGroupAccess(Base):
    __tablename__ = "teacher_group_access"

    group_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        default=_course_id_from_group,
    )
    ownership_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="group", server_default="group"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public", server_default="public"
    )
    authorization_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Description is mutable Agent metadata, deliberately separate from
    # AgentVersion.revision.  It is used only by the metadata PATCH CAS and
    # never copied into a frozen version/snapshot.
    metadata_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # This pointer is deliberately validated by the service against the same
    # agent and a published state.  A direct FK would create a migration cycle
    # with agent_versions on SQLite.
    current_published_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])
    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent", cascade="all, delete-orphan", order_by="AgentVersion.version_seq"
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_agents_status"),
        CheckConstraint("metadata_revision >= 0", name="ck_agents_metadata_revision_nonnegative"),
        CheckConstraint(
            "((ownership_scope = 'group' AND group_id IS NOT NULL) OR "
            "(ownership_scope = 'personal' AND group_id IS NULL AND owner_user_id IS NOT NULL))",
            name="ck_agents_owner_scope",
        ),
        CheckConstraint("visibility IN ('private', 'public')", name="ck_agents_visibility"),
        CheckConstraint(
            "owner_user_id IS NOT NULL OR (ownership_scope = 'group' AND visibility = 'public')",
            name="ck_agents_owner_visibility",
        ),
        CheckConstraint("authorization_epoch >= 0", name="ck_agents_authorization_epoch"),
        ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_agents_group_course",
            ondelete="CASCADE",
        ),
        Index("ix_agents_group_id", "group_id"),
        Index("ix_agents_group_status", "group_id", "status"),
        Index(
            "ix_agents_owner_course_scope",
            "owner_user_id",
            "course_id",
            "ownership_scope",
            "status",
        ),
        Index("ix_agents_course_visibility", "course_id", "visibility", "status"),
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
    # Wave 4 Persona is nullable for immutable legacy rows.  ``agent_md`` is
    # still the only raw authored source; these columns hold only its hash and
    # the extraction/confirmation result.
    raw_agent_md_hash: Mapped[str | None] = mapped_column(String(71), nullable=True)
    persona_spec_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona_spec_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona_compiler_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona_diagnostics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona_confirmation_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    student_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    persona_confirming_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Internal activation marker.  Existing published/superseded rows remain
    # false for historical read/Replay compatibility; every active draft path
    # sets this true so raw Markdown shape can never decide eligibility.
    persona_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    avatar_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    voice_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    knowledge_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    authorization_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # A draft that contains owner-only material stays owner-only until the
    # owner publishes a public immutable version. Visibility changes do not
    # refresh this sticky provenance marker.
    draft_visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    published_visibility: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default="public"
    )
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
        CheckConstraint("authorization_epoch >= 0", name="ck_agent_versions_authorization_epoch"),
        CheckConstraint(
            "((persona_spec_json IS NULL AND persona_spec_hash IS NULL "
            "AND persona_compiler_version IS NULL) OR "
            "(persona_spec_json IS NOT NULL AND persona_spec_hash IS NOT NULL "
            "AND persona_compiler_version IS NOT NULL))",
            name="ck_agent_versions_persona_compilation_fields",
        ),
        CheckConstraint(
            "((persona_confirmation_revision IS NULL AND student_confirmed_at IS NULL "
            "AND persona_confirming_user_id IS NULL) OR "
            "(persona_confirmation_revision IS NOT NULL AND student_confirmed_at IS NOT NULL "
            "AND persona_confirming_user_id IS NOT NULL))",
            name="ck_agent_versions_persona_confirmation_fields",
        ),
        CheckConstraint(
            "persona_confirmation_revision IS NULL OR persona_confirmation_revision = revision",
            name="ck_agent_versions_persona_confirmation_revision",
        ),
        CheckConstraint(
            "state IN ('draft', 'published', 'superseded')", name="ck_agent_versions_state"
        ),
        CheckConstraint(
            "published_visibility IS NULL OR published_visibility IN ('private', 'public')",
            name="ck_agent_versions_published_visibility",
        ),
        UniqueConstraint("agent_id", "version_seq", name="uq_agent_versions_agent_seq"),
        Index("ix_agent_versions_agent_state", "agent_id", "state"),
        Index(
            "uq_agent_versions_one_draft",
            "agent_id",
            unique=True,
            sqlite_where=(state == "draft"),
            postgresql_where=(state == "draft"),
        ),
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    course_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
        default=_course_id_from_group,
    )
    ownership_scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="group", server_default="group"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="public", server_default="public"
    )
    authorization_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_owner_role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="student", server_default="student"
    )
    stored_file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_version_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    index_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    index_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workspace_state: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    group: Mapped[Group | None] = relationship(foreign_keys=[group_id])
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
        CheckConstraint(
            "source_owner_role IN ('student', 'teacher')",
            name="ck_knowledge_documents_source_owner_role",
        ),
        CheckConstraint("char_count >= 1", name="ck_knowledge_documents_char_count"),
        CheckConstraint(
            "((ownership_scope = 'group' AND group_id IS NOT NULL) OR "
            "(ownership_scope = 'personal' AND group_id IS NULL AND owner_user_id IS NOT NULL))",
            name="ck_knowledge_documents_owner_scope",
        ),
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="ck_knowledge_documents_visibility",
        ),
        CheckConstraint(
            "owner_user_id IS NOT NULL OR (ownership_scope = 'group' AND visibility = 'public')",
            name="ck_knowledge_documents_owner_visibility",
        ),
        CheckConstraint(
            "authorization_epoch >= 0",
            name="ck_knowledge_documents_authorization_epoch",
        ),
        CheckConstraint("index_revision >= 0", name="ck_knowledge_documents_index_revision"),
        CheckConstraint(
            "content_version_seq >= 1", name="ck_knowledge_documents_content_version_seq"
        ),
        CheckConstraint(
            "index_status IN ('pending', 'indexing', 'ready', 'failed')",
            name="ck_knowledge_documents_index_status",
        ),
        CheckConstraint(
            "workspace_state IN ('active', 'hidden')", name="ck_knowledge_documents_workspace_state"
        ),
        ForeignKeyConstraint(
            ["group_id", "course_id"],
            ["groups.id", "groups.course_id"],
            name="fk_knowledge_documents_group_course",
            ondelete="CASCADE",
        ),
        Index("ix_knowledge_documents_group_state", "group_id", "workspace_state"),
        Index(
            "ix_knowledge_documents_owner_course_state",
            "owner_user_id",
            "course_id",
            "workspace_state",
        ),
        Index(
            "ix_knowledge_documents_course_visibility",
            "course_id",
            "visibility",
            "workspace_state",
        ),
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
        String(36), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), primary_key=True
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
            postgresql_where=(enabled.is_(True)),
        ),
        Index("ix_agent_version_documents_document", "document_id"),
    )


class KnowledgeSnapshot(Base):
    __tablename__ = "knowledge_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
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
    # Wave 4 makes the embedding identity explicit on the existing immutable
    # snapshot row.  The server defaults keep isolated pre-migration test
    # databases and legacy Mock writers safe; the 0013 migration backfills
    # historical rows and installs the closed identity check.
    embedding_provider: Mapped[str] = mapped_column(
        String(40), nullable=False, default="mock", server_default="mock"
    )
    embedding_region: Mapped[str] = mapped_column(
        String(40), nullable=False, default="local", server_default="local"
    )
    embedding_dimension: Mapped[int] = mapped_column(
        Integer, nullable=False, default=256, server_default="256"
    )
    embedding_policy_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="w4-mock-v1", server_default="w4-mock-v1"
    )
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
            "total_char_count >= 1",
            name="ck_knowledge_snapshots_total_chars",
        ),
        CheckConstraint(
            "(embedding_provider = 'mock' "
            "AND embedding_model_key = 'mock-sha256-v1' "
            "AND embedding_region = 'local' "
            "AND embedding_dimension = 256 "
            "AND embedding_policy_version = 'w4-mock-v1') "
            "OR (embedding_provider = 'dashscope' "
            "AND embedding_model_key = 'text-embedding-v4' "
            "AND embedding_region = 'cn-beijing' "
            "AND embedding_dimension = 1024 "
            "AND embedding_policy_version = 'w4-embed-v1')",
            name="ck_knowledge_snapshots_embedding_identity",
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

    @validates("embedding_key")
    def _normalize_legacy_mock_key(self, _key: str, value: str) -> str:
        """Map the pre-Wave-4 short Mock spelling to the frozen identity key."""

        return "mock-sha256-v1" if value == "mock" else value

    @property
    def embedding_model(self) -> str:
        """Short identity alias for the existing model-key column."""

        return self.embedding_key

    @embedding_model.setter
    def embedding_model(self, value: str) -> None:
        self.embedding_key = value

    @property
    def model(self) -> str:
        """Short identity alias for the existing model-key column."""

        return self.embedding_key

    @model.setter
    def model(self, value: str) -> None:
        self.embedding_key = value

    @property
    def provider(self) -> str:
        """Compatibility alias for identity-oriented callers."""

        return self.embedding_provider

    @provider.setter
    def provider(self, value: str) -> None:
        self.embedding_provider = value

    @property
    def region(self) -> str:
        """Compatibility alias for identity-oriented callers."""

        return self.embedding_region

    @region.setter
    def region(self, value: str) -> None:
        self.embedding_region = value

    @property
    def dimension(self) -> int:
        """Compatibility alias for identity-oriented callers."""

        return self.embedding_dimension

    @dimension.setter
    def dimension(self, value: int) -> None:
        self.embedding_dimension = value

    @property
    def policy_version(self) -> str:
        """Compatibility alias for identity-oriented callers."""

        return self.embedding_policy_version

    @policy_version.setter
    def policy_version(self, value: str) -> None:
        self.embedding_policy_version = value

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
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
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
    source_authorization_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

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
        CheckConstraint(
            "source_authorization_epoch >= 0",
            name="ck_snapshot_documents_source_authorization_epoch",
        ),
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
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_documents.id", ondelete="SET NULL"), nullable=True
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
    insight_snapshot_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "barrage_insight_snapshots.id",
            name="fk_jobs_insight_snapshot",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    report_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "civilization_report_revisions.id",
            name="fk_jobs_report_revision",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
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
        CheckConstraint(
            "(operation = 'barrage_insight.generate' AND insight_snapshot_id IS NOT NULL "
            "AND report_revision_id IS NULL) OR "
            "(operation = 'report.generate' AND insight_snapshot_id IS NULL "
            "AND report_revision_id IS NOT NULL) OR "
            "(operation NOT IN ('barrage_insight.generate', 'report.generate') "
            "AND insight_snapshot_id IS NULL AND report_revision_id IS NULL)",
            name="ck_jobs_wave3_typed_owner",
        ),
        Index("ix_jobs_document", "document_id"),
        Index("ix_jobs_debate", "debate_id"),
        Index("ix_jobs_turn", "turn_id"),
        Index(
            "uq_jobs_insight_snapshot",
            "insight_snapshot_id",
            unique=True,
            sqlite_where=insight_snapshot_id.is_not(None),
            postgresql_where=insight_snapshot_id.is_not(None),
        ),
        Index(
            "uq_jobs_report_revision",
            "report_revision_id",
            unique=True,
            sqlite_where=report_revision_id.is_not(None),
            postgresql_where=report_revision_id.is_not(None),
        ),
        Index(
            "uq_jobs_operation_idempotency_key",
            "operation",
            "idempotency_key",
            unique=True,
            sqlite_where=idempotency_key.is_not(None),
            postgresql_where=idempotency_key.is_not(None),
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
    # The normalized enrollment sample, kept so a Debate can create its own
    # independent clone (2026-10-20). NULL for voices enrolled before 0077.
    sample_file_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("stored_files.id", ondelete="RESTRICT", name="fk_voice_profiles_sample"),
        nullable=True,
    )
    sample_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
        CheckConstraint("scope IN ('system', 'group', 'personal')", name="ck_voice_profiles_scope"),
        CheckConstraint(
            "status IN ('validating', 'enrolling', 'preview_ready', 'ready', 'deleting', "
            "'outcome_unknown', 'failed', 'deleted')",
            name="ck_voice_profiles_status",
        ),
        CheckConstraint(
            # A teacher's personal voice belongs to no group; its owner is the
            # consent actor, enforced in code because that column is SET NULL.
            "(scope = 'system' AND group_id IS NULL) OR (scope = 'group' AND group_id IS NOT NULL) "
            "OR (scope = 'personal' AND group_id IS NULL)",
            name="ck_voice_profiles_scope_group",
        ),
        Index("ix_voice_profiles_group_status", "group_id", "status"),
        # One enrolled system fallback. A preset sets provenance kind to
        # "preset" and stays outside this index, so it can share the system
        # scope without becoming a second fallback.
        Index(
            "uq_voice_profiles_one_system",
            "scope",
            unique=True,
            sqlite_where=sql_text(
                "scope = 'system' AND COALESCE(json_extract(provenance_json, '$.kind'), '') "
                "!= 'preset'"
            ),
            postgresql_where=sql_text(
                "scope = 'system' AND COALESCE(json_extract(provenance_json, '$.kind'), '') "
                "!= 'preset'"
            ),
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
            ondelete="CASCADE",
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
            "profile_scope IN ('system', 'group', 'personal')",
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
            postgresql_where=(
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
            postgresql_where=(operation_type == "delete"),
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


class VoicePreviewCounter(Base):
    """A persisted, shared counter that picks the next preview sample line.

    One row per key (``global``); each preview generation atomically adds one
    and reads the new value, so lines rotate in click order across all users
    and backend replicas.
    """

    __tablename__ = "voice_preview_counters"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ProviderPolicySnapshot(Base):
    """Server-only, immutable supplier policy evidence for ProviderDataCallV1."""

    __tablename__ = "provider_policy_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(120), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier: Mapped[str] = mapped_column(String(160), nullable=False)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    account_product: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    privacy_notice_url: Mapped[str] = mapped_column(String(500), nullable=False)
    privacy_notice_retrieved_at: Mapped[str] = mapped_column(String(64), nullable=False)
    privacy_notice_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    service_terms_url: Mapped[str] = mapped_column(String(500), nullable=False)
    service_terms_retrieved_at: Mapped[str] = mapped_column(String(64), nullable=False)
    service_terms_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    faq_url: Mapped[str] = mapped_column(String(500), nullable=False)
    faq_retrieved_at: Mapped[str] = mapped_column(String(64), nullable=False)
    faq_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    no_training_basis: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_response_logging_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    inference_log_backflow_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    optional_content_logging_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    service_improvement_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    storage_disclosed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retention_setting: Mapped[str | None] = mapped_column(String(160), nullable=True)
    snapshot_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "policy_id", "snapshot_revision", name="uq_provider_policy_snapshots_revision"
        ),
        CheckConstraint(
            "contract_version = 'ProviderDataCallV1'",
            name="ck_provider_policy_snapshots_contract",
        ),
        CheckConstraint("region = 'cn-beijing'", name="ck_provider_policy_snapshots_region"),
        CheckConstraint(
            "account_product IN ('payg_api', 'pay-as-you-go api', 'pay-as-you-go API', "
            "'token_plan_team', 'Token Plan Team')",
            name="ck_provider_policy_snapshots_account_product",
        ),
        CheckConstraint(
            portable_sql(
                "prompt_response_logging_disabled = 1 "
                "AND inference_log_backflow_disabled = 1 "
                "AND optional_content_logging_disabled = 1 "
                "AND service_improvement_disabled = 1",
                "prompt_response_logging_disabled IS TRUE "
                "AND inference_log_backflow_disabled IS TRUE "
                "AND optional_content_logging_disabled IS TRUE "
                "AND service_improvement_disabled IS TRUE",
            ),
            name="ck_provider_policy_snapshots_controls",
        ),
        CheckConstraint(
            portable_sql(
                "storage_disclosed = 1",
                "storage_disclosed IS TRUE",
            ),
            name="ck_provider_policy_snapshots_storage",
        ),
        CheckConstraint("snapshot_revision >= 1", name="ck_provider_policy_snapshots_revision"),
        Index("ix_provider_policy_snapshots_policy", "policy_id", "snapshot_revision"),
    )


class ProviderExportManifest(Base):
    """Server-only allowlist of fields approved for one provider operation."""

    __tablename__ = "provider_export_manifests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    policy_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_policy_snapshots.id",
            ondelete="RESTRICT",
            name="fk_provider_export_manifests_policy",
        ),
        nullable=False,
    )
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_operation: Mapped[str] = mapped_column(String(80), nullable=False)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    build_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fields_json: Mapped[str] = mapped_column(Text, nullable=False)
    operation_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    contains_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contains_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contains_private_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contains_teacher_note: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    course_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "courses.id",
            ondelete="RESTRICT",
            name="fk_provider_export_manifests_course",
        ),
        nullable=True,
    )
    group_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "groups.id",
            ondelete="RESTRICT",
            name="fk_provider_export_manifests_group",
        ),
        nullable=True,
    )
    agent_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "agent_versions.id",
            ondelete="SET NULL",
            name="fk_provider_export_manifests_agent_version",
        ),
        nullable=True,
    )
    debate_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "debates.id",
            ondelete="RESTRICT",
            name="fk_provider_export_manifests_debate",
        ),
        nullable=True,
    )
    turn_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "debate_turns.id",
            ondelete="RESTRICT",
            name="fk_provider_export_manifests_turn",
        ),
        nullable=True,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    max_total_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    max_cost_cny: Mapped[float] = mapped_column(
        Numeric(28, 6), nullable=False, default=0, server_default="0"
    )
    repair_policy_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    repair_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    policy: Mapped[ProviderPolicySnapshot] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["turn_id", "debate_id"],
            ["debate_turns.id", "debate_turns.debate_id"],
            name="fk_provider_export_manifests_turn_debate",
            ondelete="RESTRICT",
        ),
        CheckConstraint("operation_revision >= 1", name="ck_provider_export_manifests_revision"),
        CheckConstraint(
            portable_sql(
                "contains_secret = 0 AND contains_identity = 0 "
                "AND contains_private_audio = 0 AND contains_teacher_note = 0",
                "contains_secret IS FALSE AND contains_identity IS FALSE "
                "AND contains_private_audio IS FALSE AND contains_teacher_note IS FALSE",
            ),
            name="ck_provider_export_manifests_no_forbidden_data",
        ),
        CheckConstraint(
            "(debate_id IS NULL AND turn_id IS NULL) OR "
            "(debate_id IS NOT NULL AND turn_id IS NOT NULL)",
            name="ck_provider_export_manifests_owner_pair",
        ),
        CheckConstraint(
            "provider_operation <> 'llm_debate_turn' OR "
            "(debate_id IS NOT NULL AND turn_id IS NOT NULL)",
            name="ck_provider_export_manifests_llm_owner",
        ),
        # An LLM turn manifest is either the ordinary two-attempt envelope that
        # discloses the exact repair-feedback policy, or the bounded Real-Core
        # Demo one-shot envelope that has no repair attempt and therefore must
        # not disclose a repair policy at all.  ``ExportManifestV1`` enforces
        # the same pair, so a one-shot row can never carry repair fields.
        CheckConstraint(
            "provider_operation <> 'llm_debate_turn' OR "
            "(max_attempts = 2 AND repair_policy_version = 'repair_feedback_v1' "
            "AND repair_policy_hash = "
            "'d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b') OR "
            "(max_attempts = 1 AND repair_policy_version IS NULL "
            "AND repair_policy_hash IS NULL)",
            name="ck_provider_export_manifests_llm_retry_policy",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 2", name="ck_provider_export_manifests_attempts"
        ),
        CheckConstraint("max_total_tokens >= 0", name="ck_provider_export_manifests_tokens"),
        CheckConstraint("max_cost_cny >= 0", name="ck_provider_export_manifests_cost"),
        CheckConstraint(
            "(repair_policy_version IS NULL AND repair_policy_hash IS NULL) OR "
            "(repair_policy_version IS NOT NULL AND repair_policy_hash IS NOT NULL)",
            name="ck_provider_export_manifests_repair_policy_pair",
        ),
        Index("ix_provider_export_manifests_scope", "scope_id", "provider_operation"),
        Index("ix_provider_export_manifests_policy", "policy_snapshot_id"),
        Index("ix_provider_export_manifests_course", "course_id"),
        Index("ix_provider_export_manifests_group", "group_id"),
        Index("ix_provider_export_manifests_agent_version", "agent_version_id"),
        Index("ix_provider_export_manifests_debate", "debate_id"),
        Index("ix_provider_export_manifests_turn", "turn_id"),
    )


class ProviderExportConfirmation(Base):
    """Immutable confirmation binding one exact export and policy hash."""

    __tablename__ = "provider_export_confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    manifest_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_export_manifests.id",
            ondelete="RESTRICT",
            name="fk_provider_export_confirmations_manifest",
        ),
        nullable=False,
        unique=True,
    )
    policy_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_policy_snapshots.id",
            ondelete="RESTRICT",
            name="fk_provider_export_confirmations_policy",
        ),
        nullable=False,
    )
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_at: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    manifest: Mapped[ProviderExportManifest] = relationship()
    policy: Mapped[ProviderPolicySnapshot] = relationship()

    __table_args__ = (
        CheckConstraint(
            "confirmation_revision >= 1", name="ck_provider_export_confirmations_revision"
        ),
        Index("ix_provider_export_confirmations_policy", "policy_snapshot_id"),
    )


class ProviderScopeBudget(Base):
    """Atomic request/token/cost accounting for one server-owned scope."""

    __tablename__ = "provider_scope_budgets"

    scope_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    budget_bucket: Mapped[str] = mapped_column(String(40), primary_key=True)
    max_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    max_total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_cost_cny: Mapped[float] = mapped_column(Numeric(28, 6), nullable=False)
    allocated_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    allocated_total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    allocated_cost_cny: Mapped[float] = mapped_column(Numeric(28, 6), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "budget_bucket IN ('embedding_snapshot', 'embedding_query', 'llm_debate_turn', "
            "'llm_barrage_insight', 'llm_maya_report', 'tts_synthesis', 'voice_enrollment')",
            name="ck_provider_scope_budgets_bucket",
        ),
        CheckConstraint("max_requests >= 0", name="ck_provider_scope_budgets_max_requests"),
        CheckConstraint("max_total_tokens >= 0", name="ck_provider_scope_budgets_max_tokens"),
        CheckConstraint("max_cost_cny >= 0", name="ck_provider_scope_budgets_max_cost"),
        CheckConstraint(
            "allocated_requests >= 0",
            name="ck_provider_scope_budgets_allocated_requests",
        ),
        CheckConstraint(
            "allocated_total_tokens >= 0",
            name="ck_provider_scope_budgets_allocated_tokens",
        ),
        CheckConstraint(
            "allocated_cost_cny >= 0",
            name="ck_provider_scope_budgets_allocated_cost",
        ),
    )


class DemoAcceptanceRun(Base):
    """Server-side identity and bounded call ledger for one Real-Core Demo run."""

    __tablename__ = "demo_acceptance_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_version: Mapped[str] = mapped_column(String(80), nullable=False)
    fixture_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    baseline_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    target_agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    target_version_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False
    )
    debate_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("debates.id", ondelete="RESTRICT"), nullable=True
    )
    report_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("civilization_report_revisions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="prepared")
    starting_charged_requests: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    operations: Mapped[list[ProviderOperation]] = relationship(
        back_populates="acceptance_run",
    )

    __table_args__ = (
        CheckConstraint(
            "plan_version = 'real_core_demo_v2'",
            name="ck_demo_acceptance_runs_plan_version",
        ),
        CheckConstraint(
            portable_sql(
                "length(fixture_hash) = 64 AND fixture_hash NOT GLOB '*[^0-9a-f]*'",
                "length(fixture_hash) = 64 AND "
                "translate(fixture_hash, '0123456789abcdef', '') = ''",
            ),
            name="ck_demo_acceptance_runs_fixture_hash",
        ),
        CheckConstraint(
            "state IN ('prepared', 'executing', 'executed', 'verified')",
            name="ck_demo_acceptance_runs_state",
        ),
        CheckConstraint(
            "starting_charged_requests = 0",
            name="ck_demo_acceptance_runs_initial_charged_zero",
        ),
        Index("ix_demo_acceptance_runs_target", "target_agent_id", "target_version_id"),
        Index("ix_demo_acceptance_runs_debate", "debate_id"),
    )


class ProviderOperation(Base):
    """Generic server-side ProviderDataCallV1 operation metadata."""

    __tablename__ = "provider_operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_operation: Mapped[str] = mapped_column(String(80), nullable=False)
    logical_item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cost_cny: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    export_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    build_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model_key: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared")
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charged_request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staged_response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acceptance_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("demo_acceptance_runs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    call_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    acceptance_run: Mapped[DemoAcceptanceRun | None] = relationship(
        back_populates="operations",
    )
    reservations: Mapped[list[ProviderReservation]] = relationship(
        back_populates="operation", cascade="all, delete-orphan"
    )
    accepted_embedding_stage: Mapped[EmbeddingAcceptedStage | None] = relationship(
        back_populates="operation",
        uselist=False,
        cascade="all, delete-orphan",
    )
    accepted_llm_stage: Mapped[LlmAcceptedStage | None] = relationship(
        back_populates="operation",
        uselist=False,
        cascade="all, delete-orphan",
    )
    recovery_input: Mapped[LlmRecoveryInput | None] = relationship(
        back_populates="operation",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "scope_id",
            "provider_operation",
            "logical_item_id",
            "attempt_no",
            name="uq_provider_operations_attempt",
        ),
        CheckConstraint("attempt_no >= 1", name="ck_provider_operations_attempt"),
        CheckConstraint("max_tokens >= 0", name="ck_provider_operations_max_tokens"),
        CheckConstraint("max_cost_cny >= 0", name="ck_provider_operations_max_cost"),
        CheckConstraint(
            "state IN ('prepared', 'reserved', 'sending', 'accepted', 'succeeded', "
            "'not_sent', 'acceptance_unknown', 'failed', 'abandoned')",
            name="ck_provider_operations_state",
        ),
        CheckConstraint(
            "request_count >= 0 AND charged_request_count >= 0",
            name="ck_provider_operations_counters",
        ),
        CheckConstraint(
            "(acceptance_run_id IS NULL AND call_no IS NULL) OR "
            "(acceptance_run_id IS NOT NULL AND call_no IS NOT NULL)",
            name="ck_provider_operations_acceptance_call_pair",
        ),
        CheckConstraint(
            "call_no IS NULL OR call_no >= 1",
            name="ck_provider_operations_call_no",
        ),
        UniqueConstraint(
            "acceptance_run_id",
            "call_no",
            name="uq_provider_operations_acceptance_call",
        ),
        Index("ix_provider_operations_scope_state", "scope_id", "state"),
        Index("ix_provider_operations_state", "state"),
        Index("ix_provider_operations_acceptance_run", "acceptance_run_id", "call_no"),
    )


class EmbeddingAcceptedStage(Base):
    """Sanitized accepted embedding metadata retained for local recovery.

    The stage intentionally stores hashes and local opaque identities only.  A
    provider response envelope, credential, endpoint and workspace never have
    a column in this table.
    """

    __tablename__ = "embedding_accepted_stages"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("provider_operations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    build_id: Mapped[str] = mapped_column(String(120), nullable=False)
    build_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    model_key: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_region: Mapped[str] = mapped_column(String(40), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    operation: Mapped[ProviderOperation] = relationship(back_populates="accepted_embedding_stage")
    vectors: Mapped[list[EmbeddingAcceptedVector]] = relationship(
        back_populates="stage",
        cascade="all, delete-orphan",
        order_by="EmbeddingAcceptedVector.item_index",
    )

    __table_args__ = (
        CheckConstraint("batch_index >= 0", name="ck_embedding_accepted_stages_batch_index"),
        CheckConstraint("dimension > 0", name="ck_embedding_accepted_stages_dimension"),
        CheckConstraint(
            "length(build_manifest_hash) = 64",
            name="ck_embedding_accepted_stages_build_hash",
        ),
        CheckConstraint(
            "length(response_hash) = 64",
            name="ck_embedding_accepted_stages_response_hash",
        ),
        CheckConstraint("length(build_id) > 0", name="ck_embedding_accepted_stages_build_id"),
        CheckConstraint("length(model_key) > 0", name="ck_embedding_accepted_stages_model"),
        CheckConstraint(
            "(embedding_provider = 'mock' AND model_key = 'mock-sha256-v1' "
            "AND embedding_region = 'local' AND dimension = 256 "
            "AND policy_version = 'w4-mock-v1') OR "
            "(embedding_provider = 'dashscope' AND model_key = 'text-embedding-v4' "
            "AND embedding_region = 'cn-beijing' AND dimension = 1024 "
            "AND policy_version = 'w4-embed-v1')",
            name="ck_embedding_accepted_stages_identity",
        ),
        Index("ix_embedding_accepted_stages_build", "build_id", "batch_index"),
    )


class EmbeddingAcceptedVector(Base):
    """One ordered, validated vector in an accepted embedding stage.

    ``chunk_id`` is the opaque frozen SnapshotBuild identity.  Publication
    later verifies it against the newly-created KnowledgeChunk row, so staging
    can happen before that row exists.
    """

    __tablename__ = "embedding_accepted_vectors"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("embedding_accepted_stages.operation_id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    embedding_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    stage: Mapped[EmbeddingAcceptedStage] = relationship(back_populates="vectors")

    __table_args__ = (
        UniqueConstraint(
            "operation_id",
            "chunk_id",
            name="uq_embedding_accepted_vectors_chunk",
        ),
        CheckConstraint("item_index >= 0", name="ck_embedding_accepted_vectors_item_index"),
        CheckConstraint(
            "length(embedding_blob) > 0",
            name="ck_embedding_accepted_vectors_blob",
        ),
        Index("ix_embedding_accepted_vectors_chunk", "chunk_id"),
    )


# Runtime-facing names used by the pure embedding stage port.  These are
# aliases for the single durable ORM rows, not additional tables/models.
AcceptedEmbeddingStage = EmbeddingAcceptedStage
AcceptedEmbeddingVector = EmbeddingAcceptedVector


class LlmAcceptedStage(Base):
    """Immutable sanitized accepted result and usage ledger for one LLM turn.

    This table intentionally stores the provider's validated structured JSON,
    hashes and accounting facts only.  Raw response envelopes, headers,
    supplier IDs, credentials and outbound message text never enter durable
    provider-control state.
    """

    __tablename__ = "llm_accepted_stages"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_operations.id",
            ondelete="RESTRICT",
            name="fk_llm_accepted_stages_operation",
        ),
        primary_key=True,
    )
    turn_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("debate_turns.id", ondelete="RESTRICT", name="fk_llm_accepted_stages_turn"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tokenizer_id: Mapped[str] = mapped_column(String(160), nullable=False)
    tokenizer_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    persona_spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    transcript_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    export_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    build_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    repair_policy_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_fence: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    output_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    price_card_version: Mapped[str] = mapped_column(String(120), nullable=False)
    input_price_cny_per_million: Mapped[float] = mapped_column(Numeric(20, 9), nullable=False)
    cached_input_price_cny_per_million: Mapped[float] = mapped_column(
        Numeric(20, 9), nullable=False
    )
    output_price_cny_per_million: Mapped[float] = mapped_column(Numeric(20, 9), nullable=False)
    estimated_cost_cny: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    actual_cost_cny: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    retrieval_reused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    repair_policy_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    operation: Mapped[ProviderOperation] = relationship(back_populates="accepted_llm_stage")

    __table_args__ = (
        UniqueConstraint("turn_id", "attempt_no", name="uq_llm_accepted_stages_turn_attempt"),
        CheckConstraint("attempt_no >= 1 AND attempt_no <= 2", name="ck_llm_stages_attempt"),
        CheckConstraint(
            "length(request_hash) = 64 AND length(schema_hash) = 64 "
            "AND length(prompt_hash) = 64 "
            "AND length(tokenizer_hash) = 64 AND length(rule_set_hash) = 64 "
            "AND length(persona_spec_hash) = 64 AND length(transcript_hash) = 64 "
            "AND length(receipt_hash) = 64 AND length(policy_hash) = 64 "
            "AND length(export_manifest_hash) = 64 AND length(build_manifest_hash) = 64 "
            "AND length(output_hash) = 64",
            name="ck_llm_stages_hashes",
        ),
        CheckConstraint(
            "repair_policy_hash IS NULL OR length(repair_policy_hash) = 64",
            name="ck_llm_stages_repair_hash",
        ),
        CheckConstraint(
            "(repair_policy_version IS NULL AND repair_policy_hash IS NULL) OR "
            "(repair_policy_version IS NOT NULL AND repair_policy_hash IS NOT NULL)",
            name="ck_llm_stages_repair_policy_pair",
        ),
        CheckConstraint(
            "prompt_tokens >= 0 AND cached_input_tokens >= 0 AND completion_tokens >= 0 "
            "AND total_tokens >= 0 AND cached_input_tokens <= prompt_tokens "
            "AND total_tokens = prompt_tokens + completion_tokens",
            name="ck_llm_stages_usage",
        ),
        CheckConstraint(
            "input_price_cny_per_million >= 0 "
            "AND cached_input_price_cny_per_million >= 0 "
            "AND output_price_cny_per_million >= 0 "
            "AND estimated_cost_cny >= 0 "
            "AND (actual_cost_cny IS NULL OR actual_cost_cny >= 0)",
            name="ck_llm_stages_costs",
        ),
        CheckConstraint("length(output_json) > 0", name="ck_llm_stages_output"),
        Index("ix_llm_accepted_stages_turn", "turn_id", "attempt_no"),
    )


# Names used by the runtime adapter.  They intentionally resolve to the one
# immutable row so a stage and its accepted usage facts cannot diverge.
LLMAcceptedStage = LlmAcceptedStage
LLMUsageLedger = LlmAcceptedStage
LlmUsageLedger = LlmAcceptedStage
LLMUsage = LlmAcceptedStage


class LlmRecoveryInput(Base):
    """Immutable canonical input retained for zero-network LLM recovery."""

    __tablename__ = "llm_recovery_inputs"

    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_operations.id",
            ondelete="RESTRICT",
            name="fk_llm_recovery_inputs_operation",
        ),
        primary_key=True,
    )
    turn_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("debate_turns.id", ondelete="RESTRICT", name="fk_llm_recovery_inputs_turn"),
        nullable=False,
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    input_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    operation: Mapped[ProviderOperation] = relationship(back_populates="recovery_input")

    __table_args__ = (
        UniqueConstraint("turn_id", "attempt_no", name="uq_llm_recovery_inputs_turn_attempt"),
        CheckConstraint(
            "attempt_no >= 1 AND attempt_no <= 2",
            name="ck_llm_recovery_inputs_attempt",
        ),
        CheckConstraint(
            "input_version IN ('llm_recovery_input_v1', 'segment_recovery_input_v2')",
            name="ck_llm_recovery_inputs_version",
        ),
        CheckConstraint(
            portable_sql(
                "length(CAST(input_json AS BLOB)) > 0",
                "octet_length(input_json) > 0",
            ),
            name="ck_llm_recovery_inputs_size",
        ),
        CheckConstraint(
            portable_sql(
                "length(input_hash) = 64 AND input_hash NOT GLOB '*[^0-9a-f]*'",
                "length(input_hash) = 64 AND translate(input_hash, '0123456789abcdef', '') = ''",
            ),
            name="ck_llm_recovery_inputs_hash",
        ),
        Index("ix_llm_recovery_inputs_turn", "turn_id", "attempt_no"),
    )


LLMRecoveryInput = LlmRecoveryInput


class ProviderReservation(Base):
    """Durable pre-send allowance linked to exactly one operation attempt."""

    __tablename__ = "provider_reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "provider_operations.id",
            ondelete="CASCADE",
            name="fk_provider_reservations_operation",
        ),
        nullable=False,
        unique=True,
    )
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_operation: Mapped[str] = mapped_column(String(80), nullable=False)
    logical_item_id: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cost_cny: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    operation: Mapped[ProviderOperation] = relationship(back_populates="reservations")

    __table_args__ = (
        CheckConstraint("attempt_no >= 1", name="ck_provider_reservations_attempt"),
        CheckConstraint("max_tokens >= 0", name="ck_provider_reservations_max_tokens"),
        CheckConstraint("max_cost_cny >= 0", name="ck_provider_reservations_max_cost"),
        CheckConstraint(
            "state IN ('prepared', 'reserved', 'sending', 'accepted', 'succeeded', "
            "'not_sent', 'acceptance_unknown', 'failed', 'abandoned')",
            name="ck_provider_reservations_state",
        ),
        Index("ix_provider_reservations_scope_state", "scope_id", "state"),
    )


class DataResetRow(Base):
    """A row the ``0060`` data reset retired, kept so a downgrade restores it."""

    __tablename__ = "data_reset_rows"

    table_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    row_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)


# Keep a small helper available to fingerprint/serialization code without
# exposing ORM internals in route modules.
