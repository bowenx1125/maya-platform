"""Injected-transport embedding adapters.

The adapters in this module are inert until a caller explicitly supplies a
transport and invokes ``embed_batch``.  There is no selector, environment
lookup, default client or network side effect here.  This makes the adapter
safe to exercise with a local fake transport and lets the application layer
perform its own Gate/policy/reservation checks first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx

from app.core.request_timing import provider_call

from .embedding import (
    EmbeddingResponseDialect,
    ValidatedEmbeddingBatchV1,
    validate_embedding_batch_response,
)
from .packing import (
    MAX_BATCH_ITEMS,
    MAX_BATCH_TOKENS,
    EmbeddingBatchV1,
    EmbeddingPlanError,
)
from .snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
)

DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH = (
    "/api/v1/services/embeddings/text-embedding/text-embedding"
)
LOGGER = logging.getLogger(__name__)

EmbeddingTransportPhase = Literal["connect", "write", "read", "response", "decode", "unknown"]

_SAFE_TRANSPORT_EXCEPTION_CLASSES = frozenset(
    {
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "WriteError",
        "NetworkError",
        "TimeoutException",
        "TimeoutError",
        "ConnectionError",
        "OSError",
        "EmbeddingTransportNotSent",
        "EmbeddingAcceptanceUnknown",
        "HTTPStatus",
        "UnknownError",
    }
)
_SAFE_CLIENT_MODES = frozenset({"managed", "provided", "injected"})


@dataclass(frozen=True, slots=True)
class EmbeddingTransportDiagnostics:
    """Safe transport facts retained without provider request content."""

    exception_class: str
    phase: EmbeddingTransportPhase
    elapsed_ms: int
    timeout_seconds: float
    client_mode: str
    trust_env: bool | None
    http_status: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "exception_class": self.exception_class,
            "phase": self.phase,
            "elapsed_ms": self.elapsed_ms,
            "timeout_seconds": self.timeout_seconds,
            "client_mode": self.client_mode,
            "trust_env": self.trust_env,
            "http_status": self.http_status,
        }


def _safe_transport_exception_class(error: BaseException | None) -> str:
    if error is None:
        return "HTTPStatus"
    name = type(error).__name__
    return name if name in _SAFE_TRANSPORT_EXCEPTION_CLASSES else "UnknownError"


def _transport_phase(error: BaseException | None) -> EmbeddingTransportPhase:
    if error is None:
        return "response"
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connect"
    if isinstance(error, (httpx.ReadError, httpx.ReadTimeout)):
        return "read"
    if isinstance(error, httpx.WriteError):
        return "write"
    return "unknown"


def _transport_diagnostics(
    error: BaseException | None,
    *,
    started: float,
    timeout_seconds: float,
    client_mode: str,
    trust_env: bool | None,
    phase: EmbeddingTransportPhase | None = None,
    http_status: int | None = None,
) -> EmbeddingTransportDiagnostics:
    return EmbeddingTransportDiagnostics(
        exception_class=_safe_transport_exception_class(error),
        phase=phase or _transport_phase(error),
        elapsed_ms=max(0, int(round((time.monotonic() - started) * 1000))),
        timeout_seconds=float(timeout_seconds),
        client_mode=client_mode if client_mode in _SAFE_CLIENT_MODES else "injected",
        trust_env=trust_env,
        http_status=http_status,
    )


def _log_transport_diagnostics(diagnostics: EmbeddingTransportDiagnostics) -> None:
    """Emit only the allowlisted diagnostic projection; never ``exc_info``."""

    LOGGER.warning(
        "embedding_transport_failure %s",
        json.dumps(diagnostics.as_dict(), sort_keys=True, separators=(",", ":")),
        extra={"embedding_transport": diagnostics.as_dict()},
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

    def __init__(self, client: httpx.Client | None = None, *, trust_env: bool = True) -> None:
        self.client = client
        self._trust_env = bool(trust_env)

    @property
    def client_mode(self) -> str:
        return "provided" if self.client is not None else "managed"

    @property
    def trust_env(self) -> bool | None:
        if self.client is None:
            return self._trust_env
        value = getattr(self.client, "_trust_env", None)
        return value if isinstance(value, bool) else None

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        started = time.monotonic()
        try:
            with provider_call("embedding"):
                return self._post(url, headers=headers, json=json, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=timeout,
                client_mode=self.client_mode,
                trust_env=self.trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingTransportNotSent(diagnostics=diagnostics) from exc
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=timeout,
                client_mode=self.client_mode,
                trust_env=self.trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingAcceptanceUnknown(diagnostics=diagnostics) from exc

    def _post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        if self.client is not None:
            return self.client.post(
                url,
                headers=dict(headers),
                json=dict(json),
                timeout=timeout,
                follow_redirects=False,
            )
        with httpx.Client(follow_redirects=False, trust_env=self._trust_env) as client:
            return client.post(
                url,
                headers=dict(headers),
                json=dict(json),
                timeout=timeout,
            )


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
        diagnostics: EmbeddingTransportDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics: dict[str, object] | None = (
            diagnostics.as_dict() if diagnostics is not None else None
        )


class EmbeddingHTTPRejected(EmbeddingProviderError):
    """A supplier HTTP status explicitly rejected the request."""

    def __init__(
        self,
        status_code: int,
        *,
        diagnostics: EmbeddingTransportDiagnostics | None = None,
    ) -> None:
        self.status_code = status_code
        super().__init__(code="provider_http_rejected", diagnostics=diagnostics)


class EmbeddingTransportNotSent(EmbeddingProviderError):
    """Transport proved that no supplier request could have been accepted."""

    def __init__(
        self,
        message: str = "embedding request was not sent",
        *,
        diagnostics: EmbeddingTransportDiagnostics | None = None,
    ) -> None:
        super().__init__(message, code="provider_not_sent", diagnostics=diagnostics)


class EmbeddingAcceptanceUnknown(EmbeddingProviderError):
    """The connection outcome cannot exclude supplier acceptance."""

    def __init__(
        self,
        message: str = "embedding request acceptance is unknown",
        *,
        diagnostics: EmbeddingTransportDiagnostics | None = None,
    ) -> None:
        super().__init__(message, code="acceptance_unknown", diagnostics=diagnostics)


class EmbeddingAdapterError(EmbeddingProviderError):
    """The adapter received an invalid HTTP envelope or supplier JSON shape."""

    def __init__(
        self,
        message: str = "embedding provider response invalid",
        *,
        diagnostics: EmbeddingTransportDiagnostics | None = None,
    ) -> None:
        super().__init__(message, code="provider_response_invalid", diagnostics=diagnostics)


@dataclass(frozen=True, slots=True)
class DashScopeEmbeddingConfig:
    """Fixed Beijing embedding resource configuration.

    The config carries no selector.  The caller must decide when this fixed
    resource is allowed and provide a transport explicitly.
    """

    api_key: str = field(default="", repr=False)
    workspace_id: str = ""
    region: str = REAL_EMBEDDING_REGION
    model_key: str = REAL_EMBEDDING_MODEL
    dimension: int = REAL_EMBEDDING_DIMENSION
    policy_version: str = REAL_EMBEDDING_POLICY_VERSION
    endpoint: str | None = None

    @property
    def resolved_endpoint(self) -> str:
        if self.region != REAL_EMBEDDING_REGION:
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


def _validate_dashscope_resource(config: DashScopeEmbeddingConfig) -> str:
    """Validate the exact real-provider resource before request construction."""

    if (
        config.region != REAL_EMBEDDING_REGION
        or config.model_key != REAL_EMBEDDING_MODEL
        or config.dimension != REAL_EMBEDDING_DIMENSION
        or config.policy_version != REAL_EMBEDDING_POLICY_VERSION
        or not config.workspace_id
    ):
        raise ValueError("DashScope embedding resource is not the fixed 1024 contract")
    endpoint = config.resolved_endpoint
    parsed = urlsplit(endpoint)
    expected_host = f"{config.workspace_id}.cn-beijing.maas.aliyuncs.com".lower()
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != expected_host
        or parsed.path != DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DashScope embedding endpoint is not the fixed Beijing workspace")
    return endpoint


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


def _validate_batch_before_send(
    batch: EmbeddingBatchV1,
    *,
    expected_model: str | None = None,
    expected_dimension: int | None = None,
    expected_provider: str | None = None,
    expected_region: str | None = None,
    expected_policy_version: str | None = None,
) -> None:
    if not batch.items:
        raise EmbeddingPlanError("embedding batch cannot be empty", code="embedding_plan_empty")
    if len(batch.items) > MAX_BATCH_ITEMS:
        raise EmbeddingPlanError(
            "embedding batch exceeds ten items", code="embedding_batch_items_exceeded"
        )
    if isinstance(batch.total_tokens, bool) or not isinstance(batch.total_tokens, int):
        raise EmbeddingPlanError(
            "embedding batch token count is invalid", code="embedding_batch_tokens_invalid"
        )
    if any(
        isinstance(item.token_count, bool)
        or not isinstance(item.token_count, int)
        or item.token_count < 0
        for item in batch.items
    ):
        raise EmbeddingPlanError(
            "embedding item token count is invalid", code="embedding_batch_tokens_invalid"
        )
    if batch.total_tokens > MAX_BATCH_TOKENS or any(
        item.token_count > MAX_BATCH_TOKENS for item in batch.items
    ):
        raise EmbeddingPlanError(
            "embedding batch exceeds the 30000-token supplier limit",
            code="embedding_batch_tokens_exceeded",
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
    if any(
        hashlib.sha256(item.text.encode("utf-8")).hexdigest() != item.chunk_sha256
        for item in batch.items
    ):
        raise EmbeddingPlanError(
            "embedding batch contains altered chunk text",
            code="embedding_build_mismatch",
        )
    if expected_model is not None and batch.model_key != expected_model:
        raise EmbeddingPlanError(
            "embedding batch model does not match the selected resource",
            code="embedding_model_mismatch",
        )
    if expected_dimension is not None and batch.dimension != expected_dimension:
        raise EmbeddingPlanError(
            "embedding batch dimension does not match the selected resource",
            code="embedding_dimension_mismatch",
        )
    if expected_provider is not None and batch.embedding_provider != expected_provider:
        raise EmbeddingPlanError(
            "embedding batch provider does not match the selected resource",
            code="embedding_provider_mismatch",
        )
    if expected_region is not None and batch.embedding_region != expected_region:
        raise EmbeddingPlanError(
            "embedding batch region does not match the selected resource",
            code="embedding_region_mismatch",
        )
    if expected_policy_version is not None and batch.policy_version != expected_policy_version:
        raise EmbeddingPlanError(
            "embedding batch policy does not match the selected resource",
            code="embedding_policy_mismatch",
        )


class OpenAICompatibleEmbeddingAdapter:
    """Embedding adapter for an injected OpenAI-compatible transport."""

    key = "openai-compatible"
    # This generic adapter is retained as an inert compatibility seam.  It is
    # not a permitted Maya identity; the fixed production path is DashScope
    # below.  Leaving provider blank avoids pretending that an arbitrary
    # OpenAI-compatible endpoint is a closed resource.
    provider = ""
    region = ""
    response_dialect: EmbeddingResponseDialect = "generic"

    def __init__(
        self,
        transport: EmbeddingTransport,
        *,
        endpoint: str,
        api_key: str = "",
        model_key: str = REAL_EMBEDDING_MODEL,
        dimension: int = REAL_EMBEDDING_DIMENSION,
        policy_version: str = REAL_EMBEDDING_POLICY_VERSION,
        timeout_seconds: float = 120.0,
    ) -> None:
        _validate_https_endpoint(endpoint)
        if not model_key or dimension < 1 or timeout_seconds <= 0:
            raise ValueError("embedding adapter configuration is invalid")
        if not policy_version:
            raise ValueError("embedding adapter policy version is required")
        self.transport = transport
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_key = model_key
        self.dimension = dimension
        self.policy_version = policy_version
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
        _validate_batch_before_send(
            batch,
            expected_model=self.model_key,
            expected_dimension=self.dimension,
            expected_provider=self.provider or None,
            expected_region=self.region or None,
            expected_policy_version=self.policy_version,
        )
        started = time.monotonic()
        raw_client_mode = getattr(self.transport, "client_mode", "injected")
        client_mode = (
            raw_client_mode
            if isinstance(raw_client_mode, str) and raw_client_mode in _SAFE_CLIENT_MODES
            else "injected"
        )
        trust_env_value = getattr(self.transport, "trust_env", None)
        trust_env = trust_env_value if isinstance(trust_env_value, bool) else None
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
        except EmbeddingProviderError as exc:
            if exc.diagnostics is None and exc.code in {
                "provider_not_sent",
                "acceptance_unknown",
            }:
                diagnostics = _transport_diagnostics(
                    exc.__cause__ if isinstance(exc.__cause__, BaseException) else exc,
                    started=started,
                    timeout_seconds=self.timeout_seconds,
                    client_mode=client_mode,
                    trust_env=trust_env,
                )
                exc.diagnostics = diagnostics.as_dict()
                _log_transport_diagnostics(diagnostics)
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Keep this classification here as well as in HttpxEmbeddingTransport:
            # injected fakes may raise the concrete HTTPX exception directly.
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingTransportNotSent(diagnostics=diagnostics) from exc
        except (
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            httpx.TimeoutException,
        ) as exc:
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingAcceptanceUnknown(diagnostics=diagnostics) from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            # A generic broken connection cannot prove whether the supplier
            # accepted the request.  Callers must persist this state and never
            # retry it automatically.
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingAcceptanceUnknown(diagnostics=diagnostics) from exc
        except Exception as exc:
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingProviderError(diagnostics=diagnostics) from exc
        try:
            status_code, payload = _response_parts(response)
        except EmbeddingAdapterError as exc:
            diagnostics = _transport_diagnostics(
                exc,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
                phase="decode",
            )
            exc.diagnostics = diagnostics.as_dict()
            _log_transport_diagnostics(diagnostics)
            raise
        if status_code < 200 or status_code >= 300:
            diagnostics = _transport_diagnostics(
                None,
                started=started,
                timeout_seconds=self.timeout_seconds,
                client_mode=client_mode,
                trust_env=trust_env,
                phase="response",
                http_status=status_code,
            )
            _log_transport_diagnostics(diagnostics)
            raise EmbeddingHTTPRejected(status_code, diagnostics=diagnostics)
        return validate_embedding_batch_response(
            payload,
            batch,
            expected_model=self.model_key,
            expected_dimension=self.dimension,
            expected_provider=self.provider,
            expected_region=self.region or None,
            expected_policy_version=self.policy_version,
            response_dialect=self.response_dialect,
        )

    def embed(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        return self.embed_batch(batch)


class DashScopeEmbeddingAdapter(OpenAICompatibleEmbeddingAdapter):
    """Fixed Beijing DashScope adapter over a caller-injected transport."""

    key = "dashscope"
    provider = REAL_EMBEDDING_PROVIDER
    region = REAL_EMBEDDING_REGION
    response_dialect: EmbeddingResponseDialect = "dashscope_native"

    def __init__(
        self,
        config: DashScopeEmbeddingConfig,
        transport: EmbeddingTransport,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        endpoint = _validate_dashscope_resource(config)
        super().__init__(
            transport,
            endpoint=endpoint,
            api_key=config.api_key,
            model_key=config.model_key,
            dimension=config.dimension,
            policy_version=config.policy_version,
            timeout_seconds=timeout_seconds,
        )
        self.config = config

    def _payload(self, batch: EmbeddingBatchV1) -> dict[str, object]:
        """Use DashScope's nested text-array request envelope."""

        return {
            "model": self.model_key,
            "input": {"texts": list(batch.texts)},
            "parameters": {"dimension": REAL_EMBEDDING_DIMENSION},
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
    "EmbeddingHTTPRejected",
    "EmbeddingProviderError",
    "EmbeddingTransportDiagnostics",
    "EmbeddingTransport",
    "EmbeddingTransportNotSent",
    "EmbeddingTransportResponse",
    "HttpxEmbeddingTransport",
    "OpenAICompatibleEmbeddingAdapter",
    "OpenAIEmbeddingAdapter",
]
