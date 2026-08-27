"""One-shot operator gate for the real system-voice TTS preview.

This module is intentionally separate from :mod:`fallback`.  The historical
fallback verifier owns the old enrollment/preview ledger and its bounded
retry policy.  The Wave 2 operator gate is a new, durable ``tts_preview``
attempt (attempt 3) and must never reset or reuse that history.

The gate is not an HTTP route.  A caller must explicitly pass ``allow_real``
and use the DashScope TTS selector while every other provider remains Mock.
The operation is persisted as ``prepared`` and then ``dispatched`` before
crossing the provider boundary.  A provider result is validated in memory,
then stored only as a short-lived platform-owned ``VoicePreview`` resource;
supplier identifiers, URLs, response bodies, and provider metadata are never
written to logs or the database.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.models import StoredFile, VoicePreview, VoiceProfile, VoiceProviderOperation
from app.modules.knowledge.files import contained_path, ensure_private_dir, write_atomic
from app.modules.voices.crypto import VoiceEncryptionError, decrypt_external_voice_id
from app.modules.voices.service import PREVIEW_TTL
from app.providers.audio import MAX_PREVIEW_BYTES, AudioValidationError, validate_technical_audio
from app.providers.tts import TTSProvider, TTSProviderError, TTSProviderTimeout

TTS_OPERATION_TYPE = "tts_preview"
TTS_GATE_ATTEMPT = 3
TTS_GATE_ID = "maya-real-tts-preview-attempt3-v1"
TTS_GATE_NAMESPACE = UUID("6e326c5d-b2ec-5c99-9e21-d4d6fb4c4c93")
TTS_GATE_LANGUAGE = "en"
TTS_GATE_TEXT = (
    "This technical check confirms that a clear English sentence can be "
    "synthesized for the Maya classroom."
)
TTS_GATE_DEADLINE = timedelta(seconds=35)
TTS_SAFE_CODES = frozenset(
    {
        "tts_http_rejected",
        "tts_response_invalid",
        "tts_result_url_rejected",
        "tts_result_dns_failed",
        "tts_result_download_failed",
        "tts_audio_invalid",
        "tts_timeout",
        "tts_outcome_unknown",
    }
)

TTSGateStatus = Literal["ready", "failed", "outcome_unknown"]


class TTSGateError(RuntimeError):
    """Safe operator error that never carries provider or secret details."""

    def __init__(self, safe_code: str) -> None:
        self.safe_code = safe_code
        super().__init__(safe_code)


@dataclass(frozen=True)
class TTSGateResult:
    """Safe result returned to an operator-only caller."""

    profile_id: str
    operation_id: str
    status: TTSGateStatus
    error_code: str | None = None
    output_bytes: int = 0
    metrics: dict[str, float] | None = None
    preview_id: str | None = None
    attempt: int = TTS_GATE_ATTEMPT


@dataclass(frozen=True)
class _PreviewArtifact:
    id: str
    relative_path: str


@contextmanager
def _tts_gate_lock(data_root: Path) -> Iterator[None]:
    """Serialize this one-shot gate on the local host."""

    lock_path = data_root / "tmp" / "system-fallback-tts-gate.lock"
    try:
        ensure_private_dir(lock_path.parent)
        handle = lock_path.open("a+b")
        lock_path.chmod(0o600)
    except OSError as exc:
        raise TTSGateError("tts_outcome_unknown") from exc
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TTSGateError("tts_outcome_unknown") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _gate_hash(profile: VoiceProfile) -> str:
    """Hash only deterministic gate metadata, never the external voice ID."""

    payload = {
        "attempt": TTS_GATE_ATTEMPT,
        "gate_id": TTS_GATE_ID,
        "language": TTS_GATE_LANGUAGE,
        "profile_id": profile.id,
        "provider_key": profile.provider_key,
        "target_model_key": profile.target_model_key,
        "text": TTS_GATE_TEXT,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def gate_hash_for_profile(profile: VoiceProfile) -> str:
    """Return the durable Gate hash used by attempt 3."""

    return _gate_hash(profile)


def gate_operation_id(profile: VoiceProfile, request_hash: str | None = None) -> str:
    """Return the deterministic DB claim ID for this exact Gate request."""

    digest = request_hash or _gate_hash(profile)
    return str(uuid5(TTS_GATE_NAMESPACE, f"{TTS_GATE_ID}:{profile.id}:{digest}"))


def _safe_provider_code(error: TTSProviderError, fallback: str = "tts_response_invalid") -> str:
    value = getattr(error, "safe_code", None)
    return value if isinstance(value, str) and value in TTS_SAFE_CODES else fallback


def _store_preview(
    session: Session,
    settings: Settings,
    profile: VoiceProfile,
    raw: bytes,
) -> _PreviewArtifact:
    """Stage a short-lived same-origin preview in the platform store."""

    preview_id = str(uuid4())
    relative_path = f"system/voices/previews/{preview_id}.wav"
    data_root = settings.resolved_data_root
    try:
        digest, size = write_atomic(data_root, relative_path, raw)
        timestamp = _now_utc()
        stored = StoredFile(
            id=str(uuid4()),
            kind="voice_preview",
            relative_path=relative_path,
            sha256=digest,
            size_bytes=size,
            state="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        preview = VoicePreview(
            id=preview_id,
            profile_id=profile.id,
            group_id=None,
            stored_file_id=stored.id,
            relative_path=relative_path,
            state="active",
            expires_at=timestamp + PREVIEW_TTL,
            created_at=timestamp,
        )
        session.add_all([stored, preview])
        return _PreviewArtifact(preview_id, relative_path)
    except Exception:
        _remove_preview_file(data_root, relative_path)
        raise


def _remove_preview_file(data_root: Path, relative_path: str) -> None:
    try:
        path = contained_path(data_root, relative_path)
        if path.exists() or path.is_symlink():
            path.unlink()
    except (ValueError, OSError):
        pass


def _validate_operator_selectors(settings: Settings, *, allow_real: bool) -> None:
    if not allow_real:
        raise TTSGateError("tts_response_invalid")
    if settings.tts_provider != "dashscope":
        raise TTSGateError("tts_response_invalid")
    if settings.voice_provider != "mock":
        raise TTSGateError("tts_response_invalid")
    if settings.llm_provider != "mock" or settings.embedding_provider != "mock":
        raise TTSGateError("tts_response_invalid")
    if settings.translation_provider not in {None, "", "mock"}:
        raise TTSGateError("tts_response_invalid")


def _system_profile(session: Session) -> VoiceProfile:
    profiles = session.scalars(
        select(VoiceProfile).where(VoiceProfile.scope == "system").order_by(VoiceProfile.created_at)
    ).all()
    if len(profiles) != 1:
        raise TTSGateError("tts_response_invalid")
    return profiles[0]


def _attempt_three(
    session: Session,
    profile: VoiceProfile,
    expected_hash: str,
) -> VoiceProviderOperation | None:
    operations = session.scalars(
        select(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.profile_id == profile.id,
            VoiceProviderOperation.operation_type == TTS_OPERATION_TYPE,
        )
        .order_by(VoiceProviderOperation.created_at, VoiceProviderOperation.id)
    ).all()
    attempt_three = [operation for operation in operations if operation.attempt == TTS_GATE_ATTEMPT]
    if len(attempt_three) > 1:
        raise TTSGateError("tts_response_invalid")
    # Attempt 4+ would mean another caller has crossed the one-shot boundary.
    # Do not attempt to repair, reset, or supersede it.
    if any(operation.attempt > TTS_GATE_ATTEMPT for operation in operations):
        raise TTSGateError("tts_response_invalid")
    if not attempt_three:
        return None
    operation = attempt_three[0]
    if operation.id != gate_operation_id(profile, expected_hash):
        raise TTSGateError("tts_response_invalid")
    if operation.request_hash != expected_hash:
        raise TTSGateError("tts_response_invalid")
    if operation.profile_scope != "system":
        raise TTSGateError("tts_response_invalid")
    return operation


def _new_operation(
    profile: VoiceProfile,
    request_hash: str,
    operation_id: str,
) -> VoiceProviderOperation:
    timestamp = _now_utc()
    return VoiceProviderOperation(
        id=operation_id,
        profile_id=profile.id,
        operation_type=TTS_OPERATION_TYPE,
        profile_scope="system",
        state="prepared",
        attempt=TTS_GATE_ATTEMPT,
        claim_token=uuid4().hex,
        request_hash=request_hash,
        provider_deadline=timestamp + TTS_GATE_DEADLINE,
        request_count=0,
        charged_request_count=0,
        input_bytes=len(TTS_GATE_TEXT.encode("utf-8")),
        output_bytes=0,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _dispatch(session: Session, operation: VoiceProviderOperation) -> None:
    changed = session.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.attempt == TTS_GATE_ATTEMPT,
            VoiceProviderOperation.state == "prepared",
            VoiceProviderOperation.claim_token == operation.claim_token,
        )
        .values(
            state="dispatched",
            request_count=VoiceProviderOperation.request_count + 1,
            # A real TTS request may be charged even when its response fails.
            charged_request_count=VoiceProviderOperation.charged_request_count + 1,
            dispatched_at=_now_utc(),
            updated_at=_now_utc(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        session.rollback()
        raise TTSGateError("tts_response_invalid")
    session.commit()


def _result_from_existing(
    session: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
) -> TTSGateResult:
    """Replay attempt 3 without any provider operation."""

    if operation.state == "succeeded":
        preview = session.scalar(
            select(VoicePreview)
            .where(
                VoicePreview.profile_id == profile.id,
                VoicePreview.state == "active",
            )
            .order_by(VoicePreview.created_at.desc())
        )
        if preview is None or preview.relative_path is None:
            raise TTSGateError("tts_response_invalid")
        if profile.status == "preview_ready":
            profile.status = "ready"
            profile.safe_error_code = None
            profile.updated_at = _now_utc()
            session.commit()
        elif profile.status != "ready":
            raise TTSGateError("tts_response_invalid")
        return TTSGateResult(
            profile_id=profile.id,
            operation_id=operation.id,
            status="ready",
            output_bytes=operation.output_bytes,
            preview_id=preview.id,
        )
    if operation.state == "failed":
        if profile.status not in {"preview_ready", "ready"}:
            raise TTSGateError("tts_response_invalid")
        if profile.status == "ready":
            # A failed duplicate cannot undo a ready profile.  This is a
            # conservative replay-only branch for an externally repaired DB.
            return TTSGateResult(
                profile_id=profile.id,
                operation_id=operation.id,
                status="ready",
                output_bytes=operation.output_bytes,
            )
        return TTSGateResult(
            profile_id=profile.id,
            operation_id=operation.id,
            status="failed",
            error_code=(
                operation.safe_error_code
                if operation.safe_error_code in TTS_SAFE_CODES
                else "tts_response_invalid"
            ),
            output_bytes=operation.output_bytes,
        )
    if operation.state in {"prepared", "dispatched", "reconciling", "outcome_unknown"}:
        # A stale prepared row may have been created before the worker died;
        # it is still treated as an unknown one-shot attempt and never retried.
        unknown_code = (
            operation.safe_error_code
            if operation.safe_error_code in TTS_SAFE_CODES
            else "tts_outcome_unknown"
        )
        changed = session.execute(
            update(VoiceProviderOperation)
            .where(
                VoiceProviderOperation.id == operation.id,
                VoiceProviderOperation.attempt == TTS_GATE_ATTEMPT,
                VoiceProviderOperation.state.in_(
                    ("prepared", "dispatched", "reconciling", "outcome_unknown")
                ),
                VoiceProviderOperation.claim_token == operation.claim_token,
            )
            .values(state="outcome_unknown", safe_error_code=unknown_code, updated_at=_now_utc())
        )
        if getattr(changed, "rowcount", 0) != 1:
            session.rollback()
            raise TTSGateError("tts_response_invalid")
        if profile.status == "preview_ready":
            # Unknown must not demote a successfully-enrolled mapping.  The
            # operator must reconcile this attempt outside the one-shot gate.
            profile.safe_error_code = unknown_code
            profile.updated_at = _now_utc()
        session.commit()
        return TTSGateResult(
            profile_id=profile.id,
            operation_id=operation.id,
            status="outcome_unknown",
            error_code=unknown_code,
            output_bytes=operation.output_bytes,
        )
    raise TTSGateError("tts_response_invalid")


def _finish(
    session: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    *,
    state: Literal["succeeded", "failed", "outcome_unknown"],
    error_code: str | None,
    output_bytes: int = 0,
    metrics: dict[str, float] | None = None,
    safe_request_id: str | None = None,
    preview: _PreviewArtifact | None = None,
) -> TTSGateResult:
    timestamp = _now_utc()
    changed = session.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.attempt == TTS_GATE_ATTEMPT,
            VoiceProviderOperation.state == "dispatched",
            VoiceProviderOperation.claim_token == operation.claim_token,
        )
        .values(
            state=state,
            safe_error_code=error_code,
            output_bytes=output_bytes,
            safe_request_id=safe_request_id,
            completed_at=timestamp if state in {"succeeded", "failed"} else None,
            updated_at=timestamp,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        session.rollback()
        existing = session.get(VoiceProviderOperation, operation.id)
        if existing is not None and existing.state == "outcome_unknown":
            code = (
                existing.safe_error_code
                if existing.safe_error_code in TTS_SAFE_CODES
                else "tts_outcome_unknown"
            )
            if profile.status == "preview_ready":
                profile.safe_error_code = code
                profile.updated_at = _now_utc()
                session.commit()
            return TTSGateResult(
                profile_id=profile.id,
                operation_id=existing.id,
                status="outcome_unknown",
                error_code=code,
                output_bytes=existing.output_bytes,
            )
        if existing is not None and existing.state in {"succeeded", "failed"}:
            return _result_from_existing(session, profile, existing)
        raise TTSGateError("tts_outcome_unknown")
    if state == "succeeded":
        if preview is None:
            session.rollback()
            raise TTSGateError("tts_response_invalid")
        profile.status = "ready"
        profile.safe_error_code = None
    elif state == "failed":
        # An ordinary provider/audio failure is retry-free but leaves the
        # already-enrolled mapping usable for a later explicitly reviewed run.
        profile.status = "preview_ready"
        profile.safe_error_code = error_code or "tts_response_invalid"
    else:
        # The provider outcome is uncertain, but the enrollment mapping is
        # still a usable preview-ready profile.  Do not promote or demote it.
        profile.status = "preview_ready"
        profile.safe_error_code = error_code or "tts_outcome_unknown"
    profile.updated_at = timestamp
    session.commit()
    return TTSGateResult(
        profile_id=profile.id,
        operation_id=operation.id,
        status="ready" if state == "succeeded" else state,
        error_code=error_code,
        output_bytes=output_bytes,
        metrics=metrics,
        preview_id=preview.id if preview is not None else None,
    )


def _run_once(
    settings: Settings,
    database: Database,
    *,
    provider: TTSProvider | None,
) -> TTSGateResult:
    session = database.session_factory()
    try:
        profile = _system_profile(session)
        if profile.provider_key != "dashscope":
            raise TTSGateError("tts_response_invalid")
        if profile.target_model_key != "qwen3-tts-vc-2026-01-22":
            raise TTSGateError("tts_response_invalid")
        expected_hash = _gate_hash(profile)
        operation = _attempt_three(session, profile, expected_hash)
        if operation is not None:
            return _result_from_existing(session, profile, operation)
        if profile.status != "preview_ready":
            raise TTSGateError("tts_response_invalid")

        if provider is None:
            from app.providers.factory import tts_provider

            try:
                provider = tts_provider(settings)
            except Exception as exc:
                raise TTSGateError("tts_response_invalid") from exc
        if (
            getattr(provider, "key", None) != "dashscope"
            or getattr(provider, "target_model_key", None) != profile.target_model_key
        ):
            raise TTSGateError("tts_response_invalid")

        try:
            external_voice_id = decrypt_external_voice_id(
                profile.external_id_encrypted or b"",
                settings.secret_bytes,
                profile_id=profile.id,
                scope=profile.scope,
                group_id=profile.group_id,
                provider_key=profile.provider_key,
                target_model_key=profile.target_model_key,
            )
        except VoiceEncryptionError as exc:
            raise TTSGateError("tts_response_invalid") from exc

        operation_id = gate_operation_id(profile, expected_hash)
        operation = _new_operation(profile, expected_hash, operation_id)
        session.add(operation)
        try:
            # The deterministic primary key is the correctness fence across
            # processes.  Both contenders may reach this INSERT, but only
            # one can commit the exact Gate row.
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            winner = session.get(VoiceProviderOperation, operation_id)
            if winner is None:
                raise TTSGateError("tts_outcome_unknown") from exc
            if (
                winner.profile_id != profile.id
                or winner.operation_type != TTS_OPERATION_TYPE
                or winner.profile_scope != "system"
                or winner.attempt != TTS_GATE_ATTEMPT
                or winner.request_hash != expected_hash
            ):
                raise TTSGateError("tts_response_invalid") from exc
            return _result_from_existing(session, profile, winner)
        _dispatch(session, operation)
        try:
            # This is the only provider method reachable from the gate.
            result = provider.synthesize(
                TTS_GATE_TEXT, external_voice_id, language=TTS_GATE_LANGUAGE
            )
        except TTSProviderTimeout:
            return _finish(
                session,
                profile,
                operation,
                state="outcome_unknown",
                error_code="tts_timeout",
            )
        except TTSProviderError as exc:
            return _finish(
                session,
                profile,
                operation,
                state="failed",
                error_code=_safe_provider_code(exc),
            )
        except Exception:
            return _finish(
                session,
                profile,
                operation,
                state="failed",
                error_code="tts_response_invalid",
            )
        try:
            raw = result.audio_bytes
            if not isinstance(raw, bytes) or len(raw) > MAX_PREVIEW_BYTES:
                raise AudioValidationError("tts_audio_invalid")
            metrics = validate_technical_audio(raw)
            output_bytes = len(raw)
        except Exception:
            return _finish(
                session,
                profile,
                operation,
                state="failed",
                error_code="tts_audio_invalid",
            )
        artifact: _PreviewArtifact | None = None
        try:
            artifact = _store_preview(session, settings, profile, raw)
        except Exception:
            session.rollback()
            return _finish(
                session,
                profile,
                operation,
                state="failed",
                error_code="tts_audio_invalid",
            )
        try:
            safe_request_id = getattr(result, "request_id", None)
            if not isinstance(safe_request_id, str) or len(safe_request_id) > 120:
                safe_request_id = None
            finished = _finish(
                session,
                profile,
                operation,
                state="succeeded",
                error_code=None,
                output_bytes=output_bytes,
                metrics=metrics,
                safe_request_id=safe_request_id,
                preview=artifact,
            )
            if finished.preview_id != artifact.id:
                # Another process fenced this provider result while this
                # worker was validating it.  Do not leave an orphan file.
                _remove_preview_file(settings.resolved_data_root, artifact.relative_path)
            return finished
        except TTSGateError:
            _remove_preview_file(settings.resolved_data_root, artifact.relative_path)
            raise
        except Exception:
            _remove_preview_file(settings.resolved_data_root, artifact.relative_path)
            raise
    except TTSGateError:
        session.rollback()
        raise
    except Exception as exc:
        # Provider construction and unexpected adapter failures are not
        # allowed to leak details.  If dispatch already committed, make a
        # retry-free failed outcome where possible.
        session.rollback()
        raise TTSGateError("tts_response_invalid") from exc
    finally:
        session.close()


def run_operator_tts_gate(
    settings: Settings,
    *,
    allow_real: bool = False,
    database: Database | None = None,
    provider: TTSProvider | None = None,
) -> TTSGateResult:
    """Run or replay the one-shot operator TTS Gate.

    ``database`` and ``provider`` are injectable for isolated tests.  The
    normal caller supplies neither, in which case the reviewed provider
    factory is used.  The database is expected to already be at the current
    migration head; this function never writes ``.env`` or performs schema
    repair as part of an operator audio check.
    """

    _validate_operator_selectors(settings, allow_real=allow_real)
    data_root = settings.resolved_data_root
    owned_database = database is None
    active_database = database or Database(settings.database_url, data_root)
    try:
        with _tts_gate_lock(data_root):
            return _run_once(settings, active_database, provider=provider)
    finally:
        if owned_database:
            active_database.dispose()
