"""Two-stage, operator-only enrollment of the immutable system fallback voice.

The fallback is deliberately split into two explicit commands:

* ``enroll`` may call only the configured ``VoiceCloneProvider`` and leaves a
  successful profile in ``preview_ready``;
* ``verify`` may call only the configured ``TTSProvider`` and promotes that
  profile to ``ready`` after a bounded technical preview check.

The separation is important when a provider account charges both operations:
the command never turns a voice enrollment into an implicit TTS call, and an
ambiguous enrollment is reconciled by ``exists`` before any new create is
considered.  The source is copied through the same controlled temporary
pipeline as student enrollment and is never modified by this module.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.models import VoiceProfile, VoiceProviderOperation
from app.modules.knowledge.files import contained_path, ensure_private_dir
from app.modules.voices.crypto import VoiceEncryptionError, encrypt_external_voice_id
from app.modules.voices.lease_lock import lock_exclusive, unlock
from app.modules.voices.preset import is_preset_profile
from app.modules.voices.service import (
    PREVIEW_TEXT,
    TARGET_MODEL_KEY,
    _new_recovery_name,
    now_utc,
)
from app.modules.voices.service import (
    _profile_external_id as decrypt_profile_external_id,
)
from app.providers.audio import (
    AudioValidationError,
    audio_quality_metrics,
    read_pcm16_wav,
    run_ffmpeg_normalize,
    validate_source_audio,
    validate_technical_audio,
)
from app.providers.factory import tts_provider, voice_provider
from app.providers.tts import TTSProviderError
from app.providers.voice import VoiceCloneProvider, VoiceProviderError, VoiceProviderTimeout

FallbackStage = Literal["enroll", "verify"]
MAX_SOURCE_BYTES = 10 * 1024 * 1024
TTS_OPERATION_TYPE = "tts_preview"
OPERATION_STATES = ("prepared", "dispatched", "reconciling")


class FallbackEnrollmentError(RuntimeError):
    """Safe operator error; source paths and provider details stay private."""


@contextmanager
def _fallback_lock(data_root: Path) -> Iterator[None]:
    """Serialize the one authorized fallback command on this host."""

    lock_path = data_root / "tmp" / "system-fallback.lock"
    ensure_private_dir(lock_path.parent)
    try:
        handle = lock_path.open("a+b")
        lock_path.chmod(0o600)
    except OSError as exc:
        raise FallbackEnrollmentError("fallback lock unavailable") from exc
    try:
        try:
            lock_exclusive(handle)
        except OSError as exc:
            raise FallbackEnrollmentError("fallback enrollment is already running") from exc
        yield
    finally:
        try:
            unlock(handle)
        except OSError:
            pass
        handle.close()


def _validate_stage_provider(settings: Settings, stage: FallbackStage, allow_real: bool) -> None:
    """Fail closed before any source/provider side effect for a stage."""

    try:
        settings.validate_provider_configuration()
    except RuntimeError as exc:
        raise FallbackEnrollmentError("provider configuration is not allowed") from exc
    if stage == "enroll":
        # Voice enrollment is the only operation allowed to be real in this
        # stage.  TTS must remain Mock even though no TTS call is made here.
        if settings.llm_provider != "mock" or settings.tts_provider != "mock":
            raise FallbackEnrollmentError("enroll stage permits only the voice provider")
        if settings.voice_provider == "dashscope" and not allow_real:
            raise FallbackEnrollmentError("use --allow-real for a real voice provider")
        if settings.voice_provider == "mock" and allow_real:
            raise FallbackEnrollmentError("real fallback requires DashScope voice provider")
    else:
        # Verify only synthesizes a preview.  It must never call VoiceClone or
        # LLM, and a real TTS call is always an explicit operator choice.
        if settings.llm_provider != "mock" or settings.voice_provider != "mock":
            raise FallbackEnrollmentError("verify stage permits only the TTS provider")
        if settings.tts_provider == "dashscope" and not allow_real:
            raise FallbackEnrollmentError("use --allow-real for a real TTS provider")


@contextmanager
def _normalised_source(settings: Settings, source: Path) -> Iterator[tuple[bytes, str]]:
    """Yield normalized bytes/hash and always remove the UUID request tree."""

    source = source.expanduser()
    if source.is_symlink() or not source.is_file():
        raise FallbackEnrollmentError("fallback source is unavailable")
    try:
        source_size = source.stat().st_size
    except OSError as exc:
        raise FallbackEnrollmentError("fallback source is unavailable") from exc
    if source_size <= 0 or source_size > MAX_SOURCE_BYTES:
        raise FallbackEnrollmentError("fallback source is invalid")
    temporary_root = settings.resolved_data_root / "tmp" / "voice-enrollment"
    ensure_private_dir(temporary_root)
    request_id = str(uuid4())
    directory = contained_path(temporary_root, request_id)
    if directory.exists() or directory.is_symlink():
        raise FallbackEnrollmentError("fallback temporary directory is unavailable")
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    marker = directory / ".active"
    active_lease = None
    source_copy = directory / "source.upload"
    normalized = directory / "normalized.wav"
    try:
        active_lease = marker.open("xb")
        marker.chmod(0o600)
        lock_exclusive(active_lease)
        digest = hashlib.sha256()
        copied = 0
        with source.open("rb") as input_stream, source_copy.open("xb") as output_stream:
            while True:
                chunk = input_stream.read(64 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_SOURCE_BYTES:
                    raise FallbackEnrollmentError("fallback source is too large")
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
        source_copy.chmod(0o600)
        source_info = validate_source_audio(source_copy, source.name)
        run_ffmpeg_normalize(
            source_copy,
            normalized,
            duration_seconds=(
                source_info.duration_seconds if "m4a" in source_info.format_names else None
            ),
        )
        normalized_bytes = read_pcm16_wav(normalized)
        metrics = audio_quality_metrics(normalized_bytes)
        if not 10.0 <= metrics["duration_seconds"] <= 20.0:
            raise FallbackEnrollmentError("fallback source is invalid")
        yield normalized_bytes, digest.hexdigest()
    except (AudioValidationError, OSError) as exc:
        raise FallbackEnrollmentError("fallback source or normalization failed") from exc
    finally:
        if active_lease is not None and not active_lease.closed:
            try:
                unlock(active_lease)
            finally:
                active_lease.close()
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        if directory.exists() or directory.is_symlink():
            if directory.is_dir() and not directory.is_symlink():
                shutil.rmtree(directory)


def _profile_external_id(profile: VoiceProfile, settings: Settings) -> str:
    try:
        return decrypt_profile_external_id(profile, settings)
    except VoiceEncryptionError as exc:
        raise FallbackEnrollmentError("fallback mapping is unavailable") from exc


def _system_profile(session: Session) -> VoiceProfile | None:
    # A preset shares the system scope but is not the enrolled fallback.
    # Counting it would make one fallback look ambiguous.
    profiles = [
        profile
        for profile in session.scalars(
            select(VoiceProfile)
            .where(VoiceProfile.scope == "system")
            .order_by(VoiceProfile.created_at)
        ).all()
        if not is_preset_profile(profile)
    ]
    if len(profiles) > 1:
        raise FallbackEnrollmentError("system fallback state is ambiguous")
    return profiles[0] if profiles else None


def _operation(
    session: Session,
    profile_id: str,
    operation_type: str,
) -> VoiceProviderOperation | None:
    return session.scalar(
        select(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.profile_id == profile_id,
            VoiceProviderOperation.operation_type == operation_type,
        )
        .order_by(VoiceProviderOperation.created_at.desc())
    )


def _new_operation(
    profile: VoiceProfile,
    operation_type: str,
    request_hash: str,
    *,
    attempt: int = 1,
) -> VoiceProviderOperation:
    timestamp = now_utc()
    return VoiceProviderOperation(
        id=str(uuid4()),
        profile_id=profile.id,
        operation_type=operation_type,
        profile_scope="system",
        state="prepared",
        attempt=attempt,
        claim_token=uuid4().hex,
        request_hash=request_hash,
        provider_deadline=timestamp + timedelta(seconds=35),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _dispatch(
    session: Session,
    operation: VoiceProviderOperation,
    *,
    charged: bool,
) -> None:
    timestamp = now_utc()
    changed = session.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.state == "prepared",
            VoiceProviderOperation.attempt == operation.attempt,
            VoiceProviderOperation.claim_token == operation.claim_token,
        )
        .values(
            state="dispatched",
            request_count=VoiceProviderOperation.request_count + 1,
            charged_request_count=VoiceProviderOperation.charged_request_count + int(charged),
            dispatched_at=timestamp,
            updated_at=timestamp,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        raise FallbackEnrollmentError("fallback operation is no longer available")
    session.commit()


def _finish(
    session: Session,
    operation: VoiceProviderOperation,
    *,
    state: str,
    safe_error_code: str | None = None,
    output_bytes: int = 0,
) -> None:
    timestamp = now_utc()
    changed = session.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.state.in_(OPERATION_STATES),
            VoiceProviderOperation.attempt == operation.attempt,
            VoiceProviderOperation.claim_token == operation.claim_token,
        )
        .values(
            state=state,
            safe_error_code=safe_error_code,
            output_bytes=output_bytes,
            completed_at=timestamp if state in {"succeeded", "failed"} else None,
            updated_at=timestamp,
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        session.rollback()
        raise FallbackEnrollmentError("fallback operation is no longer owned")
    session.commit()


def _mark_unknown(
    session: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    safe_error_code: str = "provider_unavailable",
) -> None:
    profile.status = "outcome_unknown"
    profile.safe_error_code = safe_error_code
    _finish(session, operation, state="outcome_unknown", safe_error_code=safe_error_code)


def _reconcile_existing(
    session: Session,
    profile: VoiceProfile,
    operation: VoiceProviderOperation,
    provider: VoiceCloneProvider,
    settings: Settings,
) -> str:
    """Use exists/list only; no create is allowed on zero/multiple matches."""

    changed = session.execute(
        update(VoiceProviderOperation)
        .where(
            VoiceProviderOperation.id == operation.id,
            VoiceProviderOperation.state.in_(
                ("prepared", "dispatched", "reconciling", "outcome_unknown")
            ),
            VoiceProviderOperation.attempt == operation.attempt,
            VoiceProviderOperation.claim_token == operation.claim_token,
        )
        .values(
            state="reconciling",
            request_count=VoiceProviderOperation.request_count + 1,
            updated_at=now_utc(),
        )
    )
    if getattr(changed, "rowcount", 0) != 1:
        session.rollback()
        raise FallbackEnrollmentError("fallback operation is no longer owned")
    session.commit()
    try:
        result = provider.exists(profile.recovery_name, target_model_key=profile.target_model_key)
    except (VoiceProviderTimeout, VoiceProviderError) as exc:
        _mark_unknown(session, profile, operation)
        raise FallbackEnrollmentError("fallback enrollment outcome is uncertain") from exc
    if not result.visibility_known or len(result.matches) != 1:
        _mark_unknown(session, profile, operation, "voice_enrollment_failed")
        raise FallbackEnrollmentError("fallback enrollment outcome is uncertain")
    try:
        profile.external_id_encrypted = encrypt_external_voice_id(
            result.matches[0],
            settings.secret_bytes,
            profile_id=profile.id,
            scope=profile.scope,
            group_id=profile.group_id,
            provider_key=profile.provider_key,
            target_model_key=profile.target_model_key,
        )
    except VoiceEncryptionError as exc:
        _mark_unknown(session, profile, operation, "voice_mapping_unavailable")
        raise FallbackEnrollmentError("fallback mapping failed") from exc
    profile.status = "preview_ready"
    profile.safe_error_code = None
    profile.updated_at = now_utc()
    _finish(session, operation, state="succeeded")
    return profile.id


def _enroll_new(
    session: Session,
    settings: Settings,
    provider: VoiceCloneProvider,
    normalized_bytes: bytes,
    source_hash: str,
    *,
    allow_real: bool,
) -> str:
    timestamp = now_utc()
    profile_id = str(uuid4())
    profile = VoiceProfile(
        id=profile_id,
        scope="system",
        group_id=None,
        display_name="System English Fallback",
        status="enrolling",
        provider_key=provider.key,
        target_model_key=getattr(provider, "target_model_key", TARGET_MODEL_KEY),
        external_id_encrypted=None,
        recovery_name=_new_recovery_name(profile_id),
        provenance_json="{}",
        source_filename=None,
        source_sha256=None,
        consent_copy_version=None,
        consent_actor_user_id=None,
        consent_accepted_at=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    operation = _new_operation(profile, "enroll", source_hash)
    session.add_all([profile, operation])
    session.commit()
    _dispatch(session, operation, charged=allow_real)
    encoded = base64.b64encode(normalized_bytes).decode("ascii")
    data_uri = "data:audio/wav;base64," + encoded
    try:
        result = provider.enroll(
            data_uri,
            recovery_name=profile.recovery_name,
            target_model_key=profile.target_model_key,
            language="en",
        )
    except (VoiceProviderTimeout, VoiceProviderError) as exc:
        _mark_unknown(session, profile, operation)
        raise FallbackEnrollmentError("fallback provider failed") from exc
    finally:
        encoded = ""
        data_uri = ""
    try:
        profile.external_id_encrypted = encrypt_external_voice_id(
            result.external_voice_id,
            settings.secret_bytes,
            profile_id=profile.id,
            scope=profile.scope,
            group_id=profile.group_id,
            provider_key=profile.provider_key,
            target_model_key=profile.target_model_key,
        )
    except VoiceEncryptionError as exc:
        _mark_unknown(session, profile, operation, "voice_mapping_unavailable")
        raise FallbackEnrollmentError("fallback mapping failed") from exc
    profile.status = "failed" if result.degraded else "preview_ready"
    profile.safe_error_code = "voice_enrollment_failed" if result.degraded else None
    profile.updated_at = now_utc()
    operation.safe_request_id = result.request_id
    operation.input_bytes = result.input_bytes
    operation.output_bytes = result.output_bytes
    _finish(session, operation, state="succeeded", output_bytes=result.output_bytes)
    if result.degraded:
        raise FallbackEnrollmentError("fallback enrollment quality check failed")
    return profile.id


def _enroll_stage(settings: Settings, source: Path, *, allow_real: bool) -> str:
    _validate_stage_provider(settings, "enroll", allow_real)
    data_root = settings.resolved_data_root
    with _fallback_lock(data_root):
        database = Database(settings.database_url, data_root)
        try:
            database.upgrade_schema()
            with database.session() as session:
                profile = _system_profile(session)
                if profile is not None:
                    if profile.status in {"preview_ready", "ready"}:
                        _profile_external_id(profile, settings)
                        return profile.id
                    provider = voice_provider(settings)
                    operation = _operation(session, profile.id, "enroll")
                    if operation is None:
                        operation = _new_operation(
                            profile,
                            "exists",
                            hashlib.sha256(profile.recovery_name.encode()).hexdigest(),
                        )
                        session.add(operation)
                        session.commit()
                    return _reconcile_existing(session, profile, operation, provider, settings)
                provider = voice_provider(settings)
                with _normalised_source(settings, source) as (normalized, source_hash):
                    return _enroll_new(
                        session,
                        settings,
                        provider,
                        normalized,
                        source_hash,
                        allow_real=allow_real,
                    )
        except FallbackEnrollmentError:
            raise
        except (IntegrityError, OSError) as exc:
            raise FallbackEnrollmentError("fallback state is unavailable") from exc
        finally:
            database.dispose()


def _tts_request_hash(profile: VoiceProfile) -> str:
    return hashlib.sha256(f"fallback-preview:{profile.id}".encode()).hexdigest()


def _verify_stage(settings: Settings, *, allow_real: bool) -> str:
    _validate_stage_provider(settings, "verify", allow_real)
    data_root = settings.resolved_data_root
    with _fallback_lock(data_root):
        database = Database(settings.database_url, data_root)
        try:
            database.upgrade_schema()
            with database.session() as session:
                profile = _system_profile(session)
                if profile is None:
                    raise FallbackEnrollmentError("system fallback enrollment is required first")
                if profile.status == "ready":
                    _profile_external_id(profile, settings)
                    return profile.id
                if profile.status != "preview_ready":
                    raise FallbackEnrollmentError("system fallback is not ready for verification")
                external_id = _profile_external_id(profile, settings)
                operation = _operation(session, profile.id, TTS_OPERATION_TYPE)
                if operation is not None:
                    if operation.state == "succeeded":
                        profile.status = "ready"
                        profile.safe_error_code = None
                        session.commit()
                        return profile.id
                    if operation.state in {"dispatched", "reconciling", "outcome_unknown"}:
                        raise FallbackEnrollmentError("fallback preview outcome is uncertain")
                    if operation.state == "failed" and operation.attempt >= 2:
                        raise FallbackEnrollmentError("fallback preview verification failed")
                    if operation.state == "failed":
                        operation.state = "prepared"
                        operation.claim_token = uuid4().hex
                        operation.updated_at = now_utc()
                        session.commit()
                if operation is None:
                    operation = _new_operation(
                        profile, TTS_OPERATION_TYPE, _tts_request_hash(profile)
                    )
                    session.add(operation)
                    session.commit()
                tts = tts_provider(settings)
                max_attempts = 2
                while operation.attempt <= max_attempts:
                    _dispatch(session, operation, charged=getattr(tts, "key", "mock") != "mock")
                    try:
                        result = tts.synthesize(
                            PREVIEW_TEXT,
                            external_id,
                            language="en",
                            target_model_key=profile.target_model_key,
                        )
                        validate_technical_audio(result.audio_bytes)
                    except (TTSProviderError, AudioValidationError, OSError) as exc:
                        if operation.attempt >= max_attempts:
                            profile.status = "preview_ready"
                            profile.safe_error_code = "provider_unavailable"
                            _finish(
                                session,
                                operation,
                                state="failed",
                                safe_error_code="provider_unavailable",
                            )
                            raise FallbackEnrollmentError(
                                "fallback preview verification failed"
                            ) from exc
                        operation.state = "prepared"
                        operation.attempt += 1
                        operation.claim_token = uuid4().hex
                        operation.provider_deadline = now_utc() + timedelta(seconds=35)
                        operation.updated_at = now_utc()
                        session.commit()
                        continue
                    operation.safe_request_id = result.request_id
                    operation.output_bytes = len(result.audio_bytes)
                    profile.status = "ready"
                    profile.safe_error_code = None
                    profile.updated_at = now_utc()
                    _finish(
                        session,
                        operation,
                        state="succeeded",
                        output_bytes=len(result.audio_bytes),
                    )
                    return profile.id
                raise FallbackEnrollmentError("fallback preview verification failed")
        except FallbackEnrollmentError:
            raise
        except (IntegrityError, OSError) as exc:
            raise FallbackEnrollmentError("fallback state is unavailable") from exc
        finally:
            database.dispose()


def enroll_system_fallback(
    settings: Settings,
    source: Path | None = None,
    *,
    allow_real: bool = False,
    stage: FallbackStage = "enroll",
) -> str:
    """Run the explicit fallback ``enroll`` or ``verify`` operator stage."""

    if stage not in {"enroll", "verify"}:
        raise FallbackEnrollmentError("fallback stage is not supported")
    if stage == "enroll":
        if source is None:
            raise FallbackEnrollmentError("fallback source is required for enrollment")
        return _enroll_stage(settings, source, allow_real=allow_real)
    return _verify_stage(settings, allow_real=allow_real)
