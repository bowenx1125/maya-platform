from __future__ import annotations

from typing import Any

import pytest
from app.modules.voices import preview as voice_preview
from app.providers.tts import MockTTSProvider, TTSProviderError, TTSResultDNSFailedError

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
