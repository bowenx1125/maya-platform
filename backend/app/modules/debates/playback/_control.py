"""The teacher's control commands: start, next, pause, finish, reset."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.errors import PlatformError, conflict, forbidden, invalid_state, not_found
from app.modules.auth.service import AuthContext
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.topic_language import TopicLanguageError, validate_english_topic

from ._core import (
    _RECOVERABLE_PROVIDER_GENERATION_CODES,
    EvidenceTraceCorruptError,
    PlaybackCore,
)
from .audio import AudioMetadata
from .events import EventRecord
from .protocols import (
    MemoryPlaybackRepository,
)
from .schemas import (
    PlaybackStateDTO,
)

LOGGER = logging.getLogger(__name__)


class PlaybackControlMixin(PlaybackCore):
    """The teacher's control commands: start, next, pause, finish, reset."""

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
            if state.mode != "live":
                raise invalid_state("Only live playback can be finished.")
            if state.status in {"completed", "stopped"}:
                raise invalid_state("This debate has already reached a terminal state.")
            # Finish is the teacher's way out of a lesson, so it is available
            # from any live, non-terminal state. Allowing it only from
            # waiting_next trapped a debate whose turn was prepared but never
            # played: it could not be started and could not be ended, and it
            # held the course's single running slot until an operator reset.
            # A finish before every turn is public is already representable as
            # the partial finish computed below.

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
