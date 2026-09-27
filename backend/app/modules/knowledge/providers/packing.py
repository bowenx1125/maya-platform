"""Deterministic embedding item and request packing for W4-EMBED."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from .snapshot_build import embedding_policy_version_for
from .tokenizer import PinnedTokenizer, TokenizerError, count_tokens

if TYPE_CHECKING:
    from .snapshot_build import SnapshotBuildChunkV1, SnapshotBuildV1


MAX_BATCH_ITEMS = 10
MAX_BATCH_TOKENS = 30_000
MAX_REQUESTS = 20
MAX_TOTAL_TOKENS = 120_000
DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION = Decimal("0.5")
DEFAULT_EMBEDDING_COST_CAP_CNY = Decimal("0.10")


class EmbeddingPlanError(ValueError):
    """A build cannot be sent under the frozen item/batch/cost limits."""

    def __init__(self, message: str, *, code: str = "embedding_plan_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EmbeddingItemV1:
    """One provider input bound to one immutable build chunk."""

    chunk_id: str
    text: str
    token_count: int
    chunk_sha256: str
    build_manifest_hash: str
    document_id: str
    document_order: int
    chunk_index: int

    @property
    def input_id(self) -> str:
        return self.chunk_id

    @property
    def id(self) -> str:
        return self.chunk_id

    @property
    def input_text(self) -> str:
        return self.text

    @property
    def text_hash(self) -> str:
        return self.chunk_sha256

    def as_record(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "text_sha256": self.chunk_sha256,
            "build_manifest_hash": self.build_manifest_hash,
            "document_id": self.document_id,
            "document_order": self.document_order,
            "chunk_index": self.chunk_index,
            "token_count": self.token_count,
        }


@dataclass(frozen=True, slots=True)
class EmbeddingBatchV1:
    """A stable greedy batch, never reordered by a provider adapter."""

    batch_index: int
    build_id: str
    build_manifest_hash: str
    model_key: str
    dimension: int
    items: tuple[EmbeddingItemV1, ...]
    total_tokens: int
    policy_version: str = ""
    embedding_provider: str = ""
    embedding_region: str = ""

    @property
    def request_index(self) -> int:
        return self.batch_index

    @property
    def inputs(self) -> tuple[EmbeddingItemV1, ...]:
        return self.items

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.items)

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(item.chunk_id for item in self.items)

    @property
    def item_count(self) -> int:
        return len(self.items)

    def as_record(self) -> dict[str, object]:
        return {
            "batch_index": self.batch_index,
            "build_id": self.build_id,
            "build_manifest_hash": self.build_manifest_hash,
            "embedding_provider": self.embedding_provider,
            "model_key": self.model_key,
            "embedding_region": self.embedding_region,
            "dimension": self.dimension,
            "policy_version": self.policy_version,
            "total_tokens": self.total_tokens,
            "items": [item.as_record() for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class EmbeddingPlanV1:
    """Complete, preflighted embedding request plan."""

    build_id: str
    build_manifest_hash: str
    model_key: str
    dimension: int
    batches: tuple[EmbeddingBatchV1, ...]
    total_tokens: int
    estimated_cost_cny: float
    tokenizer_id: str
    tokenizer_asset_hash: str
    policy_version: str = ""
    embedding_provider: str = ""
    embedding_region: str = ""

    @property
    def request_count(self) -> int:
        return len(self.batches)

    @property
    def requests(self) -> tuple[EmbeddingBatchV1, ...]:
        return self.batches

    @property
    def item_count(self) -> int:
        return sum(batch.item_count for batch in self.batches)

    @property
    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(item.chunk_id for batch in self.batches for item in batch.items)

    @property
    def plan_hash(self) -> str:
        """Hash the request identity without exposing source text in logs."""

        import hashlib
        import json

        payload = {
            "build_id": self.build_id,
            "build_manifest_hash": self.build_manifest_hash,
            "embedding_provider": self.embedding_provider,
            "model_key": self.model_key,
            "embedding_region": self.embedding_region,
            "dimension": self.dimension,
            "policy_version": self.policy_version,
            "batches": [
                {
                    "batch_index": batch.batch_index,
                    "chunk_ids": list(batch.chunk_ids),
                    "token_counts": [item.token_count for item in batch.items],
                    "parameters": {"dimension": self.dimension},
                }
                for batch in self.batches
            ],
            "total_tokens": self.total_tokens,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_asset_hash": self.tokenizer_asset_hash,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def as_record(self) -> dict[str, object]:
        return {
            "build_id": self.build_id,
            "build_manifest_hash": self.build_manifest_hash,
            "model_key": self.model_key,
            "dimension": self.dimension,
            "embedding_provider": self.embedding_provider,
            "embedding_region": self.embedding_region,
            "policy_version": self.policy_version,
            "total_tokens": self.total_tokens,
            "estimated_cost_cny": self.estimated_cost_cny,
            "tokenizer_id": self.tokenizer_id,
            "tokenizer_asset_hash": self.tokenizer_asset_hash,
            "plan_hash": self.plan_hash,
            "batches": [batch.as_record() for batch in self.batches],
        }


def _decimal(value: Decimal | float | int | str, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EmbeddingPlanError(f"{field} is invalid", code="embedding_budget_invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise EmbeddingPlanError(f"{field} is invalid", code="embedding_budget_invalid")
    return parsed


def _chunk_item(
    chunk: SnapshotBuildChunkV1,
    *,
    build_manifest_hash: str,
    tokenizer: PinnedTokenizer | object | None,
) -> EmbeddingItemV1:
    try:
        count = count_tokens(chunk.text, tokenizer)
    except TokenizerError as exc:
        raise EmbeddingPlanError(
            "tokenizer is unavailable", code="embedding_tokenizer_unavailable"
        ) from exc
    return EmbeddingItemV1(
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        token_count=count,
        chunk_sha256=chunk.text_sha256,
        build_manifest_hash=build_manifest_hash,
        document_id=chunk.document_id,
        document_order=chunk.document_order,
        chunk_index=chunk.chunk_index,
    )


def plan_embedding_batches(
    build: SnapshotBuildV1,
    *,
    tokenizer: PinnedTokenizer | object | None = None,
    price_cny_per_million: Decimal | float | int | str = DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION,
    cost_cap_cny: Decimal | float | int | str = DEFAULT_EMBEDDING_COST_CAP_CNY,
) -> EmbeddingPlanV1:
    """Pack chunks in document/chunk order and fail before any provider call."""

    # Import at runtime to keep this module's type-only boundary acyclic.
    from .tokenizer import Utf8ByteTokenizer

    if not build.chunks:
        raise EmbeddingPlanError("SnapshotBuild has no chunks", code="embedding_plan_empty")
    policy_version = build.embedding_policy_version
    if not policy_version:
        policy_version = (
            embedding_policy_version_for(build.embedding_model_key, build.embedding_dimension) or ""
        )
    if not policy_version:
        raise EmbeddingPlanError(
            "embedding resource has no supported policy version",
            code="embedding_resource_invalid",
        )
    effective_tokenizer = tokenizer if tokenizer is not None else Utf8ByteTokenizer()
    tokenizer_id = str(getattr(effective_tokenizer, "tokenizer_id", "unknown"))
    tokenizer_asset_hash = str(getattr(effective_tokenizer, "asset_hash", "unknown"))
    if not tokenizer_id or not tokenizer_asset_hash:
        raise EmbeddingPlanError(
            "tokenizer identity is required", code="embedding_tokenizer_invalid"
        )

    items = tuple(
        _chunk_item(
            chunk,
            build_manifest_hash=build.manifest_hash,
            tokenizer=effective_tokenizer,
        )
        for chunk in build.chunks
    )
    # Snapshot-wide token, request and CNY ceilings were removed. Batch shape
    # below still keeps each provider call within the supplier's item count.
    total_tokens = sum(item.token_count for item in items)

    batches: list[EmbeddingBatchV1] = []
    current: list[EmbeddingItemV1] = []
    current_tokens = 0
    for item in items:
        if item.token_count > MAX_BATCH_TOKENS:
            raise EmbeddingPlanError(
                "one embedding item exceeds the 30000-token supplier batch limit",
                code="embedding_item_tokens_exceeded",
            )
        would_exceed = bool(current) and (
            len(current) >= MAX_BATCH_ITEMS or current_tokens + item.token_count > MAX_BATCH_TOKENS
        )
        if would_exceed:
            batches.append(
                EmbeddingBatchV1(
                    batch_index=len(batches),
                    build_id=build.build_id,
                    build_manifest_hash=build.manifest_hash,
                    model_key=build.embedding_model_key,
                    dimension=build.embedding_dimension,
                    items=tuple(current),
                    total_tokens=current_tokens,
                    policy_version=policy_version,
                    embedding_provider=build.embedding_provider,
                    embedding_region=build.embedding_region,
                )
            )
            current = []
            current_tokens = 0
        current.append(item)
        current_tokens += item.token_count
    if current:
        batches.append(
            EmbeddingBatchV1(
                batch_index=len(batches),
                build_id=build.build_id,
                build_manifest_hash=build.manifest_hash,
                model_key=build.embedding_model_key,
                dimension=build.embedding_dimension,
                items=tuple(current),
                total_tokens=current_tokens,
                policy_version=policy_version,
                embedding_provider=build.embedding_provider,
                embedding_region=build.embedding_region,
            )
        )

    price = _decimal(price_cny_per_million, field="embedding price")
    _decimal(cost_cap_cny, field="embedding cost cap")
    estimated = (Decimal(total_tokens) * price) / Decimal(1_000_000)
    return EmbeddingPlanV1(
        build_id=build.build_id,
        build_manifest_hash=build.manifest_hash,
        model_key=build.embedding_model_key,
        dimension=build.embedding_dimension,
        batches=tuple(batches),
        total_tokens=total_tokens,
        estimated_cost_cny=float(estimated),
        tokenizer_id=tokenizer_id,
        tokenizer_asset_hash=tokenizer_asset_hash,
        policy_version=policy_version,
        embedding_provider=build.embedding_provider,
        embedding_region=build.embedding_region,
    )


# Descriptive aliases for the integration layer.
pack_embedding_batches = plan_embedding_batches
build_embedding_plan = plan_embedding_batches


__all__ = [
    "DEFAULT_EMBEDDING_COST_CAP_CNY",
    "DEFAULT_EMBEDDING_PRICE_CNY_PER_MILLION",
    "EmbeddingBatchV1",
    "EmbeddingItemV1",
    "EmbeddingPlanError",
    "EmbeddingPlanV1",
    "MAX_BATCH_ITEMS",
    "MAX_BATCH_TOKENS",
    "MAX_REQUESTS",
    "MAX_TOTAL_TOKENS",
    "build_embedding_plan",
    "pack_embedding_batches",
    "plan_embedding_batches",
]
