"""Provider-neutral Agent/version API DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.persona import (
    PERSONA_COMPILER_VERSION,
    PersonaCompilerVersion,
    PersonaDiagnostic,
    PersonaSpecVersion,
)
from app.modules.knowledge.schemas import KnowledgeDocument


class AvatarConfig(BaseModel):
    template_id: str
    material_theme: str
    eye_color: str | None = None
    default_expression: Literal["neutral", "attentive", "happy", "serious_angry", "sad"]
    expression_strength: Literal["low", "medium", "high"]
    motion_style: Literal["calm", "active"]


class AgentSummary(BaseModel):
    id: UUID
    group_id: UUID | None
    course_id: UUID
    ownership_scope: Literal["group", "personal"]
    visibility: Literal["private", "public"]
    # True only for the account that published this Agent. Public use is read-only.
    can_edit: bool
    name: str
    description: str = ""
    metadata_revision: int = Field(ge=0)
    status: Literal["active", "archived"]
    current_published_version_id: UUID | None = None
    current_draft_version_id: UUID | None = None


class KnowledgeGenerationIntent(BaseModel):
    """Explicit Done intent tied to the exact saved Agent source selection."""

    model_config = ConfigDict(extra="forbid")

    source_document_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> KnowledgeGenerationIntent:
        if len(self.source_document_ids) != len(set(self.source_document_ids)):
            raise ValueError("source_document_ids must be unique")
        return self


class KnowledgeGenerationReceipt(BaseModel):
    run_id: UUID
    job_id: UUID
    knowledge_set_id: UUID
    state: Literal["pending", "running", "blocked", "completed", "failed", "interrupted"]


class AgentVersion(BaseModel):
    id: UUID
    agent_id: UUID
    version_label: str = Field(pattern=r"^V[0-9]+\.[0-9]+$")
    state: Literal["draft", "published", "superseded"]
    revision: int = Field(ge=0)
    agent_md: str = ""
    raw_agent_md_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec: PersonaSpecVersion | None = None
    persona_spec_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    persona_compiler_version: PersonaCompilerVersion | None = None
    persona_diagnostics: list[PersonaDiagnostic] = Field(default_factory=list)
    persona_confirmation_revision: int | None = Field(default=None, ge=0)
    student_confirmed_at: datetime | None = None
    persona_confirmed: bool = False
    avatar_config: AvatarConfig
    voice_profile_id: UUID | None = None
    effective_voice_profile_id: UUID | None = None
    voice_fallback_active: bool
    knowledge_snapshot_id: UUID | None = None
    published_visibility: Literal["private", "public"] | None = None
    enabled_documents: list[KnowledgeDocument] = Field(default_factory=list)
    publish_blockers: list[str] = Field(default_factory=list)
    knowledge_generation: KnowledgeGenerationReceipt | None = None


class CompilePersonaRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class ConfirmPersonaRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    raw_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: PersonaCompilerVersion = PERSONA_COMPILER_VERSION


class PersonaCompileResponse(BaseModel):
    version_id: UUID
    revision: int = Field(ge=0)
    compiled: bool
    raw_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec: PersonaSpecVersion | None = None
    persona_spec_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiler_version: PersonaCompilerVersion = PERSONA_COMPILER_VERSION
    diagnostics: list[PersonaDiagnostic] = Field(default_factory=list)
    persona_confirmed: bool = False


class KnowledgeDocumentMutation(BaseModel):
    document: KnowledgeDocument
    agent_version: AgentVersion | None = None


class AgentDetail(AgentSummary):
    versions: list[AgentVersion] = Field(default_factory=list)


class UpdateAgentDraftRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    agent_md: str = ""
    avatar_config: AvatarConfig = None  # type: ignore[assignment]
    voice_profile_id: UUID | None = None


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    visibility: Literal["private", "public"] = "private"


class UpdateAgentMetadataRequest(BaseModel):
    """CAS payload for mutable Agent metadata and owner-controlled visibility.

    ``description`` is intentionally nullable on the wire so clients can
    clear an older/null value explicitly.  The database stores a non-null
    empty string.
    """

    expected_metadata_revision: int = Field(ge=0)
    description: str | None = ""
    visibility: Literal["private", "public"] | None = None


class SetDocumentsRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    document_ids: list[UUID]


class PublishAgentVersionRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    acceptance_run_id: UUID | None = None
    call_no: int | None = Field(default=None, ge=1, le=1)
    generation: KnowledgeGenerationIntent | None = None

    @model_validator(mode="after")
    def validate_acceptance_binding(self) -> PublishAgentVersionRequest:
        if (self.acceptance_run_id is None) != (self.call_no is None):
            raise ValueError("acceptance_run_id and call_no must be supplied together")
        return self


# Kept as an import-compatible alias for existing non-Demo callers.
ExpectedRevisionRequest = PublishAgentVersionRequest


class RagPreview(BaseModel):
    version_id: UUID
    total_char_count: int
    limit: None
    document_count: int
    index_status: Literal["pending", "ready", "failed"]
    combined_markdown: str = ""


class RetrievalSource(BaseModel):
    source_filename: str
    chunk_id: UUID = None  # type: ignore[assignment]


class TestChatRequest(BaseModel):
    message: str = Field(min_length=1)


class TestChatResponse(BaseModel):
    answer: str
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"]
    sources: list[RetrievalSource]


class PublishedAgentAuthor(BaseModel):
    user_id: UUID
    display_name: str
    avatar: str | None = None


class PublishedAgentSummary(BaseModel):
    author: PublishedAgentAuthor | None = None
    group_name: str
    agent: AgentSummary
    current_version: AgentVersion


class SnapshotDocument(BaseModel):
    id: UUID
    source_filename: str
    char_count: int = Field(ge=1)
    order_index: int = Field(ge=0)


class KnowledgeSnapshot(BaseModel):
    id: UUID
    agent_version_id: UUID
    content_hash: str
    total_char_count: int = Field(ge=1)
    documents: list[SnapshotDocument]
    created_at: datetime
