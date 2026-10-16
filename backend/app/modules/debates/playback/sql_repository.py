"""SQLAlchemy repository adapter for the debate playback tables.

M10 owns the declarative debate models and migration.  To keep ownership
isolated, this adapter uses a deliberately small SQL/text boundary and maps
rows to provider-neutral objects consumed by ``PlaybackService``.  It never
creates or alters tables; an absent playback migration is reported as an empty
repository, which keeps Wave 1 tests independent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from app.core.sqlutil import begin_immediate
from app.providers.tts import TTS_UNAVAILABLE_CODES

from .audio import AudioMetadata
from .events import EventRecord
from .llm_publication import SqlLLMPublication
from .protocols import (
    PlaybackRepository,
    PreparedGenerationFence,
    PreparedTurn,
    ResolvedTurnVoice,
)


def _now() -> datetime:
    return datetime.now(UTC)


_TTS_DEFERRED_CODES = frozenset(
    {
        "tts_timeout",
        "tts_http_rejected",
        "tts_response_invalid",
        "tts_result_url_rejected",
        "tts_result_dns_failed",
        "tts_result_download_failed",
        "tts_audio_invalid",
    }
)


def _row_value(row: object, name: str, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _turn_structured_value(turn: object) -> Mapping[str, object] | None:
    raw = _row_value(turn, "structured_json", _row_value(turn, "structured"))
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _has_cached_segment_fence(turn: object) -> bool:
    """Recognize only a complete, already validated v2 text/fence shape."""

    speech = _row_value(turn, "speech", _row_value(turn, "original_text"))
    transcript_hash = _row_value(turn, "transcript_hash")
    structured = _turn_structured_value(turn)
    if not isinstance(speech, str) or not speech.strip() or not isinstance(transcript_hash, str):
        return False
    if not transcript_hash.strip() or structured is None:
        return False
    if structured.get("schema_version") != "segment_turn_v2":
        return False
    try:
        from app.modules.debates.generation.segments import load_stored_segment_turn_result

        return load_stored_segment_turn_result(structured).speech == speech
    except (TypeError, ValueError):
        return False


def _segment_fence_matches(turn: object, fence: PreparedGenerationFence) -> bool:
    if not _has_cached_segment_fence(turn):
        return False
    transcript_hash = _row_value(turn, "transcript_hash")
    cutoff = _row_value(turn, "cutoff_turn_index")
    predecessors = _row_value(turn, "predecessor_turn_ids_json")
    if not isinstance(transcript_hash, str) or not isinstance(cutoff, int):
        return False
    if not isinstance(predecessors, str):
        return False
    try:
        parsed = json.loads(predecessors)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return (
        transcript_hash == fence.transcript_hash
        and int(cutoff) == fence.cutoff_turn_index
        and isinstance(parsed, list)
        and tuple(str(item) for item in parsed) == tuple(fence.predecessor_turn_ids)
    )


@dataclass
class SqlRow:
    """A mutable row projection retaining no provider-specific fields."""

    values: dict[str, Any] = field(default_factory=dict)
    _session: Any = field(default=None, repr=False)

    def __getattr__(self, name: str) -> Any:
        values = object.__getattribute__(self, "values")
        if name in values:
            return values[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"values", "_session"}:
            object.__setattr__(self, name, value)
        else:
            self.values[name] = value


def _row(result: Any, session: Any) -> SqlRow | None:
    mapping = result.mappings().first()
    if mapping is None:
        return None
    return SqlRow(dict(mapping), session)


def _rows(result: Any, session: Any) -> list[SqlRow]:
    return [SqlRow(dict(value), session) for value in result.mappings().all()]


class SqlEventStore:
    """Durable ``debate_events`` implementation for the event hub."""

    def __init__(self, session_factory: Any | None = None) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _session_for(event: EventRecord, factory: Any | None) -> tuple[Any, bool]:
        if factory is None:
            raise RuntimeError("SqlEventStore needs a session factory")
        session = factory()
        return session, True

    def append_event(self, event: EventRecord) -> None:
        session, owned = self._session_for(event, self.session_factory)
        try:
            session.execute(
                text(
                    "INSERT INTO debate_events "
                    "(id, debate_id, sequence, event_type, event_version, "
                    "payload_json, occurred_at) VALUES "
                    "(:id, :debate_id, :sequence, :event_type, :event_version, "
                    ":payload_json, :occurred_at)"
                ),
                {
                    "id": event.event_id,
                    "debate_id": event.debate_id,
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "event_version": event.event_version,
                    "payload_json": json.dumps(
                        event.payload, sort_keys=True, separators=(",", ":")
                    ),
                    "occurred_at": event.occurred_at,
                },
            )
            session.commit()
        finally:
            if owned:
                session.close()

    def events_after(self, debate_id: str, sequence: int) -> tuple[EventRecord, ...]:
        session, owned = self._session_for(
            EventRecord(str(uuid4()), debate_id, 0, "snapshot", 1, _now(), {}),
            self.session_factory,
        )
        try:
            result = session.execute(
                text(
                    "SELECT id, debate_id, sequence, event_type, event_version, "
                    "payload_json, occurred_at FROM debate_events "
                    "WHERE debate_id=:debate_id AND sequence>:sequence ORDER BY sequence"
                ),
                {"debate_id": debate_id, "sequence": sequence},
            )
            output: list[EventRecord] = []
            for item in result.mappings().all():
                try:
                    payload = json.loads(str(item["payload_json"]))
                except (TypeError, ValueError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                output.append(
                    EventRecord(
                        event_id=str(item["id"]),
                        debate_id=str(item["debate_id"]),
                        sequence=int(item["sequence"]),
                        event_type=str(item["event_type"]),
                        event_version=int(item["event_version"]),
                        occurred_at=item["occurred_at"],
                        payload=payload,
                    )
                )
            return tuple(output)
        finally:
            if owned:
                session.close()

    def last_sequence(self, debate_id: str) -> int:
        session, owned = self._session_for(
            EventRecord(str(uuid4()), debate_id, 0, "snapshot", 1, _now(), {}),
            self.session_factory,
        )
        try:
            value = session.execute(
                text(
                    "SELECT COALESCE(MAX(sequence), 0) FROM debate_events "
                    "WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).scalar_one()
            return int(value or 0)
        finally:
            if owned:
                session.close()


class SqlPlaybackRepository(PlaybackRepository):
    """Read/write adapter for M10's migration without importing its classes."""

    def __init__(self, *, session_factory: Any | None = None) -> None:
        self.session_factory = session_factory

    @staticmethod
    def last_sequence_in_session(db: Any, debate_id: str) -> int:
        value = db.execute(
            text("SELECT last_sequence FROM debates WHERE id=:debate_id"),
            {"debate_id": debate_id},
        ).scalar_one_or_none()
        if value is None:
            raise RuntimeError("debate event owner is unavailable")
        return int(value)

    @staticmethod
    def resolve_effective_voice(
        db: Any,
        participant: SqlRow,
        settings: Any,
    ) -> ResolvedTurnVoice:
        """Resolve custom/system audio; an empty real token means text-only."""

        def ready_profile(
            profile_id: str | None, *, system_only: bool = False
        ) -> tuple[str, str] | None:
            if not profile_id:
                return None
            scope_guard = " AND scope='system' AND group_id IS NULL" if system_only else ""
            row = (
                db.execute(
                    text(
                        "SELECT id, scope, group_id, provider_key, target_model_key, "
                        "external_id_encrypted FROM voice_profiles "
                        "WHERE id=:profile_id AND status='ready'" + scope_guard
                    ),
                    {"profile_id": profile_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            model = row["target_model_key"]
            if not isinstance(model, str) or not model:
                return None
            if getattr(settings, "tts_provider", "mock") == "mock":
                return str(profile_id), model
            if row["provider_key"] != "dashscope" or not row["external_id_encrypted"]:
                return None
            from app.modules.voices.crypto import VoiceEncryptionError, decrypt_external_voice_id

            try:
                token = decrypt_external_voice_id(
                    row["external_id_encrypted"],
                    settings.secret_bytes,
                    profile_id=str(profile_id),
                    scope=row["scope"],
                    group_id=row["group_id"],
                    provider_key=row["provider_key"],
                    target_model_key=model,
                )
            except VoiceEncryptionError:
                return None
            return token, model

        frozen_id = getattr(participant, "effective_voice_profile_id", None)
        if getattr(participant, "effective_voice_kind", None) == "platform_profile" and (
            ready := ready_profile(frozen_id)
        ):
            return ResolvedTurnVoice("platform_profile", str(frozen_id), *ready)
        fallback_id = getattr(settings, "fallback_voice_profile_id", None)
        if ready := ready_profile(fallback_id, system_only=True):
            return ResolvedTurnVoice("platform_profile", str(fallback_id), *ready)
        if getattr(settings, "tts_provider", "mock") == "mock":
            return ResolvedTurnVoice("mock_sentinel", None, "mock")
        return ResolvedTurnVoice("mock_sentinel", None, "")

    def recover_startup(self, db: Any) -> tuple[str, ...]:
        """Fence interrupted work and revoke process-local playback authority."""

        if not self._has_table(db, "debates"):
            return ()
        paused_ids: set[str] = set()
        if self._has_table(db, "playback_states"):
            paused_ids = {
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT ps.debate_id FROM playback_states AS ps "
                        "JOIN debates AS d ON d.id=ps.debate_id "
                        "WHERE ps.status='paused' AND d.status='running'"
                    )
                ).all()
            }
        accepted_recovery_turns: set[str] = set()
        blocked_recovery_turns: set[str] = set()
        deferred_provider_turns: set[str] = set()
        deferred_segment_tts_turns: set[str] = set()
        if (
            self._has_table(db, "llm_accepted_stages")
            and self._has_table(db, "llm_recovery_inputs")
            and self._has_table(db, "provider_operations")
        ):
            accepted_recovery_turns = {
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT s.turn_id FROM llm_accepted_stages AS s "
                        "JOIN llm_recovery_inputs AS r ON r.operation_id=s.operation_id "
                        "JOIN provider_operations AS p ON p.id=s.operation_id "
                        "WHERE p.provider_operation='llm_debate_turn' "
                        "AND p.state='accepted' AND p.logical_item_id=s.turn_id"
                    )
                ).all()
            }
            blocked_recovery_turns = {
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT s.turn_id FROM llm_accepted_stages AS s "
                        "JOIN provider_operations AS p ON p.id=s.operation_id "
                        "LEFT JOIN llm_recovery_inputs AS r ON r.operation_id=s.operation_id "
                        "WHERE p.provider_operation='llm_debate_turn' "
                        "AND p.state='accepted' AND r.operation_id IS NULL"
                    )
                ).all()
            }
            # A complete accepted bundle is a local continuation point.  It
            # must not be converted into process_restarted/failed work; the
            # next playback preparation will map/validate it without a
            # provider call and proceed to TTS.
            if accepted_recovery_turns:
                if self._has_table(db, "debate_turns"):
                    db.execute(
                        text(
                            "UPDATE debate_turns SET generation_status='pending', "
                            "preparation_stage='generation', safe_error_code=NULL, "
                            "updated_at=:updated_at WHERE id IN :turn_ids "
                            "AND COALESCE(safe_error_code,'') NOT IN :tts_codes"
                        ).bindparams(
                            bindparam("turn_ids", expanding=True),
                            bindparam("tts_codes", expanding=True),
                        ),
                        {
                            "updated_at": _now(),
                            "turn_ids": tuple(accepted_recovery_turns),
                            "tts_codes": tuple(_TTS_DEFERRED_CODES),
                        },
                    )
                if self._has_table(db, "jobs"):
                    db.execute(
                        text(
                            "UPDATE jobs SET state='pending', claim_token=NULL, "
                            "safe_error_code=NULL, updated_at=:updated_at "
                            "WHERE turn_id IN :turn_ids AND state IN ('pending','running') "
                            "AND COALESCE(safe_error_code,'') NOT IN :tts_codes"
                        ).bindparams(
                            bindparam("turn_ids", expanding=True),
                            bindparam("tts_codes", expanding=True),
                        ),
                        {
                            "updated_at": _now(),
                            "turn_ids": tuple(accepted_recovery_turns),
                            "tts_codes": tuple(_TTS_DEFERRED_CODES),
                        },
                    )
            if blocked_recovery_turns:
                if self._has_table(db, "debate_turns"):
                    db.execute(
                        text(
                            "UPDATE debate_turns SET generation_status='pending', "
                            "preparation_stage='generation', "
                            "safe_error_code='llm_recovery_input_unavailable', "
                            "updated_at=:updated_at WHERE id IN :turn_ids"
                        ).bindparams(bindparam("turn_ids", expanding=True)),
                        {"updated_at": _now(), "turn_ids": tuple(blocked_recovery_turns)},
                    )
                if self._has_table(db, "jobs"):
                    db.execute(
                        text(
                            "UPDATE jobs SET state='pending', claim_token=NULL, "
                            "safe_error_code='llm_recovery_input_unavailable', "
                            "updated_at=:updated_at WHERE turn_id IN :turn_ids "
                            "AND state IN ('pending','running')"
                        ).bindparams(bindparam("turn_ids", expanding=True)),
                        {"updated_at": _now(), "turn_ids": tuple(blocked_recovery_turns)},
                    )
        if self._has_table(db, "jobs"):
            if self._has_table(db, "debate_turns"):
                deferred_segment_tts_turns = {
                    str(row[0])
                    for row in db.execute(
                        text(
                            "SELECT DISTINCT j.turn_id FROM jobs AS j "
                            "JOIN debate_turns AS t ON t.id=j.turn_id "
                            "WHERE j.turn_id IS NOT NULL AND j.state IN ('pending','running') "
                            "AND j.safe_error_code IN :tts_codes "
                            "AND json_valid(t.structured_json) "
                            "AND json_extract(t.structured_json, '$.schema_version')="
                            "'segment_turn_v2' AND trim(COALESCE(t.speech,''))<>'' "
                            "AND trim(COALESCE(t.transcript_hash,''))<>''"
                        ).bindparams(bindparam("tts_codes", expanding=True)),
                        {"tts_codes": tuple(_TTS_DEFERRED_CODES) or ("",)},
                    ).all()
                }
                if deferred_segment_tts_turns:
                    db.execute(
                        text(
                            "UPDATE debate_turns SET generation_status='pending', "
                            "preparation_stage='generation', updated_at=:updated_at "
                            "WHERE id IN :turn_ids"
                        ).bindparams(bindparam("turn_ids", expanding=True)),
                        {
                            "updated_at": _now(),
                            "turn_ids": tuple(deferred_segment_tts_turns),
                        },
                    )
            if deferred_segment_tts_turns:
                db.execute(
                    text(
                        "UPDATE jobs SET state='pending', claim_token=NULL, updated_at=:updated_at "
                        "WHERE turn_id IN :turn_ids AND state IN ('pending','running') "
                        "AND safe_error_code IN :tts_codes"
                    )
                    .bindparams(bindparam("turn_ids", expanding=True))
                    .bindparams(bindparam("tts_codes", expanding=True)),
                    {
                        "updated_at": _now(),
                        "turn_ids": tuple(deferred_segment_tts_turns),
                        "tts_codes": tuple(_TTS_DEFERRED_CODES),
                    },
                )
            deferred_provider_turns = {
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT DISTINCT turn_id FROM jobs "
                        "WHERE turn_id IS NOT NULL AND state IN ('pending','running') "
                        "AND safe_error_code IN "
                        "('provider_confirmation_required','provider_not_sent',"
                        "'acceptance_unknown')"
                    )
                ).all()
            }
            if deferred_provider_turns and self._has_table(db, "debate_turns"):
                db.execute(
                    text(
                        "UPDATE debate_turns SET generation_status='pending', "
                        "preparation_stage='generation', updated_at=:updated_at "
                        "WHERE id IN :turn_ids"
                    ).bindparams(bindparam("turn_ids", expanding=True)),
                    {"updated_at": _now(), "turn_ids": tuple(deferred_provider_turns)},
                )
            if deferred_provider_turns:
                db.execute(
                    text(
                        "UPDATE jobs SET state='pending', claim_token=NULL, "
                        "updated_at=:updated_at WHERE turn_id IN :turn_ids "
                        "AND state IN ('pending','running')"
                    ).bindparams(bindparam("turn_ids", expanding=True)),
                    {"updated_at": _now(), "turn_ids": tuple(deferred_provider_turns)},
                )
        if self._has_table(db, "debate_turns"):
            # A pending turn holding a transcript_hash cannot be prepared by
            # anything: mark_turn_running requires that hash to be null, so the
            # turn reads as ready to start, claims cleanly, and is refused at
            # the last CAS every time. The pair is contradictory whatever
            # produced it, so startup clears it rather than leaving a Debate
            # that can never move.
            db.execute(
                text(
                    "UPDATE debate_turns SET transcript_hash=NULL, updated_at=:updated_at "
                    "WHERE generation_status='pending' AND transcript_hash IS NOT NULL "
                    "AND NOT (json_valid(structured_json) "
                    "AND json_extract(structured_json, '$.schema_version')='segment_turn_v2' "
                    "AND trim(COALESCE(speech,''))<>'')"
                ),
                {"updated_at": _now()},
            )
        affected: tuple[str, ...] = ()
        if self._has_table(db, "jobs"):
            all_inflight = tuple(
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT DISTINCT debate_id FROM jobs WHERE debate_id IS NOT NULL "
                        "AND state IN ('pending','running')"
                    )
                ).all()
            )
            # A paused run keeps its cancellation generation and can continue
            # after the teacher reconnects.  Only non-paused in-flight runs
            # are interrupted and converted to failed debates on restart.
            accepted_recovery_debates: set[str] = set()
            protected_turns = (
                accepted_recovery_turns
                | blocked_recovery_turns
                | deferred_provider_turns
                | deferred_segment_tts_turns
            )
            if protected_turns and self._has_table(db, "debate_turns"):
                accepted_recovery_debates = {
                    str(row[0])
                    for row in db.execute(
                        text(
                            "SELECT DISTINCT debate_id FROM debate_turns WHERE id IN :turn_ids"
                        ).bindparams(bindparam("turn_ids", expanding=True)),
                        {"turn_ids": tuple(protected_turns)},
                    ).all()
                }
            affected = tuple(
                item
                for item in all_inflight
                if item not in paused_ids and item not in accepted_recovery_debates
            )
            if paused_ids:
                if self._has_table(db, "debate_turns"):
                    db.execute(
                        text(
                            "UPDATE debate_turns SET generation_status='pending', "
                            "preparation_stage='generation', safe_error_code=NULL, "
                            "updated_at=:updated_at WHERE generation_status IN "
                            "('pending','running') "
                            "AND id IN (SELECT j.turn_id FROM jobs AS j "
                            "JOIN playback_states AS ps ON ps.debate_id=j.debate_id "
                            "JOIN debates AS d ON d.id=ps.debate_id "
                            "WHERE j.turn_id IS NOT NULL AND j.state IN ('pending','running') "
                            "AND ps.status='paused' AND d.status='running' "
                            "AND j.turn_id NOT IN :deferred_segment_tts_turn_ids)"
                        ).bindparams(bindparam("deferred_segment_tts_turn_ids", expanding=True)),
                        {
                            "updated_at": _now(),
                            "deferred_segment_tts_turn_ids": tuple(deferred_segment_tts_turns)
                            or ("",),
                        },
                    )
                db.execute(
                    text(
                        "UPDATE jobs SET state='pending', safe_error_code=NULL, "
                        "claim_token=NULL, updated_at=:updated_at "
                        "WHERE state IN ('pending','running') AND debate_id IN "
                        "(SELECT ps.debate_id FROM playback_states AS ps "
                        "JOIN debates AS d ON d.id=ps.debate_id "
                        "WHERE ps.status='paused' AND d.status='running') "
                        "AND (turn_id IS NULL OR turn_id NOT IN "
                        ":deferred_segment_tts_turn_ids)"
                    ).bindparams(bindparam("deferred_segment_tts_turn_ids", expanding=True)),
                    {
                        "updated_at": _now(),
                        "deferred_segment_tts_turn_ids": tuple(deferred_segment_tts_turns) or ("",),
                    },
                )
            # Mark the Turn while its Job still has the pre-restart state;
            # otherwise diagnostics could observe a failed Debate with a
            # generation row that still looks resumable.
            if self._has_table(db, "debate_turns"):
                db.execute(
                    text(
                        "UPDATE debate_turns SET generation_status='failed', "
                        "preparation_stage='failed', safe_error_code='process_restarted', "
                        "updated_at=:updated_at WHERE generation_status IN ('pending','running') "
                        "AND id NOT IN :accepted_turn_ids "
                        "AND id NOT IN :blocked_turn_ids "
                        "AND id NOT IN :deferred_provider_turn_ids "
                        "AND id NOT IN :deferred_segment_tts_turn_ids "
                        "AND id IN (SELECT turn_id FROM jobs WHERE debate_id IS NOT NULL "
                        "AND turn_id IS NOT NULL AND state IN ('pending','running'))"
                    )
                    .bindparams(bindparam("accepted_turn_ids", expanding=True))
                    .bindparams(bindparam("blocked_turn_ids", expanding=True))
                    .bindparams(bindparam("deferred_provider_turn_ids", expanding=True))
                    .bindparams(bindparam("deferred_segment_tts_turn_ids", expanding=True)),
                    {
                        "updated_at": _now(),
                        "accepted_turn_ids": tuple(accepted_recovery_turns) or ("",),
                        "blocked_turn_ids": tuple(blocked_recovery_turns) or ("",),
                        "deferred_provider_turn_ids": tuple(deferred_provider_turns) or ("",),
                        "deferred_segment_tts_turn_ids": tuple(deferred_segment_tts_turns) or ("",),
                    },
                )
            db.execute(
                text(
                    "UPDATE jobs SET state='interrupted', safe_error_code='process_restarted', "
                    "updated_at=:updated_at WHERE debate_id IS NOT NULL "
                    "AND state IN ('pending','running') AND turn_id NOT IN :accepted_turn_ids "
                    "AND turn_id NOT IN :blocked_turn_ids "
                    "AND turn_id NOT IN :deferred_provider_turn_ids "
                    "AND turn_id NOT IN :deferred_segment_tts_turn_ids "
                    "AND debate_id NOT IN "
                    "(SELECT ps.debate_id FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "WHERE ps.status='paused' AND d.status='running')"
                )
                .bindparams(bindparam("accepted_turn_ids", expanding=True))
                .bindparams(bindparam("blocked_turn_ids", expanding=True))
                .bindparams(bindparam("deferred_provider_turn_ids", expanding=True))
                .bindparams(bindparam("deferred_segment_tts_turn_ids", expanding=True)),
                {
                    "updated_at": _now(),
                    "accepted_turn_ids": tuple(accepted_recovery_turns) or ("",),
                    "blocked_turn_ids": tuple(blocked_recovery_turns) or ("",),
                    "deferred_provider_turn_ids": tuple(deferred_provider_turns) or ("",),
                    "deferred_segment_tts_turn_ids": tuple(deferred_segment_tts_turns) or ("",),
                },
            )
        state_columns = (
            self._columns(db, "playback_states")
            if self._has_table(db, "playback_states")
            else set()
        )
        pending_clear = ""
        if {
            "pending_action",
            "pending_ticket_hash",
            "pending_media_command_id",
            "audio_duration_ms",
        }.issubset(state_columns):
            pending_clear = (
                ", pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL, audio_duration_ms=0"
            )
        pending_where = (
            "pending_action IS NOT NULL OR pending_ticket_hash IS NOT NULL "
            "OR pending_media_command_id IS NOT NULL OR audio_duration_ms <> 0"
            if pending_clear
            else "0"
        )
        for debate_id in affected:
            db.execute(
                text(
                    "UPDATE debates SET status='failed', updated_at=:updated_at "
                    "WHERE id=:debate_id AND status='running'"
                ),
                {"debate_id": debate_id, "updated_at": _now()},
            )
            if self._has_table(db, "playback_states"):
                db.execute(
                    text(
                        "UPDATE playback_states SET status='stopped', cursor_ms=0, "
                        "control_version=control_version+1, controller_epoch=NULL, "
                        "controller_owner_connection=NULL, server_started_at=NULL, "
                        "updated_at=:updated_at" + pending_clear + " WHERE debate_id=:debate_id"
                    ),
                    {"debate_id": debate_id, "updated_at": _now()},
                )
        if self._has_table(db, "playback_states"):
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', cursor_ms=0, "
                    "control_version=control_version+1, controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "updated_at=:updated_at" + pending_clear + " WHERE status='playing' "
                    "AND debate_id NOT IN (SELECT id FROM debates WHERE status='failed')"
                ),
                {"updated_at": _now()},
            )
            # Explicit Pause is durable.  Revoke only process-local authority
            # and media tickets; preserve status and cursor so Continue can
            # resume the same turn after a fresh controller acquire.
            db.execute(
                text(
                    "UPDATE playback_states SET controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "control_version=control_version+1, updated_at=:updated_at"
                    + pending_clear
                    + " WHERE status='paused' AND debate_id NOT IN "
                    "(SELECT id FROM debates WHERE status='failed')"
                ),
                {"updated_at": _now()},
            )
            db.execute(
                text(
                    "UPDATE playback_states SET controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "updated_at=:updated_at"
                    + pending_clear
                    + " WHERE controller_epoch IS NOT NULL OR "
                    + pending_where
                ),
                {"updated_at": _now()},
            )
        return affected

    def recoverable_llm_turns(self, db: Any) -> tuple[tuple[str, str], ...]:
        """Return accepted stage turns that can continue locally after restart."""

        required = (
            "llm_accepted_stages",
            "llm_recovery_inputs",
            "provider_operations",
            "debate_turns",
        )
        if any(not self._has_table(db, table) for table in required):
            return ()
        rows = db.execute(
            text(
                "SELECT DISTINCT t.debate_id, t.turn_index, t.id FROM debate_turns AS t "
                "JOIN debates AS d ON d.id=t.debate_id AND d.deleted_at IS NULL "
                "JOIN llm_accepted_stages AS s ON s.turn_id=t.id "
                "JOIN llm_recovery_inputs AS r ON r.operation_id=s.operation_id "
                "JOIN provider_operations AS p ON p.id=s.operation_id "
                "WHERE p.provider_operation='llm_debate_turn' AND p.state='accepted' "
                "AND p.logical_item_id=t.id ORDER BY t.debate_id, t.turn_index, t.id"
            )
        ).all()
        return tuple((str(row[0]), str(row[2])) for row in rows)

    def unattempted_llm_turn(self, db: Any, debate_id: str, turn_id: str) -> bool:
        if not self._has_table(db, "provider_operations"):
            return False
        return (
            db.execute(
                text(
                    "SELECT id FROM provider_operations WHERE scope_id=:debate "
                    "AND logical_item_id=:turn AND provider_operation='llm_debate_turn' LIMIT 1"
                ),
                {"debate": debate_id, "turn": turn_id},
            ).first()
            is None
        )

    def audio_swap_journals(self, db: Any) -> list[SqlRow]:
        if not self._has_table(db, "file_operations"):
            return []
        return _rows(
            db.execute(
                text(
                    "SELECT * FROM file_operations WHERE operation_type='debate_audio_swap' "
                    "AND state IN ('prepared','staged','committed','cleanup_required') "
                    "ORDER BY created_at, id"
                )
            ),
            db,
        )

    def mark_audio_swap_recovered(self, db: Any, operation_id: str) -> None:
        db.execute(
            text(
                "UPDATE file_operations SET state='recovered', updated_at=:updated_at "
                "WHERE id=:id AND operation_type='debate_audio_swap' "
                "AND state IN ('prepared','staged','committed','cleanup_required')"
            ),
            {"id": operation_id, "updated_at": _now()},
        )

    @staticmethod
    def _dialect_name(db: Any) -> str:
        bind = db.get_bind()
        return str(getattr(getattr(bind, "dialect", None), "name", ""))

    @staticmethod
    def _has_table(db: Any, table: str) -> bool:
        try:
            if SqlPlaybackRepository._dialect_name(db) == "postgresql":
                statement = text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                )
            else:
                statement = text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name")
            row = db.execute(statement, {"name": table}).first()
        except Exception:
            return False
        return row is not None

    @staticmethod
    def _columns(db: Any, table: str) -> set[str]:
        try:
            if SqlPlaybackRepository._dialect_name(db) == "postgresql":
                rows = db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :name"
                    ),
                    {"name": table},
                ).all()
                return {str(row[0]) for row in rows}
            return {str(row[1]) for row in db.execute(text(f"PRAGMA table_info({table})")).all()}
        except Exception:
            return set()

    @classmethod
    def _select_one(cls, db: Any, table: str, object_id: str) -> SqlRow | None:
        if not cls._has_table(db, table):
            return None
        return _row(db.execute(text(f"SELECT * FROM {table} WHERE id=:id"), {"id": object_id}), db)

    @classmethod
    def _update_row(cls, db: Any, table: str, row: SqlRow, *, key: str = "id") -> None:
        columns = cls._columns(db, table)
        values = {
            name: value for name, value in row.values.items() if name in columns and name != key
        }
        if not values or key not in row.values:
            return
        assignments = ", ".join(f"{name}=:{name}" for name in values)
        values[key] = row.values[key]
        db.execute(text(f"UPDATE {table} SET {assignments} WHERE {key}=:{key}"), values)

    def get_debate(self, db: Any, debate_id: str) -> SqlRow | None:
        row = self._select_one(db, "debates", debate_id)
        return None if row is not None and getattr(row, "deleted_at", None) is not None else row

    def save_debate(self, db: Any, debate: SqlRow) -> None:
        self._update_row(db, "debates", debate)

    def participants(self, db: Any, debate: SqlRow) -> list[SqlRow]:
        if not self._has_table(db, "debate_participants"):
            return []
        return _rows(
            db.execute(
                text(
                    "SELECT * FROM debate_participants WHERE debate_id=:debate_id "
                    "ORDER BY order_index, id"
                ),
                {"debate_id": str(debate.id)},
            ),
            db,
        )

    def turns(self, db: Any, debate: SqlRow) -> list[SqlRow]:
        if not self._has_table(db, "debate_turns"):
            return []
        rows = _rows(
            db.execute(
                text(
                    "SELECT * FROM debate_turns WHERE debate_id=:debate_id ORDER BY turn_index, id"
                ),
                {"debate_id": str(debate.id)},
            ),
            db,
        )
        if self._has_table(db, "turn_sources"):
            for turn in rows:
                turn.sources = _rows(
                    db.execute(
                        text("SELECT * FROM turn_sources WHERE turn_id=:turn_id ORDER BY rank, id"),
                        {"turn_id": str(turn.id)},
                    ),
                    db,
                )
        return rows

    def ensure_turn_plan(self, db: Any, debate: SqlRow) -> list[SqlRow]:
        existing = self.turns(db, debate)
        if existing or not self._has_table(db, "debate_turns"):
            return existing
        # M10 is the sole owner of the deterministic plan and predecessor
        # prefix.  Do not duplicate that algorithm here: its helper assigns
        # every UUID before insert and freezes the exact lower-index prefix.
        from app.modules.debates.setup.service import commit_start_plan

        commit_start_plan(
            db,
            debate_id=str(debate.id),
            expected_revision=int(debate.revision),
            expected_status="draft",
        )
        return self.turns(db, debate)

    def playback_state(self, db: Any, debate: SqlRow) -> SqlRow:
        if not self._has_table(db, "playback_states"):
            # A test can provide a fake row even before migration.  Production
            # composition must fail closed rather than creating an untracked
            # in-memory authority.
            raise RuntimeError("Debate playback tables are not installed")
        result = db.execute(
            text("SELECT * FROM playback_states WHERE debate_id=:debate_id"),
            {"debate_id": str(debate.id)},
        )
        row = _row(result, db)
        if row is not None:
            return row
        columns = self._columns(db, "playback_states")
        values: dict[str, Any] = {
            "debate_id": str(debate.id),
            "status": "preparing",
            "mode": "live",
            "current_turn_id": None,
            "cursor_ms": 0,
            "playback_rate": 1.0,
            "control_version": 0,
            "controller_epoch": None,
            "controller_session_hash": None,
            "controller_connection_id": None,
            "pending_action": None,
            "pending_ticket_hash": None,
            "pending_media_command_id": None,
            "audio_duration_ms": 0,
            "replay_scope": None,
            "replay_index": None,
            "replay_turn_ids_json": "[]",
            "created_at": _now(),
            "updated_at": _now(),
        }
        filtered = {key: value for key, value in values.items() if key in columns}
        names = ", ".join(filtered)
        bind = ", ".join(f":{key}" for key in filtered)
        db.execute(text(f"INSERT INTO playback_states ({names}) VALUES ({bind})"), filtered)
        return self.playback_state(db, debate)

    def save_playback(self, db: Any, state: SqlRow) -> None:
        self._update_row(db, "playback_states", state, key="debate_id")

    def advance_playback_cas(
        self,
        db: Any,
        debate: SqlRow,
        *,
        expected_control_version: int,
        expected_current_turn_id: str,
        successor_turn_id: str,
        teacher_user_id: str | None = None,
    ) -> bool:
        """Atomically claim the live successor transition, interrupting audio if needed.

        The application request session may already hold a read snapshot after
        resolving the playback DTO.  SQLite WAL cannot promote that snapshot
        after another writer commits, so a Next claim must never write through
        it.  When a session factory is available, use the short-lived claim
        transaction below instead.  The legacy branch is retained for small
        repository doubles that do not expose a factory.
        """

        if self.session_factory is not None:
            return self.claim_next_playback(
                debate_id=str(debate.id),
                expected_control_version=expected_control_version,
                expected_current_turn_id=expected_current_turn_id,
                successor_turn_id=successor_turn_id,
                teacher_user_id=teacher_user_id,
            )

        changed = db.execute(
            text(
                "UPDATE playback_states SET status='ready', mode='live', "
                "current_turn_id=:successor_turn_id, cursor_ms=0, "
                "control_version=:next_control_version, server_started_at=NULL, "
                "pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL, audio_duration_ms=0, "
                "updated_at=:updated_at WHERE debate_id=:debate_id "
                "AND status IN ('playing','paused','waiting_next') AND mode='live' "
                "AND current_turn_id=:expected_current_turn_id "
                "AND control_version=:expected_control_version "
                "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=:debate_id "
                "AND debates.status='running')"
            ),
            {
                "successor_turn_id": successor_turn_id,
                "next_control_version": expected_control_version + 1,
                "updated_at": _now(),
                "debate_id": str(debate.id),
                "expected_current_turn_id": expected_current_turn_id,
                "expected_control_version": expected_control_version,
            },
        )
        return int(getattr(changed, "rowcount", 0)) == 1

    def claim_next_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str,
        successor_turn_id: str,
        teacher_user_id: str | None = None,
        committed_events: list[EventRecord] | None = None,
    ) -> bool:
        """Run the cross-process Next claim in a fresh, serialized transaction.

        ``BEGIN IMMEDIATE`` is deliberately the first SQL sent on the new
        connection.  It takes SQLite's writer lock before any validation read,
        so another process either waits for this claim to commit or validates
        against its committed result.  A failed validation/claim is therefore
        a deterministic stale result rather than a WAL snapshot promotion
        error.  The final UPDATE repeats the identity CAS; the write lock also
        prevents a concurrent writer from changing any gate between the
        validation SELECT and this UPDATE.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        params = {
            "debate_id": debate_id,
            "expected_control_version": expected_control_version,
            "expected_current_turn_id": expected_current_turn_id,
            "successor_turn_id": successor_turn_id,
            "teacher_user_id": teacher_user_id,
            "mutual_rule_set_id": "ordered_multi_expert_mutual_learning_v1",
            "teaching_protocol": "four_round_v1",
            "tts_codes": tuple(sorted(TTS_UNAVAILABLE_CODES)),
        }
        try:
            # Do not issue a SELECT (or any other statement) before this
            # explicit write transaction.  This is the WAL snapshot fix.
            begin_immediate(claim_session)
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid AS claim_rowid, successor.audio_file_id, "
                    "successor.audio_duration_ms "
                    "FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "JOIN debate_turns AS current_turn "
                    "ON current_turn.id=ps.current_turn_id "
                    "AND current_turn.debate_id=ps.debate_id "
                    "JOIN debate_turns AS successor "
                    "ON successor.id=:successor_turn_id "
                    "AND successor.debate_id=ps.debate_id "
                    "AND successor.turn_index=current_turn.turn_index + 1 "
                    "WHERE ps.debate_id=:debate_id "
                    "AND ps.status IN ('playing','paused','waiting_next') AND ps.mode='live' "
                    "AND ps.current_turn_id=:expected_current_turn_id "
                    "AND ps.control_version=:expected_control_version "
                    "AND ps.replay_scope IS NULL AND ps.replay_index IS NULL "
                    "AND d.status='running' "
                    "AND :teacher_user_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM course_members AS cm "
                    "WHERE cm.course_id=d.course_id AND cm.user_id=:teacher_user_id "
                    "AND cm.role='teacher') "
                    "AND current_turn.publication_status='public' "
                    "AND NOT EXISTS (SELECT 1 FROM debate_turns AS prefix "
                    "WHERE prefix.debate_id=ps.debate_id "
                    "AND prefix.turn_index < current_turn.turn_index "
                    "AND (d.rule_set_id <> :mutual_rule_set_id "
                    "OR (json_extract(d.rule_snapshot_json, '$.teaching_protocol') "
                    "= :teaching_protocol AND current_turn.round_no > 1) "
                    "OR prefix.round_no < current_turn.round_no) "
                    "AND prefix.publication_status <> 'public') "
                    "AND (SELECT COUNT(*) FROM debate_turns AS prefix_count "
                    "WHERE prefix_count.debate_id=ps.debate_id "
                    "AND prefix_count.turn_index < CASE "
                    "WHEN d.rule_set_id=:mutual_rule_set_id THEN successor.turn_index "
                    "ELSE current_turn.turn_index END "
                    # The mutual-learning visible set belongs to the successor's
                    # round, exactly like the cutoff and predecessor checks
                    # below.  Counting against the current turn's round makes
                    # every round boundary unclaimable.
                    "AND (d.rule_set_id <> :mutual_rule_set_id "
                    "OR (json_extract(d.rule_snapshot_json, '$.teaching_protocol') "
                    "= :teaching_protocol AND successor.round_no > 1) "
                    "OR prefix_count.round_no < successor.round_no)) "
                    "= CASE WHEN d.rule_set_id=:mutual_rule_set_id "
                    "THEN json_array_length(successor.predecessor_turn_ids_json) "
                    "ELSE current_turn.turn_index END "
                    "AND NOT EXISTS (SELECT 1 FROM debate_turns AS duplicate "
                    "WHERE duplicate.debate_id=ps.debate_id "
                    "AND duplicate.turn_index=current_turn.turn_index + 1 "
                    "AND duplicate.id <> successor.id) "
                    "AND successor.publication_status='unpublished' "
                    "AND successor.generation_status='final_ready' "
                    "AND successor.preparation_stage='ready' "
                    "AND trim(COALESCE(successor.speech, '')) <> '' "
                    "AND ((successor.audio_file_id IS NOT NULL "
                    "AND successor.audio_duration_ms IS NOT NULL "
                    "AND successor.audio_duration_ms > 0 "
                    "AND EXISTS (SELECT 1 FROM stored_files AS sf "
                    "WHERE sf.id=successor.audio_file_id AND sf.state='active') "
                    "AND successor.actual_tts_voice_kind IN ('platform_profile','mock_sentinel') "
                    "AND ((successor.actual_tts_voice_kind='mock_sentinel' "
                    "AND successor.actual_tts_voice_profile_id IS NULL) OR "
                    "(successor.actual_tts_voice_kind='platform_profile' "
                    "AND successor.actual_tts_voice_profile_id IS NOT NULL))) OR "
                    "(successor.audio_file_id IS NULL AND successor.safe_error_code IN :tts_codes "
                    "AND (successor.audio_duration_ms IS NULL OR "
                    "(successor.safe_error_code='tts_voice_unavailable' "
                    "AND successor.audio_duration_ms=0)))) "
                    "AND successor.transcript_hash IS NOT NULL "
                    "AND trim(successor.transcript_hash) <> '' "
                    "AND successor.cutoff_turn_index=CASE "
                    "WHEN d.rule_set_id=:mutual_rule_set_id "
                    "AND json_extract(d.rule_snapshot_json, '$.teaching_protocol') "
                    "= :teaching_protocol AND successor.round_no > 1 "
                    "THEN successor.turn_index - 1 "
                    "WHEN d.rule_set_id=:mutual_rule_set_id THEN COALESCE(("
                    "SELECT MAX(prior.turn_index) FROM debate_turns AS prior "
                    "WHERE prior.debate_id=ps.debate_id "
                    "AND prior.round_no < successor.round_no), -1) "
                    "ELSE successor.turn_index - 1 END "
                    "AND json_valid(successor.predecessor_turn_ids_json) "
                    "AND successor.predecessor_turn_ids_json = ("
                    "SELECT json_group_array(prefix_ids.id) FROM ("
                    "SELECT id FROM debate_turns "
                    "WHERE debate_id=ps.debate_id "
                    "AND turn_index < successor.turn_index "
                    "AND (d.rule_set_id <> :mutual_rule_set_id "
                    "OR (json_extract(d.rule_snapshot_json, '$.teaching_protocol') "
                    "= :teaching_protocol AND successor.round_no > 1) "
                    "OR round_no < successor.round_no) "
                    "ORDER BY turn_index, id"
                    ") AS prefix_ids) "
                    "AND EXISTS (SELECT 1 FROM jobs AS successor_job "
                    "WHERE successor_job.debate_id=ps.debate_id "
                    "AND successor_job.turn_id=successor.id "
                    "AND successor_job.state='completed' "
                    "AND successor_job.cancellation_generation=d.cancellation_generation)"
                ).bindparams(bindparam("tts_codes", expanding=True)),
                params,
            ).first()
            if candidate is None:
                claim_session.rollback()
                return False

            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='live', "
                    "current_turn_id=:successor_turn_id, cursor_ms=0, "
                    "control_version=:next_control_version, server_started_at=NULL, "
                    "pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0, "
                    "updated_at=:updated_at WHERE rowid=:claim_rowid "
                    "AND debate_id=:debate_id "
                    "AND status IN ('playing','paused','waiting_next') AND mode='live' "
                    "AND current_turn_id=:expected_current_turn_id "
                    "AND control_version=:expected_control_version "
                    "AND replay_scope IS NULL AND replay_index IS NULL"
                ),
                {
                    **params,
                    "claim_rowid": candidate[0],
                    "next_control_version": expected_control_version + 1,
                    "updated_at": _now(),
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            event = None
            if candidate[1] is None and candidate[2] is None:
                event = self._publish_text_current_tx(
                    claim_session,
                    debate_id=debate_id,
                    expected_control_version=expected_control_version + 1,
                    turn_id=successor_turn_id,
                )
                if event is None:
                    claim_session.rollback()
                    return False
            claim_session.commit()
            if event is not None and committed_events is not None:
                committed_events.append(event)
            return True
        except OperationalError:
            # Includes a bounded SQLite busy timeout.  The caller exposes the
            # same stale 409 as a losing CAS; it must never retry a provider or
            # leak a transient 503 for this teacher command.
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def _publish_text_current_tx(
        self,
        db: Any,
        *,
        debate_id: str,
        expected_control_version: int,
        turn_id: str,
        expected_generation: int | None = None,
    ) -> EventRecord | None:
        """Finish only the text item already selected by teacher Start/Next."""

        from app.modules.debates.round_count import (
            debate_round_count,
            debate_teaching_protocol,
            uses_segment_protocol,
        )

        debate = self.get_debate(db, debate_id)
        if debate is None or debate.status != "running":
            return None
        generation = int(debate.cancellation_generation or 0)
        if expected_generation is not None and generation != expected_generation:
            return None
        state = self.playback_state(db, debate)
        if (
            state.mode != "live"
            or state.status not in {"preparing", "ready"}
            or state.current_turn_id != turn_id
            or state.control_version != expected_control_version
            or state.replay_scope is not None
            or state.replay_index is not None
        ):
            return None
        turns = self.turns(db, debate)
        turn = next((item for item in turns if str(item.id) == turn_id), None)
        if (
            turn is None
            or turn.generation_status != "final_ready"
            or turn.preparation_stage != "ready"
            or turn.publication_status != "unpublished"
            or turn.audio_file_id is not None
            or turn.audio_duration_ms is not None
            or turn.safe_error_code not in TTS_UNAVAILABLE_CODES
            or not str(turn.speech or "").strip()
            or not str(turn.transcript_hash or "").strip()
        ):
            return None
        prior = [item for item in turns if int(item.turn_index) < int(turn.turn_index)]
        if [int(item.turn_index) for item in prior] != list(range(int(turn.turn_index))):
            return None
        if any(item.publication_status != "public" for item in prior):
            return None
        mutual = debate.rule_set_id == "ordered_multi_expert_mutual_learning_v1" and not (
            debate_teaching_protocol(debate) == "four_round_v1" and int(turn.round_no) > 1
        )
        predecessors = (
            [item for item in prior if int(item.round_no) < int(turn.round_no)] if mutual else prior
        )
        expected_cutoff = max((int(item.turn_index) for item in predecessors), default=-1)
        try:
            frozen_ids = json.loads(turn.predecessor_turn_ids_json)
        except (TypeError, ValueError):
            return None
        if frozen_ids != [str(item.id) for item in predecessors] or (
            turn.cutoff_turn_index != expected_cutoff
        ):
            return None
        if (
            uses_segment_protocol(debate)
            and int(turn.round_no) == debate_round_count(debate)
            and not getattr(debate, "final_input_json", None)
        ):
            return None
        job = db.execute(
            text(
                "SELECT 1 FROM jobs WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND state='completed' AND cancellation_generation=:generation"
            ),
            {"debate_id": debate_id, "turn_id": turn_id, "generation": generation},
        ).first()
        if job is None:
            return None
        changed = db.execute(
            text(
                "UPDATE playback_states SET status='waiting_next', cursor_ms=0, "
                "control_version=control_version+1, server_started_at=NULL, "
                "pending_action=NULL, pending_ticket_hash=NULL, pending_media_command_id=NULL, "
                "audio_duration_ms=0, updated_at=:now WHERE debate_id=:debate_id "
                "AND current_turn_id=:turn_id AND control_version=:version "
                "AND mode='live' AND status IN ('preparing','ready')"
            ),
            {
                "now": _now(),
                "debate_id": debate_id,
                "turn_id": turn_id,
                "version": expected_control_version,
            },
        )
        if int(getattr(changed, "rowcount", 0)) != 1 or not self.publish_turn(db, turn):
            raise RuntimeError("text publication lost its current turn fence")
        return self.append_event_tx(
            db,
            debate_id=debate_id,
            event_type="playback.waiting_next",
            payload={
                "mode": "live",
                "completed_turn_id": turn_id,
                "control_version": expected_control_version + 1,
                "next_turn_ready": False,
            },
        )

    def claim_text_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        turn_id: str,
        expected_generation: int,
    ) -> EventRecord | None:
        if self.session_factory is None:
            return None
        with self.session_factory() as db:
            try:
                begin_immediate(db)
                event = self._publish_text_current_tx(
                    db,
                    debate_id=debate_id,
                    expected_control_version=expected_control_version,
                    turn_id=turn_id,
                    expected_generation=expected_generation,
                )
                if event is None:
                    db.rollback()
                else:
                    db.commit()
                return event
            except OperationalError:
                db.rollback()
                return None

    def claim_pause_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        cursor_ms: int,
        teacher_user_id: str | None = None,
    ) -> bool:
        """CAS a playing item into durable, recoverable ``paused`` state.

        The request Session may have an old WAL read snapshot (for example
        after loading a teacher page).  Use a fresh ``BEGIN IMMEDIATE`` writer
        and repeat the teacher/current-version checks there so a concurrent
        tab can win deterministically without a database lock promotion error.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid, ps.current_turn_id, ps.control_version "
                    "FROM playback_states AS ps JOIN debates AS d ON d.id=ps.debate_id "
                    "WHERE ps.debate_id=:debate_id AND ps.status='playing' "
                    "AND ps.current_turn_id IS NOT NULL "
                    "AND ps.control_version=:expected_control_version "
                    "AND d.status='running' AND :teacher_user_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM course_members AS cm "
                    "WHERE cm.course_id=d.course_id AND cm.user_id=:teacher_user_id "
                    "AND cm.role='teacher')"
                ),
                {
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                    "teacher_user_id": teacher_user_id,
                },
            ).first()
            if candidate is None:
                claim_session.rollback()
                return False
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET status='paused', cursor_ms=:cursor_ms, "
                    "control_version=:next_control_version, server_started_at=NULL, "
                    "pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0, "
                    "updated_at=:updated_at WHERE rowid=:rowid AND debate_id=:debate_id "
                    "AND status='playing' AND control_version=:expected_control_version"
                ),
                {
                    "rowid": candidate[0],
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                    "next_control_version": expected_control_version + 1,
                    "cursor_ms": max(0, int(cursor_ms)),
                    "updated_at": _now(),
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def claim_resume_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        teacher_user_id: str | None = None,
    ) -> bool:
        """CAS a paused item back to ``ready`` after rechecking its audio."""

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid, ps.current_turn_id FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "JOIN debate_turns AS t ON t.id=ps.current_turn_id "
                    "AND t.debate_id=ps.debate_id "
                    "WHERE ps.debate_id=:debate_id AND ps.status='paused' "
                    "AND ps.current_turn_id IS NOT NULL "
                    "AND ps.control_version=:expected_control_version "
                    "AND d.status='running' AND :teacher_user_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM course_members AS cm "
                    "WHERE cm.course_id=d.course_id AND cm.user_id=:teacher_user_id "
                    "AND cm.role='teacher') "
                    "AND t.generation_status='final_ready' "
                    "AND t.preparation_stage='ready' "
                    "AND trim(COALESCE(t.speech,'')) <> '' "
                    "AND t.audio_file_id IS NOT NULL "
                    "AND t.audio_duration_ms IS NOT NULL AND t.audio_duration_ms > 0 "
                    "AND EXISTS (SELECT 1 FROM stored_files AS sf "
                    "WHERE sf.id=t.audio_file_id AND sf.kind='debate_audio' "
                    "AND sf.state='active')"
                ),
                {
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                    "teacher_user_id": teacher_user_id,
                },
            ).first()
            if candidate is None:
                claim_session.rollback()
                return False
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET status='ready', cursor_ms=0, "
                    "control_version=:next_control_version, server_started_at=NULL, "
                    "pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0, "
                    "updated_at=:updated_at WHERE rowid=:rowid AND debate_id=:debate_id "
                    "AND status='paused' AND control_version=:expected_control_version"
                ),
                {
                    "rowid": candidate[0],
                    "debate_id": debate_id,
                    "expected_control_version": expected_control_version,
                    "next_control_version": expected_control_version + 1,
                    "updated_at": _now(),
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def claim_finish_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str | None = None,
        teacher_user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically finish a running Debate as full or partial.

        ``full`` requires every planned turn to be final-ready *and public*;
        anything less is a partial finish.  Partial completion keeps all
        immutable turn rows but bumps the cancellation generation and
        interrupts pending work, preventing late workers from publishing into
        a downstream-ineligible Debate. The Debate itself is marked
        ``debate_finished`` while its playback is terminal ``stopped``.
        """

        if self.session_factory is None:
            return None
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            row = (
                claim_session.execute(
                    text(
                        "SELECT ps.rowid, ps.current_turn_id, ps.control_version, "
                        "d.course_id, d.status, "
                        "(SELECT COUNT(*) FROM debate_turns t "
                        "WHERE t.debate_id=d.id) AS total_turns, "
                        "(SELECT COUNT(*) FROM debate_turns t WHERE t.debate_id=d.id "
                        "AND t.generation_status='final_ready' AND t.publication_status='public') "
                        "AS complete_turns "
                        "FROM playback_states ps JOIN debates d ON d.id=ps.debate_id "
                        "WHERE ps.debate_id=:debate_id "
                        "AND ps.control_version=:expected_control_version "
                        "AND ps.status IN ('preparing','ready','playing','paused','waiting_next') "
                        "AND ps.mode='live' "
                        "AND d.status='running' AND :teacher_user_id IS NOT NULL "
                        "AND EXISTS (SELECT 1 FROM course_members cm "
                        "WHERE cm.course_id=d.course_id "
                        "AND cm.user_id=:teacher_user_id AND cm.role='teacher') "
                        "AND (:expected_current_turn_id IS NULL OR "
                        "ps.current_turn_id=:expected_current_turn_id)"
                    ),
                    {
                        "debate_id": debate_id,
                        "expected_control_version": expected_control_version,
                        "expected_current_turn_id": expected_current_turn_id,
                        "teacher_user_id": teacher_user_id,
                    },
                )
                .mappings()
                .first()
            )
            if row is None:
                claim_session.rollback()
                return None
            total = int(row["total_turns"] or 0)
            complete = total > 0 and int(row["complete_turns"] or 0) == total
            now = _now()
            next_version = int(row["control_version"] or 0) + 1
            if complete:
                changed = claim_session.execute(
                    text(
                        "UPDATE debates SET status='debate_finished', finished_at=:finished_at, "
                        "updated_at=:updated_at WHERE id=:debate_id AND status='running'"
                    ),
                    {"debate_id": debate_id, "finished_at": now, "updated_at": now},
                )
                if int(getattr(changed, "rowcount", 0)) != 1:
                    claim_session.rollback()
                    return None
                playback_changed = claim_session.execute(
                    text(
                        "UPDATE playback_states SET status='completed', mode='live', "
                        "current_turn_id=NULL, cursor_ms=0, control_version=:control_version, "
                        "controller_epoch=NULL, controller_owner_connection=NULL, "
                        "server_started_at=NULL, replay_scope=NULL, replay_index=NULL, "
                        "pending_action=NULL, pending_ticket_hash=NULL, "
                        "pending_media_command_id=NULL, audio_duration_ms=0, "
                        "updated_at=:updated_at WHERE rowid=:rowid AND debate_id=:debate_id "
                        "AND control_version=:expected_control_version"
                    ),
                    {
                        "rowid": row["rowid"],
                        "debate_id": debate_id,
                        "expected_control_version": expected_control_version,
                        "control_version": next_version,
                        "updated_at": now,
                    },
                )
                if int(getattr(playback_changed, "rowcount", 0)) != 1:
                    claim_session.rollback()
                    return None
            else:
                changed = claim_session.execute(
                    text(
                        "UPDATE debates SET status='debate_finished', cancellation_generation="
                        "cancellation_generation+1, finished_at=:finished_at, "
                        "updated_at=:updated_at WHERE id=:debate_id AND status='running'"
                    ),
                    {"debate_id": debate_id, "finished_at": now, "updated_at": now},
                )
                if int(getattr(changed, "rowcount", 0)) != 1:
                    claim_session.rollback()
                    return None
                claim_session.execute(
                    text(
                        "UPDATE jobs SET state='interrupted', "
                        "safe_error_code='debate_finished_partial', "
                        "updated_at=:updated_at WHERE debate_id=:debate_id "
                        "AND state IN ('pending','running')"
                    ),
                    {"debate_id": debate_id, "updated_at": now},
                )
                playback_changed = claim_session.execute(
                    text(
                        "UPDATE playback_states SET status='stopped', mode='live', "
                        "current_turn_id=NULL, cursor_ms=0, control_version=:control_version, "
                        "controller_epoch=NULL, controller_owner_connection=NULL, "
                        "server_started_at=NULL, replay_scope=NULL, replay_index=NULL, "
                        "pending_action=NULL, pending_ticket_hash=NULL, "
                        "pending_media_command_id=NULL, audio_duration_ms=0, "
                        "updated_at=:updated_at WHERE rowid=:rowid AND debate_id=:debate_id "
                        "AND control_version=:expected_control_version"
                    ),
                    {
                        "rowid": row["rowid"],
                        "debate_id": debate_id,
                        "expected_control_version": expected_control_version,
                        "control_version": next_version,
                        "updated_at": now,
                    },
                )
                if int(getattr(playback_changed, "rowcount", 0)) != 1:
                    claim_session.rollback()
                    return None
            claim_session.commit()
            return {
                "kind": "full" if complete else "partial",
                "control_version": next_version,
                "current_turn_id": row["current_turn_id"],
                "total_turns": total,
                "complete_turns": int(row["complete_turns"] or 0),
            }
        except OperationalError:
            claim_session.rollback()
            return None
        finally:
            claim_session.close()

    def claim_replay_next_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str,
        successor_turn_id: str,
        expected_replay_index: int,
        expected_audio_relative_path: str | None = None,
        expected_audio_sha256: str | None = None,
        expected_audio_size_bytes: int | None = None,
        teacher_user_id: str | None = None,
    ) -> bool:
        """Atomically move one retained replay item past the Next gate.

        Replay has no generation job to claim.  This writer transaction only
        advances the persisted replay cursor after rechecking teacher scope,
        public adjacency and the durable StoredFile identity.  Byte-level WAV
        validation is performed immediately before this call and again by the
        media.prepare command, so a changed/corrupt file cannot be played.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        params = {
            "debate_id": debate_id,
            "expected_control_version": expected_control_version,
            "expected_current_turn_id": expected_current_turn_id,
            "successor_turn_id": successor_turn_id,
            "expected_replay_index": expected_replay_index,
            "expected_audio_relative_path": expected_audio_relative_path,
            "expected_audio_sha256": expected_audio_sha256,
            "expected_audio_size_bytes": expected_audio_size_bytes,
            "teacher_user_id": teacher_user_id,
        }
        try:
            begin_immediate(claim_session)
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid AS claim_rowid FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "JOIN courses AS c ON c.id=d.course_id "
                    "JOIN debate_turns AS current_turn ON current_turn.id=ps.current_turn_id "
                    "AND current_turn.debate_id=ps.debate_id "
                    "JOIN debate_turns AS successor ON successor.id=:successor_turn_id "
                    "AND successor.debate_id=ps.debate_id "
                    "AND successor.turn_index=current_turn.turn_index + 1 "
                    "WHERE ps.debate_id=:debate_id "
                    "AND ps.status IN ('playing','paused','waiting_next') "
                    "AND ps.mode='replay' AND ps.replay_scope='all' "
                    "AND ps.replay_index=:expected_replay_index "
                    "AND ps.current_turn_id=:expected_current_turn_id "
                    "AND ps.control_version=:expected_control_version "
                    "AND d.status IN ('debate_finished','completed') "
                    "AND (c.current_audio_debate_id=d.id OR "
                    "json_extract(d.rule_snapshot_json, '$.turn_protocol')='segments_v2') "
                    "AND :teacher_user_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM course_members AS cm "
                    "WHERE cm.course_id=d.course_id AND cm.user_id=:teacher_user_id "
                    "AND cm.role='teacher') "
                    "AND current_turn.publication_status='public' "
                    "AND successor.publication_status='public' "
                    "AND successor.generation_status='final_ready' "
                    "AND successor.preparation_stage='ready' "
                    "AND trim(COALESCE(successor.speech,'')) <> '' "
                    "AND successor.audio_file_id IS NOT NULL "
                    "AND successor.audio_duration_ms IS NOT NULL "
                    "AND successor.audio_duration_ms > 0 "
                    "AND EXISTS (SELECT 1 FROM stored_files AS sf "
                    "WHERE sf.id=successor.audio_file_id AND sf.kind='debate_audio' "
                    "AND sf.state='active' "
                    "AND sf.relative_path=:expected_audio_relative_path "
                    "AND sf.sha256=:expected_audio_sha256 "
                    "AND sf.size=:expected_audio_size_bytes) "
                    "AND NOT EXISTS (SELECT 1 FROM debate_turns AS duplicate "
                    "WHERE duplicate.debate_id=ps.debate_id "
                    "AND duplicate.turn_index=current_turn.turn_index + 1 "
                    "AND duplicate.id <> successor.id)"
                ),
                params,
            ).first()
            if candidate is None:
                claim_session.rollback()
                return False
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET status='ready', mode='replay', "
                    "current_turn_id=:successor_turn_id, cursor_ms=0, "
                    "replay_index=:next_replay_index, server_started_at=NULL, "
                    "pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0, "
                    "control_version=:next_control_version, updated_at=:updated_at "
                    "WHERE rowid=:claim_rowid AND debate_id=:debate_id "
                    "AND status IN ('playing','paused','waiting_next') AND mode='replay' "
                    "AND replay_scope='all' AND replay_index=:expected_replay_index "
                    "AND current_turn_id=:expected_current_turn_id "
                    "AND control_version=:expected_control_version"
                ),
                {
                    **params,
                    "next_replay_index": expected_replay_index + 1,
                    "next_control_version": expected_control_version + 1,
                    "updated_at": _now(),
                    "claim_rowid": candidate[0],
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def rollback_replay_next_playback(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        expected_current_turn_id: str,
        expected_replay_index: int,
        previous_turn_id: str,
        previous_replay_index: int,
    ) -> bool:
        """Return a claimed replay successor to its waiting gate by CAS.

        The service performs a second byte/pointer validation after the fresh
        Next claim.  If the file changed in that interval, this writer
        transaction prevents a corrupted successor from remaining ``ready``;
        a concurrent winner causes a stable false result rather than an
        unguarded overwrite.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            columns = self._columns(claim_session, "playback_states")
            pending_clear = ""
            if {
                "pending_action",
                "pending_ticket_hash",
                "pending_media_command_id",
                "audio_duration_ms",
            }.issubset(columns):
                pending_clear = (
                    ", pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0"
                )
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET status='waiting_next', mode='replay', "
                    "current_turn_id=:previous_turn_id, replay_index=:previous_replay_index, "
                    "cursor_ms=0, control_version=:next_control_version, "
                    "server_started_at=NULL, updated_at=:updated_at"
                    + pending_clear
                    + " WHERE debate_id=:debate_id AND status='ready' "
                    "AND mode='replay' AND replay_scope='all' "
                    "AND current_turn_id=:expected_current_turn_id "
                    "AND replay_index=:expected_replay_index "
                    "AND control_version=:expected_control_version"
                ),
                {
                    "previous_turn_id": previous_turn_id,
                    "previous_replay_index": previous_replay_index,
                    "next_control_version": expected_control_version + 1,
                    "updated_at": _now(),
                    "debate_id": debate_id,
                    "expected_current_turn_id": expected_current_turn_id,
                    "expected_replay_index": expected_replay_index,
                    "expected_control_version": expected_control_version,
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def claim_operator_reset(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        actor_kind: str = "operator",
        actor_id: str | None = None,
        request_id: str | None = None,
        teacher_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Atomically reset one Debate from a fresh SQLite writer transaction.

        Reset is an operator boundary rather than an HTTP request mutation.
        ``BEGIN IMMEDIATE`` therefore precedes every read, and the control
        version, cancellation fence, playback authority, jobs and redacted
        AuditLog row commit (or roll back) together.  A missing/invalid audit
        table is an error: silently resetting without an audit record would
        violate the operator contract.
        """

        if self.session_factory is None:
            raise RuntimeError("operator reset requires a SQL session factory")
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            row = (
                claim_session.execute(
                    text(
                        "SELECT d.status AS debate_status, d.course_id, "
                        "ps.status AS playback_status, ps.mode, ps.current_turn_id, "
                        "ps.control_version, ps.controller_epoch "
                        "FROM debates AS d JOIN playback_states AS ps ON ps.debate_id=d.id "
                        "WHERE d.id=:debate_id"
                    ),
                    {"debate_id": debate_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                claim_session.rollback()
                return {"claimed": False, "reason": "not_found"}

            current_control_version = int(row["control_version"] or 0)
            if current_control_version != expected_control_version:
                claim_session.rollback()
                return {
                    "claimed": False,
                    "reason": "stale_control_version",
                    "control_version": current_control_version,
                }
            previous_mode = str(row["mode"] or "live")
            playback_status = str(row["playback_status"] or "preparing")
            if (previous_mode == "live" and playback_status in {"completed", "stopped"}) or (
                previous_mode == "replay" and playback_status == "completed"
            ):
                claim_session.rollback()
                return {"claimed": False, "reason": "invalid_state"}
            if teacher_user_id:
                allowed = claim_session.execute(
                    text(
                        "SELECT 1 FROM course_members AS cm "
                        "WHERE cm.course_id=:course_id AND cm.user_id=:teacher_user_id "
                        "AND cm.role='teacher'"
                    ),
                    {
                        "course_id": str(row["course_id"]),
                        "teacher_user_id": teacher_user_id,
                    },
                ).first()
                if allowed is None:
                    claim_session.rollback()
                    return {"claimed": False, "reason": "forbidden"}

            resulting_status = "completed" if previous_mode == "replay" else "stopped"
            resulting_debate_status = (
                str(row["debate_status"]) if previous_mode == "replay" else "stopped"
            )
            next_control_version = current_control_version + 1
            timestamp = _now()
            claim_session.execute(
                text(
                    "UPDATE debates SET status=:status, "
                    "cancellation_generation=COALESCE(cancellation_generation, 0)+1, "
                    "updated_at=:updated_at WHERE id=:debate_id"
                ),
                {
                    "status": resulting_debate_status,
                    "updated_at": timestamp,
                    "debate_id": debate_id,
                },
            )
            if self._has_table_in_session(claim_session, "jobs"):
                claim_session.execute(
                    text(
                        "UPDATE jobs SET state='interrupted', "
                        "safe_error_code='operator_reset', updated_at=:updated_at "
                        "WHERE debate_id=:debate_id AND state IN ('pending','running')"
                    ),
                    {"updated_at": timestamp, "debate_id": debate_id},
                )

            state_columns = self._columns(claim_session, "playback_states")
            queue_clause = (
                ", replay_turn_ids_json='[]'" if "replay_turn_ids_json" in state_columns else ""
            )
            pending_clause = ""
            if {
                "pending_action",
                "pending_ticket_hash",
                "pending_media_command_id",
                "audio_duration_ms",
            }.issubset(state_columns):
                pending_clause = (
                    ", pending_action=NULL, pending_ticket_hash=NULL, "
                    "pending_media_command_id=NULL, audio_duration_ms=0"
                )
            claim_session.execute(
                text(
                    "UPDATE playback_states SET status=:status, mode='live', "
                    "current_turn_id=NULL, cursor_ms=0, "
                    "control_version=:control_version, controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "replay_scope=NULL, replay_index=NULL" + queue_clause + pending_clause + ", "
                    "updated_at=:updated_at WHERE debate_id=:debate_id "
                    "AND status=:expected_status AND mode=:expected_mode "
                    "AND control_version=:expected_control_version"
                ),
                {
                    "status": resulting_status,
                    "control_version": next_control_version,
                    "updated_at": timestamp,
                    "debate_id": debate_id,
                    "expected_status": playback_status,
                    "expected_mode": previous_mode,
                    "expected_control_version": expected_control_version,
                },
            )

            # Importing the ORM here keeps the repository's text boundary
            # narrow while still making this a real AuditLog row.  ``flush``
            # deliberately occurs before commit so any missing table,
            # constraint or malformed payload rolls the entire reset back.
            from app.modules.debates.models import AuditLog

            details_json = json.dumps(
                {
                    "mode": previous_mode,
                    "status": resulting_status,
                    "control_version": next_control_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            claim_session.add(
                AuditLog(
                    id=str(uuid4()),
                    event_type="playback.operator_reset",
                    actor_kind=actor_kind,
                    actor_id=actor_id,
                    course_id=str(row["course_id"]),
                    debate_id=debate_id,
                    request_id=request_id,
                    details_json=details_json,
                    created_at=timestamp,
                )
            )
            claim_session.flush()
            claim_session.commit()
            return {
                "claimed": True,
                "previous_mode": previous_mode,
                "previous_status": playback_status,
                "resulting_status": resulting_status,
                "debate_status": resulting_debate_status,
                "current_turn_id": row["current_turn_id"],
                "controller_epoch": row["controller_epoch"],
                "control_version": next_control_version,
            }
        except Exception:
            claim_session.rollback()
            raise
        finally:
            claim_session.close()

    def claim_text_media_playback(
        self,
        db: Any,
        *,
        debate_id: str,
        turn_id: str,
        expected_control_version: int,
        controller_epoch: str,
    ) -> bool:
        result = db.execute(
            text(
                "UPDATE playback_states SET status='waiting_next', cursor_ms=0, "
                "audio_duration_ms=0, server_started_at=NULL, updated_at=:now "
                "WHERE debate_id=:debate_id AND current_turn_id=:turn_id "
                "AND status='ready' AND mode='live' "
                "AND control_version=:version AND controller_epoch=:epoch "
                "AND pending_action IS NULL AND pending_ticket_hash IS NULL "
                "AND pending_media_command_id IS NULL "
                "AND EXISTS (SELECT 1 FROM debate_turns AS t "
                "JOIN debates AS d ON d.id=t.debate_id "
                "JOIN jobs AS j ON j.turn_id=t.id AND j.debate_id=d.id "
                "WHERE t.id=:turn_id AND t.debate_id=:debate_id AND d.status='running' "
                "AND t.generation_status='final_ready' AND t.preparation_stage='ready' "
                "AND t.publication_status='unpublished' "
                "AND t.safe_error_code='tts_voice_unavailable' "
                "AND trim(COALESCE(t.speech,''))<>'' AND t.audio_file_id IS NULL "
                "AND t.audio_duration_ms=0 AND j.state='completed' "
                "AND j.cancellation_generation=d.cancellation_generation "
                "AND NOT EXISTS (SELECT 1 FROM json_each(t.predecessor_turn_ids_json) AS p "
                "LEFT JOIN debate_turns AS prior ON prior.id=p.value AND prior.debate_id=d.id "
                "WHERE prior.id IS NULL OR prior.publication_status<>'public'))"
            ),
            {
                "debate_id": debate_id,
                "turn_id": turn_id,
                "version": expected_control_version,
                "epoch": controller_epoch,
                "now": _now(),
            },
        )
        return int(getattr(result, "rowcount", 0)) == 1

    def claim_media_prepare(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        controller_epoch: str,
        turn_id: str,
        ticket_hash: str,
        command_id: str,
        action: str,
        audio_duration_ms: int,
        expected_audio_relative_path: str | None = None,
        expected_audio_sha256: str | None = None,
        expected_audio_size_bytes: int | None = None,
    ) -> bool:
        """Claim the single durable media ticket slot with a fresh writer.

        Ticket bytes are issued by the service before this CAS so a losing
        request can revoke its just-issued token.  This transaction binds the
        winning hash, command/action, duration and controller epoch to the
        authoritative PlaybackState; no request-local cache decides whether a
        second service may prepare another ticket.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            columns = self._columns(claim_session, "playback_states")
            required = {
                "pending_action",
                "pending_ticket_hash",
                "pending_media_command_id",
                "audio_duration_ms",
            }
            if not required.issubset(columns):
                claim_session.rollback()
                return False
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid AS claim_rowid FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "JOIN debate_turns AS t ON t.id=ps.current_turn_id "
                    "AND t.debate_id=ps.debate_id "
                    "JOIN courses AS c ON c.id=d.course_id "
                    "JOIN stored_files AS sf ON sf.id=t.audio_file_id "
                    "WHERE ps.debate_id=:debate_id AND ps.status='ready' "
                    "AND ((:action='replay' AND ps.mode='replay') OR "
                    "(:action<>'replay' AND ps.mode='live')) "
                    "AND ps.current_turn_id=:turn_id "
                    "AND ps.control_version=:expected_control_version "
                    "AND ps.controller_epoch=:controller_epoch "
                    "AND ps.pending_action IS NULL "
                    "AND ps.pending_ticket_hash IS NULL "
                    "AND ps.pending_media_command_id IS NULL "
                    "AND ((:action='replay' AND d.status IN ('debate_finished','completed')) OR "
                    "(:action<>'replay' AND d.status='running')) "
                    "AND t.generation_status='final_ready' "
                    "AND t.audio_file_id IS NOT NULL "
                    "AND t.audio_duration_ms IS NOT NULL "
                    "AND t.audio_duration_ms > 0 "
                    "AND t.audio_duration_ms=:audio_duration_ms "
                    "AND (c.current_audio_debate_id=d.id OR "
                    "json_extract(d.rule_snapshot_json, '$.turn_protocol')='segments_v2') "
                    "AND sf.kind='debate_audio' AND sf.state='active' "
                    "AND sf.relative_path=:expected_audio_relative_path "
                    "AND sf.sha256=:expected_audio_sha256 "
                    "AND sf.size=:expected_audio_size_bytes"
                ),
                {
                    "debate_id": debate_id,
                    "turn_id": turn_id,
                    "expected_control_version": expected_control_version,
                    "controller_epoch": controller_epoch,
                    "action": action,
                    "audio_duration_ms": audio_duration_ms,
                    "expected_audio_relative_path": expected_audio_relative_path,
                    "expected_audio_sha256": expected_audio_sha256,
                    "expected_audio_size_bytes": expected_audio_size_bytes,
                },
            ).first()
            if candidate is None:
                claim_session.rollback()
                return False
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET pending_action=:action, "
                    "pending_ticket_hash=:ticket_hash, "
                    "pending_media_command_id=:command_id, "
                    "audio_duration_ms=:audio_duration_ms, updated_at=:updated_at "
                    "WHERE rowid=:claim_rowid AND debate_id=:debate_id "
                    "AND status='ready' AND current_turn_id=:turn_id "
                    "AND ((:action='replay' AND mode='replay') OR "
                    "(:action<>'replay' AND mode='live')) "
                    "AND control_version=:expected_control_version "
                    "AND controller_epoch=:controller_epoch "
                    "AND pending_action IS NULL AND pending_ticket_hash IS NULL "
                    "AND pending_media_command_id IS NULL"
                ),
                {
                    "action": action,
                    "ticket_hash": ticket_hash,
                    "command_id": command_id,
                    "audio_duration_ms": audio_duration_ms,
                    "updated_at": _now(),
                    "claim_rowid": candidate[0],
                    "debate_id": debate_id,
                    "turn_id": turn_id,
                    "expected_control_version": expected_control_version,
                    "controller_epoch": controller_epoch,
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def release_media_prepare(
        self,
        *,
        debate_id: str,
        expected_control_version: int,
        controller_epoch: str,
        turn_id: str,
        ticket_hash: str,
        command_id: str,
    ) -> bool:
        """Release one media claim after a post-claim byte validation fails.

        The release is a fresh writer CAS.  A request Session must not clear
        a claim through a stale WAL snapshot while a browser acknowledgement
        may already be racing; matching the complete pending identity keeps
        the losing cleanup from touching a newer claim.
        """

        if self.session_factory is None:
            return False
        claim_session = self.session_factory()
        try:
            begin_immediate(claim_session)
            columns = self._columns(claim_session, "playback_states")
            required = {
                "pending_action",
                "pending_ticket_hash",
                "pending_media_command_id",
                "audio_duration_ms",
            }
            if not required.issubset(columns):
                claim_session.rollback()
                return False
            changed = claim_session.execute(
                text(
                    "UPDATE playback_states SET pending_action=NULL, "
                    "pending_ticket_hash=NULL, pending_media_command_id=NULL, "
                    "audio_duration_ms=0, updated_at=:updated_at "
                    "WHERE debate_id=:debate_id AND status='ready' "
                    "AND current_turn_id=:turn_id "
                    "AND control_version=:expected_control_version "
                    "AND controller_epoch=:controller_epoch "
                    "AND pending_ticket_hash=:ticket_hash "
                    "AND pending_media_command_id=:command_id"
                ),
                {
                    "updated_at": _now(),
                    "debate_id": debate_id,
                    "turn_id": turn_id,
                    "expected_control_version": expected_control_version,
                    "controller_epoch": controller_epoch,
                    "ticket_hash": ticket_hash,
                    "command_id": command_id,
                },
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                claim_session.rollback()
                return False
            claim_session.commit()
            return True
        except OperationalError:
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    @staticmethod
    def _has_table_in_session(session: Any, table_name: str) -> bool:
        return SqlPlaybackRepository._has_table(session, table_name)

    def save_turn_text(
        self,
        db: Any,
        turn: SqlRow,
        prepared: PreparedTurn,
        *,
        claim_token: str | None,
        generation: int,
        debate_status: str,
    ) -> bool:
        """Persist validated teacher text before the separate audio request."""

        if claim_token is None or prepared.transcript_hash is None:
            return False
        from app.modules.debates.source_lineage import receipt_scope_is_valid

        for source in prepared.source_receipts:
            if not receipt_scope_is_valid(db, turn, source):
                return False
            chunk = db.execute(
                text("SELECT text FROM knowledge_chunks WHERE id=:id AND snapshot_id=:snapshot"),
                {"id": source.chunk_id, "snapshot": source.snapshot_id},
            ).first()
            if chunk is None or str(chunk[0]) != source.text:
                return False
        changed = db.execute(
            text(
                "UPDATE debate_turns SET speech=:speech, structured_json=:structured, "
                "retrieval_status=:retrieval, grounding_mode=:grounding, "
                "retrieval_receipts_json=:receipts, evidence_trace_json=:trace, updated_at=:now "
                "WHERE id=:id AND generation_status='running' "
                "AND transcript_hash=:transcript_hash AND predecessor_turn_ids_json=:predecessors "
                "AND cutoff_turn_index=:cutoff "
                "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status=:status AND debates.cancellation_generation=:generation) "
                "AND EXISTS (SELECT 1 FROM jobs WHERE jobs.turn_id=debate_turns.id "
                "AND jobs.state='running' AND jobs.claim_token=:claim "
                "AND jobs.cancellation_generation=:generation)"
            ),
            {
                "id": str(turn.id),
                "speech": prepared.speech,
                "structured": json.dumps(
                    dict(prepared.structured), sort_keys=True, separators=(",", ":")
                ),
                "retrieval": prepared.retrieval_status,
                "grounding": prepared.grounding_mode,
                "receipts": json.dumps(
                    [
                        {key: value for key, value in asdict(source).items() if value is not None}
                        for source in prepared.source_receipts
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "trace": json.dumps(
                    [dict(item) for item in prepared.evidence_trace], separators=(",", ":")
                ),
                "now": _now(),
                "transcript_hash": prepared.transcript_hash,
                "predecessors": json.dumps(prepared.predecessor_turn_ids, separators=(",", ":")),
                "cutoff": prepared.cutoff_turn_index,
                "status": debate_status,
                "generation": generation,
                "claim": claim_token,
            },
        )
        return int(getattr(changed, "rowcount", 0)) == 1

    def fence_audio_promotion(
        self,
        db: Any,
        debate: SqlRow,
        turn: SqlRow,
        claim_token: str | None,
        generation: int,
    ) -> bool:
        """Hold the SQL writer fence while staged audio becomes canonical.

        The no-op Job update deliberately remains uncommitted.  The caller
        must promote the already staged bytes and finish ``mark_turn_ready``
        on this Session before releasing the writer lock, so Delete Voice or
        Stop cannot clear the turn between the final check and the rename.
        """

        if claim_token is None:
            return False
        turn_id = str(turn.id)
        debate_id = str(debate.id)
        changed = db.execute(
            text(
                "UPDATE jobs SET updated_at=updated_at WHERE debate_id=:debate_id "
                "AND turn_id=:turn_id AND operation='debate_turn_prepare' "
                "AND state='running' AND claim_token=:claim_token "
                "AND cancellation_generation=:generation "
                "AND EXISTS (SELECT 1 FROM debates WHERE id=:debate_id "
                "AND status IN ('draft','running') "
                "AND cancellation_generation=:generation)"
            ),
            {
                "debate_id": debate_id,
                "turn_id": turn_id,
                "claim_token": claim_token,
                "generation": generation,
            },
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            return False
        current = (
            db.execute(
                text(
                    "SELECT t.generation_status, t.speech, t.structured_json, "
                    "t.transcript_hash, t.predecessor_turn_ids_json, t.cutoff_turn_index, "
                    "d.status, d.cancellation_generation FROM debate_turns AS t "
                    "JOIN debates AS d ON d.id=t.debate_id "
                    "WHERE t.id=:turn_id AND t.debate_id=:debate_id"
                ),
                {"turn_id": turn_id, "debate_id": debate_id},
            )
            .mappings()
            .first()
        )
        if current is None or str(current["generation_status"]) != "running":
            return False
        if (
            str(current["status"]) not in {"draft", "running"}
            or int(current["cancellation_generation"] or 0) != generation
        ):
            return False
        for name in (
            "speech",
            "structured_json",
            "transcript_hash",
            "predecessor_turn_ids_json",
            "cutoff_turn_index",
        ):
            expected = _row_value(turn, name)
            if expected is not None and current[name] != expected:
                return False
        return True

    def mark_turn_ready(
        self,
        db: Any,
        turn: SqlRow,
        prepared: PreparedTurn,
        audio: AudioMetadata | None,
        *,
        generation: int,
        attempt: int,
        claim_token: str | None = None,
        debate_status: str = "running",
        audio_error_code: str | None = None,
    ) -> bool:
        # None retains validated text when no TTS voice is configured; publication
        # still goes through the same job, generation and accepted-LLM fences.
        # The Debate this turn belongs to has to be in the state the caller
        # prepared it for: ``running`` for a live lesson, ``draft`` for one
        # warming ahead of its lesson. Naming it rather than assuming it is
        # what keeps a pre-warm from ever writing into a running Debate.
        if debate_status not in {"running", "draft"}:
            return False
        if (
            audio is None
            and audio_error_code is not None
            and audio_error_code not in TTS_UNAVAILABLE_CODES
        ):
            return False
        if audio is not None and audio_error_code is not None:
            return False
        predecessor_json = json.dumps(prepared.predecessor_turn_ids, separators=(",", ":"))
        if (
            prepared.transcript_hash is None
            or prepared.cutoff_turn_index is None
            or prepared.generation_attempt not in {1, 2}
        ):
            return False
        receipt_payload: list[dict[str, Any]] = []
        from app.modules.debates.source_lineage import receipt_scope_is_valid

        for source in prepared.source_receipts:
            if (
                not receipt_scope_is_valid(db, turn, source)
                or source.rank < 1
                or source.rank > 6
                or len(source.query_hash) != 64
            ):
                return False
            chunk = db.execute(
                text(
                    "SELECT text FROM knowledge_chunks WHERE id=:chunk_id "
                    "AND snapshot_id=:snapshot_id"
                ),
                {"chunk_id": source.chunk_id, "snapshot_id": source.snapshot_id},
            ).first()
            if chunk is None or str(chunk[0]) != source.text:
                return False
            receipt_value: dict[str, Any] = {
                "snapshot_id": source.snapshot_id,
                "query_kind": source.query_kind,
                "query_hash": source.query_hash,
                "threshold_key": source.threshold_key,
                "source_filename": source.source_filename,
                "chunk_id": source.chunk_id,
                "evidence_id": source.evidence_id,
                "rank": source.rank,
                "score": source.score,
                "text": source.text,
            }
            for key in (
                "source_document_id",
                "source_start_offset",
                "source_end_offset",
                "excerpt",
                "query_id",
            ):
                value = getattr(source, key, None)
                if value is not None:
                    receipt_value[key] = value
            receipt_payload.append(receipt_value)
        columns = self._columns(db, "debate_turns")
        values: dict[str, Any] = {
            "generation_status": "final_ready",
            "preparation_stage": "ready",
            "publication_status": "unpublished",
            "speech": prepared.speech,
            "structured_json": json.dumps(
                dict(prepared.structured), sort_keys=True, separators=(",", ":")
            ),
            "retrieval_status": prepared.retrieval_status,
            "grounding_mode": prepared.grounding_mode,
            "retrieval_receipts_json": json.dumps(
                receipt_payload,
                sort_keys=True,
                separators=(",", ":"),
            ),
            # New hosts may expose this optional column (or persist the same
            # immutable rows in a dedicated trace table).  Filtering against
            # the reflected columns below keeps pre-trace databases and old
            # replay rows byte-compatible while making the trace part of the
            # final-ready UPDATE transaction when available.
            "evidence_trace_json": json.dumps(
                [dict(item) for item in prepared.evidence_trace],
                sort_keys=True,
                separators=(",", ":"),
            ),
            "word_count": prepared.word_count or len(prepared.speech.split()),
            "attempt": prepared.generation_attempt,
            "audio_file_id": None,
            "audio_duration_ms": (
                audio.duration_ms
                if audio is not None
                else (0 if audio_error_code is None else None)
            ),
            "audio_relative_path": getattr(audio, "relative_path", None),
            "audio_sha256": getattr(audio, "sha256", None),
            "actual_tts_voice_kind": prepared.actual_voice_kind if audio is not None else None,
            "actual_tts_voice_profile_id": (
                prepared.actual_voice_profile_id if audio is not None else None
            ),
            "safe_error_code": audio_error_code
            or ("tts_voice_unavailable" if audio is None else None),
            "updated_at": _now(),
        }
        # The M10 schema stores retained bytes through StoredFile and keeps
        # only its UUID on DebateTurn.  Create that row in the same transaction
        # before pointing the turn at it; if the host adapter has a direct
        # relative-path column too, both values are written consistently.
        if audio is None:
            values["audio_file_id"] = None
        audio_file_id = getattr(audio, "file_id", None) or str(uuid4())
        stored_columns = self._columns(db, "stored_files")
        if audio is not None and audio.relative_path and stored_columns and "id" in stored_columns:
            stored_values: dict[str, Any] = {
                "id": audio_file_id,
                "kind": "debate_audio",
                "relative_path": audio.relative_path,
                "sha256": getattr(audio, "sha256", ""),
                "size": getattr(audio, "size_bytes", 0),
                "size_bytes": getattr(audio, "size_bytes", 0),
                "state": "active",
                "created_at": _now(),
                "updated_at": _now(),
            }
            stored_filtered = {
                key: value for key, value in stored_values.items() if key in stored_columns
            }
            names = ", ".join(stored_filtered)
            binds = ", ".join(f":{key}" for key in stored_filtered)
            db.execute(
                text(f"INSERT INTO stored_files ({names}) VALUES ({binds})"),
                stored_filtered,
            )
            values["audio_file_id"] = audio_file_id
        filtered = {key: value for key, value in values.items() if key in columns}
        if not filtered or "id" not in turn.values:
            return False
        filtered["id"] = str(turn.id)
        filtered.update(
            {
                "generation": generation,
                "debate_status": debate_status,
                "claim_token": claim_token,
                "claimed_attempt": 1,
                "expected_predecessors": predecessor_json,
                "expected_transcript_hash": prepared.transcript_hash,
                "expected_cutoff": prepared.cutoff_turn_index,
            }
        )
        where = (
            "id=:id AND generation_status='running' AND preparation_stage='generation' "
            "AND attempt=:claimed_attempt "
            "AND predecessor_turn_ids_json=:expected_predecessors "
            "AND transcript_hash=:expected_transcript_hash "
            "AND cutoff_turn_index=:expected_cutoff "
            "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
            "AND debates.status=:debate_status "
            "AND debates.cancellation_generation=:generation) "
            # A live lesson may only ready the playing turn or the one after
            # it. A draft has no playing turn, so its ordering is the fact that
            # every earlier turn is already made -- the same rule, stated for a
            # Debate that nothing is advancing through.
            + (
                "AND EXISTS (SELECT 1 FROM playback_states "
                "JOIN debate_turns AS current_turn "
                "ON current_turn.id=playback_states.current_turn_id "
                "WHERE playback_states.debate_id=debate_turns.debate_id "
                "AND debate_turns.turn_index IN "
                "(current_turn.turn_index,current_turn.turn_index+1)) "
                if debate_status == "running"
                else "AND NOT EXISTS (SELECT 1 FROM debate_turns AS earlier "
                "WHERE earlier.debate_id=debate_turns.debate_id "
                "AND earlier.turn_index < debate_turns.turn_index "
                "AND earlier.generation_status NOT IN "
                "('final_ready','ready','completed')) "
            )
            + "AND EXISTS (SELECT 1 FROM jobs WHERE jobs.debate_id=debate_turns.debate_id "
            "AND jobs.turn_id=debate_turns.id AND jobs.state='running' "
            "AND jobs.claim_token=:claim_token "
            "AND jobs.cancellation_generation=:generation "
            "AND jobs.attempt=:claimed_attempt)"
        )
        assignments = ", ".join(
            f"{key}=:{key}"
            for key in filtered
            if key
            not in {
                "id",
                "generation",
                "debate_status",
                "claim_token",
                "claimed_attempt",
                "expected_predecessors",
                "expected_transcript_hash",
                "expected_cutoff",
            }
        )
        if claim_token is None:
            return False
        result = db.execute(
            text(f"UPDATE debate_turns SET {assignments} WHERE {where}"),
            filtered,
        )
        # Persist only server-assigned sources.  M11 normally performs this
        # receipt validation before invoking playback; this narrow adapter
        # accepts a source only when it carries a concrete chunk UUID and
        # immutable snapshot metadata, never a provider filename from the LLM.
        accepted = int(getattr(result, "rowcount", 0)) == 1
        if not accepted:
            if values.get("audio_file_id") is not None:
                db.execute(
                    text("DELETE FROM stored_files WHERE id=:id"),
                    {"id": values["audio_file_id"]},
                )
            return False
        if self._has_table(db, "turn_sources"):
            source_columns = self._columns(db, "turn_sources")
            db.execute(
                text("DELETE FROM turn_sources WHERE turn_id=:turn_id"), {"turn_id": str(turn.id)}
            )
            receipts: tuple[Any, ...] = prepared.source_receipts or tuple(
                source for source in prepared.sources if getattr(source, "chunk_id", None)
            )
            for fallback_rank, source in enumerate(receipts, start=1):
                chunk_id = getattr(source, "chunk_id", None)
                if chunk_id is None:
                    continue
                if prepared.source_receipts:
                    from app.modules.debates.source_lineage import receipt_scope_is_valid

                    if not receipt_scope_is_valid(db, turn, source):
                        raise ValueError("turn source has no valid evidence origin")
                source_values = {
                    "id": str(uuid4()),
                    "turn_id": str(turn.id),
                    "participant_id": str(turn.values.get("participant_id", "")),
                    "snapshot_id": str(
                        getattr(source, "snapshot_id", turn.values.get("knowledge_snapshot_id", ""))
                    ),
                    "chunk_id": str(chunk_id),
                    "evidence_id": getattr(
                        source, "evidence_id", f"source-{turn.id}-{fallback_rank}"
                    ),
                    "source_filename": source.source_filename,
                    "rank": int(getattr(source, "rank", fallback_rank)),
                    "score": float(getattr(source, "score", 0.0)),
                    "created_at": _now(),
                }
                source_filtered = {
                    key: value for key, value in source_values.items() if key in source_columns
                }
                names = ", ".join(source_filtered)
                binds = ", ".join(f":{key}" for key in source_filtered)
                if (
                    source_filtered.get("participant_id")
                    and source_filtered.get("snapshot_id")
                    and self._has_table(db, "knowledge_chunks")
                    and db.execute(
                        text(
                            "SELECT 1 FROM knowledge_chunks WHERE id=:chunk_id "
                            "AND snapshot_id=:snapshot_id"
                        ),
                        {
                            "chunk_id": source_filtered.get("chunk_id"),
                            "snapshot_id": source_filtered.get("snapshot_id"),
                        },
                    ).first()
                    is not None
                ):
                    db.execute(
                        text(f"INSERT INTO turn_sources ({names}) VALUES ({binds})"),
                        source_filtered,
                    )
        if claim_token is not None:
            completed = db.execute(
                text(
                    "UPDATE jobs SET state='completed', attempt=:attempt, updated_at=:updated_at "
                    "WHERE debate_id=:debate_id AND turn_id=:turn_id AND state='running' "
                    "AND claim_token=:claim_token AND cancellation_generation=:generation"
                ),
                {
                    "attempt": prepared.generation_attempt or attempt,
                    "updated_at": _now(),
                    "debate_id": str(turn.values.get("debate_id", "")),
                    "turn_id": str(turn.id),
                    "claim_token": claim_token,
                    "generation": generation,
                },
            )
            if int(getattr(completed, "rowcount", 0)) != 1:
                raise RuntimeError("turn completion lost its claimed job fence")
        handoff = prepared.llm_publication
        if handoff is not None:
            commit = SqlLLMPublication(db).commit_llm_turn_success
            commit(
                operation_id=str(getattr(handoff, "operation_id", "")),
                turn_id=str(getattr(handoff, "turn_id", turn.id)),
                debate_id=str(getattr(handoff, "debate_id", turn.values.get("debate_id", ""))),
                request_hash=str(getattr(handoff, "request_hash", "")),
                operation=getattr(handoff, "operation", None),
                stage=getattr(handoff, "stage", None),
                usage=getattr(handoff, "usage", None),
                result=getattr(handoff, "result", None),
                final_ready=getattr(handoff, "final_ready", None),
                evidence_trace=getattr(handoff, "evidence_trace", ()),
                recovery_input=getattr(handoff, "recovery_input", None),
            )
        return accepted

    def ensure_turn_jobs(self, db: Any, debate: SqlRow, turns: list[SqlRow]) -> None:
        """Create only the initial durable job; later turns are claimed on demand."""

        if not self._has_table(db, "jobs"):
            return
        ordered = sorted(turns, key=lambda item: int(item.turn_index))
        if ordered:
            self._ensure_turn_job(db, debate, ordered[0])

    @staticmethod
    def _ensure_turn_job(db: Any, debate: SqlRow, turn: SqlRow) -> None:
        key = f"{debate.id}:{turn.id}"
        timestamp = _now()
        db.execute(
            text(
                "INSERT OR IGNORE INTO jobs "
                "(id, document_id, debate_id, turn_id, idempotency_key, claim_token, "
                "cancellation_generation, operation, state, safe_error_code, attempt, "
                "created_at, updated_at) VALUES "
                "(:id, NULL, :debate_id, :turn_id, :key, NULL, :generation, "
                "'debate_turn_prepare', 'pending', NULL, 0, :created_at, :updated_at)"
            ),
            {
                "id": str(uuid4()),
                "debate_id": str(debate.id),
                "turn_id": str(turn.id),
                "key": key,
                "generation": int(debate.cancellation_generation or 0),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def ensure_turn_job(self, db: Any, debate: SqlRow, turn: SqlRow) -> None:
        """Persist an on-demand next-turn job before exposing its preparing state."""

        self._ensure_turn_job(db, debate, turn)

    def claim_turn_job(
        self,
        db: Any,
        debate: SqlRow,
        turn: SqlRow,
        *,
        cancellation_generation: int,
    ) -> str | None:
        self._ensure_turn_job(db, debate, turn)
        token = str(uuid4())
        changed = db.execute(
            text(
                "UPDATE jobs SET state='running', claim_token=:token, safe_error_code=NULL, "
                "updated_at=:updated_at "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id AND state='pending' "
                "AND (safe_error_code IS NULL OR safe_error_code NOT LIKE 'tts_%') "
                "AND cancellation_generation=:generation"
            ),
            {
                "token": token,
                "updated_at": _now(),
                "debate_id": str(debate.id),
                "turn_id": str(turn.id),
                "generation": cancellation_generation,
            },
        )
        return token if int(getattr(changed, "rowcount", 0)) == 1 else None

    def authorize_pending_tts_retry(
        self, db: Any, debate: SqlRow, turn: SqlRow, *, code: str
    ) -> bool:
        """Clear only an explicitly requested live audio retry, preserving text."""

        if code not in _TTS_DEFERRED_CODES:
            return False
        params = {
            "debate_id": str(debate.id),
            "turn_id": str(turn.id),
            "generation": int(debate.cancellation_generation or 0),
            "code": code,
        }
        job = db.execute(
            text(
                "UPDATE jobs SET safe_error_code=NULL WHERE debate_id=:debate_id "
                "AND turn_id=:turn_id AND state='pending' AND safe_error_code=:code "
                "AND cancellation_generation=:generation "
                "AND EXISTS (SELECT 1 FROM debates WHERE id=:debate_id AND status='running')"
            ),
            params,
        )
        if int(getattr(job, "rowcount", 0)) != 1:
            return False
        changed = db.execute(
            text(
                "UPDATE debate_turns SET safe_error_code=NULL WHERE id=:turn_id "
                "AND debate_id=:debate_id AND generation_status='pending' "
                "AND safe_error_code=:code"
            ),
            params,
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            db.rollback()
            return False
        return True

    def mark_turn_prewarming(
        self,
        db: Any,
        turn: SqlRow,
        *,
        cancellation_generation: int,
        claim_token: str | None,
        fence: PreparedGenerationFence | None = None,
    ) -> bool:
        """Claim one turn of a draft that is warming ahead of its lesson.

        Deliberately a separate statement from ``mark_turn_running`` rather
        than a relaxed version of it. That one encodes the live fence -- the
        Debate is running and this turn is adjacent to the playing one -- and
        that fence governs who may advance playback. A draft has no playing
        turn to be adjacent to, so widening the live condition to cover it
        would quietly weaken the rule it exists to state. Every other guard is
        identical: the same prefix fence, the same attempt, and the same
        durable job claim.
        """

        if claim_token is None or fence is None or fence.attempt not in {1, 2}:
            return False
        predecessor_json = json.dumps(fence.predecessor_turn_ids, separators=(",", ":"))
        cached_segment = _segment_fence_matches(turn, fence)
        transcript_guard = (
            "AND transcript_hash=:transcript_hash "
            "AND speech=:cached_speech AND structured_json=:cached_structured "
            if cached_segment
            else "AND transcript_hash IS NULL "
        )
        changed = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='running', "
                "preparation_stage='generation', transcript_hash=:transcript_hash, "
                "attempt=:attempt, safe_error_code=NULL, updated_at=:updated_at "
                "WHERE id=:turn_id AND generation_status='pending' "
                + transcript_guard
                + "AND attempt=:attempt "
                "AND predecessor_turn_ids_json=:predecessors "
                "AND cutoff_turn_index=:cutoff "
                "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status='draft' "
                "AND debates.cancellation_generation=:generation) "
                "AND NOT EXISTS (SELECT 1 FROM debate_turns AS earlier "
                "WHERE earlier.debate_id=debate_turns.debate_id "
                "AND earlier.turn_index < debate_turns.turn_index "
                "AND earlier.generation_status NOT IN ('final_ready','ready','completed')) "
                "AND EXISTS (SELECT 1 FROM jobs WHERE turn_id=:turn_id AND state='running' "
                "AND claim_token=:claim_token AND cancellation_generation=:generation)"
            ),
            {
                "updated_at": _now(),
                "turn_id": str(turn.id),
                "claim_token": claim_token,
                "generation": cancellation_generation,
                "transcript_hash": fence.transcript_hash,
                "cached_speech": _row_value(turn, "speech", ""),
                "cached_structured": _row_value(turn, "structured_json", ""),
                "attempt": fence.attempt,
                "predecessors": predecessor_json,
                "cutoff": fence.cutoff_turn_index,
            },
        )
        accepted = int(getattr(changed, "rowcount", 0)) == 1
        if accepted:
            job = db.execute(
                text(
                    "UPDATE jobs SET attempt=:attempt, updated_at=:updated_at "
                    "WHERE turn_id=:turn_id AND state='running' "
                    "AND claim_token=:claim_token AND cancellation_generation=:generation"
                ),
                {
                    "attempt": fence.attempt,
                    "updated_at": _now(),
                    "turn_id": str(turn.id),
                    "claim_token": claim_token,
                    "generation": cancellation_generation,
                },
            )
            if int(getattr(job, "rowcount", 0)) != 1:
                raise RuntimeError("turn claim lost its durable job fence")
        return accepted

    def mark_turn_running(
        self,
        db: Any,
        turn: SqlRow,
        *,
        cancellation_generation: int,
        claim_token: str | None,
        fence: PreparedGenerationFence | None = None,
    ) -> bool:
        if claim_token is None or fence is None or fence.attempt not in {1, 2}:
            return False
        predecessor_json = json.dumps(fence.predecessor_turn_ids, separators=(",", ":"))
        cached_segment = _segment_fence_matches(turn, fence)
        transcript_guard = (
            "AND transcript_hash=:transcript_hash "
            "AND speech=:cached_speech AND structured_json=:cached_structured "
            if cached_segment
            else "AND transcript_hash IS NULL "
        )
        changed = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='running', "
                "preparation_stage='generation', transcript_hash=:transcript_hash, "
                "attempt=:attempt, safe_error_code=NULL, updated_at=:updated_at "
                "WHERE id=:turn_id AND generation_status='pending' "
                + transcript_guard
                + "AND attempt=:attempt "
                "AND predecessor_turn_ids_json=:predecessors "
                "AND cutoff_turn_index=:cutoff "
                "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status='running' "
                "AND debates.cancellation_generation=:generation) "
                "AND EXISTS (SELECT 1 FROM playback_states "
                "JOIN debate_turns AS current_turn "
                "ON current_turn.id=playback_states.current_turn_id "
                "WHERE playback_states.debate_id=debate_turns.debate_id "
                "AND debate_turns.turn_index IN "
                "(current_turn.turn_index,current_turn.turn_index+1)) "
                "AND EXISTS (SELECT 1 FROM jobs WHERE turn_id=:turn_id AND state='running' "
                "AND claim_token=:claim_token AND cancellation_generation=:generation)"
            ),
            {
                "updated_at": _now(),
                "turn_id": str(turn.id),
                "claim_token": claim_token,
                "generation": cancellation_generation,
                "transcript_hash": fence.transcript_hash,
                "cached_speech": _row_value(turn, "speech", ""),
                "cached_structured": _row_value(turn, "structured_json", ""),
                "attempt": fence.attempt,
                "predecessors": predecessor_json,
                "cutoff": fence.cutoff_turn_index,
            },
        )
        accepted = int(getattr(changed, "rowcount", 0)) == 1
        if accepted:
            job = db.execute(
                text(
                    "UPDATE jobs SET attempt=:attempt, updated_at=:updated_at "
                    "WHERE turn_id=:turn_id AND state='running' "
                    "AND claim_token=:claim_token AND cancellation_generation=:generation"
                ),
                {
                    "attempt": fence.attempt,
                    "updated_at": _now(),
                    "turn_id": str(turn.id),
                    "claim_token": claim_token,
                    "generation": cancellation_generation,
                },
            )
            if int(getattr(job, "rowcount", 0)) != 1:
                raise RuntimeError("turn claim lost its durable job fence")
        return accepted

    def fail_prewarm_turn(
        self, db: Any, turn: SqlRow, *, claim_token: str | None, code: str
    ) -> bool:
        """Keep a failed Preview visible without terminating its draft."""

        if claim_token is None:
            return False
        changed = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='failed', "
                "safe_error_code=:code, updated_at=:updated_at "
                "WHERE id=:turn_id AND generation_status='running' "
                "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status='draft') "
                "AND EXISTS (SELECT 1 FROM jobs WHERE jobs.turn_id=debate_turns.id "
                "AND jobs.operation='debate_turn_prepare' AND jobs.state='running' "
                "AND jobs.claim_token=:claim_token)"
            ),
            {
                "updated_at": _now(),
                "turn_id": str(turn.id),
                "claim_token": claim_token,
                "code": code,
            },
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            return False
        self.fail_turn_job(db, turn, claim_token, code)
        return True

    def reset_prewarm_turn(
        self,
        db: Any,
        turn: SqlRow,
        *,
        claim_token: str | None,
        cancellation_generation: int,
    ) -> bool:
        """Release only this owner's unfinished draft claim, preserving saved text."""

        if claim_token is None or cancellation_generation < 0:
            return False
        parameters = {
            "updated_at": _now(),
            "turn_id": str(turn.id),
            "debate_id": str(turn.debate_id),
            "claim_token": claim_token,
            "generation": cancellation_generation,
        }
        # save_turn_text commits before TTS without mutating the worker's old
        # projection. Only the durable row can tell us which fence to preserve.
        stored = (
            db.execute(
                text("SELECT * FROM debate_turns WHERE id=:turn_id AND debate_id=:debate_id"),
                parameters,
            )
            .mappings()
            .first()
        )
        if stored is None:
            return False
        cached_segment = _has_cached_segment_fence(stored)
        transcript_update = "" if cached_segment else "transcript_hash=NULL, "
        parameters.update(
            existing_transcript_hash=stored["transcript_hash"],
            existing_speech=stored["speech"],
            existing_structured=stored["structured_json"],
            allowed_codes=("", *TTS_UNAVAILABLE_CODES) if cached_segment else ("",),
        )
        provider_guard = ""
        if self._has_table(db, "provider_operations"):
            accepted_guard = "p.state='accepted'"
            if self._has_table(db, "llm_accepted_stages") and self._has_table(
                db, "llm_recovery_inputs"
            ):
                accepted_guard += (
                    " AND NOT EXISTS (SELECT 1 FROM llm_accepted_stages AS s "
                    "JOIN llm_recovery_inputs AS r ON r.operation_id=s.operation_id "
                    "WHERE s.operation_id=p.id AND s.turn_id=:turn_id "
                    "AND r.turn_id=s.turn_id AND r.attempt_no=s.attempt_no "
                    "AND s.attempt_no=p.attempt_no)"
                )
            provider_guard = (
                "AND NOT EXISTS (SELECT 1 FROM provider_operations AS p "
                "WHERE p.scope_id=:debate_id AND p.logical_item_id=:turn_id "
                "AND p.provider_operation='llm_debate_turn' "
                "AND (p.state IN ('sending','acceptance_unknown') OR (" + accepted_guard + "))) "
            )
        changed = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                + transcript_update
                + "preparation_stage='generation', safe_error_code=NULL, updated_at=:updated_at "
                "WHERE id=:turn_id AND debate_id=:debate_id "
                "AND generation_status IN ('pending','running') "
                "AND COALESCE(safe_error_code,'') IN :allowed_codes "
                "AND transcript_hash IS :existing_transcript_hash "
                "AND speech IS :existing_speech AND structured_json IS :existing_structured "
                + "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status='draft' AND debates.cancellation_generation=:generation) "
                "AND EXISTS (SELECT 1 FROM jobs WHERE jobs.turn_id=:turn_id "
                "AND jobs.debate_id=:debate_id AND jobs.operation='debate_turn_prepare' "
                "AND jobs.state='running' AND jobs.claim_token=:claim_token "
                "AND jobs.cancellation_generation=:generation "
                "AND COALESCE(jobs.safe_error_code,'') IN :allowed_codes) " + provider_guard
            ).bindparams(bindparam("allowed_codes", expanding=True)),
            parameters,
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            return False
        job = db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=NULL, "
                "updated_at=:updated_at WHERE turn_id=:turn_id AND debate_id=:debate_id "
                "AND operation='debate_turn_prepare' AND state='running' "
                "AND claim_token=:claim_token AND cancellation_generation=:generation "
                "AND COALESCE(safe_error_code,'') IN :allowed_codes "
                "AND EXISTS (SELECT 1 FROM debate_turns AS t JOIN debates AS d "
                "ON d.id=t.debate_id WHERE t.id=:turn_id AND t.debate_id=:debate_id "
                "AND t.generation_status='pending' AND d.status='draft' "
                "AND d.cancellation_generation=:generation) " + provider_guard
            ).bindparams(bindparam("allowed_codes", expanding=True)),
            parameters,
        )
        if int(getattr(job, "rowcount", 0)) != 1:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            return False
        return True

    def retry_draft_segment_turn(
        self,
        db: Any,
        debate: SqlRow,
        turn: SqlRow,
        *,
        expected_control_version: int,
        code: str,
    ) -> bool:
        """CAS one safe Preview retry back to the preparation queue.

        This is the SQL half of the teacher's draft retry command.  It moves
        the exact failed/pending preparation Job and turn together while
        advancing the draft PlaybackState control version.  A cached segment
        TTS failure keeps its validated text/fence; provider-not-sent and a
        verified accepted-stage continuation clear the old transcript fence so
        preparation recomputes it from the current immutable prefix.

        The method does not commit.  On a failed multi-table CAS it rolls back
        its own writes so callers can safely return a stale-control response.
        """

        if expected_control_version < 0:
            return False
        retry_codes = {
            "provider_confirmation_required",
            "provider_not_sent",
            "turn_generation_failed",
        } | _TTS_DEFERRED_CODES
        if code not in retry_codes or not self._has_table(db, "playback_states"):
            return False
        debate_id = str(debate.id)
        turn_id = str(turn.id)
        if (
            code == "turn_generation_failed"
            and (
                debate_id,
                turn_id,
            )
            not in self.recoverable_llm_turns(db)
            and not self.unattempted_llm_turn(db, debate_id, turn_id)
        ):
            return False
        cached_segment = code in _TTS_DEFERRED_CODES and _has_cached_segment_fence(turn)
        if code in _TTS_DEFERRED_CODES and not cached_segment:
            return False
        timestamp = _now()

        state = db.execute(
            text(
                "UPDATE playback_states SET control_version=control_version+1, "
                "updated_at=:updated_at WHERE debate_id=:debate_id AND status='preparing' "
                "AND mode='live' AND current_turn_id IS NULL "
                "AND control_version=:expected_control_version "
                "AND EXISTS (SELECT 1 FROM debates AS d WHERE d.id=:debate_id "
                "AND d.status='draft' AND json_valid(d.rule_snapshot_json) "
                "AND json_extract(d.rule_snapshot_json, '$.turn_protocol')='segments_v2')"
            ),
            {
                "updated_at": timestamp,
                "debate_id": debate_id,
                "expected_control_version": expected_control_version,
            },
        )
        if int(getattr(state, "rowcount", 0)) != 1:
            return False

        turn_sql = (
            "UPDATE debate_turns SET generation_status='pending', "
            "preparation_stage='generation', "
            + ("" if cached_segment else "transcript_hash=NULL, ")
            + "safe_error_code=NULL, updated_at=:updated_at "
            "WHERE id=:turn_id AND debate_id=:debate_id "
            "AND generation_status IN ('pending','failed','turn_generation_failed') "
            "AND publication_status='unpublished' AND safe_error_code=:code "
            "AND CAST(round_no AS INTEGER) < CAST(COALESCE(json_extract(("
            "SELECT rule_snapshot_json FROM debates WHERE id=:debate_id), "
            "'$.round_count'), 2) AS INTEGER) "
            "AND NOT EXISTS (SELECT 1 FROM debate_turns AS earlier "
            "WHERE earlier.debate_id=debate_turns.debate_id "
            "AND earlier.turn_index < debate_turns.turn_index "
            "AND earlier.generation_status NOT IN ('final_ready','ready','completed')) "
            + (
                "AND transcript_hash=:existing_transcript_hash "
                "AND speech=:existing_speech AND structured_json=:existing_structured "
                if cached_segment
                else ""
            )
        )
        changed = db.execute(
            text(turn_sql),
            {
                "updated_at": timestamp,
                "turn_id": turn_id,
                "debate_id": debate_id,
                "code": code,
                "existing_transcript_hash": _row_value(turn, "transcript_hash", ""),
                "existing_speech": _row_value(turn, "speech", ""),
                "existing_structured": _row_value(turn, "structured_json", ""),
            },
        )
        if int(getattr(changed, "rowcount", 0)) != 1:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            return False
        job = db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=NULL, "
                "updated_at=:updated_at WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND operation='debate_turn_prepare' AND state IN ('pending','failed') "
                "AND safe_error_code=:code"
            ),
            {
                "updated_at": timestamp,
                "debate_id": debate_id,
                "turn_id": turn_id,
                "code": code,
            },
        )
        if int(getattr(job, "rowcount", 0)) != 1:
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
            return False
        return True

    def defer_turn_job(
        self,
        db: Any,
        debate: SqlRow,
        turn: SqlRow,
        claim_token: str | None,
        code: str,
    ) -> bool:
        """Atomically park one provider-gated turn without terminating its Debate."""

        if claim_token is None or code not in {
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
        }:
            return False
        preserve_segment_fence = code in _TTS_DEFERRED_CODES and _has_cached_segment_fence(turn)
        timestamp = _now()
        job = db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL, safe_error_code=:code, "
                "updated_at=:updated_at WHERE debate_id=:debate_id AND turn_id=:turn_id "
                "AND operation='debate_turn_prepare' AND state='running' "
                "AND claim_token=:claim_token AND cancellation_generation=:generation"
            ),
            {
                "code": code,
                "updated_at": timestamp,
                "debate_id": str(debate.id),
                "turn_id": str(turn.id),
                "claim_token": claim_token,
                "generation": int(debate.cancellation_generation or 0),
            },
        )
        if int(getattr(job, "rowcount", 0)) != 1:
            return False
        deferred = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', "
                + ("" if preserve_segment_fence else "transcript_hash=NULL, ")
                + "safe_error_code=:code, updated_at=:updated_at "
                "WHERE id=:turn_id AND debate_id=:debate_id "
                "AND generation_status='running' AND publication_status='unpublished' "
                + (
                    "AND transcript_hash=:existing_transcript_hash "
                    "AND speech=:existing_speech AND structured_json=:existing_structured "
                    if preserve_segment_fence
                    else ""
                )
                + "AND EXISTS (SELECT 1 FROM debates WHERE debates.id=debate_turns.debate_id "
                "AND debates.status='running' "
                "AND debates.cancellation_generation=:generation)"
            ),
            {
                "code": code,
                "updated_at": timestamp,
                "debate_id": str(debate.id),
                "turn_id": str(turn.id),
                "generation": int(debate.cancellation_generation or 0),
                "existing_transcript_hash": _row_value(turn, "transcript_hash", ""),
                "existing_speech": _row_value(turn, "speech", ""),
                "existing_structured": _row_value(turn, "structured_json", ""),
            },
        )
        if int(getattr(deferred, "rowcount", 0)) != 1:
            raise RuntimeError("provider-gated turn lost its durable job fence")
        return True

    def fail_turn_job(self, db: Any, turn: SqlRow, claim_token: str | None, code: str) -> None:
        if claim_token is None:
            return
        db.execute(
            text(
                "UPDATE jobs SET state='failed', safe_error_code=:code, updated_at=:updated_at "
                "WHERE turn_id=:turn_id AND state='running' AND claim_token=:claim_token"
            ),
            {
                "code": code,
                "updated_at": _now(),
                "turn_id": str(turn.id),
                "claim_token": claim_token,
            },
        )

    def publish_turn(self, db: Any, turn: SqlRow) -> bool:
        columns = self._columns(db, "debate_turns")
        if "publication_status" not in columns:
            return False
        current = (
            db.execute(
                text(
                    "SELECT publication_status, structured_json, participant_id, debate_id "
                    "FROM debate_turns WHERE id=:id"
                ),
                {"id": str(turn.id)},
            )
            .mappings()
            .first()
        )
        if current is None:
            return False
        if str(current["publication_status"]) == "public":
            return True
        result = db.execute(
            text(
                "UPDATE debate_turns SET publication_status='public', public_at=:public_at, "
                "updated_at=:updated_at WHERE id=:id AND publication_status='unpublished' "
                "AND generation_status='final_ready'"
            ),
            {"id": str(turn.id), "public_at": _now(), "updated_at": _now()},
        )
        if int(getattr(result, "rowcount", 0)) != 1:
            return False
        try:
            structured = json.loads(str(current["structured_json"]))
        except (TypeError, ValueError):
            raise RuntimeError("final-ready turn has invalid structured data") from None
        if not isinstance(structured, dict):
            raise RuntimeError("final-ready turn has invalid structured data")
        if structured.get("schema_version") == "segment_turn_v2":
            from app.modules.debates.generation.segments import load_stored_segment_turn_result

            load_stored_segment_turn_result(structured)
            # Paragraphs express the position themselves; do not invent the
            # retired position-summary/history fields during publication.
            return True
        participant_id = str(current["participant_id"])
        participant = (
            db.execute(
                text(
                    "SELECT current_position_summary, current_stance, stance_mode "
                    "FROM debate_participants WHERE id=:participant_id"
                ),
                {"participant_id": participant_id},
            )
            .mappings()
            .first()
        )
        if participant is None:
            raise RuntimeError("turn participant is unavailable")
        after_summary = str(structured.get("position_summary", "")).strip()
        if not after_summary:
            raise RuntimeError("final-ready turn has no position summary")
        participant_updates: dict[str, Any] = {
            "participant_id": participant_id,
            "summary": after_summary,
            "updated_at": _now(),
        }
        stance_assignment = ""
        new_stance = structured.get("new_stance")
        if new_stance is not None:
            if str(participant["stance_mode"]) == "open":
                raise RuntimeError("open participant cannot publish an enum stance")
            participant_updates["stance"] = str(new_stance)
            stance_assignment = ", current_stance=:stance"
        db.execute(
            text(
                "UPDATE debate_participants SET current_position_summary=:summary, "
                f"updated_at=:updated_at{stance_assignment} WHERE id=:participant_id"
            ),
            participant_updates,
        )
        influencing_turn_id = structured.get("rebuttal_target_turn_id")
        if influencing_turn_id is None and isinstance(structured.get("engagements"), list):
            first_engagement = next(
                (
                    item
                    for item in structured["engagements"]
                    if isinstance(item, dict) and item.get("target_turn_id")
                ),
                None,
            )
            if isinstance(first_engagement, dict):
                influencing_turn_id = first_engagement.get("target_turn_id")
        if influencing_turn_id is not None:
            same_debate = db.execute(
                text("SELECT 1 FROM debate_turns WHERE id=:turn_id AND debate_id=:debate_id"),
                {
                    "turn_id": str(influencing_turn_id),
                    "debate_id": str(current["debate_id"]),
                },
            ).first()
            if same_debate is None:
                raise RuntimeError("position influence crossed the debate boundary")
        evidence_ids = structured.get("used_evidence_id", [])
        if not evidence_ids and isinstance(structured.get("key_claims"), list):
            evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for claim in structured["key_claims"]
                    if isinstance(claim, dict)
                    for evidence_id in claim.get("used_evidence_ids", [])
                    if isinstance(evidence_id, str) and evidence_id
                )
            )
        if not isinstance(evidence_ids, list):
            evidence_ids = []
        update_type = str(structured.get("position_update", "unchanged"))
        # PositionHistory predates mutual-learning's more descriptive enum.
        # Preserve the exact new value in structured_json while writing the
        # closest compatible audit projection into its frozen legacy column.
        update_type = {
            "clarified": "refined",
            "extended": "refined",
            "qualified": "partial_concession",
            "partially_revised": "partial_concession",
            "substantially_revised": "reframed",
        }.get(update_type, update_type)
        db.execute(
            text(
                "INSERT INTO position_history "
                "(id, participant_id, turn_id, before_summary, after_summary, update_type, "
                "reason, influencing_turn_id, influencing_evidence_ids_json, created_at) "
                "VALUES (:id, :participant_id, :turn_id, :before_summary, :after_summary, "
                ":update_type, :reason, :influencing_turn_id, :evidence_ids, :created_at)"
            ),
            {
                "id": str(uuid4()),
                "participant_id": participant_id,
                "turn_id": str(turn.id),
                "before_summary": str(participant["current_position_summary"] or ""),
                "after_summary": after_summary,
                "update_type": update_type,
                "reason": str(structured.get("position_update_reason") or ""),
                "influencing_turn_id": (
                    str(influencing_turn_id) if influencing_turn_id is not None else None
                ),
                "evidence_ids": json.dumps(evidence_ids, separators=(",", ":")),
                "created_at": _now(),
            },
        )
        return True

    def fail_turn_and_debate(self, db: Any, debate: SqlRow, turn: SqlRow, code: str) -> None:
        if self._has_table(db, "debate_turns"):
            columns = self._columns(db, "debate_turns")
            updates = {
                "generation_status": "turn_generation_failed",
                "safe_error_code": code,
                "updated_at": _now(),
            }
            filtered = {key: value for key, value in updates.items() if key in columns}
            if filtered:
                filtered["id"] = str(turn.id)
                assignments = ", ".join(f"{key}=:{key}" for key in filtered if key != "id")
                db.execute(
                    text(f"UPDATE debate_turns SET {assignments} WHERE id=:id"),
                    filtered,
                )
        debate.status = "failed"
        self.save_debate(db, debate)

    def mark_jobs_interrupted(self, db: Any, debate: SqlRow, code: str) -> None:
        if not self._has_table(db, "jobs"):
            return
        columns = self._columns(db, "jobs")
        if "debate_id" not in columns:
            return
        updates = {"state": "interrupted"}
        if "safe_error_code" in columns:
            updates["safe_error_code"] = code
        assignments = ", ".join(f"{key}=:{key}" for key in updates)
        db.execute(
            text(
                f"UPDATE jobs SET {assignments} WHERE debate_id=:debate_id "
                "AND state IN ('pending','running')"
            ),
            {**updates, "debate_id": str(debate.id)},
        )

    def teacher_allowed(self, db: Any, debate: SqlRow, context: Any) -> bool:
        try:
            value = db.execute(
                text(
                    "SELECT 1 FROM course_members "
                    "WHERE course_id=:course_id AND user_id=:user_id AND role='teacher'"
                ),
                {"course_id": str(debate.course_id), "user_id": str(context.user.id)},
            ).first()
        except Exception:
            return False
        return value is not None

    def course_running(self, db: Any, course_id: str, except_debate_id: str | None = None) -> bool:
        if not self._has_table(db, "debates"):
            return False
        where = "course_id=:course_id AND status='running' AND deleted_at IS NULL"
        params: dict[str, Any] = {"course_id": course_id}
        if except_debate_id is not None:
            where += " AND id!=:except_id"
            params["except_id"] = except_debate_id
        return (
            db.execute(text(f"SELECT 1 FROM debates WHERE {where} LIMIT 1"), params).first()
            is not None
        )

    def running_debate_ids(self, db: Any) -> tuple[str, ...]:
        """Every lesson still marked running, for startup to drive again."""

        if not self._has_table(db, "debates"):
            return ()
        return tuple(
            str(row[0])
            for row in db.execute(
                text(
                    "SELECT id FROM debates WHERE status IN ('running','paused') "
                    "AND deleted_at IS NULL"
                )
            ).all()
        )

    def running_debate(self, db: Any, course_id: str, except_debate_id: str | None = None) -> Any:
        """Which debate holds this course's running slot, so the UI can name it.

        ``course_running`` answers only yes/no, so a teacher who could not
        start a debate was told something else was running and left to find it
        themselves. Recovery is only usable if the thing to recover is named
        where the failure happened.
        """

        if not self._has_table(db, "debates"):
            return None
        where = "course_id=:course_id AND status IN ('running','paused') AND deleted_at IS NULL"
        params: dict[str, Any] = {"course_id": course_id}
        if except_debate_id is not None:
            where += " AND id!=:except_id"
            params["except_id"] = except_debate_id
        row = db.execute(
            text(f"SELECT id, topic FROM debates WHERE {where} LIMIT 1"), params
        ).first()
        return None if row is None else {"id": str(row[0]), "topic": str(row[1] or "")}

    def current_audio_debate_id(self, db: Any, course_id: str) -> str | None:
        try:
            value = db.execute(
                text("SELECT current_audio_debate_id FROM courses WHERE id=:course_id"),
                {"course_id": course_id},
            ).scalar_one_or_none()
            return cast(str | None, value)
        except Exception:
            return None

    def set_current_audio_debate(self, db: Any, course_id: str, debate_id: str | None) -> bool:
        try:
            result = db.execute(
                text("UPDATE courses SET current_audio_debate_id=:debate_id WHERE id=:course_id"),
                {"course_id": course_id, "debate_id": debate_id},
            )
        except Exception:
            return False
        return int(getattr(result, "rowcount", 0)) == 1

    def retained_audio_file(self, db: Any, debate: SqlRow, turn: SqlRow) -> SqlRow | None:
        """Read the StoredFile facts bound to one DebateTurn.

        Replay must not trust the process-local AudioStore index.  This query
        deliberately joins through the exact DebateTurn/debate identity so a
        file UUID copied from another debate cannot authorize playback.
        """

        if not self._has_table(db, "stored_files") or not self._has_table(db, "debate_turns"):
            return None
        file_id = getattr(turn, "audio_file_id", None)
        if not file_id:
            return None
        return _row(
            db.execute(
                text(
                    "SELECT sf.* FROM stored_files AS sf "
                    "JOIN debate_turns AS dt ON dt.audio_file_id=sf.id "
                    "WHERE dt.id=:turn_id AND dt.debate_id=:debate_id "
                    "AND dt.audio_file_id=:file_id"
                ),
                {
                    "turn_id": str(turn.id),
                    "debate_id": str(debate.id),
                    "file_id": str(file_id),
                },
            ),
            db,
        )

    def mark_debate_audio_deleted(self, db: Any, debate_id: str) -> int:
        """Mark only this debate's retained audio rows deleted after cleanup.

        Text/source/turn rows remain untouched.  The update is intentionally
        keyed by both ``kind`` and the turn's debate so an audio swap cannot
        alter Markdown, voice previews, or another debate's files.
        """

        if not self._has_table(db, "stored_files") or not self._has_table(db, "debate_turns"):
            return 0
        changed = db.execute(
            text(
                "UPDATE stored_files SET state='deleted', updated_at=:updated_at "
                "WHERE kind='debate_audio' AND state <> 'deleted' "
                "AND id IN (SELECT audio_file_id FROM debate_turns "
                "WHERE debate_id=:debate_id AND audio_file_id IS NOT NULL)"
            ),
            {"debate_id": debate_id, "updated_at": _now()},
        )
        return int(getattr(changed, "rowcount", 0))

    def commit_start_state(
        self,
        db: Any,
        debate: SqlRow,
        *,
        expected_revision: int,
        expected_audio_pointer: str | None,
        journal_id: str | None,
    ) -> bool:
        """CAS draft, course pointer and typed journal inside one transaction."""

        if expected_audio_pointer is None:
            pointer_where = "current_audio_debate_id IS NULL"
            parameters: dict[str, Any] = {
                "course_id": str(debate.course_id),
                "new_debate_id": str(debate.id),
            }
        else:
            pointer_where = "current_audio_debate_id=:expected_audio_pointer"
            parameters = {
                "course_id": str(debate.course_id),
                "new_debate_id": str(debate.id),
                "expected_audio_pointer": expected_audio_pointer,
            }
        pointer = db.execute(
            text(
                "UPDATE courses SET current_audio_debate_id=:new_debate_id "
                f"WHERE id=:course_id AND {pointer_where}"
            ),
            parameters,
        )
        if int(getattr(pointer, "rowcount", 0)) != 1:
            return False
        timestamp = _now()
        started = db.execute(
            text(
                "UPDATE debates SET status='running', started_at=:started_at, "
                "updated_at=:updated_at WHERE id=:debate_id AND status='draft' "
                "AND revision=:expected_revision"
            ),
            {
                "started_at": timestamp,
                "updated_at": timestamp,
                "debate_id": str(debate.id),
                "expected_revision": expected_revision,
            },
        )
        if int(getattr(started, "rowcount", 0)) != 1:
            return False
        if journal_id is not None:
            from app.modules.debates.setup.audio_swap import (
                AudioSwapState,
                transition_audio_swap,
            )

            transition_audio_swap(
                db,
                journal_id,
                expected_state=AudioSwapState.STAGED,
                target_state=AudioSwapState.COMMITTED,
            )
        debate.status = "running"
        debate.started_at = timestamp
        debate.updated_at = timestamp
        return True

    def terminate_retained_playback(self, db: Any, debate_id: str) -> dict[str, Any] | None:
        """Revoke an old retained Debate's live/replay authority in the start tx."""

        row = (
            db.execute(
                text(
                    "SELECT current_turn_id, control_version, controller_epoch, "
                    "controller_owner_connection, status FROM playback_states "
                    "WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        new_version = int(row["control_version"] or 0) + 1
        db.execute(
            text(
                "UPDATE playback_states SET status='completed', mode='live', cursor_ms=0, "
                "control_version=:control_version, controller_epoch=NULL, "
                "controller_owner_connection=NULL, server_started_at=NULL, "
                "replay_scope=NULL, replay_index=NULL, "
                "pending_action=NULL, pending_ticket_hash=NULL, "
                "pending_media_command_id=NULL, audio_duration_ms=0, "
                "updated_at=:updated_at WHERE debate_id=:debate_id"
            ),
            {
                "control_version": new_version,
                "updated_at": _now(),
                "debate_id": debate_id,
            },
        )
        if "replay_turn_ids_json" in self._columns(db, "playback_states"):
            db.execute(
                text(
                    "UPDATE playback_states SET replay_turn_ids_json='[]' "
                    "WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            )
        return {
            "turn_id": row["current_turn_id"],
            "control_version": new_version,
            "controller_epoch": row["controller_epoch"],
            "controller_connection_id": row["controller_owner_connection"],
            "previous_status": row["status"],
        }

    def public_turn(self, db: Any, debate: SqlRow, turn_id: str) -> SqlRow | None:
        if not self._has_table(db, "debate_turns"):
            return None
        row = _row(
            db.execute(
                text(
                    "SELECT * FROM debate_turns WHERE id=:id AND debate_id=:debate_id "
                    "AND publication_status IN ('public','published')"
                ),
                {"id": turn_id, "debate_id": str(debate.id)},
            ),
            db,
        )
        return row

    def append_event_tx(
        self,
        db: Any,
        *,
        debate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> EventRecord:
        """CAS the debate watermark and insert one event in the same DB tx."""

        if not self._has_table(db, "debate_events") or not self._has_table(db, "debates"):
            raise RuntimeError("Debate event tables are not installed")
        result = db.execute(
            text(
                "UPDATE debates SET last_sequence=last_sequence+1, updated_at=:updated_at "
                "WHERE id=:debate_id"
            ),
            {"debate_id": debate_id, "updated_at": _now()},
        )
        if int(getattr(result, "rowcount", 0)) != 1:
            raise RuntimeError("debate event watermark could not be advanced")
        sequence_value = db.execute(
            text("SELECT last_sequence FROM debates WHERE id=:debate_id"),
            {"debate_id": debate_id},
        ).scalar_one()
        sequence = int(sequence_value)
        from .events import validate_event_payload

        validated = validate_event_payload(event_type, payload)
        event = EventRecord(
            event_id=str(uuid4()),
            debate_id=debate_id,
            sequence=sequence,
            event_type=event_type,
            event_version=1,
            occurred_at=_now(),
            payload=validated,
        )
        db.execute(
            text(
                "INSERT INTO debate_events "
                "(id, debate_id, sequence, event_type, event_version, "
                "payload_json, occurred_at) VALUES "
                "(:id, :debate_id, :sequence, :event_type, :event_version, "
                ":payload_json, :occurred_at)"
            ),
            {
                "id": event.event_id,
                "debate_id": debate_id,
                "sequence": sequence,
                "event_type": event_type,
                "event_version": 1,
                "payload_json": json.dumps(validated, sort_keys=True, separators=(",", ":")),
                "occurred_at": event.occurred_at,
            },
        )
        return event
