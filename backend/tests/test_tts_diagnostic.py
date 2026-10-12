from __future__ import annotations

import io
import math
import struct
import wave
from collections.abc import Callable, Iterator
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import StoredFile, VoicePreview, VoiceProfile, VoiceProviderOperation
from app.modules.voices.crypto import encrypt_external_voice_id
from app.modules.voices.service import TARGET_MODEL_KEY
from app.modules.voices.tts_diagnostic import (
    TTS_GATE_TEXT,
    TTSGateError,
    TTSGateResult,
    _new_operation,
    gate_hash_for_profile,
    gate_operation_id,
    run_operator_tts_gate,
)
from app.providers.audio import AudioValidationError, audio_quality_metrics
from app.providers.tts import TTSProviderError, TTSProviderTimeout, TTSResult
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def _valid_wav(seconds: float = 1.25) -> bytes:
    frames = int(24_000 * seconds)
    payload = bytearray()
    for index in range(frames):
        sample = int(4_000 * math.sin(2.0 * math.pi * 260 * index / 24_000))
        payload.extend(struct.pack("<h", sample))
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        stream.writeframes(payload)
    return output.getvalue()


class _FakeTTSProvider:
    key = "dashscope"
    target_model_key = TARGET_MODEL_KEY

    def __init__(self, mode: Literal["success", "failure", "timeout"] = "success") -> None:
        self.mode = mode
        self.calls: list[tuple[str, str, str]] = []

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
    ) -> TTSResult:
        del target_model_key
        self.calls.append((text, external_voice_id, language))
        if self.mode == "failure":
            raise TTSProviderError("provider detail must not escape")
        if self.mode == "timeout":
            raise TTSProviderTimeout("provider detail must not escape")
        return TTSResult(_valid_wav(), request_id="provider-request-is-not-public")


class _BlockingTTSProvider(_FakeTTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()
        self._call_lock = Lock()

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
    ) -> TTSResult:
        del target_model_key
        with self._call_lock:
            self.calls.append((text, external_voice_id, language))
        self.entered.set()
        assert self.release.wait(5)
        return TTSResult(_valid_wav(), request_id="provider-request-is-not-public")


@pytest.fixture
def gate_context(tmp_path: Path) -> Iterator[tuple[Database, Settings, str]]:
    profile_id = str(uuid4())
    settings = Settings(
        maya_env="test",
        session_secret="s" * 32,
        database_url="sqlite://",
        data_root=tmp_path,
        tts_provider="dashscope",
        voice_provider="mock",
        llm_provider="mock",
        embedding_provider="mock",
    )
    database = Database(settings.database_url, settings.data_root)
    database.initialize_schema()
    timestamp = datetime.now(UTC)
    profile = VoiceProfile(
        id=profile_id,
        scope="system",
        group_id=None,
        display_name="System English Fallback",
        status="preview_ready",
        provider_key="dashscope",
        target_model_key=TARGET_MODEL_KEY,
        external_id_encrypted=None,
        recovery_name=f"maya{profile_id.replace('-', '')[:12]}",
        provenance_json="{}",
        created_at=timestamp,
        updated_at=timestamp,
    )
    profile.external_id_encrypted = encrypt_external_voice_id(
        "opaque-external-id",
        settings.secret_bytes,
        profile_id=profile.id,
        scope=profile.scope,
        group_id=profile.group_id,
        provider_key=profile.provider_key,
        target_model_key=profile.target_model_key,
    )
    historical = VoiceProviderOperation(
        id=str(uuid4()),
        profile_id=profile.id,
        operation_type="tts_preview",
        profile_scope="system",
        state="failed",
        attempt=2,
        claim_token="historical-attempt-two",
        request_hash="h" * 64,
        provider_deadline=timestamp - timedelta(seconds=1),
        request_count=2,
        charged_request_count=2,
        input_bytes=123,
        output_bytes=0,
        safe_request_id=None,
        safe_error_code="provider_unavailable",
        completed_at=timestamp,
        created_at=timestamp - timedelta(minutes=1),
        updated_at=timestamp - timedelta(minutes=1),
    )
    with database.session() as session:
        session.add_all([profile, historical])
    try:
        yield database, settings, profile_id
    finally:
        database.dispose()


def _rows(database: Database, profile_id: str) -> list[VoiceProviderOperation]:
    with database.session() as session:
        return session.scalars(
            select(VoiceProviderOperation)
            .where(VoiceProviderOperation.profile_id == profile_id)
            .order_by(VoiceProviderOperation.attempt)
        ).all()


def _file_gate_context(tmp_path: Path) -> tuple[Database, Settings, str]:
    profile_id = str(uuid4())
    settings = Settings(
        maya_env="test",
        session_secret="s" * 32,
        database_url=f"sqlite:///{tmp_path / 'race.sqlite3'}",
        data_root=tmp_path,
        tts_provider="dashscope",
        voice_provider="mock",
        llm_provider="mock",
        embedding_provider="mock",
    )
    database = Database(settings.database_url, settings.data_root)
    database.initialize_schema()
    timestamp = datetime.now(UTC)
    profile = VoiceProfile(
        id=profile_id,
        scope="system",
        group_id=None,
        display_name="System English Fallback",
        status="preview_ready",
        provider_key="dashscope",
        target_model_key=TARGET_MODEL_KEY,
        external_id_encrypted=None,
        recovery_name=f"maya{profile_id.replace('-', '')[:12]}",
        provenance_json="{}",
        created_at=timestamp,
        updated_at=timestamp,
    )
    profile.external_id_encrypted = encrypt_external_voice_id(
        "opaque-external-id",
        settings.secret_bytes,
        profile_id=profile.id,
        scope=profile.scope,
        group_id=profile.group_id,
        provider_key=profile.provider_key,
        target_model_key=profile.target_model_key,
    )
    historical = VoiceProviderOperation(
        id=str(uuid4()),
        profile_id=profile.id,
        operation_type="tts_preview",
        profile_scope="system",
        state="failed",
        attempt=2,
        claim_token="historical-attempt-two",
        request_hash="h" * 64,
        provider_deadline=timestamp - timedelta(seconds=1),
        request_count=2,
        charged_request_count=2,
        safe_error_code="provider_unavailable",
        completed_at=timestamp,
        created_at=timestamp - timedelta(minutes=1),
        updated_at=timestamp - timedelta(minutes=1),
    )
    with database.session() as session:
        session.add_all([profile, historical])
    return database, settings, profile_id


def test_attempt_three_success_promotes_once_and_replays_without_provider(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    provider = _FakeTTSProvider()

    first = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert first.status == "ready"
    assert first.attempt == 3
    assert first.metrics is not None
    assert first.metrics["duration_seconds"] >= 1.0
    assert first.metrics["rms"] >= 100
    assert first.output_bytes > 0
    assert first.preview_id is not None
    assert len(provider.calls) == 1
    assert provider.calls[0][0] == TTS_GATE_TEXT
    assert provider.calls[0][2] == "en"

    rows = _rows(database, profile_id)
    assert [row.attempt for row in rows] == [2, 3]
    assert rows[0].state == "failed"
    assert rows[0].request_count == 2
    assert rows[0].charged_request_count == 2
    assert rows[1].state == "succeeded"
    assert rows[1].request_count == 1
    assert rows[1].charged_request_count == 1
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert profile.status == "ready"
        preview = session.get(VoicePreview, first.preview_id)
        assert preview is not None
        assert preview.state == "active"
        assert preview.relative_path is not None
        stored = session.get(StoredFile, preview.stored_file_id)
        assert stored is not None
        assert stored.state == "active"
        assert (settings.resolved_data_root / preview.relative_path).is_file()

    replay = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert replay.status == "ready"
    assert replay.operation_id == first.operation_id
    assert len(provider.calls) == 1


def test_attempt_three_provider_failure_is_retry_free_and_keeps_preview_ready(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    provider = _FakeTTSProvider("failure")

    result = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert result.status == "failed"
    assert result.error_code == "tts_response_invalid"
    assert len(provider.calls) == 1
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert profile.status == "preview_ready"
        assert profile.safe_error_code == "tts_response_invalid"
    rows = _rows(database, profile_id)
    assert rows[-1].attempt == 3
    assert rows[-1].state == "failed"
    assert rows[-1].request_count == 1
    assert rows[-1].charged_request_count == 1

    replay = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert replay.status == "failed"
    assert len(provider.calls) == 1


def test_truncated_attempt_three_audio_never_promotes_or_stores_preview(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context

    class TruncatedProvider(_FakeTTSProvider):
        def synthesize(
            self,
            text: str,
            external_voice_id: str,
            *,
            language: str = "en",
            target_model_key: str | None = None,
        ) -> TTSResult:
            del target_model_key
            self.calls.append((text, external_voice_id, language))
            return TTSResult(_valid_wav()[:-1], request_id="truncated-provider-result")

    provider = TruncatedProvider()
    result = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert result.status == "failed"
    assert result.error_code == "tts_audio_invalid"
    assert len(provider.calls) == 1
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert profile.status == "preview_ready"
        assert profile.safe_error_code == "tts_audio_invalid"
        assert (
            session.scalar(
                select(VoicePreview).where(
                    VoicePreview.profile_id == profile_id,
                    VoicePreview.state == "active",
                )
            )
            is None
        )
        assert (
            session.scalar(
                select(StoredFile).where(
                    StoredFile.kind == "voice_preview",
                    StoredFile.state == "active",
                )
            )
            is None
        )
    preview_root = settings.resolved_data_root / "system" / "voices" / "previews"
    if preview_root.exists():
        assert not list(preview_root.glob("*.wav"))


@pytest.mark.parametrize("raw_factory", [lambda: _valid_wav()[:-1], lambda: _valid_wav() + b"tail"])
def test_audio_metrics_reject_truncation_and_malformed_tail(
    raw_factory: Callable[[], bytes],
) -> None:
    raw = raw_factory()
    with pytest.raises(AudioValidationError):
        audio_quality_metrics(raw)


def test_attempt_three_timeout_is_unknown_and_never_retried(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    provider = _FakeTTSProvider("timeout")

    result = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert result.status == "outcome_unknown"
    assert result.error_code == "tts_timeout"
    assert len(provider.calls) == 1
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert profile.status == "preview_ready"
        assert profile.safe_error_code == "tts_timeout"
    rows = _rows(database, profile_id)
    assert rows[-1].state == "outcome_unknown"
    assert rows[-1].request_count == 1
    assert rows[-1].charged_request_count == 1

    replay = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert replay.status == "outcome_unknown"
    assert replay.error_code == "tts_timeout"
    assert len(provider.calls) == 1


def test_gate_requires_explicit_authorization_without_touching_ledger(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    provider = _FakeTTSProvider()
    with pytest.raises(TTSGateError) as error:
        run_operator_tts_gate(settings, database=database, provider=provider)
    assert error.value.safe_code == "tts_response_invalid"
    assert len(provider.calls) == 0
    assert [row.attempt for row in _rows(database, profile_id)] == [2]


def test_gate_rejects_non_tts_real_selector_before_creating_attempt_three(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    conflicting = settings.model_copy(update={"voice_provider": "dashscope"})
    provider = _FakeTTSProvider()
    with pytest.raises(TTSGateError) as error:
        run_operator_tts_gate(conflicting, allow_real=True, database=database, provider=provider)
    assert error.value.safe_code == "tts_response_invalid"
    assert len(provider.calls) == 0
    assert [row.attempt for row in _rows(database, profile_id)] == [2]


def test_stale_attempt_three_is_marked_unknown_without_demoting_profile(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        timestamp = datetime.now(UTC)
        session.add(
            VoiceProviderOperation(
                id=gate_operation_id(profile),
                profile_id=profile.id,
                operation_type="tts_preview",
                profile_scope="system",
                state="prepared",
                attempt=3,
                claim_token="stale-gate",
                request_hash=gate_hash_for_profile(profile),
                provider_deadline=timestamp + timedelta(seconds=35),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    provider = _FakeTTSProvider()
    result = run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert result.status == "outcome_unknown"
    assert result.error_code == "tts_outcome_unknown"
    assert len(provider.calls) == 0
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert profile.status == "preview_ready"
        assert profile.safe_error_code == "tts_outcome_unknown"


def test_database_primary_key_claim_wins_without_provider_call(tmp_path: Path) -> None:
    database, settings, profile_id = _file_gate_context(tmp_path)
    database.dispose()
    first_database = Database(settings.database_url, settings.data_root)
    second_database = Database(settings.database_url, settings.data_root)
    first_session = first_database.session_factory()
    second_session = second_database.session_factory()
    try:
        first_profile = first_session.get(VoiceProfile, profile_id)
        second_profile = second_session.get(VoiceProfile, profile_id)
        assert first_profile is not None and second_profile is not None
        request_hash = gate_hash_for_profile(first_profile)
        first_operation = _new_operation(
            first_profile,
            request_hash,
            gate_operation_id(first_profile, request_hash),
        )
        second_operation = _new_operation(
            second_profile,
            request_hash,
            gate_operation_id(second_profile, request_hash),
        )
        first_session.add(first_operation)
        first_session.commit()
        second_session.add(second_operation)
        with pytest.raises(IntegrityError):
            second_session.commit()
        second_session.rollback()
        winner = second_session.get(
            VoiceProviderOperation, gate_operation_id(second_profile, request_hash)
        )
        assert winner is not None
        assert winner.attempt == 3
        assert winner.request_hash == request_hash
        rows = second_session.scalars(
            select(VoiceProviderOperation)
            .where(
                VoiceProviderOperation.profile_id == profile_id,
                VoiceProviderOperation.operation_type == "tts_preview",
            )
            .order_by(VoiceProviderOperation.attempt)
        ).all()
        assert sorted(row.attempt for row in rows) == [2, 3]
        assert rows[0].request_count == 2
        assert rows[0].charged_request_count == 2
    finally:
        first_session.close()
        second_session.close()
        first_database.dispose()
        second_database.dispose()


def test_concurrent_gate_has_one_claim_and_one_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, settings, profile_id = _file_gate_context(tmp_path)
    database.dispose()
    # The DB primary-key fence remains authoritative even when the host lock
    # is unavailable (for example, two independent operator containers).
    monkeypatch.setattr(
        "app.modules.voices.tts_diagnostic._tts_gate_lock",
        lambda _root: nullcontext(),
    )
    provider = _BlockingTTSProvider()
    results: list[TTSGateResult | BaseException] = []
    result_lock = Lock()

    def run(database_url: str) -> None:
        active = Database(database_url, settings.data_root)
        try:
            value = run_operator_tts_gate(
                settings, allow_real=True, database=active, provider=provider
            )
            with result_lock:
                results.append(value)
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            with result_lock:
                results.append(exc)
        finally:
            active.dispose()

    first = Thread(target=run, args=(settings.database_url,))
    first.start()
    assert provider.entered.wait(5)
    second = Thread(target=run, args=(settings.database_url,))
    second.start()
    second.join(5)
    provider.release.set()
    first.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert len(provider.calls) == 1
    assert len(results) == 2
    assert all(isinstance(value, TTSGateResult) for value in results)
    assert {value.status for value in results if isinstance(value, TTSGateResult)} == {
        "outcome_unknown"
    }
    check_database = Database(settings.database_url, settings.data_root)
    try:
        with check_database.session() as session:
            profile = session.get(VoiceProfile, profile_id)
            assert profile is not None
            assert profile.status == "preview_ready"
            assert profile.safe_error_code == "tts_outcome_unknown"
            rows = session.scalars(
                select(VoiceProviderOperation)
                .where(
                    VoiceProviderOperation.profile_id == profile_id,
                    VoiceProviderOperation.operation_type == "tts_preview",
                )
                .order_by(VoiceProviderOperation.attempt)
            ).all()
            assert sorted(row.attempt for row in rows) == [2, 3]
            assert rows[0].request_count == 2
            assert rows[0].charged_request_count == 2
            assert rows[1].request_count == 1
            assert rows[1].charged_request_count == 1
            assert rows[1].state == "outcome_unknown"
    finally:
        check_database.dispose()


def test_gate_hash_mismatch_stops_without_provider_call(
    gate_context: tuple[Database, Settings, str],
) -> None:
    database, settings, profile_id = gate_context
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        timestamp = datetime.now(UTC)
        session.add(
            VoiceProviderOperation(
                id=str(uuid4()),
                profile_id=profile.id,
                operation_type="tts_preview",
                profile_scope="system",
                state="prepared",
                attempt=3,
                claim_token="unexpected-gate",
                request_hash="x" * 64,
                provider_deadline=timestamp + timedelta(seconds=35),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    provider = _FakeTTSProvider()
    with pytest.raises(TTSGateError) as error:
        run_operator_tts_gate(settings, allow_real=True, database=database, provider=provider)
    assert error.value.safe_code == "tts_response_invalid"
    assert len(provider.calls) == 0
    with database.session() as session:
        profile = session.get(VoiceProfile, profile_id)
        assert profile is not None
        assert gate_hash_for_profile(profile) != "x" * 64
