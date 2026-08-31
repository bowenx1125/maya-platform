"""Single-attempt HTTP transport for the fixed Beijing Qwen Chat resource."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

LLM_CONNECT_TIMEOUT_SECONDS = 5.0
LLM_TOTAL_TIMEOUT_SECONDS = 120.0
LLM_ACCEPTED_HTTP_STATUS = 200

TransportAcceptance = Literal["not_sent", "acceptance_unknown", "accepted"]


class LLMTransportError(RuntimeError):
    """A transport outcome that is safe to expose without supplier details."""

    acceptance: TransportAcceptance = "acceptance_unknown"
    safe_error_code = "llm_transport_failed"

    def __init__(self, message: str = "LLM transport failed") -> None:
        super().__init__(message)


class LLMTransportNotSent(LLMTransportError):
    """DNS/TCP/TLS/connect failed before request bytes could be accepted."""

    acceptance: TransportAcceptance = "not_sent"
    safe_error_code = "llm_transport_not_sent"

    def __init__(self, message: str = "LLM request was not sent") -> None:
        super().__init__(message)


class LLMAcceptanceUnknown(LLMTransportError):
    """Write/read/protocol failure where supplier acceptance is unknowable."""

    acceptance: TransportAcceptance = "acceptance_unknown"
    safe_error_code = "llm_acceptance_unknown"

    def __init__(self, message: str = "LLM request acceptance is unknown") -> None:
        super().__init__(message)


# Descriptive aliases used by callers that name the classification first.
LLMTransportAcceptanceUnknown = LLMAcceptanceUnknown
LLMAcceptanceUnknownError = LLMAcceptanceUnknown
LLMTransportUnknown = LLMAcceptanceUnknown
LLMTransportAcceptanceUnknownError = LLMAcceptanceUnknown


@dataclass(frozen=True, slots=True)
class LLMTransportResponse:
    """Minimal fake-friendly response; no provider headers are persisted."""

    status_code: int
    payload: object
    headers: Mapping[str, str] = field(default_factory=dict)

    def json(self) -> object:
        return self.payload


class LLMTransport(Protocol):
    """The only side-effecting port accepted by :class:`DashScopeLLMAdapter`."""

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: object,
    ) -> object:
        """Make exactly one HTTP attempt and return its response."""


def classify_http_status(status_code: int) -> TransportAcceptance:
    """An HTTP status proves a response was received and is therefore charged."""

    if isinstance(status_code, bool) or not isinstance(status_code, int):
        raise ValueError("HTTP status is invalid")
    return "accepted"


class HttpxLLMTransport:
    """No-redirect, no-retry HTTPX transport with closed timeout classes."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    @staticmethod
    def timeout() -> httpx.Timeout:
        # ``timeout=120`` gives total/read/write/pool coverage while the
        # explicit connect value preserves the frozen five-second connect cap.
        return httpx.Timeout(
            timeout=LLM_TOTAL_TIMEOUT_SECONDS,
            connect=LLM_CONNECT_TIMEOUT_SECONDS,
        )

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: object = LLM_TOTAL_TIMEOUT_SECONDS,
    ) -> object:
        # A caller may pass the frozen total as a float or an HTTPX timeout;
        # either way redirects stay disabled and this method performs one call.
        resolved_timeout: float | httpx.Timeout
        if isinstance(timeout, httpx.Timeout):
            resolved_timeout = timeout
        else:
            resolved_timeout = self.timeout()
        try:
            if self.client is not None:
                return self.client.post(
                    url,
                    headers=dict(headers),
                    json=dict(json),
                    timeout=resolved_timeout,
                    follow_redirects=False,
                )
            with httpx.Client(follow_redirects=False) as client:
                return client.post(
                    url,
                    headers=dict(headers),
                    json=dict(json),
                    timeout=resolved_timeout,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise LLMTransportNotSent() from exc
        except (
            httpx.WriteError,
            httpx.WriteTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            httpx.TimeoutException,
        ) as exc:
            # A write may have begun and read/protocol failures happen after
            # send.  They can never authorize an automatic resend.
            raise LLMAcceptanceUnknown() from exc
        except httpx.HTTPError as exc:
            # Unknown HTTPX failures are conservatively uncertain.
            raise LLMAcceptanceUnknown() from exc


# Naming aliases mirror the embedding adapter and keep imports discoverable.
DashScopeLLMTransport = HttpxLLMTransport
LLMTransportResponseV1 = LLMTransportResponse


__all__ = [
    "DashScopeLLMTransport",
    "HttpxLLMTransport",
    "LLM_ACCEPTED_HTTP_STATUS",
    "LLM_CONNECT_TIMEOUT_SECONDS",
    "LLM_TOTAL_TIMEOUT_SECONDS",
    "LLMAcceptanceUnknown",
    "LLMAcceptanceUnknownError",
    "LLMTransport",
    "LLMTransportAcceptanceUnknown",
    "LLMTransportAcceptanceUnknownError",
    "LLMTransportError",
    "LLMTransportNotSent",
    "LLMTransportResponse",
    "LLMTransportUnknown",
    "LLMTransportResponseV1",
    "TransportAcceptance",
    "classify_http_status",
]
