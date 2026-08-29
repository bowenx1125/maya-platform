"""Narrow interfaces between playback and the M10/M11 domain services."""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from .schemas import RetrievalSourceDTO


@dataclass(frozen=True)
class PreparedSource:
    snapshot_id: str
    query_kind: str
    query_hash: str
    threshold_key: str
    source_filename: str
    chunk_id: str
    evidence_id: str
    rank: int
    score: float
    text: str


@dataclass(frozen=True)
class PreparedGenerationFence:
    """Prompt prefix identity committed before any provider call."""

    predecessor_turn_ids: tuple[str, ...]
    transcript_hash: str
    cutoff_turn_index: int
    attempt: int = 1


@dataclass(frozen=True)
class ResolvedTurnVoice:
    """Server-only voice mapping revalidated immediately before TTS."""

    kind: str
    profile_id: str | None
    voice_token: str


@dataclass(frozen=True)
class PreparedTurn:
    """Generation output accepted from M11 after its own validator."""

    speech: str
    sources: tuple[RetrievalSourceDTO, ...] = ()
    retrieval_status: str = "no_match"
    grounding_mode: str = "general_reasoning"
    structured: Mapping[str, Any] = field(default_factory=dict)
    voice_token: str = "mock"
    actual_voice_kind: str = "mock_sentinel"
    actual_voice_profile_id: str | None = None
    source_receipts: tuple[PreparedSource, ...] = ()
    predecessor_turn_ids: tuple[str, ...] = ()
    transcript_hash: str | None = None
    cutoff_turn_index: int | None = None
    word_count: int | None = None
    generation_attempt: int = 1


@dataclass
class MemoryParticipant:
    id: str = field(default_factory=lambda: str(uuid4()))
    agent_id: str = field(default_factory=lambda: str(uuid4()))
    slot: str = "A"
    order_index: int = 0
    name: str = "Agent"
    version_label: str = "V1.0"
    avatar_config: dict[str, Any] = field(
        default_factory=lambda: {
            "template_id": "wave1-default-head",
            "material_theme": "demo",
            "eye_color": None,
            "default_expression": "neutral",
            "expression_strength": "medium",
            "motion_style": "calm",
        }
    )
    effective_voice_profile_id: str | None = None
    voice_fallback_active: bool = True
    initial_stance: str | None = None
    current_stance: str | None = None
    current_position_summary: str = ""


@dataclass
class MemoryTurn:
    id: str = field(default_factory=lambda: str(uuid4()))
    participant_id: str = ""
    round_no: int = 1
    turn_index: int = 0
    generation_status: str = "pending"
    publication_status: str = "unpublished"
    preparation_stage: str | None = None
    speech: str | None = None
    structured: dict[str, Any] = field(default_factory=dict)
    sources: list[RetrievalSourceDTO] = field(default_factory=list)
    retrieval_status: str = "no_match"
    grounding_mode: str = "general_reasoning"
    audio_duration_ms: int | None = None
    audio_file_id: str | None = None
    audio_size_bytes: int | None = None
    audio_sha256: str | None = None
    audio_relative_path: str | None = None
    predecessor_turn_ids: tuple[str, ...] = ()
    predecessor_hash: str | None = None
    attempt: int = 1
    failed_code: str | None = None


@dataclass
class MemoryDebate:
    id: str = field(default_factory=lambda: str(uuid4()))
    course_id: str = field(default_factory=lambda: str(uuid4()))
    topic: str = ""
    status: str = "draft"
    revision: int = 0
    cancellation_generation: int = 0
    participants: list[MemoryParticipant] = field(default_factory=list)
    turns: list[MemoryTurn] = field(default_factory=list)
    playback: Any = None
    interaction_status: str = "closed"
    insight_status: str = "not_started"
    report_status: str = "not_started"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PlaybackRepository(Protocol):
    """Methods the service needs from setup/generation persistence."""

    def get_debate(self, db: Any, debate_id: str) -> Any | None: ...

    def save_debate(self, db: Any, debate: Any) -> None: ...

    def participants(self, db: Any, debate: Any) -> list[Any]: ...

    def turns(self, db: Any, debate: Any) -> list[Any]: ...

    def ensure_turn_plan(self, db: Any, debate: Any) -> list[Any]: ...

    def playback_state(self, db: Any, debate: Any) -> Any: ...

    def save_playback(self, db: Any, state: Any) -> None: ...

    def advance_playback_cas(
        self,
        db: Any,
        debate: Any,
        *,
        expected_control_version: int,
        expected_current_turn_id: str,
        successor_turn_id: str,
    ) -> bool: ...

    def mark_turn_ready(
        self,
        db: Any,
        turn: Any,
        prepared: PreparedTurn,
        audio: Any,
        *,
        generation: int,
        attempt: int,
        claim_token: str | None = None,
    ) -> bool: ...

    def publish_turn(self, db: Any, turn: Any) -> bool: ...

    def fail_turn_and_debate(self, db: Any, debate: Any, turn: Any, code: str) -> None: ...

    def mark_jobs_interrupted(self, db: Any, debate: Any, code: str) -> None: ...

    def teacher_allowed(self, db: Any, debate: Any, context: Any) -> bool: ...

    def course_running(
        self, db: Any, course_id: str, except_debate_id: str | None = None
    ) -> bool: ...

    def current_audio_debate_id(self, db: Any, course_id: str) -> str | None: ...

    def set_current_audio_debate(self, db: Any, course_id: str, debate_id: str | None) -> bool: ...

    def public_turn(self, db: Any, debate: Any, turn_id: str) -> Any | None: ...

    def retained_audio_file(self, db: Any, debate: Any, turn: Any) -> Any | None: ...

    def mark_debate_audio_deleted(self, db: Any, debate_id: str) -> int: ...

    # Teacher Stop/Continue/Finish controls use independent fresh-session
    # CAS methods in the SQL adapter.  The service keeps a small in-memory
    # fallback for unit tests that do not implement these optional seams.
    def claim_pause_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        cursor_ms: int,
        teacher_user_id: str | None = None,
    ) -> bool: ...

    def claim_resume_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        teacher_user_id: str | None = None,
    ) -> bool: ...

    def claim_finish_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str | None = None,
        teacher_user_id: str | None = None,
    ) -> Mapping[str, Any] | None: ...


class TurnPreparer(Protocol):
    def __call__(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        *,
        attempt: int,
        cancellation_generation: int,
    ) -> PreparedTurn | Awaitable[PreparedTurn]: ...


class MemoryPlaybackRepository:
    """A complete repository double for playback tests and local composition."""

    def __init__(self) -> None:
        self.debates: dict[str, MemoryDebate] = {}
        self.jobs_interrupted: list[tuple[str, str]] = []
        self.course_audio: dict[str, str | None] = {}
        self.audio_file_states: dict[str, str] = {}
        self.audit_logs: list[dict[str, Any]] = []

    def add_debate(self, debate: MemoryDebate) -> MemoryDebate:
        if debate.playback is None:
            from .service import PlaybackRuntime

            debate.playback = PlaybackRuntime()
        self.debates[debate.id] = debate
        return debate

    def get_debate(self, db: Any, debate_id: str) -> MemoryDebate | None:
        del db
        return self.debates.get(debate_id)

    def save_debate(self, db: Any, debate: MemoryDebate) -> None:
        del db
        self.debates[debate.id] = debate

    def participants(self, db: Any, debate: MemoryDebate) -> list[MemoryParticipant]:
        del db
        return sorted(debate.participants, key=lambda item: item.order_index)

    def turns(self, db: Any, debate: MemoryDebate) -> list[MemoryTurn]:
        del db
        return sorted(debate.turns, key=lambda item: item.turn_index)

    def ensure_turn_plan(self, db: Any, debate: MemoryDebate) -> list[MemoryTurn]:
        del db
        participants = self.participants(None, debate)
        if not debate.turns:
            for round_no in (1, 2):
                for participant in participants:
                    debate.turns.append(
                        MemoryTurn(
                            participant_id=participant.id,
                            round_no=round_no,
                            turn_index=len(debate.turns),
                        )
                    )
        return self.turns(None, debate)

    def playback_state(self, db: Any, debate: MemoryDebate) -> Any:
        del db
        if debate.playback is None:
            from .service import PlaybackRuntime

            debate.playback = PlaybackRuntime()
        return debate.playback

    def save_playback(self, db: Any, state: Any) -> None:
        del db, state

    def advance_playback_cas(
        self,
        db: Any,
        debate: MemoryDebate,
        *,
        expected_control_version: int,
        expected_current_turn_id: str,
        successor_turn_id: str,
    ) -> bool:
        del db, successor_turn_id
        state = self.playback_state(None, debate)
        return bool(
            state.control_version == expected_control_version
            and state.current_turn_id == expected_current_turn_id
            and state.status == "waiting_next"
            and state.mode == "live"
        )

    def mark_turn_ready(
        self,
        db: Any,
        turn: MemoryTurn,
        prepared: PreparedTurn,
        audio: Any,
        *,
        generation: int,
        attempt: int,
        claim_token: str | None = None,
    ) -> bool:
        del db, generation, claim_token
        if turn.generation_status not in {"pending", "running", "final_ready"}:
            return False
        turn.generation_status = "final_ready"
        turn.preparation_stage = "ready"
        turn.speech = prepared.speech
        turn.structured = dict(prepared.structured)
        turn.sources = list(prepared.sources)
        turn.retrieval_status = prepared.retrieval_status
        turn.grounding_mode = prepared.grounding_mode
        turn.audio_duration_ms = getattr(audio, "duration_ms", None)
        turn.audio_file_id = getattr(audio, "file_id", None) or (
            f"memory-audio:{turn.id}" if getattr(audio, "relative_path", None) else None
        )
        turn.audio_size_bytes = getattr(audio, "size_bytes", None)
        turn.audio_sha256 = getattr(audio, "sha256", None)
        turn.audio_relative_path = getattr(audio, "relative_path", None)
        turn.attempt = prepared.generation_attempt or attempt
        turn.predecessor_turn_ids = prepared.predecessor_turn_ids
        turn.predecessor_hash = prepared.transcript_hash
        return True

    def publish_turn(self, db: Any, turn: MemoryTurn) -> bool:
        del db
        if turn.speech is None or turn.generation_status not in {"ready", "final_ready"}:
            return False
        if turn.publication_status == "public":
            return True
        turn.publication_status = "public"
        return True

    def fail_turn_and_debate(
        self, db: Any, debate: MemoryDebate, turn: MemoryTurn, code: str
    ) -> None:
        del db
        turn.generation_status = "failed"
        turn.failed_code = code
        debate.status = "failed"

    def mark_jobs_interrupted(self, db: Any, debate: MemoryDebate, code: str) -> None:
        del db
        self.jobs_interrupted.append((debate.id, code))

    def claim_pause_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        cursor_ms: int,
        teacher_user_id: str | None = None,
    ) -> bool:
        del teacher_user_id
        debate = self.debates.get(debate_id)
        if debate is None:
            return False
        state = self.playback_state(None, debate)
        if (
            debate.status != "running"
            or state.status != "playing"
            or state.current_turn_id is None
            or state.control_version != expected_control_version
        ):
            return False
        state.status = "paused"
        state.cursor_ms = max(0, int(cursor_ms))
        state.started_monotonic = None
        state.control_version += 1
        state.pending_action = None
        state.pending_ticket_hash = None
        state.pending_media_command_id = None
        state.audio_duration_ms = 0
        return True

    def claim_resume_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        teacher_user_id: str | None = None,
    ) -> bool:
        del teacher_user_id
        debate = self.debates.get(debate_id)
        if debate is None:
            return False
        state = self.playback_state(None, debate)
        if (
            debate.status != "running"
            or state.status != "paused"
            or state.current_turn_id is None
            or state.control_version != expected_control_version
        ):
            return False
        turn = next(
            (item for item in debate.turns if item.id == state.current_turn_id),
            None,
        )
        if turn is None or turn.generation_status not in {"ready", "final_ready", "completed"}:
            return False
        state.status = "ready"
        state.control_version += 1
        state.pending_action = None
        state.pending_ticket_hash = None
        state.pending_media_command_id = None
        state.audio_duration_ms = 0
        return True

    def claim_finish_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str | None = None,
        teacher_user_id: str | None = None,
    ) -> Mapping[str, Any] | None:
        del teacher_user_id
        debate = self.debates.get(debate_id)
        if debate is None:
            return None
        state = self.playback_state(None, debate)
        if debate.status != "running" or state.control_version != expected_control_version:
            return None
        if (
            expected_current_turn_id is not None
            and state.current_turn_id != expected_current_turn_id
        ):
            return None
        turns = self.turns(None, debate)
        complete = bool(turns) and all(
            item.generation_status == "final_ready" and item.publication_status == "public"
            for item in turns
        )
        if complete:
            debate.status = "debate_finished"
            state.status = "completed"
        else:
            debate.status = "stopped"
            debate.cancellation_generation += 1
            self.mark_jobs_interrupted(None, debate, "debate_finished_partial")
            state.status = "stopped"
        state.mode = "live"
        state.current_turn_id = None
        state.cursor_ms = 0
        state.control_version += 1
        state.controller_epoch = None
        state.controller_session_hash = None
        state.controller_connection_id = None
        state.pending_action = None
        state.pending_ticket_hash = None
        state.pending_media_command_id = None
        state.audio_duration_ms = 0
        state.replay_scope = None
        state.replay_index = None
        state.replay_turn_ids = []
        return {
            "kind": "full" if complete else "partial",
            "control_version": state.control_version,
            "current_turn_id": None,
            "total_turns": len(turns),
            "complete_turns": sum(
                1
                for item in turns
                if item.generation_status == "final_ready" and item.publication_status == "public"
            ),
        }

    def write_playback_reset_audit(
        self,
        db: Any,
        *,
        debate_id: str,
        actor_user_id: str | None,
        previous_mode: str,
        resulting_status: str,
        control_version: int,
        request_id: str | None,
    ) -> None:
        del db
        self.audit_logs.append(
            {
                "id": str(uuid4()),
                "event_type": "playback.operator_reset",
                "actor_kind": "operator",
                "actor_id": actor_user_id,
                "course_id": None,
                "debate_id": debate_id,
                "request_id": request_id,
                "details": {
                    "mode": previous_mode,
                    "status": resulting_status,
                    "control_version": control_version,
                },
                "created_at": datetime.now(UTC),
            }
        )

    def teacher_allowed(self, db: Any, debate: MemoryDebate, context: Any) -> bool:
        del db, debate, context
        return True

    def course_running(self, db: Any, course_id: str, except_debate_id: str | None = None) -> bool:
        del db
        return any(
            debate.course_id == course_id
            and debate.id != except_debate_id
            and debate.status == "running"
            for debate in self.debates.values()
        )

    def current_audio_debate_id(self, db: Any, course_id: str) -> str | None:
        del db
        return self.course_audio.get(course_id)

    def set_current_audio_debate(self, db: Any, course_id: str, debate_id: str | None) -> bool:
        del db
        self.course_audio[course_id] = debate_id
        return True

    def public_turn(self, db: Any, debate: MemoryDebate, turn_id: str) -> MemoryTurn | None:
        del db
        return next(
            (
                turn
                for turn in debate.turns
                if turn.id == turn_id and turn.publication_status == "public"
            ),
            None,
        )

    def retained_audio_file(
        self, db: Any, debate: MemoryDebate, turn: MemoryTurn
    ) -> dict[str, Any] | None:
        """Expose the same durable-fact shape for the in-memory test double.

        SQL tests use the real StoredFile row.  Memory tests intentionally do
        not construct the Wave 1/2 database, so the turn's persisted audio
        fields stand in for that row while the AudioStore still validates the
        actual canonical bytes.
        """

        del db
        relative = turn.audio_relative_path
        if not relative:
            return None
        file_id = turn.audio_file_id or f"memory-audio:{debate.id}:{turn.id}"
        state = self.audio_file_states.get(file_id, "active")
        return {
            "id": file_id,
            "kind": "debate_audio",
            "relative_path": relative,
            "sha256": turn.audio_sha256,
            "size": turn.audio_size_bytes,
            "state": state,
        }

    def mark_debate_audio_deleted(self, db: Any, debate_id: str) -> int:
        del db
        changed = 0
        debate = self.debates.get(debate_id)
        if debate is None:
            return 0
        for turn in debate.turns:
            file_id = turn.audio_file_id
            if file_id is not None and self.audio_file_states.get(file_id) != "deleted":
                self.audio_file_states[file_id] = "deleted"
                changed += 1
        return changed
