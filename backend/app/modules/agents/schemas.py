"""Provider-neutral Agent/version API DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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
    group_id: UUID
    name: str
    description: str = ""
    status: Literal["active", "archived"]
    current_published_version_id: UUID | None = None
    current_draft_version_id: UUID | None = None


class AgentVersion(BaseModel):
    id: UUID
    agent_id: UUID
    version_label: str = Field(pattern=r"^V[0-9]+\.[0-9]+$")
    state: Literal["draft", "published", "superseded"]
    revision: int = Field(ge=0)
    agent_md: str = Field(default="", max_length=12000)
    avatar_config: AvatarConfig
    voice_profile_id: UUID | None = None
    effective_voice_profile_id: UUID | None = None
    voice_fallback_active: bool
    knowledge_snapshot_id: UUID | None = None
    enabled_documents: list[KnowledgeDocument] = Field(default_factory=list)
    publish_blockers: list[str] = Field(default_factory=list)


class KnowledgeDocumentMutation(BaseModel):
    document: KnowledgeDocument
    agent_version: AgentVersion


class AgentDetail(AgentSummary):
    versions: list[AgentVersion] = Field(default_factory=list)


class UpdateAgentDraftRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    agent_md: str = Field(default="", max_length=12000)
    avatar_config: AvatarConfig = None  # type: ignore[assignment]
    voice_profile_id: UUID | None = None


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""


class SetDocumentsRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    document_ids: list[UUID]


class ExpectedRevisionRequest(BaseModel):
    expected_revision: int = Field(ge=0)


class RagPreview(BaseModel):
    version_id: UUID
    total_char_count: int
    limit: Literal[100000]
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


class PublishedAgentSummary(BaseModel):
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
    total_char_count: int = Field(ge=1, le=100000)
    documents: list[SnapshotDocument]
    created_at: datetime
