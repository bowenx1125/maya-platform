"""Machine assertions for the controlled system-voice flash preview API."""

from __future__ import annotations

import io
import wave
from typing import Any

import pytest
from app.modules.voices import system_voice_preview as svp
from app.providers.dashscope import FLASH_SYSTEM_VOICES, FLASH_TTS_MODEL_KEY
from app.providers.tts import MockTTSProvider, TTSResult
from app.providers.voice import MockVoiceCloneProvider
from fastapi.testclient import TestClient

from tests.conftest import login

ORIGIN = {"Origin": "http://testserver"}


class _TrackingTTS(MockTTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []
        self.enroll_calls = 0

    def synthesize(
        self,
        text: str,
        external_voice_id: str,
        *,
        language: str = "en",
        target_model_key: str | None = None,
    ) -> TTSResult:
        self.calls.append(
            {
                "text": text,
                "voice": external_voice_id,
                "language": language,
                "target_model_key": target_model_key,
            }
        )
        return super().synthesize(
            text,
            external_voice_id,
            language=language,
            target_model_key=target_model_key,
        )


def _headers(csrf: str) -> dict[str, str]:
    return {**ORIGIN, "X-CSRF-Token": csrf}


def _enable_flash(client: TestClient) -> None:
    client.app.state.settings.tts_qwen3_flash_enabled = True


def _wav_duration_seconds(raw: bytes) -> float:
    with wave.open(io.BytesIO(raw), "rb") as stream:
        frames = stream.getnframes()
        rate = stream.getframerate()
        assert frames > 0
        assert rate > 0
        return frames / float(rate)


def test_scripts_list_four_fixed_segments_for_teacher(client: TestClient) -> None:
    _login, csrf = login(client, "maya")
    response = client.get(
        "/api/v1/system-voice-previews/scripts",
        headers=_headers(csrf),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row["segment_id"] for row in payload] == list(svp.SEGMENT_IDS)
    by_id = {row["segment_id"]: row for row in payload}
    assert by_id["mandarin"]["voice"] == "Cherry"
    assert by_id["cantonese"]["voice"] == "Kiki"
    assert by_id["cantonese"]["voice"] != "Cherry"
    assert by_id["mixed"]["voice"] == "Cherry"
    assert by_id["numbers"]["voice"] == "Cherry"
    assert "粤语" in by_id["cantonese"]["expected_reading"]
    assert "001203" in by_id["numbers"]["expected_reading"]
    for row in payload:
        assert row["voice"] in FLASH_SYSTEM_VOICES
        assert row["text"]
        assert row["expected_reading"]


def test_four_segments_succeed_downloadable_non_silent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_flash(client)
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    voice = MockVoiceCloneProvider()
    monkeypatch.setattr(
        "app.providers.factory.voice_provider", lambda _settings: voice
    )

    _login, csrf = login(client, "maya")
    expected_voices = {
        "mandarin": "Cherry",
        "cantonese": "Kiki",
        "mixed": "Cherry",
        "numbers": "Cherry",
    }
    for segment_id, voice_name in expected_voices.items():
        created = client.post(
            "/api/v1/system-voice-previews",
            headers=_headers(csrf),
            json={"segment_id": segment_id},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["segment_id"] == segment_id
        assert body["voice"] == voice_name
        assert body["deduplicated"] is False
        assert body["playback_url"].endswith("/media")
        assert body["provider_request_id"]
        media = client.get(body["playback_url"], headers=_headers(csrf))
        assert media.status_code == 200, media.text
        assert media.headers["content-type"].startswith("audio/wav")
        duration = _wav_duration_seconds(media.content)
        assert duration > 0

    assert len(provider.calls) == 4
    assert [call["voice"] for call in provider.calls] == [
        "Cherry",
        "Kiki",
        "Cherry",
        "Cherry",
    ]
    assert all(call["target_model_key"] == FLASH_TTS_MODEL_KEY for call in provider.calls)
    assert voice.enroll_calls == 0


def test_post_all_returns_four(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flash(client)
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    _login, csrf = login(client, "maya")
    response = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "all"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    assert [row["segment_id"] for row in payload] == list(svp.SEGMENT_IDS)
    assert len(provider.calls) == 4


def test_unauthenticated_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/system-voice-previews",
        headers=ORIGIN,
        json={"segment_id": "mandarin"},
    )
    assert response.status_code in {401, 403}


def test_student_forbidden(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flash(client)
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    _login, csrf = login(client, "bowen")
    response = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "mandarin"},
    )
    assert response.status_code == 403, response.text
    assert provider.synthesize_calls == 0
    scripts = client.get("/api/v1/system-voice-previews/scripts", headers=_headers(csrf))
    assert scripts.status_code == 403


def test_flash_off_zero_outbound(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    client.app.state.settings.tts_qwen3_flash_enabled = False
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    _login, csrf = login(client, "maya")
    response = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "mandarin"},
    )
    assert response.status_code == 503, response.text
    assert provider.synthesize_calls == 0
    all_response = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "all"},
    )
    assert all_response.status_code == 503
    assert provider.synthesize_calls == 0


def test_illegal_segment_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_flash(client)
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    _login, csrf = login(client, "maya")
    response = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "pirate"},
    )
    assert response.status_code in {400, 422}
    assert provider.synthesize_calls == 0


def test_dedup_second_call_zero_extra_synth(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_flash(client)
    provider = _TrackingTTS()
    monkeypatch.setattr(svp, "tts_provider", lambda _settings: provider)
    _login, csrf = login(client, "maya")
    first = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "mixed"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        "/api/v1/system-voice-previews",
        headers=_headers(csrf),
        json={"segment_id": "mixed"},
    )
    assert second.status_code == 200, second.text
    assert first.json()["request_id"] == second.json()["request_id"]
    assert second.json()["deduplicated"] is True
    assert provider.synthesize_calls == 1


def test_fixed_scripts_never_use_clone_voice_ids() -> None:
    for script in svp.list_system_voice_scripts():
        assert script.voice in FLASH_SYSTEM_VOICES
        assert script.voice != "clone-voice-id"
    assert svp.SCRIPTS["cantonese"].voice == "Kiki"
