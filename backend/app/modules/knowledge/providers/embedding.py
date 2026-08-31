"""Closed embedding response validation and provider-neutral vector values."""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from .packing import EmbeddingBatchV1
from .snapshot_build import (
    FIXED_EMBEDDING_DIMENSION,
    MOCK_EMBEDDING_DIMENSION,
    MOCK_EMBEDDING_MODEL,
    MOCK_EMBEDDING_POLICY_VERSION,
    MOCK_EMBEDDING_PROVIDER,
    MOCK_EMBEDDING_REGION,
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
    embedding_identity_for,
)


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


EmbeddingResponseDialect = Literal["generic", "dashscope_native"]

# A provider may explicitly return ``null`` for a model, which is different
# from omitting the field.  Keep an identity sentinel while normalising the
# native envelope so every explicitly declared value is checked.
_MISSING_MODEL = object()


class EmbeddingProvider(Protocol):
    """Provider port consumed by the reservation runner."""

    model_key: str
    dimension: int
    provider: str
    region: str
    policy_version: str

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
    embedding_provider: str = ""
    embedding_region: str = ""
    policy_version: str = ""

    def __post_init__(self) -> None:
        if not self.build_id or not self.build_manifest_hash or self.batch_index < 0:
            raise EmbeddingValidationError("validated embedding identity is invalid")
        if len(self.chunk_ids) != len(self.vectors):
            raise EmbeddingShapeError("validated vector count does not match chunk IDs")
        if (
            not isinstance(self.model_key, str)
            or not self.model_key
            or isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
            or self.dimension < 1
        ):
            raise EmbeddingValidationError("validated embedding metadata is invalid")
        identity = embedding_identity_for(
            self.model_key,
            self.dimension,
            provider=self.embedding_provider or None,
            region=self.embedding_region or None,
            policy_version=self.policy_version or None,
        )
        if self.model_key in {MOCK_EMBEDDING_MODEL, REAL_EMBEDDING_MODEL} and identity is None:
            raise EmbeddingValidationError(
                "validated embedding identity is not a closed resource",
                code="embedding_identity_mismatch",
            )
        if identity is not None:
            object.__setattr__(self, "embedding_provider", identity.provider)
            object.__setattr__(self, "embedding_region", identity.region)
            object.__setattr__(self, "policy_version", identity.policy_version)
        # Reuse the same strict checks used for provider JSON and freeze the
        # sanitized numeric tuples at the stage boundary.
        object.__setattr__(
            self,
            "vectors",
            tuple(_vector(vector, dimension=self.dimension) for vector in self.vectors),
        )

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
    response_dialect: EmbeddingResponseDialect,
) -> tuple[Mapping[str, object], bool, object, object]:
    payload = _mapping(response, field="embedding response")
    if response_dialect not in {"generic", "dashscope_native"}:
        raise EmbeddingResponseError(
            "embedding response dialect is invalid", code="embedding_response_invalid"
        )
    # OpenAI-compatible responses are already in the closed ``data`` shape.
    # Only the fixed DashScope adapter may normalize the supplier's native
    # ``output.embeddings`` envelope.  Keeping this opt-in prevents an
    # arbitrary missing-model response from crossing the generic boundary.
    if response_dialect == "dashscope_native":
        output = payload.get("output")
        if isinstance(output, Mapping) and "data" not in payload:
            raw_embeddings = output.get("embeddings")
            if isinstance(raw_embeddings, list):
                # The native successful response may omit model.  If it is
                # present, it is still compared with the request model below.
                top_model = payload.get("model", _MISSING_MODEL)
                nested_model = output.get("model", _MISSING_MODEL)
                if top_model is not _MISSING_MODEL:
                    model = top_model
                elif nested_model is not _MISSING_MODEL:
                    model = nested_model
                else:
                    model = None
                normalized: dict[str, object] = {
                    "model": model,
                    "data": raw_embeddings,
                }
                if "build_manifest_hash" in payload:
                    normalized["build_manifest_hash"] = payload["build_manifest_hash"]
                return normalized, True, top_model, nested_model
    return payload, False, payload.get("model", _MISSING_MODEL), _MISSING_MODEL


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
    expected_model: str = MOCK_EMBEDDING_MODEL,
    expected_dimension: int | None = None,
    expected_provider: str | None = None,
    expected_region: str | None = None,
    expected_policy_version: str | None = None,
    expected_build_manifest_hash: str | None = None,
    response_dialect: EmbeddingResponseDialect = "generic",
) -> tuple[tuple[float, ...], ...]:
    """Validate exact model/count/order/dimension/finite values.

    ``expected_build_manifest_hash`` is optional because a real supplier need
    not echo Maya's local hash.  When a response does carry the field (as the
    Mock adapter does), it must match rather than being silently ignored.
    """

    resolved_dimension = expected_dimension
    if resolved_dimension is None:
        # The legacy generic/Mock call shape remains 256 unless the caller
        # explicitly asks for the fixed real model.  Real callers should also
        # pass the dimension carried by their frozen request.
        resolved_dimension = (
            REAL_EMBEDDING_DIMENSION
            if expected_model == REAL_EMBEDDING_MODEL
            else MOCK_EMBEDDING_DIMENSION
        )
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count < 0
        or isinstance(resolved_dimension, bool)
        or not isinstance(resolved_dimension, int)
        or resolved_dimension < 1
        or not isinstance(expected_model, str)
        or not expected_model
    ):
        raise EmbeddingValidationError("embedding validation expectation is invalid")
    identity = embedding_identity_for(
        expected_model,
        resolved_dimension,
        provider=expected_provider,
        region=expected_region,
        policy_version=expected_policy_version,
    )
    if expected_model in {MOCK_EMBEDDING_MODEL, REAL_EMBEDDING_MODEL} and identity is None:
        raise EmbeddingValidationError(
            "embedding validation identity is not a closed resource",
            code="embedding_identity_mismatch",
        )
    payload, native_envelope, top_model, nested_model = _normalise_response(
        response,
        expected_model=expected_model,
        response_dialect=response_dialect,
    )
    if native_envelope:
        # DashScope's native envelope has appeared with either model field,
        # or with both.  Missing fields are allowed by the official response
        # shape, but every field that is present must match exactly.  Checking
        # both independently prevents a correct top-level value from masking
        # a conflicting nested value.
        if (
            top_model is not _MISSING_MODEL
            and nested_model is not _MISSING_MODEL
            and top_model != nested_model
        ) or any(
            model is not _MISSING_MODEL and model != expected_model
            for model in (top_model, nested_model)
        ):
            raise EmbeddingModelError(
                "embedding model does not match the fixed model",
                code="embedding_model_mismatch",
            )
    elif top_model is _MISSING_MODEL or top_model != expected_model:
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
        raw_index = (
            item.get("text_index") if native_envelope else item.get("index", item.get("text_index"))
        )
        if _index(raw_index) != expected_index:
            raise EmbeddingShapeError(
                "embedding response order does not match the request",
                code="embedding_order_mismatch",
            )
        vectors.append(_vector(item.get("embedding"), dimension=resolved_dimension))
    return tuple(vectors)


def validate_embedding_batch_response(
    response: object,
    batch: EmbeddingBatchV1,
    *,
    expected_model: str | None = None,
    expected_dimension: int | None = None,
    expected_provider: str | None = None,
    expected_region: str | None = None,
    expected_policy_version: str | None = None,
    response_dialect: EmbeddingResponseDialect = "generic",
) -> ValidatedEmbeddingBatchV1:
    """Validate a provider result against one exact planned batch."""

    model = expected_model or batch.model_key
    dimension = batch.dimension if expected_dimension is None else expected_dimension
    provider = batch.embedding_provider if expected_provider is None else expected_provider
    region = batch.embedding_region if expected_region is None else expected_region
    policy_version = (
        batch.policy_version if expected_policy_version is None else expected_policy_version
    )
    vectors = validate_embedding_response(
        response,
        expected_count=len(batch.items),
        expected_model=model,
        expected_dimension=dimension,
        expected_provider=provider or None,
        expected_region=region or None,
        expected_policy_version=policy_version or None,
        expected_build_manifest_hash=batch.build_manifest_hash,
        response_dialect=response_dialect,
    )
    payload, _native_envelope, _top_model, _nested_model = _normalise_response(
        response,
        expected_model=model,
        response_dialect=response_dialect,
    )
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
        embedding_provider=provider,
        embedding_region=region,
        policy_version=policy_version,
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


def validate_real_embedding_response(
    response: object,
    *,
    expected_count: int,
    expected_build_manifest_hash: str | None = None,
    response_dialect: EmbeddingResponseDialect = "generic",
) -> tuple[tuple[float, ...], ...]:
    """Validate the fixed real text-embedding-v4/1024 response shape."""

    return validate_embedding_response(
        response,
        expected_count=expected_count,
        expected_model=REAL_EMBEDDING_MODEL,
        expected_dimension=REAL_EMBEDDING_DIMENSION,
        expected_provider=REAL_EMBEDDING_PROVIDER,
        expected_region=REAL_EMBEDDING_REGION,
        expected_policy_version=REAL_EMBEDDING_POLICY_VERSION,
        expected_build_manifest_hash=expected_build_manifest_hash,
        response_dialect=response_dialect,
    )


def validate_mock_embedding_response(
    response: object,
    *,
    expected_count: int,
    expected_build_manifest_hash: str | None = None,
) -> tuple[tuple[float, ...], ...]:
    """Validate the existing Mock ``mock-sha256-v1``/256 response shape."""

    return validate_embedding_response(
        response,
        expected_count=expected_count,
        expected_model=MOCK_EMBEDDING_MODEL,
        expected_dimension=MOCK_EMBEDDING_DIMENSION,
        expected_provider=MOCK_EMBEDDING_PROVIDER,
        expected_region=MOCK_EMBEDDING_REGION,
        expected_policy_version=MOCK_EMBEDDING_POLICY_VERSION,
        expected_build_manifest_hash=expected_build_manifest_hash,
    )


__all__ = [
    "EmbeddingBatchResultV1",
    "EmbeddingDimensionError",
    "EmbeddingModelError",
    "EmbeddingProvider",
    "EmbeddingResponseDialect",
    "EmbeddingResponseError",
    "EmbeddingShapeError",
    "EmbeddingValidationError",
    "ValidatedEmbeddingBatchV1",
    "validate_embedding_batch_response",
    "validate_embedding_response",
    "validate_embedding_result",
    "validate_embedding_vectors",
    "validate_mock_embedding_response",
    "validate_real_embedding_response",
]
