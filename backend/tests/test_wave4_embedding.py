"""Focused W4-EMBED contract tests; all provider boundaries are fake/local."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import replace

import pytest
from app.modules.knowledge.markdown import MAX_CHUNK_UTF8_BYTES
from app.modules.knowledge.providers import (
    MAX_BATCH_TOKENS,
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    EmbeddingBatchV1,
    EmbeddingHTTPRejected,
    EmbeddingModelError,
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
    reservation_request_for_batch,
    validate_real_embedding_response,
)
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingAcceptanceUnknown,
    EmbeddingTransportNotSent,
    EmbeddingTransportResponse,
    OpenAICompatibleEmbeddingAdapter,
)
from app.modules.knowledge.providers.embedding import validate_embedding_response
from app.modules.knowledge.providers.operations import (
    EmbeddingAcceptanceUnknownResult,
    execute_embedding_batch,
)


def _build(
    text: str = "TikTok recommendation governance and public safety.",
    *,
    dimension: int = 256,
) -> SnapshotBuildV1:
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
        embedding_model_key=(
            REAL_EMBEDDING_MODEL if dimension == REAL_EMBEDDING_DIMENSION else "mock-sha256-v1"
        ),
        embedding_dimension=dimension,
        embedding_provider=(
            REAL_EMBEDDING_PROVIDER if dimension == REAL_EMBEDDING_DIMENSION else "mock"
        ),
        embedding_region=("cn-beijing" if dimension == REAL_EMBEDDING_DIMENSION else "local"),
        embedding_policy_version=(
            REAL_EMBEDDING_POLICY_VERSION if dimension == REAL_EMBEDDING_DIMENSION else "w4-mock-v1"
        ),
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
        embedding_model_key="mock-sha256-v1",
        embedding_dimension=256,
        embedding_provider="mock",
        embedding_region="local",
        embedding_policy_version="w4-mock-v1",
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


def test_snapshot_chunk_ids_are_stable_per_snapshot_but_not_cross_snapshot() -> None:
    first = _build()
    rebuilt = _build()
    other_snapshot = prepare_snapshot_build(
        agent_version_id=first.agent_version_id,
        knowledge_snapshot_id="snapshot-new-2",
        draft_revision=first.draft_revision,
        persona_spec_hash=first.persona_spec_hash,
        documents=[
            {
                "document_id": "document-1",
                "source_filename": "lesson.md",
                "text": first.documents[0].normalized_text,
            }
        ],
    )

    assert first.chunks[0].chunk_id == rebuilt.chunks[0].chunk_id
    assert first.chunks[0].chunk_id != other_snapshot.chunks[0].chunk_id


def test_long_unbroken_input_is_planned_without_a_per_item_cap() -> None:
    # The owner removed the 8,000-token per-item ceiling, so a long unbroken
    # chunk is planned instead of rejected. Planning still calls no provider.
    provider = MockEmbeddingProvider()
    build = _build("x" * 8_001)
    plan = plan_embedding_batches(build)
    assert [item.token_count for batch in plan.batches for item in batch.items] == [8_001]
    assert provider.call_count == 0


@pytest.mark.parametrize(
    ("source", "expected_tokens"),
    (
        ("x" * 100_001, 100_001),
        ("界" * 100_001, 300_003),
        (("w" * 100 + " ") * 400, 40_400),
        ("prefix" + (" " * 30_000) + "suffix", 15_012),
    ),
    ids=(
        "unbroken-ascii",
        "unbroken-chinese",
        "many-long-space-separated-words",
        "large-whitespace-gap",
    ),
)
def test_oversized_source_splits_losslessly_into_supplier_safe_chunks(
    source: str,
    expected_tokens: int,
) -> None:
    build = _build(source)
    document = build.documents[0]
    chunks = document.chunks

    assert build.chunking_version == "markdown-heading-paragraph-v2"
    assert len(chunks) > 1
    assert document.content_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    previous_end = 0
    reconstructed: list[str] = []
    for index, chunk in enumerate(chunks):
        assert chunk.chunk_index == index
        assert chunk.document_id == document.document_id
        assert chunk.document_order == document.order_index
        assert previous_end <= chunk.start_offset
        whitespace_gap = document.normalized_text[previous_end : chunk.start_offset]
        assert not whitespace_gap.strip()
        reconstructed.extend((whitespace_gap, chunk.text))
        assert chunk.end_offset - chunk.start_offset == len(chunk.text)
        assert document.normalized_text[chunk.start_offset : chunk.end_offset] == chunk.text
        assert chunk.text_sha256 == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert len(chunk.text.encode("utf-8")) <= MAX_CHUNK_UTF8_BYTES
        previous_end = chunk.end_offset
    trailing_whitespace = document.normalized_text[previous_end:]
    assert not trailing_whitespace.strip()
    reconstructed.append(trailing_whitespace)
    assert "".join(reconstructed) == source

    plan = plan_embedding_batches(build)
    assert plan.total_tokens == expected_tokens
    assert plan.chunk_ids == tuple(chunk.chunk_id for chunk in chunks)
    assert all(len(batch.items) <= 10 for batch in plan.batches)
    assert all(batch.total_tokens <= MAX_BATCH_TOKENS for batch in plan.batches)


def test_planner_refuses_a_single_estimated_item_over_supplier_batch_cap() -> None:
    build = _build()
    original_chunk_ids = tuple(chunk.chunk_id for chunk in build.chunks)
    tokenizer = PinnedTokenizerV1(
        "oversized-item-test",
        "b" * 64,
        lambda _text: MAX_BATCH_TOKENS + 1,
    )
    with pytest.raises(EmbeddingPlanError) as caught:
        plan_embedding_batches(build, tokenizer=tokenizer)
    assert caught.value.code == "embedding_item_tokens_exceeded"
    assert tuple(chunk.chunk_id for chunk in build.chunks) == original_chunk_ids


def test_adapter_refuses_oversized_batch_before_transport() -> None:
    batch = plan_embedding_batches(_build(dimension=REAL_EMBEDDING_DIMENSION)).batches[0]
    oversized_item = replace(batch.items[0], token_count=MAX_BATCH_TOKENS + 1)
    oversized_batch = replace(
        batch,
        items=(oversized_item,),
        total_tokens=MAX_BATCH_TOKENS + 1,
    )
    transport = _FakeTransport({})
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )

    with pytest.raises(EmbeddingPlanError) as caught:
        adapter.embed_batch(oversized_batch)

    assert caught.value.code == "embedding_batch_tokens_exceeded"
    assert transport.calls == []


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
    build = _build(dimension=1024)
    plan = plan_embedding_batches(build)
    transport = _FakeTransport(
        {"model": "text-embedding-v4", "data": [{"index": 0, "embedding": [0.0] * 1024}]}
    )
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(api_key="test-only", workspace_id="workspace"), transport
    )
    result = adapter.embed_batch(plan.batches[0])
    assert result.count == 1
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["model"] == "text-embedding-v4"


def _real_three_item_batch() -> EmbeddingBatchV1:
    build = replace(
        _manual_build(3),
        embedding_model_key=REAL_EMBEDDING_MODEL,
        embedding_dimension=REAL_EMBEDDING_DIMENSION,
        embedding_provider=REAL_EMBEDDING_PROVIDER,
        embedding_region="cn-beijing",
        embedding_policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )
    return plan_embedding_batches(build).batches[0]


def _native_dashscope_response(
    batch: EmbeddingBatchV1,
    *,
    model: str | None = None,
    nested_model: str | None = None,
    vectors: list[list[float]] | None = None,
    text_indices: list[int] | None = None,
) -> dict[str, object]:
    values = vectors or [[0.0] * REAL_EMBEDDING_DIMENSION for _ in batch.items]
    indices = text_indices or list(range(len(batch.items)))
    output: dict[str, object] = {
        "embeddings": [
            {"text_index": index, "embedding": vector}
            for index, vector in zip(indices, values, strict=False)
        ]
    }
    if nested_model is not None:
        output["model"] = nested_model
    response: dict[str, object] = {
        "request_id": "request-fixture",
        "code": "",
        "message": "",
        "output": output,
        "usage": {"total_tokens": batch.total_tokens},
    }
    if model is not None:
        response["model"] = model
    return response


def test_dashscope_native_response_without_model_accepts_three_1024_items() -> None:
    batch = _real_three_item_batch()
    transport = _FakeTransport(_native_dashscope_response(batch))
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )

    result = adapter.embed_batch(batch)

    assert result.count == 3
    assert all(len(vector) == REAL_EMBEDDING_DIMENSION for vector in result.vectors)
    assert transport.calls[0][1]["model"] == REAL_EMBEDDING_MODEL
    assert transport.calls[0][1]["parameters"] == {"dimension": REAL_EMBEDDING_DIMENSION}


def test_dashscope_native_explicit_wrong_model_is_rejected() -> None:
    batch = _real_three_item_batch()
    transport = _FakeTransport(_native_dashscope_response(batch, model="wrong-model"))
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )

    with pytest.raises(EmbeddingModelError) as error:
        adapter.embed_batch(batch)
    assert error.value.code == "embedding_model_mismatch"


@pytest.mark.parametrize(
    ("model", "nested_model", "accepted"),
    (
        (REAL_EMBEDDING_MODEL, "wrong-model", False),
        ("wrong-model", REAL_EMBEDDING_MODEL, False),
        (REAL_EMBEDDING_MODEL, REAL_EMBEDDING_MODEL, True),
        (None, "wrong-model", False),
        (None, REAL_EMBEDDING_MODEL, True),
    ),
    ids=(
        "top-correct-nested-wrong",
        "top-wrong-nested-correct",
        "both-correct",
        "nested-only-wrong",
        "nested-only-correct",
    ),
)
def test_dashscope_native_all_explicit_model_fields_must_match(
    model: str | None,
    nested_model: str | None,
    accepted: bool,
) -> None:
    batch = _real_three_item_batch()
    transport = _FakeTransport(
        _native_dashscope_response(batch, model=model, nested_model=nested_model)
    )
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )

    if accepted:
        assert adapter.embed_batch(batch).count == 3
    else:
        with pytest.raises(EmbeddingModelError) as error:
            adapter.embed_batch(batch)
        assert error.value.code == "embedding_model_mismatch"


def test_dashscope_native_data_envelope_without_model_is_rejected() -> None:
    batch = _real_three_item_batch()
    transport = _FakeTransport(
        {
            "data": [
                {"index": index, "embedding": [0.0] * REAL_EMBEDDING_DIMENSION}
                for index in range(3)
            ]
        }
    )
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )

    with pytest.raises(EmbeddingModelError) as error:
        adapter.embed_batch(batch)
    assert error.value.code == "embedding_model_mismatch"


def test_generic_missing_model_is_rejected_even_with_valid_data() -> None:
    batch = _real_three_item_batch()
    transport = _FakeTransport(
        {
            "data": [
                {"index": index, "embedding": [0.0] * REAL_EMBEDDING_DIMENSION}
                for index in range(3)
            ]
        }
    )
    adapter = OpenAICompatibleEmbeddingAdapter(
        transport,
        endpoint="https://example.invalid/embeddings",
        model_key=REAL_EMBEDDING_MODEL,
        dimension=REAL_EMBEDDING_DIMENSION,
        policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )

    with pytest.raises(EmbeddingModelError) as error:
        adapter.embed_batch(batch)
    assert error.value.code == "embedding_model_mismatch"


def test_dashscope_native_shape_checks_remain_fail_closed() -> None:
    batch = _real_three_item_batch()
    cases = (
        _native_dashscope_response(batch, vectors=[[0.0] * REAL_EMBEDDING_DIMENSION] * 2),
        _native_dashscope_response(batch, text_indices=[0, 2, 1]),
        _native_dashscope_response(
            batch,
            vectors=[
                [0.0] * (REAL_EMBEDDING_DIMENSION - 1),
                [0.0] * REAL_EMBEDDING_DIMENSION,
                [0.0] * REAL_EMBEDDING_DIMENSION,
            ],
        ),
        _native_dashscope_response(
            batch,
            vectors=[
                [float("nan")] + [0.0] * (REAL_EMBEDDING_DIMENSION - 1),
                [0.0] * REAL_EMBEDDING_DIMENSION,
                [0.0] * REAL_EMBEDDING_DIMENSION,
            ],
        ),
    )
    for response in cases:
        adapter = DashScopeEmbeddingAdapter(
            DashScopeEmbeddingConfig(workspace_id="workspace"), _FakeTransport(response)
        )
        with pytest.raises(EmbeddingShapeError):
            adapter.embed_batch(batch)


def test_real_dashscope_payload_pins_dimension_and_request_hash_without_key() -> None:
    build = _build(dimension=REAL_EMBEDDING_DIMENSION)
    plan = plan_embedding_batches(build)
    transport = _FakeTransport(
        {
            "model": REAL_EMBEDDING_MODEL,
            "data": [{"index": 0, "embedding": [0.0] * REAL_EMBEDDING_DIMENSION}],
        }
    )
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(
            api_key="fixture-secret-that-must-not-enter-json",
            workspace_id="workspace",
        ),
        transport,
    )

    result = adapter.embed_batch(plan.batches[0])
    request = reservation_request_for_batch(plan.batches[0], scope_id="real-scope")
    payload = transport.calls[0][1]

    assert result.dimension == REAL_EMBEDDING_DIMENSION
    assert result.policy_version == REAL_EMBEDDING_POLICY_VERSION
    assert plan.policy_version == REAL_EMBEDDING_POLICY_VERSION
    assert plan.batches[0].as_record()["dimension"] == REAL_EMBEDDING_DIMENSION
    assert plan.batches[0].as_record()["policy_version"] == REAL_EMBEDDING_POLICY_VERSION
    assert len(request.request_hash) == 64
    assert plan.plan_hash == plan_embedding_batches(build).plan_hash
    assert payload["parameters"] == {"dimension": REAL_EMBEDDING_DIMENSION}
    assert "api_key" not in payload
    assert "authorization" not in payload


@pytest.mark.parametrize("dimension", [256, 768, 1023, 1025])
def test_real_validator_rejects_every_non_1024_dimension(dimension: int) -> None:
    with pytest.raises(EmbeddingShapeError):
        validate_real_embedding_response(
            {
                "model": REAL_EMBEDDING_MODEL,
                "data": [{"index": 0, "embedding": [0.0] * dimension}],
            },
            expected_count=1,
        )


@pytest.mark.parametrize(
    "value",
    [
        "not-a-vector",
        [0.0] * 1023,
        ["not-a-number"] * REAL_EMBEDDING_DIMENSION,
        [float("nan")] + [0.0] * 1023,
        [float("inf")] + [0.0] * 1023,
    ],
)
def test_real_validator_rejects_non_numeric_nonfinite_or_malformed_vectors(value: object) -> None:
    with pytest.raises(EmbeddingShapeError):
        validate_real_embedding_response(
            {"model": REAL_EMBEDDING_MODEL, "data": [{"index": 0, "embedding": value}]},
            expected_count=1,
        )


@pytest.mark.parametrize("status_code", [429, 500])
def test_dashscope_http_rejection_is_explicit_and_never_retried(status_code: int) -> None:
    build = _build(dimension=REAL_EMBEDDING_DIMENSION)
    batch = plan_embedding_batches(build).batches[0]
    transport = _FakeTransport(EmbeddingTransportResponse(status_code, {"error": "redacted"}))
    adapter = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport,
    )

    with pytest.raises(EmbeddingHTTPRejected) as error:
        adapter.embed_batch(batch)
    assert error.value.status_code == status_code
    assert error.value.code == "provider_http_rejected"
    assert len(transport.calls) == 1


def test_mock_embedding_contract_remains_256_and_mock_key() -> None:
    build = _build()
    batch = plan_embedding_batches(build).batches[0]
    provider = MockEmbeddingProvider()

    result = provider.embed_batch(batch)

    assert provider.key == "mock-sha256-v1"
    assert result.dimension == 256
    assert result.policy_version == "w4-mock-v1"
    assert all(len(vector) == 256 for vector in result.vectors)


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

    build = _build(dimension=1024)
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
