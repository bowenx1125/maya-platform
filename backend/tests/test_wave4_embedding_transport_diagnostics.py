"""Sanitized transport diagnostics without a network request."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

import httpx
import pytest
from app.modules.knowledge.providers import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingAcceptanceUnknown,
    EmbeddingHTTPRejected,
    EmbeddingTransportNotSent,
    EmbeddingTransportResponse,
    HttpxEmbeddingTransport,
    plan_embedding_batches,
    prepare_snapshot_build,
)


def _batch():
    build = prepare_snapshot_build(
        agent_version_id="agent-version",
        knowledge_snapshot_id="snapshot",
        draft_revision=1,
        persona_spec_hash="persona",
        documents=[
            {
                "document_id": "document",
                "source_filename": "lesson.md",
                "text": "A safe embedding fixture.",
            }
        ],
        embedding_model_key=REAL_EMBEDDING_MODEL,
        embedding_dimension=REAL_EMBEDDING_DIMENSION,
        embedding_provider=REAL_EMBEDDING_PROVIDER,
        embedding_region=REAL_EMBEDDING_REGION,
        embedding_policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )
    return plan_embedding_batches(build).batches[0]


def _endpoint() -> str:
    return DashScopeEmbeddingConfig(workspace_id="workspace123").resolved_endpoint


@pytest.mark.parametrize(
    ("factory", "expected", "exception_class", "phase"),
    (
        (
            lambda request: httpx.ConnectError("secret connect sentinel", request=request),
            EmbeddingTransportNotSent,
            "ConnectError",
            "connect",
        ),
        (
            lambda request: httpx.ReadTimeout("secret read sentinel", request=request),
            EmbeddingAcceptanceUnknown,
            "ReadTimeout",
            "read",
        ),
        (
            lambda request: httpx.RemoteProtocolError("secret protocol sentinel", request=request),
            EmbeddingAcceptanceUnknown,
            "RemoteProtocolError",
            "unknown",
        ),
    ),
)
def test_transport_failure_diagnostics_are_allowlisted_and_single_attempt(
    factory: Callable[[httpx.Request], httpx.HTTPError],
    expected: type[Exception],
    exception_class: str,
    phase: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "provider-secret-sentinel"
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.headers["x-test-marker"] == secret
        raise factory(request)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        transport = HttpxEmbeddingTransport(client)
        with caplog.at_level(logging.WARNING, logger="app.modules.knowledge.providers.adapters"):
            with pytest.raises(expected) as raised:
                transport.post(
                    _endpoint(),
                    headers={"X-Test-Marker": secret},
                    json={"input": {"texts": [secret]}},
                    timeout=1.0,
                )

    diagnostics = raised.value.diagnostics
    assert diagnostics is not None
    assert diagnostics["exception_class"] == exception_class
    assert diagnostics["phase"] == phase
    assert diagnostics["elapsed_ms"] >= 0
    assert diagnostics["timeout_seconds"] == 1.0
    assert diagnostics["client_mode"] == "provided"
    assert diagnostics["trust_env"] is False
    assert diagnostics["http_status"] is None
    assert calls == 1
    assert secret not in caplog.text
    assert "sentinel" not in caplog.text
    assert _endpoint() not in caplog.text
    assert f'"exception_class":"{exception_class}"' in caplog.text
    assert '"timeout_seconds":1.0' in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_adapter_adds_diagnostics_to_direct_injected_transport_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "adapter-secret-sentinel"
    calls = 0

    class RaisingTransport:
        def post(
            self,
            _url: str,
            *,
            headers: Mapping[str, str],
            json: Mapping[str, object],
            timeout: float,
        ) -> object:
            nonlocal calls
            calls += 1
            del headers, json, timeout
            raise httpx.ReadTimeout(secret)

    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"),
        RaisingTransport(),  # type: ignore[arg-type]
        timeout_seconds=1.0,
    )
    with caplog.at_level(logging.WARNING, logger="app.modules.knowledge.providers.adapters"):
        with pytest.raises(EmbeddingAcceptanceUnknown) as raised:
            adapter.embed_batch(_batch())
    assert raised.value.diagnostics is not None
    assert raised.value.diagnostics["exception_class"] == "ReadTimeout"
    assert raised.value.diagnostics["phase"] == "read"
    assert raised.value.diagnostics["client_mode"] == "injected"
    assert raised.value.diagnostics["trust_env"] is None
    assert calls == 1
    assert secret not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_non_2xx_diagnostics_include_status_without_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "response-body-secret-sentinel"

    class ResponseTransport:
        def post(
            self,
            _url: str,
            *,
            headers: Mapping[str, str],
            json: Mapping[str, object],
            timeout: float,
        ) -> object:
            del headers, json, timeout
            return EmbeddingTransportResponse(503, {"error": secret})

    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"),
        ResponseTransport(),  # type: ignore[arg-type]
        timeout_seconds=1.0,
    )
    with caplog.at_level(logging.WARNING, logger="app.modules.knowledge.providers.adapters"):
        with pytest.raises(EmbeddingHTTPRejected) as raised:
            adapter.embed_batch(_batch())
    assert raised.value.status_code == 503
    assert raised.value.diagnostics is not None
    assert raised.value.diagnostics["exception_class"] == "HTTPStatus"
    assert raised.value.diagnostics["phase"] == "response"
    assert raised.value.diagnostics["http_status"] == 503
    assert secret not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_managed_transport_reports_explicit_trust_env_mode() -> None:
    transport = HttpxEmbeddingTransport(trust_env=False)
    assert transport.client_mode == "managed"
    assert transport.trust_env is False
