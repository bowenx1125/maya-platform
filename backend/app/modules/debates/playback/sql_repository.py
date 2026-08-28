"""SQLAlchemy repository adapter for the frozen Wave 2 tables.

M10 owns the declarative debate models and migration.  To keep ownership
isolated, this adapter uses a deliberately small SQL/text boundary and maps
rows to provider-neutral objects consumed by ``PlaybackService``.  It never
creates or alters tables; an absent Wave 2 migration is reported as an empty
repository, which keeps Wave 1 tests independent.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from .events import EventRecord
from .protocols import (
    PlaybackRepository,
    PreparedGenerationFence,
    PreparedTurn,
    ResolvedTurnVoice,
)


def _now() -> datetime:
    return datetime.now(UTC)


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
        """Revalidate the frozen custom voice, then system fallback, then Mock."""

        def ready_profile(profile_id: str | None, *, system_only: bool = False) -> bool:
            if not profile_id:
                return False
            scope_guard = " AND scope='system'" if system_only else ""
            row = db.execute(
                text(
                    "SELECT 1 FROM voice_profiles WHERE id=:profile_id AND status='ready'"
                    + scope_guard
                ),
                {"profile_id": profile_id},
            ).first()
            return row is not None

        frozen_id = getattr(participant, "effective_voice_profile_id", None)
        if getattr(
            participant, "effective_voice_kind", None
        ) == "platform_profile" and ready_profile(frozen_id):
            return ResolvedTurnVoice("platform_profile", str(frozen_id), str(frozen_id))
        fallback_id = getattr(settings, "fallback_voice_profile_id", None)
        if ready_profile(fallback_id, system_only=True):
            return ResolvedTurnVoice("platform_profile", str(fallback_id), str(fallback_id))
        selectors = (
            getattr(settings, "llm_provider", "mock"),
            getattr(settings, "embedding_provider", "mock"),
            getattr(settings, "tts_provider", "mock"),
            getattr(settings, "voice_provider", "mock"),
            getattr(settings, "translation_provider", None) or "mock",
        )
        if all(value == "mock" for value in selectors):
            return ResolvedTurnVoice("mock_sentinel", None, "mock")
        raise RuntimeError("no ready effective voice is available")

    def recover_startup(self, db: Any) -> tuple[str, ...]:
        """Fence interrupted work and revoke process-local playback authority."""

        if not self._has_table(db, "debates"):
            return ()
        affected: tuple[str, ...] = ()
        if self._has_table(db, "jobs"):
            affected = tuple(
                str(row[0])
                for row in db.execute(
                    text(
                        "SELECT DISTINCT debate_id FROM jobs WHERE debate_id IS NOT NULL "
                        "AND state IN ('pending','running')"
                    )
                ).all()
            )
            # A durable Job and its dependent Turn share one restart outcome.
            # Mark the Turn while the Job still has its pre-restart state;
            # otherwise the Debate would fail while its generation row still
            # looked resumable to later code and diagnostics.
            if self._has_table(db, "debate_turns"):
                db.execute(
                    text(
                        "UPDATE debate_turns SET generation_status='failed', "
                        "preparation_stage='failed', safe_error_code='process_restarted', "
                        "updated_at=:updated_at WHERE generation_status IN ('pending','running') "
                        "AND id IN (SELECT turn_id FROM jobs WHERE debate_id IS NOT NULL "
                        "AND turn_id IS NOT NULL AND state IN ('pending','running'))"
                    ),
                    {"updated_at": _now()},
                )
            db.execute(
                text(
                    "UPDATE jobs SET state='interrupted', safe_error_code='process_restarted', "
                    "updated_at=:updated_at WHERE debate_id IS NOT NULL "
                    "AND state IN ('pending','running')"
                ),
                {"updated_at": _now()},
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
                        "updated_at=:updated_at WHERE debate_id=:debate_id"
                    ),
                    {"debate_id": debate_id, "updated_at": _now()},
                )
        if self._has_table(db, "playback_states"):
            db.execute(
                text(
                    "UPDATE playback_states SET status='ready', cursor_ms=0, "
                    "control_version=control_version+1, controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "updated_at=:updated_at WHERE status IN ('playing','paused') "
                    "AND debate_id NOT IN (SELECT id FROM debates WHERE status='failed')"
                ),
                {"updated_at": _now()},
            )
            db.execute(
                text(
                    "UPDATE playback_states SET controller_epoch=NULL, "
                    "controller_owner_connection=NULL, server_started_at=NULL, "
                    "updated_at=:updated_at WHERE controller_epoch IS NOT NULL"
                ),
                {"updated_at": _now()},
            )
        return affected

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
    def _has_table(db: Any, table: str) -> bool:
        try:
            row = db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table},
            ).first()
        except Exception:
            return False
        return row is not None

    @staticmethod
    def _columns(db: Any, table: str) -> set[str]:
        try:
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
        return self._select_one(db, "debates", debate_id)

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
            raise RuntimeError("Wave 2 playback tables are not installed")
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
            "replay_scope": None,
            "replay_index": 0,
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
        """Atomically claim the live waiting successor transition.

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
                "updated_at=:updated_at WHERE debate_id=:debate_id "
                "AND status='waiting_next' AND mode='live' "
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
        }
        try:
            # Do not issue a SELECT (or any other statement) before this
            # explicit write transaction.  This is the WAL snapshot fix.
            claim_session.execute(text("BEGIN IMMEDIATE"))
            candidate = claim_session.execute(
                text(
                    "SELECT ps.rowid AS claim_rowid "
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
                    "AND ps.status='waiting_next' AND ps.mode='live' "
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
                    "AND prefix.publication_status <> 'public') "
                    "AND (SELECT COUNT(*) FROM debate_turns AS prefix_count "
                    "WHERE prefix_count.debate_id=ps.debate_id "
                    "AND prefix_count.turn_index < current_turn.turn_index) "
                    "= current_turn.turn_index "
                    "AND NOT EXISTS (SELECT 1 FROM debate_turns AS duplicate "
                    "WHERE duplicate.debate_id=ps.debate_id "
                    "AND duplicate.turn_index=current_turn.turn_index + 1 "
                    "AND duplicate.id <> successor.id) "
                    "AND successor.publication_status='unpublished' "
                    "AND successor.generation_status='final_ready' "
                    "AND successor.preparation_stage='ready' "
                    "AND trim(COALESCE(successor.speech, '')) <> '' "
                    "AND successor.audio_file_id IS NOT NULL "
                    "AND successor.audio_duration_ms IS NOT NULL "
                    "AND successor.audio_duration_ms > 0 "
                    "AND EXISTS (SELECT 1 FROM stored_files AS sf "
                    "WHERE sf.id=successor.audio_file_id AND sf.state='active') "
                    "AND successor.transcript_hash IS NOT NULL "
                    "AND trim(successor.transcript_hash) <> '' "
                    "AND successor.cutoff_turn_index=successor.turn_index - 1 "
                    "AND json_valid(successor.predecessor_turn_ids_json) "
                    "AND successor.predecessor_turn_ids_json = ("
                    "SELECT json_group_array(prefix_ids.id) FROM ("
                    "SELECT id FROM debate_turns "
                    "WHERE debate_id=ps.debate_id "
                    "AND turn_index < successor.turn_index "
                    "ORDER BY turn_index, id"
                    ") AS prefix_ids) "
                    "AND (successor.actual_tts_voice_kind IN "
                    "('platform_profile', 'mock_sentinel')) "
                    "AND ((successor.actual_tts_voice_kind='mock_sentinel' "
                    "AND successor.actual_tts_voice_profile_id IS NULL) OR "
                    "(successor.actual_tts_voice_kind='platform_profile' "
                    "AND successor.actual_tts_voice_profile_id IS NOT NULL)) "
                    "AND EXISTS (SELECT 1 FROM jobs AS successor_job "
                    "WHERE successor_job.debate_id=ps.debate_id "
                    "AND successor_job.turn_id=successor.id "
                    "AND successor_job.state='completed' "
                    "AND successor_job.cancellation_generation=d.cancellation_generation)"
                ),
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
                    "updated_at=:updated_at WHERE rowid=:claim_rowid "
                    "AND debate_id=:debate_id "
                    "AND status='waiting_next' AND mode='live' "
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
            claim_session.commit()
            return True
        except OperationalError:
            # Includes a bounded SQLite busy timeout.  The caller exposes the
            # same stale 409 as a losing CAS; it must never retry a provider or
            # leak a transient 503 for this teacher command.
            claim_session.rollback()
            return False
        finally:
            claim_session.close()

    def mark_turn_ready(
        self,
        db: Any,
        turn: SqlRow,
        prepared: PreparedTurn,
        audio: Any,
        *,
        generation: int,
        attempt: int,
        claim_token: str | None = None,
    ) -> bool:
        predecessor_json = json.dumps(prepared.predecessor_turn_ids, separators=(",", ":"))
        if (
            prepared.transcript_hash is None
            or prepared.cutoff_turn_index is None
            or prepared.generation_attempt not in {1, 2}
        ):
            return False
        receipt_payload: list[dict[str, Any]] = []
        for source in prepared.source_receipts:
            if (
                source.snapshot_id != str(turn.values.get("knowledge_snapshot_id", ""))
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
            receipt_payload.append(
                {
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
            )
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
            "word_count": prepared.word_count or len(prepared.speech.split()),
            "attempt": prepared.generation_attempt,
            "audio_duration_ms": getattr(audio, "duration_ms", None),
            "audio_relative_path": getattr(audio, "relative_path", None),
            "audio_sha256": getattr(audio, "sha256", None),
            "actual_tts_voice_kind": prepared.actual_voice_kind,
            "actual_tts_voice_profile_id": prepared.actual_voice_profile_id,
            "updated_at": _now(),
        }
        # The M10 schema stores retained bytes through StoredFile and keeps
        # only its UUID on DebateTurn.  Create that row in the same transaction
        # before pointing the turn at it; if the host adapter has a direct
        # relative-path column too, both values are written consistently.
        audio_file_id = getattr(audio, "file_id", None) or str(uuid4())
        stored_columns = self._columns(db, "stored_files")
        if getattr(audio, "relative_path", None) and stored_columns and "id" in stored_columns:
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
            "AND debates.status='running' "
            "AND debates.cancellation_generation=:generation) "
            "AND EXISTS (SELECT 1 FROM playback_states "
            "JOIN debate_turns AS current_turn ON current_turn.id=playback_states.current_turn_id "
            "WHERE playback_states.debate_id=debate_turns.debate_id "
            "AND debate_turns.turn_index IN (current_turn.turn_index,current_turn.turn_index+1)) "
            "AND EXISTS (SELECT 1 FROM jobs WHERE jobs.debate_id=debate_turns.debate_id "
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
                source_values = {
                    "id": str(uuid4()),
                    "turn_id": str(turn.id),
                    "participant_id": str(turn.values.get("participant_id", "")),
                    "snapshot_id": str(turn.values.get("knowledge_snapshot_id", "")),
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
                "UPDATE jobs SET state='running', claim_token=:token, updated_at=:updated_at "
                "WHERE debate_id=:debate_id AND turn_id=:turn_id AND state='pending' "
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
        changed = db.execute(
            text(
                "UPDATE debate_turns SET generation_status='running', "
                "preparation_stage='generation', transcript_hash=:transcript_hash, "
                "attempt=:attempt, updated_at=:updated_at "
                "WHERE id=:turn_id AND generation_status='pending' "
                "AND transcript_hash IS NULL AND attempt=:attempt "
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
        if not isinstance(evidence_ids, list):
            evidence_ids = []
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
                "update_type": str(structured.get("position_update", "unchanged")),
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
        where = "course_id=:course_id AND status='running'"
        params: dict[str, Any] = {"course_id": course_id}
        if except_debate_id is not None:
            where += " AND id!=:except_id"
            params["except_id"] = except_debate_id
        return (
            db.execute(text(f"SELECT 1 FROM debates WHERE {where} LIMIT 1"), params).first()
            is not None
        )

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
                "updated_at=:updated_at WHERE debate_id=:debate_id"
            ),
            {
                "control_version": new_version,
                "updated_at": _now(),
                "debate_id": debate_id,
            },
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
            raise RuntimeError("Wave 2 event tables are not installed")
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
