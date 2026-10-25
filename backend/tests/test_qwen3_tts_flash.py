"""Machine assertions for system-voice flash and Qwen-Audio-TTS clone paths."""

from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest
from app.providers.dashscope import (
    ALLOWED_TTS_TARGET_MODELS,
    CLONE_TTS_MODEL_KEYS,
    DEFAULT_TARGET_MODEL_KEY,
    FLASH_SYSTEM_VOICES,
    FLASH_TTS_MODEL_KEY,
    LEGACY_CLONE_MODEL_KEY,
    PRESET_TTS_MODEL_KEY,
    QWEN_TTS_URL,
    SPEECH_SYNTHESIZER_PATH,
    UPLOAD_POLICY_URL,
    VOICE_CUSTOMIZATION_PATH,
    DashScopeConfig,
    DashScopeTTSProvider,
    DashScopeVoiceCloneProvider,
    _base_url,
    tts_model_for_call,
)
from app.providers.tts import TTSProviderError, TTSVoiceUnavailableError
from app.providers.voice import VoiceCloneRefusedError, VoiceProviderError

from tests.postgres_db import named_url

SAMPLE = b"RIFF-sample-bytes"
SAMPLE_URI = "data:audio/wav;base64," + base64.b64encode(SAMPLE).decode("ascii")
POLICY = {
    "policy": "policy-doc",
    "signature": "signature",
    "upload_dir": "dashscope-instant/abc/2026-10-17/xyz",
    "upload_host": "https://dashscope-file-mgr.oss-cn-beijing.aliyuncs.com",
    "oss_access_key_id": "access-id",
    "x_oss_object_acl": "private",
    "x_oss_forbid_overwrite": "true",
}


class _CaptureClient:
    def __init__(self, responses: list[dict[str, object]] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, object]] = []

    def __enter__(self) -> _CaptureClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def _reply(self, method: str, url: str) -> httpx.Response:
        payload = (
            self.responses.pop(0)
            if self.responses
            else {
                "output": {"audio": {"url": "https://example.test/preview.wav"}},
                "request_id": "tts-request",
            }
        )
        return httpx.Response(200, json=payload, request=httpx.Request(method, url))

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._reply("GET", url)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._reply("POST", url)


class _Downloader:
    def download(self, _url: str) -> bytes:
        return b"RIFF" + b"\x00" * 40  # placeholder; validate_speech_audio patched


def _config(target: str = DEFAULT_TARGET_MODEL_KEY) -> DashScopeConfig:
    return DashScopeConfig(api_key="fixture", workspace_id="workspace123", target_model_key=target)


WORKSPACE_BASE = _base_url(_config())


def _tts(
    monkeypatch: pytest.MonkeyPatch, *, target: str = DEFAULT_TARGET_MODEL_KEY
) -> tuple[DashScopeTTSProvider, _CaptureClient]:
    capture = _CaptureClient()
    monkeypatch.setattr("app.providers.dashscope._client", lambda **_kwargs: capture)
    monkeypatch.setattr("app.providers.dashscope.validate_speech_audio", lambda _audio: None)
    provider = DashScopeTTSProvider(
        _config(target),
        downloader=_Downloader(),  # type: ignore[arg-type]
    )
    return provider, capture


def _voice(
    monkeypatch: pytest.MonkeyPatch, responses: list[dict[str, object]] | None = None
) -> tuple[DashScopeVoiceCloneProvider, _CaptureClient]:
    capture = _CaptureClient(responses)
    monkeypatch.setattr("app.providers.dashscope._client", lambda **_kwargs: capture)
    return DashScopeVoiceCloneProvider(_config()), capture


def test_allowlist_holds_system_and_clone_models_but_not_the_retired_clone() -> None:
    assert FLASH_TTS_MODEL_KEY in ALLOWED_TTS_TARGET_MODELS
    assert PRESET_TTS_MODEL_KEY in ALLOWED_TTS_TARGET_MODELS
    assert set(CLONE_TTS_MODEL_KEYS) == {"qwen-audio-3.1-tts-flash", "qwen-audio-3.0-tts-flash"}
    assert DEFAULT_TARGET_MODEL_KEY == "qwen-audio-3.1-tts-flash"
    assert set(CLONE_TTS_MODEL_KEYS) <= ALLOWED_TTS_TARGET_MODELS
    assert LEGACY_CLONE_MODEL_KEY not in ALLOWED_TTS_TARGET_MODELS
    assert "Cherry" in FLASH_SYSTEM_VOICES
    assert "Eldric Sage" in FLASH_SYSTEM_VOICES


def test_tts_model_for_call_routes_every_system_voice_to_flash() -> None:
    assert tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, PRESET_TTS_MODEL_KEY) == FLASH_TTS_MODEL_KEY
    assert tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, FLASH_TTS_MODEL_KEY) == FLASH_TTS_MODEL_KEY
    assert tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, None) == DEFAULT_TARGET_MODEL_KEY
    assert (
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, "qwen-audio-3.0-tts-flash")
        == "qwen-audio-3.0-tts-flash"
    )
    with pytest.raises(TTSVoiceUnavailableError):
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, LEGACY_CLONE_MODEL_KEY)
    with pytest.raises(TTSProviderError) as rejected:
        tts_model_for_call(DEFAULT_TARGET_MODEL_KEY, "qwen-tts-latest")
    assert rejected.value.safe_code == "tts_response_invalid"


def test_preset_profile_speaks_through_flash(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch)
    provider.synthesize(
        "A short line.",
        "Eldric Sage",
        language="zh",
        target_model_key=PRESET_TTS_MODEL_KEY,
    )
    assert len(capture.calls) == 1
    assert capture.calls[0]["url"] == QWEN_TTS_URL
    assert capture.calls[0]["json"] == {
        "model": FLASH_TTS_MODEL_KEY,
        "input": {
            "text": "A short line.",
            "voice": "Eldric Sage",
            "language_type": "Chinese",
        },
    }


def test_clone_speaks_through_the_speech_synthesizer(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch)
    result = provider.synthesize("Clone sentence.", "qwen-audio-3.1-tts-flash-mabc-123")
    assert result.request_id == "tts-request"
    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["url"] == f"{WORKSPACE_BASE}{SPEECH_SYNTHESIZER_PATH}"
    assert call["json"] == {
        "model": DEFAULT_TARGET_MODEL_KEY,
        "input": {
            "text": "Clone sentence.",
            "voice": "qwen-audio-3.1-tts-flash-mabc-123",
            "format": "wav",
            "sample_rate": 24000,
        },
    }
    assert call["headers"] == {
        "Authorization": "Bearer fixture",
        "X-DashScope-WorkSpace": "workspace123",
    }


def test_retired_clone_is_unavailable_with_zero_outbound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _tts(monkeypatch)
    with pytest.raises(TTSVoiceUnavailableError) as rejected:
        provider.synthesize("Hi.", "old-voice", target_model_key=LEGACY_CLONE_MODEL_KEY)
    assert rejected.value.safe_code == "tts_voice_unavailable"
    assert capture.calls == []


def test_unpublished_system_voice_zero_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch)
    with pytest.raises(TTSVoiceUnavailableError) as rejected:
        provider.synthesize(
            "Hi.",
            "maya123456789012-generated",
            language="en",
            target_model_key=FLASH_TTS_MODEL_KEY,
        )
    assert rejected.value.safe_code == "tts_voice_unavailable"
    assert "fixture" not in str(rejected.value)
    assert capture.calls == []


def test_oversize_system_voice_text_zero_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch)
    with pytest.raises(TTSProviderError) as rejected:
        provider.synthesize(
            "字" * 601, "Cherry", language="zh", target_model_key=FLASH_TTS_MODEL_KEY
        )
    assert rejected.value.safe_code == "tts_response_invalid"
    assert capture.calls == []


@pytest.mark.parametrize(
    "target", [FLASH_TTS_MODEL_KEY, PRESET_TTS_MODEL_KEY, LEGACY_CLONE_MODEL_KEY]
)
def test_enroll_refuses_non_clone_targets_with_zero_outbound(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    provider, capture = _voice(monkeypatch)
    with pytest.raises(VoiceCloneRefusedError):
        provider.enroll(SAMPLE_URI, recovery_name="mabcdef12", target_model_key=target)
    assert capture.calls == []


def test_enroll_uploads_the_sample_then_creates_the_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _voice(
        monkeypatch,
        [
            {"data": POLICY, "request_id": "policy"},
            {},
            {"output": {"voice_id": "qwen-audio-3.1-tts-flash-mabcdef12-x1"}, "request_id": "r1"},
            {"output": {"status": "OK"}},
        ],
    )
    result = provider.enroll(
        SAMPLE_URI, recovery_name="mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY
    )
    assert result.external_voice_id == "qwen-audio-3.1-tts-flash-mabcdef12-x1"
    assert result.request_id == "r1"
    policy, upload, create, review = capture.calls
    assert review["json"] == {
        "model": "voice-enrollment",
        "input": {"action": "query_voice", "voice_id": "qwen-audio-3.1-tts-flash-mabcdef12-x1"},
    }
    assert policy["method"] == "GET"
    assert policy["url"] == UPLOAD_POLICY_URL
    assert policy["params"] == {"action": "getPolicy", "model": "voice-enrollment"}
    key = f"{POLICY['upload_dir']}/mabcdef12.wav"
    assert upload["url"] == POLICY["upload_host"]
    assert upload["data"]["key"] == key  # type: ignore[index]
    assert upload["files"] == {"file": ("mabcdef12.wav", SAMPLE, "audio/wav")}
    assert create["url"] == f"{WORKSPACE_BASE}{VOICE_CUSTOMIZATION_PATH}"
    assert create["headers"]["X-DashScope-OssResourceResolve"] == "enable"  # type: ignore[index]
    assert create["json"] == {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": DEFAULT_TARGET_MODEL_KEY,
            "prefix": "mabcdef12",
            "url": f"oss://{key}",
        },
    }


def _created(*review: dict[str, object]) -> list[dict[str, object]]:
    return [
        {"data": POLICY},
        {},
        {"output": {"voice_id": "qwen-audio-3.1-tts-flash-mabcdef12-x1"}},
        *review,
    ]


def test_enroll_refuses_and_deletes_a_voice_the_review_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.providers.dashscope.time.sleep", lambda _seconds: None)
    provider, capture = _voice(
        monkeypatch,
        _created({"output": {"status": "DEPLOYING"}}, {"output": {"status": "UNDEPLOYED"}}, {}),
    )
    with pytest.raises(VoiceCloneRefusedError):
        provider.enroll(
            SAMPLE_URI, recovery_name="mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY
        )
    assert capture.calls[-1]["json"] == {
        "model": "voice-enrollment",
        "input": {"action": "delete_voice", "voice_id": "qwen-audio-3.1-tts-flash-mabcdef12-x1"},
    }


def test_enroll_returns_a_voice_still_under_review_after_the_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    clock = iter(range(0, 1000, 3))
    monkeypatch.setattr("app.providers.dashscope.time.sleep", sleeps.append)
    monkeypatch.setattr("app.providers.dashscope.time.monotonic", lambda: float(next(clock)))
    provider, capture = _voice(monkeypatch, _created(*([{"output": {"status": "DEPLOYING"}}] * 20)))
    result = provider.enroll(
        SAMPLE_URI, recovery_name="mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY
    )
    assert result.external_voice_id == "qwen-audio-3.1-tts-flash-mabcdef12-x1"
    reviews = [call for call in capture.calls if "query_voice" in str(call.get("json"))]
    assert 1 < len(reviews) < 20
    assert all(seconds == 2.0 for seconds in sleeps)


def test_enroll_never_uploads_to_a_host_outside_the_supplier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _voice(
        monkeypatch,
        [{"data": {**POLICY, "upload_host": "https://collector.example.test"}}],
    )
    with pytest.raises(VoiceProviderError):
        provider.enroll(
            SAMPLE_URI, recovery_name="mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY
        )
    assert [call["method"] for call in capture.calls] == ["GET"]


def test_exists_lists_by_prefix_and_matches_only_that_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _voice(
        monkeypatch,
        [
            {
                "output": {
                    "voice_list": [
                        {"voice_id": "qwen-audio-3.1-tts-flash-mabcdef12-x1"},
                        {"voice_id": "qwen-audio-3.1-tts-flash-mabcdef123-x2"},
                    ]
                }
            }
        ],
    )
    result = provider.exists("mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY)
    assert result.matches == ("qwen-audio-3.1-tts-flash-mabcdef12-x1",)
    assert result.visibility_known is True
    assert capture.calls[0]["json"] == {
        "model": "voice-enrollment",
        "input": {
            "action": "list_voice",
            "prefix": "mabcdef12",
            "page_index": 0,
            "page_size": 100,
        },
    }


def test_delete_uses_the_api_of_the_model_the_voice_was_enrolled_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _voice(monkeypatch, [{}, {}])
    provider.delete("new-voice", target_model_key=DEFAULT_TARGET_MODEL_KEY)
    provider.delete("old-voice", target_model_key=LEGACY_CLONE_MODEL_KEY)
    assert capture.calls[0]["json"] == {
        "model": "voice-enrollment",
        "input": {"action": "delete_voice", "voice_id": "new-voice"},
    }
    assert capture.calls[1]["json"] == {
        "model": "qwen-voice-enrollment",
        "input": {"action": "delete", "voice": "old-voice"},
    }


def _settings(tmp_path: Path, **values: object) -> object:
    from app.core.config import Settings

    return Settings(
        maya_env="test",
        session_secret="s" * 32,
        database_url=named_url(f"{tmp_path / 't.sqlite3'}"),
        data_root=tmp_path,
        tts_provider="dashscope",
        voice_provider="dashscope",
        llm_provider="mock",
        embedding_provider="mock",
        dashscope_api_key="fixture",
        dashscope_workspace_id="workspace123",
        dashscope_region="cn-beijing",
        **values,
    )


def test_factory_clones_on_the_configured_model(tmp_path: Path) -> None:
    from app.providers.factory import tts_provider, voice_provider

    default = _settings(tmp_path)
    assert voice_provider(default).target_model_key == "qwen-audio-3.1-tts-flash"  # type: ignore[arg-type]
    assert tts_provider(default).target_model_key == "qwen-audio-3.1-tts-flash"  # type: ignore[arg-type,attr-defined]
    chosen = _settings(tmp_path, voice_clone_model="qwen-audio-3.0-tts-flash")
    assert voice_provider(chosen).target_model_key == "qwen-audio-3.0-tts-flash"  # type: ignore[arg-type]
    assert _settings(tmp_path, voice_clone_model="").voice_clone_model == (  # type: ignore[attr-defined]
        "qwen-audio-3.1-tts-flash"
    )
    with pytest.raises(ValueError):
        _settings(tmp_path, voice_clone_model=LEGACY_CLONE_MODEL_KEY)


def test_enroll_returns_a_created_voice_when_the_review_query_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The voice id came back from create_voice, so the voice exists. A review
    # status read that times out must not turn it into an unknown outcome.
    class _TimeoutOnReview(_CaptureClient):
        def post(self, url: str, **kwargs: object) -> httpx.Response:
            if "query_voice" in str(kwargs.get("json")):
                self.calls.append({"method": "POST", "url": url, **kwargs})
                raise httpx.ReadTimeout("review status timed out")
            return super().post(url, **kwargs)

    capture = _TimeoutOnReview(_created())
    monkeypatch.setattr("app.providers.dashscope._client", lambda **_kwargs: capture)
    provider = DashScopeVoiceCloneProvider(_config())
    result = provider.enroll(
        SAMPLE_URI, recovery_name="mabcdef12", target_model_key=DEFAULT_TARGET_MODEL_KEY
    )
    assert result.external_voice_id == "qwen-audio-3.1-tts-flash-mabcdef12-x1"
    assert not result.degraded
    assert any("query_voice" in str(call.get("json")) for call in capture.calls)


def test_a_clone_sends_rate_instruction_and_seed_in_its_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, capture = _tts(monkeypatch)
    provider.synthesize(
        "Clone sentence.",
        "qwen-audio-3.1-tts-flash-mabc-123",
        voice_params={"rate": 1.25, "instruction": " 语气坚定，像辩论赛选手 ", "seed": 7},
    )
    assert capture.calls[0]["json"] == {
        "model": DEFAULT_TARGET_MODEL_KEY,
        "input": {
            "text": "Clone sentence.",
            "voice": "qwen-audio-3.1-tts-flash-mabc-123",
            "format": "wav",
            "sample_rate": 24000,
            "rate": 1.25,
            "instruction": "语气坚定，像辩论赛选手",
            "seed": 7,
        },
    }


def test_empty_voice_parameters_are_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch, target="qwen-audio-3.0-tts-flash")
    provider.synthesize(
        "Clone sentence.",
        "qwen-audio-3.0-tts-flash-mabc-123",
        voice_params={"rate": 1.1, "instruction": "   ", "seed": None},
    )
    sent = capture.calls[0]["json"]["input"]  # type: ignore[index]
    assert sent["rate"] == 1.1
    assert "instruction" not in sent and "seed" not in sent


def test_a_preset_voice_never_sends_voice_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, capture = _tts(monkeypatch)
    voice = sorted(FLASH_SYSTEM_VOICES)[0]
    provider.synthesize(
        "Preset sentence.",
        voice,
        target_model_key=FLASH_TTS_MODEL_KEY,
        voice_params={"rate": 1.25, "instruction": "语气坚定", "seed": 7},
    )
    call = capture.calls[0]
    assert call["url"] == QWEN_TTS_URL
    assert set(call["json"]["input"]) == {"text", "voice", "language_type"}  # type: ignore[index]
