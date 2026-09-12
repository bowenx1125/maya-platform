"""Identity-bound real-query embedding tests using injected fakes only."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from app.modules.knowledge.providers.adapters import EmbeddingTransportNotSent
from app.modules.knowledge.providers.embedding import ValidatedEmbeddingBatchV1
from app.modules.knowledge.providers.query_embedding import (
    IdentityQuerySearch,
    QueryEmbeddingCache,
    QueryEmbeddingError,
    QueryEmbeddingIdentityError,
    QueryEmbeddingPreflightError,
    QueryEmbeddingProviderError,
    QueryEmbeddingService,
    embedding_identity_from_snapshot,
    identity_vector_store,
    query_hash,
)
from app.modules.knowledge.vector import (
    MOCK_EMBEDDING_IDENTITY,
    REAL_EMBEDDING_IDENTITY,
    QueryEmbeddingV1,
    StoredVectorRow,
)


def _snapshot(identity: Any = REAL_EMBEDDING_IDENTITY) -> SimpleNamespace:
    return SimpleNamespace(
        id="snapshot-query-1",
        embedding_provider=identity.provider,
        embedding_model_key=identity.model_key,
        embedding_region=identity.region,
        embedding_dimension=identity.dimension,
        embedding_policy_version=identity.policy_version,
        source_filename="private/should-never-be-read.md",
        private_metadata={"student_id": "private-student"},
    )


@dataclass
class _Preflight:
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def require_exact_manifest(self, **kwargs: Any) -> None:
        self.calls.append(("manifest", kwargs["query_hashes"]))

    def require_query_preflight(self, **kwargs: Any) -> None:
        self.calls.append(("control", kwargs["query_hashes"]))

    def reserve_query(self, **kwargs: Any) -> None:
        self.calls.append(("budget", kwargs["query_hashes"]))


@dataclass
class _BatchProvider:
    identity: Any = REAL_EMBEDDING_IDENTITY
    calls: list[Any] = field(default_factory=list)
    result_mutator: Any = None

    @property
    def provider(self) -> str:
        return self.identity.provider

    @property
    def model_key(self) -> str:
        return self.identity.model_key

    @property
    def region(self) -> str:
        return self.identity.region

    @property
    def dimension(self) -> int:
        return self.identity.dimension

    @property
    def policy_version(self) -> str:
        return self.identity.policy_version

    def embed_batch(self, batch: Any) -> ValidatedEmbeddingBatchV1:
        self.calls.append(batch)
        values = tuple((0.25,) * batch.dimension for _ in batch.items)
        result = ValidatedEmbeddingBatchV1(
            build_id=batch.build_id,
            build_manifest_hash=batch.build_manifest_hash,
            batch_index=batch.batch_index,
            chunk_ids=batch.chunk_ids,
            vectors=values,
            model_key=batch.model_key,
            dimension=batch.dimension,
            embedding_provider=batch.embedding_provider,
            embedding_region=batch.embedding_region,
            policy_version=batch.policy_version,
        )
        if self.result_mutator is not None:
            self.result_mutator(result)
        return result


@dataclass
class _FailingBatchProvider(_BatchProvider):
    failure: Exception = field(default_factory=EmbeddingTransportNotSent)

    def embed_batch(self, batch: Any) -> ValidatedEmbeddingBatchV1:
        self.calls.append(batch)
        raise self.failure


def _real_service(
    *,
    provider: Any | None = None,
    cache: Any | None = None,
) -> tuple[QueryEmbeddingService, _Preflight, _BatchProvider]:
    preflight = _Preflight()
    batch_provider = provider or _BatchProvider()
    service = QueryEmbeddingService(
        provider=batch_provider,
        manifest=preflight,
        control=preflight,
        budget=preflight,
        cache=cache or QueryEmbeddingCache(),
    )
    return service, preflight, batch_provider


def test_persisted_snapshot_identity_constructs_mock_and_real_query_shapes() -> None:
    mock = QueryEmbeddingService().embed_query(_snapshot(MOCK_EMBEDDING_IDENTITY), "culture")
    assert mock.identity == MOCK_EMBEDDING_IDENTITY
    assert len(mock.values) == 256

    service, _preflight, provider = _real_service()
    real = service.embed_query(_snapshot(), "culture")
    assert real.identity == REAL_EMBEDDING_IDENTITY
    assert len(real.values) == 1024
    assert len(provider.calls) == 1


def test_real_subqueries_deduplicate_provider_call_and_preserve_request_order() -> None:
    service, preflight, provider = _real_service()
    values = service.embed_subqueries(_snapshot(), (" alpha ", "beta", "alpha"))

    assert len(values) == 3
    assert values[0] is values[2]
    assert values[0].values == values[2].values
    assert len(provider.calls) == 1
    assert provider.calls[0].texts == ("alpha", "beta")
    assert [kind for kind, _ in preflight.calls] == ["manifest", "control", "budget"]
    assert preflight.calls[0][1] == (query_hash("alpha"), query_hash("beta"))


def test_query_hash_and_payload_use_trimmed_canonical_query() -> None:
    assert query_hash("  same query  ") == query_hash("same query")
    service, _preflight, provider = _real_service()

    first = service.embed_query(_snapshot(), "  same query  ")
    second = service.embed_query(_snapshot(), "same query")

    assert first is second
    assert len(provider.calls) == 1
    assert provider.calls[0].texts == ("same query",)


def test_invalid_query_sequence_fails_closed() -> None:
    service, _preflight, provider = _real_service()
    with pytest.raises(QueryEmbeddingError, match="query text is invalid"):
        service.embed_subqueries(_snapshot(), ("valid", None))  # type: ignore[list-item]
    assert provider.calls == []


def test_long_query_has_no_per_item_backend_limit() -> None:
    service, preflight, provider = _real_service()

    result = service.embed_query(_snapshot(), "x" * 8_001)
    assert result.values
    assert preflight.calls
    assert len(provider.calls) == 1


def test_real_request_batch_contains_no_source_or_private_metadata() -> None:
    service, _preflight, provider = _real_service()
    service.embed_query(_snapshot(), "public query")
    record = provider.calls[0].as_record()
    encoded = repr(record).casefold()
    assert "source_filename" not in encoded
    assert "private" not in encoded
    assert "student_id" not in encoded
    assert "should-never-be-read" not in encoded
    assert all("source_filename" not in item for item in record["items"])


@pytest.mark.parametrize("method", ("manifest", "control", "budget"))
def test_missing_real_preflight_port_fails_before_provider_call(method: str) -> None:
    preflight = _Preflight()
    kwargs = {"manifest": preflight, "control": preflight, "budget": preflight}
    kwargs[method] = None
    provider = _BatchProvider()
    service = QueryEmbeddingService(provider=provider, **kwargs)

    with pytest.raises(QueryEmbeddingPreflightError):
        service.embed_query(_snapshot(), "blocked")
    assert provider.calls == []


def test_provider_transport_classification_is_preserved_for_durable_owner() -> None:
    provider = _FailingBatchProvider()
    service, _preflight, _provider = _real_service(provider=provider)

    with pytest.raises(EmbeddingTransportNotSent):
        service.embed_query(_snapshot(), "provider failure")
    assert len(provider.calls) == 1


def test_provider_identity_mismatch_fails_before_provider_call() -> None:
    wrong = _BatchProvider(identity=MOCK_EMBEDDING_IDENTITY)
    service, _preflight, _provider = _real_service(provider=wrong)

    with pytest.raises(QueryEmbeddingPreflightError):
        service.embed_query(_snapshot(), "blocked")
    assert wrong.calls == []


def test_snapshot_identity_mismatch_and_missing_identity_fail_closed() -> None:
    bad = _snapshot()
    bad.embedding_policy_version = "wrong-policy"
    with pytest.raises(QueryEmbeddingIdentityError):
        embedding_identity_from_snapshot(bad)

    missing = SimpleNamespace(
        id="snapshot-missing",
        embedding_provider="dashscope",
        embedding_model_key="text-embedding-v4",
        embedding_region="cn-beijing",
        embedding_dimension=1024,
    )
    with pytest.raises(QueryEmbeddingIdentityError):
        embedding_identity_from_snapshot(missing)


@pytest.mark.parametrize("kind", ("wrong_length", "nonfinite", "wrong_chunk_ids"))
def test_wrong_provider_result_fails_closed(kind: str) -> None:
    def mutate(result: ValidatedEmbeddingBatchV1) -> None:
        if kind == "wrong_length":
            object.__setattr__(result, "vectors", ((0.1,),))
        elif kind == "nonfinite":
            object.__setattr__(
                result,
                "vectors",
                ((float("nan"),) * REAL_EMBEDDING_IDENTITY.dimension,),
            )
        else:
            object.__setattr__(result, "chunk_ids", ("not-the-query",))

    provider = _BatchProvider(result_mutator=mutate)
    service, _preflight, _provider = _real_service(provider=provider)
    with pytest.raises(QueryEmbeddingProviderError):
        service.embed_query(_snapshot(), "invalid result")
    assert len(provider.calls) == 1


def test_invalid_provider_batch_does_not_partially_fill_query_cache() -> None:
    def mutate(result: ValidatedEmbeddingBatchV1) -> None:
        object.__setattr__(
            result,
            "vectors",
            (
                (0.1,) * REAL_EMBEDDING_IDENTITY.dimension,
                (float("nan"),) * REAL_EMBEDDING_IDENTITY.dimension,
            ),
        )

    provider = _BatchProvider(result_mutator=mutate)
    service, _preflight, _provider = _real_service(provider=provider)

    with pytest.raises(QueryEmbeddingProviderError):
        service.embed_subqueries(_snapshot(), ("first", "second"))
    assert service.cache.values == {}


def test_cache_identity_mismatch_and_missing_cache_are_not_repaired_by_network() -> None:
    cache = QueryEmbeddingCache()
    cache.put(
        query_hash("same"),
        QueryEmbeddingV1(MOCK_EMBEDDING_IDENTITY, (0.0,) * MOCK_EMBEDDING_IDENTITY.dimension),
    )
    service, _preflight, provider = _real_service(cache=cache)
    with pytest.raises(QueryEmbeddingError, match="identity"):
        service.embed_query(_snapshot(), "same")
    assert provider.calls == []


def test_strict_and_relaxed_search_reuse_one_query_vector() -> None:
    service, _preflight, provider = _real_service()
    strict_query = service.embed_query(_snapshot(), "shared")
    row = StoredVectorRow(
        chunk_id="chunk-query",
        source_filename="safe.md",
        chunk_text="Safe excerpt",
        blob=strict_query.blob,
        dimension=REAL_EMBEDDING_IDENTITY.dimension,
        key=REAL_EMBEDDING_IDENTITY.model_key,
        document_order=0,
        chunk_index=0,
    )
    store = identity_vector_store(_snapshot(), (row,))
    search = IdentityQuerySearch(service)

    first = search.search(_snapshot(), "shared", store, strict=True)
    second = search.search(_snapshot(), "shared", store, strict=False)
    assert len(first) == len(second) == 1
    assert len(provider.calls) == 1
    assert service.cache.get(query_hash("shared"), REAL_EMBEDDING_IDENTITY) is strict_query


def test_store_identity_mismatch_fails_before_search() -> None:
    service = QueryEmbeddingService()
    mock_snapshot = _snapshot(MOCK_EMBEDDING_IDENTITY)
    real_rows: tuple[StoredVectorRow, ...] = ()
    real_store = identity_vector_store(_snapshot(), real_rows)
    with pytest.raises(QueryEmbeddingIdentityError):
        IdentityQuerySearch(service).search(mock_snapshot, "blocked", real_store)
