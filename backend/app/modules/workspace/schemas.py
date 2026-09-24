from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.agents.schemas import AvatarConfig
from app.modules.debates.playback.schemas import PlaybackStateDTO


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
    available: bool = True


class ChatSource(ClosedModel):
    chunk_id: UUID
    filename: str
    excerpt: str


class ChatTurn(ClosedModel):
    id: UUID
    user_text: str
    assistant_text: str | None
    mode: ComponentMode
    state: Literal["pending", "ready", "failed", "acceptance_unknown"]
    sources: list[ChatSource]
    safe_error_code: str | None


class ChatSession(ClosedModel):
    id: UUID
    agent: ChatAgent
    revision: int
    turns: list[ChatTurn]
    created_at: datetime


class CreateChat(ClosedModel):
    version_id: UUID


class SendChat(ClosedModel):
    request_id: UUID
    expected_revision: int = Field(ge=0)
    message: str = Field(min_length=1)


class StreamChat(ClosedModel):
    # ``lang`` stays a plain string so an unsupported value can return the
    # chat language code.  A Literal would collapse that into a generic
    # malformed-request validation error.
    request_id: UUID
    expected_revision: int = Field(ge=0)
    message: str = Field(min_length=1)
    lang: str = Field(min_length=1)


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
    active: bool
    debate_id: UUID
    sequence: int
    server_time: datetime
    participants: list[LiveParticipant]
    turns: list[LiveTurn]
    playback: PlaybackStateDTO | None
