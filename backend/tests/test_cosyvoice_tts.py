from __future__ import annotations

import math
import struct
import sys
import wave
from io import BytesIO
from types import ModuleType
from typing import Any

import pytest
from app.providers.cosyvoice_tts import CosyVoiceConfig, CosyVoiceTTSProvider
from app.providers.tts import (
    FallbackTTSProvider,
    MockTTSProvider,
    TTSProviderError,
    TTSProviderTimeout,
    TTSProviderUnavailableError,
    TTSResult,
    TTSVoiceUnavailableError,
)


def _config(**updates: object) -> CosyVoiceConfig:
    values: dict[str, Any] = {
        "api_key": "k" * 16,
        "workspace_id": "ws-test",
        "region": "cn-beijing",
    }
    values.update(updates)
    return CosyVoiceConfig(**values)


def _sine_pcm(sample_rate: int = 24000, seconds: float = 0.5) -> bytes:
    frames = int(sample_rate * seconds)
    payload = bytearray()
    for index in range(frames):
        sample = int(6000 * math.sin(2.0 * math.pi * 220.0 * index / sample_rate))
        payload.extend(struct.pack("<h", sample))
    return bytes(payload)


def _fake_sdk(monkeypatch: pytest.MonkeyPatch, events: list[object]) -> None:
    """Install a minimal dashscope module exposing Client().audio.tts.connect()."""

    class _Session:
        def __enter__(self) -> _Session:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def send_text(self, text: str) -> None:
            del text

        def flush(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def events(self) -> list[object]:
            return events

    class _Tts:
        def connect(self, **kwargs: object) -> _Session:
            del kwargs
            return _Session()

    class _Audio:
        tts = _Tts()

    class _Client:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        audio = _Audio()

    module = ModuleType("dashscope")
    module.Client = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dashscope", module)


def test_provider_requires_cn_beijing_workspace_and_key() -> None:
    with pytest.raises(TTSProviderUnavailableError):
        CosyVoiceTTSProvider(_config(region="ap-southeast-1"))
    with pytest.raises(TTSProviderUnavailableError):
        CosyVoiceTTSProvider(_config(api_key=""))


def test_synthesize_rejects_empty_text() -> None:
    provider = CosyVoiceTTSProvider(_config())
    with pytest.raises(TTSProviderError):
        provider.synthesize("  ", "longanyang")


def test_missing_sdk_is_a_pre_request_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "dashscope", raising=False)
    real_import = __import__

    def _blocked(name: str, *args: object, **kwargs: object) -> object:
        if name == "dashscope":
            raise ImportError("No module named 'dashscope'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _blocked)
    provider = CosyVoiceTTSProvider(_config())
    with pytest.raises(TTSProviderUnavailableError) as exc_info:
        provider.synthesize("你好", "longanyang")
    assert exc_info.value.safe_code == "tts_provider_unavailable"


def test_synthesize_returns_wav_with_absolute_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pcm = _sine_pcm()
    sentence_words = [
        {"text": "你", "begin_index": 0, "end_index": 1, "begin_time": 0, "end_time": 160},
        {"text": "好", "begin_index": 1, "end_index": 2, "begin_time": 160, "end_time": 320},
    ]
    events: list[object] = [
        {
            "header": {},
            "payload": {"output": {"type": "sentence-end", "sentence": {"words": sentence_words}}},
        },
        pcm,
        {"header": {"event": "task-finished"}, "payload": {"usage": {"characters": 2}}},
    ]
    _fake_sdk(monkeypatch, events)
    provider = CosyVoiceTTSProvider(_config())
    result = provider.synthesize("你好", "longanyang")
    assert result.content_type == "audio/wav"
    with wave.open(BytesIO(result.audio_bytes)) as wav:
        assert wav.getframerate() == 24000
        assert wav.getnframes() == len(pcm) // 2
    assert result.word_timestamps is not None
    stamps = result.word_timestamps
    assert len(stamps) == 2
    assert stamps[0]["begin_ms"] == 0
    assert stamps[1]["end_ms"] <= round(len(pcm) / 2 / 24000 * 1000, 1)


def test_task_failed_maps_to_response_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[object] = [
        {"header": {"event": "task-failed", "message": "internal"}, "payload": {}},
    ]
    _fake_sdk(monkeypatch, events)
    provider = CosyVoiceTTSProvider(_config())
    with pytest.raises(TTSProviderError) as exc_info:
        provider.synthesize("你好", "longanyang")
    assert exc_info.value.safe_code == "tts_response_invalid"


def test_pcm_to_wav_round_trip() -> None:
    pcm = _sine_pcm(seconds=0.25)
    wav = CosyVoiceTTSProvider._pcm_to_wav(pcm, 24000)
    with wave.open(BytesIO(wav)) as parsed:
        assert parsed.getnframes() == len(pcm) // 2
        assert parsed.readframes(len(pcm) // 2) == pcm


def test_absolute_words_clamps_to_total() -> None:
    sentences = [
        {
            "words": [
                {"text": "你", "begin_index": 0, "end_index": 1, "begin_time": 0, "end_time": 900}
            ]
        },
        {
            "words": [
                {"text": "好", "begin_index": 2, "end_index": 3, "begin_time": 0, "end_time": 400}
            ]
        },
    ]
    words = CosyVoiceTTSProvider._absolute_words(sentences, total_ms=1000)
    assert words[0]["end_ms"] == 900
    assert words[1]["begin_ms"] == 960  # 900 + 60 ms consonant tail
    assert words[1]["end_ms"] == 1000  # clamped to the real recording length


class _FailingPrimary:
    key = "cosyvoice"
    target_model_key = "cosyvoice-v3-flash"

    def __init__(self, error: TTSProviderError) -> None:
        self._error = error

    def synthesize(self, text: str, external_voice_id: str, **kwargs: object) -> TTSResult:
        del text, external_voice_id, kwargs
        raise self._error


def test_fallback_degrades_only_on_pre_request_refusals() -> None:
    fallback = MockTTSProvider()
    unavailable = FallbackTTSProvider(
        _FailingPrimary(TTSProviderUnavailableError("blocked before request")), fallback
    )
    assert unavailable.key == "cosyvoice"
    result = unavailable.synthesize("text", "voice")
    assert result.audio_bytes
    assert fallback.synthesize_calls == 1

    voice_missing = FallbackTTSProvider(
        _FailingPrimary(TTSVoiceUnavailableError("no such voice")), MockTTSProvider()
    )
    assert voice_missing.synthesize("text", "voice").audio_bytes

    charged_failure = FallbackTTSProvider(
        _FailingPrimary(TTSProviderTimeout("possibly charged")), MockTTSProvider()
    )
    with pytest.raises(TTSProviderTimeout):
        charged_failure.synthesize("text", "voice")
