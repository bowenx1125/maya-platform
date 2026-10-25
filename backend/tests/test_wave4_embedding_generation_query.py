"""Fake-transport product test for real query retrieval and Evidence receipts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from app.modules.knowledge.providers.adapters import (
    EmbeddingTransportResponse,
)
from app.modules.knowledge.providers.snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
)
from app.providers.control import ProviderPolicySnapshotV1


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _QueryTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> EmbeddingTransportResponse:
        del headers, timeout
        payload = dict(json)
        self.calls.append(payload)
        nested = payload.get("input")
        assert isinstance(nested, dict)
        texts = nested.get("texts")
        assert isinstance(texts, list)
        vector = [1.0] + [0.0] * (REAL_EMBEDDING_DIMENSION - 1)
        return EmbeddingTransportResponse(
            200,
            {
                "model": REAL_EMBEDDING_MODEL,
                "data": [
                    {"index": index, "embedding": vector} for index, _text in enumerate(texts)
                ],
            },
        )


def _policy(endpoint: str) -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        endpoint=endpoint,
        privacy_notice_retrieved_at="2026-08-31T00:00:00Z",
        privacy_notice_sha256=_digest("privacy"),
        service_terms_retrieved_at="2026-08-31T00:00:00Z",
        service_terms_sha256=_digest("terms"),
        faq_retrieved_at="2026-08-31T00:00:00Z",
        faq_sha256=_digest("faq"),
        no_training_basis="payg-api-terms-2026-08-31",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )
