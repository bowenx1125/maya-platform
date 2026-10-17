"""Playback state, persistence, queries and event staging.

Authoritative classroom playback state machine.


The service owns controller epochs, media bootstrap acknowledgements, playback
CAS and event ordering.  Debate setup and generation remain outside this
package and are provided via :mod:`protocols`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from app.core.errors import PlatformError, conflict, forbidden, invalid_state, not_found
from app.modules.auth.service import AuthContext
from app.modules.debates.generation.evidence_trace import public_evidence_trace
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.round_phase import phase_for_round
from app.modules.debates.round_count import debate_teaching_protocol, uses_segment_protocol
from app.providers.tts import TTS_UNAVAILABLE_CODES, MockTTSProvider, TTSProvider

from .audio import AudioMetadata, AudioStore, MediaTicketBinding, MediaTicketStore
from .events import DebateEventHub, EventRecord, validate_event_payload
from .protocols import (
    MemoryPlaybackRepository,
    PlaybackRepository,
    TurnPreparer,
)
from .schemas import (
    ControllerRevokedResult,
    MediaPreparedResult,
    PlaybackStateDTO,
)

LOGGER = logging.getLogger(__name__)
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_SAFE_GENERATION_CODES = {
    "turn_generation_failed",
    "provider_unavailable",
    # The same code the HTTP path already returns to a browser. Without it a
    # missing provider policy collapsed into the generic failure, so a teacher
    # was told a turn failed with no way to learn that a real selector was on
    # and its reviewed policy was never imported.
    "provider_preflight_blocked",
    "persona_confirmation_required",
    "provider_confirmation_required",
    "provider_not_sent",
    "acceptance_unknown",
    "debate_stopped",
    "audio_invalid",
    "tts_timeout",
    "tts_http_rejected",
    "tts_response_invalid",
    "tts_result_url_rejected",
    "tts_result_dns_failed",
    "tts_result_download_failed",
    "tts_audio_invalid",
    # Fail-path mirrors for codes that usually go through mark_turn_ready.
    "tts_provider_unavailable",
    "tts_voice_unavailable",
    # Adapter / validation codes that must not collapse to a generic failure.
    "turn_length_invalid",
    "schema_invalid",
    "llm_recovery_failed",
    "llm_recovery_fence_stale",
    "llm_recovery_input_unavailable",
    # Stuck pending/running prepare work past the agreed watchdog.
    "preparation_timeout",
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
    "preparation_timeout",
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
    replay_index: int | None = None


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


class PlaybackCore:
    """Shared state, persistence and query surface for playback.

    Every playback mixin inherits this rather than ``object`` so the
    attributes set in ``__init__`` are visible to the type checker and the
    method resolution order stays a single line.
    """

    """A provider-neutral, single-controller classroom playback service."""

    # The scheduling half of turn preparation lives here because more than one
    # mixin enqueues work; the generation itself is PlaybackPreparationMixin's.
    # Declaring the contract keeps the core -> mixin call explicit and typed.
    async def prepare_turn(self, db: Any, debate_id: str, turn_id: str) -> None:
        raise NotImplementedError

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
            tuple[str, str], tuple[PreparedMedia | None, MediaPreparedResult]
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
        # Fencing an interrupted turn returns it to pending, which is only half
        # a recovery: a lesson still marked running then had a current turn
        # nobody was preparing, so it showed no speech, offered no Next and
        # raised no failure to retry. Drive that turn again.
        await self._resume_running_debates(db)
        return affected

    async def _resume_running_debates(self, db: Any) -> None:
        """Re-enqueue the current turn of every lesson still marked running."""

        listing = getattr(self.repository, "running_debate_ids", None)
        if not callable(listing):
            return
        for debate_id in listing(db):
            debate = self.repository.get_debate(db, debate_id)
            if debate is None:
                continue
            state = self._state(db, debate)
            if state.current_turn_id is None:
                continue
            turn = next(
                (
                    item
                    for item in self._turns(db, debate)
                    if str(getattr(item, "id", "")) == state.current_turn_id
                ),
                None,
            )
            await self.enqueue_frozen_final(db, debate_id)
            if turn is not None and self._turn_text_fallback_ready(turn):
                await self._publish_text_current(db, debate, turn)
                continue
            if turn is None or self._turn_ready(turn):
                # A ready turn needs no work; prepare_turn announces it when
                # the classroom reconnects.
                continue
            # Only a turn the fence returned to a clean pending state. Recovery
            # deliberately parks some turns -- a missing LLM recovery input
            # leaves one running with its own code, waiting for an operator --
            # and re-driving those would turn a decision into a failure.
            if str(self._get(turn, "generation_status", default="")) != "pending":
                continue
            if str(self._get(turn, "safe_error_code", default="") or ""):
                continue
            await self._enqueue(debate, turn)

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
            PlaybackCore._get(turn, "publication_status", "public_status", default="private")
        )
        return status in {"public", "published"}

    @staticmethod
    def _turn_text_only(turn: Any) -> bool:
        return (
            PlaybackCore._get(turn, "generation_status") == "final_ready"
            and PlaybackCore._get(turn, "safe_error_code", "failed_code") == "tts_voice_unavailable"
            and bool(str(PlaybackCore._get(turn, "speech", default="")).strip())
            and PlaybackCore._get(turn, "audio_file_id", "audio_relative_path") is None
            and PlaybackCore._get(turn, "audio_duration_ms") == 0
        )

    @staticmethod
    def _turn_ready(turn: Any) -> bool:
        generation = str(PlaybackCore._get(turn, "generation_status", "status", default="pending"))
        audio = PlaybackCore._get(turn, "audio_relative_path", "audio_file_id", default=None)
        return generation in {"ready", "final_ready", "completed"} and (
            audio is not None or PlaybackCore._turn_text_only(turn)
        )

    @staticmethod
    def _turn_text_fallback_ready(turn: Any) -> bool:
        get = PlaybackCore._get
        return (
            get(turn, "generation_status", default="") == "final_ready"
            and get(turn, "safe_error_code", "failed_code") in TTS_UNAVAILABLE_CODES
            and isinstance(get(turn, "speech"), str)
            and bool(get(turn, "speech").strip())
            and get(turn, "audio_file_id") is None
            and get(turn, "audio_relative_path") is None
            and get(turn, "audio_duration_ms") is None
        )

    async def _publish_text_current(self, db: Any, debate: Any, turn: Any) -> bool:
        """Complete an authorized current item without impersonating audio playback."""

        debate_id, turn_id = str(debate.id), str(turn.id)
        state = self._state(db, debate)
        if (
            self._get(debate, "status") != "running"
            or state.mode != "live"
            or state.status not in {"preparing", "ready"}
            or state.current_turn_id != turn_id
            or self._turn_public(turn)
            or not self._turn_text_fallback_ready(turn)
        ):
            return False
        claim = getattr(self.repository, "claim_text_playback", None)
        if callable(claim):
            version = state.control_version
            generation = int(self._get(debate, "cancellation_generation", default=0) or 0)
            self._rollback(db)
            event = claim(
                debate_id=debate_id,
                expected_control_version=version,
                turn_id=turn_id,
                expected_generation=generation,
            )
            self._rollback(db)
            if event is None:
                return False
            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
        else:
            turns = self._turns(db, debate)
            arguments = {
                "rule_set_id": str(self._get(debate, "rule_set_id", default="")),
                "teaching_protocol": debate_teaching_protocol(debate),
            }
            if not self._turn_fence_ready(turns, turn, **arguments) or (
                not self._has_public_predecessor_prefix(turns, turn, **arguments)
            ):
                return False
            if not self.repository.publish_turn(db, turn):
                return False
            self._set_nonplaying(state, "waiting_next", 0)
            state.control_version += 1
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._save(db, debate, state)
            event = self._stage_event(
                db,
                debate_id,
                "playback.waiting_next",
                {
                    "mode": "live",
                    "completed_turn_id": turn_id,
                    "control_version": state.control_version,
                    "next_turn_ready": self._next_turn_ready(db, debate, state),
                },
            )
            self._commit(db)
        self.ticket_store.revoke_item(debate_id, turn_id)
        self._clear_media_results(debate_id)
        await self._publish_event(event)
        turns = self._turns(db, debate)
        current = next((item for item in turns if str(item.id) == turn_id), None)
        if current is not None:
            successor, unique = self._adjacent_successor(turns, current)
            if unique and successor is not None and not self._next_turn_ready(db, debate, state):
                await self._enqueue(debate, successor)
        return True

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
        trace = PlaybackCore._evidence_trace(turn)
        return {"evidence_trace": trace} if trace else {}

    def _segment_payload(self, db: Any, turn: Any) -> dict[str, Any]:
        raw = self._get(turn, "structured_json")
        if not raw or '"segment_turn_v2"' not in raw:
            return {}
        from app.modules.debates.models import DebateParticipant, DebateTurn
        from app.modules.debates.setup.segment_projection import segment_projection

        saved = db.get(DebateTurn, str(turn.id))
        participant = db.get(DebateParticipant, str(turn.participant_id))
        if saved is None or participant is None:
            raise invalid_state("The saved paragraph owner is unavailable.")
        from app.core.models import StoredFile

        audio = db.get(StoredFile, saved.audio_file_id) if saved.audio_file_id else None
        result, sources = segment_projection(db, saved, participant)
        if result is None:
            raise invalid_state("The saved paragraph is unavailable.")
        return {
            "segment_turn": result.model_dump(mode="json"),
            "source_details": [item.model_dump(mode="json") for item in sources],
            "audio_ready": audio is not None and audio.state == "active",
        }

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

    @staticmethod
    def _validate_retained_audio_facts(
        audio_store: AudioStore,
        *,
        course_id: str,
        debate_id: str,
        turn_id: str,
        record_kind: Any,
        record_state: Any,
        relative_path: Any,
        expected_sha256: Any,
        expected_size: Any,
        expected_duration_ms: Any,
    ) -> AudioMetadata | None:
        """Validate one retained audio row and the bytes it names.

        Setup detail and playback controls must make the same decision. Keep
        the canonical-path, digest, size and WAV validation in this shared
        seam; callers only resolve the durable row shape for their adapter.
        """

        if record_kind != "debate_audio" or record_state != "active":
            return None
        try:
            canonical = audio_store.relative_path(course_id, debate_id, turn_id)
        except (TypeError, ValueError):
            return None
        if not isinstance(relative_path, str) or relative_path != canonical:
            return None
        try:
            size_value = int(expected_size) if expected_size is not None else None
            duration_value = int(expected_duration_ms) if expected_duration_ms is not None else None
        except (TypeError, ValueError):
            return None
        if duration_value is None or duration_value <= 0:
            return None
        metadata = audio_store.validate_file(
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            relative_path=relative_path,
            expected_sha256=(str(expected_sha256) if expected_sha256 is not None else None),
            expected_size_bytes=size_value,
            expected_duration_ms=duration_value,
        )
        if metadata is not None:
            audio_store.rehydrate(metadata)
        return metadata

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
        course_id = self._course_id(debate)

        record = self._retained_audio_record(db, debate, turn)
        if record is not None:
            file_id = self._get(turn, "audio_file_id", default=None)
            if (file_id is None and not isinstance(self.repository, MemoryPlaybackRepository)) or (
                file_id is not None and str(self._get(record, "id", default="")) != str(file_id)
            ):
                return None
            record_kind = self._get(record, "kind", default=None)
            record_state = self._get(record, "state", default=None)
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
            record_kind = "debate_audio"
            record_state = "active"
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

        return self._validate_retained_audio_facts(
            self.audio_store,
            course_id=course_id,
            debate_id=debate_id,
            turn_id=turn_id,
            record_kind=record_kind,
            record_state=record_state,
            relative_path=relative_path,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
            expected_duration_ms=self._get(turn, "audio_duration_ms", default=None),
        )

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
        if not uses_segment_protocol(debate) and self.repository.current_audio_debate_id(
            db, self._course_id(debate)
        ) != self._debate_id(debate):
            return False
        return self._validated_turn_audio(db, debate, turn) is not None

    def audio_retained(self, db: Any, debate_id: str) -> bool:
        """Return whether the course currently retains every public turn's bytes."""

        debate = self._get_debate(db, debate_id)
        if (
            not uses_segment_protocol(debate)
            and self.repository.current_audio_debate_id(db, self._course_id(debate)) != debate_id
        ):
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
        teaching_protocol: str | None = None,
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
        try:
            current_round = int(cls._get(turn, "round_no", default=1) or 1)
        except (TypeError, ValueError):
            return False
        is_mutual = rule_set_id == MUTUAL_LEARNING_RULE_SET_ID and not (
            teaching_protocol == "four_round_v1" and current_round > 1
        )
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
        """Derive a ready successor for a published live item; never persist it."""

        if (
            self._get(debate, "status", default="running") != "running"
            or state.mode != "live"
            or state.status not in {"playing", "paused", "waiting_next"}
            or not state.current_turn_id
        ):
            return False
        turns = self._turns(db, debate)
        current = next(
            (item for item in turns if str(getattr(item, "id", "")) == state.current_turn_id),
            None,
        )
        if current is None or not self._turn_public(current):
            return False
        successor, unique = self._adjacent_successor(turns, current)
        if successor is None or not unique:
            return False
        if self._turn_public(successor):
            return False
        # Align with claim_next_playback when SQL columns are populated: stage
        # must be ready and generation must be final_ready.  Memory doubles that
        # leave preparation_stage=None keep the looser playback boundary.
        stage = self._get(successor, "preparation_stage", default=None)
        if stage is not None and str(stage) != "ready":
            return False
        if stage is not None and str(
            self._get(successor, "generation_status", "status", default="")
        ) != "final_ready":
            return False
        rule_set_id = str(self._get(debate, "rule_set_id", default=""))
        teaching_protocol = debate_teaching_protocol(debate)
        if not (
            self._turn_ready(successor) or self._turn_text_fallback_ready(successor)
        ) or not self._turn_fence_ready(
            turns, successor, rule_set_id=rule_set_id, teaching_protocol=teaching_protocol
        ):
            return False
        if not self._has_public_predecessor_prefix(
            turns, successor, rule_set_id=rule_set_id, teaching_protocol=teaching_protocol
        ):
            return False
        if (
            not self._turn_text_fallback_ready(successor)
            and not self._turn_text_only(successor)
            and self._validated_turn_audio(db, debate, successor) is None
        ):
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
            self._get(debate, "status", default="") not in {"debate_finished", "completed"}
            or state.mode != "replay"
            or state.status not in {"playing", "paused", "waiting_next"}
            or state.current_turn_id is None
            or state.replay_index is None
        ):
            return False
        queue, valid = self._replay_queue(db, debate, state)
        if not valid:
            return False
        try:
            index = int(state.replay_index)
        except (TypeError, ValueError):
            return False
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
        teaching_protocol: str | None = None,
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
        try:
            current_round = int(cls._get(turn, "round_no", default=1) or 1)
        except (TypeError, ValueError):
            return False
        is_mutual = rule_set_id == MUTUAL_LEARNING_RULE_SET_ID and not (
            teaching_protocol == "four_round_v1" and current_round > 1
        )
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
        teaching_protocol: str | None = None,
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
            if not cls._has_public_predecessor_prefix(
                turns, turn, rule_set_id=rule_set_id, teaching_protocol=teaching_protocol
            ):
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
        if not cls._has_public_predecessor_prefix(
            turns, turn, rule_set_id=rule_set_id, teaching_protocol=teaching_protocol
        ):
            raise conflict(
                "invalid_state",
                "The live turn cannot be published before its public predecessor prefix.",
            )

    @staticmethod
    def _word_count(text: str) -> int:
        return len(_WORD_RE.findall(text))

    @staticmethod
    def _sources(turn: Any) -> list[dict[str, Any]]:
        raw = PlaybackCore._get(turn, "sources", "turn_sources", default=()) or ()
        output: list[dict[str, Any]] = []
        for source in raw:
            filename = PlaybackCore._get(source, "source_filename", "filename", default=None)
            if not isinstance(filename, str) or not filename.strip():
                continue
            chunk = PlaybackCore._get(source, "chunk_id", "evidence_id", default=None)
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
        participant_id = str(PlaybackCore._get(turn, "participant_id", default=""))
        return next(
            (item for item in participants if str(getattr(item, "id", "")) == participant_id), None
        )

    @staticmethod
    def _slot(participant: Any | None) -> str:
        slot = str(PlaybackCore._get(participant, "slot", default="A")) if participant else "A"
        return slot if slot in {"A", "B", "C", "D", "E"} else "A"

    @staticmethod
    def _round(turn: Any) -> int:
        return int(PlaybackCore._get(turn, "round_no", "round", default=1) or 1)

    @staticmethod
    def _mutual_phase_payload(debate: Any, turn: Any) -> dict[str, Any]:
        """Return versioned phase metadata without changing legacy events."""

        if str(PlaybackCore._get(debate, "rule_set_id", default="")) != MUTUAL_LEARNING_RULE_SET_ID:
            return {}
        round_count = PlaybackCore._get(debate, "round_count", default=None)
        if round_count is None:
            try:
                snapshot = json.loads(
                    str(PlaybackCore._get(debate, "rule_snapshot_json", default="{}"))
                )
                round_count = snapshot.get("round_count") if isinstance(snapshot, dict) else None
            except (TypeError, ValueError):
                round_count = None
        if not isinstance(round_count, int) or not 2 <= round_count <= 5:
            return {}
        try:
            phase = phase_for_round(PlaybackCore._round(turn), round_count).value
        except ValueError:
            return {}
        return {"phase": phase, "round_count": round_count}

    @staticmethod
    def _mutual_phase_only(debate: Any, turn: Any) -> dict[str, Any]:
        """Return just the phase for closed REST read models.

        The WebSocket event schema carries ``round_count`` beside ``phase``,
        but ``DebateTurn`` is a closed model that permits only ``phase``.
        Splatting the full WS payload into a transcript turn therefore makes
        every mutual-learning transcript fail response validation.
        """

        payload = PlaybackCore._mutual_phase_payload(debate, turn)
        phase = payload.get("phase")
        return {"phase": phase} if phase is not None else {}

    @staticmethod
    def _mutual_round_count(debate: Any) -> int | None:
        if str(PlaybackCore._get(debate, "rule_set_id", default="")) != MUTUAL_LEARNING_RULE_SET_ID:
            return None
        value = PlaybackCore._get(debate, "round_count", default=None)
        if value is None:
            try:
                snapshot = json.loads(
                    str(PlaybackCore._get(debate, "rule_snapshot_json", default="{}"))
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

    # These are called from more than one mixin, so they live here: the
    # dependency between playback modules stays one-directional.

    # Called from more than one mixin, so they live here and the
    # dependency between playback modules stays one-directional.
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

    async def enqueue_frozen_final(self, db: Any, debate_id: str) -> None:
        """Resume the adjacent final speaker from the committed classroom cutoff."""
        debate = self._get_debate(db, debate_id)
        if not uses_segment_protocol(debate) or not self._get(debate, "final_input_json"):
            return
        if self._get(debate, "status") != "running":
            return
        state = self._state(db, debate)
        if state.mode != "live" or state.status != "waiting_next":
            return
        turns = self._turns(db, debate)
        current = next((item for item in turns if str(item.id) == state.current_turn_id), None)
        if current is None:
            return
        successor, unique = self._adjacent_successor(turns, current)
        if (
            successor is None
            or not unique
            or self._turn_ready(successor)
            or self._turn_text_fallback_ready(successor)
        ):
            return
        if self._get(successor, "generation_status") != "pending" or self._get(
            successor, "safe_error_code"
        ):
            return
        await self._enqueue(debate, successor)

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
