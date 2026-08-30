"""Closed Mock-256 versus real-1024 vector-search identity tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from app.modules.knowledge.vector import (
    MOCK_EMBEDDING_IDENTITY,
    REAL_EMBEDDING_IDENTITY,
    IdentityVectorStore,
    QueryEmbeddingV1,
    StoredVectorRow,
)


def _row(*, identity=REAL_EMBEDDING_IDENTITY, value: float = 0.25) -> StoredVectorRow:
    query = QueryEmbeddingV1(identity, (value,) * identity.dimension)
    return StoredVectorRow(
        chunk_id="chunk-1",
        source_filename="source.md",
        chunk_text="A bounded source excerpt.",
        blob=query.blob,
        dimension=identity.dimension,
        key=identity.model_key,
        document_order=0,
        chunk_index=0,
    )


def test_real_1024_query_scores_only_matching_real_snapshot_identity() -> None:
    query = QueryEmbeddingV1(
        REAL_EMBEDDING_IDENTITY,
        (0.5,) * REAL_EMBEDDING_IDENTITY.dimension,
    )
    matches = IdentityVectorStore(REAL_EMBEDDING_IDENTITY, [_row()]).search_values(query)
    assert [item.chunk_id for item in matches] == ["chunk-1"]


def test_query_identity_mismatch_fails_before_any_vector_comparison() -> None:
    query = QueryEmbeddingV1(
        MOCK_EMBEDDING_IDENTITY,
        (0.0,) * MOCK_EMBEDDING_IDENTITY.dimension,
    )
    with pytest.raises(ValueError, match="do not match"):
        IdentityVectorStore(REAL_EMBEDDING_IDENTITY, [_row()]).search_values(query)


def test_closed_identity_rejects_same_shape_with_another_policy() -> None:
    with pytest.raises(ValueError, match="closed contract"):
        replace(REAL_EMBEDDING_IDENTITY, policy_version="other")


def test_mixed_real_snapshot_vector_metadata_fails_closed() -> None:
    query = QueryEmbeddingV1(
        REAL_EMBEDDING_IDENTITY,
        (0.5,) * REAL_EMBEDDING_IDENTITY.dimension,
    )
    mixed = replace(_row(), dimension=256)
    with pytest.raises(ValueError, match="mixed"):
        IdentityVectorStore(REAL_EMBEDDING_IDENTITY, [mixed]).search_values(query)


def test_wrong_blob_length_and_nonfinite_query_are_rejected() -> None:
    short = replace(_row(), blob=b"\x00" * (4 * 1023))
    query = QueryEmbeddingV1(
        REAL_EMBEDDING_IDENTITY,
        (0.5,) * REAL_EMBEDDING_IDENTITY.dimension,
    )
    with pytest.raises(ValueError, match="blob length"):
        IdentityVectorStore(REAL_EMBEDDING_IDENTITY, [short]).search_values(query)
    with pytest.raises(ValueError, match="shape"):
        QueryEmbeddingV1(
            REAL_EMBEDDING_IDENTITY,
            (float("nan"),) + (0.0,) * 1023,
        )
