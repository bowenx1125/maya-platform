"""No-network classification checks for the production embedding transport."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.modules.knowledge.providers import (
    EmbeddingAcceptanceUnknown,
    EmbeddingTransportNotSent,
    HttpxEmbeddingTransport,
)


def _workspace_endpoint() -> str:
    return (
        "https://"
        + "workspace123.cn-beijing.maas."
        + "aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
    )


@pytest.mark.parametrize(
    ("error_factory", "expected"),
    (
        (
            lambda request: httpx.ConnectError("local injected failure", request=request),
            EmbeddingTransportNotSent,
        ),
        (
            lambda request: httpx.ConnectTimeout("local injected failure", request=request),
            EmbeddingTransportNotSent,
        ),
        (
            lambda request: httpx.ReadTimeout("local injected failure", request=request),
            EmbeddingAcceptanceUnknown,
        ),
        (
            lambda request: httpx.RemoteProtocolError("local injected failure", request=request),
            EmbeddingAcceptanceUnknown,
        ),
    ),
)
def test_http_transport_classifies_acceptance_without_retry(
    error_factory: Callable[[httpx.Request], httpx.HTTPError],
    expected: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_factory(request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        transport = HttpxEmbeddingTransport(client)
        with pytest.raises(expected):
            transport.post(
                _workspace_endpoint(),
                headers={"X-Test-Marker": "redacted-fixture"},
                json={"model": "text-embedding-v4", "input": {"texts": ["safe"]}},
                timeout=1.0,
            )


def test_http_transport_returns_response_without_following_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-test-marker"] == "redacted-fixture"
        return httpx.Response(307, headers={"Location": "https://example.invalid"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = HttpxEmbeddingTransport(client).post(
            _workspace_endpoint(),
            headers={"X-Test-Marker": "redacted-fixture"},
            json={"model": "text-embedding-v4", "input": {"texts": ["safe"]}},
            timeout=1.0,
        )
    assert isinstance(response, httpx.Response)
    assert response.status_code == 307
