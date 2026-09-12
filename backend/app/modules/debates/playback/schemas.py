"""Closed provider-neutral playback and WebSocket schemas.

These models intentionally mirror the frozen playback wire contracts. Internal
generation/voice details never cross this file's public DTO boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.debates.generation.evidence_trace import EvidenceTraceV1
from app.modules.debates.schemas import SegmentSourceDetail, SegmentTurnPublic


class ClosedModel(BaseModel):
    """Schema objects are closed so accidental supplier fields fail loudly."""

    model_config = ConfigDict(extra="forbid")


PlaybackStatus = Literal[
    "preparing", "ready", "playing", "paused", "waiting_next", "completed", "stopped"
]
PlaybackMode = Literal["live", "replay"]
PlaybackAction = Literal["start", "resume", "next", "replay"]
AvatarMotion = Literal["idle", "listening", "speaking", "thinking", "nod_yes"]
AvatarExpression = Literal["neutral", "attentive", "happy", "serious_angry", "sad"]
AvatarStrength = Literal["low", "medium", "high"]


class PlaybackStateDTO(ClosedModel):
    status: PlaybackStatus
    mode: PlaybackMode
    current_turn_id: UUID | None = None
    cursor_ms: int = Field(ge=0)
    playback_rate: float = Field(ge=0.95, le=1.25)
    control_version: int = Field(ge=0)
    next_turn_ready: bool


class RetrievalSourceDTO(ClosedModel):
    source_filename: str = Field(min_length=1)
    chunk_id: UUID | None = None


class PublicTurnDTO(ClosedModel):
    audio_ready: bool | None = None
    id: UUID
    participant_id: UUID
    round_no: int = Field(ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    round_count: int | None = Field(default=None, ge=2, le=5)
    turn_index: int = Field(ge=0)
    speech: str = Field(min_length=1)
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"]
    sources: list[RetrievalSourceDTO]
    evidence_trace: list[EvidenceTraceV1] | None = None
    segment_turn: SegmentTurnPublic | None = None
    source_details: list[SegmentSourceDetail] = Field(default_factory=list)


class AvatarStateDTO(ClosedModel):
    participant_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    motion_state: AvatarMotion
    expression: AvatarExpression
    expression_strength: AvatarStrength | None = None


class DebatePlaybackResourceDTO(ClosedModel):
    playback_url: str = Field(
        pattern=(
            r"^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        )
    )
    expires_at: datetime


class PlaybackStartedPayload(ClosedModel):
    audio_ready: bool | None = None
    turn_id: UUID
    slot: Literal["A", "B", "C", "D", "E"] | None = None
    round_no: int | None = Field(default=None, ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    round_count: int | None = Field(default=None, ge=2, le=5)
    speech: str = Field(min_length=1)
    sources: list[RetrievalSourceDTO]
    evidence_trace: list[EvidenceTraceV1] | None = None
    segment_turn: SegmentTurnPublic | None = None
    source_details: list[SegmentSourceDetail] = Field(default_factory=list)
    playback_url: str = Field(
        pattern=(
            r"^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        )
    )
    avatar_states: list[AvatarStateDTO] = Field(min_length=1)
    cursor_ms: Literal[0] = 0
    playback_rate: float | None = Field(default=None, ge=0.95, le=1.25)


class PlaybackCursorPayload(ClosedModel):
    turn_id: UUID
    cursor_ms: int = Field(ge=0)
    control_version: int = Field(ge=0)
    playback_rate: float | None = Field(default=None, ge=0.95, le=1.25)


class PlaybackWaitingNextPayload(ClosedModel):
    """Readiness-only signal for the teacher's next-turn gate.

    The successor identity and all prepared content remain server-side until
    the teacher commits the REST Next CAS and the browser acknowledges media.
    """

    mode: PlaybackMode
    completed_turn_id: UUID
    control_version: int = Field(ge=0)
    next_turn_ready: bool


class ReplayPayload(ClosedModel):
    scope: Literal["turn", "all"]
    turn_id: UUID | None
    control_version: int | None = Field(default=None, ge=0)


class DebateStartedPayload(ClosedModel):
    rule_set_id: Literal["ordered_multi_expert_mutual_learning_v1"]
    round_count: int | None = Field(default=None, ge=2, le=5)
    participants: list[ParticipantSlotDTO] | None = Field(default=None, min_length=2)
    participant_slots: list[ParticipantSlotDTO] | None = Field(default=None, min_length=2)


class ParticipantSlotDTO(ClosedModel):
    participant_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    order_index: int | None = Field(default=None, ge=0, le=4)
    name: str | None = Field(default=None, min_length=1)


class RoundStartedPayload(ClosedModel):
    round_no: int = Field(ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    round_count: int | None = Field(default=None, ge=2, le=5)
    turn_count: int | None = Field(default=None, ge=1)


class TurnPreparingPayload(ClosedModel):
    turn_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    round_no: int = Field(ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    round_count: int | None = Field(default=None, ge=2, le=5)
    stage: Literal["rag", "llm", "tts"] | None = None


class TurnReadyPayload(ClosedModel):
    turn_id: UUID
    slot: Literal["A", "B", "C", "D", "E"]
    round_no: int | None = Field(default=None, ge=1)
    phase: Literal["opening", "exchange", "final_integration", "rebuttal"] | None = None
    round_count: int | None = Field(default=None, ge=2, le=5)
    audio_ready: Literal[True] = True
    retrieval_status: Literal["matched", "no_match"]
    grounding_mode: Literal["rag_grounded", "mixed", "general_reasoning"] | None = None
    audio_duration_ms: int | None = Field(default=None, ge=0)


class ErrorPayload(ClosedModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    request_id: UUID | None = None
    recoverable: bool | None = None


class SnapshotInteractionDTO(ClosedModel):
    status: Literal["closed", "open", "finalized"]
    votes: list[SnapshotVoteAggregateDTO]
    barrage_count: int = Field(ge=0)
    total_votes: int = Field(ge=0)


class SnapshotVoteAggregateDTO(ClosedModel):
    participant_id: UUID
    count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)


class SnapshotInsightDTO(ClosedModel):
    status: Literal["not_started", "generating", "ready", "failed"]
    included_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)
    snapshot_id: UUID | None
    revision: int | None = Field(ge=1)


class SnapshotReportDTO(ClosedModel):
    generation_status: Literal["not_started", "generating", "ready", "failed"]
    latest_attempt_status: Literal["not_started", "generating", "ready", "failed"]
    insight: SnapshotInsightDTO
    active_revision_id: UUID | None
    current_success_revision_id: UUID | None
    current_success_word_count: int | None = Field(ge=0)


class InteractionOpenedPayload(ClosedModel):
    window_id: UUID
    aggregate_zeros: list[SnapshotVoteAggregateDTO]
    status: Literal["open"]


class InteractionVoteCreatedPayload(ClosedModel):
    participant_id: UUID
    slot: Literal["A", "B", "C", "D", "E"] | None = None
    new_count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)
    total_votes: int = Field(ge=0)


class InteractionBarrageCreatedPayload(ClosedModel):
    message_id: UUID
    nickname: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    sequence: int = Field(ge=1)


class InteractionClosedTotals(ClosedModel):
    total_votes: int = Field(ge=0)
    total_barrages: int = Field(ge=0)


class InteractionClosedPayload(ClosedModel):
    totals: InteractionClosedTotals
    message_count: int = Field(ge=0)
    input_hash: str = Field(min_length=1)


class BarrageInsightStartedPayload(ClosedModel):
    revision: int = Field(ge=1)
    status: Literal["generating"] | None = None


class BarrageInsightCompletedPayload(ClosedModel):
    snapshot_id: UUID
    revision: int = Field(ge=1)
    status: Literal["ready"]
    included_count: int = Field(ge=0)
    filtered_count: int = Field(ge=0)


class BarrageInsightFailedPayload(ClosedModel):
    revision: int = Field(ge=1)
    status: Literal["failed"]
    included_count: int | None = Field(default=None, ge=0)
    filtered_count: int | None = Field(default=None, ge=0)
    safe_error_code: str = Field(min_length=1)


class ReportStartedPayload(ClosedModel):
    revision_id: UUID
    status: Literal["generating"]


class ReportCompletedPayload(ClosedModel):
    revision_id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["ready"]
    current_success_revision_id: UUID
    latest_attempt_status: Literal["ready"]
    word_count: int = Field(ge=0)


class ReportFailedPayload(ClosedModel):
    revision_id: UUID
    revision_no: int = Field(ge=1)
    status: Literal["failed"]
    current_success_revision_id: UUID | None
    latest_attempt_status: Literal["failed"]
    safe_error_code: str = Field(min_length=1)


class TranslationBatchStartedPayload(ClosedModel):
    batch_id: UUID
    status: Literal["running"]
    total_items: int = Field(ge=0)
    succeeded_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class TranslationBatchCompletedPayload(ClosedModel):
    batch_id: UUID
    status: Literal["completed", "partial"]
    total_items: int = Field(ge=0)
    succeeded_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class TranslationBatchFailedPayload(ClosedModel):
    batch_id: UUID
    status: Literal["failed"]
    total_items: int = Field(ge=0)
    succeeded_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class DebateTerminalPayload(ClosedModel):
    final_states: dict[str, object]
    downstream_outcome: Literal["failed", "stopped"]
    safe_error_code: str | None = None


class SnapshotPayload(ClosedModel):
    final_input_frozen: bool = False
    debate_status: Literal["draft", "running", "debate_finished", "completed", "failed", "stopped"]
    playback_status: PlaybackStatus
    interaction_status: Literal["closed", "open", "finalized"]
    insight_status: Literal["not_started", "generating", "ready", "failed"]
    report_status: Literal["not_started", "generating", "ready", "failed"]
    public_turns: list[PublicTurnDTO]
    playback: PlaybackStateDTO
    interaction: SnapshotInteractionDTO
    report: SnapshotReportDTO
    latest_sequence: int = Field(ge=0)


class WSCommandBase(ClosedModel):
    command_id: UUID
    command_type: str
    command_version: Literal[1] = 1
    debate_id: UUID
    expected_control_version: int = Field(ge=0)


class ControllerAcquireCommand(WSCommandBase):
    command_type: Literal["playback.controller.acquire"] = "playback.controller.acquire"


class MediaPrepareCommand(WSCommandBase):
    command_type: Literal["playback.media.prepare"] = "playback.media.prepare"
    controller_epoch: UUID
    turn_id: UUID
    playback_action: PlaybackAction


class StartedAckCommand(WSCommandBase):
    command_type: Literal["playback.started_ack"] = "playback.started_ack"
    controller_epoch: UUID
    turn_id: UUID
    playback_action: PlaybackAction


class EndedAckCommand(WSCommandBase):
    command_type: Literal["playback.ended_ack"] = "playback.ended_ack"
    controller_epoch: UUID
    turn_id: UUID


class PlayFailedCommand(WSCommandBase):
    command_type: Literal["playback.play_failed"] = "playback.play_failed"
    controller_epoch: UUID
    turn_id: UUID
    playback_action: PlaybackAction
    failure_phase: Literal["pre_ack", "post_ack"]
    cursor_ms: int = Field(ge=0)
    safe_client_code: Literal[
        "autoplay_blocked",
        "not_supported",
        "decode_error",
        "network_error",
        "aborted",
        "unknown",
    ]


WSCommand = Annotated[
    ControllerAcquireCommand
    | MediaPrepareCommand
    | StartedAckCommand
    | EndedAckCommand
    | PlayFailedCommand,
    Field(discriminator="command_type"),
]


class PrivateResultBase(ClosedModel):
    message_id: UUID
    message_type: str
    result_version: Literal[1] = 1
    debate_id: UUID
    occurred_at: datetime
    command_id: UUID | None = None


class ControllerAcquiredResult(PrivateResultBase):
    message_type: Literal["controller.acquired"] = "controller.acquired"
    command_id: UUID
    controller_epoch: UUID
    control_version: int = Field(ge=0)


class MediaPreparedResult(PrivateResultBase):
    message_type: Literal["media.prepared"] = "media.prepared"
    command_id: UUID
    controller_epoch: UUID
    turn_id: UUID
    media_url: str = Field(
        pattern=(
            r"^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/"
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\?media_ticket=[A-Za-z0-9_-]{43}$"
        )
    )
    expires_at: datetime


class CommandRejectedResult(PrivateResultBase):
    message_type: Literal["command.rejected"] = "command.rejected"
    command_id: UUID
    code: str = Field(min_length=1)
    current_control_version: int = Field(ge=0)
    recoverable: bool


class CommandDuplicateResult(PrivateResultBase):
    message_type: Literal["command.duplicate"] = "command.duplicate"
    command_id: UUID
    code: Literal["duplicate_command"] = "duplicate_command"
    current_control_version: int = Field(ge=0)


class ControllerRevokedResult(PrivateResultBase):
    message_type: Literal["controller.revoked"] = "controller.revoked"
    command_id: None = Field(default=None, exclude=True)
    controller_epoch: UUID
    reason: Literal[
        "superseded", "disconnected", "session_revoked", "start_next", "debate_terminal"
    ]


PrivateResult = Annotated[
    ControllerAcquiredResult
    | MediaPreparedResult
    | CommandRejectedResult
    | CommandDuplicateResult
    | ControllerRevokedResult,
    Field(discriminator="message_type"),
]


class ControlCommandDTO(ClosedModel):
    expected_control_version: int = Field(ge=0)


class StartDebateDTO(ClosedModel):
    expected_revision: int = Field(ge=0)
    expected_current_audio_debate_id: UUID | None
    confirm_previous_audio_cleanup: bool


class AudioResponseHeaders(ClosedModel):
    """Internal test projection for the exact byte-range response headers."""

    accept_ranges: Literal["bytes"] = "bytes"
    etag: str
    content_length: int = Field(ge=0)
    content_range: str | None = None


DebateStartedPayload.model_rebuild()
SnapshotInteractionDTO.model_rebuild()
SnapshotReportDTO.model_rebuild()
