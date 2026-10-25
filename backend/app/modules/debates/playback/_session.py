"""Controller ownership, media commands and the public snapshot."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from app.core.errors import PlatformError, conflict, forbidden, invalid_state, not_found
from app.modules.auth.service import AuthContext
from app.modules.debates.round_count import debate_teaching_protocol, uses_segment_protocol

from ._core import (
    AudioAuthorization,
    EvidenceTraceCorruptError,
    PlaybackCore,
    PreparedMedia,
)
from .audio import MediaTicketBinding
from .events import EventRecord
from .schemas import (
    CommandDuplicateResult,
    CommandRejectedResult,
    ControllerAcquiredResult,
    MediaPreparedResult,
    PlaybackStateDTO,
)

LOGGER = logging.getLogger(__name__)


class PlaybackSessionMixin(PlaybackCore):
    """Controller ownership, media commands and the public snapshot."""

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
        async with self._debate_lock(debate_id, "controller_acquire"):
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
            # Older live starts persisted a replay cursor, which makes the SQL
            # Next claim fail. Repair it within the fenced controller handoff.
            if state.mode == "live":
                state.replay_scope = None
                state.replay_index = None
                state.replay_turn_ids = []
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
            current = next(
                (turn for turn in self._turns(db, debate) if str(turn.id) == state.current_turn_id),
                None,
            )
            if current is not None and self._turn_text_fallback_ready(current):
                await self._publish_text_current(db, debate, current)
                debate = self._get_debate(db, debate_id)
                state = self._state(db, debate)
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
        async with self._debate_lock(debate_id, "controller_disconnect"):
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
    ) -> tuple[PreparedMedia | None, MediaPreparedResult]:
        prepared, result = await self._media_prepare_locked(
            db,
            debate_id,
            command_id=command_id,
            expected_control_version=expected_control_version,
            epoch=epoch,
            session_hash=session_hash,
            turn_id=turn_id,
            action=action,
            context=context,
        )
        if result.text_only:
            debate = self._get_debate(db, debate_id)
            state = self._state(db, debate)
            if state.status == "waiting_next" and state.current_turn_id == turn_id:
                current = self._current_turn(db, debate, state)
                successor, unique = self._adjacent_successor(self._turns(db, debate), current)
                if unique and successor is not None and not self._turn_ready(successor):
                    await self._enqueue(debate, successor)
        return prepared, result

    async def _media_prepare_locked(
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
    ) -> tuple[PreparedMedia | None, MediaPreparedResult]:
        async with self._debate_lock(debate_id, "media_prepare_locked"):
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)

            command_key = (debate_id, command_id)
            previous = self._media_command_results.get(command_key)
            if previous is not None:
                prepared, result = previous
                if prepared is None:
                    if state.current_turn_id == turn_id and state.status == "waiting_next":
                        return prepared, result
                    self._media_command_results.pop(command_key, None)
                    raise conflict("invalid_state", "The text item is no longer current.")
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
                teaching_protocol=debate_teaching_protocol(debate),
            )
            if not self._turn_ready(turn):
                raise not_found()
            if action == "replay":
                try:
                    self._evidence_trace(turn)
                except EvidenceTraceCorruptError as exc:
                    raise invalid_state("Replay evidence trace is unavailable.") from exc
            if self._turn_text_only(turn) and action in {"start", "next"}:
                result = await self._prepare_text_turn(
                    db,
                    debate,
                    turn,
                    state,
                    command_id=command_id,
                    epoch=epoch,
                )
                self._media_command_results[command_key] = (None, result)
                return None, result
            metadata = self._validated_turn_audio(db, debate, turn)
            if (
                action == "replay"
                and not uses_segment_protocol(debate)
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
                        or uses_segment_protocol(debate)
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
            media_url = self._media_url(debate_id, turn_id, token)
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

    async def _prepare_text_turn(
        self,
        db: Any,
        debate: Any,
        turn: Any,
        state: Any,
        *,
        command_id: str,
        epoch: str,
    ) -> MediaPreparedResult:
        debate_id, turn_id = self._debate_id(debate), str(turn.id)
        turns = self._turns(db, debate)
        successor, unique = self._adjacent_successor(turns, turn)
        if not unique or (
            successor is None and any(int(item.turn_index) > int(turn.turn_index) for item in turns)
        ):
            raise conflict("invalid_state", "The turn plan has a missing or ambiguous successor.")
        try:
            evidence = self._evidence_trace_payload(turn)
        except EvidenceTraceCorruptError as exc:
            raise invalid_state("Evidence trace is unavailable.") from exc
        claim = getattr(self.repository, "claim_text_media_playback", None)
        if callable(claim) and not claim(
            db,
            debate_id=debate_id,
            turn_id=turn_id,
            expected_control_version=state.control_version,
            controller_epoch=epoch,
        ):
            raise conflict("stale_control_version", "The text playback claim is stale.")
        if not self.repository.publish_turn(db, turn):
            raise conflict("invalid_state", "The text turn is not ready to publish.")
        participants = self._participants(db, debate)
        events = [
            self._stage_event(
                db,
                debate_id,
                "playback.started",
                {
                    "turn_id": turn_id,
                    "slot": self._slot(self._participant_for_turn(participants, turn)),
                    "round_no": self._round(turn),
                    "speech": str(self._get(turn, "speech", default="")),
                    "sources": self._sources(turn),
                    **evidence,
                    **self._segment_payload(db, turn),
                    **self._mutual_phase_payload(debate, turn),
                    "audio_ready": False,
                    "playback_url": None,
                    "avatar_states": self._avatar_states(participants, turn),
                    "cursor_ms": 0,
                },
            )
        ]
        self._set_nonplaying(state, "waiting_next" if successor is not None else "completed", 0)
        state.audio_duration_ms = 0
        state.pending_action = None
        state.pending_ticket_hash = None
        state.pending_media_command_id = None
        if successor is None:
            debate.status = "debate_finished"
            state.controller_epoch = None
            state.controller_session_hash = None
            state.controller_connection_id = None
            self._controller_sessions.pop(debate_id, None)
            self.repository.save_debate(db, debate)
        self._save(db, debate, state)
        events.append(
            self._stage_event(
                db,
                debate_id,
                "playback.completed",
                {
                    "turn_id": turn_id,
                    "cursor_ms": 0,
                    "control_version": state.control_version,
                },
            )
        )
        next_ready = self._next_turn_ready(db, debate, state) if successor is not None else False
        if successor is not None:
            events.append(
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
                ensure_job = getattr(self.repository, "ensure_turn_job", None)
                if callable(ensure_job):
                    ensure_job(db, debate, successor)
        self._commit(db)
        await self._publish_events(events)
        if successor is None:
            self._revoke_epoch(epoch, debate_id, "debate_terminal")
            self.ticket_store.revoke_debate(debate_id)
        return MediaPreparedResult(
            message_id=uuid4(),
            debate_id=UUID(debate_id),
            occurred_at=datetime.now(UTC),
            command_id=UUID(command_id),
            controller_epoch=UUID(epoch),
            turn_id=UUID(turn_id),
            text_only=True,
            media_url=None,
            expires_at=datetime.now(UTC),
        )

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
        async with self._debate_lock(debate_id, "started_ack"):
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
                teaching_protocol=debate_teaching_protocol(debate),
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
                    **self._segment_payload(db, turn),
                    **self._mutual_phase_payload(debate, turn),
                    "playback_url": f"/api/v1/debates/{debate_id}/audio/{turn_id}",
                    "avatar_states": self._avatar_states(participants, turn),
                    "cursor_ms": 0,
                }
                event_type = "playback.started"
            started_event = self._stage_event(db, debate_id, event_type, payload)
            self._commit(db)
        if started_event is not None:
            await self._publish_event(started_event)
        if action in {"start", "next"}:
            await self._enqueue_lookahead(db, debate)
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
        async with self._debate_lock(debate_id, "ended_ack"):
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if state.status not in {"playing", "paused"} or state.current_turn_id != turn_id:
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
                    teaching_protocol=debate_teaching_protocol(debate),
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
        async with self._debate_lock(debate_id, "play_failed"):
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if state.current_turn_id != turn_id:
                raise not_found()
            if failure_phase == "pre_ack" and state.status != "ready":
                raise invalid_state("A pre-play failure requires ready playback.")
            if failure_phase == "post_ack" and state.status != "playing":
                raise invalid_state("A post-play failure requires playing playback.")
            self.ticket_store.revoke_item(debate_id, turn_id)
            state.pending_action = None
            state.pending_ticket_hash = None
            state.pending_media_command_id = None
            state.audio_duration_ms = 0
            self._clear_media_results(debate_id)
            if failure_phase == "post_ack":
                self._set_nonplaying(state, "ready", cursor_ms)
                state.control_version += 1
            # Pre-ack failures also need a committed event so the browser can
            # recover after its failed media ticket has been cleared.
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
                    **self._mutual_phase_only(debate, turn),
                    "turn_index": int(self._get(turn, "turn_index", default=0) or 0),
                    "speech": speech,
                    "audio_ready": self._validated_turn_audio(db, debate, turn) is not None,
                    "retrieval_status": str(
                        self._get(turn, "retrieval_status", default="no_match")
                    ),
                    "grounding_mode": str(
                        self._get(turn, "grounding_mode", default="general_reasoning")
                    ),
                    "sources": self._sources(turn),
                    **self._evidence_trace_payload(turn),
                    **self._segment_payload(db, turn),
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
            "final_input_frozen": bool(self._get(debate, "final_input_json")),
            "playback_status": state.status,
            "interaction_status": wave3["interaction_status"],
            "insight_status": wave3["insight_status"],
            "report_status": wave3["report_status"],
            "public_turns": public_turns,
            # PR A2: the Immerse stage starts downloading these at once.
            "audio_ready_turn_ids": self.audio_ready_turn_ids(db, debate),
            "playback": self._state_dto(state, db, debate).model_dump(mode="json"),
            "interaction": wave3["interaction"],
            "report": wave3["report"],
            "latest_sequence": last_sequence,
        }
        return payload, last_sequence

    async def prefetch_next_audio(
        self,
        db: Any,
        debate_id: str,
        *,
        expected_control_version: int | None,
        expected_current_turn_id: str | None,
        epoch: str,
        session_hash: str,
        turn_id: str | None = None,
        context: AuthContext | None = None,
    ) -> tuple[str, str]:
        """Let the active controller download a ready speech before it plays.

        PR A2 (2026-10-24): the Immerse stage downloads every speech whose
        audio is ready, one after another, independent of Next and of the
        playback state; ``turn_id`` names it. The ticket is the controller's
        own and never makes the turn public or current. Without ``turn_id``
        the older form names the adjacent successor of the playing turn.
        """

        if turn_id is not None:
            return await self._prefetch_turn(
                db, debate_id, turn_id, epoch=epoch, session_hash=session_hash, context=context
            )
        assert expected_control_version is not None and expected_current_turn_id is not None
        async with self._debate_lock(debate_id, "prefetch_next_audio"):
            debate = self._get_debate(db, debate_id)
            self._assert_teacher(db, debate, context)
            state = self._state(db, debate)
            self._check_control(state, expected_control_version)
            self._check_epoch(state, epoch=epoch, session_hash=session_hash)
            if state.current_turn_id != expected_current_turn_id:
                raise conflict(
                    "stale_control_version",
                    "The playback current turn is stale.",
                    {"current_current_turn_id": state.current_turn_id},
                )
            successor = self._prefetchable_successor(db, debate, state)
            if successor is None:
                raise conflict(
                    "next_not_ready", "The adjacent next turn is not ready for playback."
                )
            successor_id = str(successor.id)
            # One outstanding prefetch per item; a repeat replaces it.
            self.ticket_store.revoke_item(debate_id, successor_id)
            token, _binding = self.ticket_store.issue(
                session_hash=session_hash,
                controller_epoch=epoch,
                debate_id=debate_id,
                turn_id=successor_id,
                action="prefetch",
                control_version=state.control_version,
            )
            return (
                successor_id,
                self._media_url(debate_id, successor_id, token),
            )

    async def _prefetch_turn(
        self,
        db: Any,
        debate_id: str,
        turn_id: str,
        *,
        epoch: str,
        session_hash: str,
        context: AuthContext | None,
    ) -> tuple[str, str]:
        debate = self._get_debate(db, debate_id)
        self._assert_teacher(db, debate, context)
        state = self._state(db, debate)
        self._check_epoch(state, epoch=epoch, session_hash=session_hash)
        turn = next((item for item in self._turns(db, debate) if str(item.id) == turn_id), None)
        if turn is None or not self._prefetchable_turn(db, debate, turn):
            raise conflict("next_not_ready", "This speech's audio is not ready yet.")
        return turn_id, self._prefetch_url(debate_id, turn_id, state, epoch, session_hash)

    def _prefetch_url(
        self, debate_id: str, turn_id: str, state: Any, epoch: str, session_hash: str
    ) -> str:
        # One outstanding prefetch per item; a repeat replaces it.
        self.ticket_store.revoke_item(debate_id, turn_id)
        token, _binding = self.ticket_store.issue(
            session_hash=session_hash,
            controller_epoch=epoch,
            debate_id=debate_id,
            turn_id=turn_id,
            action="prefetch",
            control_version=state.control_version,
        )
        return self._media_url(debate_id, turn_id, token)

    def _media_url(self, debate_id: str, turn_id: str, token: str) -> str:
        """The ticket URL; it asks for the MP3 copy when the server can encode one."""

        url = f"/api/v1/debates/{debate_id}/audio/{turn_id}?media_ticket={token}"
        store = self.audio_store
        return f"{url}&format=mp3" if store is not None and store.compressed else url

    def _prefetchable_turn(self, db: Any, debate: Any, turn: Any) -> bool:
        """A speech whose saved audio can be downloaded now (final and validated)."""

        return (
            str(self._get(turn, "generation_status", default="")) == "final_ready"
            and not self._turn_text_only(turn)
            and not self._turn_text_fallback_ready(turn)
            and self._validated_turn_audio(db, debate, turn) is not None
        )

    def audio_ready_turn_ids(self, db: Any, debate: Any) -> list[str]:
        """Every speech whose audio can be downloaded now, in speaking order."""

        return [
            str(turn.id)
            for turn in self._turns(db, debate)
            if self._prefetchable_turn(db, debate, turn)
        ]

    def current_audio_url(
        self, db: Any, debate_id: str, *, session_hash: str, context: AuthContext | None = None
    ) -> str | None:
        """After Next: a controller ticket URL for the new current speech, if ready."""

        debate = self._get_debate(db, debate_id)
        self._assert_teacher(db, debate, context)
        state = self._state(db, debate)
        if (
            not state.controller_epoch
            or state.controller_session_hash != session_hash
            or not state.current_turn_id
        ):
            return None
        turn = next(
            (item for item in self._turns(db, debate) if str(item.id) == state.current_turn_id),
            None,
        )
        if turn is None or not self._prefetchable_turn(db, debate, turn):
            return None
        return self._prefetch_url(
            debate_id, str(turn.id), state, str(state.controller_epoch), session_hash
        )

    def _prefetchable_successor(self, db: Any, debate: Any, state: Any) -> Any | None:
        if not self._next_turn_ready(db, debate, state):
            return None
        current = self._current_turn(db, debate, state)
        successor, unique = self._adjacent_successor(self._turns(db, debate), current)
        if (
            successor is None
            or not unique
            or self._turn_text_only(successor)
            or self._turn_text_fallback_ready(successor)
            or self._validated_turn_audio(db, debate, successor) is None
        ):
            return None
        return successor

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

        if not uses_segment_protocol(debate) and current_pointer != debate_id:
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
        if ticket_binding.action == "prefetch":
            # PR A2: any ready speech, for the controller that asked for it.
            if state.controller_epoch != ticket_binding.controller_epoch or not (
                self._prefetchable_turn(db, debate, turn)
            ):
                raise forbidden()
            return AudioAuthorization(metadata, ticket_binding)
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
