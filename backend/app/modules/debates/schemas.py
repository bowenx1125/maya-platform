"""Provider-neutral Debate API and setup DTOs.

Only frozen platform display data is represented here.  Provider/model names,
raw responses, external voice IDs and storage paths deliberately have no DTO
field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.modules.agents.schemas import AvatarConfig
from app.modules.debates.generation.evidence_trace import EvidenceTraceV1
from app.modules.debates.generation.types import (
    MutualLearningSynthesisV1,
    MutualLearningTurnResultV1,
)
from app.modules.debates.generation_params import DebateLLMParams, DebateVoiceParams

Stance = Literal["support", "oppose", "neutral"]
StanceMode = Literal["assigned", "open"]
Slot = Literal["A", "B", "C", "D", "E"]
RULE_SET_ID_MUTUAL_LEARNING: Literal["ordered_multi_expert_mutual_learning_v1"] = (
    "ordered_multi_expert_mutual_learning_v1"
)
RuleSetId = Literal["ordered_multi_expert_mutual_learning_v1"]
RULE_SET_ID: Literal["ordered_multi_expert_mutual_learning_v1"] = RULE_SET_ID_MUTUAL_LEARNING
NEW_DEBATE_RULE_SET_ID: Literal["ordered_multi_expert_mutual_learning_v1"] = (
    RULE_SET_ID_MUTUAL_LEARNING
)
MOCK_RETRIEVAL_POLICY_ID: Literal["mock_lexical_anchor_v2"] = "mock_lexical_anchor_v2"


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
        # Typed errors, so the Debate form can name the Agent and the reason.
        if self.stance_mode == "assigned" and self.assigned_stance is None:
            raise PydanticCustomError(
                "assigned_stance_missing",
                "assigned stance is required when stance_mode is assigned",
            )
        if self.stance_mode == "open" and self.assigned_stance is not None:
            raise PydanticCustomError(
                "assigned_stance_unexpected",
                "assigned stance must be empty when stance_mode is open",
            )
        return self


class TeachingPrompts(_ClosedModel):
    zh: str
    en: str


class DebateRulesetContract(_ClosedModel):
    """The code-owned execution contract per language; read-only for teachers."""

    zh: str
    en: str


class DebateRulesetDefaults(_ClosedModel):
    """The editable default Ruleset plus the contract every new Debate adds to it."""

    zh: str
    en: str
    contract: DebateRulesetContract


class DebateLLMParamSpec(_ClosedModel):
    name: Literal[
        "temperature",
        "top_p",
        "presence_penalty",
        "frequency_penalty",
        "repetition_penalty",
        "max_tokens",
        "enable_thinking",
        "seed",
    ]
    kind: Literal["float", "int", "bool"]
    # The env default; null means not sent unless the teacher sets a value.
    default: float | int | bool | None = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool
    exclusive_maximum: bool
    step: float | None = None
    # False: stored with the Debate but never sent to the model.
    sent: bool


class DebateVoiceParamSpec(_ClosedModel):
    name: Literal["rate", "instruction", "seed"]
    kind: Literal["float", "int", "text"]
    default: float | int | str | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    max_length: int | None = None


class DebateLLMDefaults(_ClosedModel):
    params: list[DebateLLMParamSpec]
    # Cloned voices only; every Debate plays at 1.0.
    voice_params: list[DebateVoiceParamSpec]


class DebateDraftRequest(_ClosedModel):
    topic: str = Field(
        min_length=1, description="Non-empty topic; any script or symbols are accepted."
    )
    background: str = ""
    teaching_prompts: TeachingPrompts | None = None
    participants: list[DebateParticipantInput] = Field(min_length=2, max_length=5)
    round_count: Literal[4] = 4
    output_language: Literal["en", "zh"] = "zh"
    turn_protocol: Literal["segments_v2"] | None = "segments_v2"
    rule_set_id: RuleSetId = NEW_DEBATE_RULE_SET_ID
    total_duration_seconds: None = None
    turn_duration_seconds: None = None
    # The parameter card's values; omitted means the DEBATE_LLM_* defaults.
    llm_params: DebateLLMParams | None = None
    # Voice card values (cloned voices); omitted means the DEBATE_TTS_* defaults.
    voice_params: DebateVoiceParams | None = None
    # Spoken length the whole Debate aims for; omitted means five minutes.
    target_minutes: int | None = Field(default=None, ge=3, le=10)

    @field_validator("teaching_prompts", mode="before")
    @classmethod
    def ignore_echoed_contract(cls, value: object) -> object:
        # The ruleset read returns the read-only contract beside the editable
        # text, and an editor that sends that object back must still create
        # the Debate. The server never reads the echoed contract.
        if isinstance(value, dict) and "contract" in value:
            return {key: item for key, item in value.items() if key != "contract"}
        return value

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        if not value.strip():
            raise PydanticCustomError("topic_blank", "topic must not be blank")
        return value

    @field_validator("participants")
    @classmethod
    def validate_participants(
        cls, value: list[DebateParticipantInput]
    ) -> list[DebateParticipantInput]:
        ids = [item.agent_id for item in value]
        if len(set(ids)) != len(ids):
            raise PydanticCustomError("participants_duplicate", "participants must be unique")
        return value


class DebateDraftUpdateRequest(DebateDraftRequest):
    expected_revision: int = Field(ge=0)


class DebateStartRequest(_ClosedModel):
    expected_revision: int = Field(ge=0)
    expected_current_audio_debate_id: UUID | None
    confirm_previous_audio_cleanup: bool
    # Retained for old clients; it may only confirm the draft's saved language.
    output_language: Literal["en", "zh"] | None = None


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


class ReleaseDebateRequest(_ClosedModel):
    """Explicit confirmation for recovering one stuck classroom playback.

    Recovery used to be a CLI with a literal ``--confirm RESET`` token, so a
    stuck debate could only be cleared by someone with a shell on the server.
    That made an ordinary classroom accident -- a lesson left running -- into
    something no teacher could undo, and it blocked every later debate on that
    course. The guard the token provided is kept: this must be asked for
    deliberately, by a teacher of this course, and it is audited.
    """

    confirm_release: Literal[True]


class AdvancePlaybackRequest(_ClosedModel):
    expected_control_version: int = Field(ge=0)
    expected_current_turn_id: UUID


class PrefetchNextAudioRequest(_ClosedModel):
    """A controller ticket for one speech's audio, downloaded ahead of playback.

    PR A2 (2026-10-24): the Immerse stage downloads every ready speech in
    order, whatever the playback state, by naming ``turn_id``. The older form
    (no ``turn_id``) still names the adjacent successor of the current turn.
    """

    controller_epoch: UUID
    turn_id: UUID | None = None
    expected_control_version: int | None = Field(default=None, ge=0)
    expected_current_turn_id: UUID | None = None

    @model_validator(mode="after")
    def _names_a_turn(self) -> PrefetchNextAudioRequest:
        if self.turn_id is None and (
            self.expected_control_version is None or self.expected_current_turn_id is None
        ):
            raise PydanticCustomError(
                "prefetch_turn_missing",
                "Name turn_id, or the expected control version and current turn.",
            )
        return self


class PrefetchedNextAudio(_ClosedModel):
    turn_id: UUID
    media_url: str = Field(
        pattern=r"^/api/v1/debates/[0-9a-f-]{36}/audio/[0-9a-f-]{36}\?media_ticket=[A-Za-z0-9_-]{43}(?:&format=mp3)?$"
    )


class RetryPreparationRequest(_ClosedModel):
    expected_control_version: int = Field(ge=0)
    turn_id: UUID


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


DebateCardDropReason = Literal[
    "length_limit",
    "language_choice",
    "output_format",
    "debate_procedure",
    "duplicate_translation",
]


class DebateCardDrop(_ClosedModel):
    """AGENT.md content the card left out, and why."""

    excerpt: str
    reason: DebateCardDropReason


class DebateCard(_ClosedModel):
    """The persona compiled once from the participant's frozen AGENT.md."""

    identity: str
    position: str
    reasoning: list[str]
    speaking_style: str
    voice_style: str | None
    dropped: list[DebateCardDrop]


class DebateParticipant(_ClosedModel):
    """Frozen participant display projection, without supplier metadata."""

    id: UUID
    slot: Slot
    order_index: int = Field(ge=0, le=4)
    agent_id: UUID | None
    agent_name: str
    agent_version_id: UUID | None
    version_label: str = Field(pattern=r"^V[0-9]+\.[0-9]+$")
    knowledge_snapshot_id: UUID
    avatar_config: AvatarConfig
    effective_voice_profile_id: UUID | None
    voice_fallback_active: bool
    stance_mode: StanceMode
    initial_stance: Stance | None = None
    current_stance: Stance | None = None
    current_position_summary: str = ""
    # Null for a Debate created before cards. "fallback" means the turns send
    # the original AGENT.md; only "ready" carries a card.
    card_status: Literal["compiling", "ready", "fallback"] | None = None
    card: DebateCard | None = None


class DebateStall(_ClosedModel):
    """The turn that stopped a draft warming, and why."""

    turn_id: UUID
    round_no: int = Field(ge=1)
    safe_error_code: str


class DebatePreviewProgress(_ClosedModel):
    prepared_turns: int = Field(ge=0)
    expected_turns: int = Field(ge=1)
    ready: bool


class DebateSummary(_ClosedModel):
    id: UUID
    course_id: UUID
    topic: str
    round_count: int = Field(ge=2, le=5)
    status: Literal[
        "draft",
        "running",
        "debate_finished",
        "completed",
        "failed",
        "stopped",
    ]
    created_at: datetime
    # How much of this Debate's plan is already generated. A draft warms in the
    # background, so the list can say how ready it is rather than only that it
    # is a draft.
    audio_restore_needed: bool = False
    prepared_turns: int = Field(default=0, ge=0)
    expected_turns: int = Field(default=0, ge=0)
    preview: DebatePreviewProgress | None = None
    # Warming stops at the first turn that will not generate and changes no
    # status, so a stalled draft used to be indistinguishable from one still
    # thinking. This is read from that turn, not stored on the debate.
    stall: DebateStall | None = None


class PlaybackState(_ClosedModel):
    status: Literal[
        "preparing", "ready", "playing", "paused", "waiting_next", "completed", "stopped"
    ]
    mode: Literal["live", "replay"]
    current_turn_id: UUID | None = None
    cursor_ms: int = Field(ge=0)
    control_version: int = Field(ge=0)
    next_turn_ready: bool


class AdvancedPlayback(PlaybackState):
    """Next's answer: the new state and, when its audio is ready, the URL.

    ``media_url`` carries a controller ticket for the new current speech, so
    the stage can start it without waiting for the media handshake.
    """

    media_url: str | None = Field(
        default=None,
        pattern=r"^/api/v1/debates/[0-9a-f-]{36}/audio/[0-9a-f-]{36}\?media_ticket=[A-Za-z0-9_-]{43}(?:&format=mp3)?$",
    )


class DebateSegment(_ClosedModel):
    text: str
    source_ids: list[str]
    reply_to: str | None
    reply_text: str | None = None
    # Optional for byte-compatible reads of older segment_turn_v2 results.
    # New provider output includes the mode; omitted values remain ungraded.
    support_mode: Literal["direct", "contextual", "no_match"] | None = None


class SegmentTurnPublic(_ClosedModel):
    schema_version: Literal["segment_turn_v2"] = "segment_turn_v2"
    segments: list[DebateSegment]


class SegmentSourceDetail(_ClosedModel):
    source_id: str
    source_filename: str
    excerpt: str
    query_text: str | None = None
    version_label: str


class PreviewTurn(_ClosedModel):
    id: UUID
    participant_id: UUID
    round_no: int
    turn_index: int
    speech: str
    generation_status: str
    audio_ready: bool
    safe_error_code: str | None = None
    segments: list[DebateSegment] = Field(default_factory=list)
    sources: list[SegmentSourceDetail] = Field(default_factory=list)


class DebateTurn(_ClosedModel):
    id: UUID
    participant_id: UUID
    round_no: int = Field(ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    turn_index: int = Field(ge=0)
    speech: str
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"]
    sources: list[RetrievalSource]
    playback_resource: DebatePlaybackResource | None = None
    audio_ready: bool | None = None
    mutual_learning: MutualLearningTurnResultV1 | None = None
    evidence_trace: list[EvidenceTraceV1] | None = None
    segment_turn: SegmentTurnPublic | None = None
    source_details: list[SegmentSourceDetail] = Field(default_factory=list)


class Transcript(_ClosedModel):
    debate_id: UUID
    turns: list[DebateTurn]
    audio_retained: bool


class DebateDetail(DebateSummary):
    background: str = ""
    teaching_protocol: Literal["four_round_v1"] | None = None
    output_language: Literal["en", "zh"] = "en"
    # Effective protocol. segments_v2 for every new debate; a pre-segments row
    # reports what it really runs (legacy_v1) instead of a bare null.
    # Nullable in the type only so existing clients keep compiling; never None.
    turn_protocol: Literal["legacy_v1", "segments_v2"] | None = "segments_v2"
    preview_turns: list[PreviewTurn] = Field(default_factory=list)
    final_input_frozen: bool = False
    revision: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    rule_set_id: RuleSetId
    participants: list[DebateParticipant]
    public_turns: list[DebateTurn]
    playback: PlaybackState
    interaction_status: Literal["closed", "open", "finalized"]
    insight_status: Literal["not_started", "generating", "ready", "failed"]
    report_status: Literal["not_started", "generating", "ready", "failed"]
    mutual_learning_synthesis: MutualLearningSynthesisV1 | None = None


class DebateCleanupRequest(_ClosedModel):
    expected_revision: int = Field(ge=0)
    expected_control_version: int = Field(ge=0)


class DebateCleanupResult(_ClosedModel):
    debate_id: UUID
    cleanup_status: Literal["complete", "pending"]
    revision: int = Field(ge=0)
    control_version: int = Field(ge=0)
    deleted_file_count: int = Field(ge=0)
    pending_file_count: int = Field(ge=0)
    regenerable_turn_ids: list[UUID] = Field(default_factory=list)


class TurnPlanEntry(_ClosedModel):
    """Deterministic internal plan entry shared with generation/playback."""

    participant_id: UUID
    slot: Slot
    order_index: int = Field(ge=0, le=4)
    round_no: int = Field(ge=1)
    turn_index: int = Field(ge=0)
    predecessor_turn_indexes: tuple[int, ...] = ()
    question_type: Literal["agent", "audience_reflection", "none"] = "none"
    question_target_participant_id: UUID | None = None
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] = "opening"
    is_final_round: bool = False


class DebateRuleSnapshot(_ClosedModel):
    """Versioned immutable rule data stored on each Debate."""

    rule_set_id: RuleSetId = "ordered_multi_expert_mutual_learning_v1"
    retrieval_policy_id: Literal["mock_lexical_anchor_v2"] | None = MOCK_RETRIEVAL_POLICY_ID
    round_count: int = Field(default=2, ge=2, le=5)
    turn_protocol: Literal["segments_v2"] | None = "segments_v2"
    teaching_protocol: Literal["four_round_v1"] | None = None
    min_participants: Literal[2] = 2
    max_participants: Literal[5] = 5
    min_words: Literal[80] = 80
    max_words: Literal[200] = 200
    target_min_words: Literal[160] = 160
    target_max_words: Literal[185] = 185

    @model_validator(mode="after")
    def validate_versioned_retrieval_policy(self) -> DebateRuleSnapshot:
        if self.round_count < 2:
            raise ValueError("mutual-learning snapshots require at least two rounds")
        return self


__all__ = [
    "AdvancePlaybackRequest",
    "DebateDetail",
    "DebateDraftRequest",
    "DebateDraftUpdateRequest",
    "DebateParticipant",
    "DebateParticipantInput",
    "DebatePlaybackResource",
    "DebateRuleSnapshot",
    "DebateRulesetContract",
    "DebateRulesetDefaults",
    "DebateStartRequest",
    "DebateSummary",
    "DebateTurn",
    "PlaybackCommandRequest",
    "PlaybackState",
    "PlaybackControlRequest",
    "RetryPreparationRequest",
    "FinishDebateRequest",
    "ReleaseDebateRequest",
    "RetrievalSource",
    "RULE_SET_ID",
    "RULE_SET_ID_MUTUAL_LEARNING",
    "RuleSetId",
    "MOCK_RETRIEVAL_POLICY_ID",
    "Transcript",
    "TurnPlanEntry",
]


class RegenerateTurnAudioRequest(_ClosedModel):
    expected_revision: int = Field(ge=0)


class RegenerateTurnAudioResult(_ClosedModel):
    operation: Literal["debate_turn_tts"] = "debate_turn_tts"
    status: Literal["completed", "already_ready", "queued", "failed", "stale", "not_found"]
    debate_id: UUID
    turn_id: UUID
    revision: int | None
    operation_id: UUID | None
    audio_ready: bool
    audio_duration_ms: int | None
    safe_error_code: str | None
