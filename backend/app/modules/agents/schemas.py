"""Provider-neutral Agent/version API DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.persona import (
    PERSONA_COMPILER_VERSION,
    PersonaCompilerVersion,
    PersonaDiagnostic,
    PersonaSpecVersion,
)
from app.modules.knowledge.schemas import KnowledgeDocument

Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]


class DrawingPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: Coordinate
    y: Coordinate


class DrawingErase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: float = Field(ge=1 / 1024, le=0.1, allow_inf_nan=False, strict=True)
    points: list[DrawingPoint] = Field(min_length=1, max_length=4096)


class DrawingStroke(DrawingErase):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    opacity: float = Field(default=1, ge=0, le=1, allow_inf_nan=False, strict=True)
    erasures: list[DrawingErase] = Field(default_factory=list, max_length=256)


class DrawingMouth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(default=0.5, ge=0.4, le=0.6, allow_inf_nan=False, strict=True)
    y: float = Field(default=0.435, ge=0.3, le=0.65, allow_inf_nan=False, strict=True)


class AvatarDrawing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    strokes: list[DrawingStroke] = Field(max_length=256)
    mouth: DrawingMouth

    @model_validator(mode="after")
    def bounded_drawing(self) -> AvatarDrawing:
        if len({stroke.id for stroke in self.strokes}) != len(self.strokes):
            raise ValueError("duplicate stroke ids")
        points = sum(len(s.points) + sum(len(e.points) for e in s.erasures) for s in self.strokes)
        masks = sum(len(s.erasures) for s in self.strokes)
        if points > 20000 or masks > 2048 or len(self.model_dump_json().encode()) > 524288:
            raise ValueError("drawing too large")
        return self


class AvatarConfig(BaseModel):
    template_id: str
    material_theme: str
    eye_color: str | None = None
    default_expression: Literal["neutral", "attentive", "happy", "serious_angry", "sad"]
    expression_strength: Literal["low", "medium", "high"]
    motion_style: Literal["calm", "active"]
    drawing: AvatarDrawing | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def drawing_is_egg_only(self) -> AvatarConfig:
        if self.drawing is not None and self.template_id != "egg":
            raise ValueError("drawing requires egg")
        return self


class AgentSummary(BaseModel):
    id: UUID
    group_id: UUID | None
    course_id: UUID
    ownership_scope: Literal["group", "personal"]
    visibility: Literal["private", "public"]
    # Creator; for a public Agent also same-group students and course teachers.
    can_edit: bool
    # That same edit role, and only while the Agent is still private.
    can_manage_visibility: bool = False
    name: str
    description: str = ""
    metadata_revision: int = Field(ge=0)
    status: Literal["active", "archived"]
    current_published_version_id: UUID | None = None
    current_draft_version_id: UUID | None = None
    # Creator, same-group student (public only) or course teacher (public only).
    can_delete: bool | None = None
    is_creator: bool | None = None
    # Owner holds CourseMember.role == teacher in this course. Optional so
    # older clients keep working; the Studyform sticker reads "Teacher".
    is_teacher_owned: bool | None = None
    last_edited_by_name: str | None = None
    last_edited_at: datetime | None = None
    # Label of the current published version (e.g. "1.2"), for the open
    # button's hover tooltip 「最新编辑：…，Version：1.X」.
    current_version_label: str | None = None
    # For list cards: the published version's label and avatar theme, else
    # those of the draft this caller may see (so a list needs no per-Agent
    # versions read).
    card_version_label: str | None = None
    card_material_theme: str | None = None


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
    # The editor's collapsed tag reads the existing agent_debate_cards row.
    # It is not a column, and reading it must not start a compile.
    stored_card_status: Literal["compiling", "ready", "fallback"] | None = None


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


class AgentReadinessIssue(BaseModel):
    """One hint about an Agent's current published version, named by Agent."""

    agent_id: UUID
    agent_name: str
    issue: Literal[
        "agent_archived",
        "agent_not_published",
        "rag_missing",
        "agent_md_invalid",
        "avatar_missing",
        "voice_missing",
    ]
    # Only blocking issues keep the Agent out of a new Debate.
    blocking: bool
    message: str


class AgentDetail(AgentSummary):
    versions: list[AgentVersion] = Field(default_factory=list)
    readiness_issues: list[AgentReadinessIssue] = Field(default_factory=list)


class UpdateAgentDraftRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    agent_md: str = ""
    avatar_config: AvatarConfig = None  # type: ignore[assignment]
    voice_profile_id: UUID | None = None


class SaveAvatarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    expected_published_version_id: UUID | None
    avatar_config: AvatarConfig


class AgentCreateRequest(BaseModel):
    # Trimmed and checked by the route so empty / too-long names get the
    # stable ``agent_name_required`` / ``agent_name_too_long`` codes.
    name: str
    avatar_config: AvatarConfig | None = None
    description: str = ""
    visibility: Literal["private", "public"] = "private"


class UpdateAgentMetadataRequest(BaseModel):
    """CAS payload for mutable Agent metadata and owner-controlled visibility.

    ``description`` is intentionally nullable on the wire so clients can
    clear an older/null value explicitly.  The database stores a non-null
    empty string.

    ``name`` is optional: omitted or null leaves the name unchanged. A sent
    name is trimmed; empty after trimming is 422 ``agent_name_required`` and
    more than 120 characters is 422 ``agent_name_too_long``. A name already
    used in the Agent's namespace resolves to ``Name-2`` etc., exactly as on
    create. ``description`` changes only when it is sent.
    """

    expected_metadata_revision: int = Field(ge=0)
    name: str | None = None
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
    readiness_issues: list[AgentReadinessIssue] = Field(default_factory=list)


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


class AgentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    agent_md: str = ""
    avatar_config: AvatarConfig
    voice_profile_id: UUID | None = None
    version_id: UUID | None = None
    course_id: UUID | None = None
    group_id: UUID | None = None


class AgentPreviewResponse(BaseModel):
    answer: str
    audio_base64: str | None = None
    audio_content_type: Literal["audio/wav"] | None = None
