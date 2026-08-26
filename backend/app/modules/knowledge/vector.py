"""Standard-library deterministic vector adapter."""

from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.modules.knowledge.markdown import (
    EMBEDDING_DIMENSION,
    EMBEDDING_KEY,
    mock_embedding,
)
from app.modules.knowledge.ports import VectorMatch


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
        query_blob = mock_embedding(query)
        query_values = struct.unpack("<256f", query_blob)
        matches: list[VectorMatch] = []
        for row in self.rows:
            if (
                row.dimension != EMBEDDING_DIMENSION
                or row.key != EMBEDDING_KEY
                or len(row.blob) != EMBEDDING_DIMENSION * 4
            ):
                raise ValueError("mixed or invalid vector metadata")
            values = struct.unpack("<256f", row.blob)
            score = sum(left * right for left, right in zip(query_values, values, strict=True))
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
        return matches[:top_k]
