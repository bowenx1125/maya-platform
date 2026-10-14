"""Machine assertions for the qwen3-tts-flash trial path (architecture A)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.providers.dashscope import (
    DEFAULT_TARGET_MODEL_KEY,
    FLASH_SYSTEM_VOICES,
    FLASH_TTS_MODEL_KEY,
    PRESET_TTS_MODEL_KEY,
    QWEN_TTS_URL,
    VOICE_CUSTOMIZATION_PATH,
    ALLOWED_TTS_TARGET_MODELS,
    DashScopeConfig,
    DashScopeTTSProvider,
    DashScopeVoiceCloneProvider,
    tts_model_for_call,
)
from app.providers.tts import (
    TTSProviderError,
    TTSProviderUnavailableError,
    TTSVoiceUnavailableError,
)
from app.providers.tts_flash_budget import (
    FlashTrialBudget,
    TTS_FLASH_TRIAL_BUDGET_CHARS,
)
from app.providers.voice import VoiceProviderError


class _CaptureClient:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {
            "output": {"audio": {"url": "https://example.test/preview.wav"}},
            "request_id": "flash-tts",
        }
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> _CaptureClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append(
            {"url": url, "headers": kwargs.get("headers"), "json": kwargs.get("json")}
        )
        return httpx.Response(
            200,
            json=self.payload,
            request=httpx.Request("POST", url),
        )


class _Downloader:
    def download(self, _url: str) -> bytes:
        return b"RIFF" + b"\x00" * 40  # placeholder; validate_speech_audio patched


def _config() -> DashScopeConfig:
    return DashScopeConfig(api_key="fixture", workspace_id="workspace123")


def _provider(
    tmp_path: Path,
    *,
    flash_enabled: bool,
    monkeypatch: pytest.MonkeyPatch,
    client: _CaptureClient | None = None,
) -> tuple[DashScopeTTSProvider, _CaptureClient]:
    capture = client or _CaptureClient()
    monkeypatch.setattr("app.providers.dashscope._client", lambda **_kwargs: capture)
    monkeypatch.setattr("app.providers.dashscope.validate_speech_audio", lambda _audio: None)
    budget = FlashTrialBudget(tmp_path / "provider" / "tts_qwen3_flash_trial_chars")
    provider = DashScopeTTSProvider(
        _config(),
        downloader=_Downloader(),  # type: ignore[arg-type]
        flash_enabled=flash_enabled,
        trial_budget=budget,
    )
    return provider, capture


def test_allowlist_includes_flash_alias_and_keeps_snapshot_rollback() -> None:
    assert FLASH_TTS_MODEL_KEY in ALLOWED_TTS_TARGET_MODELS
    assert PRESET_TTS_MODEL_KEY in ALLOWED_TTS_TARGET_MODELS
    assert DEFAULT_TARGET_MODEL_KEY in ALLOWED_TTS_TARGET_MODELS
    assert "Cherry" in FLASH_SYSTEM_VOICES
    assert "Eldric Sage" in FLASH_SYSTEM_VOICES


def test_switch_off_refuses_flash_alias_with_zero_outbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=False, monkeypatch=monkeypatch)
    with pytest.raises(TTSProviderError) as rejected:
        provider.synthesize("Hello.", "Cherry", language="en", target_model_key=FLASH_TTS_MODEL_KEY)
    assert rejected.value.safe_code == "tts_response_invalid"
    assert capture.calls == []


def test_switch_off_keeps_snapshot_and_clone_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=False, monkeypatch=monkeypatch)
    provider.synthesize(
        "Rollback sentence.",
        "Eldric Sage",
        language="en",
        target_model_key=PRESET_TTS_MODEL_KEY,
    )
    provider.synthesize("Clone sentence.", "clone-voice-id", language="en")
    assert len(capture.calls) == 2
    assert capture.calls[0]["json"]["model"] == PRESET_TTS_MODEL_KEY
    assert capture.calls[1]["json"]["model"] == DEFAULT_TARGET_MODEL_KEY


def test_switch_on_flash_sends_alias_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=True, monkeypatch=monkeypatch)
    provider.synthesize(
        "A short line.",
        "Cherry",
        language="zh",
        target_model_key=FLASH_TTS_MODEL_KEY,
    )
    assert len(capture.calls) == 1
    assert capture.calls[0]["url"] == QWEN_TTS_URL
    assert capture.calls[0]["json"] == {
        "model": FLASH_TTS_MODEL_KEY,
        "input": {
            "text": "A short line.",
            "voice": "Cherry",
            "language_type": "Chinese",
        },
    }
    assert VOICE_CUSTOMIZATION_PATH not in capture.calls[0]["url"]


def test_illegal_clone_voice_zero_outbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=True, monkeypatch=monkeypatch)
    with pytest.raises(TTSVoiceUnavailableError) as rejected:
        provider.synthesize(
            "Hi.",
            "maya123456789012-generated",
            language="en",
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
    assert rejected.value.safe_code == "tts_voice_unavailable"
    assert capture.calls == []


def test_oversize_text_zero_outbound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=True, monkeypatch=monkeypatch)
    text = "字" * 601
    with pytest.raises(TTSProviderError) as rejected:
        provider.synthesize(text, "Cherry", language="zh", target_model_key=FLASH_TTS_MODEL_KEY)
    assert rejected.value.safe_code == "tts_response_invalid"
    assert capture.calls == []
    assert FlashTrialBudget(tmp_path / "provider" / "tts_qwen3_flash_trial_chars").used() == 0


def test_over_budget_zero_outbound_and_retries_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=True, monkeypatch=monkeypatch)
    budget_path = tmp_path / "provider" / "tts_qwen3_flash_trial_chars"
    # Fill almost to the cap, then refuse the next claim.
    FlashTrialBudget(budget_path).preclaim(TTS_FLASH_TRIAL_BUDGET_CHARS - 5)
    with pytest.raises(TTSProviderUnavailableError) as rejected:
        provider.synthesize(
            "123456",  # 6 chars > remaining 5
            "Cherry",
            language="en",
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
    assert rejected.value.safe_code == "tts_provider_unavailable"
    assert capture.calls == []
    assert FlashTrialBudget(budget_path).used() == TTS_FLASH_TRIAL_BUDGET_CHARS - 5

    # A successful short claim counts; a second attempt that fails still counted.
    provider.synthesize("ab", "Cherry", language="en", target_model_key=FLASH_TTS_MODEL_KEY)
    assert len(capture.calls) == 1
    assert FlashTrialBudget(budget_path).used() == TTS_FLASH_TRIAL_BUDGET_CHARS - 3


def test_budget_persists_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "provider" / "tts_qwen3_flash_trial_chars"
    first = FlashTrialBudget(path)
    first.preclaim(120)
    second = FlashTrialBudget(path)
    assert second.used() == 120
    second.preclaim(30)
    assert FlashTrialBudget(path).used() == 150


def test_tts_model_for_call_gates_flash_alias() -> None:
    assert (
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, FLASH_TTS_MODEL_KEY, flash_enabled=True)
        == FLASH_TTS_MODEL_KEY
    )
    with pytest.raises(TTSProviderError):
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, FLASH_TTS_MODEL_KEY, flash_enabled=False)
    assert (
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, PRESET_TTS_MODEL_KEY, flash_enabled=False)
        == PRESET_TTS_MODEL_KEY
    )


def test_flash_enroll_refused_with_zero_customization_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _NoClient:
        def __enter__(self) -> _NoClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, **_kwargs: object) -> httpx.Response:
            calls.append(url)
            raise AssertionError("enrollment must not open a network call for flash")

    monkeypatch.setattr("app.providers.dashscope._client", lambda **_kwargs: _NoClient())
    voice = DashScopeVoiceCloneProvider(_config())
    with pytest.raises(VoiceProviderError):
        voice.enroll(
            "data:audio/wav;base64,AA==",
            recovery_name="maya123456789012",
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
    assert calls == []


def test_factory_wires_switch_default_off(tmp_path: Path) -> None:
    from app.core.config import Settings
    from app.providers.factory import tts_provider

    settings = Settings(
        maya_env="test",
        session_secret="s" * 32,
        database_url=f"sqlite:///{tmp_path / 't.sqlite3'}",
        data_root=tmp_path,
        tts_provider="dashscope",
        voice_provider="mock",
        llm_provider="mock",
        embedding_provider="mock",
        dashscope_api_key="fixture",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
    )
    provider = tts_provider(settings)
    assert isinstance(provider, DashScopeTTSProvider)
    assert provider.flash_enabled is False
    assert provider.trial_budget is not None


def test_flash_errors_never_echo_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, capture = _provider(tmp_path, flash_enabled=True, monkeypatch=monkeypatch)
    with pytest.raises(TTSVoiceUnavailableError) as rejected:
        provider.synthesize(
            "Hi.",
            "not-a-system-voice",
            language="en",
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
    message = str(rejected.value)
    assert "fixture" not in message
    assert "Bearer" not in message
    assert capture.calls == []
