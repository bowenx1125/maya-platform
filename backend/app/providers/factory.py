"""Server-side provider selection for voice and TTS."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.dashscope import (
    DashScopeConfig,
    DashScopeTTSProvider,
    DashScopeVoiceCloneProvider,
)
from app.providers.tts import MockTTSProvider, TTSProvider
from app.providers.voice import MockVoiceCloneProvider, VoiceCloneProvider


def _dashscope_config(settings: Settings) -> DashScopeConfig:
    if (
        not settings.dashscope_api_key
        or not settings.dashscope_workspace_id
        or not settings.dashscope_region
    ):
        raise RuntimeError("DashScope provider is not configured")
    return DashScopeConfig(
        api_key=settings.dashscope_api_key,
        workspace_id=settings.dashscope_workspace_id,
        region=settings.dashscope_region,
    )


def voice_provider(settings: Settings) -> VoiceCloneProvider:
    if settings.voice_provider == "mock":
        return MockVoiceCloneProvider()
    if settings.voice_provider == "dashscope":
        return DashScopeVoiceCloneProvider(_dashscope_config(settings))
    raise RuntimeError("voice provider is not supported")


def tts_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "mock":
        return MockTTSProvider()
    if settings.tts_provider == "dashscope":
        return DashScopeTTSProvider(_dashscope_config(settings))
    raise RuntimeError("tts provider is not supported")
