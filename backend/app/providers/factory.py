"""Server-side provider selection for Wave 1 and Wave 2 capabilities."""

from __future__ import annotations

from app.core.config import Settings
from app.providers.dashscope import (
    DashScopeConfig,
    DashScopeTTSProvider,
    DashScopeVoiceCloneProvider,
)
from app.providers.llm import LLMProvider
from app.providers.llm import llm_provider as select_llm_provider
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


def llm_provider(settings: Settings) -> LLMProvider:
    """Return the reviewed Wave 2 text provider.

    Wave 2 intentionally exposes only the deterministic Mock implementation;
    ``select_llm_provider`` fails closed for a real selector.
    """

    return select_llm_provider(settings)
