"""Injected-transport embedding adapters.

The adapters in this module are inert until a caller explicitly supplies a
transport and invokes ``embed_batch``.  There is no selector, environment
lookup, default client or network side effect here.  This makes the adapter
safe to exercise with a local fake transport and lets the application layer
perform its own Gate/policy/reservation checks first.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .embedding import ValidatedEmbeddingBatchV1, validate_embedding_batch_response
from .packing import (
    MAX_BATCH_ITEMS,
    MAX_BATCH_TOKENS,
    MAX_ITEM_TOKENS,
    EmbeddingBatchV1,
    EmbeddingPlanError,
)
from .snapshot_build import FIXED_EMBEDDING_DIMENSION, FIXED_EMBEDDING_MODEL

DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH = (
    "/api/v1/services/embeddings/text-embedding/text-embedding"
)


class EmbeddingTransport(Protocol):
    """The only side-effecting port accepted by an embedding adapter."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        """Return a transport response or raise a classified transport error."""


class HttpxEmbeddingTransport:
    """Single-attempt HTTP transport with explicit acceptance classification."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        try:
            if self.client is not None:
                return self.client.post(
                    url,
                    headers=dict(headers),
                    json=dict(json),
                    timeout=timeout,
                    follow_redirects=False,
                )
            with httpx.Client(follow_redirects=False) as client:
                return client.post(
                    url,
                    headers=dict(headers),
                    json=dict(json),
                    timeout=timeout,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise EmbeddingTransportNotSent() from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise EmbeddingAcceptanceUnknown() from exc


@dataclass(frozen=True, slots=True)
class EmbeddingTransportResponse:
    """Small fake-friendly response value; no httpx dependency is required."""

    status_code: int
    payload: object
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> object:
        return self.payload


class EmbeddingProviderError(RuntimeError):
    """A safe provider/transport failure; supplier details stay server-side."""

    def __init__(
        self,
        message: str = "embedding provider unavailable",
        *,
        code: str = "provider_unavailable",
    ) -> None:
        super().__init__(message)
        self.code = code


class EmbeddingTransportNotSent(EmbeddingProviderError):
    """Transport proved that no supplier request could have been accepted."""

    def __init__(self, message: str = "embedding request was not sent") -> None:
        super().__init__(message, code="provider_not_sent")


class EmbeddingAcceptanceUnknown(EmbeddingProviderError):
    """The connection outcome cannot exclude supplier acceptance."""

    def __init__(self, message: str = "embedding request acceptance is unknown") -> None:
        super().__init__(message, code="acceptance_unknown")


class EmbeddingAdapterError(EmbeddingProviderError):
    """The adapter received an invalid HTTP envelope or supplier JSON shape."""

    def __init__(self, message: str = "embedding provider response invalid") -> None:
        super().__init__(message, code="provider_response_invalid")


@dataclass(frozen=True, slots=True)
class DashScopeEmbeddingConfig:
    """Fixed Beijing embedding resource configuration.

    The config carries no selector.  The caller must decide when this fixed
    resource is allowed and provide a transport explicitly.
    """

    api_key: str = ""
    workspace_id: str = ""
    region: str = "cn-beijing"
    model_key: str = FIXED_EMBEDDING_MODEL
    dimension: int = FIXED_EMBEDDING_DIMENSION
    endpoint: str | None = None

    @property
    def resolved_endpoint(self) -> str:
        if self.region != "cn-beijing":
            raise ValueError("embedding endpoint must be in cn-beijing")
        if self.endpoint is not None:
            _validate_https_endpoint(self.endpoint)
            return self.endpoint
        if not self.workspace_id or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in self.workspace_id
        ):
            raise ValueError("embedding workspace is invalid")
        return f"https://{self.workspace_id}.cn-beijing.maas.aliyuncs.com{DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH}"


def _validate_https_endpoint(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port is not None
    ):
        raise ValueError("embedding endpoint is invalid")


def _response_parts(response: object) -> tuple[int, object]:
    if isinstance(response, EmbeddingTransportResponse):
        return response.status_code, response.payload
    if isinstance(response, Mapping):
        return 200, response
    status = getattr(response, "status_code", None)
    json_method = getattr(response, "json", None)
    if isinstance(status, int) and callable(json_method):
        try:
            return status, json_method()
        except Exception as exc:
            raise EmbeddingAdapterError() from exc
    raise EmbeddingAdapterError("embedding transport returned an invalid response")


def _validate_batch_before_send(batch: EmbeddingBatchV1) -> None:
    if not batch.items:
        raise EmbeddingPlanError("embedding batch cannot be empty", code="embedding_plan_empty")
    if len(batch.items) > MAX_BATCH_ITEMS:
        raise EmbeddingPlanError(
            "embedding batch exceeds ten items", code="embedding_batch_items_exceeded"
        )
    if batch.total_tokens > MAX_BATCH_TOKENS:
        raise EmbeddingPlanError(
            "embedding batch exceeds 30,000 counted tokens",
            code="embedding_batch_tokens_exceeded",
        )
    if any(item.token_count > MAX_ITEM_TOKENS for item in batch.items):
        raise EmbeddingPlanError(
            "embedding item exceeds 8,000 counted tokens",
            code="embedding_item_too_large",
        )
    if batch.total_tokens != sum(item.token_count for item in batch.items):
        raise EmbeddingPlanError(
            "embedding batch token count is inconsistent",
            code="embedding_batch_tokens_invalid",
        )
    if any(item.build_manifest_hash != batch.build_manifest_hash for item in batch.items):
        raise EmbeddingPlanError(
            "embedding batch contains a different SnapshotBuild",
            code="embedding_build_mismatch",
        )


class OpenAICompatibleEmbeddingAdapter:
    """Embedding adapter for an injected OpenAI-compatible transport."""

    key = "openai-compatible"

    def __init__(
        self,
        transport: EmbeddingTransport,
        *,
        endpoint: str,
        api_key: str = "",
        model_key: str = FIXED_EMBEDDING_MODEL,
        dimension: int = FIXED_EMBEDDING_DIMENSION,
        timeout_seconds: float = 30.0,
    ) -> None:
        _validate_https_endpoint(endpoint)
        if not model_key or dimension < 1 or timeout_seconds <= 0:
            raise ValueError("embedding adapter configuration is invalid")
        self.transport = transport
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_key = model_key
        self.dimension = dimension
        self.timeout_seconds = timeout_seconds

    @property
    def target_model_key(self) -> str:
        return self.model_key

    def _payload(self, batch: EmbeddingBatchV1) -> dict[str, object]:
        return {
            "model": self.model_key,
            "input": list(batch.texts),
            "encoding_format": "float",
        }

    def embed_batch(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        _validate_batch_before_send(batch)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = self.transport.post(
                self.endpoint,
                headers=headers,
                json=self._payload(batch),
                timeout=self.timeout_seconds,
            )
        except EmbeddingProviderError:
            raise
        except (TimeoutError, ConnectionError, OSError) as exc:
            # A generic broken connection cannot prove whether the supplier
            # accepted the request.  Callers must persist this state and never
            # retry it automatically.
            raise EmbeddingAcceptanceUnknown() from exc
        except Exception as exc:
            raise EmbeddingProviderError() from exc
        status_code, payload = _response_parts(response)
        if status_code < 200 or status_code >= 300:
            raise EmbeddingProviderError(code="provider_http_rejected")
        return validate_embedding_batch_response(
            payload,
            batch,
            expected_model=self.model_key,
            expected_dimension=self.dimension,
        )

    def embed(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        return self.embed_batch(batch)


class DashScopeEmbeddingAdapter(OpenAICompatibleEmbeddingAdapter):
    """Fixed Beijing DashScope adapter over a caller-injected transport."""

    key = "dashscope"

    def __init__(
        self,
        config: DashScopeEmbeddingConfig,
        transport: EmbeddingTransport,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            transport,
            endpoint=config.resolved_endpoint,
            api_key=config.api_key,
            model_key=config.model_key,
            dimension=config.dimension,
            timeout_seconds=timeout_seconds,
        )
        self.config = config

    def _payload(self, batch: EmbeddingBatchV1) -> dict[str, object]:
        """Use DashScope's nested text-array request envelope."""

        return {
            "model": self.model_key,
            "input": {"texts": list(batch.texts)},
        }


# Explicit aliases keep integration imports descriptive without creating a
# second implementation or a selector side effect.
DashScopeEmbeddingProvider = DashScopeEmbeddingAdapter
OpenAIEmbeddingAdapter = OpenAICompatibleEmbeddingAdapter


__all__ = [
    "DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH",
    "DashScopeEmbeddingAdapter",
    "DashScopeEmbeddingConfig",
    "DashScopeEmbeddingProvider",
    "EmbeddingAcceptanceUnknown",
    "EmbeddingAdapterError",
    "EmbeddingProviderError",
    "EmbeddingTransport",
    "EmbeddingTransportNotSent",
    "EmbeddingTransportResponse",
    "HttpxEmbeddingTransport",
    "OpenAICompatibleEmbeddingAdapter",
    "OpenAIEmbeddingAdapter",
]
