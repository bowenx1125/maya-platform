"""Server-side provider selection for Maya capabilities."""

from __future__ import annotations

from app.core.config import Settings
from app.modules.knowledge.providers import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_REGION,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingProvider,
    EmbeddingTransport,
    HttpxEmbeddingTransport,
    MockEmbeddingProvider,
)
from app.providers.dashscope import (
    DashScopeConfig,
    DashScopeTTSProvider,
    DashScopeVoiceCloneProvider,
)
from app.providers.llm import (
    DashScopeLLMAdapter,
    DashScopeLLMConfig,
    LLMOutboundManifestV1,
    LLMProvider,
    LLMTokenizerPort,
    LLMTransport,
)
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


def llm_provider(
    settings: Settings,
    *,
    transport: LLMTransport | None = None,
    tokenizer: LLMTokenizerPort | object | None = None,
    outbound_manifest: LLMOutboundManifestV1 | None = None,
) -> LLMProvider:
    """Compose Mock or the inert fixed LLM adapter without making a call."""

    if settings.llm_provider == "mock":
        return select_llm_provider(settings)
    if settings.llm_provider != "dashscope":
        raise RuntimeError("llm provider is not supported")
    if (
        not settings.dashscope_api_key
        or not settings.dashscope_workspace_id
        or settings.dashscope_region != "cn-beijing"
    ):
        raise RuntimeError("DashScope LLM provider is not configured")
    policy_hash = settings.provider_policy_hash_for("llm")
    if not isinstance(policy_hash, str) or not policy_hash:
        raise RuntimeError(
            "LLM_PROVIDER_POLICY_HASH is required for the selected real LLM resource"
        )
    return DashScopeLLMAdapter(
        DashScopeLLMConfig(
            api_key=settings.dashscope_api_key,
            workspace_id=settings.dashscope_workspace_id,
            region=settings.dashscope_region,
            model_key=settings.llm_model,
            policy_hash=policy_hash,
        ),
        transport,
        tokenizer=tokenizer,
        outbound_manifest=outbound_manifest,
    )


def embedding_provider(
    settings: Settings,
    *,
    transport: EmbeddingTransport | None = None,
) -> EmbeddingProvider:
    """Return the fixed embedding adapter without performing a request."""

    if settings.embedding_provider == "mock":
        return MockEmbeddingProvider()
    if settings.embedding_provider != "dashscope":
        raise RuntimeError("embedding provider is not supported")
    if (
        not settings.dashscope_api_key
        or not settings.dashscope_workspace_id
        or settings.dashscope_region != "cn-beijing"
    ):
        raise RuntimeError("DashScope embedding provider is not configured")
    return DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(
            api_key=settings.dashscope_api_key,
            workspace_id=settings.dashscope_workspace_id,
            region=REAL_EMBEDDING_REGION,
            model_key=REAL_EMBEDDING_MODEL,
            dimension=REAL_EMBEDDING_DIMENSION,
            policy_version=REAL_EMBEDDING_POLICY_VERSION,
        ),
        transport or HttpxEmbeddingTransport(),
    )
