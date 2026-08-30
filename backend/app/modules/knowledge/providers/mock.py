"""Deterministic local embedding provider for W4-EMBED tests and Demo code."""

from __future__ import annotations

import struct
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.modules.knowledge.markdown import mock_embedding

from .adapters import EmbeddingAcceptanceUnknown, EmbeddingTransportNotSent
from .embedding import ValidatedEmbeddingBatchV1
from .packing import EmbeddingBatchV1
from .snapshot_build import FIXED_EMBEDDING_DIMENSION, FIXED_EMBEDDING_MODEL


@dataclass(frozen=True, slots=True)
class MockEmbeddingCall:
    """Safe call trace; source text, keys and provider responses are excluded."""

    build_manifest_hash: str
    batch_index: int
    item_count: int


@dataclass
class MockEmbeddingProvider:
    """Byte-stable 256-dimensional vectors with explicit test failures."""

    model_key: str = FIXED_EMBEDDING_MODEL
    dimension: int = FIXED_EMBEDDING_DIMENSION
    key: str = "mock-sha256-v1"
    failures: Iterable[str] = ()
    calls: int = field(default=0, init=False)
    call_log: list[MockEmbeddingCall] = field(default_factory=list, init=False)
    _failures: deque[str] = field(default_factory=deque, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.dimension != FIXED_EMBEDDING_DIMENSION:
            raise ValueError("W4-EMBED Mock vectors must be dimension 256")
        self._failures.extend(str(item) for item in self.failures)

    @property
    def target_model_key(self) -> str:
        return self.model_key

    @property
    def call_count(self) -> int:
        return self.calls

    @property
    def prompts(self) -> tuple[MockEmbeddingCall, ...]:
        return tuple(self.call_log)

    def fail_next(self, kind: str) -> None:
        self._failures.append(kind)

    def embed_batch(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        # Importing and using the same pre-send checks as the real adapter keeps
        # Mock acceptance honest without involving export confirmation.
        from .adapters import _validate_batch_before_send

        _validate_batch_before_send(batch)
        self.calls += 1
        self.call_log.append(
            MockEmbeddingCall(batch.build_manifest_hash, batch.batch_index, len(batch.items))
        )
        failure = self._failures.popleft() if self._failures else None
        if failure in {"not_sent", "transport_not_sent"}:
            raise EmbeddingTransportNotSent()
        if failure in {"acceptance_unknown", "timeout", "transport_unknown"}:
            raise EmbeddingAcceptanceUnknown()
        vectors = [list(struct.unpack("<256f", mock_embedding(item.text))) for item in batch.items]
        data: list[dict[str, object]] = [
            {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
        ]
        payload: dict[str, object] = {
            "model": self.model_key,
            "build_manifest_hash": batch.build_manifest_hash,
            "data": data,
        }
        if failure in {"partial", "short"}:
            payload["data"] = data[:-1]
        elif failure in {"malformed", "shape"}:
            payload["data"] = [{"index": 0, "embedding": "not-a-vector"}]
        elif failure in {"wrong_dimension", "dimension"}:
            payload["data"] = [
                {"index": index, "embedding": vector[:-1]} for index, vector in enumerate(vectors)
            ]
        elif failure in {"nonfinite", "nan"}:
            if vectors:
                vectors[0][0] = float("nan")
            payload["data"] = [
                {"index": index, "embedding": vector} for index, vector in enumerate(vectors)
            ]
        elif failure in {"wrong_model", "model"}:
            payload["model"] = "different-embedding-model"
        elif failure in {"wrong_build", "build_mismatch"}:
            payload["build_manifest_hash"] = "f" * 64
        elif failure is not None:
            raise RuntimeError("unknown mock embedding failure injection")
        # Reuse the same strict response parser as a real adapter.  This means
        # Mock cannot accidentally publish partial or malformed vectors.
        from .embedding import validate_embedding_batch_response

        return validate_embedding_batch_response(payload, batch, expected_model=self.model_key)

    def embed(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        return self.embed_batch(batch)


__all__ = ["MockEmbeddingCall", "MockEmbeddingProvider"]
