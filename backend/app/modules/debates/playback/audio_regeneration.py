"""Text-only audio regeneration for already accepted segment turns.

The service deliberately stops at the TTS boundary.  It reads the saved
``segment_turn_v2`` result and its server-owned receipts, claims a dedicated
Job, stages one unique WAV, then publishes it only when the Debate revision,
cancellation generation and Job claim are still current.  No LLM or
embedding code is reachable from this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.debates.generation.segments import (
    SegmentProtocolError,
    StoredSegmentTurnResult,
    load_stored_segment_turn_result,
)
from app.modules.debates.llm_params import frozen_voice_params
from app.modules.debates.playback.audio import (
    AudioMetadata,
    AudioStore,
    StagedAudio,
    audio_relative_path,
    audio_staging_relative_path,
    wav_duration_ms,
)
from app.modules.debates.playback.protocols import ResolvedTurnVoice
from app.providers.tts import TTSProvider, TTSProviderError

AUDIO_REGENERATION_OPERATION = "debate_turn_tts"
AUDIO_FILE_OPERATION = "debate_turn_tts"
AUDIO_REGENERATION_STALE_CODE = "audio_regeneration_stale"
AUDIO_REGENERATION_INTERRUPTED_CODE = "audio_regeneration_interrupted"
_REVISION_MARKER_PREFIX = "audio_regeneration_revision:"
_REGENERABLE_DEBATE_STATES = frozenset(
    {"draft", "running", "debate_finished", "completed", "stopped", "failed"}
)
_REGENERABLE_TURN_STATES = frozenset(
    {"pending", "running", "final_ready", "ready", "completed", "failed", "turn_generation_failed"}
)

AudioRegenerationStatus = Literal[
    "completed",
    "already_ready",
    "queued",
    "failed",
    "stale",
    "not_found",
]


class AudioRegenerationError(ValueError):
    """A safe, server-authored audio regeneration failure."""

    def __init__(self, message: str, *, code: str = "audio_regeneration_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CachedSegmentTurn:
    """Validated text and lineage loaded from one frozen SQL turn."""

    debate_id: str
    course_id: str
    turn_id: str
    participant_id: str
    revision: int
    cancellation_generation: int
    output_language: str
    speech: str
    structured_json: str
    structured: StoredSegmentTurnResult
    transcript_hash: str
    publication_status: str
    generation_status: str
    preparation_stage: str
    previous_audio_file_id: str | None
    effective_voice_kind: str
    effective_voice_profile_id: str | None
    receipt_ids: tuple[str, ...]
    turn_source_ids: tuple[str, ...]
    # The Debate's frozen rate / instruction / seed: a regenerated speech
    # sounds like the rest of its Debate.
    voice_params: dict[str, Any] = field(default_factory=dict)

    @property
    def speech_hash(self) -> str:
        return hashlib.sha256(self.speech.encode("utf-8")).hexdigest()

    @property
    def structured_hash(self) -> str:
        return hashlib.sha256(self.structured_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AudioRegenerationClaim:
    """The durable Job and FileOperation identities owned by one attempt."""

    operation_id: str
    file_operation_id: str
    claim_token: str
    idempotency_key: str
    debate_id: str
    turn_id: str
    expected_revision: int
    cancellation_generation: int
    speech_hash: str
    structured_hash: str
    transcript_hash: str
    speech: str
    structured_json: str
    previous_audio_file_id: str | None


@dataclass(frozen=True, slots=True)
class AudioRegenerationJob:
    """Small durable Job projection used for idempotent replay."""

    operation_id: str
    debate_id: str | None
    turn_id: str | None
    idempotency_key: str | None
    claim_token: str | None
    cancellation_generation: int | None
    state: str
    safe_error_code: str | None
    file_operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class AudioRegenerationResult:
    """API-ready result without speech, provider data or private paths."""

    status: AudioRegenerationStatus
    debate_id: str
    turn_id: str
    revision: int | None
    operation_id: str | None = None
    audio: AudioMetadata | None = None
    safe_error_code: str | None = None

    @property
    def audio_ready(self) -> bool:
        return self.audio is not None

    def to_public_dict(self) -> dict[str, object]:
        """Return the narrow route projection; callers add auth-specific URLs."""

        return {
            "operation": AUDIO_REGENERATION_OPERATION,
            "status": self.status,
            "debate_id": self.debate_id,
            "turn_id": self.turn_id,
            "revision": self.revision,
            "operation_id": self.operation_id,
            "audio_ready": self.audio_ready,
            "audio_duration_ms": self.audio.duration_ms if self.audio is not None else None,
            "safe_error_code": self.safe_error_code,
        }

    as_public_dict = to_public_dict


class AudioRegenerationRepository(Protocol):
    """Port implemented by the SQL adapter and small in-memory test doubles."""

    def load_cached_turn(self, db: Session, debate_id: str, turn_id: str) -> CachedSegmentTurn: ...

    def load_job(self, db: Session, idempotency_key: str) -> AudioRegenerationJob | None: ...

    def active_audio(
        self, db: Session, cached: CachedSegmentTurn, audio_store: AudioStore
    ) -> AudioMetadata | None: ...

    def claim(
        self,
        db: Session,
        cached: CachedSegmentTurn,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> AudioRegenerationClaim | None: ...

    def mark_staged(
        self, db: Session, claim: AudioRegenerationClaim, staged: StagedAudio
    ) -> bool: ...

    def claim_is_current(self, db: Session, claim: AudioRegenerationClaim) -> bool: ...

    def mark_promoted(self, db: Session, claim: AudioRegenerationClaim) -> bool: ...

    def commit_promotion(
        self,
        db: Session,
        claim: AudioRegenerationClaim,
        staged: StagedAudio,
        metadata: AudioMetadata,
        voice: ResolvedTurnVoice,
    ) -> bool: ...

    def canonical_is_unowned(self, db: Session, claim: AudioRegenerationClaim) -> bool: ...

    def fail(self, db: Session, claim: AudioRegenerationClaim, code: str) -> None: ...

    def recoverable(
        self, db: Session
    ) -> tuple[tuple[AudioRegenerationClaim, StagedAudio | None], ...]: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_provider_code(error: BaseException) -> str:
    code = getattr(error, "safe_code", None)
    if isinstance(code, str) and code.startswith("tts_"):
        return code
    return "tts_provider_error"


def _json_list(value: object, *, code: str) -> list[object]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AudioRegenerationError("saved audio lineage is invalid", code=code) from exc
    if not isinstance(parsed, list):
        raise AudioRegenerationError("saved audio lineage is invalid", code=code)
    return parsed


class SqlAudioRegenerationRepository:
    """Default SQL adapter for the bounded audio-only transaction."""

    @staticmethod
    def load_cached_turn(db: Session, debate_id: str, turn_id: str) -> CachedSegmentTurn:
        row = (
            db.execute(
                text(
                    "SELECT d.id AS debate_id, d.course_id, d.revision, "
                    "d.cancellation_generation, d.output_language, d.status AS debate_status, "
                    "d.rule_snapshot_json, "
                    "t.id AS turn_id, t.participant_id, t.generation_status, "
                    "t.publication_status, t.preparation_stage, t.speech, t.structured_json, "
                    "t.retrieval_receipts_json, t.transcript_hash, t.audio_file_id, "
                    "p.effective_voice_kind, "
                    "p.effective_voice_profile_id "
                    "FROM debates AS d JOIN debate_turns AS t ON t.debate_id=d.id "
                    "JOIN debate_participants AS p ON p.id=t.participant_id "
                    "AND p.debate_id=d.id WHERE d.id=:debate_id AND t.id=:turn_id"
                ),
                {"debate_id": debate_id, "turn_id": turn_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AudioRegenerationError("the Debate turn was not found", code="not_found")
        if str(row["debate_status"]) not in _REGENERABLE_DEBATE_STATES:
            raise AudioRegenerationError(
                "the Debate is not available for audio regeneration",
                code="debate_not_regenerable",
            )
        if str(row["generation_status"]) not in _REGENERABLE_TURN_STATES:
            raise AudioRegenerationError(
                "the turn has no retained final text",
                code="turn_text_unavailable",
            )
        speech = row["speech"]
        structured_json = row["structured_json"]
        transcript_hash = row["transcript_hash"]
        if (
            not isinstance(speech, str)
            or not speech.strip()
            or not isinstance(structured_json, str)
            or not structured_json
            or not isinstance(transcript_hash, str)
            or not transcript_hash
        ):
            raise AudioRegenerationError(
                "the turn has no retained final text", code="turn_text_unavailable"
            )
        try:
            structured_value = json.loads(structured_json)
            if not isinstance(structured_value, Mapping):
                raise ValueError("stored segment result is not an object")
            stored = load_stored_segment_turn_result(structured_value)
        except (TypeError, ValueError, json.JSONDecodeError, SegmentProtocolError) as exc:
            raise AudioRegenerationError(
                "the saved segment result is invalid", code="cached_segments_invalid"
            ) from exc
        if stored.speech != speech:
            raise AudioRegenerationError(
                "saved speech does not match its paragraphs", code="cached_segments_invalid"
            )
        output_language = row["output_language"]
        if not isinstance(output_language, str) or output_language not in {"en", "zh"}:
            raise AudioRegenerationError("the Debate language is invalid", code="language_invalid")
        snapshot_id = db.execute(
            text("SELECT knowledge_snapshot_id FROM debate_turns WHERE id=:turn_id"),
            {"turn_id": turn_id},
        ).scalar_one_or_none()
        if not isinstance(snapshot_id, str) or not snapshot_id:
            raise AudioRegenerationError(
                "turn snapshot is unavailable", code="receipt_scope_invalid"
            )

        receipt_rows = _json_list(row["retrieval_receipts_json"], code="receipt_invalid")
        from app.modules.debates.models import DebateTurn
        from app.modules.debates.source_lineage import receipt_scope_is_valid

        saved_turn = db.get(DebateTurn, turn_id)
        receipt_ids: list[str] = []
        for item in receipt_rows:
            if not isinstance(item, Mapping):
                raise AudioRegenerationError("saved receipts are invalid", code="receipt_invalid")
            evidence_id = item.get("evidence_id")
            receipt_snapshot = item.get("snapshot_id")
            chunk_id = item.get("chunk_id")
            receipt_text = item.get("text")
            if (
                not isinstance(evidence_id, str)
                or not evidence_id
                or not isinstance(receipt_snapshot, str)
                or saved_turn is None
                or not receipt_scope_is_valid(db, saved_turn, item)
                or not isinstance(chunk_id, str)
                or not isinstance(receipt_text, str)
            ):
                raise AudioRegenerationError("saved receipts are invalid", code="receipt_invalid")
            chunk = db.execute(
                text("SELECT snapshot_id, text FROM knowledge_chunks WHERE id=:chunk_id"),
                {"chunk_id": chunk_id},
            ).first()
            if chunk is None or str(chunk[0]) != receipt_snapshot or str(chunk[1]) != receipt_text:
                raise AudioRegenerationError(
                    "saved receipt crossed its snapshot", code="receipt_scope_invalid"
                )
            if evidence_id in receipt_ids:
                raise AudioRegenerationError(
                    "saved receipt IDs are duplicated", code="receipt_invalid"
                )
            receipt_ids.append(evidence_id)
        source_rows = (
            db.execute(
                text(
                    "SELECT evidence_id, participant_id, snapshot_id FROM turn_sources "
                    "WHERE turn_id=:turn_id"
                ),
                {"turn_id": turn_id},
            )
            .mappings()
            .all()
        )
        turn_source_ids: list[str] = []
        for source in source_rows:
            evidence_id = source["evidence_id"]
            if (
                not isinstance(evidence_id, str)
                or not evidence_id
                or str(source["participant_id"]) != str(row["participant_id"])
                or (
                    str(source["snapshot_id"]) != snapshot_id
                    and not any(
                        isinstance(item, Mapping)
                        and item.get("evidence_id") == evidence_id
                        and item.get("snapshot_id") == str(source["snapshot_id"])
                        for item in receipt_rows
                    )
                )
            ):
                raise AudioRegenerationError(
                    "turn source ownership is invalid", code="receipt_scope_invalid"
                )
            turn_source_ids.append(evidence_id)
        used_ids = stored.used_evidence_ids
        if not set(used_ids).issubset(receipt_ids) or not set(used_ids).issubset(turn_source_ids):
            raise AudioRegenerationError(
                "segment references do not belong to this turn", code="receipt_scope_invalid"
            )
        try:
            snapshot = json.loads(row["rule_snapshot_json"] or "{}")
        except ValueError:
            snapshot = {}
        voice_params = frozen_voice_params(
            snapshot if isinstance(snapshot, dict) else None, get_settings()
        )
        return CachedSegmentTurn(
            voice_params=voice_params,
            debate_id=str(row["debate_id"]),
            course_id=str(row["course_id"]),
            turn_id=str(row["turn_id"]),
            participant_id=str(row["participant_id"]),
            revision=int(row["revision"]),
            cancellation_generation=int(row["cancellation_generation"] or 0),
            output_language=output_language,
            speech=speech,
            structured_json=structured_json,
            structured=stored,
            transcript_hash=transcript_hash,
            publication_status=str(row["publication_status"]),
            generation_status=str(row["generation_status"]),
            preparation_stage=str(row["preparation_stage"]),
            previous_audio_file_id=(
                str(row["audio_file_id"]) if row["audio_file_id"] is not None else None
            ),
            effective_voice_kind=str(row["effective_voice_kind"]),
            effective_voice_profile_id=(
                str(row["effective_voice_profile_id"])
                if row["effective_voice_profile_id"] is not None
                else None
            ),
            receipt_ids=tuple(receipt_ids),
            turn_source_ids=tuple(turn_source_ids),
        )

    @staticmethod
    def load_job(db: Session, idempotency_key: str) -> AudioRegenerationJob | None:
        row = (
            db.execute(
                text(
                    "SELECT id, debate_id, turn_id, idempotency_key, claim_token, "
                    "cancellation_generation, state, safe_error_code FROM jobs "
                    "WHERE operation=:operation AND idempotency_key=:key"
                ),
                {"operation": AUDIO_REGENERATION_OPERATION, "key": idempotency_key},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        file_operation_id = db.execute(
            text(
                "SELECT id FROM file_operations WHERE operation_type=:operation "
                "AND request_id=:request_id ORDER BY created_at DESC LIMIT 1"
            ),
            {"operation": AUDIO_FILE_OPERATION, "request_id": str(row["id"])},
        ).scalar_one_or_none()
        return AudioRegenerationJob(
            operation_id=str(row["id"]),
            debate_id=str(row["debate_id"]) if row["debate_id"] is not None else None,
            turn_id=str(row["turn_id"]) if row["turn_id"] is not None else None,
            idempotency_key=(
                str(row["idempotency_key"]) if row["idempotency_key"] is not None else None
            ),
            claim_token=str(row["claim_token"]) if row["claim_token"] is not None else None,
            cancellation_generation=(
                int(row["cancellation_generation"])
                if row["cancellation_generation"] is not None
                else None
            ),
            state=str(row["state"]),
            safe_error_code=(
                str(row["safe_error_code"]) if row["safe_error_code"] is not None else None
            ),
            file_operation_id=(str(file_operation_id) if file_operation_id is not None else None),
        )

    @staticmethod
    def active_audio(
        db: Session, cached: CachedSegmentTurn, audio_store: AudioStore
    ) -> AudioMetadata | None:
        if cached.previous_audio_file_id is None:
            return None
        row = (
            db.execute(
                text(
                    "SELECT relative_path, sha256, size, state FROM stored_files "
                    "WHERE id=:file_id AND kind='debate_audio'"
                ),
                {"file_id": cached.previous_audio_file_id},
            )
            .mappings()
            .first()
        )
        if row is None or str(row["state"]) != "active":
            return None
        return audio_store.validate_file(
            course_id=cached.course_id,
            debate_id=cached.debate_id,
            turn_id=cached.turn_id,
            relative_path=str(row["relative_path"]),
            expected_sha256=str(row["sha256"]),
            expected_size_bytes=int(row["size"]),
        )

    @staticmethod
    def claim(
        db: Session,
        cached: CachedSegmentTurn,
        *,
        expected_revision: int,
        idempotency_key: str,
    ) -> AudioRegenerationClaim | None:
        existing = SqlAudioRegenerationRepository.load_job(db, idempotency_key)
        if existing is not None:
            return None
        operation_id = str(uuid4())
        file_operation_id = str(uuid4())
        claim_token = str(uuid4())
        now = _now()
        try:
            db.execute(
                text(
                    "INSERT INTO jobs (id, document_id, debate_id, turn_id, idempotency_key, "
                    "claim_token, cancellation_generation, operation, state, safe_error_code, "
                    "attempt, created_at, updated_at) VALUES "
                    "(:id, NULL, :debate_id, :turn_id, :key, :claim, :generation, "
                    ":operation, 'running', NULL, 1, :now, :now)"
                ),
                {
                    "id": operation_id,
                    "debate_id": cached.debate_id,
                    "turn_id": cached.turn_id,
                    "key": idempotency_key,
                    "claim": claim_token,
                    "generation": cached.cancellation_generation,
                    "operation": AUDIO_REGENERATION_OPERATION,
                    "now": now,
                },
            )
            db.commit()
            target = audio_relative_path(cached.course_id, cached.debate_id, cached.turn_id)
            source = audio_staging_relative_path(
                cached.course_id, cached.debate_id, cached.turn_id, file_operation_id
            )
            db.execute(
                text(
                    "INSERT INTO file_operations "
                    "(id, idempotency_record_id, operation_type, entity_id, request_id, "
                    "source_relative_path, target_relative_path, expected_sha256, state, "
                    "safe_error_code, created_at, updated_at) VALUES "
                    "(:id, NULL, :operation, :entity_id, :request_id, :source, :target, NULL, "
                    "'prepared', :revision_marker, :now, :now)"
                ),
                {
                    "id": file_operation_id,
                    "operation": AUDIO_FILE_OPERATION,
                    "entity_id": cached.debate_id,
                    "request_id": operation_id,
                    "source": source,
                    "target": target,
                    "revision_marker": f"{_REVISION_MARKER_PREFIX}{expected_revision}",
                    "now": now,
                },
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        return AudioRegenerationClaim(
            operation_id=operation_id,
            file_operation_id=file_operation_id,
            claim_token=claim_token,
            idempotency_key=idempotency_key,
            debate_id=cached.debate_id,
            turn_id=cached.turn_id,
            expected_revision=expected_revision,
            cancellation_generation=cached.cancellation_generation,
            speech_hash=cached.speech_hash,
            structured_hash=cached.structured_hash,
            transcript_hash=cached.transcript_hash,
            speech=cached.speech,
            structured_json=cached.structured_json,
            previous_audio_file_id=cached.previous_audio_file_id,
        )

    @staticmethod
    def mark_staged(db: Session, claim: AudioRegenerationClaim, staged: StagedAudio) -> bool:
        changed = db.execute(
            text(
                "UPDATE file_operations SET state='staged', source_relative_path=:source, "
                "target_relative_path=:target, expected_sha256=:sha, updated_at=:now "
                "WHERE id=:id AND request_id=:request_id AND operation_type=:operation "
                "AND state='prepared'"
            ),
            {
                "id": claim.file_operation_id,
                "request_id": claim.operation_id,
                "operation": AUDIO_FILE_OPERATION,
                "source": staged.relative_path,
                "target": staged.target_relative_path,
                "sha": staged.sha256,
                "now": _now(),
            },
        )
        accepted = int(getattr(changed, "rowcount", 0)) == 1
        if accepted:
            db.commit()
        else:
            db.rollback()
        return accepted

    @staticmethod
    def claim_is_current(db: Session, claim: AudioRegenerationClaim) -> bool:
        row = (
            db.execute(
                text(
                    "SELECT d.revision, d.cancellation_generation AS debate_generation, d.status, "
                    "t.generation_status, t.speech, t.structured_json, j.state, j.claim_token, "
                    "t.transcript_hash, j.cancellation_generation AS job_generation, j.attempt "
                    "FROM debates AS d "
                    "JOIN debate_turns AS t ON t.debate_id=d.id JOIN jobs AS j "
                    "ON j.debate_id=d.id AND j.turn_id=t.id WHERE d.id=:debate_id "
                    "AND t.id=:turn_id AND j.id=:operation_id"
                ),
                {
                    "debate_id": claim.debate_id,
                    "turn_id": claim.turn_id,
                    "operation_id": claim.operation_id,
                },
            )
            .mappings()
            .first()
        )
        if row is None:
            return False
        speech = row["speech"]
        structured = row["structured_json"]
        return (
            str(row["status"]) in _REGENERABLE_DEBATE_STATES
            and int(row["revision"]) == claim.expected_revision
            and int(row["debate_generation"] or 0) == claim.cancellation_generation
            and str(row["generation_status"]) in _REGENERABLE_TURN_STATES
            and str(row["state"]) == "running"
            and str(row["claim_token"] or "") == claim.claim_token
            and int(row["job_generation"] or 0) == claim.cancellation_generation
            and isinstance(speech, str)
            and hashlib.sha256(speech.encode("utf-8")).hexdigest() == claim.speech_hash
            and isinstance(structured, str)
            and hashlib.sha256(structured.encode("utf-8")).hexdigest() == claim.structured_hash
            and str(row["transcript_hash"] or "") == claim.transcript_hash
        )

    @staticmethod
    def mark_promoted(db: Session, claim: AudioRegenerationClaim) -> bool:
        changed = db.execute(
            text(
                "UPDATE file_operations SET state='promoted', updated_at=:now WHERE id=:id "
                "AND request_id=:request_id AND operation_type=:operation AND state='staged'"
            ),
            {
                "id": claim.file_operation_id,
                "request_id": claim.operation_id,
                "operation": AUDIO_FILE_OPERATION,
                "now": _now(),
            },
        )
        accepted = int(getattr(changed, "rowcount", 0)) == 1
        if accepted:
            db.commit()
        else:
            db.rollback()
        return accepted

    @staticmethod
    def commit_promotion(
        db: Session,
        claim: AudioRegenerationClaim,
        staged: StagedAudio,
        metadata: AudioMetadata,
        voice: ResolvedTurnVoice,
    ) -> bool:
        if voice.kind not in {"platform_profile", "mock_sentinel"}:
            return False
        if voice.kind == "mock_sentinel" and voice.profile_id is not None:
            return False
        if voice.kind == "platform_profile" and not voice.profile_id:
            return False
        try:
            if not SqlAudioRegenerationRepository.claim_is_current(db, claim):
                db.rollback()
                return False
            now = _now()
            existing = db.execute(
                text("SELECT id FROM stored_files WHERE relative_path=:path"),
                {"path": metadata.relative_path},
            ).scalar_one_or_none()
            file_id = str(existing or claim.previous_audio_file_id or uuid4())
            if existing is None and claim.previous_audio_file_id is None:
                db.execute(
                    text(
                        "INSERT INTO stored_files (id, kind, relative_path, sha256, size, state, "
                        "created_at, updated_at) VALUES (:id, 'debate_audio', :path, :sha, :size, "
                        "'active', :now, :now)"
                    ),
                    {
                        "id": file_id,
                        "path": metadata.relative_path,
                        "sha": metadata.sha256,
                        "size": metadata.size_bytes,
                        "now": now,
                    },
                )
            else:
                updated_file = db.execute(
                    text(
                        "UPDATE stored_files SET kind='debate_audio', relative_path=:path, "
                        "sha256=:sha, size=:size, state='active', updated_at=:now WHERE id=:id"
                    ),
                    {
                        "id": file_id,
                        "path": metadata.relative_path,
                        "sha": metadata.sha256,
                        "size": metadata.size_bytes,
                        "now": now,
                    },
                )
                if int(getattr(updated_file, "rowcount", 0)) != 1:
                    db.rollback()
                    return False
            turn_update = db.execute(
                text(
                    "UPDATE debate_turns SET audio_file_id=:file_id, audio_duration_ms=:duration, "
                    "actual_tts_voice_kind=:voice_kind, actual_tts_voice_profile_id=:profile_id, "
                    "preparation_stage='ready', safe_error_code=NULL, updated_at=:now "
                    "WHERE id=:turn_id AND debate_id=:debate_id "
                    "AND generation_status IN "
                    "('pending','running','final_ready','ready','completed','failed',"
                    "'turn_generation_failed') "
                    "AND speech IS NOT NULL AND structured_json IS NOT NULL "
                    "AND audio_file_id IS NULL AND speech=:speech AND structured_json=:structured "
                    "AND EXISTS (SELECT 1 FROM debates WHERE id=:debate_id "
                    "AND revision=:revision AND cancellation_generation=:generation "
                    "AND status IN ('draft','running','debate_finished','completed',"
                    "'stopped','failed')) "
                    "AND EXISTS (SELECT 1 FROM jobs WHERE id=:operation_id "
                    "AND debate_id=:debate_id "
                    "AND turn_id=:turn_id AND state='running' AND claim_token=:claim_token "
                    "AND cancellation_generation=:generation)"
                ),
                {
                    "file_id": file_id,
                    "duration": metadata.duration_ms,
                    "voice_kind": voice.kind,
                    "profile_id": voice.profile_id,
                    "now": now,
                    "turn_id": claim.turn_id,
                    "debate_id": claim.debate_id,
                    "speech": claim.speech,
                    "structured": claim.structured_json,
                    "revision": claim.expected_revision,
                    "generation": claim.cancellation_generation,
                    "operation_id": claim.operation_id,
                    "claim_token": claim.claim_token,
                },
            )
            # Fill the text predicates from their hashes only after the cheap
            # current-claim check; the exact values are loaded by the caller
            # and passed through this server-side object, never the browser.
            if int(getattr(turn_update, "rowcount", 0)) != 1:
                db.rollback()
                return False
            completed = db.execute(
                text(
                    "UPDATE jobs SET state='completed', safe_error_code=NULL, updated_at=:now "
                    "WHERE id=:operation_id AND state='running' AND claim_token=:claim_token"
                ),
                {
                    "operation_id": claim.operation_id,
                    "claim_token": claim.claim_token,
                    "now": now,
                },
            )
            if int(getattr(completed, "rowcount", 0)) != 1:
                db.rollback()
                return False
            journal = db.execute(
                text(
                    "UPDATE file_operations SET state='committed', safe_error_code=NULL, "
                    "updated_at=:now "
                    "WHERE id=:file_operation_id AND request_id=:operation_id "
                    "AND state='promoted'"
                ),
                {
                    "file_operation_id": claim.file_operation_id,
                    "operation_id": claim.operation_id,
                    "now": now,
                },
            )
            if int(getattr(journal, "rowcount", 0)) != 1:
                db.rollback()
                return False
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def canonical_is_unowned(db: Session, claim: AudioRegenerationClaim) -> bool:
        value = db.execute(
            text(
                "SELECT audio_file_id FROM debate_turns WHERE id=:turn_id AND debate_id=:debate_id"
            ),
            {"turn_id": claim.turn_id, "debate_id": claim.debate_id},
        ).scalar_one_or_none()
        return value is None

    @staticmethod
    def fail(db: Session, claim: AudioRegenerationClaim, code: str) -> None:
        now = _now()
        try:
            db.execute(
                text(
                    "UPDATE jobs SET state='failed', safe_error_code=:code, updated_at=:now "
                    "WHERE id=:operation_id AND state IN ('pending','running','interrupted') "
                    "AND (claim_token=:claim_token OR claim_token IS NULL)"
                ),
                {
                    "operation_id": claim.operation_id,
                    "claim_token": claim.claim_token,
                    "code": code,
                    "now": now,
                },
            )
            db.execute(
                text(
                    "UPDATE file_operations SET state='recovered', safe_error_code=:code, "
                    "updated_at=:now WHERE id=:file_operation_id AND request_id=:operation_id "
                    "AND state IN ('prepared','staged','promoted','cleanup_required')"
                ),
                {
                    "file_operation_id": claim.file_operation_id,
                    "operation_id": claim.operation_id,
                    "code": code,
                    "now": now,
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def recoverable(
        db: Session,
    ) -> tuple[tuple[AudioRegenerationClaim, StagedAudio | None], ...]:
        rows = (
            db.execute(
                text(
                    "SELECT j.id AS operation_id, j.debate_id, j.turn_id, j.idempotency_key, "
                    "j.claim_token, j.cancellation_generation, j.state AS job_state, "
                    "f.id AS file_operation_id, f.source_relative_path, f.target_relative_path, "
                    "f.expected_sha256, f.safe_error_code AS journal_marker, "
                    "t.speech, t.structured_json, t.audio_file_id, "
                    "t.transcript_hash, d.revision, d.course_id FROM jobs AS j "
                    "JOIN file_operations AS f "
                    "ON f.request_id=j.id AND f.operation_type=:operation JOIN debate_turns AS t "
                    "ON t.id=j.turn_id JOIN debates AS d ON d.id=j.debate_id WHERE "
                    "j.operation=:operation AND j.state IN ('pending','running') "
                    "AND f.state IN ('prepared','staged','promoted')"
                ),
                {"operation": AUDIO_REGENERATION_OPERATION},
            )
            .mappings()
            .all()
        )
        recovered: list[tuple[AudioRegenerationClaim, StagedAudio | None]] = []
        for row in rows:
            if not row["claim_token"] or not row["idempotency_key"]:
                continue
            speech = str(row["speech"] or "")
            structured = str(row["structured_json"] or "")
            staged: StagedAudio | None = None
            marker = str(row["journal_marker"] or "")
            expected_revision = int(row["revision"])
            if marker.startswith(_REVISION_MARKER_PREFIX):
                try:
                    expected_revision = int(marker[len(_REVISION_MARKER_PREFIX) :])
                except ValueError:
                    continue
            claim = AudioRegenerationClaim(
                operation_id=str(row["operation_id"]),
                file_operation_id=str(row["file_operation_id"]),
                claim_token=str(row["claim_token"]),
                idempotency_key=str(row["idempotency_key"]),
                debate_id=str(row["debate_id"]),
                turn_id=str(row["turn_id"]),
                expected_revision=expected_revision,
                cancellation_generation=int(row["cancellation_generation"] or 0),
                speech_hash=hashlib.sha256(speech.encode("utf-8")).hexdigest(),
                structured_hash=hashlib.sha256(structured.encode("utf-8")).hexdigest(),
                transcript_hash=str(row["transcript_hash"] or ""),
                speech=speech,
                structured_json=structured,
                previous_audio_file_id=(
                    str(row["audio_file_id"]) if row["audio_file_id"] is not None else None
                ),
            )
            # The filesystem facts are reconstructed by the service after it
            # has the configured data root; this adapter returns the claim
            # with no staged object when the path cannot be safely inspected.
            recovered.append((claim, staged))
        return tuple(recovered)


def default_voice_resolver(cached: CachedSegmentTurn) -> ResolvedTurnVoice:
    """Resolve the frozen Mock voice; real profiles require the runtime resolver."""

    if cached.effective_voice_kind == "mock_sentinel":
        return ResolvedTurnVoice("mock_sentinel", None, "mock")
    raise AudioRegenerationError("the effective voice is unavailable", code="voice_unavailable")


class AudioRegenerationService:
    """Bounded synchronous regeneration service for one SQL Session."""

    def __init__(
        self,
        db: Session,
        *,
        data_root: Path | None = None,
        audio_store: AudioStore | None = None,
        tts_provider: TTSProvider | None = None,
        voice_resolver: Callable[[CachedSegmentTurn], ResolvedTurnVoice] | None = None,
        repository: AudioRegenerationRepository | None = None,
        playback_service: object | None = None,
        before_promotion: Callable[[AudioRegenerationClaim], None] | None = None,
    ) -> None:
        if playback_service is not None:
            audio_store = audio_store or getattr(playback_service, "audio_store", None)
            tts_provider = tts_provider or getattr(playback_service, "tts_provider", None)
        if audio_store is None:
            if data_root is None:
                raise ValueError("audio regeneration needs data_root or audio_store")
            audio_store = AudioStore(data_root, tts_provider=tts_provider)
        elif tts_provider is not None and audio_store.tts_provider is not tts_provider:
            raise ValueError("audio_store and tts_provider must be the same provider")
        self.db = db
        self.audio_store = audio_store
        self.voice_resolver = voice_resolver or default_voice_resolver
        self.repository = repository or SqlAudioRegenerationRepository()
        self.before_promotion = before_promotion

    def regenerate_turn_audio(
        self,
        debate_id: str,
        turn_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> AudioRegenerationResult:
        """Regenerate cached audio without changing text or playback state."""

        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            return AudioRegenerationResult(
                "failed", debate_id, turn_id, None, safe_error_code="idempotency_invalid"
            )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            return AudioRegenerationResult(
                "failed", debate_id, turn_id, None, safe_error_code="revision_invalid"
            )
        key = idempotency_key.strip()
        existing = self.repository.load_job(self.db, key)
        if existing is not None:
            if existing.debate_id != debate_id or existing.turn_id != turn_id:
                return AudioRegenerationResult(
                    "failed",
                    debate_id,
                    turn_id,
                    None,
                    operation_id=existing.operation_id,
                    safe_error_code="idempotency_conflict",
                )
            cached = self._cached_or_none(debate_id, turn_id)
            audio = (
                self.repository.active_audio(self.db, cached, self.audio_store)
                if cached is not None
                else None
            )
            if existing.state == "completed":
                return AudioRegenerationResult(
                    "completed",
                    debate_id,
                    turn_id,
                    cached.revision if cached is not None else expected_revision,
                    operation_id=existing.operation_id,
                    audio=audio,
                )
            if existing.state in {"pending", "running"}:
                return AudioRegenerationResult(
                    "queued",
                    debate_id,
                    turn_id,
                    cached.revision if cached is not None else expected_revision,
                    operation_id=existing.operation_id,
                )
            return AudioRegenerationResult(
                "failed",
                debate_id,
                turn_id,
                cached.revision if cached is not None else expected_revision,
                operation_id=existing.operation_id,
                safe_error_code=existing.safe_error_code or AUDIO_REGENERATION_INTERRUPTED_CODE,
            )

        try:
            cached = self.repository.load_cached_turn(self.db, debate_id, turn_id)
        except AudioRegenerationError as exc:
            status: AudioRegenerationStatus = "not_found" if exc.code == "not_found" else "failed"
            return AudioRegenerationResult(
                status, debate_id, turn_id, None, safe_error_code=exc.code
            )
        if cached.revision != expected_revision:
            return AudioRegenerationResult(
                "stale",
                debate_id,
                turn_id,
                cached.revision,
                safe_error_code="stale_revision",
            )
        existing_audio = self.repository.active_audio(self.db, cached, self.audio_store)
        if existing_audio is not None:
            return AudioRegenerationResult(
                "already_ready", debate_id, turn_id, cached.revision, audio=existing_audio
            )
        try:
            voice = self.voice_resolver(cached)
            self._validate_voice(voice)
        except AudioRegenerationError as exc:
            return AudioRegenerationResult(
                "failed", debate_id, turn_id, cached.revision, safe_error_code=exc.code
            )
        except Exception:
            return AudioRegenerationResult(
                "failed", debate_id, turn_id, cached.revision, safe_error_code="voice_unavailable"
            )
        claim = self.repository.claim(
            self.db,
            cached,
            expected_revision=expected_revision,
            idempotency_key=key,
        )
        if claim is None:
            replay = self.repository.load_job(self.db, key)
            if replay is not None and replay.debate_id == debate_id and replay.turn_id == turn_id:
                replay_status: AudioRegenerationStatus = (
                    "queued" if replay.state in {"pending", "running"} else "failed"
                )
                return AudioRegenerationResult(
                    replay_status,
                    debate_id,
                    turn_id,
                    cached.revision,
                    operation_id=replay.operation_id,
                    safe_error_code=replay.safe_error_code,
                )
            return AudioRegenerationResult(
                "failed", debate_id, turn_id, cached.revision, safe_error_code="claim_unavailable"
            )
        if not self.repository.claim_is_current(self.db, claim):
            self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
            return AudioRegenerationResult(
                "stale",
                debate_id,
                turn_id,
                expected_revision,
                claim.operation_id,
                safe_error_code="stale_revision",
            )
        staged: StagedAudio | None = None
        promoted = False
        try:
            staged = self.audio_store.stage_synthesis(
                course_id=cached.course_id,
                debate_id=cached.debate_id,
                turn_id=cached.turn_id,
                speech=cached.speech,
                voice_token=voice.voice_token,
                language=cached.output_language,
                operation_id=claim.file_operation_id,
                target_model_key=voice.target_model_key,
                voice_params=cached.voice_params,
            )
            if not self.repository.mark_staged(self.db, claim, staged):
                raise AudioRegenerationError(
                    "audio stage claim is stale", code=AUDIO_REGENERATION_STALE_CODE
                )
            if self.before_promotion is not None:
                self.before_promotion(claim)
            if not self.repository.claim_is_current(self.db, claim):
                self._discard_stage(staged)
                self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
                return AudioRegenerationResult(
                    "stale",
                    debate_id,
                    turn_id,
                    expected_revision,
                    claim.operation_id,
                    safe_error_code="stale_revision",
                )
            metadata = self.audio_store.promote_staged_audio(staged)
            promoted = True
            if not self.repository.mark_promoted(self.db, claim):
                self._remove_promoted(staged, claim)
                self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
                return AudioRegenerationResult(
                    "stale",
                    debate_id,
                    turn_id,
                    expected_revision,
                    claim.operation_id,
                    safe_error_code="claim_lost",
                )
            if not self.repository.commit_promotion(self.db, claim, staged, metadata, voice):
                self._remove_promoted(staged, claim)
                self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
                return AudioRegenerationResult(
                    "stale",
                    debate_id,
                    turn_id,
                    expected_revision,
                    claim.operation_id,
                    safe_error_code="stale_revision",
                )
            return AudioRegenerationResult(
                "completed",
                debate_id,
                turn_id,
                expected_revision,
                claim.operation_id,
                audio=metadata,
            )
        except TTSProviderError as exc:
            self._cleanup_failed(staged, promoted, claim)
            code = _safe_provider_code(exc)
            self.repository.fail(self.db, claim, code)
            return AudioRegenerationResult(
                "failed",
                debate_id,
                turn_id,
                expected_revision,
                claim.operation_id,
                safe_error_code=code,
            )
        except Exception:
            self._cleanup_failed(staged, promoted, claim)
            self.repository.fail(self.db, claim, "audio_regeneration_failed")
            return AudioRegenerationResult(
                "failed",
                debate_id,
                turn_id,
                expected_revision,
                claim.operation_id,
                safe_error_code="audio_regeneration_failed",
            )

    def resume_startup(self) -> tuple[AudioRegenerationResult, ...]:
        """Promote durable staged WAVs after a restart without another TTS call."""

        results: list[AudioRegenerationResult] = []
        for claim, _unused in self.repository.recoverable(self.db):
            op_row = (
                self.db.execute(
                    text(
                        "SELECT f.source_relative_path, f.target_relative_path, f.expected_sha256, "
                        "f.state, d.course_id, t.audio_file_id FROM file_operations AS f "
                        "JOIN debates AS d ON d.id=:debate_id "
                        "JOIN debate_turns AS t ON t.id=:turn_id "
                        "WHERE f.id=:file_operation_id"
                    ),
                    {
                        "debate_id": claim.debate_id,
                        "turn_id": claim.turn_id,
                        "file_operation_id": claim.file_operation_id,
                    },
                )
                .mappings()
                .first()
            )
            if op_row is None:
                self.repository.fail(self.db, claim, AUDIO_REGENERATION_INTERRUPTED_CODE)
                results.append(
                    AudioRegenerationResult(
                        "failed",
                        claim.debate_id,
                        claim.turn_id,
                        claim.expected_revision,
                        claim.operation_id,
                        safe_error_code=AUDIO_REGENERATION_INTERRUPTED_CODE,
                    )
                )
                continue
            state = str(op_row["state"])
            journal_promoted = state == "promoted"
            if state == "promoted":
                staged = self._load_promoted_from_journal(claim, cast(Mapping[str, object], op_row))
                metadata = self._metadata_for_promoted(staged)
                current = staged is not None and metadata is not None
            else:
                staged = self._load_staged_from_journal(claim, cast(Mapping[str, object], op_row))
                metadata = None
                current = staged is not None
                if not current:
                    # A process may have crashed after the filesystem rename
                    # but before the journal's ``promoted`` transition.
                    staged = self._load_promoted_from_journal(
                        claim, cast(Mapping[str, object], op_row)
                    )
                    metadata = self._metadata_for_promoted(staged)
                    current = staged is not None and metadata is not None
                    if current:
                        state = "promoted"
            if not current or not self.repository.claim_is_current(self.db, claim):
                self._discard_stage(staged if state != "promoted" else None)
                if state == "promoted" and staged is not None:
                    self._remove_promoted(staged, claim)
                self.repository.fail(self.db, claim, AUDIO_REGENERATION_INTERRUPTED_CODE)
                results.append(
                    AudioRegenerationResult(
                        "stale",
                        claim.debate_id,
                        claim.turn_id,
                        claim.expected_revision,
                        claim.operation_id,
                        safe_error_code=AUDIO_REGENERATION_INTERRUPTED_CODE,
                    )
                )
                continue
            promoted = False
            try:
                if not journal_promoted:
                    assert staged is not None
                    if staged.relative_path != staged.target_relative_path:
                        metadata = self.audio_store.promote_staged_audio(staged)
                    else:
                        metadata = self._metadata_for_promoted(staged)
                        if metadata is None:
                            raise AudioRegenerationError(
                                "the promoted audio is unavailable",
                                code=AUDIO_REGENERATION_INTERRUPTED_CODE,
                            )
                    promoted = True
                    if not self.repository.mark_promoted(self.db, claim):
                        self._remove_promoted(staged, claim)
                        self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
                        results.append(
                            AudioRegenerationResult(
                                "stale",
                                claim.debate_id,
                                claim.turn_id,
                                claim.expected_revision,
                                claim.operation_id,
                                safe_error_code="claim_lost",
                            )
                        )
                        continue
                cached = self.repository.load_cached_turn(self.db, claim.debate_id, claim.turn_id)
                voice = self.voice_resolver(cached)
                self._validate_voice(voice)
                if staged is None or metadata is None:
                    raise AudioRegenerationError(
                        "the staged audio is unavailable", code=AUDIO_REGENERATION_INTERRUPTED_CODE
                    )
                if not self.repository.commit_promotion(self.db, claim, staged, metadata, voice):
                    self._remove_promoted(staged, claim)
                    self.repository.fail(self.db, claim, AUDIO_REGENERATION_STALE_CODE)
                    results.append(
                        AudioRegenerationResult(
                            "stale",
                            claim.debate_id,
                            claim.turn_id,
                            claim.expected_revision,
                            claim.operation_id,
                            safe_error_code="stale_revision",
                        )
                    )
                    continue
                results.append(
                    AudioRegenerationResult(
                        "completed",
                        claim.debate_id,
                        claim.turn_id,
                        claim.expected_revision,
                        claim.operation_id,
                        audio=metadata,
                    )
                )
            except Exception:
                self._cleanup_failed(staged, promoted, claim)
                self.repository.fail(self.db, claim, "audio_regeneration_failed")
                results.append(
                    AudioRegenerationResult(
                        "failed",
                        claim.debate_id,
                        claim.turn_id,
                        claim.expected_revision,
                        claim.operation_id,
                        safe_error_code="audio_regeneration_failed",
                    )
                )
        return tuple(results)

    def _cached_or_none(self, debate_id: str, turn_id: str) -> CachedSegmentTurn | None:
        try:
            return self.repository.load_cached_turn(self.db, debate_id, turn_id)
        except AudioRegenerationError:
            return None

    @staticmethod
    def _validate_voice(voice: object) -> None:
        if not isinstance(voice, ResolvedTurnVoice):
            raise AudioRegenerationError(
                "the effective voice is unavailable", code="voice_unavailable"
            )
        if voice.kind not in {"mock_sentinel", "platform_profile"} or not voice.voice_token:
            raise AudioRegenerationError(
                "the effective voice is unavailable", code="voice_unavailable"
            )
        if voice.kind == "mock_sentinel" and voice.profile_id is not None:
            raise AudioRegenerationError(
                "the effective voice is unavailable", code="voice_unavailable"
            )
        # platform_profile may carry no profile id: a Debate's own clone keeps
        # speaking after the platform Voice is deleted (2026-10-20).

    def _discard_stage(self, staged: StagedAudio | None) -> None:
        if staged is not None:
            self.audio_store.discard_staged_audio(staged)

    def _remove_promoted(
        self, staged: StagedAudio, claim: AudioRegenerationClaim | None = None
    ) -> None:
        # Once another worker has attached a StoredFile to the turn, deleting
        # matching bytes could remove its winning publication.  The SQL port
        # owns this final DB-side ownership check; simple test ports may omit
        # it because they have no shared canonical row.
        guard = getattr(self.repository, "canonical_is_unowned", None)
        if claim is not None and callable(guard) and not guard(self.db, claim):
            return
        self.audio_store.remove_promoted_audio_if_owned(staged)

    def _cleanup_failed(
        self,
        staged: StagedAudio | None,
        promoted: bool,
        claim: AudioRegenerationClaim | None = None,
    ) -> None:
        if staged is None:
            return
        if promoted:
            self._remove_promoted(staged, claim)
        else:
            self._discard_stage(staged)

    def _load_staged_from_journal(
        self, claim: AudioRegenerationClaim, row: Mapping[str, object]
    ) -> StagedAudio | None:
        source = row.get("source_relative_path")
        target = row.get("target_relative_path")
        expected = row.get("expected_sha256")
        course = row.get("course_id")
        if not all(
            isinstance(value, str) and value for value in (source, target, expected, course)
        ):
            return None
        source = cast(str, source)
        target = cast(str, target)
        expected = cast(str, expected)
        course = cast(str, course)
        try:
            if source != audio_staging_relative_path(
                course, claim.debate_id, claim.turn_id, claim.file_operation_id
            ) or target != audio_relative_path(course, claim.debate_id, claim.turn_id):
                return None
        except ValueError:
            return None
        path = self.audio_store._non_symlink_path(source)
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected:
                return None
            return StagedAudio(
                operation_id=claim.file_operation_id,
                course_id=course,
                debate_id=claim.debate_id,
                turn_id=claim.turn_id,
                relative_path=source,
                target_relative_path=target,
                sha256=digest,
                size_bytes=len(raw),
                duration_ms=wav_duration_ms(raw),
            )
        except (OSError, TTSProviderError, ValueError):
            return None

    def _load_promoted_from_journal(
        self, claim: AudioRegenerationClaim, row: Mapping[str, object]
    ) -> StagedAudio | None:
        target = row.get("target_relative_path")
        expected = row.get("expected_sha256")
        course = row.get("course_id")
        if not all(isinstance(value, str) and value for value in (target, expected, course)):
            return None
        target = cast(str, target)
        expected = cast(str, expected)
        course = cast(str, course)
        try:
            if target != audio_relative_path(course, claim.debate_id, claim.turn_id):
                return None
        except ValueError:
            return None
        path = self.audio_store._non_symlink_path(target)
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected:
                return None
            return StagedAudio(
                operation_id=claim.file_operation_id,
                course_id=course,
                debate_id=claim.debate_id,
                turn_id=claim.turn_id,
                relative_path=target,
                target_relative_path=target,
                sha256=digest,
                size_bytes=len(raw),
                duration_ms=wav_duration_ms(raw),
            )
        except (OSError, TTSProviderError, ValueError):
            return None

    def _metadata_for_promoted(self, staged: StagedAudio | None) -> AudioMetadata | None:
        if staged is None:
            return None
        path = self.audio_store._non_symlink_path(staged.target_relative_path)
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != staged.sha256:
                return None
            duration = wav_duration_ms(raw)
            if duration != staged.duration_ms:
                return None
            return AudioMetadata(
                course_id=staged.course_id,
                debate_id=staged.debate_id,
                turn_id=staged.turn_id,
                relative_path=staged.target_relative_path,
                sha256=staged.sha256,
                size_bytes=len(raw),
                duration_ms=duration,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
            )
        except (OSError, TTSProviderError, ValueError):
            return None


def regenerate_turn_audio(
    db: Session,
    debate_id: str,
    turn_id: str,
    expected_revision: int,
    idempotency_key: str,
    *,
    data_root: Path | None = None,
    audio_store: AudioStore | None = None,
    tts_provider: TTSProvider | None = None,
    voice_resolver: Callable[[CachedSegmentTurn], ResolvedTurnVoice] | None = None,
    repository: AudioRegenerationRepository | None = None,
    playback_service: object | None = None,
) -> AudioRegenerationResult:
    """Convenience entry point used by the teacher route."""

    return AudioRegenerationService(
        db,
        data_root=data_root,
        audio_store=audio_store,
        tts_provider=tts_provider,
        voice_resolver=voice_resolver,
        repository=repository,
        playback_service=playback_service,
    ).regenerate_turn_audio(debate_id, turn_id, expected_revision, idempotency_key)


def startup_resume_audio_regeneration(
    db: Session,
    *,
    data_root: Path | None = None,
    audio_store: AudioStore | None = None,
    tts_provider: TTSProvider | None = None,
    repository: AudioRegenerationRepository | None = None,
    playback_service: object | None = None,
) -> tuple[AudioRegenerationResult, ...]:
    """Startup hook that resumes only durable staged WAV promotion."""

    service = AudioRegenerationService(
        db,
        data_root=data_root,
        audio_store=audio_store,
        tts_provider=tts_provider,
        repository=repository,
        playback_service=playback_service,
    )
    return service.resume_startup()


__all__ = [
    "AUDIO_FILE_OPERATION",
    "AUDIO_REGENERATION_OPERATION",
    "AudioRegenerationClaim",
    "AudioRegenerationError",
    "AudioRegenerationJob",
    "AudioRegenerationRepository",
    "AudioRegenerationResult",
    "AudioRegenerationService",
    "CachedSegmentTurn",
    "SqlAudioRegenerationRepository",
    "default_voice_resolver",
    "regenerate_turn_audio",
    "startup_resume_audio_regeneration",
]


def discard_unjournaled_audio_stages(db: Session, audio_store: AudioStore) -> int:
    """Remove interrupted normal preparation stages before any worker starts."""
    root = audio_store.data_root / "staging" / "debate-turn-tts"
    if not root.is_dir() or root.is_symlink():
        return 0
    retained = set(
        db.scalars(
            text(
                "SELECT source_relative_path FROM file_operations "
                "WHERE operation_type='debate_turn_tts' "
                "AND state IN ('prepared','staged','promoted','cleanup_required')"
            )
        )
    )
    owned = {
        tuple(str(value) for value in row)
        for row in db.execute(
            text(
                "SELECT d.course_id,d.id,t.id,j.claim_token FROM jobs j "
                "JOIN debate_turns t ON t.id=j.turn_id AND t.debate_id=j.debate_id "
                "JOIN debates d ON d.id=t.debate_id "
                "WHERE j.operation='debate_turn_prepare' AND j.claim_token IS NOT NULL "
                "AND j.state IN ('pending','running')"
            )
        )
    }
    removed = 0
    for path in root.glob("*/*/*/*.wav"):
        relative = path.relative_to(audio_store.data_root).as_posix()
        if relative in retained:
            continue
        parts = path.relative_to(root).parts
        identity = (*parts[:3], path.stem)
        if identity not in owned:
            continue
        try:
            from uuid import UUID

            if len(parts) != 4:
                continue
            for part in (*parts[:3], Path(parts[3]).stem):
                UUID(part)
        except ValueError:
            continue
        if audio_store._non_symlink_path(relative) is None:
            continue
        audio_store.discard_staged_audio(relative)
        removed += 1
    return removed
