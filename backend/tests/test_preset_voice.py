"""Preset TTS voices: per-profile model, Plato binding, and no clone deletion."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import VoiceProfile, VoiceProviderOperation
from app.modules.demo_baseline.service import (
    BASELINE_LAOZI,
    BASELINE_PLATO,
    BASELINE_SOCRATES,
    ensure_demo_baseline,
)
from app.modules.voices.crypto import encrypt_external_voice_id
from app.modules.voices.deletion import _reconcile_delete
from app.modules.voices.fallback import _system_profile
from app.modules.voices.preset import (
    ELDRIC_SAGE_PROFILE_ID,
    ELDRIC_SAGE_VOICE,
    ensure_eldricsage_preset,
    is_preset_profile,
)
from app.modules.voices.service import _reconcile_enrollment
from app.providers.dashscope import (
    DEFAULT_TARGET_MODEL_KEY,
    PRESET_TTS_MODEL_KEY,
    DashScopeConfig,
    DashScopeTTSProvider,
)
from app.providers.tts import TTSProviderError, TTSResult
from app.seed import GROUP_DEMO_ID, seed_uuid
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import login
from tests.test_task_20260924_001a import _parse_sse, _stream
from tests.test_wave1b_voices import _headers, _wav


class _CaptureClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> _CaptureClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append({"url": url, "json": kwargs.get("json")})
        return httpx.Response(
            200,
            json=self.payload,
            request=httpx.Request("POST", url),
        )


class _RecordingTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str | None]] = []

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
    ) -> TTSResult:
        self.calls.append((text, external_voice_id, language, target_model_key))
        return TTSResult(audio_bytes=_wav(1), content_type="audio/wav", request_id="preset-tts")


class _CloneSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def exists(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("exists")
        raise AssertionError("preset profiles are not clone-checked")

    def delete(self, *_args: object, **_kwargs: object) -> None:
        self.calls.append("delete")
        raise AssertionError("preset profiles are not deleted at the provider")


def _settings(tmp_path: Path, *, url: str) -> Settings:
    return Settings(
        maya_env="test",
        session_secret="p" * 32,
        database_url=url,
        data_root=tmp_path,
        tts_provider="mock",
        voice_provider="mock",
        llm_provider="mock",
        embedding_provider="mock",
    )


def _fallback_row(profile_id: str) -> VoiceProfile:
    timestamp = datetime.now(UTC)
    return VoiceProfile(
        id=profile_id,
        scope="system",
        group_id=None,
        display_name="System English Fallback",
        status="ready",
        provider_key="mock",
        target_model_key="mock-tts-v1",
        external_id_encrypted=None,
        recovery_name=f"maya{profile_id.replace('-', '')[:12]}",
        provenance_json="{}",
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_documented_preset_id_matches_the_seed_namespace() -> None:
    assert seed_uuid("preset-voice-eldricsage") == ELDRIC_SAGE_PROFILE_ID


def test_tts_call_uses_the_profile_model_and_refuses_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = DashScopeConfig(api_key="fixture", workspace_id="workspace123")

    def refused_client() -> _CaptureClient:
        raise AssertionError("a disallowed TTS model must not open a client")

    monkeypatch.setattr("app.providers.dashscope._client", refused_client)
    with pytest.raises(TTSProviderError) as rejected:
        DashScopeTTSProvider(config).synthesize(
            "A sentence.",
            ELDRIC_SAGE_VOICE,
            language="en",
            target_model_key="qwen3-tts-flash-2025-09-18",
        )
    assert rejected.value.safe_code == "tts_response_invalid"

    audio = {
        "output": {
            "audio": {"url": "https://example.test/preview.wav"}
        },
        "request_id": "tts-request",
    }
    flash = _CaptureClient(audio)
    monkeypatch.setattr("app.providers.dashscope._client", lambda: flash)

    class _Downloader:
        def download(self, _url: str) -> bytes:
            return _wav(2)

    provider = DashScopeTTSProvider(config, downloader=_Downloader())
    provider.synthesize(
        "A steady sentence.",
        ELDRIC_SAGE_VOICE,
        language="zh",
        target_model_key=PRESET_TTS_MODEL_KEY,
    )
    assert flash.calls[0]["json"] == {
        "model": PRESET_TTS_MODEL_KEY,
        "input": {
            "text": "A steady sentence.",
            "voice": ELDRIC_SAGE_VOICE,
            "language_type": "Chinese",
        },
    }

    clone = _CaptureClient(audio)
    monkeypatch.setattr("app.providers.dashscope._client", lambda: clone)
    provider.synthesize("A cloned sentence.", "clone-voice-id", language="en")
    assert clone.calls[0]["json"] == {
        "model": DEFAULT_TARGET_MODEL_KEY,
        "input": {
            "text": "A cloned sentence.",
            "voice": "clone-voice-id",
            "language_type": "English",
        },
    }


@pytest.mark.parametrize("migrate", [False, True])
def test_preset_seed_is_idempotent_and_keeps_the_fallback(tmp_path: Path, migrate: bool) -> None:
    url = f"sqlite:///{tmp_path / 'preset.sqlite3'}"
    settings = _settings(tmp_path, url=url)
    database = Database(url, tmp_path)
    if migrate:
        database.upgrade_schema()
    else:
        database.initialize_schema()
    fallback_id = str(uuid4())
    with database.session() as session:
        session.add(_fallback_row(fallback_id))
        first = ensure_eldricsage_preset(session, settings)
        assert first == ELDRIC_SAGE_PROFILE_ID
        stored = session.get(VoiceProfile, first)
        assert stored is not None
        ciphertext = stored.external_id_encrypted
        assert ciphertext
        assert ELDRIC_SAGE_VOICE.encode() not in ciphertext
        assert stored.consent_actor_user_id is None
        assert stored.consent_copy_version is None
        assert stored.consent_accepted_at is None
        assert stored.group_id is None
        assert is_preset_profile(stored)
        assert not is_preset_profile(_fallback_row(str(uuid4())))
    with database.session() as session:
        assert ensure_eldricsage_preset(session, settings) == first
        again = session.get(VoiceProfile, first)
        assert again is not None
        assert again.external_id_encrypted == ciphertext
        fallback = _system_profile(session)
        assert fallback is not None
        assert fallback.id == fallback_id
        assert (
            session.execute(
                text("SELECT COUNT(*) FROM voice_profiles WHERE scope = 'system'")
            ).scalar_one()
            == 2
        )
    database.dispose()


def test_preset_is_excluded_from_clone_deletion(
    tmp_path: Path,
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        with database.session() as session:
            ensure_eldricsage_preset(session, settings)
            profile = session.get(VoiceProfile, ELDRIC_SAGE_PROFILE_ID)
            assert profile is not None
            operation = VoiceProviderOperation(
                id=str(uuid4()),
                profile_id=profile.id,
                operation_type="delete",
                profile_scope="system",
                state="dispatched",
                attempt=1,
                claim_token="preset-delete-claim",
                request_hash="d" * 64,
                provider_deadline=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            spy = _CloneSpy()
            with pytest.raises(PlatformError) as deleted:
                _reconcile_delete(session, profile, operation, spy)  # type: ignore[arg-type]
            assert deleted.value.status_code == 404
            with pytest.raises(PlatformError) as enrolled:
                _reconcile_enrollment(session, profile, operation, spy, settings)  # type: ignore[arg-type]
            assert enrolled.value.status_code == 404
            assert spy.calls == []
        spy = _CloneSpy()
        monkeypatch.setattr("app.providers.factory.voice_provider", lambda _settings: spy)
        _user, csrf = login(client, "bowen")
        response = client.delete(
            f"/api/v1/voice-profiles/{ELDRIC_SAGE_PROFILE_ID}",
            headers=_headers(csrf, "preset-not-deletable1"),
        )
        assert response.status_code == 404
        assert spy.calls == []
        with database.session() as session:
            kept = session.get(VoiceProfile, ELDRIC_SAGE_PROFILE_ID)
            assert kept is not None
            assert kept.status == "ready"


def test_plato_resolves_the_preset_and_a_clone_keeps_its_model(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, database, settings = app_factory()
    clone_id = str(uuid4())
    with TestClient(app) as client:
        client.headers["Origin"] = "http://testserver"
        with database.session() as session:
            ensure_demo_baseline(session, settings.resolved_data_root)
            ensure_eldricsage_preset(session, settings)
            timestamp = datetime.now(UTC)
            clone = VoiceProfile(
                id=clone_id,
                scope="group",
                group_id=GROUP_DEMO_ID,
                display_name="Socrates clone",
                status="ready",
                provider_key="dashscope",
                target_model_key=DEFAULT_TARGET_MODEL_KEY,
                external_id_encrypted=None,
                recovery_name=f"maya{clone_id.replace('-', '')[:12]}",
                provenance_json="{}",
                created_at=timestamp,
                updated_at=timestamp,
            )
            clone.external_id_encrypted = encrypt_external_voice_id(
                "clone-voice-id",
                settings.secret_bytes,
                profile_id=clone.id,
                scope=clone.scope,
                group_id=clone.group_id,
                provider_key=clone.provider_key,
                target_model_key=clone.target_model_key,
            )
            session.add(clone)
        client.app.state.settings = settings.model_copy(
            update={
                "baseline_default_voices": (f"socrates={clone_id},plato={ELDRIC_SAGE_PROFILE_ID}")
            }
        )
        recorder = _RecordingTTS()
        monkeypatch.setattr(
            "app.modules.workspace.chat_stream.tts_provider", lambda _settings: recorder
        )
        _user, csrf = login(client, "bowen")

        def speak(version_id: str) -> str | None:
            created = client.post(
                "/api/v1/conversations",
                headers={"X-CSRF-Token": csrf},
                json={"version_id": version_id},
            )
            assert created.status_code == 200, created.text
            response = _stream(
                client, csrf, created.json()["id"], lang="zh-CN", message="Speak", revision=0
            )
            assert response.status_code == 200, response.text
            ready = [payload for name, payload in _parse_sse(response.text) if name == "tts_ready"]
            if not ready:
                return None
            voice_profile_id = ready[0]["voice_profile_id"]
            assert isinstance(voice_profile_id, str)
            return voice_profile_id

        assert speak(BASELINE_SOCRATES.version_id) == clone_id
        assert speak(BASELINE_PLATO.version_id) == ELDRIC_SAGE_PROFILE_ID
        assert speak(BASELINE_LAOZI.version_id) is None
        assert [(call[1], call[3]) for call in recorder.calls] == [
            ("clone-voice-id", DEFAULT_TARGET_MODEL_KEY),
            (ELDRIC_SAGE_VOICE, PRESET_TTS_MODEL_KEY),
        ]
