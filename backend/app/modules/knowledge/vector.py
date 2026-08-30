"""Standard-library deterministic vector adapter."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.modules.knowledge.markdown import (
    EMBEDDING_DIMENSION,
    EMBEDDING_KEY,
    mock_embedding,
)
from app.modules.knowledge.ports import VectorMatch

MOCK_EMBEDDING_POLICY_VERSION = "w4-mock-v1"
REAL_EMBEDDING_POLICY_VERSION = "w4-embed-v1"
REAL_EMBEDDING_PROVIDER = "dashscope"
REAL_EMBEDDING_MODEL = "text-embedding-v4"
REAL_EMBEDDING_REGION = "cn-beijing"
REAL_EMBEDDING_DIMENSION = 1024


@dataclass(frozen=True)
class EmbeddingIdentityV1:
    provider: str
    model_key: str
    region: str
    dimension: int
    policy_version: str

    def __post_init__(self) -> None:
        identity = (
            self.provider,
            self.model_key,
            self.region,
            self.dimension,
            self.policy_version,
        )
        if identity not in {
            ("mock", EMBEDDING_KEY, "local", EMBEDDING_DIMENSION, MOCK_EMBEDDING_POLICY_VERSION),
            (
                REAL_EMBEDDING_PROVIDER,
                REAL_EMBEDDING_MODEL,
                REAL_EMBEDDING_REGION,
                REAL_EMBEDDING_DIMENSION,
                REAL_EMBEDDING_POLICY_VERSION,
            ),
        }:
            raise ValueError("embedding identity is not part of the closed contract")


MOCK_EMBEDDING_IDENTITY = EmbeddingIdentityV1(
    provider="mock",
    model_key=EMBEDDING_KEY,
    region="local",
    dimension=EMBEDDING_DIMENSION,
    policy_version=MOCK_EMBEDDING_POLICY_VERSION,
)
REAL_EMBEDDING_IDENTITY = EmbeddingIdentityV1(
    provider=REAL_EMBEDDING_PROVIDER,
    model_key=REAL_EMBEDDING_MODEL,
    region=REAL_EMBEDDING_REGION,
    dimension=REAL_EMBEDDING_DIMENSION,
    policy_version=REAL_EMBEDDING_POLICY_VERSION,
)


@dataclass(frozen=True)
class QueryEmbeddingV1:
    identity: EmbeddingIdentityV1
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.values) != self.identity.dimension or any(
            not math.isfinite(value) for value in self.values
        ):
            raise ValueError("query embedding shape is invalid")

    @property
    def blob(self) -> bytes:
        return struct.pack(f"<{self.identity.dimension}f", *self.values)


def unpack_vector(blob: bytes, identity: EmbeddingIdentityV1) -> tuple[float, ...]:
    if len(blob) != identity.dimension * 4:
        raise ValueError("vector blob length does not match embedding identity")
    values = struct.unpack(f"<{identity.dimension}f", blob)
    if any(not math.isfinite(value) for value in values):
        raise ValueError("vector blob contains a non-finite value")
    return values


@dataclass(frozen=True)
class StoredVectorRow:
    chunk_id: str
    source_filename: str
    chunk_text: str
    blob: bytes
    dimension: int
    key: str
    document_order: int
    chunk_index: int


@dataclass(frozen=True)
class MockEmbeddingProvider:
    dimension: int = EMBEDDING_DIMENSION
    key: str = EMBEDDING_KEY

    def embed(self, text: str) -> bytes:
        return mock_embedding(text)


class MockVectorStore:
    """Search vectors belonging to one caller-authorized source scope."""

    def __init__(self, rows: Sequence[StoredVectorRow]) -> None:
        self.rows = tuple(rows)

    def search(self, query: str, *, top_k: int = 6) -> Iterable[VectorMatch]:
        query_values = unpack_vector(mock_embedding(query), MOCK_EMBEDDING_IDENTITY)
        return IdentityVectorStore(MOCK_EMBEDDING_IDENTITY, self.rows).search_values(
            QueryEmbeddingV1(MOCK_EMBEDDING_IDENTITY, query_values),
            top_k=top_k,
        )


class IdentityVectorStore:
    """Score only vectors that match one frozen Snapshot identity exactly."""

    def __init__(
        self,
        identity: EmbeddingIdentityV1,
        rows: Sequence[StoredVectorRow],
    ) -> None:
        self.identity = identity
        self.rows = tuple(rows)

    def search_values(
        self,
        query: QueryEmbeddingV1,
        *,
        top_k: int = 6,
    ) -> tuple[VectorMatch, ...]:
        if query.identity != self.identity:
            raise ValueError("query and Snapshot embedding identities do not match")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        matches: list[VectorMatch] = []
        for row in self.rows:
            if row.dimension != self.identity.dimension or row.key != self.identity.model_key:
                raise ValueError("mixed or invalid vector metadata")
            values = unpack_vector(row.blob, self.identity)
            score = sum(left * right for left, right in zip(query.values, values, strict=True))
            matches.append(
                VectorMatch(
                    chunk_id=row.chunk_id,
                    source_filename=row.source_filename,
                    score=score,
                    document_order=row.document_order,
                    chunk_index=row.chunk_index,
                    chunk_text=row.chunk_text,
                )
            )
        matches.sort(
            key=lambda item: (
                -item.score,
                item.document_order,
                item.chunk_index,
                item.chunk_id,
            )
        )
        return tuple(matches[:top_k])
