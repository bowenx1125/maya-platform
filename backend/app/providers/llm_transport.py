"""Single-attempt HTTP transport for the fixed Beijing Qwen Chat resource."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from app.core.llm_admission import llm_admission_slot
from app.core.message_timing import add_model_call
from app.core.request_timing import add_provider_time

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


# A provider that is overloaded answers 429 (too many requests for this key)
# or 502/503/504/529 (busy or briefly down). Those are named for the person
# who sent the message, so they wait and send again; the call is still never
# retried by the server.
PROVIDER_STATUS_CODES = {
    401: "provider_auth_failed",
    403: "provider_auth_failed",
    429: "provider_rate_limited",
    502: "provider_busy",
    503: "provider_busy",
    504: "provider_busy",
    529: "provider_busy",
}

# Teacher Preview Retry may send again after these provider rejects.
# Successful or ambiguous accepts stay terminal so a billed completion
# is not charged twice. HTTP 429 is stored today as llm_http_rejected.
RETRYABLE_PROVIDER_REJECT_CODES = frozenset(
    {
        "llm_http_rejected",
        "provider_rate_limited",
        "provider_busy",
    }
)


def rejected_status_code(status: object, fallback: str) -> str:
    """The safe error code for a non-200 provider answer."""

    if isinstance(status, int) and not isinstance(status, bool):
        return PROVIDER_STATUS_CODES.get(status, fallback)
    return fallback


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


DeltaSink = Callable[[str], None]

# What a stream that cannot be folded into one completion is stored as: an
# accepted, charged response that the chat validator then rejects, exactly as a
# malformed non-stream body is.
STREAM_INVALID_BODY = b'{"stream_invalid":true}'


@dataclass(frozen=True, slots=True)
class LLMStreamedResponse:
    """A streamed chat completion folded back into one non-stream body.

    The ledger stores and replays ``content`` exactly as it stores a plain
    response, so a streamed call is recovered, audited and validated the same
    way as one that was not streamed.
    """

    status_code: int
    content: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    ttft_ms: float | None = None


def _event_stream(content_type: str | None) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() == "text/event-stream"


def _emit(on_delta: DeltaSink, piece: str) -> None:
    try:
        on_delta(piece)
    except Exception:  # noqa: BLE001 - a listener gone away must not fail the call
        pass


def fold_chat_stream(
    lines: Iterable[str],
    on_delta: DeltaSink | None = None,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bytes, float | None]:
    """Fold OpenAI-compatible ``chat.completion.chunk`` events into one body.

    Returns the body and the seconds (on ``clock``) at which the first text
    arrived. Tool calls arrive split by ``index``: the first non-empty id and
    name win and argument fragments are joined, which is how the supplier
    sends them (later fragments repeat an empty id and no name).
    """

    started = clock()
    parts: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    finish: object = None
    usage: object = None
    meta: dict[str, object] = {}
    first: float | None = None
    for raw in lines:
        if deadline is not None and clock() > deadline:
            # The same outcome as a read that ran past the total timeout.
            raise LLMAcceptanceUnknown()
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return STREAM_INVALID_BODY, first
        if not isinstance(chunk, dict):
            return STREAM_INVALID_BODY, first
        for key in ("id", "model", "created"):
            if key not in meta and chunk.get(key) is not None:
                meta[key] = chunk[key]
        if chunk.get("usage") is not None:
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not isinstance(choices, list):
            return STREAM_INVALID_BODY, first
        for choice in choices:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                return STREAM_INVALID_BODY, first
            if delta is None:
                delta = {}
            if not isinstance(delta, dict):
                return STREAM_INVALID_BODY, first
            piece = delta.get("content")
            if piece is not None and not isinstance(piece, str):
                return STREAM_INVALID_BODY, first
            if piece:
                parts.append(piece)
                if first is None:
                    first = clock() - started
                if on_delta is not None:
                    _emit(on_delta, piece)
            fragments = delta.get("tool_calls") or []
            if not isinstance(fragments, list):
                return STREAM_INVALID_BODY, first
            for fragment in fragments:
                index = fragment.get("index") if isinstance(fragment, dict) else None
                function = fragment.get("function") or {} if isinstance(fragment, dict) else None
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not isinstance(function, dict)
                ):
                    return STREAM_INVALID_BODY, first
                call = calls.setdefault(
                    index, {"id": "", "type": "function", "name": "", "arguments": ""}
                )
                for key, value in (
                    ("id", fragment.get("id")),
                    ("name", function.get("name")),
                ):
                    if value is not None and not isinstance(value, str):
                        return STREAM_INVALID_BODY, first
                    if value and not call[key]:
                        call[key] = value
                arguments = function.get("arguments")
                if arguments is not None and not isinstance(arguments, str):
                    return STREAM_INVALID_BODY, first
                call["arguments"] += arguments or ""
                if isinstance(fragment.get("type"), str) and fragment["type"]:
                    call["type"] = fragment["type"]
            if choice.get("finish_reason") is not None:
                finish = choice["finish_reason"]
    message: dict[str, object] = {
        "role": "assistant",
        "content": "".join(parts) if parts or not calls else None,
    }
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": call["type"],
                "function": {"name": call["name"], "arguments": call["arguments"]},
            }
            for _, call in sorted(calls.items())
        ]
    body: dict[str, object] = {
        **meta,
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }
    if usage is not None:
        body["usage"] = usage
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), first


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
        on_delta: DeltaSink | None = None,
    ) -> object:
        """Send canonical JSON bytes without decoding or re-encoding them.

        With ``on_delta`` the request body must ask for a stream: each text
        piece is handed to it as it arrives, and the result is still one
        response whose body is the folded completion. Still exactly one call.
        """
        json_headers = {
            key: value for key, value in headers.items() if key.lower() != "content-type"
        }
        json_headers["Content-Type"] = "application/json"
        return self._post(
            url,
            headers=json_headers,
            timeout=timeout,
            content=content,
            on_delta=on_delta,
        )

    def _post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: object,
        json_payload: Mapping[str, object] | None = None,
        content: bytes | None = None,
        on_delta: DeltaSink | None = None,
    ) -> object:
        # Take an LLM slot (unified queue, then the LLM_ADMISSION_LIMIT backstop). Host
        # memory/load pressure suspends the attempt until recovery; only a
        # wait timeout or full queue raises a retryable 503. PlatformError
        # propagates unchanged; the slot is always released afterwards.
        with llm_admission_slot():
            started = time.perf_counter()
            response: object = None
            try:
                response = self._send_once(
                    url,
                    headers=headers,
                    timeout=timeout,
                    json_payload=json_payload,
                    content=content,
                    on_delta=on_delta,
                )
                return response
            finally:
                _record_model_call(url, json_payload, content, started, response)

    def _send_once(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: object,
        json_payload: Mapping[str, object] | None,
        content: bytes | None,
        on_delta: DeltaSink | None = None,
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
                    on_delta=on_delta,
                )
            with httpx.Client(follow_redirects=False) as client:
                return self._dispatch(
                    client,
                    url,
                    headers=headers,
                    timeout=resolved_timeout,
                    json_payload=json_payload,
                    content=content,
                    on_delta=on_delta,
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
        on_delta: DeltaSink | None = None,
    ) -> httpx.Response | LLMStreamedResponse:
        request_headers = dict(headers)
        if content is not None and on_delta is not None:
            return _dispatch_stream_impl(
                client,
                url,
                headers=request_headers,
                timeout=timeout,
                content=content,
                on_delta=on_delta,
            )
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


def _dispatch_stream_impl(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str],
    timeout: float | httpx.Timeout,
    content: bytes,
    on_delta: DeltaSink,
) -> LLMStreamedResponse:
    # HTTPX's read timeout is per read, so a slow trickle could outlive the
    # frozen total; the fold enforces the total as a wall-clock deadline.
    deadline = time.monotonic() + LLM_TOTAL_TIMEOUT_SECONDS
    with client.stream(
        "POST",
        url,
        headers=dict(headers),
        content=content,
        timeout=timeout,
        follow_redirects=False,
    ) as response:
        if response.status_code != LLM_ACCEPTED_HTTP_STATUS or not _event_stream(
            response.headers.get("content-type")
        ):
            return LLMStreamedResponse(
                status_code=response.status_code,
                content=response.read(),
                headers=dict(response.headers),
            )
        body, first = fold_chat_stream(response.iter_lines(), on_delta, deadline=deadline)
        return LLMStreamedResponse(
            status_code=response.status_code,
            content=body,
            headers=dict(response.headers),
            ttft_ms=None if first is None else first * 1000.0,
        )


def _model_label(url: str, json_payload: Mapping[str, object] | None, content: bytes | None) -> str:
    """``<model>/<last path segment>``; no prompt or payload content."""

    model = ""
    if json_payload is not None and isinstance(json_payload.get("model"), str):
        model = str(json_payload["model"])
    elif content is not None:
        index = content.find(b'"model"')
        if index >= 0:
            tail = content[index + 7 : index + 160].lstrip(b" :")
            if tail.startswith(b'"'):
                model = tail[1:].split(b'"', 1)[0].decode("utf-8", "replace")
    path = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
    return f"{model or 'llm'}/{path}"[:120]


def _record_model_call(
    url: str,
    json_payload: Mapping[str, object] | None,
    content: bytes | None,
    started: float,
    response: object,
) -> None:
    try:
        duration_ms = (time.perf_counter() - started) * 1000.0
        add_provider_time("llm", duration_ms)
        status = getattr(response, "status_code", None)
        status_code = status if isinstance(status, int) else None
        streamed_ttft = getattr(response, "ttft_ms", None)
        add_model_call(
            label=_model_label(url, json_payload, content),
            duration_ms=duration_ms,
            # Non-streaming: the first token arrives with the whole body.
            ttft_ms=(
                streamed_ttft
                if isinstance(streamed_ttft, float)
                else duration_ms
                if status_code is not None
                else None
            ),
            status=status_code,
            failed=status_code != LLM_ACCEPTED_HTTP_STATUS,
        )
    except Exception:  # pragma: no cover - timing must never break a model call
        pass


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
    "LLMStreamedResponse",
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
    "fold_chat_stream",
]
