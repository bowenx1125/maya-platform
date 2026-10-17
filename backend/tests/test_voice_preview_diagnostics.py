from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from app.core.errors import PlatformError
from app.modules.voices import preview as voice_preview
from app.modules.voices import router as voice_router
from app.providers.tts import MockTTSProvider, TTSProviderError, TTSResultDNSFailedError
from app.providers.voice import VoiceProviderError

from tests import test_wave1b_voices as voice_fixtures
from tests.conftest import login
from tests.test_wave1b_voices import GROUP_A, _headers, _wav

voice_client = voice_fixtures.voice_client


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (TTSResultDNSFailedError("private-provider-response"), "tts_result_dns_failed"),
        (
            TTSProviderError("private-provider-response", safe_code="private-provider-code"),
            "tts_failed",
        ),
    ],
)
def test_preview_failure_logs_only_safe_classification(
    voice_client: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: TTSProviderError,
    expected_code: str,
) -> None:
    client, _, _ = voice_client
    _, csrf = login(client, "bowen")
    enrolled = client.post(
        f"/api/v1/groups/{GROUP_A}/voice-profiles",
        headers=_headers(csrf, "voice-preview-diagnostics"),
        data={"consent_accepted": "true", "consent_copy_version": "voice-consent-v1"},
        files={"file": ("sample.wav", _wav(), "audio/wav")},
    )
    assert enrolled.status_code == 202
    provider = MockTTSProvider()
    provider.next_error = error
    monkeypatch.setattr(voice_preview, "tts_provider", lambda _: provider)
    response = client.post(
        f"/api/v1/voice-profiles/{enrolled.json()['id']}/preview",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "provider_unavailable"
    assert f"safe_code={expected_code}" in caplog.text
    assert "private-provider" not in caplog.text + response.text
    assert provider.synthesize_calls == 0


@pytest.fixture
def direct_preview_profile(monkeypatch: pytest.MonkeyPatch) -> Any:
    profile = SimpleNamespace(
        id="cc5546ad-cace-4d28-b362-1f8cb653462f",
        status="preview_ready",
        target_model_key="mock-voice-v1",
        external_id_encrypted=None,
    )
    monkeypatch.setattr(
        voice_preview,
        "visible_student_voice",
        lambda _db, _context, _profile_id: SimpleNamespace(profile=profile),
    )
    return profile


def test_direct_preview_configuration_failure_is_logged_without_private_data(
    direct_preview_profile: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unavailable(_settings: Any) -> Any:
        raise RuntimeError("private-provider-key-or-endpoint")

    monkeypatch.setattr(voice_preview, "tts_provider", unavailable)
    with pytest.raises(PlatformError) as caught:
        voice_preview.create_voice_preview(None, None, direct_preview_profile.id, None)  # type: ignore[arg-type]
    assert caught.value.code == "provider_unavailable"
    assert "safe_code=tts_configuration_unavailable" in caplog.text
    assert f"profile_id={direct_preview_profile.id}" in caplog.text
    assert "private-provider" not in caplog.text + str(caught.value)
    assert direct_preview_profile.status == "preview_ready"


def test_direct_preview_mapping_failure_stops_before_synthesis_and_logs_safely(
    direct_preview_profile: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = MockTTSProvider()
    with pytest.raises(PlatformError) as caught:
        voice_preview.create_voice_preview(
            None,
            None,
            direct_preview_profile.id,
            None,
            provider=provider,  # type: ignore[arg-type]
        )
    assert caught.value.code == "provider_unavailable"
    assert "safe_code=voice_mapping_unavailable" in caplog.text
    assert provider.synthesize_calls == 0
    assert direct_preview_profile.status == "preview_ready"


def test_direct_preview_invalid_provider_configuration_is_logged_safely(
    direct_preview_profile: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class InvalidConfiguration:
        def synthesize(self, *_args: Any, **_kwargs: Any) -> Any:
            raise VoiceProviderError("private-provider-workspace")

    monkeypatch.setattr(voice_preview, "_tts_external_id", lambda _profile, _settings: "fixture")
    monkeypatch.setattr(voice_preview, "next_preview_line", lambda _db: "fixture line")
    with pytest.raises(PlatformError) as caught:
        voice_preview.create_voice_preview(
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            direct_preview_profile.id,
            None,  # type: ignore[arg-type]
            provider=InvalidConfiguration(),  # type: ignore[arg-type]
        )
    assert caught.value.code == "provider_unavailable"
    assert "safe_code=tts_configuration_unavailable" in caplog.text
    assert "private-provider" not in caplog.text + str(caught.value)


def test_direct_preview_route_logs_unknown_runtime_failure_without_exception_body(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(*_args: Any) -> Any:
        raise RuntimeError("private-provider-response")

    monkeypatch.setattr(voice_router, "create_voice_preview", fail)
    with pytest.raises(PlatformError) as caught:
        voice_router.create_voice_preview_route(UUID("cc5546ad-cace-4d28-b362-1f8cb653462f"))
    assert caught.value.code == "provider_unavailable"
    assert "operation=preview safe_code=provider_unavailable" in caplog.text
    assert "private-provider" not in caplog.text + str(caught.value)
