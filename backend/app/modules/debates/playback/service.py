"""Authoritative Wave 2 playback state machine.

The service owns controller epochs, media bootstrap acknowledgements, playback
CAS and event ordering.  Debate setup and generation remain outside this
package and are provided via :mod:`protocols`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from app.core.errors import PlatformError, conflict, forbidden, invalid_state, not_found
from app.modules.auth.service import AuthContext
from app.modules.debates.generation.evidence_trace import public_evidence_trace
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.round_phase import phase_for_round
from app.modules.debates.topic_language import TopicLanguageError, validate_english_topic
from app.providers.tts import MockTTSProvider, TTSProvider, TTSProviderError

from .audio import AudioMetadata, AudioStore, MediaTicketBinding, MediaTicketStore
from .events import DebateEventHub, EventRecord, validate_event_payload
from .protocols import (
    MemoryPlaybackRepository,
    PlaybackRepository,
    PreparedGenerationFence,
    PreparedSource,
    PreparedTurn,
    ResolvedTurnVoice,
    TurnPreparer,
)
from .schemas import (
    CommandDuplicateResult,
    CommandRejectedResult,
    ControllerAcquiredResult,
    ControllerRevokedResult,
    MediaPreparedResult,
    PlaybackStateDTO,
    RetrievalSourceDTO,
)

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_SAFE_GENERATION_CODES = {
    "turn_generation_failed",
    "provider_unavailable",
    "persona_confirmation_required",
    "provider_confirmation_required",
    "provider_not_sent",
    "acceptance_unknown",
    "debate_stopped",
    "audio_invalid",
}
_RECOVERABLE_PROVIDER_GENERATION_CODES = {
    "provider_confirmation_required",
    "provider_not_sent",
    "acceptance_unknown",
    "tts_timeout",
    "tts_http_rejected",
    "tts_response_invalid",
    "tts_result_url_rejected",
    "tts_result_dns_failed",
    "tts_result_download_failed",
    "tts_audio_invalid",
}


class EvidenceTraceCorruptError(ValueError):
    """Persisted evidence trace cannot be projected under the frozen DTO."""


@dataclass
class PlaybackRuntime:
    status: str = "preparing"
    mode: str = "live"
    current_turn_id: str | None = None
    cursor_ms: int = 0
    playback_rate: float = 1.0
    control_version: int = 0
    controller_epoch: str | None = None
    controller_session_hash: str | None = None
    controller_connection_id: str | None = None
    pending_action: str | None = None
    pending_ticket_hash: str | None = None
    pending_media_command_id: str | None = None
    started_monotonic: float | None = None
    audio_duration_ms: int = 0
    replay_scope: str | None = None
    replay_turn_ids: list[str] = field(default_factory=list)
    replay_index: int | None = 0


@dataclass(frozen=True)
class PreparedMedia:
    media_url: str
    expires_at: datetime
    token: str
    binding: MediaTicketBinding


@dataclass(frozen=True)
class AudioAuthorization:
    metadata: AudioMetadata
    ticket: MediaTicketBinding | None


@dataclass(frozen=True)
class ControllerHandle:
    epoch: str
    control_version: int


class PlaybackService:
    """A provider-neutral, single-controller classroom playback service."""

    def __init__(
        self,
        repository: PlaybackRepository | None = None,
        *,
        audio_store: AudioStore | None = None,
        ticket_store: MediaTicketStore | None = None,
        event_hub: DebateEventHub | None = None,
        task_manager: Any | None = None,
        turn_preparer: TurnPreparer | None = None,
        tts_provider: TTSProvider | None = None,
        session_factory: Callable[[], Any] | None = None,
        settings: Any | None = None,
        snapshot_projector: Callable[[Any, str], dict[str, Any]] | None = None,
    ) -> None:
        self.repository: PlaybackRepository = repository or MemoryPlaybackRepository()
        self.audio_store = audio_store
        self.ticket_store = ticket_store or MediaTicketStore()
        self.event_hub = event_hub or DebateEventHub()
        if task_manager is None:
            from .task_manager import TaskManager

            task_manager = TaskManager()
        self.task_manager = task_manager
        self.turn_preparer = turn_preparer
        self.tts_provider = tts_provider or MockTTSProvider()
        self.session_factory = session_factory
        self.settings = settings
        self.snapshot_projector = snapshot_projector
        self._db_hint: Any | None = None
        self._connection_callbacks: dict[
            str, Callable[[dict[str, Any]], Awaitable[None] | None]
        ] = {}
        self._revoked: dict[str, dict[str, Any]] = {}
        self._command_ids: dict[str, set[str]] = {}
        # M10's durable PlaybackState intentionally stores only an opaque
        # controller epoch/owner, not a Session hash.  Keep the session binding
        # process-local; restart recovery revokes all epochs before accepting a
        # new connection, so an old browser cannot inherit authority.
        self._controller_sessions: dict[str, str] = {}
        self._runtime_cache: dict[str, PlaybackRuntime] = {}
        # Raw media URLs remain process-local and short-lived.  The durable
        # pending hash is the authorization fence; this cache only lets the
        # same in-process command replay its original private result without
        # issuing a second ticket.
        self._media_command_results: dict[
            tuple[str, str], tuple[PreparedMedia, MediaPreparedResult]
        ] = {}
        self._lock = asyncio.Lock()

    async def recover_startup(self, db: Any) -> tuple[str, ...]:
        """Fence interrupted work, revoke controllers and recover audio swaps."""

        recoverable_llm_turns: tuple[tuple[str, str], ...] = ()
        async with self._lock:
            recover = getattr(self.repository, "recover_startup", None)
            affected = tuple(recover(db)) if callable(recover) else ()
            recoverable = getattr(self.repository, "recoverable_llm_turns", None)
            if callable(recoverable):
                recoverable_llm_turns = tuple(recoverable(db))
            # The SQL adapter applies this fence in one statement.  Mirror the
            # restart matrix for the in-memory/test adapter so playback never
            # resumes a stale local ``playing`` clock and an in-flight
            # generation can never publish after restart.
            known = getattr(self.repository, "debates", None)
            if isinstance(known, Mapping):
                affected_set = set(affected)
                for candidate in tuple(known.values()):
                    candidate_id = self._debate_id(candidate)
                    candidate_turns = self._turns(db, candidate)
                    in_flight = any(
                        self._get(turn, "generation_status", default="") == "running"
                        for turn in candidate_turns
                    )
                    paused_recoverable = (
                        str(self._get(candidate.playback, "status", default="")) == "paused"
                        and str(self._get(candidate, "status", default="")) == "running"
                    )
                    if (candidate_id in affected_set and not paused_recoverable) or (
                        in_flight and not paused_recoverable
                    ):
                        affected_set.add(candidate_id)
                        candidate.status = "failed"
                        for candidate_turn in candidate_turns:
                            if self._get(candidate_turn, "generation_status", default="") in {
                                "pending",
                                "running",
                            }:
                                candidate_turn.generation_status = "failed"
                                candidate_turn.failed_code = "process_restarted"
                        self.repository.save_debate(db, candidate)
                        state = self._state(db, candidate)
                        self._set_nonplaying(state, "stopped")
                        state.control_version += 1
                        state.controller_epoch = None
                        state.controller_session_hash = None
                        state.controller_connection_id = None
                        state.pending_action = None
                        state.pending_ticket_hash = None
                        state.pending_media_command_id = None
                        state.audio_duration_ms = 0
                        self._clear_media_results(candidate_id)
                        self._save(db, candidate, state)
                    else:
                        state = self._state(db, candidate)
                        if state.status == "playing":
                            self._set_nonplaying(state, "ready", 0)
                            state.control_version += 1
                            state.controller_epoch = None
                            state.controller_session_hash = None
                            state.controller_connection_id = None
                            state.pending_action = None
                            state.pending_ticket_hash = None
                            state.pending_media_command_id = None
                            state.audio_duration_ms = 0
                            self._clear_media_results(candidate_id)
                            self._save(db, candidate, state)
                        elif state.status == "paused":
                            # Explicit Pause survives restart.  Revoke only
                            # the process-local authority/ticket and keep the
                            # paused cursor so a fresh controller can Continue.
                            state.controller_epoch = None
                            state.controller_session_hash = None
                            state.controller_connection_id = None
                            state.pending_action = None
                            state.pending_ticket_hash = None
                            state.pending_media_command_id = None
                            state.audio_duration_ms = 0
                            state.control_version += 1
                            self._clear_media_results(candidate_id)
                            self._save(db, candidate, state)
                        elif (
                            state.controller_epoch is not None
                            or state.controller_connection_id is not None
                            or state.pending_action is not None
                            or state.pending_ticket_hash is not None
                            or state.pending_media_command_id is not None
                            or state.audio_duration_ms != 0
                        ):
                            # A waiting replay gate is durable across a
                            # restart, but its process-local controller and
                            # media ticket are not.  Clear only those
                            # authority fields so restart cannot auto-advance
                            # or let an old socket prepare media; the teacher
                            # may reconnect and issue the same explicit Next.
                            state.controller_epoch = None
                            state.controller_session_hash = None
                            state.controller_connection_id = None
                            state.pending_action = None
                            state.pending_ticket_hash = None
                            state.pending_media_command_id = None
                            state.audio_duration_ms = 0
                            self._clear_media_results(candidate_id)
                            self._save(db, candidate, state)
                    self.ticket_store.revoke_debate(candidate_id)
                affected = tuple(sorted(affected_set))
            journals = getattr(self.repository, "audio_swap_journals", None)
            rows = list(journals(db)) if callable(journals) else []
            for row in rows:
                staging = self._get(row, "staging_relative_path", default=None)
                old_debate_id = self._get(row, "old_audio_debate_id", default=None)
                new_debate_id = self._get(row, "new_debate_id", default=None)
                if not isinstance(staging, str) or not staging:
                    marker = getattr(self.repository, "mark_audio_swap_recovered", None)
                    if callable(marker):
                        marker(db, str(row.id))
                    continue
                current: str | None = None
                # FileOperation.entity_id is the new Debate, not the course.
                # Resolve the course through the committed Debate row.
                new_debate = (
                    self.repository.get_debate(db, str(new_debate_id)) if new_debate_id else None
                )
                course_id = self._course_id(new_debate) if new_debate is not None else None
                if course_id is not None:
                    current = self.repository.current_audio_debate_id(db, course_id)
                committed_won = (
                    str(self._get(row, "state", default="")) in {"committed", "cleanup_required"}
                    and current == new_debate_id
                )
                if self.audio_store is not None and course_id is not None:
                    if committed_won:
                        self.audio_store.delete_staging(staging)
                        if old_debate_id:
                            self.audio_store.remove_debate(str(old_debate_id))
                            self.ticket_store.revoke_debate(str(old_debate_id))
                            mark_deleted = getattr(
                                self.repository, "mark_debate_audio_deleted", None
                            )
                            if callable(mark_deleted):
                                mark_deleted(db, str(old_debate_id))
                    elif old_debate_id:
                        self.audio_store.restore_staged_debate(
                            course_id=course_id,
                            debate_id=str(old_debate_id),
                            staging_relative_path=staging,
                        )
                marker = getattr(self.repository, "mark_audio_swap_recovered", None)
                if callable(marker):
                    marker(db, str(row.id))
            self._commit(db)
            self._controller_sessions.clear()
            self._runtime_cache.clear()
            self._media_command_results.clear()
        # Requeue accepted-stage continuations only after the restart fence
        # transaction commits.  SqlTurnPreparer then maps/validates locally
        # and TTS remains the only later stage; no provider call is retried.
        for debate_id, turn_id in recoverable_llm_turns:
            debate = self.repository.get_debate(db, debate_id)
            if debate is not None:
                turn = next(
                    (
                        item
                        for item in self._turns(db, debate)
                        if str(getattr(item, "id", "")) == turn_id
                    ),
                    None,
                )
                if turn is not None:
                    await self._enqueue(debate, turn)
        return affected

    # ------------------------------------------------------------------
    # Generic repository/ORM helpers.  The setup and generation workers can
    # provide richer implementations; the fallback uses the memory adapter.
    # ------------------------------------------------------------------
    def _get_debate(self, db: Any, debate_id: str) -> Any:
        debate = self.repository.get_debate(db, debate_id)
        if debate is None:
            raise not_found()
        return debate

    def _participants(self, db: Any, debate: Any) -> list[Any]:
        return list(self.repository.participants(db, debate))

    def _turns(self, db: Any, debate: Any) -> list[Any]:
        return list(self.repository.turns(db, debate))

    def _state(self, db: Any, debate: Any) -> PlaybackRuntime:
        debate_id = self._debate_id(debate)
        state = self.repository.playback_state(db, debate)
        # SQLAlchemy rows from a host adapter expose the same attributes.  A
        # one-time conversion keeps the runtime's monotonic timestamp local
        # while all durable fields are copied back by ``_save``.
        if isinstance(state, PlaybackRuntime):
            cached = self._runtime_cache.get(debate_id)
            if cached is not None and cached is not state:
                return cached
            self._runtime_cache[debate_id] = state
            return state
        cached = self._runtime_cache.get(debate_id)
        if cached is not None:
            cached.status = str(getattr(state, "status", cached.status))
            cached.mode = str(getattr(state, "mode", cached.mode))
            cached.current_turn_id = getattr(state, "current_turn_id", cached.current_turn_id)
            cached.cursor_ms = int(getattr(state, "cursor_ms", cached.cursor_ms) or 0)
            cached.playback_rate = float(
                getattr(state, "playback_rate", cached.playback_rate) or 1.0
            )
            cached.control_version = int(
                getattr(state, "control_version", cached.control_version) or 0
            )
            cached.controller_epoch = getattr(state, "controller_epoch", cached.controller_epoch)
            cached.controller_session_hash = self._controller_sessions.get(debate_id)
            cached.controller_connection_id = getattr(
                state,
                "controller_connection_id",
                getattr(
                    state,
                    "controller_owner_connection",
                    cached.controller_connection_id,
                ),
            )
            cached.pending_action = getattr(state, "pending_action", cached.pending_action)
            cached.pending_ticket_hash = getattr(
                state, "pending_ticket_hash", cached.pending_ticket_hash
            )
            cached.pending_media_command_id = getattr(
                state, "pending_media_command_id", cached.pending_media_command_id
            )
            cached.audio_duration_ms = int(
                getattr(state, "audio_duration_ms", cached.audio_duration_ms) or 0
            )
            cached.replay_scope = getattr(state, "replay_scope", cached.replay_scope)
            raw_replay_index = getattr(state, "replay_index", cached.replay_index)
            cached.replay_index = None if raw_replay_index is None else int(raw_replay_index)
            raw_replay = getattr(state, "replay_turn_ids_json", None)
            if isinstance(raw_replay, str):
                try:
                    parsed_replay = json.loads(raw_replay)
                    if isinstance(parsed_replay, list):
                        cached.replay_turn_ids = [str(item) for item in parsed_replay]
                except (TypeError, ValueError):
                    cached.replay_turn_ids = []
            return cached
        runtime = PlaybackRuntime(
            status=str(getattr(state, "status", "preparing")),
            mode=str(getattr(state, "mode", "live")),
            current_turn_id=getattr(state, "current_turn_id", None),
            cursor_ms=int(getattr(state, "cursor_ms", 0) or 0),
            playback_rate=float(getattr(state, "playback_rate", 1.0) or 1.0),
            control_version=int(getattr(state, "control_version", 0) or 0),
            controller_epoch=getattr(state, "controller_epoch", None),
            controller_session_hash=self._controller_sessions.get(debate_id),
            controller_connection_id=getattr(
                state,
                "controller_connection_id",
                getattr(state, "controller_owner_connection", None),
            ),
            pending_action=getattr(state, "pending_action", None),
            pending_ticket_hash=getattr(state, "pending_ticket_hash", None),
            pending_media_command_id=getattr(state, "pending_media_command_id", None),
            audio_duration_ms=int(getattr(state, "audio_duration_ms", 0) or 0),
            replay_scope=getattr(state, "replay_scope", None),
            replay_turn_ids=list(getattr(state, "replay_turn_ids", []) or []),
            replay_index=(
                None
                if getattr(state, "replay_index", None) is None
                else int(getattr(state, "replay_index", 0) or 0)
            ),
        )
        raw_replay = getattr(state, "replay_turn_ids_json", None)
        if isinstance(raw_replay, str):
            try:
                parsed_replay = json.loads(raw_replay)
                if isinstance(parsed_replay, list):
                    runtime.replay_turn_ids = [str(item) for item in parsed_replay]
            except (TypeError, ValueError):
                pass
        self._runtime_cache[debate_id] = runtime
        return runtime

    def _save(self, db: Any, debate: Any, state: PlaybackRuntime) -> None:
        existing = self.repository.playback_state(db, debate)
        if existing is not state and not isinstance(existing, PlaybackRuntime):
            for name in (
                "status",
                "mode",
                "current_turn_id",
                "cursor_ms",
                "playback_rate",
                "control_version",
                "controller_epoch",
                "controller_session_hash",
                "controller_connection_id",
                "pending_action",
                "pending_ticket_hash",
                "pending_media_command_id",
                "audio_duration_ms",
                "replay_scope",
                "replay_index",
                "replay_turn_ids_json",
            ):
                target_name = (
                    "controller_owner_connection"
                    if name == "controller_connection_id"
                    and not hasattr(existing, name)
                    and hasattr(existing, "controller_owner_connection")
                    else name
                )
                if name == "replay_turn_ids_json" and hasattr(existing, name):
                    import json

                    setattr(
                        existing, name, json.dumps(state.replay_turn_ids, separators=(",", ":"))
                    )
                elif hasattr(existing, target_name):
                    setattr(existing, target_name, getattr(state, name))
            self.repository.save_playback(db, existing)
        else:
            self.repository.save_playback(db, state)
        self._runtime_cache[self._debate_id(debate)] = state
        if state.controller_epoch and state.controller_session_hash:
            self._controller_sessions[self._debate_id(debate)] = state.controller_session_hash
        self._db_hint = db

    @staticmethod
    def _commit(db: Any) -> None:
        commit = getattr(db, "commit", None)
        if callable(commit):
            commit()

    def _clear_media_results(self, debate_id: str) -> None:
        """Drop process-local media result handles after their authority ends."""

        for key in tuple(self._media_command_results):
            if key[0] == debate_id:
                self._media_command_results.pop(key, None)

    def _rollback_replay_next(self, db: Any, debate: Any, state: PlaybackRuntime) -> bool:
        """CAS a replay successor back to waiting when bytes changed after Next."""

        if state.mode != "replay" or state.replay_scope != "all":
            return False
        queue, valid = self._replay_queue(db, debate, state)
        if not valid:
            return False
        try:
            replay_index = int(state.replay_index) if state.replay_index is not None else -1
        except (TypeError, ValueError):
            return False
        if replay_index <= 0 or replay_index >= len(queue):
            return False
        current = queue[replay_index]
        previous = queue[replay_index - 1]
        if str(current.id) != str(state.current_turn_id):
            return False
        rollback = getattr(self.repository, "rollback_replay_next_playback", None)
        if callable(rollback):
            changed = bool(
                rollback(
                    debate_id=self._debate_id(debate),
                    expected_control_version=state.control_version,
                    expected_current_turn_id=str(current.id),
                    expected_replay_index=replay_index,
                    previous_turn_id=str(previous.id),
                    previous_replay_index=replay_index - 1,
                )
            )
            self._rollback(db)
            if changed:
                self._clear_media_results(self._debate_id(debate))
            return changed
        state.status = "waiting_next"
        state.current_turn_id = str(previous.id)
        state.replay_index = replay_index - 1
        state.cursor_ms = 0
        state.pending_action = None
        state.pending_ticket_hash = None
        state.pending_media_command_id = None
        state.audio_duration_ms = 0
        state.control_version += 1
        self._clear_media_results(self._debate_id(debate))
        self._save(db, debate, state)
        self._commit(db)
        return True

    @staticmethod
    def _rollback(db: Any) -> None:
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()

    def _assert_teacher(self, db: Any, debate: Any, context: AuthContext | None) -> None:
        if context is None:
            return
        checker = getattr(self.repository, "teacher_allowed", None)
        if callable(checker):
            try:
                allowed = checker(db, debate, context)
            except TypeError:
                allowed = checker(db, debate, context.user)
            if not allowed:
                raise forbidden()

    def _claim_control_idempotency(
        self,
        db: Any,
        *,
        context: AuthContext | None,
        operation: str,
        key: str | None,
        body: Mapping[str, Any],
    ) -> tuple[Any | None, bool]:
        """Claim a teacher control key without coupling the runtime to HTTP.

        Playback tests and the in-memory repository intentionally omit the
        Wave 0 idempotency tables.  In the SQL composition, the shared
        idempotency helper commits a short claim before the control CAS; an
        exact replay simply reloads the authoritative state and performs no
        second transition/event.
        """

        if not key or context is None or isinstance(self.repository, MemoryPlaybackRepository):
            return None, False
        from app.modules.knowledge.services import claim_idempotency, request_hash

        body_hash = request_hash(
            operation,
            str(context.user.id),
            [str(body.get("debate_id"))],
            body,
        )
        record, replay = claim_idempotency(
            db,
            context,
            operation,
            key,
            body_hash,
            data_root=(
                getattr(self.settings, "resolved_data_root", None)
                if self.settings is not None
                else None
            ),
        )
        if replay is not None:
            self._rollback(db)
            return None, True
        return record, False

    @staticmethod
    def _finish_control_idempotency(db: Any, record: Any | None, state: PlaybackStateDTO) -> None:
        if record is None:
            return
        from app.modules.knowledge.services import finish_idempotency

        finish_idempotency(db, record, 200, state.model_dump(mode="json"))

    @staticmethod
    def _debate_id(debate: Any) -> str:
        return str(debate.id)

    @staticmethod
    def _course_id(debate: Any) -> str:
        value = getattr(debate, "course_id", None)
        if value is None:
            raise not_found()
        return str(value)

    @staticmethod
    def _get(value: Any, *names: str, default: Any = None) -> Any:
        for name in names:
            if isinstance(value, Mapping) and name in value:
                result = value[name]
                if result is not None:
                    return result
                continue
            if hasattr(value, name):
                result = getattr(value, name)
                if result is not None:
                    return result
        return default

    @staticmethod
    def _turn_public(turn: Any) -> bool:
        status = str(
            PlaybackService._get(turn, "publication_status", "public_status", default="private")
        )
        return status in {"public", "published"}

    @staticmethod
    def _turn_ready(turn: Any) -> bool:
        generation = str(
            PlaybackService._get(turn, "generation_status", "status", default="pending")
        )
        audio = PlaybackService._get(turn, "audio_relative_path", "audio_file_id", default=None)
        return generation in {"ready", "final_ready", "completed"} and audio is not None

    @staticmethod
    def _evidence_trace(turn: Any) -> list[dict[str, Any]]:
        """Return only validated public trace rows from a frozen turn."""

        found = False
        raw: Any = None
        for name in ("evidence_trace_json", "evidence_trace", "evidence_traces"):
            if isinstance(turn, Mapping) and name in turn:
                found = True
                raw = turn[name]
                break
            try:
                raw = getattr(turn, name)
            except AttributeError:
                continue
            found = True
            break
        # Turns written before EvidenceTraceV1 did not have a trace field at
        # all (and some in-memory compatibility rows use None).  They remain
        # replayable with the historical empty projection.  Once a field is
        # present, however, malformed JSON is corruption, not an empty trace.
        if not found or raw is None:
            return []
        if isinstance(raw, str) and not raw.strip():
            raise EvidenceTraceCorruptError("persisted evidence trace is empty or malformed")
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            return [item.model_dump(mode="json") for item in public_evidence_trace(value)]
        except (TypeError, ValueError) as exc:
            # A malformed trace must never be downgraded to []: that would
            # make a corrupted replay indistinguishable from legacy history.
            raise EvidenceTraceCorruptError("persisted evidence trace is unavailable") from exc

    @staticmethod
    def _evidence_trace_payload(turn: Any) -> dict[str, Any]:
        trace = PlaybackService._evidence_trace(turn)
        return {"evidence_trace": trace} if trace else {}

    def _retained_audio_record(self, db: Any, debate: Any, turn: Any) -> Any | None:
        reader = getattr(self.repository, "retained_audio_file", None)
        if not callable(reader):
            return None
        try:
            return reader(db, debate, turn)
        except TypeError:
            # Keep small repository doubles written before the three-argument
            # retention contract usable; the SQL adapter always takes the
            # exact Debate/Turn identity above.
            try:
                return reader(db, turn)
            except TypeError:
                return None

    def _validated_turn_audio(
        self,
        db: Any,
        debate: Any,
        turn: Any,
    ) -> AudioMetadata | None:
        """Validate one turn's durable StoredFile and canonical WAV bytes.

        ``AudioStore.metadata`` is only a process-local cache.  SQL playback
        therefore requires the repository's StoredFile row and compares its
        exact kind/state/path/hash/size facts against the bytes on disk.  The
        in-memory repository has no SQL schema, so its turn fields provide the
        same test-double facts while the byte validation remains identical.
        """

        if self.audio_store is None:
            return None
        debate_id = self._debate_id(debate)
        turn_id = str(self._get(turn, "id", default=""))
        if not turn_id:
            return None
        try:
            course_id = self._course_id(debate)
            canonical = self.audio_store.relative_path(course_id, debate_id, turn_id)
        except (TypeError, ValueError):
            return None

        record = self._retained_audio_record(db, debate, turn)
        if record is not None:
            file_id = self._get(turn, "audio_file_id", default=None)
            if (file_id is None and not isinstance(self.repository, MemoryPlaybackRepository)) or (
                file_id is not None and str(self._get(record, "id", default="")) != str(file_id)
            ):
                return None
            if self._get(record, "kind", default=None) != "debate_audio":
                return None
            if self._get(record, "state", default=None) != "active":
                return None
            relative_path = self._get(record, "relative_path", default=None)
            expected_sha256 = self._get(record, "sha256", default=None)
            expected_size = self._get(record, "size_bytes", "size", default=None)
            if isinstance(self.repository, MemoryPlaybackRepository) and (
                expected_sha256 is None or expected_size is None
            ):
                cached = self.audio_store.metadata(debate_id, turn_id)
                if cached is not None:
                    expected_sha256 = expected_sha256 or cached.sha256
                    expected_size = (
                        expected_size if expected_size is not None else cached.size_bytes
                    )
        else:
            # Production SQL rows must never fall back to process metadata.
            # MemoryPlaybackRepository intentionally models the persistence
            # boundary with the turn's audio fields for unit-level playback
            # tests and controller doubles.
            if not isinstance(self.repository, MemoryPlaybackRepository):
                return None
            relative_path = self._get(turn, "audio_relative_path", default=None)
            expected_sha256 = self._get(turn, "audio_sha256", default=None)
            expected_size = self._get(turn, "audio_size_bytes", default=None)
            if expected_sha256 is None or expected_size is None:
                cached = self.audio_store.metadata(debate_id, turn_id)
                if cached is not None:
                    expected_sha256 = expected_sha256 or cached.sha256
                    expected_size = (
                        expected_size if expected_size is not None else cached.size_bytes
                    )

        if not isinstance(relative_path, str) or relative_path != canonical:
            return None
        try:
            size_value = int(expected_size) if expected_size is not None else None
        except (TypeError, ValueError):
            return None
        metadata = self.audio_store.validate_file(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative_path,
            expected_sha256=(str(expected_sha256) if expected_sha256 is not None else None),
            expected_size_bytes=size_value,
        )
        if metadata is not None:
            # Rehydration happens only after the DB facts and bytes have both
            # passed validation; a stale cache can never grant eligibility.
            self.audio_store.rehydrate(metadata)
        return metadata

    def _replay_audio_ready(self, db: Any, debate: Any, turn: Any) -> bool:
        try:
            self._evidence_trace(turn)
        except EvidenceTraceCorruptError:
            return False
        if not self._turn_public(turn):
            return False
        if str(self._get(turn, "generation_status", default="")) != "final_ready":
            return False
        # Replay is authorized only against the Debate currently retained by
        # its course.  The pointer can change after replay starts (for
        # example, when a newer Debate replaces the retained audio), so this
        # check must be repeated at every waiting/Next readiness gate rather
        # than relying on the replay-start snapshot alone.
        if self.repository.current_audio_debate_id(db, self._course_id(debate)) != self._debate_id(
            debate
        ):
            return False
        return self._validated_turn_audio(db, debate, turn) is not None

    def audio_retained(self, db: Any, debate_id: str) -> bool:
        """Return whether the course currently retains every public turn's bytes."""

        debate = self._get_debate(db, debate_id)
        if self.repository.current_audio_debate_id(db, self._course_id(debate)) != debate_id:
            return False
        turns = self._turns(db, debate)
        public_turns = [turn for turn in turns if self._turn_public(turn)]
        # Transcript callers also ask while the first live turn is final-ready
        # but not public yet.  Preserve that useful retained-audio indicator,
        # while still requiring every public turn to pass the strict replay
        # validation once publication has begun.
        candidates = public_turns or [
            turn
            for turn in turns
            if str(self._get(turn, "generation_status", default="")) == "final_ready"
            and self._get(turn, "audio_file_id", "audio_relative_path", default=None) is not None
        ]
        if not candidates:
            return False
        return all(self._validated_turn_audio(db, debate, turn) is not None for turn in candidates)

    @classmethod
    def _turn_fence_ready(
        cls,
        turns: list[Any],
        turn: Any,
        *,
        rule_set_id: str | None = None,
    ) -> bool:
        """Check the persisted M11 prefix fence when the row carries one.

        MemoryPlaybackRepository intentionally models only the playback
        boundary and therefore has no SQL fence columns.  SQL/ORM rows do
        carry the immutable predecessor JSON, transcript hash and cutoff;
        Next must not promote such a row when that committed identity is
        incomplete or no longer describes the deterministic prefix.
        """

        try:
            turn_index = int(cls._get(turn, "turn_index", default=-1))
        except (TypeError, ValueError):
            return False
        if turn_index < 0:
            return False

        has_persisted_fence = any(
            hasattr(turn, name)
            for name in ("predecessor_turn_ids_json", "transcript_hash", "cutoff_turn_index")
        )
        if not has_persisted_fence:
            return True

        raw_predecessors = cls._get(turn, "predecessor_turn_ids_json", default=None)
        if raw_predecessors is None:
            raw_predecessors = cls._get(turn, "predecessor_turn_ids", default=None)
        if isinstance(raw_predecessors, str):
            try:
                import json

                raw_predecessors = json.loads(raw_predecessors)
            except (TypeError, ValueError):
                return False
        if not isinstance(raw_predecessors, (list, tuple)):
            return False
        indexed: list[tuple[int, Any]] = []
        for candidate in turns:
            try:
                indexed.append(
                    (int(cls._get(candidate, "turn_index", default=-1) or -1), candidate)
                )
            except (TypeError, ValueError):
                return False
        ordered = [candidate for _index, candidate in sorted(indexed, key=lambda item: item[0])]
        is_mutual = rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
        try:
            current_round = int(cls._get(turn, "round_no", default=1) or 1)
        except (TypeError, ValueError):
            return False
        if is_mutual:
            expected_rows = [
                candidate
                for candidate in ordered
                if int(cls._get(candidate, "round_no", default=1) or 1) < current_round
            ]
        else:
            expected_rows = [
                candidate
                for candidate in ordered
                if int(cls._get(candidate, "turn_index", default=-1) or -1) < turn_index
            ]
        expected = [str(candidate.id) for candidate in expected_rows]
        if [str(item) for item in raw_predecessors] != expected:
            return False
        cutoff = cls._get(turn, "cutoff_turn_index", default=None)
        if cutoff is None:
            return False
        try:
            expected_cutoff = (
                max(
                    (
                        int(cls._get(candidate, "turn_index", default=-1) or -1)
                        for candidate in expected_rows
                    ),
                    default=-1,
                )
                if is_mutual
                else turn_index - 1
            )
            if int(cutoff) != expected_cutoff:
                return False
        except (TypeError, ValueError):
            return False
        transcript_hash = cls._get(turn, "transcript_hash", default=None)
        return isinstance(transcript_hash, str) and bool(transcript_hash.strip())

    @classmethod
    def _adjacent_successor(cls, turns: list[Any], current: Any) -> tuple[Any | None, bool]:
        """Return the unique turn-index +1 successor and uniqueness status."""

        try:
            current_index = int(cls._get(current, "turn_index", default=-1))
        except (TypeError, ValueError):
            return None, False
        candidates: list[Any] = []
        for candidate in turns:
            try:
                candidate_index = int(cls._get(candidate, "turn_index", default=-1) or -1)
            except (TypeError, ValueError):
                return None, False
            if candidate_index == current_index + 1:
                candidates.append(candidate)
        if len(candidates) != 1:
            return None, len(candidates) == 0
        return candidates[0], True

    def _next_turn_ready(self, db: Any, debate: Any, state: PlaybackRuntime) -> bool:
        """Derive readiness only for a live waiting state; never persist it."""

        if (
            self._get(debate, "status", default="running") != "running"
            or state.mode != "live"
            or state.status != "waiting_next"
            or not state.current_turn_id
        ):
            return False
        turns = self._turns(db, debate)
        current = next(
            (item for item in turns if str(getattr(item, "id", "")) == state.current_turn_id),
            None,
        )
        if current is None:
            return False
        successor, unique = self._adjacent_successor(turns, current)
        if successor is None or not unique:
            return False
        if self._turn_public(successor):
            return False
        rule_set_id = str(self._get(debate, "rule_set_id", default=""))
        if not self._turn_ready(successor) or not self._turn_fence_ready(
            turns, successor, rule_set_id=rule_set_id
        ):
            return False
        if not self._has_public_predecessor_prefix(turns, successor, rule_set_id=rule_set_id):
            return False
        if self._validated_turn_audio(db, debate, successor) is None:
            return False
        return True

    def _replay_queue(
        self,
        db: Any,
        debate: Any,
        state: PlaybackRuntime,
    ) -> tuple[list[Any], bool]:
        """Resolve the immutable whole-replay list and its structural validity.

        ``replay_turn_ids`` is persisted when the migration provides the
        queue column.  Older rows only have ``replay_scope``/``replay_index``;
        for those rows the public final-ready turns form the deterministic
        queue.  This fallback is safe because a finished Debate cannot publish
        another turn while replay is in progress, and all callers still check
        adjacency and durable audio below.
        """

        if state.replay_scope != "all":
            return [], False
        turns_by_id = {
            str(self._get(turn, "id", default="")): turn for turn in self._turns(db, debate)
        }
        queue_ids = [str(item) for item in state.replay_turn_ids]
        if queue_ids:
            # A persisted queue is a frozen identity list.  Duplicate or
            # missing identities make the replay fail closed rather than
            # silently selecting a different public turn.
            if len(set(queue_ids)) != len(queue_ids):
                return [], False
            queue = [turns_by_id.get(item) for item in queue_ids]
            if any(turn is None for turn in queue):
                return [], False
            resolved = cast(list[Any], queue)
        else:
            resolved = sorted(
                [
                    turn
                    for turn in turns_by_id.values()
                    if self._turn_public(turn)
                    and str(self._get(turn, "generation_status", default="")) == "final_ready"
                ],
                key=lambda item: int(self._get(item, "turn_index", default=-1) or -1),
            )
            if not resolved:
                return [], False
            # Persisting the queue is best effort for compatibility rows.  A
            # read/snapshot path must not mutate the DB; the state-changing
            # replay start path writes it explicitly.
        if any(not self._turn_public(turn) for turn in resolved):
            return [], False
        indexes: list[int] = []
        for turn in resolved:
            try:
                indexes.append(int(self._get(turn, "turn_index", default=-1)))
            except (TypeError, ValueError):
                return [], False
        if indexes != list(range(len(resolved))):
            return [], False
        return resolved, True

    def _replay_next_turn_ready(self, db: Any, debate: Any, state: PlaybackRuntime) -> bool:
        """Derive readiness for exactly one adjacent replay successor.

        Replay readiness is deliberately not inferred from an in-memory
        ``AudioStore`` cache or from ``turn.ready``.  The successor must be
        the unique next item in the frozen public queue and pass the same
        current-course pointer, StoredFile, canonical-path, size/hash and WAV
        validation used by authenticated media reads.
        """

        if (
            state.mode != "replay"
            or state.status != "waiting_next"
            or state.current_turn_id is None
            or state.replay_index is None
        ):
            return False
        queue, valid = self._replay_queue(db, debate, state)
        if not valid:
            return False
        index = int(state.replay_index)
        if index < 0 or index >= len(queue):
            return False
        current = queue[index]
        if str(self._get(current, "id", default="")) != state.current_turn_id:
            return False
        if index + 1 >= len(queue):
            return False
        successor = queue[index + 1]
        # Both the frozen queue and the physical turn plan must agree on the
        # adjacency.  This rejects duplicate/renumbered rows before any CAS.
        adjacent, unique = self._adjacent_successor(self._turns(db, debate), current)
        if not unique or adjacent is None or str(adjacent.id) != str(successor.id):
            return False
        return self._replay_audio_ready(db, debate, successor)

    @classmethod
    def _has_public_predecessor_prefix(
        cls,
        turns: list[Any],
        turn: Any,
        *,
        rule_set_id: str | None = None,
    ) -> bool:
        """Return whether every planned predecessor is already public.

        A final-ready successor may be prepared in the background, but it must
        never become the public current item (or publish at ``started_ack``)
        while any earlier planned turn remains unpublished.  Checking the
        contiguous index sequence as well as the publication flag prevents a
        malformed/partial plan from being treated as a valid prefix.
        """

        try:
            current_index = int(cls._get(turn, "turn_index", default=-1))
        except (TypeError, ValueError):
            return False
        if current_index < 0:
            return False
        is_mutual = rule_set_id == MUTUAL_LEARNING_RULE_SET_ID
        try:
            current_round = int(cls._get(turn, "round_no", default=1) or 1)
        except (TypeError, ValueError):
            return False
        predecessors: list[Any] = []
        for candidate in turns:
            try:
                candidate_index = int(cls._get(candidate, "turn_index", default=-1))
            except (TypeError, ValueError):
                return False
            try:
                candidate_round = int(cls._get(candidate, "round_no", default=1) or 1)
            except (TypeError, ValueError):
                return False
            if candidate_round < current_round if is_mutual else candidate_index < current_index:
                predecessors.append(candidate)
        predecessors.sort(key=lambda candidate: int(cls._get(candidate, "turn_index", default=-1)))
        if is_mutual:
            return all(cls._turn_public(candidate) for candidate in predecessors)
        indices = [int(cls._get(candidate, "turn_index", default=-1)) for candidate in predecessors]
        if indices != list(range(current_index)):
            return False
        return all(cls._turn_public(candidate) for candidate in predecessors)

    @classmethod
    def _validate_playback_action(
        cls,
        state: PlaybackRuntime,
        turn: Any,
        turns: list[Any],
        action: Literal["start", "resume", "next", "replay"],
        *,
        rule_set_id: str | None = None,
    ) -> None:
        """Fail closed when the browser action does not match the item context.

        ``start`` is reserved for the first publication of an unpublished
        live turn. ``next`` is reserved for the unpublished successor that
        the teacher has just authorized. ``resume`` can only continue an
        already public live turn, and ``replay`` can only address an already
        public replay item. This
        check is deliberately pure and runs before ticket/state mutation in
        both media preparation and the browser started acknowledgement.
        """

        public = cls._turn_public(turn)
        if action == "replay":
            if state.mode != "replay" or not public:
                raise conflict(
                    "invalid_state", "Replay action does not match the current public item."
                )
            return
        if state.mode != "live":
            raise invalid_state("Live playback action does not match the current playback mode.")
        if action == "next":
            try:
                turn_index = int(cls._get(turn, "turn_index", default=-1))
            except (TypeError, ValueError):
                turn_index = -1
            if state.status != "ready" or public or turn_index <= 0:
                raise conflict(
                    "invalid_state", "Next action does not match the current unpublished item."
                )
            if not cls._has_public_predecessor_prefix(turns, turn, rule_set_id=rule_set_id):
                raise conflict(
                    "invalid_state",
                    "The live turn cannot be published before its public predecessor prefix.",
                )
            return
        if action == "start":
            try:
                turn_index = int(cls._get(turn, "turn_index", default=-1))
            except (TypeError, ValueError):
                turn_index = -1
            if public or turn_index != 0:
                raise conflict("invalid_state", "A public live turn can only be resumed.")
        elif not public:
            raise conflict("invalid_state", "An unpublished live turn can only be started.")
        if not cls._has_public_predecessor_prefix(turns, turn, rule_set_id=rule_set_id):
            raise conflict(
                "invalid_state",
                "The live turn cannot be published before its public predecessor prefix.",
            )

    @staticmethod
    def _word_count(text: str) -> int:
        return len(_WORD_RE.findall(text))

    @staticmethod
    def _sources(turn: Any) -> list[dict[str, Any]]:
        raw = PlaybackService._get(turn, "sources", "turn_sources", default=()) or ()
        output: list[dict[str, Any]] = []
        for source in raw:
            filename = PlaybackService._get(source, "source_filename", "filename", default=None)
            if not isinstance(filename, str) or not filename.strip():
                continue
            chunk = PlaybackService._get(source, "chunk_id", "evidence_id", default=None)
            item: dict[str, Any] = {"source_filename": filename}
            if chunk is not None:
                try:
                    item["chunk_id"] = str(UUID(str(chunk)))
                except (TypeError, ValueError):
                    pass
            output.append(item)
        return output

    @staticmethod
    def _participant_for_turn(participants: list[Any], turn: Any) -> Any | None:
        participant_id = str(PlaybackService._get(turn, "participant_id", default=""))
        return next(
            (item for item in participants if str(getattr(item, "id", "")) == participant_id), None
        )

    @staticmethod
    def _slot(participant: Any | None) -> str:
        slot = str(PlaybackService._get(participant, "slot", default="A")) if participant else "A"
        return slot if slot in {"A", "B", "C", "D", "E"} else "A"

    @staticmethod
    def _round(turn: Any) -> int:
        return int(PlaybackService._get(turn, "round_no", "round", default=1) or 1)

    @staticmethod
    def _mutual_phase_payload(debate: Any, turn: Any) -> dict[str, Any]:
        """Return versioned phase metadata without changing legacy events."""

        if (
            str(PlaybackService._get(debate, "rule_set_id", default=""))
            != MUTUAL_LEARNING_RULE_SET_ID
        ):
            return {}
        round_count = PlaybackService._get(debate, "round_count", default=None)
        if round_count is None:
            try:
                snapshot = json.loads(
                    str(PlaybackService._get(debate, "rule_snapshot_json", default="{}"))
                )
                round_count = snapshot.get("round_count") if isinstance(snapshot, dict) else None
            except (TypeError, ValueError):
                round_count = None
        if not isinstance(round_count, int) or not 2 <= round_count <= 5:
            return {}
        try:
            phase = phase_for_round(PlaybackService._round(turn), round_count).value
        except ValueError:
            return {}
        return {"phase": phase, "round_count": round_count}

    @staticmethod
    def _mutual_round_count(debate: Any) -> int | None:
        if (
            str(PlaybackService._get(debate, "rule_set_id", default=""))
            != MUTUAL_LEARNING_RULE_SET_ID
        ):
            return None
        value = PlaybackService._get(debate, "round_count", default=None)
        if value is None:
            try:
                snapshot = json.loads(
                    str(PlaybackService._get(debate, "rule_snapshot_json", default="{}"))
                )
                value = snapshot.get("round_count") if isinstance(snapshot, dict) else None
            except (TypeError, ValueError):
                value = None
        return value if isinstance(value, int) and 2 <= value <= 5 else None

    def _current_turn(self, db: Any, debate: Any, state: PlaybackRuntime) -> Any:
        if state.current_turn_id is None:
            raise invalid_state("There is no current playback turn.")
        turn = next(
            (
                item
                for item in self._turns(db, debate)
                if str(getattr(item, "id", "")) == state.current_turn_id
            ),
            None,
        )
        if turn is None:
            raise invalid_state("The current playback turn is unavailable.")
        return turn

    def _check_control(self, state: PlaybackRuntime, expected_control_version: int) -> None:
        if state.control_version != expected_control_version:
            raise conflict(
                "stale_control_version",
                "The playback control version is stale.",
                {"current_control_version": state.control_version},
            )

    def _check_epoch(
        self,
        state: PlaybackRuntime,
        *,
        epoch: str,
        session_hash: str,
    ) -> None:
        if (
            state.controller_epoch != epoch
            or state.controller_session_hash != session_hash
            or state.controller_epoch is None
        ):
            raise conflict("stale_control_version", "The playback controller is no longer active.")

    @staticmethod
    def _cursor(state: PlaybackRuntime) -> int:
        if state.status != "playing" or state.started_monotonic is None:
            return max(0, int(state.cursor_ms))
        elapsed = max(0.0, time.monotonic() - state.started_monotonic)
        value = state.cursor_ms + int(elapsed * 1000 * state.playback_rate)
        if state.audio_duration_ms > 0:
            value = min(value, state.audio_duration_ms)
        return max(0, value)

    @staticmethod
    def _set_playing(state: PlaybackRuntime) -> None:
        state.status = "playing"
        state.started_monotonic = time.monotonic()

    @staticmethod
    def _set_nonplaying(state: PlaybackRuntime, status: str, cursor_ms: int | None = None) -> None:
        if cursor_ms is not None:
            state.cursor_ms = max(0, min(int(cursor_ms), state.audio_duration_ms or int(cursor_ms)))
        state.status = status
        state.started_monotonic = None

    def _state_dto(
        self,
        state: PlaybackRuntime,
        db: Any | None = None,
        debate: Any | None = None,
    ) -> PlaybackStateDTO:
        if debate is None:
            next_turn_ready = False
        elif state.mode == "replay":
            next_turn_ready = self._replay_next_turn_ready(db, debate, state)
        else:
            next_turn_ready = self._next_turn_ready(db, debate, state)
        return PlaybackStateDTO(
            status=state.status,  # type: ignore[arg-type]
            mode=state.mode,  # type: ignore[arg-type]
            current_turn_id=UUID(state.current_turn_id) if state.current_turn_id else None,
            cursor_ms=self._cursor(state),
            playback_rate=max(0.95, min(1.25, state.playback_rate)),
            control_version=state.control_version,
            next_turn_ready=next_turn_ready,
        )

    async def _emit(
        self,
        debate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        db: Any | None = None,
    ) -> EventRecord:
        """Append and publish one event as a standalone transaction.

        State-changing callers use ``_stage_event`` directly and commit their
        state plus event together.  Keeping this small compatibility wrapper
        is useful for callers that only need an event (and for the memory
        repository), while making it impossible for the SQL path to perform a
        second post-state event transaction by accident.
        """

        db = db or self._db_hint
        event = self._stage_event(db, debate_id, event_type, payload)
        self._commit(db)
        await self._publish_event(event)
        return event

    def _stage_event(
        self,
        db: Any | None,
        debate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> EventRecord:
        """Stage a validated event in the caller's state transaction.

        M10's SQL repository owns the durable debate watermark and event row.
        The fallback memory store appends immediately because its state is an
        in-memory object with no rollback boundary; both paths publish only
        after the caller commits.
        """

        transaction = getattr(self.repository, "append_event_tx", None)
        if db is not None and callable(transaction):
            return cast(
                EventRecord,
                transaction(
                    db,
                    debate_id=debate_id,
                    event_type=event_type,
                    payload=payload,
                ),
            )
        transaction = getattr(self.repository, "append_event_transaction", None)
        if db is not None and callable(transaction):
            # The short-lived compatibility name used by one integration
            # branch accepts positional arguments; keep this adapter tolerant
            # while the repository converges on append_event_tx.
            return cast(
                EventRecord,
                transaction(db, debate_id, event_type, payload),
            )
        validated = validate_event_payload(event_type, payload)
        event = EventRecord(
            event_id=str(uuid4()),
            debate_id=debate_id,
            sequence=self.event_hub.store.last_sequence(debate_id) + 1,
            event_type=event_type,
            event_version=1,
            occurred_at=datetime.now(UTC),
            payload=validated,
        )
        self.event_hub.store.append_event(event)
        return event

    async def _publish_event(self, event: EventRecord) -> None:
        await self.event_hub.publish(event)

    async def _publish_events(self, events: list[EventRecord]) -> None:
        for event in events:
            await self._publish_event(event)

    def _default_prepared(self, debate: Any, turn: Any, participant: Any | None) -> PreparedTurn:
        name = str(self._get(participant, "name", "agent_name", default="Agent"))
        topic = str(self._get(debate, "topic", default="the discussion"))
        round_no = self._round(turn)
        # Deterministic Mock copy: it intentionally carries no factual claim
        # or source, preserving the no-match honesty boundary when M11 is not
        # connected yet.  There are exactly 80+ words, including no question.
        words = (
            f"{name} approaches {topic} as a classroom question about responsibility, "
            "evidence, and the choices communities make when technology changes daily life. "
            f"In round {round_no}, this perspective values careful listening and "
            "clear distinctions. "
            "A policy should protect people from real harm while leaving room for legitimate "
            "expression, innovation, and cultural exchange. The strongest answer compares likely "
            "benefits with costs, acknowledges uncertainty, and explains who carries each burden. "
            "This statement is a general reasoned position rather than a claim from the knowledge "
            "base. It invites the other participant to examine assumptions, clarify trade offs, "
            "and consider practical safeguards before choosing a final conclusion."
        )
        return PreparedTurn(
            speech=words, retrieval_status="no_match", grounding_mode="general_reasoning"
        )

    async def _call_preparer(self, db: Any, debate: Any, turn: Any, attempt: int) -> PreparedTurn:
        participant = self._participant_for_turn(self._participants(db, debate), turn)
        if self.turn_preparer is None:
            existing_speech = self._get(turn, "speech", "original_text", default=None)
            if isinstance(existing_speech, str) and existing_speech.strip():
                return PreparedTurn(
                    speech=existing_speech,
                    sources=tuple(
                        RetrievalSourceDTO.model_validate(value) for value in self._sources(turn)
                    ),
                    retrieval_status=str(self._get(turn, "retrieval_status", default="no_match")),
                    grounding_mode=str(
                        self._get(turn, "grounding_mode", default="general_reasoning")
                    ),
                    structured=dict(
                        self._get(turn, "structured", "structured_json", default={}) or {}
                    ),
                    voice_token=str(
                        self._get(participant, "effective_voice_profile_id", default="mock")
                        or "mock"
                    ),
                    evidence_trace=tuple(self._evidence_trace(turn)),
                )
            return self._default_prepared(debate, turn, participant)
        result = self.turn_preparer(
            db,
            debate,
            turn,
            attempt=attempt,
            cancellation_generation=int(
                self._get(debate, "cancellation_generation", default=0) or 0
            ),
        )
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, PreparedTurn):
            return result
        if not isinstance(result, Mapping):
            raise ValueError("turn preparer returned an invalid result")
        source_values = result.get("sources", ())
        sources = tuple(
            item
            if isinstance(item, RetrievalSourceDTO)
            else RetrievalSourceDTO.model_validate(item)
            for item in source_values
        )
        receipt_values = result.get("source_receipts", ()) or ()
        receipts = tuple(
            item if isinstance(item, PreparedSource) else PreparedSource(**dict(item))
            for item in receipt_values
        )
        return PreparedTurn(
            speech=str(result.get("speech", "")),
            sources=sources,
            retrieval_status=str(result.get("retrieval_status", "no_match")),
            grounding_mode=str(result.get("grounding_mode", "general_reasoning")),
            structured=dict(result.get("structured", {})),
            voice_token=str(result.get("voice_token", "mock")),
            actual_voice_kind=str(result.get("actual_voice_kind", "mock_sentinel")),
            actual_voice_profile_id=(
                str(result["actual_voice_profile_id"])
                if result.get("actual_voice_profile_id") is not None
                else None
            ),
            source_receipts=receipts,
            predecessor_turn_ids=tuple(
                str(item) for item in result.get("predecessor_turn_ids", ())
            ),
            transcript_hash=(
                str(result["transcript_hash"])
                if result.get("transcript_hash") is not None
                else None
            ),
            cutoff_turn_index=(
                int(result["cutoff_turn_index"])
                if result.get("cutoff_turn_index") is not None
                else None
            ),
            word_count=(
                int(result["word_count"]) if result.get("word_count") is not None else None
            ),
            generation_attempt=int(result.get("generation_attempt", attempt) or attempt),
            evidence_trace=tuple(
                dict(item)
                for item in self._evidence_trace(
                    {"evidence_trace": result.get("evidence_trace", ())}
                )
            ),
            llm_publication=result.get("llm_publication"),
        )

    async def _generation_fence(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        *,
        attempt: int,
        cancellation_generation: int,
    ) -> PreparedGenerationFence | None:
        """Resolve M11's prompt-prefix fence before any provider call.

        The SQL turn preparer exposes this as a small provider-free method.
        Keeping the lookup optional preserves the in-memory repository and
        older test doubles, while the SQL repository can require the exact
        predecessor hash/CAS identity.
        """

        preparer = self.turn_preparer
        if preparer is None:
            return None
        resolver = getattr(preparer, "generation_fence", None)
        value: Any = None
        if callable(resolver):
            try:
                value = resolver(
                    db,
                    debate,
                    turn,
                    attempt=attempt,
                    cancellation_generation=cancellation_generation,
                )
            except TypeError:
                # Keep compatibility with a provider-free resolver that only
                # accepts the three immutable row arguments.
                value = resolver(db, debate, turn)
            if inspect.isawaitable(value):
                value = await value
        elif isinstance(resolver, PreparedGenerationFence):
            value = resolver
        if isinstance(value, PreparedGenerationFence):
            return value
        # A prepared row from a previous attempt may already carry the exact
        # fence.  Do not invent a hash when it is absent: SQL must fail closed
        # instead of allowing an unbound provider result to commit.
        predecessor_value = self._get(turn, "predecessor_turn_ids", default=None)
        if predecessor_value is None:
            predecessor_value = self._get(turn, "predecessor_turn_ids_json", default=None)
            if isinstance(predecessor_value, str):
                try:
                    import json

                    parsed = json.loads(predecessor_value)
                    predecessor_value = parsed if isinstance(parsed, list) else ()
                except (TypeError, ValueError):
                    predecessor_value = ()
        transcript_hash = self._get(turn, "transcript_hash", "predecessor_hash", default=None)
        cutoff = self._get(turn, "cutoff_turn_index", default=None)
        if transcript_hash is None or cutoff is None:
            return None
        return PreparedGenerationFence(
            predecessor_turn_ids=tuple(str(item) for item in predecessor_value or ()),
            transcript_hash=str(transcript_hash),
            cutoff_turn_index=int(cutoff),
            attempt=attempt,
        )

    def _resolve_voice(
        self,
        db: Any,
        participant: Any | None,
    ) -> ResolvedTurnVoice:
        resolver = getattr(self.repository, "resolve_effective_voice", None)
        if callable(resolver):
            value = resolver(db, participant, self.settings)
            if isinstance(value, ResolvedTurnVoice):
                return value
            if isinstance(value, Mapping):
                return ResolvedTurnVoice(
                    kind=str(value.get("kind", "mock_sentinel")),
                    profile_id=(
                        str(value["profile_id"]) if value.get("profile_id") is not None else None
                    ),
                    voice_token=str(value.get("voice_token", "mock")),
                )
        return ResolvedTurnVoice(
            kind="mock_sentinel",
            profile_id=None,
            voice_token=str(
                self._get(participant, "effective_voice_profile_id", default="mock") or "mock"
            ),
        )

    @staticmethod
    def _validate_prepared(prepared: PreparedTurn) -> PreparedTurn:
        speech = prepared.speech.strip()
        count = PlaybackService._word_count(speech)
        if not speech or count < 80 or count > 200:
            raise ValueError("turn speech word count is invalid")
        sources = tuple(prepared.sources)
        if sources:
            # Wave 2 intentionally uses mixed rather than claiming claim-level
            # RAG grounding.  Retrieval status is derived from receipt use.
            return replace(
                prepared,
                speech=speech,
                sources=sources,
                retrieval_status="matched",
                grounding_mode="mixed",
                word_count=count,
            )
        return replace(
            prepared,
            speech=speech,
            sources=(),
            source_receipts=(),
            retrieval_status="no_match",
            grounding_mode="general_reasoning",
            word_count=count,
        )

    def _provider_allowed(self) -> None:
        if self.settings is not None:
            embedding = getattr(self.settings, "embedding_provider", "mock")
            blocked_selectors = (
                getattr(self.settings, "tts_provider", "mock"),
                getattr(self.settings, "voice_provider", "mock"),
                getattr(self.settings, "translation_provider", None) or "mock",
            )
            if embedding not in {"mock", "dashscope"} or any(
                value != "mock" for value in blocked_selectors
            ):
                raise PlatformError(
                    "provider_unavailable", "The service is temporarily unavailable.", 503
                )
        if getattr(self.tts_provider, "key", "mock") != "mock":
            raise PlatformError(
                "provider_unavailable", "The service is temporarily unavailable.", 503
            )

    async def prepare_turn(self, db: Any, debate_id: str, turn_id: str) -> None:
        """Generate/TTS one current or immediate successor with CAS fencing."""

        async with self._lock:
            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
            turns = self._turns(db, debate)
            turn = next((item for item in turns if str(getattr(item, "id", "")) == turn_id), None)
            if turn is None or str(getattr(debate, "status", "")) != "running":
                return
            if state.current_turn_id is None:
                return
            current_index = next(
                (
                    index
                    for index, item in enumerate(turns)
                    if str(getattr(item, "id", "")) == state.current_turn_id
                ),
                -1,
            )
            if current_index < 0:
                return
            turn_index = int(self._get(turn, "turn_index", default=current_index) or current_index)
            if turn_index not in {current_index, current_index + 1}:
                return
            if turn_index == current_index + 1:
                previous = turns[current_index]
                previous_generation = str(
                    self._get(previous, "generation_status", default="pending")
                )
                if previous_generation not in {"final_ready", "ready", "completed"}:
                    return
            cancellation_generation = int(
                self._get(debate, "cancellation_generation", default=0) or 0
            )
            if self._turn_ready(turn):
                return
            claim_token: str | None = None
            generation_fence: PreparedGenerationFence | None = None
            claim_job = getattr(self.repository, "claim_turn_job", None)
            if callable(claim_job):
                claim_token = claim_job(
                    db,
                    debate,
                    turn,
                    cancellation_generation=cancellation_generation,
                )
                if claim_token is None:
                    return
                generation_fence = await self._generation_fence(
                    db,
                    debate,
                    turn,
                    attempt=1,
                    cancellation_generation=cancellation_generation,
                )
                mark_running = getattr(self.repository, "mark_turn_running", None)
                if not callable(mark_running):
                    return
                mark_kwargs: dict[str, Any] = {
                    "cancellation_generation": cancellation_generation,
                    "claim_token": claim_token,
                }
                # M12 remains compatible with the early repository double,
                # while the SQL adapter receives the exact M11 prefix fence
                # before any RAG/LLM/TTS provider call.
                try:
                    mark_signature = inspect.signature(mark_running)
                    accepts_fence = "fence" in mark_signature.parameters or any(
                        parameter.kind is inspect.Parameter.VAR_KEYWORD
                        for parameter in mark_signature.parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_fence = True
                if accepts_fence:
                    mark_kwargs["fence"] = generation_fence
                if not mark_running(db, turn, **mark_kwargs):
                    return
            else:
                turn.generation_status = "running"
                turn.preparation_stage = "generation"
                if hasattr(turn, "failed_code"):
                    turn.failed_code = None
            participants = self._participants(db, debate)
            participant = self._participant_for_turn(participants, turn)
            slot = self._slot(participant)
            round_no = self._round(turn)
            is_current = turn_index == current_index
            staged_events: list[EventRecord] = []
            if is_current:
                staged_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "turn.preparing",
                        {
                            "turn_id": turn_id,
                            "slot": slot,
                            "round_no": round_no,
                            "stage": "llm",
                            **self._mutual_phase_payload(debate, turn),
                        },
                    )
                )
            self._save(db, debate, state)
            self._commit(db)

        await self._publish_events(staged_events)

        ready_events: list[EventRecord] = []
        next_turn_to_enqueue: Any | None = None
        last_error: Exception | None = None
        audio: Any | None = None
        prepared: PreparedTurn | None = None
        try:
            # M11 owns the single shared attempt 1|2 repair budget.  Playback
            # invokes that orchestrator once and therefore cannot multiply two
            # generation attempts into four provider calls.
            prepared = self._validate_prepared(await self._call_preparer(db, debate, turn, 1))
            # Accepted LLM stage + its recovery input must survive a process
            # crash before TTS.  Generation deliberately leaves the provider
            # operation ``accepted``; only the final mark_turn_ready
            # transaction may promote it to ``succeeded``.
            if prepared.llm_publication is not None:
                self._commit(db)
            voice = self._resolve_voice(db, participant)
            prepared = replace(
                prepared,
                voice_token=voice.voice_token,
                actual_voice_kind=voice.kind,
                actual_voice_profile_id=voice.profile_id,
            )
            self._provider_allowed()
            voice_token = prepared.voice_token
            if self.audio_store is None:
                from .audio import AudioStore

                root = getattr(self.settings, "resolved_data_root", None)
                if root is None:
                    raise TTSProviderError("audio store is not configured")
                self.audio_store = AudioStore(root, tts_provider=self.tts_provider)
            audio = self.audio_store.synthesize_and_store(
                course_id=self._course_id(debate),
                debate_id=debate_id,
                turn_id=turn_id,
                speech=prepared.speech,
                voice_token=voice_token,
            )
            async with self._lock:
                fresh_debate = self._get_debate(db, debate_id)
                fresh_turn = next(
                    (
                        item
                        for item in self._turns(db, fresh_debate)
                        if str(getattr(item, "id", "")) == turn_id
                    ),
                    None,
                )
                if (
                    fresh_turn is None
                    or str(getattr(fresh_debate, "status", "")) != "running"
                    or int(self._get(fresh_debate, "cancellation_generation", default=0) or 0)
                    != cancellation_generation
                    or self._get(fresh_turn, "generation_status", default="")
                    not in {"running", "pending"}
                ):
                    self.audio_store.remove_turn(debate_id, turn_id)
                    return
                accepted = self.repository.mark_turn_ready(
                    db,
                    fresh_turn,
                    prepared,
                    audio,
                    generation=cancellation_generation,
                    attempt=prepared.generation_attempt,
                    claim_token=claim_token,
                )
                if not accepted:
                    self.audio_store.remove_turn(debate_id, turn_id)
                    return
                current_state = self._state(db, fresh_debate)
                current_turns = self._turns(db, fresh_debate)
                current_index = next(
                    (
                        index
                        for index, item in enumerate(current_turns)
                        if str(getattr(item, "id", "")) == current_state.current_turn_id
                    ),
                    0,
                )
                is_current = (
                    int(self._get(fresh_turn, "turn_index", default=0) or 0) == current_index
                )
                ready_events = []
                if is_current:
                    current_state.status = "ready"
                    current_state.cursor_ms = 0
                    current_state.audio_duration_ms = audio.duration_ms
                    current_state.pending_action = None
                    current_state.pending_ticket_hash = None
                    current_state.pending_media_command_id = None
                    self._clear_media_results(debate_id)
                    self._save(db, fresh_debate, current_state)
                    ready_events.append(
                        self._stage_event(
                            db,
                            debate_id,
                            "turn.ready",
                            {
                                "turn_id": turn_id,
                                "slot": self._slot(
                                    self._participant_for_turn(
                                        self._participants(db, fresh_debate), fresh_turn
                                    )
                                ),
                                "round_no": self._round(fresh_turn),
                                "audio_ready": True,
                                "retrieval_status": prepared.retrieval_status,
                                "grounding_mode": prepared.grounding_mode,
                                "audio_duration_ms": audio.duration_ms,
                                **self._mutual_phase_payload(fresh_debate, fresh_turn),
                            },
                        )
                    )
                elif (
                    current_state.mode == "live"
                    and current_state.status == "waiting_next"
                    and current_state.current_turn_id is not None
                    and self._next_turn_ready(db, fresh_debate, current_state)
                ):
                    # A successor may finish its slow generation/TTS after
                    # the current turn has ended.  Only the readiness bit is
                    # public; the completed current turn and its control
                    # version remain the event's sole identity.
                    ready_events.append(
                        self._stage_event(
                            db,
                            debate_id,
                            "playback.waiting_next",
                            {
                                "mode": "live",
                                "completed_turn_id": current_state.current_turn_id,
                                "control_version": current_state.control_version,
                                "next_turn_ready": True,
                            },
                        )
                    )
                self._commit(db)
                if is_current:
                    next_turn = (
                        current_turns[current_index + 1]
                        if current_index + 1 < len(current_turns)
                        else None
                    )
                    if next_turn is not None:
                        next_turn_to_enqueue = next_turn
            await self._publish_events(ready_events)
            if next_turn_to_enqueue is not None:
                await self._enqueue(fresh_debate, next_turn_to_enqueue)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            # The final Turn/source/job writes and the LLM operation CAS share
            # this transaction.  Roll back before either the recoverable or
            # terminal handler starts a new state transition.
            self._rollback(db)
            if audio is not None and self.audio_store is not None:
                self.audio_store.remove_turn(debate_id, turn_id)
        error_code = getattr(last_error, "code", None) or getattr(last_error, "safe_code", None)
        recoverable_provider_error = error_code in {
            "provider_confirmation_required",
            "provider_not_sent",
            "acceptance_unknown",
        }
        recoverable_tts_error = (
            isinstance(error_code, str)
            and error_code.startswith("tts_")
            and prepared is not None
            and prepared.llm_publication is not None
        )
        if (
            (recoverable_provider_error or recoverable_tts_error)
            and await self._defer_provider_preparation(
                db,
                debate_id=debate_id,
                turn_id=turn_id,
                claim_token=claim_token,
                code=str(error_code),
            )
        ):
            return
        failed_event: EventRecord | None = None
        failed_epoch: str | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            turns = self._turns(db, debate)
            turn = next((item for item in turns if str(getattr(item, "id", "")) == turn_id), turn)
            code = "turn_generation_failed"
            if isinstance(last_error, PlatformError) and last_error.code in _SAFE_GENERATION_CODES:
                code = last_error.code
            elif error_code in _SAFE_GENERATION_CODES:
                code = str(error_code)
            fail_job = getattr(self.repository, "fail_turn_job", None)
            if callable(fail_job):
                fail_job(db, turn, claim_token, code)
            self.repository.fail_turn_and_debate(db, debate, turn, code)
            state = self._state(db, debate)
            self._set_nonplaying(state, "stopped")
            state.control_version += 1
            failed_epoch = state.controller_epoch
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            self._controller_sessions.pop(debate_id, None)
            self._save(db, debate, state)
            failed_event = self._stage_event(
                db,
                debate_id,
                "debate.failed",
                {
                    "final_states": {
                        "debate": "failed",
                        "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                        "interaction": "closed",
                        "insight": "not_started",
                        "report": "not_started",
                    },
                    "downstream_outcome": "failed",
                    "safe_error_code": code,
                },
            )
            self._commit(db)
            self.ticket_store.revoke_debate(debate_id)
            if failed_epoch is not None:
                self._revoke_epoch(failed_epoch, debate_id, "debate_terminal")
        if failed_event is not None:
            await self._publish_event(failed_event)

    async def _defer_provider_preparation(
        self,
        db: Any,
        *,
        debate_id: str,
        turn_id: str,
        claim_token: str | None,
        code: str,
    ) -> bool:
        """Park an exact provider-gated turn while keeping its Debate resumable."""

        self._rollback(db)
        deferred_event: EventRecord | None = None
        async with self._lock:
            try:
                debate = self._get_debate(db, debate_id)
                turns = self._turns(db, debate)
                turn = next(
                    (item for item in turns if str(getattr(item, "id", "")) == turn_id),
                    None,
                )
                if turn is None or str(getattr(debate, "status", "")) != "running":
                    return False
                defer = getattr(self.repository, "defer_turn_job", None)
                if not callable(defer) or not defer(db, debate, turn, claim_token, code):
                    self._rollback(db)
                    return False
                deferred_event = self._stage_event(
                    db,
                    debate_id,
                    "error",
                    {
                        "code": code,
                        "message": (
                            "Teacher confirmation is required before this turn can continue."
                            if code == "provider_confirmation_required"
                            else (
                                "The provider acceptance is unknown and requires reconciliation."
                                if code == "acceptance_unknown"
                                else (
                                    "The TTS stage did not complete. The accepted LLM result "
                                    "is retained for a local retry."
                                    if code.startswith("tts_")
                                    else (
                                        "The provider request was not sent. "
                                        "The teacher may retry safely."
                                    )
                                )
                            )
                        ),
                        "recoverable": True,
                    },
                )
                self._commit(db)
            except Exception:
                self._rollback(db)
                return False
        if deferred_event is not None:
            await self._publish_event(deferred_event)
        return deferred_event is not None

    async def _enqueue(self, debate: Any, turn: Any) -> bool:
        try:
            return await self.task_manager.enqueue(
                self._debate_id(debate),
                str(turn.id),
                self._prepare_task,
            )
        except RuntimeError:
            # A synchronous caller can explicitly invoke prepare_turn.  Do not
            # run unbounded background work on a closed request loop.
            return False

    async def _prepare_task(self, debate_id: str, turn_id: str) -> None:
        db = self.session_factory() if self.session_factory else self._db_hint
        # MemoryPlaybackRepository deliberately has no Session; its task
        # callback still runs so pure controller tests exercise the same
        # preparation/ack path as the SQL composition.
        if db is None and not isinstance(self.repository, MemoryPlaybackRepository):
            return
        try:
            await self.prepare_turn(db, debate_id, turn_id)
        finally:
            close = getattr(db, "close", None)
            if self.session_factory and callable(close):
                close()

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def _prepare_audio_swap(
        self,
        db: Any,
        *,
        course_id: str,
        old_debate_id: str,
        new_debate_id: str,
        request_id: str,
        expected_old_debate_id: str | None,
        idempotency_record_id: str | None = None,
    ) -> tuple[Any | None, str] | None:
        """Persist the typed swap intent, then atomically stage old bytes.

        ``setup.audio_swap`` owns the durable FileOperation shape while this
        package owns the physical rename.  The helper is intentionally
        optional for the memory test double; a real SQL session always has the
        existing journal table after migration 0004.
        """

        if self.audio_store is None:
            return None
        try:
            from app.modules.debates.setup.audio_swap import (
                AudioSwapRequest,
                AudioSwapState,
                create_audio_swap_journal,
                transition_audio_swap,
            )
        except ImportError:
            return None
        if not hasattr(db, "add"):
            return None
        source = f"courses/{course_id}/current-debate-audio/{old_debate_id}"
        staging = f"staging/audio-swap/{course_id}/{request_id}/{old_debate_id}"
        request = AudioSwapRequest(
            course_id=course_id,
            request_id=request_id,
            old_debate_id=old_debate_id,
            source_relative_path=source,
            staging_relative_path=staging,
            new_debate_id=new_debate_id,
            expected_old_debate_id=expected_old_debate_id,
            idempotency_record_id=idempotency_record_id,
        )
        try:
            journal = create_audio_swap_journal(db, request)
            self._commit(db)
            moved = self.audio_store.stage_debate_directory(
                course_id=course_id,
                debate_id=old_debate_id,
                staging_relative_path=staging,
            )
            transition_audio_swap(
                db,
                str(journal.id),
                expected_state=AudioSwapState.PREPARED,
                target_state=AudioSwapState.STAGED,
            )
            self._commit(db)
            return (journal, staging if moved else "")
        except Exception as exc:
            # A failure before the final Debate transaction must restore old
            # bytes and leave a durable recovered journal.  Never use the
            # generic delete-both recovery path.
            try:
                if "moved" in locals() and moved:
                    self.audio_store.restore_staged_debate(
                        course_id=course_id,
                        debate_id=old_debate_id,
                        staging_relative_path=staging,
                    )
                if "journal" in locals():
                    db.rollback()
                    transition_audio_swap(
                        db,
                        str(journal.id),
                        expected_state=AudioSwapState.PREPARED,
                        target_state=AudioSwapState.RECOVERED,
                    )
                    self._commit(db)
            except Exception:
                self._rollback(db)
            raise PlatformError(
                "file_operation_failed",
                "The previous retained audio could not be staged safely.",
                503,
            ) from exc

    def _commit_audio_swap(
        self,
        db: Any,
        swap: tuple[Any | None, str] | None,
        *,
        course_id: str,
        old_debate_id: str,
    ) -> None:
        if swap is None:
            return
        journal, staging = swap
        if journal is None:
            return
        try:
            from app.modules.debates.setup.audio_swap import (
                AudioSwapState,
                transition_audio_swap,
            )

            if self.audio_store is not None:
                if staging:
                    self.audio_store.delete_staging(staging)
                self.audio_store.remove_debate(old_debate_id)
                self.ticket_store.revoke_debate(old_debate_id)
            mark_deleted = getattr(self.repository, "mark_debate_audio_deleted", None)
            if callable(mark_deleted):
                mark_deleted(db, old_debate_id)
            transition_audio_swap(
                db,
                str(journal.id),
                expected_state=AudioSwapState.COMMITTED,
                target_state=AudioSwapState.CLEANUP_REQUIRED,
            )
            transition_audio_swap(
                db,
                str(journal.id),
                expected_state=AudioSwapState.CLEANUP_REQUIRED,
                target_state=AudioSwapState.RECOVERED,
            )
            self._commit(db)
        except Exception:
            # The final DB pointer is authoritative and already committed.
            # Leave cleanup to startup journal recovery instead of returning
            # an ambiguous failure that could provoke a duplicate start.
            self._rollback(db)
            return

    def _restore_audio_swap(
        self,
        db: Any,
        swap: tuple[Any | None, str] | None,
        *,
        course_id: str,
        old_debate_id: str,
    ) -> None:
        if swap is None:
            return
        journal, staging = swap
        try:
            if staging and self.audio_store is not None:
                self.audio_store.restore_staged_debate(
                    course_id=course_id,
                    debate_id=old_debate_id,
                    staging_relative_path=staging,
                )
            if journal is not None:
                from app.modules.debates.setup.audio_swap import (
                    AudioSwapState,
                    transition_audio_swap,
                )

                transition_audio_swap(
                    db,
                    str(journal.id),
                    expected_state=AudioSwapState.STAGED,
                    target_state=AudioSwapState.RECOVERED,
                )
                self._commit(db)
        except Exception as exc:
            self._rollback(db)
            raise PlatformError(
                "file_operation_failed",
                "The previous retained audio could not be restored safely.",
                503,
            ) from exc

    def _recover_claim_audio_swaps(self, db: Any, idempotency_record: Any) -> bool:
        """Recover typed audio journals before an expired start claim is replaced."""

        if self.audio_store is None or not hasattr(db, "scalars"):
            return False
        from app.modules.debates.setup.audio_swap import (
            audio_swap_journals_for_idempotency,
            recover_audio_swap,
        )

        journals = audio_swap_journals_for_idempotency(db, str(idempotency_record.id))
        for journal in journals:
            new_debate = self.repository.get_debate(db, str(journal.new_debate_id))
            if new_debate is None:
                raise RuntimeError("audio swap recovery cannot resolve its Debate")
            course_id = self._course_id(new_debate)
            current_pointer = self.repository.current_audio_debate_id(db, course_id)
            outcome = recover_audio_swap(
                db,
                str(journal.id),
                current_audio_debate_id=current_pointer,
            )
            staging = outcome.staging_relative_path
            if outcome.action == "restore_old" and outcome.old_debate_id and staging:
                self.audio_store.restore_staged_debate(
                    course_id=course_id,
                    debate_id=outcome.old_debate_id,
                    staging_relative_path=staging,
                )
            elif outcome.action == "delete_staging" and staging:
                self.audio_store.delete_staging(staging)
                if outcome.old_debate_id:
                    self.audio_store.remove_debate(outcome.old_debate_id)
                    self.ticket_store.revoke_debate(outcome.old_debate_id)
                    mark_deleted = getattr(self.repository, "mark_debate_audio_deleted", None)
                    if callable(mark_deleted):
                        mark_deleted(db, outcome.old_debate_id)
        return bool(journals)

    def _terminate_previous_playback(
        self,
        db: Any,
        old_debate_id: str,
    ) -> tuple[dict[str, Any] | None, EventRecord | None]:
        """Fence an old retained playback before a new Debate starts.

        M10's SQL adapter performs the durable state update in the caller's
        start transaction.  The fallback mirrors the same semantics for the
        memory repository.  The old controller epoch is revoked only after
        the start transaction commits; its committed completion event is
        published at that same boundary.
        """

        terminator = getattr(self.repository, "terminate_retained_playback", None)
        if callable(terminator):
            raw_info = terminator(db, old_debate_id)
            info = dict(raw_info) if isinstance(raw_info, Mapping) else None
        else:
            old_debate = self.repository.get_debate(db, old_debate_id)
            if old_debate is None:
                return None, None
            old_state = self._state(db, old_debate)
            active = old_state.mode == "replay" or old_state.controller_epoch is not None
            if not active:
                return None, None
            old_turn_id = old_state.current_turn_id
            old_epoch = old_state.controller_epoch
            old_state.status = "completed"
            old_state.mode = "live"
            old_state.replay_scope = None
            old_state.replay_turn_ids = []
            old_state.replay_index = None
            old_state.pending_action = None
            old_state.pending_ticket_hash = None
            old_state.pending_media_command_id = None
            old_state.audio_duration_ms = 0
            old_state.controller_epoch = None
            old_state.controller_session_hash = None
            old_state.controller_connection_id = None
            old_state.started_monotonic = None
            old_state.cursor_ms = 0
            old_state.control_version += 1
            self._save(db, old_debate, old_state)
            self._clear_media_results(old_debate_id)
            info = {
                "turn_id": old_turn_id,
                "control_version": old_state.control_version,
                "controller_epoch": old_epoch,
                "previous_status": "replay",
                "cursor_ms": 0,
                "playback_rate": old_state.playback_rate,
            }
        if info is None:
            return None, None
        turn_id = info.get("turn_id")
        try:
            turn_value = str(UUID(str(turn_id))) if turn_id is not None else None
        except (TypeError, ValueError):
            turn_value = None
        if turn_value is None:
            return info, None
        try:
            control_version = int(info.get("control_version", 0) or 0)
            cursor_ms = int(info.get("cursor_ms", 0) or 0)
            playback_rate = float(info.get("playback_rate", 1.0) or 1.0)
            event = self._stage_event(
                db,
                old_debate_id,
                "playback.completed",
                {
                    "turn_id": turn_value,
                    "cursor_ms": max(0, cursor_ms),
                    "control_version": max(0, control_version),
                    "playback_rate": max(0.95, min(1.25, playback_rate)),
                },
            )
        except (TypeError, ValueError):
            # A malformed/legacy retained row must not block the new start;
            # the durable state still remains authoritative and the old epoch
            # is revoked after commit below.
            event = None
        return info, event

    async def start(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_revision: int,
        expected_current_audio_debate_id: str | None,
        confirm_previous_audio_cleanup: bool,
        context: AuthContext | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> PlaybackStateDTO:
        # A historical draft can predate the English-topic rule.  Check it
        # before an idempotency claim, audio swap, plan/job creation, or any
        # playback state mutation.  Replays of an already-started debate keep
        # their existing idempotency semantics because only draft topics are
        # subject to this preflight gate.
        preflight_debate = self._get_debate(db, debate_id)
        self._assert_teacher(db, preflight_debate, context)
        if str(self._get(preflight_debate, "status", default="draft")) == "draft":
            try:
                validate_english_topic(self._get(preflight_debate, "topic", default=""))
            except TopicLanguageError as exc:
                raise PlatformError(exc.code, exc.message, 422, exc.details) from exc
        idempotency_record: Any | None = None
        if idempotency_key and context is not None:
            from app.modules.knowledge.services import (
                assert_claim_owned,
                claim_idempotency,
                request_hash,
            )

            body_hash = request_hash(
                "startDebate",
                str(context.user.id),
                [debate_id],
                {
                    "expected_revision": expected_revision,
                    "expected_current_audio_debate_id": expected_current_audio_debate_id,
                    "confirm_previous_audio_cleanup": confirm_previous_audio_cleanup,
                },
            )
            idempotency_record, replay = claim_idempotency(
                db,
                context,
                "startDebate",
                idempotency_key,
                body_hash,
                data_root=(
                    getattr(self.settings, "resolved_data_root", None)
                    if self.settings is not None
                    else None
                ),
                takeover_recovery=self._recover_claim_audio_swaps,
            )
            if replay is not None:
                # The first response is a DebateDetail in the public route;
                # the playback state is the stable portion consumed by this
                # orchestrator and is returned without another side effect.
                debate = self._get_debate(db, debate_id)
                return self._state_dto(self._state(db, debate), db, debate)
            assert_claim_owned(db, idempotency_record)
        staged_events: list[EventRecord] = []
        previous_playback: dict[str, Any] | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            if str(getattr(debate, "status", "draft")) != "draft":
                raise invalid_state("Only a draft debate can be started.")
            try:
                validate_english_topic(self._get(debate, "topic", default=""))
            except TopicLanguageError as exc:
                raise PlatformError(exc.code, exc.message, 422, exc.details) from exc
            revision = int(self._get(debate, "revision", default=0) or 0)
            if revision != expected_revision:
                raise conflict(
                    "stale_revision",
                    "The debate draft revision is stale.",
                    {"current_revision": revision},
                )
            course_id = self._course_id(debate)
            current_pointer = self.repository.current_audio_debate_id(db, course_id)
            if current_pointer != expected_current_audio_debate_id:
                raise conflict("stale_control_version", "The retained audio pointer changed.")
            if current_pointer and not confirm_previous_audio_cleanup:
                raise conflict(
                    "previous_audio_cleanup_confirmation_required",
                    "Confirm removal of the previous retained audio before starting.",
                )
            if self.repository.course_running(db, course_id, except_debate_id=debate_id):
                raise conflict(
                    "debate_already_running", "Another debate is already running for this course."
                )
            swap = None
            if current_pointer and confirm_previous_audio_cleanup:
                swap = self._prepare_audio_swap(
                    db,
                    course_id=course_id,
                    old_debate_id=current_pointer,
                    new_debate_id=debate_id,
                    request_id=request_id or idempotency_key or str(uuid4()),
                    expected_old_debate_id=expected_current_audio_debate_id,
                    idempotency_record_id=(
                        str(idempotency_record.id) if idempotency_record is not None else None
                    ),
                )
                if swap is None and not isinstance(self.repository, MemoryPlaybackRepository):
                    raise PlatformError(
                        "file_operation_failed",
                        "The retained audio swap journal is unavailable.",
                        503,
                    )
                previous_playback, previous_event = self._terminate_previous_playback(
                    db, current_pointer
                )
                if previous_event is not None:
                    staged_events.append(previous_event)
            turns = list(self.repository.ensure_turn_plan(db, debate))
            turns.sort(key=lambda item: int(self._get(item, "turn_index", default=0) or 0))
            if not turns:
                raise invalid_state("The debate has no planned turns.")
            ensure_jobs = getattr(self.repository, "ensure_turn_jobs", None)
            if callable(ensure_jobs):
                ensure_jobs(db, debate, turns)
            state = self._state(db, debate)
            state.status = "preparing"
            state.mode = "live"
            state.current_turn_id = str(turns[0].id)
            state.cursor_ms = 0
            state.replay_scope = None
            state.replay_turn_ids = []
            state.replay_index = 0
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            self._save(db, debate, state)
            # Revalidate teacher authority after the independently committed
            # idempotency/journal steps and immediately before the final CAS.
            self._assert_teacher(db, debate, context)
            commit_start = getattr(self.repository, "commit_start_state", None)
            try:
                if callable(commit_start):
                    journal_id = (
                        str(swap[0].id) if swap is not None and swap[0] is not None else None
                    )
                    if not commit_start(
                        db,
                        debate,
                        expected_revision=expected_revision,
                        expected_audio_pointer=expected_current_audio_debate_id,
                        journal_id=journal_id,
                    ):
                        raise conflict(
                            "stale_revision",
                            "The Debate start conditions changed before commit.",
                        )
                else:
                    debate.status = "running"
                    if not self.repository.set_current_audio_debate(db, course_id, debate_id):
                        raise conflict(
                            "stale_control_version",
                            "The retained audio pointer changed.",
                        )
                if idempotency_record is not None:
                    from app.modules.debates.setup.service import get_debate
                    from app.modules.knowledge.services import finish_idempotency

                    if context is None:  # pragma: no cover - claim requires context
                        raise RuntimeError("idempotency claim has no authenticated actor")
                    db.flush()
                    db.expire_all()
                    response_payload = get_debate(
                        db,
                        actor_user_id=str(context.user.id),
                        debate_id=debate_id,
                    ).model_dump(mode="json")
                    finish_idempotency(
                        db,
                        idempotency_record,
                        200,
                        response_payload,
                    )
                first = turns[0]
                participants = self._participants(db, debate)
                participant_payload = [
                    {
                        "participant_id": str(item.id),
                        "slot": self._slot(item),
                        "order_index": int(self._get(item, "order_index", default=index) or index),
                        "name": str(self._get(item, "name", "agent_name", default="Agent")),
                    }
                    for index, item in enumerate(participants)
                ]
                staged_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "debate.started",
                        {
                            "rule_set_id": str(
                                self._get(
                                    debate,
                                    "rule_set_id",
                                    default="ordered_multi_agent_rounds_demo_v1",
                                )
                            ),
                            **(
                                {
                                    "round_count": self._mutual_round_count(debate),
                                }
                                if str(
                                    self._get(
                                        debate,
                                        "rule_set_id",
                                        default="",
                                    )
                                )
                                == MUTUAL_LEARNING_RULE_SET_ID
                                else {}
                            ),
                            "participants": participant_payload,
                        },
                    )
                )
                staged_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "round.started",
                        {
                            "round_no": self._round(first),
                            **self._mutual_phase_payload(debate, first),
                            "turn_count": len(
                                [item for item in turns if self._round(item) == self._round(first)]
                            ),
                        },
                    )
                )
                self._commit(db)
            except PlatformError:
                self._rollback(db)
                if current_pointer:
                    self._restore_audio_swap(
                        db,
                        swap,
                        course_id=course_id,
                        old_debate_id=current_pointer,
                    )
                raise
            except Exception as exc:
                self._rollback(db)
                if current_pointer:
                    self._restore_audio_swap(
                        db,
                        swap,
                        course_id=course_id,
                        old_debate_id=current_pointer,
                    )
                raise PlatformError(
                    "file_operation_failed",
                    "The debate could not be started safely.",
                    503,
                ) from exc
            if current_pointer:
                self._commit_audio_swap(
                    db,
                    swap,
                    course_id=course_id,
                    old_debate_id=current_pointer,
                )
        if previous_playback is not None:
            self.ticket_store.revoke_debate(current_pointer)  # type: ignore[arg-type]
            self._controller_sessions.pop(str(current_pointer), None)
            previous_epoch = previous_playback.get("controller_epoch")
            if previous_epoch:
                self._revoke_epoch(str(previous_epoch), str(current_pointer), "start_next")
        await self._publish_events(staged_events)
        first = turns[0]
        await self._enqueue(debate, first)
        return self._state_dto(state, db, debate)

    async def retry_preparation(
        self,
        db: Any,
        debate_id: str,
        *,
        turn_id: str,
        expected_control_version: int,
        context: AuthContext | None = None,
        idempotency_key: str | None = None,
    ) -> PlaybackStateDTO:
        """Explicitly retry one teacher-confirmed or proven-not-sent turn."""

        record: Any | None = None
        replay = False
        target: Any | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            record, replay = self._claim_control_idempotency(
                db,
                context=context,
                operation="retryDebatePreparation",
                key=idempotency_key,
                body={
                    "debate_id": debate_id,
                    "turn_id": turn_id,
                    "expected_control_version": expected_control_version,
                },
            )
            if replay:
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                return self._state_dto(state, db, debate)
            if str(self._get(debate, "status", default="")) != "running":
                raise invalid_state("Only a running Debate can retry preparation.")
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if state.mode != "live" or state.current_turn_id is None:
                raise invalid_state("Live playback has no retryable turn.")
            turns = sorted(
                self._turns(db, debate),
                key=lambda item: int(self._get(item, "turn_index", default=0) or 0),
            )
            current_index = next(
                (
                    index
                    for index, item in enumerate(turns)
                    if str(getattr(item, "id", "")) == state.current_turn_id
                ),
                -1,
            )
            target_index = next(
                (
                    index
                    for index, item in enumerate(turns)
                    if str(getattr(item, "id", "")) == turn_id
                ),
                -1,
            )
            if current_index < 0 or target_index not in {current_index, current_index + 1}:
                raise invalid_state("Only the current or adjacent prepared turn can be retried.")
            target = turns[target_index]
            code = str(self._get(target, "safe_error_code", "failed_code", default="") or "")
            if (
                self._get(target, "generation_status", default="") != "pending"
                or code not in _RECOVERABLE_PROVIDER_GENERATION_CODES
            ):
                raise invalid_state("The selected turn is not waiting for a safe provider retry.")
            state.control_version += 1
            self._save(db, debate, state)
            result = self._state_dto(state, db, debate)
            self._finish_control_idempotency(db, record, result)
            self._commit(db)
        if target is not None:
            await self._enqueue(debate, target)
        return result

    async def pause(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
        idempotency_key: str | None = None,
    ) -> PlaybackStateDTO:
        record: Any | None = None
        replay = False
        paused_event: EventRecord | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            record, replay = self._claim_control_idempotency(
                db,
                context=context,
                operation="pauseDebate",
                key=idempotency_key,
                body={
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                },
            )
            if replay:
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                return self._state_dto(state, db, debate)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if state.status != "playing" or state.current_turn_id is None:
                raise invalid_state("Playback is not currently playing.")
            cursor = self._cursor(state)
            claim_pause = getattr(self.repository, "claim_pause_playback", None)
            if callable(claim_pause) and context is not None:
                # End any read snapshot before the independent writer CAS.
                self._rollback(db)
                claimed = bool(
                    claim_pause(
                        debate_id=debate_id,
                        expected_control_version=expected_control_version,
                        cursor_ms=cursor,
                        teacher_user_id=str(context.user.id),
                    )
                )
                if not claimed:
                    raise conflict(
                        "stale_control_version",
                        "The playback state changed before Pause was committed.",
                    )
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
            else:
                self._set_nonplaying(state, "paused", cursor)
                state.control_version += 1
                state.pending_action = None
                state.pending_ticket_hash = None
                state.pending_media_command_id = None
                state.audio_duration_ms = 0
                self._clear_media_results(debate_id)
                self._save(db, debate, state)
            turn_id = state.current_turn_id
            payload = {
                "turn_id": turn_id,
                "cursor_ms": state.cursor_ms,
                "control_version": state.control_version,
                "playback_rate": state.playback_rate,
            }
            paused_event = self._stage_event(db, debate_id, "playback.paused", payload)
            result = self._state_dto(state, db, debate)
            self._finish_control_idempotency(db, record, result)
            self._commit(db)
        if turn_id is not None:
            self.ticket_store.revoke_item(debate_id, turn_id)
        if paused_event is not None:
            await self._publish_event(paused_event)
        return result

    async def resume(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
        idempotency_key: str | None = None,
    ) -> PlaybackStateDTO:
        record: Any | None = None
        replay = False
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            record, replay = self._claim_control_idempotency(
                db,
                context=context,
                operation="resumeDebate",
                key=idempotency_key,
                body={
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                },
            )
            if replay:
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                return self._state_dto(state, db, debate)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if state.status != "paused" or state.current_turn_id is None:
                raise invalid_state("Playback is not paused.")
            turn = self._current_turn(db, debate, state)
            if not self._turn_ready(turn):
                raise invalid_state("The current turn is not ready for playback.")
            claim_resume = getattr(self.repository, "claim_resume_playback", None)
            if callable(claim_resume) and context is not None:
                self._rollback(db)
                claimed = bool(
                    claim_resume(
                        debate_id=debate_id,
                        expected_control_version=expected_control_version,
                        teacher_user_id=str(context.user.id),
                    )
                )
                if not claimed:
                    raise conflict(
                        "stale_control_version",
                        "The playback state changed before Continue was committed.",
                    )
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
            else:
                self._set_nonplaying(state, "ready")
                state.control_version += 1
                state.pending_action = None
                state.pending_ticket_hash = None
                state.pending_media_command_id = None
                state.audio_duration_ms = 0
                self._save(db, debate, state)
            result = self._state_dto(state, db, debate)
            self._finish_control_idempotency(db, record, result)
            self._commit(db)
        return result

    async def skip(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        skip_events: list[EventRecord] = []
        next_turn_to_enqueue: Any | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if state.status != "playing" or state.current_turn_id is None or state.mode != "live":
                raise invalid_state("Only the current live playback can be skipped.")
            current = self._current_turn(db, debate, state)
            if not self._turn_ready(current):
                raise invalid_state("The current turn is not ready for playback.")
            turns = self._turns(db, debate)
            if not self._turn_public(current) or not self._has_public_predecessor_prefix(
                turns,
                current,
                rule_set_id=str(self._get(debate, "rule_set_id", default="")),
            ):
                raise conflict(
                    "invalid_state",
                    "The live turn cannot advance before its public predecessor prefix.",
                )
            cursor = self._cursor(state)
            index = next(
                index for index, item in enumerate(turns) if str(item.id) == state.current_turn_id
            )
            state.control_version += 1
            self.ticket_store.revoke_item(debate_id, state.current_turn_id)
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            if index + 1 >= len(turns):
                self._set_nonplaying(state, "completed", cursor)
                debate.status = "debate_finished"
                self.repository.save_debate(db, debate)
                next_ready = False
                next_turn = None
            else:
                # Live skip is a teacher-controlled stop at the current
                # turn.  It must never grant the adjacent turn authority;
                # only the explicit REST Next CAS may do that.
                next_turn = turns[index + 1]
                self._set_nonplaying(state, "waiting_next", cursor)
                state.replay_scope = None
                state.replay_index = None
                next_ready = self._next_turn_ready(db, debate, state)
            self._save(db, debate, state)
            payload = {
                "turn_id": str(current.id),
                "cursor_ms": cursor,
                "control_version": state.control_version,
                "playback_rate": state.playback_rate,
            }
            skip_events.append(self._stage_event(db, debate_id, "playback.skipped", payload))
            if next_turn is not None:
                if not next_ready:
                    ensure_job = getattr(self.repository, "ensure_turn_job", None)
                    if callable(ensure_job):
                        ensure_job(db, debate, next_turn)
                    next_turn_to_enqueue = next_turn
                skip_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "playback.waiting_next",
                        {
                            "mode": "live",
                            "completed_turn_id": str(current.id),
                            "control_version": state.control_version,
                            "next_turn_ready": next_ready,
                        },
                    )
                )
            self._commit(db)
        await self._publish_events(skip_events)
        if next_turn_to_enqueue is not None:
            await self._enqueue(debate, next_turn_to_enqueue)
        return self._state_dto(state, db, debate)

    async def finish(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        expected_current_turn_id: str | None = None,
        context: AuthContext | None = None,
        idempotency_key: str | None = None,
    ) -> PlaybackStateDTO:
        """Finish a Debate as full or partial under one teacher CAS.

        A full finish requires every planned turn to be final-ready and
        already public. An explicit early Finish is represented by the
        product-level ``debate_finished`` status while playback remains
        terminal ``stopped``; immutable generated/public turns remain in the
        database and downstream routes must still enforce the complete-plan
        gate.
        """

        record: Any | None = None
        replay = False
        terminal_event: EventRecord | None = None
        terminal_epoch: str | None = None
        partial = False
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            record, replay = self._claim_control_idempotency(
                db,
                context=context,
                operation="finishDebate",
                key=idempotency_key,
                body={
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                    "expected_current_turn_id": expected_current_turn_id,
                },
            )
            if replay:
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                return self._state_dto(state, db, debate)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if (
                expected_current_turn_id is not None
                and state.current_turn_id != expected_current_turn_id
            ):
                raise conflict(
                    "stale_control_version",
                    "The playback current turn is stale.",
                    {"current_current_turn_id": state.current_turn_id},
                )
            if str(self._get(debate, "status", default="")) != "running":
                raise invalid_state("Only a running debate can be finished.")
            if state.status != "waiting_next" or state.mode != "live":
                raise invalid_state(
                    "A debate can be finished only while waiting for the teacher's next command."
                )

            turns = self._turns(db, debate)
            total = len(turns)
            complete_count = sum(
                1
                for turn in turns
                if self._get(turn, "generation_status", default="") == "final_ready"
                and self._get(turn, "publication_status", default="") in {"public", "published"}
            )
            is_full = total > 0 and complete_count == total
            claim_finish = getattr(self.repository, "claim_finish_playback", None)
            if callable(claim_finish) and context is not None:
                # Keep the old process-local epoch before the independent
                # SQL claim clears it.  The callback is revoked after commit
                # so a stale WebSocket cannot continue issuing commands.
                terminal_epoch = state.controller_epoch
                self._rollback(db)
                claimed = claim_finish(
                    debate_id=debate_id,
                    expected_control_version=expected_control_version,
                    expected_current_turn_id=expected_current_turn_id,
                    teacher_user_id=str(context.user.id),
                )
                if not claimed:
                    raise conflict(
                        "stale_control_version",
                        "The Debate changed before Finish was committed.",
                    )
                partial = str(claimed.get("kind")) == "partial"
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                self._controller_sessions.pop(debate_id, None)
                # The fresh SQL claim is authoritative; do not let a stale
                # request-session count override its full/partial decision.
                is_full = not partial
            else:
                partial = not is_full
                if partial:
                    # A teacher's explicit early Finish is a product-level
                    # finished state, while playback remains terminal/stopped
                    # so all downstream complete-plan gates stay closed.
                    debate.status = "debate_finished"
                    timestamp = datetime.now(UTC)
                    if hasattr(debate, "finished_at"):
                        debate.finished_at = timestamp
                    if hasattr(debate, "updated_at"):
                        debate.updated_at = timestamp
                    debate.cancellation_generation = (
                        int(self._get(debate, "cancellation_generation", default=0) or 0) + 1
                    )
                    self.repository.mark_jobs_interrupted(db, debate, "debate_finished_partial")
                    self.repository.save_debate(db, debate)
                    self._set_nonplaying(state, "stopped")
                else:
                    debate.status = "debate_finished"
                    if hasattr(debate, "finished_at"):
                        debate.finished_at = datetime.now(UTC)
                    self.repository.save_debate(db, debate)
                    self._set_nonplaying(state, "completed")
                state.control_version += 1
                state.current_turn_id = None
                state.mode = "live"
                state.replay_scope = None
                state.replay_turn_ids = []
                state.replay_index = None
                state.pending_action = None
                state.pending_ticket_hash = None
                state.pending_media_command_id = None
                state.audio_duration_ms = 0
                terminal_epoch = state.controller_epoch
                state.controller_epoch = None
                state.controller_session_hash = None
                state.controller_connection_id = None
                self._controller_sessions.pop(debate_id, None)
                self._clear_media_results(debate_id)
                self._save(db, debate, state)

            # Reloaded SQL state already has a terminal status and cleared
            # authority.  Build one durable event from that exact state.
            terminal_epoch = terminal_epoch or state.controller_epoch
            if partial:
                terminal_event = self._stage_event(
                    db,
                    debate_id,
                    "debate.stopped",
                    {
                        "final_states": {
                            "debate": "debate_finished",
                            "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                            "interaction": "closed",
                            "insight": "not_started",
                            "report": "not_started",
                        },
                        "downstream_outcome": "stopped",
                        "safe_error_code": "debate_finished_partial",
                    },
                )
            else:
                event_turn = next(
                    (turn for turn in reversed(turns) if self._turn_public(turn)),
                    turns[-1] if turns else None,
                )
                if event_turn is not None:
                    terminal_event = self._stage_event(
                        db,
                        debate_id,
                        "playback.completed",
                        {
                            "turn_id": str(event_turn.id),
                            "cursor_ms": 0,
                            "control_version": state.control_version,
                            "playback_rate": state.playback_rate,
                        },
                    )
            result = self._state_dto(state, db, debate)
            self._finish_control_idempotency(db, record, result)
            self._commit(db)
        if partial:
            await self.task_manager.cancel_debate(debate_id)
            self.ticket_store.revoke_debate(debate_id)
        else:
            self.ticket_store.revoke_debate(debate_id)
        if terminal_epoch is not None:
            self._revoke_epoch(terminal_epoch, debate_id, "debate_terminal")
        if terminal_event is not None:
            await self._publish_event(terminal_event)
        return result

    async def next(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        expected_current_turn_id: str,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        """Authorize exactly one adjacent live or replay successor.

        Live and replay use the same teacher/CAS boundary, but they never
        share a queue or generation path. Replay Next only moves an already
        public retained turn; the browser performs the media handshake for
        that newly current item.
        """

        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if state.current_turn_id != expected_current_turn_id:
                raise conflict(
                    "stale_control_version",
                    "The playback current turn is stale.",
                    {"current_current_turn_id": state.current_turn_id},
                )
            debate_status = str(self._get(debate, "status", default=""))
            if state.status != "waiting_next":
                raise invalid_state("Playback is not waiting for the teacher's next command.")

            turns = sorted(
                self._turns(db, debate),
                key=lambda item: int(self._get(item, "turn_index", default=0) or 0),
            )
            current = self._current_turn(db, debate, state)
            is_replay = state.mode == "replay"
            queue: list[Any] = []
            replay_audio_metadata: AudioMetadata | None = None
            if is_replay:
                if debate_status not in {"debate_finished", "completed"}:
                    raise invalid_state("Replay is available only after the debate finishes.")
                queue, queue_valid = self._replay_queue(db, debate, state)
                if not queue_valid:
                    raise conflict("invalid_state", "The replay queue is unavailable.")
                try:
                    replay_index = int(state.replay_index) if state.replay_index is not None else -1
                except (TypeError, ValueError):
                    replay_index = -1
                if (
                    replay_index < 0
                    or replay_index >= len(queue)
                    or str(queue[replay_index].id) != str(current.id)
                ):
                    raise conflict("invalid_state", "The replay cursor is unavailable.")
                successor = queue[replay_index + 1] if replay_index + 1 < len(queue) else None
                if successor is None:
                    raise conflict("no_next_turn", "The replay has no adjacent successor.")
                adjacent, unique = self._adjacent_successor(turns, current)
                if not unique or adjacent is None or str(adjacent.id) != str(successor.id):
                    raise conflict("invalid_state", "The replay turn plan has multiple successors.")
                if not self._replay_next_turn_ready(db, debate, state):
                    raise conflict(
                        "next_not_ready",
                        "The adjacent retained replay turn is not ready for playback.",
                    )
                replay_audio_metadata = self._validated_turn_audio(db, debate, successor)
                if replay_audio_metadata is None:
                    raise conflict(
                        "next_not_ready",
                        "The adjacent retained replay turn is not ready for playback.",
                    )
            else:
                if debate_status != "running":
                    raise invalid_state("Only a running debate can advance to the next turn.")
                if state.mode != "live":
                    raise invalid_state("Playback is not in live mode.")
                if not self._turn_public(current) or not self._has_public_predecessor_prefix(
                    turns,
                    current,
                    rule_set_id=str(self._get(debate, "rule_set_id", default="")),
                ):
                    raise conflict(
                        "invalid_state",
                        "The live turn cannot advance before its public predecessor prefix.",
                    )
                successor, unique = self._adjacent_successor(turns, current)
                if successor is None:
                    if unique:
                        raise conflict(
                            "no_next_turn", "The current turn has no adjacent successor."
                        )
                    raise conflict(
                        "invalid_state", "The playback turn plan has multiple successors."
                    )
                if not self._next_turn_ready(db, debate, state):
                    raise conflict(
                        "next_not_ready",
                        "The adjacent next turn is not ready for playback.",
                    )

            advance_cas = getattr(self.repository, "advance_playback_cas", None)
            fresh_claim = getattr(
                self.repository,
                "claim_replay_next_playback" if is_replay else "claim_next_playback",
                None,
            )
            if callable(fresh_claim):
                # SQL repositories never write through the request Session:
                # it may be holding a WAL read snapshot from the checks above.
                teacher_user_id = str(context.user.id) if context is not None else ""
                claim_kwargs: dict[str, Any] = {
                    "debate_id": str(debate.id),
                    "expected_control_version": expected_control_version,
                    "expected_current_turn_id": expected_current_turn_id,
                    "successor_turn_id": str(successor.id),
                    "teacher_user_id": teacher_user_id,
                }
                if is_replay:
                    claim_kwargs["expected_replay_index"] = int(state.replay_index or 0)
                    claim_kwargs["expected_audio_relative_path"] = (
                        replay_audio_metadata.relative_path
                        if replay_audio_metadata is not None
                        else None
                    )
                    claim_kwargs["expected_audio_sha256"] = (
                        replay_audio_metadata.sha256 if replay_audio_metadata is not None else None
                    )
                    claim_kwargs["expected_audio_size_bytes"] = (
                        replay_audio_metadata.size_bytes
                        if replay_audio_metadata is not None
                        else None
                    )
                claimed = fresh_claim(
                    **claim_kwargs,
                )
                if not claimed:
                    raise conflict(
                        "stale_control_version",
                        "The playback transition was claimed by another controller.",
                        {"current_control_version": state.control_version},
                    )
                # Discard the old read snapshot before rebuilding the DTO from
                # the committed claim.  No stale runtime mutation is written.
                self._rollback(db)
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
                # The durable media slot stays empty until the browser's
                # single media.prepare command wins its own CAS.  The stage
                # derives replay/next action from this ready state, so do not
                # pre-fill pending_action here and accidentally reject it.
                state.pending_action = None
                if is_replay and not self._replay_audio_ready(db, debate, successor):
                    if not self._rollback_replay_next(db, debate, state):
                        raise conflict(
                            "stale_control_version",
                            "The replay transition was superseded before media validation.",
                        )
                    raise conflict(
                        "next_not_ready",
                        "The adjacent retained replay turn is not ready for playback.",
                    )
                return self._state_dto(state, db, debate)
            if (
                not is_replay
                and callable(advance_cas)
                and not advance_cas(
                    db,
                    debate,
                    expected_control_version=expected_control_version,
                    expected_current_turn_id=expected_current_turn_id,
                    successor_turn_id=str(successor.id),
                )
            ):
                raise conflict(
                    "stale_control_version",
                    "The playback transition was claimed by another controller.",
                    {"current_control_version": state.control_version},
                )

            if is_replay:
                state.replay_turn_ids = [str(item.id) for item in queue]
                state.replay_index = int(state.replay_index or 0) + 1
            state.current_turn_id = str(successor.id)
            state.cursor_ms = 0
            state.started_monotonic = None
            state.status = "ready"
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            metadata = self._validated_turn_audio(db, debate, successor)
            state.audio_duration_ms = int(metadata.duration_ms) if metadata is not None else 0
            if is_replay and not self._replay_audio_ready(db, debate, successor):
                if not self._rollback_replay_next(db, debate, state):
                    raise conflict(
                        "stale_control_version",
                        "The replay transition was superseded before media validation.",
                    )
                raise conflict(
                    "next_not_ready",
                    "The adjacent retained replay turn is not ready for playback.",
                )
            state.control_version += 1
            self._save(db, debate, state)
            self._commit(db)
            return self._state_dto(state, db, debate)

    async def stop(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        stopped_event: EventRecord | None = None
        stopped_epoch: str | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            if str(getattr(debate, "status", "")) != "running":
                raise invalid_state("Only a running debate can be stopped.")
            if state.status in {"completed", "stopped"}:
                raise invalid_state("Only active playback can be stopped.")
            debate.status = "stopped"
            debate.cancellation_generation = (
                int(self._get(debate, "cancellation_generation", default=0) or 0) + 1
            )
            self.repository.mark_jobs_interrupted(db, debate, "debate_stopped")
            self.repository.save_debate(db, debate)
            current_id = state.current_turn_id
            cursor = self._cursor(state)
            self._set_nonplaying(state, "stopped", cursor)
            state.control_version += 1
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            stopped_epoch = state.controller_epoch
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            self._controller_sessions.pop(debate_id, None)
            self._save(db, debate, state)
            payload = {
                "final_states": {
                    "debate": "stopped",
                    "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                    "interaction": "closed",
                    "insight": "not_started",
                    "report": "not_started",
                },
                "downstream_outcome": "stopped",
                "safe_error_code": None,
            }
            stopped_event = self._stage_event(db, debate_id, "debate.stopped", payload)
            self._commit(db)
            if current_id:
                self.ticket_store.revoke_item(debate_id, current_id)
        await self.task_manager.cancel_debate(debate_id)
        self.ticket_store.revoke_debate(debate_id)
        if stopped_epoch is not None:
            self._revoke_epoch(stopped_epoch, debate_id, "debate_terminal")
        if stopped_event is not None:
            await self._publish_event(stopped_event)
        return self._state_dto(state, db, debate)

    def _write_operator_reset_audit(
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
        """Write the redacted reset audit row or fail the reset.

        SQL production repositories use ``claim_operator_reset`` so this hook
        is only the in-memory repository seam.  There is deliberately no
        best-effort fallback: an operator reset without an AuditLog is an
        invalid transition.
        """

        writer = getattr(self.repository, "write_playback_reset_audit", None)
        if not callable(writer):
            raise PlatformError(
                "audit_log_failed",
                "Operator reset requires an AuditLog writer.",
                503,
            )
        try:
            writer(
                db,
                debate_id=debate_id,
                actor_user_id=actor_user_id,
                previous_mode=previous_mode,
                resulting_status=resulting_status,
                control_version=control_version,
                request_id=request_id,
            )
        except Exception as exc:
            raise PlatformError(
                "audit_log_failed",
                "Operator reset could not write its AuditLog.",
                503,
            ) from exc

    async def operator_reset(
        self,
        db: Any,
        debate_id: str,
        *,
        confirm: bool,
        expected_control_version: int | None = None,
        actor_user_id: str | None = None,
        context: AuthContext | None = None,
        request_id: str | None = None,
    ) -> PlaybackStateDTO:
        """Recover one stuck playback through the local operator boundary.

        ``confirm`` is intentionally mandatory and this method is not wired
        into FastAPI.  Reset versus Next is serialized by the same service
        lock; the losing stale command observes the incremented control
        version.  A live abnormal run becomes stopped, while replay returns
        to the completed historical view without touching turn content.
        """

        if not confirm:
            raise conflict(
                "reset_confirmation_required",
                "Explicit reset confirmation is required.",
            )
        reset_event: EventRecord | None = None
        reset_epoch: str | None = None
        # SQL deployments must claim reset through a fresh writer transaction.
        # The request Session may have read a stale WAL snapshot, and neither
        # its state mutation nor a process-local audit fallback can serialize
        # reset against another service instance's Next claim.
        sql_reset = getattr(self.repository, "claim_operator_reset", None)
        if callable(sql_reset):
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            expected = (
                state.control_version
                if expected_control_version is None
                else expected_control_version
            )
            try:
                result = sql_reset(
                    debate_id=debate_id,
                    expected_control_version=expected,
                    actor_kind="operator",
                    actor_id=(str(context.user.id) if context is not None else actor_user_id),
                    request_id=request_id,
                    teacher_user_id=(str(context.user.id) if context is not None else None),
                )
            except PlatformError:
                self._rollback(db)
                raise
            except Exception as exc:
                self._rollback(db)
                raise PlatformError(
                    "audit_log_failed",
                    "Operator reset could not commit its AuditLog transaction.",
                    503,
                ) from exc
            self._rollback(db)
            if not bool(result.get("claimed")):
                reason = str(result.get("reason", "invalid_state"))
                if reason == "stale_control_version":
                    raise conflict(
                        "stale_control_version",
                        "The playback control version is stale.",
                        {"current_control_version": result.get("control_version")},
                    )
                if reason == "not_found":
                    raise not_found()
                if reason == "forbidden":
                    raise forbidden()
                raise invalid_state("Playback is not in an operator-reset state.")

            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
            previous_mode = str(result.get("previous_mode", "live"))
            previous_turn_id = result.get("current_turn_id")
            reset_epoch = result.get("controller_epoch")
            # These fields are intentionally process-local, but clearing them
            # keeps two service instances from retaining an old pending ticket
            # after the durable writer has revoked its epoch.
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._controller_sessions.pop(debate_id, None)
            if previous_mode == "replay":
                reset_event = self._stage_event(
                    db,
                    debate_id,
                    "replay.completed",
                    {
                        "scope": "all",
                        "turn_id": previous_turn_id,
                        "control_version": state.control_version,
                    },
                )
            else:
                reset_event = self._stage_event(
                    db,
                    debate_id,
                    "debate.stopped",
                    {
                        "final_states": {
                            "debate": "stopped",
                            "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                            "interaction": "closed",
                            "insight": "not_started",
                            "report": "not_started",
                        },
                        "downstream_outcome": "stopped",
                        "safe_error_code": "operator_reset",
                    },
                )
            self._commit(db)
            await self.task_manager.cancel_debate(debate_id)
            self.ticket_store.revoke_debate(debate_id)
            if reset_epoch is not None:
                self._revoke_epoch(str(reset_epoch), debate_id, "debate_terminal")
            await self._publish_event(reset_event)
            return self._state_dto(state, db, debate)
        previous_mode = "live"
        resulting_status = "stopped"
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            if expected_control_version is not None:
                self._check_control(state, expected_control_version)
            if state.mode == "live" and state.status in {"completed", "stopped"}:
                raise invalid_state("Playback is not in an operator-reset state.")
            if state.mode == "replay" and state.status == "completed":
                raise invalid_state("Replay is already completed.")
            previous_mode = state.mode
            previous_turn_id = state.current_turn_id
            previous_control_version = state.control_version
            next_control_version = previous_control_version + 1
            resulting_status = "completed" if previous_mode == "replay" else "stopped"
            # Audit is mandatory even for the in-memory test adapter.  Write
            # it before mutating that adapter so a failing writer leaves the
            # reset state untouched, matching the SQL transaction below.
            self._write_operator_reset_audit(
                db,
                debate_id=debate_id,
                actor_user_id=(str(context.user.id) if context is not None else actor_user_id),
                previous_mode=previous_mode,
                resulting_status=resulting_status,
                control_version=next_control_version,
                request_id=request_id,
            )
            state.control_version = next_control_version
            debate.cancellation_generation = (
                int(self._get(debate, "cancellation_generation", default=0) or 0) + 1
            )
            mark_interrupted = getattr(self.repository, "mark_jobs_interrupted", None)
            if callable(mark_interrupted):
                mark_interrupted(db, debate, "operator_reset")
            if previous_mode == "replay":
                if str(self._get(debate, "status", default="")) not in {
                    "debate_finished",
                    "completed",
                }:
                    debate.status = "completed"
                self._set_nonplaying(state, "completed", state.cursor_ms)
            else:
                debate.status = "stopped"
                self._set_nonplaying(state, "stopped", state.cursor_ms)
            self.repository.save_debate(db, debate)
            reset_epoch = state.controller_epoch
            state.mode = "live"
            state.current_turn_id = None
            state.cursor_ms = 0
            state.replay_scope = None
            state.replay_turn_ids = []
            state.replay_index = None
            state.pending_action = None
            state.pending_ticket_hash = None
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            self._controller_sessions.pop(debate_id, None)
            self._save(db, debate, state)
            if previous_mode == "replay":
                reset_event = self._stage_event(
                    db,
                    debate_id,
                    "replay.completed",
                    {
                        "scope": "all",
                        "turn_id": previous_turn_id,
                        "control_version": state.control_version,
                    },
                )
            else:
                reset_event = self._stage_event(
                    db,
                    debate_id,
                    "debate.stopped",
                    {
                        "final_states": {
                            "debate": "stopped",
                            "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
                            "interaction": "closed",
                            "insight": "not_started",
                            "report": "not_started",
                        },
                        "downstream_outcome": "stopped",
                        "safe_error_code": "operator_reset",
                    },
                )
            self._commit(db)
        await self.task_manager.cancel_debate(debate_id)
        self.ticket_store.revoke_debate(debate_id)
        if reset_epoch is not None:
            self._revoke_epoch(reset_epoch, debate_id, "debate_terminal")
        if reset_event is not None:
            await self._publish_event(reset_event)
        return self._state_dto(state, db, debate)

    async def replay_all(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        return await self._begin_replay(db, debate_id, expected_control_version, None, context)

    async def replay_turn(
        self,
        db: Any,
        debate_id: str,
        turn_id: str,
        *,
        expected_control_version: int,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        return await self._begin_replay(db, debate_id, expected_control_version, turn_id, context)

    async def _begin_replay(
        self,
        db: Any,
        debate_id: str,
        expected_control_version: int,
        turn_id: str | None,
        context: AuthContext | None,
    ) -> PlaybackStateDTO:
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            if str(getattr(debate, "status", "")) not in {"debate_finished", "completed"}:
                raise invalid_state("Replay is available only after the debate finishes.")
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            # Product-level ``debate_finished`` also represents an early
            # Finish. Its playback is terminal ``stopped`` and is not a
            # replayable complete plan; only the normal completed/live state
            # can enter the retained Replay catalog.
            if state.status != "completed" or state.mode != "live":
                raise invalid_state("Replay is available only after playback completes.")
            strict_retention = not isinstance(self.repository, MemoryPlaybackRepository) or (
                self.audio_store is not None
            )
            if (
                strict_retention
                and self.repository.current_audio_debate_id(db, self._course_id(debate))
                != debate_id
            ):
                raise conflict(
                    "audio_not_retained", "The requested replay audio is no longer retained."
                )
            public_turns = [item for item in self._turns(db, debate) if self._turn_public(item)]
            public_turns.sort(key=lambda item: int(self._get(item, "turn_index", default=0) or 0))
            if turn_id is not None:
                turns = [item for item in public_turns if str(item.id) == turn_id]
                if not turns:
                    raise not_found()
            else:
                turns = public_turns
            if not turns:
                raise invalid_state("No retained public turn is available for replay.")
            try:
                # Validate the complete selected queue before changing the
                # playback mode.  A corrupt trace is an unavailable replay,
                # never a normal replay event with an empty evidence list.
                for item in turns:
                    self._evidence_trace(item)
            except EvidenceTraceCorruptError as exc:
                raise invalid_state("Replay evidence trace is unavailable.") from exc
            # Full replay is an atomic all-or-nothing eligibility check over
            # every public turn.  Single-turn replay validates only its target.
            if strict_retention and any(
                not self._replay_audio_ready(db, debate, item) for item in turns
            ):
                raise conflict(
                    "audio_not_retained", "The requested replay audio is no longer retained."
                )
            state.mode = "replay"
            state.replay_scope = "turn" if turn_id else "all"
            # Persist the exact public queue for whole replay.  The queue is
            # immutable for the lifetime of this replay; replay readiness and
            # restart recovery must not rediscover a different transcript.
            state.replay_turn_ids = [str(item.id) for item in turns]
            state.replay_index = 0
            state.current_turn_id = state.replay_turn_ids[0]
            state.cursor_ms = 0
            state.status = "ready"
            state.started_monotonic = None
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            state.control_version += 1
            self._save(db, debate, state)
            self._commit(db)
            return self._state_dto(state, db, debate)

    async def controller_acquire(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
        expected_control_version: int,
        session_hash: str,
        connection_id: str,
        context: AuthContext | None = None,
    ) -> ControllerAcquiredResult:
        takeover_event: EventRecord | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            debate_status = str(getattr(debate, "status", ""))
            if debate_status == "draft":
                raise invalid_state("A draft debate has no playback controller.")
            if debate_status in {"failed", "stopped"}:
                raise invalid_state("A failed or stopped debate has no playback controller.")
            if debate_status not in {"running", "debate_finished", "completed"}:
                raise invalid_state("The debate is not in a controllable playback state.")
            state = self._state(db, debate)
            # Stopped playback is irreversible in every mode.  A finished
            # debate may acquire the controller while its live playback state
            # is completed; the teacher still has to issue the explicit REST
            # replay command before any media action is possible.
            if state.status == "stopped":
                raise invalid_state("Stopped playback has no controller.")
            if state.mode == "replay" and debate_status not in {"debate_finished", "completed"}:
                raise invalid_state("Replay is available only after the debate finishes.")
            self._check_control(state, expected_control_version)
            previous_epoch = state.controller_epoch
            previous_connection = state.controller_connection_id
            version_advanced = False
            if previous_epoch and previous_connection != connection_id:
                if state.status == "playing" and state.current_turn_id:
                    cursor = self._cursor(state)
                    self._set_nonplaying(state, "paused", cursor)
                    state.control_version += 1
                    version_advanced = True
                    self._save(db, debate, state)
                    takeover_event = self._stage_event(
                        db,
                        debate_id,
                        "playback.paused",
                        {
                            "turn_id": state.current_turn_id,
                            "cursor_ms": state.cursor_ms,
                            "control_version": state.control_version,
                            "playback_rate": state.playback_rate,
                        },
                    )
                    self._commit(db)
                state.pending_action = None
                state.pending_ticket_hash = None
                state.pending_media_command_id = None
                state.audio_duration_ms = 0
                self._clear_media_results(debate_id)
                self._revoke_epoch(previous_epoch, debate_id, "superseded")
            # Even a paused/ready handoff increments the control version, so
            # the old tab cannot issue a stale command after takeover.
            if not version_advanced:
                state.control_version += 1
            epoch = str(uuid4())
            state.controller_epoch = epoch
            state.controller_session_hash = session_hash
            state.controller_connection_id = connection_id
            self._controller_sessions[debate_id] = session_hash
            self._save(db, debate, state)
            self._commit(db)
            result = ControllerAcquiredResult(
                message_id=uuid4(),
                debate_id=UUID(debate_id),
                occurred_at=datetime.now(UTC),
                command_id=UUID(command_id),
                controller_epoch=UUID(epoch),
                control_version=state.control_version,
            )
        if takeover_event is not None:
            await self._publish_event(takeover_event)
        return result

    def register_connection(
        self,
        epoch: str,
        callback: Callable[[dict[str, Any]], Awaitable[None] | None],
    ) -> None:
        self._connection_callbacks[epoch] = callback

    def unregister_connection(self, epoch: str) -> None:
        self._connection_callbacks.pop(epoch, None)

    def _revoke_epoch(self, epoch: str, debate_id: str, reason: str) -> None:
        result = ControllerRevokedResult(
            message_id=uuid4(),
            debate_id=UUID(debate_id),
            occurred_at=datetime.now(UTC),
            controller_epoch=UUID(epoch),
            reason=reason,  # type: ignore[arg-type]
        ).model_dump(mode="json")
        self._revoked[epoch] = result
        self.ticket_store.revoke_epoch(epoch)
        callback = self._connection_callbacks.get(epoch)
        if callback is not None:
            maybe = callback(result)
            if inspect.isawaitable(maybe):
                # Do not block the takeover transaction for a best-effort
                # private notification; the socket also observes the epoch.
                try:
                    asyncio.create_task(cast(Coroutine[Any, Any, None], maybe))
                except RuntimeError:
                    pass

    def take_revocation(self, epoch: str) -> dict[str, Any] | None:
        return self._revoked.pop(epoch, None)

    async def controller_disconnect(
        self,
        db: Any,
        debate_id: str,
        *,
        epoch: str,
        session_hash: str,
    ) -> None:
        disconnect_event: EventRecord | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
            if state.controller_epoch != epoch or state.controller_session_hash != session_hash:
                return
            if state.status == "playing" and state.current_turn_id:
                cursor = self._cursor(state)
                self._set_nonplaying(state, "paused", cursor)
                state.control_version += 1
                self._save(db, debate, state)
                disconnect_event = self._stage_event(
                    db,
                    debate_id,
                    "playback.paused",
                    {
                        "turn_id": state.current_turn_id,
                        "cursor_ms": state.cursor_ms,
                        "control_version": state.control_version,
                        "playback_rate": state.playback_rate,
                    },
                )
                self._commit(db)
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._controller_sessions.pop(debate_id, None)
            self._clear_media_results(debate_id)
            self._save(db, debate, state)
            self._commit(db)
            self._revoke_epoch(epoch, debate_id, "disconnected")
        if disconnect_event is not None:
            await self._publish_event(disconnect_event)

    async def media_prepare(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
        expected_control_version: int,
        epoch: str,
        session_hash: str,
        turn_id: str,
        action: Literal["start", "resume", "next", "replay"],
        context: AuthContext | None = None,
    ) -> tuple[PreparedMedia, MediaPreparedResult]:
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)

            command_key = (debate_id, command_id)
            previous = self._media_command_results.get(command_key)
            if previous is not None:
                prepared, result = previous
                binding = prepared.binding
                if (
                    state.status == "ready"
                    and state.current_turn_id == turn_id
                    and state.pending_action == action
                    and state.pending_ticket_hash == binding.token_hash
                    and state.pending_media_command_id == command_id
                    and binding.controller_epoch == epoch
                    and binding.session_hash == session_hash
                    and binding.control_version == expected_control_version
                ):
                    # Same command is idempotent in this process.  Reuse the
                    # original private URL; no second ticket is issued.
                    return prepared, result
                self._media_command_results.pop(command_key, None)

            # A pending hash is an authoritative one-ticket fence.  A second
            # command must not replace it, even if the browser reconnects or
            # another service instance owns a separate in-memory ticket map.
            if (
                state.pending_ticket_hash is not None
                or state.pending_action is not None
                or state.pending_media_command_id is not None
            ):
                raise conflict(
                    "duplicate_command",
                    "A media ticket is already pending for this playback item.",
                )
            if state.status != "ready" or state.current_turn_id != turn_id:
                raise not_found()
            turn = self._current_turn(db, debate, state)
            turns = self._turns(db, debate)
            self._validate_playback_action(
                state,
                turn,
                turns,
                action,
                rule_set_id=str(self._get(debate, "rule_set_id", default="")),
            )
            if not self._turn_ready(turn):
                raise not_found()
            if action == "replay":
                try:
                    self._evidence_trace(turn)
                except EvidenceTraceCorruptError as exc:
                    raise invalid_state("Replay evidence trace is unavailable.") from exc
            metadata = self._validated_turn_audio(db, debate, turn)
            if (
                action == "replay"
                and self.repository.current_audio_debate_id(db, self._course_id(debate))
                != debate_id
            ):
                metadata = None
            if metadata is None:
                if action == "replay" and state.replay_index not in {None, 0}:
                    if self._rollback_replay_next(db, debate, state):
                        raise conflict(
                            "next_not_ready",
                            "The retained replay bytes changed before media preparation.",
                        )
                    raise conflict(
                        "stale_control_version",
                        "The replay transition was superseded before media preparation.",
                    )
                raise not_found()
            token, binding = self.ticket_store.issue(
                session_hash=session_hash,
                controller_epoch=epoch,
                debate_id=debate_id,
                turn_id=turn_id,
                action=action,
                control_version=expected_control_version,
            )
            try:
                claim_media = getattr(self.repository, "claim_media_prepare", None)
                if callable(claim_media):
                    claimed = bool(
                        claim_media(
                            debate_id=debate_id,
                            expected_control_version=expected_control_version,
                            controller_epoch=epoch,
                            turn_id=turn_id,
                            ticket_hash=binding.token_hash,
                            command_id=command_id,
                            action=action,
                            audio_duration_ms=int(metadata.duration_ms),
                            expected_audio_relative_path=metadata.relative_path,
                            expected_audio_sha256=metadata.sha256,
                            expected_audio_size_bytes=metadata.size_bytes,
                        )
                    )
                    if not claimed:
                        self.ticket_store.revoke_token(token)
                        self._rollback(db)
                        if action == "replay" and state.replay_index not in {None, 0}:
                            if self._rollback_replay_next(db, debate, state):
                                raise conflict(
                                    "next_not_ready",
                                    "The retained replay bytes changed before media preparation.",
                                )
                        raise conflict(
                            "stale_control_version",
                            "The media ticket claim was superseded.",
                            {"current_control_version": state.control_version},
                        )
                    # The fresh claim committed independently of the request
                    # Session. Re-read the authoritative pending hash before
                    # constructing the private result.
                    self._rollback(db)
                    debate = self._get_debate(db, debate_id)
                    state = self._state(db, debate)
                    post_metadata = self._validated_turn_audio(db, debate, turn)
                    pointer_matches = (
                        action != "replay"
                        or self.repository.current_audio_debate_id(db, self._course_id(debate))
                        == debate_id
                    )
                    same_validated_bytes = bool(
                        post_metadata is not None
                        and post_metadata.relative_path == metadata.relative_path
                        and post_metadata.sha256 == metadata.sha256
                        and post_metadata.size_bytes == metadata.size_bytes
                    )
                    if not pointer_matches or not same_validated_bytes:
                        self.ticket_store.revoke_token(token)
                        replay_index = state.replay_index
                        if action == "replay" and replay_index not in {None, 0}:
                            if self._rollback_replay_next(db, debate, state):
                                raise conflict(
                                    "next_not_ready",
                                    "The retained replay bytes changed before media preparation.",
                                )
                        release_claim = getattr(self.repository, "release_media_prepare", None)
                        released = False
                        if callable(release_claim):
                            released = bool(
                                release_claim(
                                    debate_id=debate_id,
                                    expected_control_version=expected_control_version,
                                    controller_epoch=epoch,
                                    turn_id=turn_id,
                                    ticket_hash=binding.token_hash,
                                    command_id=command_id,
                                )
                            )
                            self._rollback(db)
                        else:
                            state.pending_action = None
                            state.pending_ticket_hash = None
                            state.pending_media_command_id = None
                            state.audio_duration_ms = 0
                            self._save(db, debate, state)
                            self._commit(db)
                            released = True
                        self._clear_media_results(debate_id)
                        if not released:
                            raise conflict(
                                "stale_control_version",
                                "The media ticket claim was superseded.",
                                {"current_control_version": state.control_version},
                            )
                        if action == "replay":
                            raise conflict(
                                "next_not_ready",
                                "The retained replay bytes changed before media preparation.",
                            )
                        raise PlatformError(
                            "audio_not_retained",
                            "This audio is no longer retained.",
                            410,
                        )
                else:
                    state.pending_action = action
                    state.pending_ticket_hash = binding.token_hash
                    state.pending_media_command_id = command_id
                    state.audio_duration_ms = int(metadata.duration_ms)
                    self._save(db, debate, state)
                    self._commit(db)
            except Exception:
                self.ticket_store.revoke_token(token)
                raise
            media_url = f"/api/v1/debates/{debate_id}/audio/{turn_id}?media_ticket={token}"
            result = MediaPreparedResult(
                message_id=uuid4(),
                debate_id=UUID(debate_id),
                occurred_at=datetime.now(UTC),
                command_id=UUID(command_id),
                controller_epoch=UUID(epoch),
                turn_id=UUID(turn_id),
                media_url=media_url,
                expires_at=binding.expires_at,
            )
            prepared = PreparedMedia(media_url, binding.expires_at, token, binding)
            self._media_command_results[command_key] = (prepared, result)
            return prepared, result

    def _find_ticket(
        self,
        *,
        session_hash: str,
        epoch: str,
        debate_id: str,
        turn_id: str,
        action: str,
    ) -> tuple[str, MediaTicketBinding] | None:
        finder = getattr(self.ticket_store, "find", None)
        if callable(finder):
            return cast(
                tuple[str, MediaTicketBinding] | None,
                finder(
                    session_hash=session_hash,
                    controller_epoch=epoch,
                    debate_id=debate_id,
                    turn_id=turn_id,
                    action=action,
                    started=False,
                ),
            )
        return None

    async def started_ack(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
        expected_control_version: int,
        epoch: str,
        session_hash: str,
        turn_id: str,
        action: Literal["start", "resume", "next", "replay"],
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        started_event: EventRecord | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if (
                state.status != "ready"
                or state.current_turn_id != turn_id
                or state.pending_action != action
                or state.pending_ticket_hash is None
                or state.pending_media_command_id is None
            ):
                raise conflict("invalid_state", "The playback acknowledgement is stale.")
            turn = self._current_turn(db, debate, state)
            turns = self._turns(db, debate)
            self._validate_playback_action(
                state,
                turn,
                turns,
                action,
                rule_set_id=str(self._get(debate, "rule_set_id", default="")),
            )
            ticket = self._find_ticket(
                session_hash=session_hash,
                epoch=epoch,
                debate_id=debate_id,
                turn_id=turn_id,
                action=action,
            )
            if ticket is None or ticket[0] != state.pending_ticket_hash:
                raise conflict("invalid_state", "The playback media ticket is unavailable.")
            token_hash, binding = ticket
            if binding.control_version != expected_control_version:
                raise conflict("invalid_state", "The playback media ticket is stale.")
            if action == "replay":
                try:
                    self._evidence_trace(turn)
                except EvidenceTraceCorruptError as exc:
                    raise invalid_state("Replay evidence trace is unavailable.") from exc
            else:
                try:
                    evidence_trace_payload = self._evidence_trace_payload(turn)
                except EvidenceTraceCorruptError as exc:
                    raise invalid_state("Evidence trace is unavailable.") from exc
            self.ticket_store.mark_binding_started(
                binding,
                audio_duration_ms=state.audio_duration_ms,
            )
            if action in {"start", "next"}:
                if not self.repository.publish_turn(db, turn):
                    raise conflict("invalid_state", "The turn is not ready to publish.")
            self._set_playing(state)
            # Keep the action/hash/command bound for the lifetime of the
            # playing item.  Audio authorization must prove that its bearer
            # ticket is the exact media.prepare claim; ended_ack/play_failed
            # clear this fence when the item leaves playback.
            state.pending_ticket_hash = token_hash
            self._save(db, debate, state)
            participants = self._participants(db, debate)
            if action == "replay":
                payload = {
                    "scope": state.replay_scope or "turn",
                    "turn_id": turn_id,
                    "control_version": state.control_version,
                }
                event_type = "replay.started"
            elif action == "resume":
                payload = {
                    "turn_id": turn_id,
                    "cursor_ms": state.cursor_ms,
                    "control_version": state.control_version,
                    "playback_rate": state.playback_rate,
                }
                event_type = "playback.resumed"
            else:
                payload = {
                    "turn_id": turn_id,
                    "slot": self._slot(self._participant_for_turn(participants, turn)),
                    "round_no": self._round(turn),
                    "speech": str(self._get(turn, "speech", "original_text", default="")),
                    "sources": self._sources(turn),
                    **evidence_trace_payload,
                    **self._mutual_phase_payload(debate, turn),
                    "playback_url": f"/api/v1/debates/{debate_id}/audio/{turn_id}",
                    "avatar_states": self._avatar_states(participants, turn),
                    "cursor_ms": 0,
                    "playback_rate": state.playback_rate,
                }
                event_type = "playback.started"
            started_event = self._stage_event(db, debate_id, event_type, payload)
            self._commit(db)
        if started_event is not None:
            await self._publish_event(started_event)
        if action in {"start", "next"}:
            turns = self._turns(db, debate)
            index = next((index for index, item in enumerate(turns) if str(item.id) == turn_id), 0)
            if index + 1 < len(turns):
                await self._enqueue(debate, turns[index + 1])
        return self._state_dto(state, db, debate)

    def _avatar_states(self, participants: list[Any], turn: Any) -> list[dict[str, Any]]:
        current_id = str(turn.participant_id)
        states: list[dict[str, Any]] = []
        for participant in participants:
            participant_id = str(participant.id)
            config = self._get(participant, "avatar_config", "avatar_config_json", default={}) or {}
            if isinstance(config, str):
                try:
                    import json

                    config = json.loads(config)
                except (TypeError, ValueError):
                    config = {}
            speaking = participant_id == current_id
            expression = (
                "neutral" if not speaking else str(config.get("default_expression", "neutral"))
            )
            if not speaking:
                expression = "attentive"
            states.append(
                {
                    "participant_id": participant_id,
                    "slot": self._slot(participant),
                    "motion_state": "speaking" if speaking else "listening",
                    "expression": expression,
                    "expression_strength": str(config.get("expression_strength", "medium")),
                }
            )
        return states

    async def ended_ack(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
        expected_control_version: int,
        epoch: str,
        session_hash: str,
        turn_id: str,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        completed_events: list[EventRecord] = []
        next_turn_to_enqueue: Any | None = None
        mode = "live"
        completed_epoch: str | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if state.status != "playing" or state.current_turn_id != turn_id:
                # Duplicate ended events are intentionally no-op/private at
                # the transport layer; callers can inspect the unchanged DTO.
                return self._state_dto(state, db, debate)
            turns = self._turns(db, debate)
            current = self._current_turn(db, debate, state)
            if state.mode == "live":
                if not self._turn_public(current) or not self._has_public_predecessor_prefix(
                    turns,
                    current,
                    rule_set_id=str(self._get(debate, "rule_set_id", default="")),
                ):
                    raise conflict(
                        "invalid_state",
                        "The live turn cannot advance before its public predecessor prefix.",
                    )
            elif not self._turn_public(current):
                raise conflict("invalid_state", "Replay requires a public playback item.")
            cursor = self._cursor(state)
            state.control_version += 1
            self.ticket_store.revoke_item(debate_id, turn_id)
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            if state.mode == "replay":
                replay_queue, queue_valid = self._replay_queue(db, debate, state)
                if not queue_valid:
                    raise conflict("invalid_state", "The replay queue is unavailable.")
                try:
                    replay_index = int(state.replay_index) if state.replay_index is not None else -1
                except (TypeError, ValueError):
                    replay_index = -1
                if (
                    replay_index < 0
                    or replay_index >= len(replay_queue)
                    or str(replay_queue[replay_index].id) != turn_id
                ):
                    raise conflict("invalid_state", "The replay cursor is unavailable.")
                mode = "replay"
                # The completed item remains current while waiting for the
                # teacher.  Only REST Next can increment this cursor and make
                # the adjacent public item ready.
                state.replay_index = replay_index
                successor = (
                    replay_queue[replay_index + 1] if replay_index + 1 < len(replay_queue) else None
                )
                if successor is not None:
                    adjacent, unique = self._adjacent_successor(turns, current)
                    if not unique or adjacent is None or str(adjacent.id) != str(successor.id):
                        raise conflict(
                            "invalid_state", "The replay turn plan has multiple successors."
                        )
                    self._set_nonplaying(state, "waiting_next", cursor)
                    state.current_turn_id = turn_id
                    next_ready = self._replay_next_turn_ready(db, debate, state)
                    self._save(db, debate, state)
                    payload = {
                        "mode": "replay",
                        "completed_turn_id": turn_id,
                        "control_version": state.control_version,
                        "next_turn_ready": next_ready,
                    }
                    completed_events.append(
                        self._stage_event(db, debate_id, "playback.waiting_next", payload)
                    )
                else:
                    # Final replay completion returns the ordinary historical
                    # view: no controller/ticket or replay cursor survives.
                    self._set_nonplaying(state, "completed", cursor)
                    state.mode = "live"
                    state.current_turn_id = None
                    state.cursor_ms = 0
                    state.replay_scope = None
                    state.replay_turn_ids = []
                    state.replay_index = None
                    state.pending_action = None
                    state.pending_ticket_hash = None
                    state.pending_media_command_id = None
                    state.audio_duration_ms = 0
                    self._clear_media_results(debate_id)
                    completed_epoch = state.controller_epoch
                    state.controller_epoch = None
                    state.controller_session_hash = None
                    state.controller_connection_id = None
                    self._controller_sessions.pop(debate_id, None)
                    self._save(db, debate, state)
                    payload = {
                        "scope": "all",
                        "turn_id": turn_id,
                        "control_version": state.control_version,
                    }
                    completed_events.append(
                        self._stage_event(db, debate_id, "replay.completed", payload)
                    )
            else:
                index = next(index for index, item in enumerate(turns) if str(item.id) == turn_id)
                if index + 1 < len(turns):
                    next_turn = turns[index + 1]
                    # Natural live completion parks on the completed public
                    # turn.  A separate teacher Next CAS is the only action
                    # allowed to make the successor current.
                    self._set_nonplaying(state, "waiting_next", cursor)
                    state.replay_scope = None
                    state.replay_index = None
                    next_ready = self._next_turn_ready(db, debate, state)
                    self._save(db, debate, state)
                    payload = {
                        "turn_id": turn_id,
                        "cursor_ms": cursor,
                        "control_version": state.control_version,
                        "playback_rate": state.playback_rate,
                    }
                else:
                    self._set_nonplaying(state, "completed", cursor)
                    debate.status = "debate_finished"
                    # Natural live completion is a terminal controller
                    # boundary, just like final replay completion and an
                    # explicit Finish.  Capture the old epoch before clearing
                    # every durable/process-local owner so the committed
                    # completion can notify and fence that tab afterwards.
                    completed_epoch = state.controller_epoch
                    state.controller_epoch = None
                    state.controller_session_hash = None
                    state.controller_connection_id = None
                    self._controller_sessions.pop(debate_id, None)
                    self.repository.save_debate(db, debate)
                    self._save(db, debate, state)
                    payload = {
                        "turn_id": turn_id,
                        "cursor_ms": cursor,
                        "control_version": state.control_version,
                        "playback_rate": state.playback_rate,
                    }
                    next_ready = False
            if mode != "replay":
                mode = state.mode
                completed_events.append(
                    self._stage_event(db, debate_id, "playback.completed", payload)
                )
            if mode == "live" and state.status == "waiting_next":
                # Keep the waiting event closed over the completed current
                # turn.  It intentionally contains no successor identity or
                # prepared content.  Slow preparation is scheduled only
                # after the false event is part of this transaction.
                completed_events.append(
                    self._stage_event(
                        db,
                        debate_id,
                        "playback.waiting_next",
                        {
                            "mode": "live",
                            "completed_turn_id": turn_id,
                            "control_version": state.control_version,
                            "next_turn_ready": next_ready,
                        },
                    )
                )
                if not next_ready:
                    next_turn = turns[index + 1]
                    ensure_job = getattr(self.repository, "ensure_turn_job", None)
                    if callable(ensure_job):
                        ensure_job(db, debate, next_turn)
                    next_turn_to_enqueue = next_turn
            self._commit(db)
        await self._publish_events(completed_events)
        if completed_epoch is not None:
            self._revoke_epoch(completed_epoch, debate_id, "debate_terminal")
            self.ticket_store.revoke_debate(debate_id)
        if next_turn_to_enqueue is not None:
            await self._enqueue(debate, next_turn_to_enqueue)
        return self._state_dto(state, db, debate)

    async def play_failed(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int,
        epoch: str,
        session_hash: str,
        turn_id: str,
        failure_phase: Literal["pre_ack", "post_ack"],
        cursor_ms: int,
        safe_client_code: str,
        context: AuthContext | None = None,
    ) -> PlaybackStateDTO:
        failed_playback_event: EventRecord | None = None
        async with self._lock:
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if state.current_turn_id != turn_id:
                raise not_found()
            self.ticket_store.revoke_item(debate_id, turn_id)
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            if failure_phase == "pre_ack":
                if state.status != "ready":
                    raise invalid_state("A pre-play failure requires ready playback.")
                self._save(db, debate, state)
                self._commit(db)
                return self._state_dto(state, db, debate)
            if state.status != "playing":
                raise invalid_state("A post-play failure requires playing playback.")
            self._set_nonplaying(state, "ready", cursor_ms)
            state.control_version += 1
            self._save(db, debate, state)
            payload = {
                "code": "playback_failed",
                "message": "Playback could not continue. Retry this turn.",
                "request_id": str(uuid4()),
                "recoverable": True,
            }
            failed_playback_event = self._stage_event(db, debate_id, "error", payload)
            self._commit(db)
        if failed_playback_event is not None:
            await self._publish_event(failed_playback_event)
        return self._state_dto(state, db, debate)

    async def snapshot(
        self, db: Any, debate_id: str, context: AuthContext | None = None
    ) -> tuple[dict[str, Any], int]:
        debate = self._get_debate(db, debate_id)
        self._assert_teacher(db, debate, context)
        state = self._state(db, debate)
        turns = self._turns(db, debate)
        public_turns = []
        for turn in sorted(
            turns, key=lambda item: int(self._get(item, "turn_index", default=0) or 0)
        ):
            if not self._turn_public(turn):
                continue
            speech = self._get(turn, "speech", "original_text", default="")
            if not isinstance(speech, str) or not speech:
                continue
            public_turns.append(
                {
                    "id": str(turn.id),
                    "participant_id": str(turn.participant_id),
                    "round_no": self._round(turn),
                    **self._mutual_phase_payload(debate, turn),
                    "turn_index": int(self._get(turn, "turn_index", default=0) or 0),
                    "speech": speech,
                    "retrieval_status": str(
                        self._get(turn, "retrieval_status", default="no_match")
                    ),
                    "grounding_mode": str(
                        self._get(turn, "grounding_mode", default="general_reasoning")
                    ),
                    "sources": self._sources(turn),
                    **self._evidence_trace_payload(turn),
                }
            )
        # Read the watermark from the same transaction/session as the
        # authoritative Debate/Playback/Turn snapshot.  A separate event-store
        # connection can otherwise observe a later sequence and create a
        # snapshot/event duplicate or gap during reconnect.
        last_sequence_reader = getattr(self.repository, "last_sequence_in_session", None)
        if callable(last_sequence_reader) and db is not None:
            last_sequence = int(last_sequence_reader(db, debate_id))
        else:
            last_sequence = self.event_hub.store.last_sequence(debate_id)
        wave3 = (
            self.snapshot_projector(db, debate_id)
            if self.snapshot_projector is not None
            else {
                "interaction_status": "closed",
                "insight_status": "not_started",
                "report_status": "not_started",
                "interaction": {
                    "status": "closed",
                    "votes": [],
                    "barrage_count": 0,
                    "total_votes": 0,
                },
                "report": {
                    "generation_status": "not_started",
                    "latest_attempt_status": "not_started",
                    "insight": {
                        "status": "not_started",
                        "included_count": 0,
                        "filtered_count": 0,
                        "snapshot_id": None,
                        "revision": None,
                    },
                    "active_revision_id": None,
                    "current_success_revision_id": None,
                    "current_success_word_count": None,
                },
            }
        )
        payload = {
            "debate_status": str(getattr(debate, "status", "draft")),
            "playback_status": state.status,
            "interaction_status": wave3["interaction_status"],
            "insight_status": wave3["insight_status"],
            "report_status": wave3["report_status"],
            "public_turns": public_turns,
            "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
            "interaction": wave3["interaction"],
            "report": wave3["report"],
            "latest_sequence": last_sequence,
        }
        return payload, last_sequence

    async def authorize_audio(
        self,
        db: Any,
        debate_id: str,
        turn_id: str,
        *,
        session_hash: str,
        media_ticket: str | None,
        context: AuthContext | None = None,
    ) -> AudioAuthorization:
        debate = self._get_debate(db, debate_id)
        self._assert_teacher(db, debate, context)
        if self.audio_store is None:
            raise not_found()
        current_pointer = self.repository.current_audio_debate_id(db, self._course_id(debate))
        if current_pointer != debate_id:
            raise PlatformError("audio_not_retained", "This audio is no longer retained.", 410)
        turn = next((item for item in self._turns(db, debate) if str(item.id) == turn_id), None)
        # Initial live media is fetched immediately after the browser's
        # play() promise but before started_ack publishes the turn.  It still
        # must be a final-ready, durably validated audio row; publication is
        # required for replay eligibility, not for this current-only ticket.
        if turn is None or str(self._get(turn, "generation_status", default="")) != "final_ready":
            raise PlatformError("audio_not_retained", "This audio is no longer retained.", 410)
        metadata = self._validated_turn_audio(db, debate, turn)
        if metadata is None:  # pragma: no cover - guarded by _replay_audio_ready
            raise PlatformError("audio_not_retained", "This audio is no longer retained.", 410)
        if media_ticket is None:
            # Public DTOs deliberately expose only a stable queryless platform
            # path.  Bytes remain private to the active controller's ticket;
            # an observation-only tab that receives the public event cannot
            # turn that path into an audio stream.
            raise forbidden()
        ticket_binding = self.ticket_store.get(media_ticket)
        if ticket_binding is None or (
            ticket_binding.session_hash != session_hash
            or ticket_binding.debate_id != debate_id
            or ticket_binding.turn_id != turn_id
        ):
            raise forbidden()
        state = self._state(db, debate)
        if (
            state.controller_epoch != ticket_binding.controller_epoch
            or state.current_turn_id != turn_id
            or state.pending_action != ticket_binding.action
            or state.pending_ticket_hash != ticket_binding.token_hash
            or state.pending_media_command_id is None
            or ticket_binding.control_version != state.control_version
        ):
            raise forbidden()
        return AudioAuthorization(metadata, ticket_binding)

    async def command_duplicate_or_rejected(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
        code: str,
        recoverable: bool,
    ) -> CommandRejectedResult:
        state = self._state(db, self._get_debate(db, debate_id))
        return CommandRejectedResult(
            message_id=uuid4(),
            debate_id=UUID(debate_id),
            occurred_at=datetime.now(UTC),
            command_id=UUID(command_id),
            code=code,
            current_control_version=state.control_version,
            recoverable=recoverable,
        )

    async def command_duplicate(
        self,
        db: Any,
        debate_id: str,
        *,
        command_id: str,
    ) -> CommandDuplicateResult:
        state = self._state(db, self._get_debate(db, debate_id))
        return CommandDuplicateResult(
            message_id=uuid4(),
            debate_id=UUID(debate_id),
            occurred_at=datetime.now(UTC),
            command_id=UUID(command_id),
            current_control_version=state.control_version,
        )
