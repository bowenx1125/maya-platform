"""Exact-byte checks for the no-network LLM HTTP transport."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.providers.llm_transport import (
    LLM_CONNECT_TIMEOUT_SECONDS,
    LLM_TOTAL_TIMEOUT_SECONDS,
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMTransportNotSent,
)


def _endpoint() -> str:
    return "https://example.invalid/v1/chat/completions"


def test_post_bytes_sends_exact_body_once_with_frozen_transport_options() -> None:
    body = '{"model":"qwen","messages":[{"content":"你好 ☯","role":"user"}]}'.encode()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    timeout = HttpxLLMTransport.timeout()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = HttpxLLMTransport(client).post_bytes(
            _endpoint(),
            headers={"Authorization": "Bearer fixture", "content-type": "text/plain"},
            content=body,
            timeout=timeout,
        )

    assert isinstance(response, httpx.Response)
    assert response.status_code == 200
    assert len(seen) == 1
    request = seen[0]
    assert request.content == body
    assert request.headers["content-type"] == "application/json"
    assert request.headers["authorization"] == "Bearer fixture"
    assert request.extensions["timeout"] == {
        "connect": LLM_CONNECT_TIMEOUT_SECONDS,
        "read": LLM_TOTAL_TIMEOUT_SECONDS,
        "write": LLM_TOTAL_TIMEOUT_SECONDS,
        "pool": LLM_TOTAL_TIMEOUT_SECONDS,
    }


@pytest.mark.parametrize(
    ("error_factory", "expected"),
    (
        (
            lambda request: httpx.ConnectError("local injected failure", request=request),
            LLMTransportNotSent,
        ),
        (
            lambda request: httpx.ReadTimeout("local injected failure", request=request),
            LLMAcceptanceUnknown,
        ),
    ),
)
def test_post_bytes_preserves_transport_error_classification_without_retry(
    error_factory: Callable[[httpx.Request], httpx.HTTPError],
    expected: type[Exception],
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise error_factory(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(expected):
            HttpxLLMTransport(client).post_bytes(
                _endpoint(),
                headers={},
                content=b'{"ok":true}',
                timeout=HttpxLLMTransport.timeout(),
            )

    assert attempts == 1
