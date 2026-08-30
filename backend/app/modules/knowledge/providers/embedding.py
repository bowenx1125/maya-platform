"""Closed embedding response validation and provider-neutral vector values."""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .packing import EmbeddingBatchV1
from .snapshot_build import FIXED_EMBEDDING_DIMENSION, FIXED_EMBEDDING_MODEL


class EmbeddingValidationError(ValueError):
    """An embedding response failed the closed supplier response contract."""

    def __init__(self, message: str, *, code: str = "embedding_response_invalid") -> None:
        super().__init__(message)
        self.code = code


class EmbeddingResponseError(EmbeddingValidationError):
    """A response is missing or not a JSON object."""


class EmbeddingModelError(EmbeddingValidationError):
    """The fixed model key was not returned exactly."""


class EmbeddingShapeError(EmbeddingValidationError):
    """The response count/order or vector shape is invalid."""


class EmbeddingDimensionError(EmbeddingShapeError):
    """A vector does not have the fixed dimension."""


class EmbeddingProvider(Protocol):
    """Provider port consumed by the reservation runner."""

    model_key: str
    dimension: int

    def embed_batch(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        """Embed one preflighted batch."""


@dataclass(frozen=True, slots=True)
class ValidatedEmbeddingBatchV1:
    """Vectors validated against one exact planned batch and build hash."""

    build_id: str
    build_manifest_hash: str
    batch_index: int
    chunk_ids: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]
    model_key: str
    dimension: int

    def __post_init__(self) -> None:
        if not self.build_id or not self.build_manifest_hash or self.batch_index < 0:
            raise EmbeddingValidationError("validated embedding identity is invalid")
        if len(self.chunk_ids) != len(self.vectors):
            raise EmbeddingShapeError("validated vector count does not match chunk IDs")
        if not self.model_key or self.dimension < 1:
            raise EmbeddingValidationError("validated embedding metadata is invalid")
        for vector in self.vectors:
            # Reuse the same strict checks used for provider JSON.  Calling
            # the helper here is safe because it returns an immutable tuple.
            _vector(vector, dimension=self.dimension)

    @property
    def count(self) -> int:
        return len(self.vectors)

    @property
    def result_count(self) -> int:
        return self.count

    @property
    def embeddings(self) -> tuple[tuple[float, ...], ...]:
        return self.vectors

    @property
    def vector_blobs(self) -> tuple[bytes, ...]:
        return tuple(struct.pack(f"<{self.dimension}f", *vector) for vector in self.vectors)

    @property
    def build_hash(self) -> str:
        return self.build_manifest_hash


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    json_method = getattr(value, "json", None)
    if callable(json_method):
        try:
            parsed = json_method()
        except Exception as exc:
            raise EmbeddingResponseError(f"{field} is not valid JSON") from exc
        if isinstance(parsed, Mapping):
            return parsed
    raise EmbeddingResponseError(f"{field} must be a JSON object")


def _normalise_response(
    response: object,
    *,
    expected_model: str,
) -> Mapping[str, object]:
    payload = _mapping(response, field="embedding response")
    # OpenAI-compatible responses are already in the closed shape.  DashScope
    # uses ``output.embeddings`` in some API versions; normalize only that
    # documented envelope and keep model/count validation identical.
    output = payload.get("output")
    if isinstance(output, Mapping) and "data" not in payload:
        raw_embeddings = output.get("embeddings")
        if isinstance(raw_embeddings, list):
            model = payload.get("model", output.get("model", expected_model))
            normalized: dict[str, object] = {
                "model": model,
                "data": raw_embeddings,
            }
            if "build_manifest_hash" in payload:
                normalized["build_manifest_hash"] = payload["build_manifest_hash"]
            return normalized
    return payload


def _index(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EmbeddingShapeError("embedding index is invalid", code="embedding_index_invalid")
    return value


def _vector(value: object, *, dimension: int) -> tuple[float, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EmbeddingShapeError(
            "embedding vector is not an array", code="embedding_vector_invalid"
        )
    if len(value) != dimension:
        raise EmbeddingDimensionError(
            f"embedding dimension must be {dimension}", code="embedding_dimension_invalid"
        )
    output: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise EmbeddingShapeError(
                "embedding vector contains a non-numeric value",
                code="embedding_vector_invalid",
            )
        converted = float(item)
        if not math.isfinite(converted):
            raise EmbeddingShapeError(
                "embedding vector contains a non-finite value",
                code="embedding_vector_nonfinite",
            )
        output.append(converted)
    return tuple(output)


def validate_embedding_response(
    response: object,
    *,
    expected_count: int,
    expected_model: str = FIXED_EMBEDDING_MODEL,
    expected_dimension: int = FIXED_EMBEDDING_DIMENSION,
    expected_build_manifest_hash: str | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Validate exact model/count/order/dimension/finite values.

    ``expected_build_manifest_hash`` is optional because a real supplier need
    not echo Maya's local hash.  When a response does carry the field (as the
    Mock adapter does), it must match rather than being silently ignored.
    """

    if expected_count < 0 or expected_dimension < 1 or not expected_model:
        raise EmbeddingValidationError("embedding validation expectation is invalid")
    payload = _normalise_response(response, expected_model=expected_model)
    model = payload.get("model")
    if model != expected_model:
        raise EmbeddingModelError(
            "embedding model does not match the fixed model", code="embedding_model_mismatch"
        )
    if expected_build_manifest_hash is not None:
        returned_hash = payload.get("build_manifest_hash")
        if returned_hash is not None and returned_hash != expected_build_manifest_hash:
            raise EmbeddingResponseError(
                "embedding response belongs to a different SnapshotBuild",
                code="embedding_build_mismatch",
            )
    raw_data = payload.get("data")
    if not isinstance(raw_data, list) or len(raw_data) != expected_count:
        raise EmbeddingShapeError(
            "embedding response count does not match the request",
            code="embedding_count_mismatch",
        )
    vectors: list[tuple[float, ...]] = []
    for expected_index, raw_item in enumerate(raw_data):
        item = _mapping(raw_item, field="embedding item")
        raw_index = item.get("index", item.get("text_index"))
        if _index(raw_index) != expected_index:
            raise EmbeddingShapeError(
                "embedding response order does not match the request",
                code="embedding_order_mismatch",
            )
        vectors.append(_vector(item.get("embedding"), dimension=expected_dimension))
    return tuple(vectors)


def validate_embedding_batch_response(
    response: object,
    batch: EmbeddingBatchV1,
    *,
    expected_model: str | None = None,
    expected_dimension: int | None = None,
) -> ValidatedEmbeddingBatchV1:
    """Validate a provider result against one exact planned batch."""

    model = expected_model or batch.model_key
    dimension = expected_dimension or batch.dimension
    vectors = validate_embedding_response(
        response,
        expected_count=len(batch.items),
        expected_model=model,
        expected_dimension=dimension,
        expected_build_manifest_hash=batch.build_manifest_hash,
    )
    payload = _normalise_response(response, expected_model=model)
    response_build_hash = payload.get("build_manifest_hash")
    if response_build_hash is not None and response_build_hash != batch.build_manifest_hash:
        raise EmbeddingResponseError(
            "embedding response belongs to a different SnapshotBuild",
            code="embedding_build_mismatch",
        )
    return ValidatedEmbeddingBatchV1(
        build_id=batch.build_id,
        build_manifest_hash=batch.build_manifest_hash,
        batch_index=batch.batch_index,
        chunk_ids=batch.chunk_ids,
        vectors=vectors,
        model_key=model,
        dimension=dimension,
    )


def validate_embedding_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimension: int = FIXED_EMBEDDING_DIMENSION,
) -> tuple[tuple[float, ...], ...]:
    """Validate local vectors when a persistence adapter has already parsed JSON."""

    if len(vectors) != expected_count:
        raise EmbeddingShapeError("embedding response count does not match the request")
    return tuple(_vector(vector, dimension=expected_dimension) for vector in vectors)


# Compatibility aliases for the adapter boundary.
validate_embedding_result = validate_embedding_batch_response
EmbeddingBatchResultV1 = ValidatedEmbeddingBatchV1


__all__ = [
    "EmbeddingBatchResultV1",
    "EmbeddingDimensionError",
    "EmbeddingModelError",
    "EmbeddingProvider",
    "EmbeddingResponseError",
    "EmbeddingShapeError",
    "EmbeddingValidationError",
    "ValidatedEmbeddingBatchV1",
    "validate_embedding_batch_response",
    "validate_embedding_response",
    "validate_embedding_result",
    "validate_embedding_vectors",
]
