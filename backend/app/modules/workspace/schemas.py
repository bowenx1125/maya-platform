from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.modules.agents.schemas import AvatarConfig
from app.modules.debates.playback.schemas import PlaybackStateDTO
from app.modules.knowledge_sets.schemas import KnowledgeGenerationChatProgress
from app.modules.learning.schemas import AssessmentRuntimeResult


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ComponentKey = Literal["llm", "embedding", "report", "tts", "voice"]
ComponentMode = Literal["real", "mock"]


class ChatAgent(ClosedModel):
    agent_id: UUID
    version_id: UUID
    course_id: UUID
    name: str
    version_label: str
    avatar_config: AvatarConfig
    visibility: Literal["private", "public"]
    available: bool = True
    # Its publisher deleted the Agent; the Chat stays readable but cannot continue.
    deleted: bool = False


class ChatSource(ClosedModel):
    chunk_id: UUID
    filename: str
    excerpt: str


class ChatTurn(ClosedModel):
    id: UUID
    user_text: str
    assistant_text: str | None
    mode: ComponentMode
    state: Literal["pending", "ready", "partial", "failed", "acceptance_unknown", "paused"]
    sources: list[ChatSource]
    safe_error_code: str | None
    assessment_result: AssessmentRuntimeResult | None = None


class ChatSession(ClosedModel):
    entry_kind: Literal["agent"] = "agent"
    chat_visibility: Literal["private", "public"] = "private"
    origin: Literal["single_agent"] = "single_agent"
    read_only: bool = False
    can_send: bool = True
    id: UUID
    agent: ChatAgent
    revision: int
    turns: list[ChatTurn]
    created_at: datetime
    title: str | None = None
    pinned_at: datetime | None = None
    # Owner Teacher Chat progress for the Agent's latest Knowledge generation,
    # same under-message slot as Team assessment_stage. Null when nothing to show.
    knowledge_generation: KnowledgeGenerationChatProgress | None = None


class TeamChatParticipant(ClosedModel):
    id: UUID
    name: str
    avatar_config: AvatarConfig
    position: int
    is_leader: bool
    available: bool = True
    deleted: bool = False


class ChatTeam(ClosedModel):
    id: UUID
    version_id: UUID
    course_id: UUID
    name: str
    members: list[TeamChatParticipant]
    available: bool
    deleted: bool = False


class TeamRouting(ClosedModel):
    mode: Literal["auto", "selected", "all"] = "auto"
    participant_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self) -> "TeamRouting":
        if self.mode == "selected" and not self.participant_ids:
            raise ValueError("Select at least one Team participant.")
        if self.mode == "auto" and self.participant_ids:
            raise ValueError("Automatic routing cannot contain selected participants.")
        return self


class TeamMemberResult(ClosedModel):
    id: UUID
    participant_id: UUID
    speaker_name: str
    ordinal: int
    state: Literal["pending", "running", "ready", "failed", "acceptance_unknown"]
    assistant_text: str | None
    sources: list[ChatSource]
    safe_error_code: str | None


class TeamChatTurn(ChatTurn):
    routing: TeamRouting
    member_results: list[TeamMemberResult]
    assessment_result: AssessmentRuntimeResult | None = None


class TeamChatSession(ClosedModel):
    id: UUID
    entry_kind: Literal["team", "maya_team"]
    chat_visibility: Literal["private", "public"]
    origin: Literal["custom_team", "published_course_team"]
    team: ChatTeam
    revision: int
    turns: list[TeamChatTurn]
    created_at: datetime
    read_only: bool
    can_send: bool = False
    title: str | None = None
    pinned_at: datetime | None = None
    # Where the server is in finishing the latest formal attempt, for the
    # progress bar under the newest message; null when nothing is finishing.
    assessment_stage: Literal["preparing", "scoring", "summarizing", "completed"] | None = None


ConversationSession = Annotated[ChatSession | TeamChatSession, Field(discriminator="entry_kind")]


class MemoryConversationSource(ClosedModel):
    kind: Literal["conversation"]
    id: UUID


class MemoryAgentSource(ClosedModel):
    kind: Literal["agent"]
    agent_id: UUID


class MemoryTeamSource(ClosedModel):
    kind: Literal["team"]
    team_id: UUID


class MemoryMayaTeamSource(ClosedModel):
    kind: Literal["maya_team"]
    team_id: UUID


MemoryEntrySource = Annotated[
    MemoryConversationSource | MemoryAgentSource | MemoryTeamSource | MemoryMayaTeamSource,
    Field(discriminator="kind"),
]


class MemoryEntryRequest(ClosedModel):
    action_id: UUID
    course_id: UUID
    source: MemoryEntrySource


class MemoryEntryResponse(ClosedModel):
    action_id: UUID
    conversation_id: UUID
    request_id: UUID
    message: str
    session: ConversationSession


class AgentChatEntry(ClosedModel):
    kind: Literal["agent"]
    version_id: UUID


class SavedTeamChatEntry(ClosedModel):
    kind: Literal["team"]
    team_id: UUID
    team_version_id: UUID | None = None


class MayaTeamChatEntry(ClosedModel):
    kind: Literal["maya_team"]
    team_id: UUID


ChatEntry = Annotated[
    AgentChatEntry | SavedTeamChatEntry | MayaTeamChatEntry, Field(discriminator="kind")
]


class CreateChat(ClosedModel):
    version_id: UUID | None = None
    entry: ChatEntry | None = None
    # Every Chat is private; the field stays only so an explicit value is checked.
    chat_visibility: Literal["private"] = "private"

    @model_validator(mode="after")
    def validate_entry(self) -> "CreateChat":
        if (self.version_id is None) == (self.entry is None):
            raise ValueError("Select exactly one Chat entry.")
        return self


CHAT_TITLE_MAX_LENGTH = 80


class UpdateChat(ClosedModel):
    """Rename or pin a Chat; a field left out keeps its value."""

    title: str | None = Field(default=None, max_length=CHAT_TITLE_MAX_LENGTH)
    pinned: bool | None = None

    @model_validator(mode="after")
    def validate_change(self) -> "UpdateChat":
        if not self.model_fields_set:
            raise ValueError("Change the title, the pin or both.")
        if "pinned" in self.model_fields_set and self.pinned is None:
            raise ValueError("Pinned is true or false.")
        return self


class SendChat(ClosedModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    message: str = Field(min_length=1)
    routing: TeamRouting | None = None


class StreamChat(ClosedModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    message: str = Field(min_length=1)
    routing: TeamRouting | None = None


class ComponentStatus(ClosedModel):
    key: ComponentKey
    mode: ComponentMode
    switchable: bool
    status: Literal["unchecked", "ready", "failed", "deferred"]
    checked_at: datetime | None = None
    safe_error_code: str | None = None


class ProviderSettings(ClosedModel):
    revision: int
    credential_ready: bool
    components: list[ComponentStatus]


class UpdateProviderSettings(ClosedModel):
    expected_revision: int = Field(ge=0)
    component: ComponentKey | None = None
    mode: ComponentMode | None = None
    api_key: SecretStr | None = None


class CheckProvider(ClosedModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    confirm_real_call: bool = False


class LiveHeartbeat(ClosedModel):
    lease_id: UUID
    controller_epoch: UUID | None = None
    active: bool = True


class LiveSummary(ClosedModel):
    course_id: UUID
    debate_id: UUID
    topic: str


class LiveParticipant(ClosedModel):
    id: UUID
    name: str
    avatar_config: AvatarConfig


class LiveTurn(ClosedModel):
    id: UUID
    participant_id: UUID
    round_no: int
    turn_index: int
    speech: str
    audio_url: str | None


class LiveSnapshot(ClosedModel):
    interaction_url: str | None = None
    active: bool
    debate_id: UUID
    sequence: int
    server_time: datetime
    participants: list[LiveParticipant]
    turns: list[LiveTurn]
    playback: PlaybackStateDTO | None
