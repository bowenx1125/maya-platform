"""Provider-neutral Debate API and setup DTOs.

Only frozen platform display data is represented here.  Provider/model names,
raw responses, external voice IDs and storage paths deliberately have no DTO
field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.schemas import AvatarConfig

Stance = Literal["support", "oppose", "neutral"]
StanceMode = Literal["assigned", "open"]
Slot = Literal["A", "B", "C", "D", "E"]
RULE_SET_ID = "ordered_multi_agent_rounds_demo_v1"


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DebateParticipantInput(_ClosedModel):
    """A teacher's ordered selection for a draft."""

    agent_id: UUID
    stance_mode: StanceMode
    assigned_stance: Stance | None = None
    teacher_note: str = ""

    @model_validator(mode="after")
    def validate_stance_shape(self) -> DebateParticipantInput:
        if self.stance_mode == "assigned" and self.assigned_stance is None:
            raise ValueError("assigned stance is required when stance_mode is assigned")
        if self.stance_mode == "open" and self.assigned_stance is not None:
            raise ValueError("assigned stance must be empty when stance_mode is open")
        return self


class DebateDraftRequest(_ClosedModel):
    topic: str = Field(
        min_length=1,
        description=(
            "Non-empty English debate topic using Latin-script letters; Unicode Latin "
            "diacritics, numbers, ordinary whitespace and punctuation are allowed. "
            "Control and non-Latin letter characters are rejected at the domain boundary."
        ),
    )
    participants: list[DebateParticipantInput] = Field(min_length=2, max_length=5)
    round_count: Literal[2]
    total_duration_seconds: None = None
    turn_duration_seconds: None = None

    @model_validator(mode="after")
    def validate_selection(self) -> DebateDraftRequest:
        if not self.topic.strip():
            raise ValueError("topic must not be blank")
        ids = [item.agent_id for item in self.participants]
        if len(set(ids)) != len(ids):
            raise ValueError("participants must be unique")
        return self


class DebateDraftUpdateRequest(DebateDraftRequest):
    expected_revision: int = Field(ge=0)


class DebateStartRequest(_ClosedModel):
    expected_revision: int = Field(ge=0)
    expected_current_audio_debate_id: UUID | None
    confirm_previous_audio_cleanup: bool


class PlaybackCommandRequest(_ClosedModel):
    expected_control_version: int = Field(ge=0)


class PlaybackControlRequest(_ClosedModel):
    """Teacher control CAS shared by pause/resume/finish routes.

    ``expected_current_turn_id`` is optional because a finish command may be
    issued while the controller is parked without a current item.  The
    service still revalidates the live row under its writer lock; this field
    is only an additional stale-tab fence, never a client-selected successor.
    """

    expected_control_version: int = Field(ge=0)
    expected_current_turn_id: UUID | None = None


FinishDebateRequest = PlaybackControlRequest


class AdvancePlaybackRequest(_ClosedModel):
    expected_control_version: int = Field(ge=0)
    expected_current_turn_id: UUID


class DebatePlaybackResource(_ClosedModel):
    playback_url: str = Field(
        pattern=(
            r"^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        )
    )
    expires_at: datetime


class RetrievalSource(_ClosedModel):
    source_filename: str
    chunk_id: UUID = None  # type: ignore[assignment]


class DebateParticipant(_ClosedModel):
    """Frozen participant display projection, without supplier metadata."""

    id: UUID
    slot: Slot
    order_index: int = Field(ge=0, le=4)
    agent_id: UUID
    agent_name: str
    agent_version_id: UUID
    version_label: str = Field(pattern=r"^V[0-9]+\.[0-9]+$")
    knowledge_snapshot_id: UUID
    avatar_config: AvatarConfig
    effective_voice_profile_id: UUID | None
    voice_fallback_active: bool
    stance_mode: StanceMode
    initial_stance: Stance | None = None
    current_stance: Stance | None = None
    current_position_summary: str = ""


class DebateSummary(_ClosedModel):
    id: UUID
    course_id: UUID
    topic: str
    status: Literal[
        "draft",
        "running",
        "debate_finished",
        "completed",
        "failed",
        "stopped",
    ]
    created_at: datetime


class PlaybackState(_ClosedModel):
    status: Literal[
        "preparing", "ready", "playing", "paused", "waiting_next", "completed", "stopped"
    ]
    mode: Literal["live", "replay"]
    current_turn_id: UUID | None = None
    cursor_ms: int = Field(ge=0)
    playback_rate: float = Field(ge=0.95, le=1.25)
    control_version: int = Field(ge=0)
    next_turn_ready: bool


class DebateTurn(_ClosedModel):
    id: UUID
    participant_id: UUID
    round_no: int = Field(ge=1, le=2)
    turn_index: int = Field(ge=0)
    speech: str
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"]
    sources: list[RetrievalSource]
    translated_text: str | None = None
    playback_resource: DebatePlaybackResource | None = None


class Transcript(_ClosedModel):
    debate_id: UUID
    turns: list[DebateTurn]
    audio_retained: bool


class DebateDetail(DebateSummary):
    revision: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    rule_set_id: Literal["ordered_multi_agent_rounds_demo_v1"]
    participants: list[DebateParticipant]
    public_turns: list[DebateTurn]
    playback: PlaybackState
    interaction_status: Literal["closed", "open", "finalized"]
    insight_status: Literal["not_started", "generating", "ready", "failed"]
    report_status: Literal["not_started", "generating", "ready", "failed"]


class TurnPlanEntry(_ClosedModel):
    """Deterministic internal plan entry shared with generation/playback."""

    participant_id: UUID
    slot: Slot
    order_index: int = Field(ge=0, le=4)
    round_no: Literal[1, 2]
    turn_index: int = Field(ge=0)
    predecessor_turn_indexes: tuple[int, ...] = ()
    question_type: Literal["agent", "audience_reflection", "none"] = "none"
    question_target_participant_id: UUID | None = None


class DebateRuleSnapshot(_ClosedModel):
    """Versioned immutable rule data stored on each Debate."""

    rule_set_id: Literal["ordered_multi_agent_rounds_demo_v1"] = (
        "ordered_multi_agent_rounds_demo_v1"
    )
    round_count: Literal[2] = 2
    min_participants: Literal[2] = 2
    max_participants: Literal[5] = 5
    min_words: Literal[80] = 80
    max_words: Literal[200] = 200
    target_min_words: Literal[160] = 160
    target_max_words: Literal[185] = 185


__all__ = [
    "AdvancePlaybackRequest",
    "DebateDetail",
    "DebateDraftRequest",
    "DebateDraftUpdateRequest",
    "DebateParticipant",
    "DebateParticipantInput",
    "DebatePlaybackResource",
    "DebateRuleSnapshot",
    "DebateStartRequest",
    "DebateSummary",
    "DebateTurn",
    "PlaybackCommandRequest",
    "PlaybackState",
    "PlaybackControlRequest",
    "FinishDebateRequest",
    "RetrievalSource",
    "RULE_SET_ID",
    "Transcript",
    "TurnPlanEntry",
]
