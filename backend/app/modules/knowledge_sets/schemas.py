"""Typed request and response contracts for Knowledge Sets."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


KnowledgeGenerationState = Literal[
    "pending", "running", "blocked", "completed", "failed", "interrupted"
]


class SourceLocation(StrictModel):
    section_path: list[str] = Field(default_factory=list)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    paragraph_index: int | None = Field(default=None, ge=0)
    excerpt_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> SourceLocation:
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must be greater than or equal to start_offset")
        return self


class AssetCitation(StrictModel):
    source_binding_id: UUID
    location: SourceLocation = Field(default_factory=SourceLocation)


class RubricCriterion(StrictModel):
    label: str = Field(min_length=1)
    guidance: str = ""
    points: float = Field(ge=0)


class Rubric(StrictModel):
    criteria: list[RubricCriterion] = Field(default_factory=list)
    total_points: float | None = Field(default=None, ge=0)


class ConceptContent(StrictModel):
    kind: Literal["concept"]
    title: str = Field(min_length=1)
    description: str = ""
    prerequisite_ids: list[UUID] = Field(default_factory=list)
    citations: list[AssetCitation] = Field(default_factory=list)


class QuestionContent(StrictModel):
    kind: Literal["question"]
    prompt: str = Field(min_length=1)
    reference_answer: str | None = None
    concept_ids: list[UUID] = Field(default_factory=list)
    citations: list[AssetCitation] = Field(default_factory=list)
    rubric: Rubric


class StudentQuestionContent(StrictModel):
    """Student question projection intentionally has no Rubric field."""

    kind: Literal["question"]
    prompt: str
    concept_ids: list[UUID] = Field(default_factory=list)
    citations: list[AssetCitation] = Field(default_factory=list)


class NoteContent(StrictModel):
    kind: Literal["note"]
    title: str = Field(min_length=1)
    body: str = ""
    citations: list[AssetCitation] = Field(default_factory=list)


AssetContent = Annotated[
    ConceptContent | QuestionContent | NoteContent, Field(discriminator="kind")
]
StudentAssetContent = Annotated[
    ConceptContent | StudentQuestionContent | NoteContent, Field(discriminator="kind")
]


class CreateKnowledgeSetRequest(StrictModel):
    display_name: str = Field(min_length=1)
    group_id: UUID | None = None


class UpdateKnowledgeSetRequest(StrictModel):
    expected_metadata_revision: int = Field(ge=0)
    display_name: str | None = Field(default=None, min_length=1)
    visibility: Literal["private", "public"] | None = None

    @model_validator(mode="after")
    def includes_a_change(self) -> UpdateKnowledgeSetRequest:
        if self.display_name is None and self.visibility is None:
            raise ValueError("at least one metadata field is required")
        return self


class DeleteKnowledgeSetRequest(StrictModel):
    expected_metadata_revision: int = Field(ge=0)
    expected_content_revision: int = Field(ge=0)


class KnowledgeSetSummary(StrictModel):
    id: UUID
    owner_user_id: UUID | None = None
    generated_by_agent_id: UUID | None = None
    course_id: UUID
    group_id: UUID | None
    ownership_scope: Literal["group", "personal"]
    visibility: Literal["private", "public"]
    display_name: str
    # Internal CAS/privacy epochs are owner-only. Public projections return
    # null rather than a counter that could reveal Private-era activity.
    metadata_revision: int | None = Field(default=None, ge=0)
    content_revision: int | None = Field(default=None, ge=0)
    authorization_epoch: int | None = Field(default=None, ge=0)
    source_count: int = Field(ge=0)
    asset_count: int = Field(ge=0)
    can_edit: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KnowledgeSetSourceDTO(StrictModel):
    id: UUID
    document_id: UUID | None
    source_filename: str | None
    char_count: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    authorization_epoch: int | None = Field(default=None, ge=0)
    order_index: int = Field(ge=0)
    is_active: bool
    available: bool


class KnowledgeSetDetail(KnowledgeSetSummary):
    sources: list[KnowledgeSetSourceDTO]


class BrainformKnowledgeSummary(StrictModel):
    agent_id: UUID
    canonical_set_id: UUID
    source_agent_display_name: str
    knowledge_display_name: str
    generation_job_id: UUID | None = None
    can_read: Literal[True] = True
    can_edit: bool
    version_seq: int | None = Field(default=None, ge=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generation_state: KnowledgeGenerationState | None = None
    safe_error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")


class KnowledgeMarkdownDocument(StrictModel):
    audience: Literal["full", "student"]
    agent_id: UUID
    canonical_set_id: UUID
    source_agent_display_name: str
    knowledge_display_name: str
    version_seq: int
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    markdown: str
    projection_available: bool
    can_read: Literal[True] = True
    can_edit: bool
    created_at: datetime


class SaveKnowledgeMarkdownRequest(StrictModel):
    expected_version_seq: int = Field(ge=0)
    markdown: str


class RegenerateKnowledgeRequest(StrictModel):
    action_id: UUID


class RegenerateKnowledgeResponse(StrictModel):
    action_id: UUID
    agent_id: UUID
    canonical_set_id: UUID
    run_id: UUID
    job_id: UUID
    state: KnowledgeGenerationState


class KnowledgeSetRevocation(StrictModel):
    id: UUID
    deleted: Literal[True] = True
    metadata_revision: int = Field(ge=0)
    content_revision: int = Field(ge=0)
    authorization_epoch: int = Field(ge=0)
    revoked_at: datetime


class ReplaceKnowledgeSetSourcesRequest(StrictModel):
    expected_content_revision: int = Field(ge=0)
    source_document_ids: list[UUID]


class RemoveKnowledgeSetSourceRequest(StrictModel):
    expected_content_revision: int = Field(ge=0)


class CreateKnowledgeAssetRequest(StrictModel):
    expected_content_revision: int = Field(ge=0)
    content: AssetContent


class UpdateKnowledgeAssetRequest(StrictModel):
    expected_content_revision: int = Field(ge=0)
    expected_asset_version_seq: int = Field(ge=1)
    content: AssetContent


class AssetVersionFullDTO(StrictModel):
    id: UUID
    asset_id: UUID
    version_seq: int | None = Field(default=None, ge=1)
    content: AssetContent
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by_user_id: UUID
    created_at: datetime


class AssetVersionStudentDTO(StrictModel):
    id: UUID
    asset_id: UUID
    version_seq: int | None = Field(default=None, ge=1)
    content: StudentAssetContent
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by_user_id: UUID
    created_at: datetime


class KnowledgeAssetFullDTO(StrictModel):
    audience: Literal["full"]
    id: UUID
    knowledge_set_id: UUID
    kind: Literal["concept", "question", "note"]
    current_version_seq: int | None = Field(default=None, ge=1)
    current_version: AssetVersionFullDTO
    can_edit: bool
    created_at: datetime | None = None
    updated_at: datetime


class KnowledgeAssetStudentDTO(StrictModel):
    audience: Literal["student"]
    id: UUID
    knowledge_set_id: UUID
    kind: Literal["concept", "question", "note"]
    current_version_seq: int | None = Field(default=None, ge=1)
    current_version: AssetVersionStudentDTO
    can_edit: Literal[False] = False
    created_at: datetime | None = None
    updated_at: datetime


KnowledgeAssetDTO = Annotated[
    KnowledgeAssetFullDTO | KnowledgeAssetStudentDTO, Field(discriminator="audience")
]


class KnowledgeAssetVersionHistoryFull(StrictModel):
    audience: Literal["full"]
    asset_id: UUID
    versions: list[AssetVersionFullDTO]


class KnowledgeAssetVersionHistoryStudent(StrictModel):
    audience: Literal["student"]
    asset_id: UUID
    versions: list[AssetVersionStudentDTO]


KnowledgeAssetVersionHistory = Annotated[
    KnowledgeAssetVersionHistoryFull | KnowledgeAssetVersionHistoryStudent,
    Field(discriminator="audience"),
]


class KnowledgeGraphNode(StrictModel):
    id: UUID
    title: str
    description: str


class KnowledgeGraphEdge(StrictModel):
    source_id: UUID
    target_id: UUID


class KnowledgeGraph(StrictModel):
    set_id: UUID
    content_revision: int | None = Field(default=None, ge=0)
    nodes: list[KnowledgeGraphNode]
    edges: list[KnowledgeGraphEdge]


class KnowledgeGenerationStatus(StrictModel):
    run_id: UUID
    job_id: UUID
    knowledge_set_id: UUID
    state: KnowledgeGenerationState
    provider_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    safe_error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$")
    accepted_item_count: int = Field(default=0, ge=0)
    materialized_item_count: int = Field(default=0, ge=0)
    failed_item_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class AgentKnowledgeSets(StrictModel):
    agent_id: UUID
    agent_metadata_revision: int = Field(ge=0)
    sets: list[KnowledgeSetSummary]


class ReplaceAgentKnowledgeSetsRequest(StrictModel):
    expected_agent_metadata_revision: int = Field(ge=0)
    set_ids: list[UUID]
