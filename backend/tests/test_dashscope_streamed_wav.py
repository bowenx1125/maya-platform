"""Qwen VC result WAVs carry streaming placeholder sizes; repair only that shape."""

from __future__ import annotations

import io
import struct
import wave

import httpx
import pytest
from app.providers.audio import AudioValidationError, validate_technical_audio
from app.providers.dashscope import DashScopeConfig, DashScopeTTSProvider, _finalize_streamed_wav
from app.providers.tts import TTSAudioInvalidError, TTSProviderError

# Observed on qwen3-tts-vc-2026-01-22: both size fields sit just under 2**31,
# and the RIFF field is the data field plus the canonical header span.
_DATA_PLACEHOLDER = 0x7FFFFF9B
_RIFF_PLACEHOLDER = 0x7FFFFFBF


def _wav(seconds: float = 1.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24_000)
        frames = int(24_000 * seconds)
        tone = b"".join(
            struct.pack("<h", 3000 if index % 40 < 20 else -3000) for index in range(frames)
        )
        stream.writeframes(tone)
    return buffer.getvalue()


def _with_placeholders(raw: bytes) -> bytes:
    fixed = bytearray(raw)
    offset = 12
    data_at: int | None = None
    while len(fixed) - offset >= 8:
        chunk_id = bytes(fixed[offset : offset + 4])
        chunk_size = int.from_bytes(fixed[offset + 4 : offset + 8], "little")
        if chunk_id == b"data":
            data_at = offset
            break
        offset += 8 + chunk_size + (chunk_size % 2)
    if data_at is None:
        raise AssertionError("fixture has no data chunk")
    fixed[4:8] = (data_at + _DATA_PLACEHOLDER).to_bytes(4, "little")
    fixed[data_at + 4 : data_at + 8] = _DATA_PLACEHOLDER.to_bytes(4, "little")
    return bytes(fixed)


def _streamed(raw: bytes) -> bytes:
    """The canonical 44-byte header shape observed from the supplier."""

    streamed = _with_placeholders(raw)
    assert streamed[4:8] == _RIFF_PLACEHOLDER.to_bytes(4, "little")
    assert streamed[40:44] == _DATA_PLACEHOLDER.to_bytes(4, "little")
    return streamed


class _CaptureClient:
    def __init__(self, document: dict[str, object]) -> None:
        self.calls: list[dict[str, object]] = []
        self._document = document

    def __enter__(self) -> _CaptureClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        body = kwargs.get("json")
        self.calls.append(body if isinstance(body, dict) else {})
        del url
        return httpx.Response(
            200,
            json=self._document,
            request=httpx.Request("POST", "https://provider.invalid"),
        )


def test_streamed_placeholder_sizes_are_repaired() -> None:
    raw = _wav()
    streamed = _streamed(raw)
    with pytest.raises(AudioValidationError):
        validate_technical_audio(streamed)
    repaired = _finalize_streamed_wav(streamed)
    assert repaired == raw
    assert validate_technical_audio(repaired)["duration_seconds"] == pytest.approx(1.5)


def test_placeholder_after_an_extra_chunk_is_repaired() -> None:
    raw = bytearray(_wav())
    # A LIST chunk before data moves the data size field off the canonical offset.
    raw[36:36] = b"LIST" + (4).to_bytes(4, "little") + b"TEST"
    raw[4:8] = (len(raw) - 8).to_bytes(4, "little")
    with_list = bytes(raw)
    repaired = _finalize_streamed_wav(_with_placeholders(with_list))
    assert repaired == with_list
    assert validate_technical_audio(repaired)["duration_seconds"] == pytest.approx(1.5)


def test_complete_truncated_or_non_wav_input_is_unchanged() -> None:
    raw = _wav()
    assert _finalize_streamed_wav(raw) is raw
    truncated = raw[:-80]
    assert _finalize_streamed_wav(truncated) is truncated
    with pytest.raises(AudioValidationError):
        validate_technical_audio(truncated)
    data_only = bytearray(raw)
    data_only[40:44] = _DATA_PLACEHOLDER.to_bytes(4, "little")
    assert _finalize_streamed_wav(bytes(data_only)) == bytes(data_only)
    assert _finalize_streamed_wav(b"not a wav") == b"not a wav"


def test_synthesize_repairs_streamed_wav_before_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _wav()
    capture = _CaptureClient(
        {
            "output": {
                "audio": {"url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x.wav"}
            },
            "request_id": "tts-request",
        }
    )
    monkeypatch.setattr("app.providers.dashscope._client", lambda: capture)

    class _Downloader:
        def download(self, value: str) -> bytes:
            assert value.endswith("/x.wav")
            return _streamed(raw)

    config = DashScopeConfig(api_key="fixture", workspace_id="workspace123")
    result = DashScopeTTSProvider(config, downloader=_Downloader()).synthesize(
        "A new English sentence.",
        "opaque-voice",
        language="en",
    )
    assert result.audio_bytes == raw
    assert capture.calls == [
        {
            "model": "qwen3-tts-vc-2026-01-22",
            "input": {
                "text": "A new English sentence.",
                "voice": "opaque-voice",
                "language_type": "English",
            },
        }
    ]


def test_synthesize_still_rejects_a_truncated_wav(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _wav()
    monkeypatch.setattr(
        "app.providers.dashscope._client",
        lambda: _CaptureClient(
            {
                "output": {
                    "audio": {
                        "url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x.wav"
                    }
                }
            }
        ),
    )

    class _Downloader:
        def download(self, value: str) -> bytes:
            del value
            return raw[:-80]

    config = DashScopeConfig(api_key="fixture", workspace_id="workspace123")
    with pytest.raises(TTSAudioInvalidError):
        DashScopeTTSProvider(config, downloader=_Downloader()).synthesize("A sentence.", "opaque")


def test_synthesize_sends_chinese_and_refuses_other_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _wav()
    capture = _CaptureClient(
        {
            "output": {
                "audio": {"url": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/x.wav"}
            }
        }
    )
    monkeypatch.setattr("app.providers.dashscope._client", lambda: capture)

    class _Downloader:
        def download(self, value: str) -> bytes:
            del value
            return raw

    config = DashScopeConfig(api_key="fixture", workspace_id="workspace123")
    DashScopeTTSProvider(config, downloader=_Downloader()).synthesize(
        "你好。",
        "opaque",
        language="zh",
    )
    assert capture.calls[0]["input"] == {
        "text": "你好。",
        "voice": "opaque",
        "language_type": "Chinese",
    }

    def unexpected_client() -> _CaptureClient:
        raise AssertionError("an unsupported language must not construct a client")

    monkeypatch.setattr("app.providers.dashscope._client", unexpected_client)
    with pytest.raises(TTSProviderError) as error:
        DashScopeTTSProvider(config).synthesize("A sentence.", "opaque", language="zh-CN")
    assert error.value.safe_code == "tts_response_invalid"
