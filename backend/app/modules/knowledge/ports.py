"""Internal provider-neutral ports used by the Wave 1A RAG service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class EmbeddingProvider(Protocol):
    dimension: int
    key: str

    def embed(self, text: str) -> bytes:
        """Return the deterministic packed vector for normalized text."""


@dataclass(frozen=True)
class VectorMatch:
    chunk_id: str
    source_filename: str
    score: float
    document_order: int
    chunk_index: int
    chunk_text: str


class VectorStore(Protocol):
    def search(self, query: str, *, top_k: int = 6) -> Iterable[VectorMatch]:
        """Search one already-authorized draft or snapshot scope."""
