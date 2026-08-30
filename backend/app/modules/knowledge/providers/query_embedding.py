"""Identity-bound query embeddings for the W4-EMBED retrieval seam.

This module deliberately stops at an injected batch-provider port.  It does
not select a Provider, read configuration, or perform network I/O.  A real
query can cross the port only after the caller supplies exact control,
manifest and budget preconditions for the persisted Snapshot identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast

from app.modules.knowledge.vector import (
    MOCK_EMBEDDING_IDENTITY,
    REAL_EMBEDDING_IDENTITY,
    EmbeddingIdentityV1,
    IdentityVectorStore,
    QueryEmbeddingV1,
    StoredVectorRow,
    unpack_vector,
)

from .adapters import EmbeddingProviderError
from .embedding import ValidatedEmbeddingBatchV1
from .packing import (
    MAX_BATCH_ITEMS,
    MAX_BATCH_TOKENS,
    MAX_ITEM_TOKENS,
    EmbeddingBatchV1,
    EmbeddingItemV1,
)
from .tokenizer import TokenizerError, count_tokens

QUERY_EMBEDDING_VERSION = "query-embedding-v1"
QUERY_PROVIDER_OPERATION = "embedding_query"


class QueryEmbeddingError(ValueError):
    """A query cannot cross or use the identity-bound embedding boundary."""

    def __init__(self, message: str, *, code: str = "query_embedding_invalid") -> None:
        super().__init__(message)
        self.code = code


class QueryEmbeddingIdentityError(QueryEmbeddingError):
    """A persisted Snapshot does not carry one supported five-field identity."""

    def __init__(self, message: str = "Snapshot embedding identity is invalid") -> None:
        super().__init__(message, code="query_embedding_identity_mismatch")


class QueryEmbeddingPreflightError(QueryEmbeddingError):
    """A required exact manifest/control/budget precondition is unavailable."""

    def __init__(self, message: str = "query embedding preflight is unavailable") -> None:
        super().__init__(message, code="query_embedding_preflight_required")


class QueryEmbeddingProviderError(QueryEmbeddingError):
    """An injected provider returned an unusable or mismatched query result."""

    def __init__(self, message: str = "query embedding provider result is invalid") -> None:
        super().__init__(message, code="query_embedding_provider_invalid")


class QueryEmbeddingManifestPort(Protocol):
    """Require the exact confirmed export manifest for a query batch."""

    def require_exact_manifest(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object:
        """Raise if the exact manifest/confirmation is unavailable."""


class QueryEmbeddingControlPort(Protocol):
    """Require the server-side operation control for one query batch."""

    def require_query_preflight(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object:
        """Raise if policy, operation or identity control is stale."""


class QueryEmbeddingBudgetPort(Protocol):
    """Reserve exactly one provider request for a query batch."""

    def reserve_query(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
        request_count: int,
        total_tokens: int,
    ) -> object:
        """Raise if the frozen request/token/cost allowance is unavailable."""


class QueryEmbeddingBatchProvider(Protocol):
    """Injected provider port; implementations must not be selected here."""

    model_key: str
    dimension: int
    provider: str
    region: str
    policy_version: str

    def embed_batch(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        """Embed the opaque query batch once."""


QueryEmbeddingControl = QueryEmbeddingControlPort
QueryEmbeddingManifest = QueryEmbeddingManifestPort
QueryEmbeddingBudget = QueryEmbeddingBudgetPort


def _snapshot_value(snapshot: object, field_name: str) -> object:
    if isinstance(snapshot, Mapping):
        return snapshot.get(field_name)
    return getattr(snapshot, field_name, None)


def persisted_snapshot_identity(snapshot: object) -> EmbeddingIdentityV1:
    """Construct a closed vector identity from a persisted Snapshot row.

    The function intentionally reads only identity fields.  It never inspects
    source filenames, source text, Persona data, private metadata or vector
    contents while preparing a query.
    """

    provider = _snapshot_value(snapshot, "embedding_provider")
    model_key = _snapshot_value(snapshot, "embedding_model_key")
    if model_key is None:
        model_key = _snapshot_value(snapshot, "embedding_key")
    region = _snapshot_value(snapshot, "embedding_region")
    dimension = _snapshot_value(snapshot, "embedding_dimension")
    policy_version = _snapshot_value(snapshot, "embedding_policy_version")
    if (
        not isinstance(provider, str)
        or not provider
        or not isinstance(model_key, str)
        or not model_key
        or not isinstance(region, str)
        or not region
        or isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or not isinstance(policy_version, str)
        or not policy_version
    ):
        raise QueryEmbeddingIdentityError("persisted Snapshot identity is incomplete")
    try:
        return EmbeddingIdentityV1(
            provider=provider,
            model_key=model_key,
            region=region,
            dimension=dimension,
            policy_version=policy_version,
        )
    except ValueError as exc:
        raise QueryEmbeddingIdentityError() from exc


snapshot_embedding_identity = persisted_snapshot_identity
embedding_identity_from_snapshot = persisted_snapshot_identity


def _snapshot_id(snapshot: object, explicit: str | None) -> str:
    value = explicit if explicit is not None else _snapshot_value(snapshot, "id")
    if not isinstance(value, str) or not value.strip():
        raise QueryEmbeddingError(
            "a persisted Snapshot ID is required for query embedding",
            code="query_embedding_snapshot_missing",
        )
    return value


def query_hash(query: str) -> str:
    """Return the stable cache key without retaining query text."""

    if not isinstance(query, str) or not query.strip() or "\x00" in query:
        raise QueryEmbeddingError("query text is invalid", code="query_embedding_query_invalid")
    return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _valid_vector_values(values: object, dimension: int) -> bool:
    """Check provider/cache values without allowing numeric conversion to leak."""

    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return False
    if len(values) != dimension:
        return False
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return False
        try:
            converted = float(item)
        except (OverflowError, TypeError, ValueError):
            return False
        if not math.isfinite(converted):
            return False
    return True


@dataclass
class QueryEmbeddingCache:
    """Identity-checked query_hash -> QueryEmbeddingV1 cache."""

    _values: dict[str, QueryEmbeddingV1] = field(default_factory=dict)

    def get(self, key: str, identity: EmbeddingIdentityV1) -> QueryEmbeddingV1 | None:
        value = self._values.get(key)
        if value is None:
            return None
        if value.identity != identity:
            raise QueryEmbeddingError(
                "cached query embedding identity does not match Snapshot",
                code="query_embedding_cache_identity_mismatch",
            )
        if not _valid_vector_values(value.values, identity.dimension):
            raise QueryEmbeddingError(
                "cached query embedding is invalid", code="query_embedding_cache_invalid"
            )
        return value

    def put(self, key: str, value: QueryEmbeddingV1) -> None:
        if not _valid_vector_values(value.values, value.identity.dimension):
            raise QueryEmbeddingError(
                "query embedding is invalid", code="query_embedding_cache_invalid"
            )
        existing = self._values.get(key)
        if existing is not None and existing != value:
            raise QueryEmbeddingError(
                "cached query embedding changed", code="query_embedding_cache_conflict"
            )
        self._values[key] = value

    @property
    def values(self) -> Mapping[str, QueryEmbeddingV1]:
        return dict(self._values)


def _cache_get(
    cache: QueryEmbeddingCache | MutableMapping[str, QueryEmbeddingV1],
    key: str,
    identity: EmbeddingIdentityV1,
) -> QueryEmbeddingV1 | None:
    if isinstance(cache, QueryEmbeddingCache):
        return cache.get(key, identity)
    value = cache.get(key)
    if value is None:
        return None
    if not isinstance(value, QueryEmbeddingV1) or value.identity != identity:
        raise QueryEmbeddingError(
            "cached query embedding identity does not match Snapshot",
            code="query_embedding_cache_identity_mismatch",
        )
    if not _valid_vector_values(value.values, identity.dimension):
        raise QueryEmbeddingError(
            "cached query embedding is invalid", code="query_embedding_cache_invalid"
        )
    return value


def _cache_put(
    cache: QueryEmbeddingCache | MutableMapping[str, QueryEmbeddingV1],
    key: str,
    value: QueryEmbeddingV1,
) -> None:
    if not _valid_vector_values(value.values, value.identity.dimension):
        raise QueryEmbeddingError(
            "query embedding is invalid", code="query_embedding_cache_invalid"
        )
    if isinstance(cache, QueryEmbeddingCache):
        cache.put(key, value)
        return
    existing = cache.get(key)
    if existing is not None and existing != value:
        raise QueryEmbeddingError(
            "cached query embedding changed", code="query_embedding_cache_conflict"
        )
    cache[key] = value


def _query_pairs(subqueries: str | Sequence[str]) -> tuple[tuple[str, str], ...]:
    values = (subqueries,) if isinstance(subqueries, str) else tuple(subqueries)
    if not values:
        raise QueryEmbeddingError(
            "at least one query is required", code="query_embedding_query_invalid"
        )
    pairs: list[tuple[str, str]] = []
    for value in values:
        if not isinstance(value, str):
            raise QueryEmbeddingError("query text is invalid", code="query_embedding_query_invalid")
        pairs.append((value.strip(), query_hash(value)))
    return tuple(pairs)


def _unique_queries(pairs: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for value, key in pairs:
        if key not in seen:
            seen.add(key)
            unique.append((value, key))
    if len(unique) > MAX_BATCH_ITEMS:
        raise QueryEmbeddingError(
            "query batch exceeds the fixed item limit", code="query_embedding_batch_too_large"
        )
    return tuple(unique)


def _query_batch(
    queries: tuple[tuple[str, str], ...],
    identity: EmbeddingIdentityV1,
    snapshot_id: str,
    build_manifest_hash: str | None = None,
) -> tuple[EmbeddingBatchV1, tuple[str, ...], int]:
    token_counts: list[int] = []
    for value, _ in queries:
        try:
            count = count_tokens(value)
        except TokenizerError as exc:
            raise QueryEmbeddingError(
                "query tokenizer is unavailable", code="query_embedding_tokenizer_unavailable"
            ) from exc
        if count > MAX_ITEM_TOKENS:
            raise QueryEmbeddingError(
                "query exceeds the fixed token limit", code="query_embedding_query_too_large"
            )
        token_counts.append(count)
    total_tokens = sum(token_counts)
    if total_tokens > MAX_BATCH_TOKENS:
        raise QueryEmbeddingError(
            "query batch exceeds the fixed token limit", code="query_embedding_batch_too_large"
        )
    query_hashes = tuple(key for _, key in queries)
    resolved_build_manifest_hash = build_manifest_hash or _canonical_hash(
        {
            "version": QUERY_EMBEDDING_VERSION,
            "snapshot_id": snapshot_id,
            "identity": {
                "provider": identity.provider,
                "model_key": identity.model_key,
                "region": identity.region,
                "dimension": identity.dimension,
                "policy_version": identity.policy_version,
            },
            "query_hashes": query_hashes,
            "token_counts": token_counts,
        }
    )
    if (
        not isinstance(resolved_build_manifest_hash, str)
        or len(resolved_build_manifest_hash) != 64
        or any(char not in "0123456789abcdef" for char in resolved_build_manifest_hash)
    ):
        raise QueryEmbeddingError(
            "query build manifest hash is invalid", code="query_embedding_manifest_invalid"
        )
    items = tuple(
        EmbeddingItemV1(
            chunk_id=key,
            text=value,
            token_count=token_count,
            chunk_sha256=key,
            build_manifest_hash=resolved_build_manifest_hash,
            document_id=f"query:{key}",
            document_order=index,
            chunk_index=0,
        )
        for index, ((value, key), token_count) in enumerate(zip(queries, token_counts, strict=True))
    )
    return (
        EmbeddingBatchV1(
            batch_index=0,
            build_id=f"query:{snapshot_id}",
            build_manifest_hash=resolved_build_manifest_hash,
            model_key=identity.model_key,
            dimension=identity.dimension,
            items=items,
            total_tokens=total_tokens,
            policy_version=identity.policy_version,
            embedding_provider=identity.provider,
            embedding_region=identity.region,
        ),
        query_hashes,
        total_tokens,
    )


def _provider_identity(provider: object) -> tuple[str, str, str, int, str]:
    values = tuple(
        getattr(provider, field_name, None)
        for field_name in ("provider", "model_key", "region", "dimension", "policy_version")
    )
    provider_name, model_key, region, dimension, policy_version = values
    if (
        not isinstance(provider_name, str)
        or not isinstance(model_key, str)
        or not isinstance(region, str)
        or isinstance(dimension, bool)
        or not isinstance(dimension, int)
        or not isinstance(policy_version, str)
    ):
        raise QueryEmbeddingPreflightError("injected provider identity is incomplete")
    return provider_name, model_key, region, dimension, policy_version


def _require_port_method(port: object | None, method_name: str) -> object:
    method = getattr(port, method_name, None) if port is not None else None
    if not callable(method):
        raise QueryEmbeddingPreflightError(f"query embedding requires {method_name} preflight")
    return method


@dataclass
class QueryEmbeddingService:
    """Build/cache query vectors under one persisted Snapshot identity."""

    provider: QueryEmbeddingBatchProvider | object | None = None
    control: QueryEmbeddingControlPort | object | None = None
    manifest: QueryEmbeddingManifestPort | object | None = None
    budget: QueryEmbeddingBudgetPort | object | None = None
    cache: QueryEmbeddingCache | MutableMapping[str, QueryEmbeddingV1] = field(
        default_factory=QueryEmbeddingCache
    )
    # Optional persisted build hash used by an application control adapter.
    # When omitted, the historical deterministic query-request hash remains
    # unchanged for standalone callers.
    build_manifest_hash: str | None = None

    def embed_query(
        self,
        snapshot: object,
        query: str,
        *,
        snapshot_id: str | None = None,
    ) -> QueryEmbeddingV1:
        return self.embed_subqueries(snapshot, (query,), snapshot_id=snapshot_id)[0]

    embed = embed_query

    def embed_subqueries(
        self,
        snapshot: object,
        subqueries: str | Sequence[str],
        *,
        snapshot_id: str | None = None,
    ) -> tuple[QueryEmbeddingV1, ...]:
        identity = persisted_snapshot_identity(snapshot)
        requested = _query_pairs(subqueries)
        queries = _unique_queries(requested)
        resolved: dict[str, QueryEmbeddingV1] = {}
        missing: list[tuple[str, str]] = []
        for value, key in queries:
            cached = _cache_get(self.cache, key, identity)
            if cached is None:
                missing.append((value, key))
            else:
                resolved[key] = cached
        if missing:
            if identity == MOCK_EMBEDDING_IDENTITY:
                for value, key in missing:
                    try:
                        values = unpack_vector(
                            _mock_embedding(value),
                            MOCK_EMBEDDING_IDENTITY,
                        )
                        embedding = QueryEmbeddingV1(identity, values)
                    except (TypeError, ValueError) as exc:
                        raise QueryEmbeddingProviderError(
                            "Mock query embedding is invalid"
                        ) from exc
                    _cache_put(self.cache, key, embedding)
                    resolved[key] = embedding
            elif identity == REAL_EMBEDDING_IDENTITY:
                resolved_snapshot_id = _snapshot_id(snapshot, snapshot_id)
                self._embed_real(
                    identity,
                    tuple(missing),
                    snapshot_id=resolved_snapshot_id,
                    resolved=resolved,
                )
            else:  # pragma: no cover - EmbeddingIdentityV1 is closed
                raise QueryEmbeddingIdentityError()
        try:
            return tuple(resolved[key] for _, key in requested)
        except KeyError as exc:  # pragma: no cover - guarded by cache/provider checks
            raise QueryEmbeddingError(
                "query embedding cache is incomplete", code="query_embedding_cache_missing"
            ) from exc

    def _embed_real(
        self,
        identity: EmbeddingIdentityV1,
        queries: tuple[tuple[str, str], ...],
        *,
        snapshot_id: str,
        resolved: dict[str, QueryEmbeddingV1],
    ) -> None:
        provider = self.provider
        if provider is None or not callable(getattr(provider, "embed_batch", None)):
            raise QueryEmbeddingPreflightError("a real query batch provider is required")
        provider_identity = _provider_identity(provider)
        if provider_identity != (
            identity.provider,
            identity.model_key,
            identity.region,
            identity.dimension,
            identity.policy_version,
        ):
            raise QueryEmbeddingPreflightError("injected provider identity does not match Snapshot")
        manifest_method = _require_port_method(self.manifest, "require_exact_manifest")
        control_method = _require_port_method(self.control, "require_query_preflight")
        budget_method = _require_port_method(self.budget, "reserve_query")
        batch, query_hashes, total_tokens = _query_batch(
            queries,
            identity,
            snapshot_id,
            self.build_manifest_hash,
        )
        try:
            cast(CallableQueryPreflight, manifest_method)(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
            )
            cast(CallableQueryPreflight, control_method)(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
            )
            cast(CallableQueryBudget, budget_method)(
                snapshot_id=snapshot_id,
                identity=identity,
                query_hashes=query_hashes,
                request_count=1,
                total_tokens=total_tokens,
            )
        except QueryEmbeddingError:
            raise
        except Exception as exc:
            raise QueryEmbeddingPreflightError() from exc
        try:
            result = cast(QueryEmbeddingBatchProvider, provider).embed_batch(batch)
        except QueryEmbeddingError:
            raise
        except EmbeddingProviderError:
            # Keep the safe not-sent/acceptance-unknown classification for the
            # durable operation adapter that owns provider outcomes.
            raise
        except Exception as exc:
            raise QueryEmbeddingProviderError() from exc
        if not isinstance(result, ValidatedEmbeddingBatchV1):
            raise QueryEmbeddingProviderError("query provider returned an unvalidated batch")
        if (
            result.build_id != batch.build_id
            or result.build_manifest_hash != batch.build_manifest_hash
            or result.batch_index != batch.batch_index
            or result.chunk_ids != query_hashes
            or result.model_key != identity.model_key
            or result.dimension != identity.dimension
            or result.embedding_provider != identity.provider
            or result.embedding_region != identity.region
            or result.policy_version != identity.policy_version
        ):
            raise QueryEmbeddingProviderError("query provider result identity does not match")
        try:
            embeddings = tuple(
                QueryEmbeddingV1(identity, tuple(values)) for values in result.vectors
            )
            if not all(
                _valid_vector_values(embedding.values, identity.dimension)
                for embedding in embeddings
            ):
                raise ValueError("query provider vector values are invalid")
            for key, embedding in zip(query_hashes, embeddings, strict=True):
                _cache_put(self.cache, key, embedding)
                resolved[key] = embedding
        except (OverflowError, TypeError, ValueError) as exc:
            raise QueryEmbeddingProviderError("query provider vector shape is invalid") from exc


class CallableQueryPreflight(Protocol):
    def __call__(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
    ) -> object: ...


class CallableQueryBudget(Protocol):
    def __call__(
        self,
        *,
        snapshot_id: str,
        identity: EmbeddingIdentityV1,
        query_hashes: tuple[str, ...],
        request_count: int,
        total_tokens: int,
    ) -> object: ...


def _mock_embedding(query: str) -> bytes:
    """Compute a local Mock vector without selecting or contacting a Provider."""

    from app.modules.knowledge.markdown import mock_embedding

    return mock_embedding(query)


@dataclass
class IdentityQuerySearch:
    """Search strict/relaxed thresholds with one cached query vector."""

    embeddings: QueryEmbeddingService

    def search(
        self,
        snapshot: object,
        query: str,
        store: IdentityVectorStore,
        *,
        strict: bool = True,
        top_k: int = 6,
    ) -> tuple[object, ...]:
        if not isinstance(strict, bool):
            raise QueryEmbeddingError("search strict flag is invalid", code="query_search_invalid")
        identity = persisted_snapshot_identity(snapshot)
        if store.identity != identity:
            raise QueryEmbeddingIdentityError("vector store identity does not match Snapshot")
        value = self.embeddings.embed_query(snapshot, query)
        # Both strict and relaxed scoring modes deliberately reuse the exact
        # identity-bound vector.  Relaxation may change caller-side threshold
        # policy, but it must never issue a second embedding call.
        del strict
        return cast(tuple[object, ...], store.search_values(value, top_k=top_k))

    search_values = search


def identity_vector_store(snapshot: object, rows: Sequence[StoredVectorRow]) -> IdentityVectorStore:
    """Build a strict vector store from one persisted Snapshot identity."""

    return IdentityVectorStore(persisted_snapshot_identity(snapshot), rows)


def search_snapshot(
    service: QueryEmbeddingService,
    snapshot: object,
    query: str,
    store: IdentityVectorStore,
    *,
    strict: bool = True,
    top_k: int = 6,
) -> tuple[object, ...]:
    """Functional seam for strict/relaxed search without a second query call."""

    return IdentityQuerySearch(service).search(
        snapshot,
        query,
        store,
        strict=strict,
        top_k=top_k,
    )


QueryEmbeddingRunner = QueryEmbeddingService
QueryEmbeddingEngine = QueryEmbeddingService
SnapshotQueryEmbeddingService = QueryEmbeddingService


__all__ = [
    "CallableQueryBudget",
    "CallableQueryPreflight",
    "IdentityQuerySearch",
    "QueryEmbeddingBatchProvider",
    "QueryEmbeddingBudget",
    "QueryEmbeddingBudgetPort",
    "QueryEmbeddingCache",
    "QueryEmbeddingControl",
    "QueryEmbeddingControlPort",
    "QueryEmbeddingEngine",
    "QueryEmbeddingError",
    "QueryEmbeddingIdentityError",
    "QueryEmbeddingManifest",
    "QueryEmbeddingManifestPort",
    "QueryEmbeddingPreflightError",
    "QueryEmbeddingProviderError",
    "QueryEmbeddingRunner",
    "QueryEmbeddingService",
    "QueryEmbeddingV1",
    "QUERY_EMBEDDING_VERSION",
    "QUERY_PROVIDER_OPERATION",
    "SnapshotQueryEmbeddingService",
    "embedding_identity_from_snapshot",
    "identity_vector_store",
    "persisted_snapshot_identity",
    "query_hash",
    "search_snapshot",
    "snapshot_embedding_identity",
]
