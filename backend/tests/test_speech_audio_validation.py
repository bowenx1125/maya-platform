from __future__ import annotations

import io
import wave

import pytest
from app.providers import dashscope
from app.providers.audio import (
    AudioValidationError,
    validate_speech_audio,
    validate_technical_audio,
)

from tests.test_dashscope_tts_timeout import _FakeClient


def _wav(seconds: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24_000)
        output.writeframes(b"\xe8\x03\x18\xfc" * 12_000 * seconds)
    return buffer.getvalue()


def test_full_speech_can_exceed_the_preview_duration() -> None:
    raw = _wav(61)
    assert validate_speech_audio(raw)["duration_seconds"] == 61
    with pytest.raises(AudioValidationError):
        validate_technical_audio(raw)
    with pytest.raises(AudioValidationError):
        validate_speech_audio(raw[:-2])
    with pytest.raises(AudioValidationError):
        validate_speech_audio(b"")


def test_dashscope_tts_validates_full_speech_without_preview_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _wav(61)

    class Download:
        def download(self, _: str) -> bytes:
            return raw

    monkeypatch.setattr(dashscope, "_client", lambda **_: _FakeClient())
    provider = dashscope.DashScopeTTSProvider(
        dashscope.DashScopeConfig(api_key="fixture-key", workspace_id="workspace123"),
        downloader=Download(),  # type: ignore[arg-type]
    )
    result = provider.synthesize("Complete speech", "fixture-voice")
    assert result.audio_bytes == raw
