from __future__ import annotations

import app.providers.dashscope as dashscope
import httpx
import pytest
from app.providers.dashscope import QWEN_TTS_URL, DashScopeConfig, DashScopeTTSProvider


class _FakeDownloader:
    def download(self, url: str) -> bytes:
        assert url == "https://result.example/audio.wav"
        return b"audio"


class _FakeClient:
    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        assert url == QWEN_TTS_URL
        assert headers == {
            "Authorization": "Bearer fixture-key",
            "X-DashScope-WorkSpace": "workspace123",
        }
        assert json["model"] == dashscope.DEFAULT_TARGET_MODEL_KEY
        return httpx.Response(
            200,
            headers={"x-request-id": "tts-request-1"},
            json={"output": {"audio": {"url": "https://result.example/audio.wav"}}},
            request=httpx.Request("POST", url),
        )


def test_tts_request_uses_extended_read_timeout_without_changing_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    default_client = dashscope._client()
    tts_client = dashscope._client(read_timeout=dashscope.TTS_GENERATION_READ_TIMEOUT_SECONDS)
    try:
        assert default_client.timeout.read == 30.0
        assert tts_client.timeout.read == 120.0
    finally:
        default_client.close()
        tts_client.close()

    observed: list[float] = []

    def client_factory(*, read_timeout: float = 30.0) -> _FakeClient:
        observed.append(read_timeout)
        return _FakeClient()

    monkeypatch.setattr(dashscope, "_client", client_factory)
    monkeypatch.setattr(dashscope, "validate_speech_audio", lambda _audio: None)
    provider = DashScopeTTSProvider(
        DashScopeConfig(api_key="fixture-key", workspace_id="workspace123"),
        downloader=_FakeDownloader(),  # type: ignore[arg-type]
    )

    result = provider.synthesize("A longer cloned-voice reply.", "voice-id")

    assert observed == [120.0]
    assert result.audio_bytes == b"audio"
    assert result.request_id == "tts-request-1"
