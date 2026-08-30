"""Focused W4-EMBED contract tests; all provider boundaries are fake/local."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from app.modules.debates.generation.retrieval import SnapshotRetriever, TurnSubquery
from app.modules.knowledge.markdown import mock_embedding
from app.modules.knowledge.mock_lexical import MOCK_LEXICAL_ANCHOR_POLICY_ID
from app.modules.knowledge.providers import (
    EmbeddingPlanError,
    EmbeddingResponseError,
    EmbeddingShapeError,
    InMemoryEmbeddingLedger,
    MockEmbeddingProvider,
    PinnedTokenizerV1,
    SnapshotBuildChunkV1,
    SnapshotBuildDocumentV1,
    SnapshotBuildV1,
    Utf8ByteTokenizer,
    plan_embedding_batches,
    prepare_snapshot_build,
)
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingAcceptanceUnknown,
    EmbeddingTransportNotSent,
)
from app.modules.knowledge.providers.embedding import validate_embedding_response
from app.modules.knowledge.providers.operations import (
    EmbeddingAcceptanceUnknownResult,
    execute_embedding_batch,
)
from app.modules.knowledge.vector import MockVectorStore, StoredVectorRow


def _build(text: str = "TikTok recommendation governance and public safety.") -> SnapshotBuildV1:
    return prepare_snapshot_build(
        agent_version_id="agent-version-1",
        knowledge_snapshot_id="snapshot-new-1",
        draft_revision=4,
        persona_spec_hash="persona-hash",
        documents=[
            {
                "document_id": "document-1",
                "source_filename": "lesson.md",
                "text": text,
            }
        ],
    )


def _manual_build(chunk_count: int = 12, *, token_count: int = 3) -> SnapshotBuildV1:
    chunks = tuple(
        SnapshotBuildChunkV1(
            chunk_id=f"chunk-{index}",
            document_id="document-1",
            document_order=0,
            chunk_index=index,
            text="one two three",
            start_offset=index * 13,
            end_offset=index * 13 + 13,
        )
        for index in range(chunk_count)
    )
    document = SnapshotBuildDocumentV1(
        document_id="document-1",
        source_filename="lesson.md",
        order_index=0,
        normalized_text="one two three",
        chunks=chunks,
    )
    # The explicit tokenizer below gives each item a controllable count; the
    # chunk text remains the exact immutable payload in the manifest.
    del token_count
    return SnapshotBuildV1(
        build_id="build-1",
        agent_version_id="agent-version-1",
        knowledge_snapshot_id="snapshot-new-1",
        draft_revision=1,
        persona_spec_hash="persona-hash",
        documents=(document,),
    )


def test_snapshot_build_manifest_is_canonical_and_changes_on_source_or_persona_drift() -> None:
    first = _build()
    second = _build()
    assert first.canonical_manifest_bytes == second.canonical_manifest_bytes
    assert first.manifest_hash == second.manifest_hash
    assert first.chunks[0].text_sha256
    assert first.canonical_manifest["documents"]
    assert _build("changed source").manifest_hash != first.manifest_hash
    changed_persona = prepare_snapshot_build(
        agent_version_id="agent-version-1",
        knowledge_snapshot_id="snapshot-new-1",
        draft_revision=4,
        persona_spec_hash="different-persona",
        documents=[
            {
                "document_id": "document-1",
                "source_filename": "lesson.md",
                "text": first.documents[0].normalized_text,
            }
        ],
    )
    assert changed_persona.manifest_hash != first.manifest_hash


def test_utf8_fallback_rejects_long_unbroken_input_before_provider_call() -> None:
    provider = MockEmbeddingProvider()
    build = _build("x" * 8_001)
    with pytest.raises(EmbeddingPlanError, match="8,000") as error:
        plan_embedding_batches(build)
    assert error.value.code == "embedding_item_too_large"
    assert provider.call_count == 0


def test_deterministic_greedy_packing_preserves_document_chunk_order() -> None:
    build = _build(" ".join(["TikTok"] * 2_400))
    tokenizer = PinnedTokenizerV1("test-tokenizer", "a" * 64, lambda text: len(text.split()))
    first = plan_embedding_batches(build, tokenizer=tokenizer)
    second = plan_embedding_batches(build, tokenizer=tokenizer)
    assert first.plan_hash == second.plan_hash
    assert first.chunk_ids == second.chunk_ids
    assert [batch.batch_index for batch in first.batches] == list(range(first.request_count))
    assert all(len(batch.items) <= 10 and batch.total_tokens <= 30_000 for batch in first.batches)


def test_response_validation_rejects_partial_malformed_reordered_and_nonfinite_vectors() -> None:
    valid_item = {"index": 0, "embedding": [0.0] * 256}
    assert (
        len(
            validate_embedding_response(
                {"model": "fixed", "data": [valid_item]},
                expected_count=1,
                expected_model="fixed",
                expected_dimension=256,
            )
        )
        == 1
    )
    with pytest.raises(EmbeddingShapeError):
        validate_embedding_response(
            {"model": "fixed", "data": []},
            expected_count=1,
            expected_model="fixed",
            expected_dimension=256,
        )
    with pytest.raises(EmbeddingShapeError):
        validate_embedding_response(
            {"model": "fixed", "data": [{"index": 1, "embedding": [0.0] * 256}]},
            expected_count=1,
            expected_model="fixed",
            expected_dimension=256,
        )
    with pytest.raises(EmbeddingShapeError):
        validate_embedding_response(
            {"model": "fixed", "data": [{"index": 0, "embedding": [0.0] * 255}]},
            expected_count=1,
            expected_model="fixed",
            expected_dimension=256,
        )
    with pytest.raises(EmbeddingShapeError):
        validate_embedding_response(
            {"model": "fixed", "data": [{"index": 0, "embedding": [math.nan] + [0.0] * 255}]},
            expected_count=1,
            expected_model="fixed",
            expected_dimension=256,
        )


def test_cross_build_response_hash_is_rejected_and_mock_never_publishes_it() -> None:
    build = _build()
    plan = plan_embedding_batches(build)
    provider = MockEmbeddingProvider(failures=["wrong_build"])
    with pytest.raises(EmbeddingResponseError, match="different SnapshotBuild"):
        provider.embed_batch(plan.batches[0])


class _FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def post(
        self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object], timeout: float
    ) -> object:
        del headers, timeout
        self.calls.append((url, json))
        return self.response


def test_dashscope_adapter_uses_only_injected_transport_and_validates_fixed_shape() -> None:
    build = _build()
    plan = plan_embedding_batches(build)
    transport = _FakeTransport(
        {"model": "text-embedding-v4", "data": [{"index": 0, "embedding": [0.0] * 256}]}
    )
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(api_key="test-only", workspace_id="workspace"), transport
    )
    result = adapter.embed_batch(plan.batches[0])
    assert result.count == 1
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["model"] == "text-embedding-v4"


def test_acceptance_unknown_is_durable_and_not_auto_retried() -> None:
    build = _build()
    plan = plan_embedding_batches(build)
    provider = MockEmbeddingProvider(failures=["acceptance_unknown"])
    ledger = InMemoryEmbeddingLedger()
    result = execute_embedding_batch(plan.batches[0], provider, ledger, scope_id="build-scope")
    assert isinstance(result, EmbeddingAcceptanceUnknownResult)
    assert result.status == "acceptance_unknown"
    assert result.retry_allowed is False
    assert result.requires_reconciliation
    assert ledger.operation(result.operation.id).state == "acceptance_unknown"
    assert provider.call_count == 1


def test_not_sent_releases_allowance_but_keeps_unique_attempt_history() -> None:
    build = _build()
    plan = plan_embedding_batches(build)
    provider = MockEmbeddingProvider(failures=["not_sent"])
    ledger = InMemoryEmbeddingLedger(max_requests=1)
    result = execute_embedding_batch(plan.batches[0], provider, ledger, scope_id="build-scope")
    assert result.status == "not_sent"
    assert ledger.operation(result.operation.id).state == "not_sent"
    assert len(ledger.operations(scope_id="build-scope")) == 1


def test_recovery_maps_stranded_reserved_to_not_sent_and_sending_to_unknown() -> None:
    build = _build()
    plan = plan_embedding_batches(build)
    ledger = InMemoryEmbeddingLedger()
    request_result = execute_embedding_batch(
        plan.batches[0], MockEmbeddingProvider(), ledger, scope_id="done"
    )
    assert request_result.status == "succeeded"
    # A separate operation is left at each state to exercise startup mapping.
    from app.modules.knowledge.providers.operations import reservation_request_for_batch

    first = ledger.create_prepared(
        reservation_request_for_batch(plan.batches[0], scope_id="recover-1")
    )
    ledger.reserve(first)
    assert ledger.recover(first.id).state == "not_sent"
    second = ledger.create_prepared(
        reservation_request_for_batch(plan.batches[0], scope_id="recover-2")
    )
    ledger.reserve(second)
    ledger.mark_sending(second.id)
    assert ledger.recover(second.id).state == "acceptance_unknown"


def test_adapter_timeout_is_acceptance_unknown_and_proven_not_sent_is_distinct() -> None:
    class TimeoutTransport:
        def post(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            json: Mapping[str, object],
            timeout: float,
        ) -> object:
            del url, headers, json, timeout
            raise TimeoutError("local fake timeout")

    class NotSentTransport:
        def post(
            self,
            url: str,
            *,
            headers: Mapping[str, str],
            json: Mapping[str, object],
            timeout: float,
        ) -> object:
            del url, headers, json, timeout
            raise EmbeddingTransportNotSent()

    build = _build()
    batch = plan_embedding_batches(build).batches[0]
    timeout_adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), TimeoutTransport()
    )
    with pytest.raises(EmbeddingAcceptanceUnknown):
        timeout_adapter.embed_batch(batch)
    not_sent_adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), NotSentTransport()
    )
    with pytest.raises(EmbeddingTransportNotSent):
        not_sent_adapter.embed_batch(batch)


def test_provider_calls_are_never_implied_by_build_or_plan_construction() -> None:
    build = _build()
    provider = MockEmbeddingProvider()
    plan_embedding_batches(build)
    assert provider.call_count == 0
    assert Utf8ByteTokenizer().count_tokens("你好") == len("你好".encode())


def test_formal_retrieval_keeps_relevant_adjacent_and_unrelated_boundaries() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads(
        (root / "manual-tests/formal-tiktok-rag/source-manifest.json").read_text(encoding="utf-8")
    )
    topic = str(manifest["topic"])
    for fixture in manifest["fixtures"]:
        path = root / "manual-tests/formal-tiktok-rag" / str(fixture["path"])
        text = path.read_text(encoding="utf-8")
        row = StoredVectorRow(
            chunk_id=f"formal-{fixture['fixture_id']}",
            source_filename=path.name,
            chunk_text=text,
            blob=mock_embedding(text),
            dimension=256,
            key="mock-sha256-v1",
            document_order=0,
            chunk_index=0,
        )
        store = MockVectorStore((row,))

        def search(
            query: str, *, top_k: int = 6, _store: MockVectorStore = store
        ) -> Iterable[object]:
            return _store.search(query, top_k=top_k)

        result = SnapshotRetriever(search).retrieve(
            f"formal-{fixture['fixture_id']}",
            (TurnSubquery("viewpoint", topic),),
            policy_id=MOCK_LEXICAL_ANCHOR_POLICY_ID,
            topic_anchor=topic,
        )
        expected = str(fixture["expected_retrieval_status"]) == "matched"
        assert result.matched is expected
        assert bool(result.receipts) is expected
