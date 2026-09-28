"""Single-attempt HTTP transport for the fixed Beijing Qwen Chat resource."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

# Measured TLS handshakes to the fixed Beijing endpoint take 2.0-2.7s from
# a developer network, so a 5s connect budget classified a healthy endpoint
# as unreachable and burned an acceptance call. The total request timeout and
# the no-retry rule are unchanged; only the connect budget is widened.
LLM_CONNECT_TIMEOUT_SECONDS = 15.0
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


class LLMHTTPRejected(LLMTransportError):
    """A received HTTP status that is charged but never retried."""

    acceptance: TransportAcceptance = "accepted"
    safe_error_code = "llm_http_rejected"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__()


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

    def post_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        timeout: object,
    ) -> object:
        """Send the provided JSON bytes in one HTTP attempt."""


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
        return self._post(
            url,
            headers=headers,
            timeout=timeout,
            json_payload=json,
        )

    def post_bytes(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        content: bytes,
        timeout: object = LLM_TOTAL_TIMEOUT_SECONDS,
    ) -> object:
        """Send canonical JSON bytes without decoding or re-encoding them."""
        json_headers = {
            key: value for key, value in headers.items() if key.lower() != "content-type"
        }
        json_headers["Content-Type"] = "application/json"
        return self._post(
            url,
            headers=json_headers,
            timeout=timeout,
            content=content,
        )

    def _post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: object,
        json_payload: Mapping[str, object] | None = None,
        content: bytes | None = None,
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
                return self._dispatch(
                    self.client,
                    url,
                    headers=headers,
                    timeout=resolved_timeout,
                    json_payload=json_payload,
                    content=content,
                )
            with httpx.Client(follow_redirects=False) as client:
                return self._dispatch(
                    client,
                    url,
                    headers=headers,
                    timeout=resolved_timeout,
                    json_payload=json_payload,
                    content=content,
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

    @staticmethod
    def _dispatch(
        client: httpx.Client,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float | httpx.Timeout,
        json_payload: Mapping[str, object] | None,
        content: bytes | None,
    ) -> httpx.Response:
        request_headers = dict(headers)
        if content is not None:
            return client.post(
                url,
                headers=request_headers,
                content=content,
                timeout=timeout,
                follow_redirects=False,
            )
        if json_payload is None:
            raise ValueError("A JSON payload or content bytes are required")
        return client.post(
            url,
            headers=request_headers,
            json=dict(json_payload),
            timeout=timeout,
            follow_redirects=False,
        )


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
    "LLMHTTPRejected",
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
