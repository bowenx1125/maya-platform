"""Focused W4-EMBED runtime tests; every transport is local and injected."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

import pytest
from app.modules.knowledge.providers import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
    EmbeddingPlanError,
    InMemoryEmbeddingLedger,
    MockEmbeddingProvider,
    PinnedTokenizerV1,
    SnapshotBuildChunkV1,
    SnapshotBuildDocumentV1,
    SnapshotBuildV1,
    plan_embedding_batches,
    prepare_snapshot_build,
)
from app.modules.knowledge.providers.adapters import (
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportNotSent,
)
from app.modules.knowledge.providers.operations import EmbeddingOperationV1
from app.modules.knowledge.providers.runtime import (
    AcceptedEmbeddingStageV1,
    InMemoryEmbeddingStageStore,
    InMemorySnapshotPublicationStore,
    SnapshotBuildDriftError,
    SnapshotEmbeddingRuntime,
    SnapshotEmbeddingRuntimeError,
    SnapshotPublicationError,
    SnapshotPublicationPort,
    _reservation_request,
    _response_hash,
)


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
        embedding_model_key=REAL_EMBEDDING_MODEL,
        embedding_dimension=REAL_EMBEDDING_DIMENSION,
        embedding_provider=REAL_EMBEDDING_PROVIDER,
        embedding_region=REAL_EMBEDDING_REGION,
        embedding_policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )


def _multi_batch_build(chunk_count: int = 11) -> SnapshotBuildV1:
    chunks = tuple(
        SnapshotBuildChunkV1(
            chunk_id=f"chunk-{index}",
            document_id="document-1",
            document_order=0,
            chunk_index=index,
            text="one",
            start_offset=index * 3,
            end_offset=index * 3 + 3,
        )
        for index in range(chunk_count)
    )
    document = SnapshotBuildDocumentV1(
        document_id="document-1",
        source_filename="lesson.md",
        order_index=0,
        normalized_text=" ".join("one" for _ in range(chunk_count)),
        chunks=chunks,
    )
    return SnapshotBuildV1(
        build_id="build-multi",
        agent_version_id="agent-version-1",
        knowledge_snapshot_id="snapshot-multi",
        draft_revision=1,
        persona_spec_hash="persona-hash",
        documents=(document,),
        embedding_model_key=REAL_EMBEDDING_MODEL,
        embedding_dimension=REAL_EMBEDDING_DIMENSION,
        embedding_provider=REAL_EMBEDDING_PROVIDER,
        embedding_region=REAL_EMBEDDING_REGION,
        embedding_policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )


class _Transport:
    def __init__(self, *, failure: str | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        del headers, timeout
        self.calls.append((url, json))
        if self.failure == "not_sent":
            raise EmbeddingTransportNotSent()
        if self.failure == "unknown":
            raise TimeoutError("local fake timeout")
        values = json.get("input")
        if isinstance(values, Mapping):
            texts = values.get("texts")
        else:
            texts = values
        if not isinstance(texts, list):
            raise AssertionError("runtime sent an invalid input envelope")
        data = [{"index": index, "embedding": [0.0] * 1024} for index, _ in enumerate(texts)]
        if self.failure == "wrong_model":
            return {"model": "different-model", "data": data}
        if self.failure == "short":
            return {"model": "text-embedding-v4", "data": data[:-1]}
        if self.failure == "reordered":
            return {
                "model": "text-embedding-v4",
                "data": [
                    {
                        "index": cast(int, item["index"]) + 1,
                        "embedding": cast(list[object], item["embedding"]),
                    }
                    for item in data
                ],
            }
        if self.failure == "wrong_dimension":
            return {
                "model": "text-embedding-v4",
                "data": [
                    {
                        "index": cast(int, item["index"]),
                        "embedding": cast(list[object], item["embedding"])[:-1],
                    }
                    for item in data
                ],
            }
        if self.failure == "nonfinite":
            cast(list[object], data[0]["embedding"])[0] = float("nan")
        return {"model": "text-embedding-v4", "data": data}


class _SecondBatchNotSentTransport:
    """Accept the first planned batch, then prove the second was not sent."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> object:
        del headers, timeout
        self.calls.append((url, json))
        values = json.get("input")
        texts = values.get("texts") if isinstance(values, Mapping) else values
        if not isinstance(texts, list):
            raise AssertionError("runtime sent an invalid input envelope")
        if len(self.calls) == 2:
            raise EmbeddingTransportNotSent()
        return {
            "model": "text-embedding-v4",
            "data": [{"index": index, "embedding": [0.0] * 1024} for index, _ in enumerate(texts)],
        }


class _CountingPublisher(InMemorySnapshotPublicationStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def publish_atomic(
        self,
        candidate: object,
        *,
        operation_ids: tuple[str, ...] = (),
    ) -> object:
        self.calls += 1
        return super().publish_atomic(cast(Any, candidate), operation_ids=operation_ids)


@dataclass
class _BadResponseProvider:
    model_key: str = "text-embedding-v4"
    dimension: int = 1024

    def embed_batch(self, batch: Any) -> object:
        del batch
        return {"not": "validated"}


class _FailingPublisher:
    def publish_atomic(self, candidate: object) -> object:
        del candidate
        raise SnapshotPublicationError()


def _runtime(
    build: SnapshotBuildV1,
    *,
    transport: _Transport | None = None,
    control: InMemoryEmbeddingLedger | None = None,
    publisher: SnapshotPublicationPort | None = None,
    stage_store: InMemoryEmbeddingStageStore | None = None,
) -> tuple[SnapshotEmbeddingRuntime, _Transport, InMemoryEmbeddingLedger, SnapshotPublicationPort]:
    wire = transport or _Transport()
    ledger = control or InMemoryEmbeddingLedger()
    destination = publisher or InMemorySnapshotPublicationStore()
    runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=ledger,
        publisher=destination,
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=wire,
        stage_store=stage_store,
    )
    del build
    return runtime, wire, ledger, destination


def _accepted_stage_fixture(
    build: SnapshotBuildV1,
) -> tuple[
    InMemoryEmbeddingLedger,
    InMemoryEmbeddingStageStore,
    tuple[EmbeddingOperationV1, ...],
    AcceptedEmbeddingStageV1,
]:
    control = InMemoryEmbeddingLedger()
    stage_store = InMemoryEmbeddingStageStore()
    transport = _Transport()
    provider = DashScopeEmbeddingAdapter(
        DashScopeEmbeddingConfig(workspace_id="workspace"), transport
    )
    batch = plan_embedding_batches(build).batches[0]
    request = _reservation_request(
        batch,
        scope_id="resume-scope",
        attempt_no=1,
        provider_operation="embedding_snapshot",
        price_cny_per_million=0.5,
    )
    operation = control.create_prepared(request)
    control.reserve(operation)
    operation = control.mark_sending(operation.id)
    result = provider.embed_batch(batch)
    stage = AcceptedEmbeddingStageV1.from_result(
        operation.id,
        result,
        response_hash=_response_hash(result),
    )
    stage_store.bind_control(control)
    stage_store.stage_accepted(stage)
    current = control.get(operation.id)
    assert current is not None
    return control, stage_store, (current,), stage


def test_runtime_orders_reserve_send_stage_accept_publish_and_succeed() -> None:
    build = _build()
    stage_store = InMemoryEmbeddingStageStore()
    runtime, transport, ledger, publisher = _runtime(build, stage_store=stage_store)

    result = runtime.run(build, scope_id="snapshot-scope", current_build=build)

    assert result.succeeded
    assert result.snapshot_id == build.knowledge_snapshot_id
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["parameters"] == {"dimension": 1024}
    assert len(result.operations) == 1
    assert result.operations[0].state == "succeeded"
    assert result.operations[0].reservation_id is not None
    assert len(stage_store.values()) == 1
    candidate = publisher.get(build.knowledge_snapshot_id)  # type: ignore[attr-defined]
    assert candidate is not None
    assert len(candidate.vectors) == len(build.chunks)
    assert ledger.operation(result.operations[0].id).state == "succeeded"


def test_runtime_handles_multiple_batches_in_stable_order() -> None:
    build = _multi_batch_build()
    runtime, transport, _, _ = _runtime(build)
    tokenizer = PinnedTokenizerV1("test", "a" * 64, lambda _: 1)
    runtime.tokenizer = tokenizer

    result = runtime.run(build, scope_id="multi-scope", current_build=build)

    assert result.status == "succeeded"
    assert [call[1]["input"]["texts"] for call in transport.calls] == [  # type: ignore[index]
        ["one"] * 10,
        ["one"],
    ]
    assert [item.batch_index for item in result.outcomes] == [0, 1]
    assert [item.status for item in result.outcomes] == ["succeeded", "succeeded"]


def test_scope_cap_failure_for_later_batch_happens_before_any_provider_call() -> None:
    build = _multi_batch_build()
    control = InMemoryEmbeddingLedger(max_requests=1)
    runtime, transport, ledger, publisher = _runtime(build, control=control)
    runtime.tokenizer = PinnedTokenizerV1("test", "a" * 64, lambda _: 1)

    result = runtime.run(build, scope_id="plan-cap", current_build=build)

    assert result.status == "failed"
    assert result.safe_error_code == "embedding_reservation_failed"
    assert transport.calls == []
    assert [item.state for item in result.operations] == ["not_sent", "failed"]
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]
    assert all(item.state in {"not_sent", "failed"} for item in ledger.operations())


def test_source_or_persona_drift_stops_before_control_or_provider() -> None:
    build = _build()
    changed_source = _build("changed source")
    runtime, transport, ledger, publisher = _runtime(build)

    with pytest.raises(SnapshotBuildDriftError):
        runtime.run(build, scope_id="drift-scope", current_build=changed_source)
    with pytest.raises(SnapshotBuildDriftError):
        runtime.run(
            build,
            scope_id="drift-scope-persona",
            current_persona_spec_hash="other-persona",
        )
    assert transport.calls == []
    assert ledger.operations() == ()
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]


def test_current_documents_rebuild_catches_source_drift_before_provider() -> None:
    build = _build()
    runtime, transport, ledger, _ = _runtime(build)

    with pytest.raises(SnapshotBuildDriftError):
        runtime.run(
            build,
            scope_id="documents-drift",
            current_documents=[
                {
                    "document_id": "document-1",
                    "source_filename": "lesson.md",
                    "text": "changed source",
                }
            ],
            current_persona_spec_hash=build.persona_spec_hash,
        )
    assert transport.calls == []
    assert ledger.operations() == ()


def test_final_current_input_check_blocks_publication_after_runtime_drift() -> None:
    build = _build()
    runtime, transport, ledger, publisher = _runtime(build)
    checks = 0

    def verifier(_: SnapshotBuildV1) -> object:
        nonlocal checks
        checks += 1
        return checks <= 2

    result = runtime.run(
        build,
        scope_id="late-drift",
        current_build_verifier=verifier,
    )

    assert result.status == "failed"
    assert result.safe_error_code == "snapshot_build_drift"
    assert checks == 3
    assert len(transport.calls) == 1
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]
    assert ledger.operation(result.operations[0].id).state == "failed"


def test_long_unbroken_input_fails_plan_with_zero_control_or_provider_calls() -> None:
    build = _build("x" * 8_001)
    runtime, transport, ledger, _ = _runtime(build)

    with pytest.raises(EmbeddingPlanError, match="8,000"):
        runtime.run(build, scope_id="long-scope")
    assert transport.calls == []
    assert ledger.operations() == ()


def test_not_sent_releases_and_allows_explicit_next_attempt_but_no_auto_retry() -> None:
    build = _build()
    control = InMemoryEmbeddingLedger(max_requests=1)
    transport = _Transport(failure="not_sent")
    publisher = InMemorySnapshotPublicationStore()
    runtime, _, _, _ = _runtime(build, transport=transport, control=control, publisher=publisher)
    first = runtime.run(build, scope_id="retry-scope", attempt_no=1)
    assert first.status == "not_sent"
    assert first.retry_allowed
    assert first.operations[0].state == "not_sent"
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]

    succeeding_transport = _Transport()
    succeeding_runtime, _, _, _ = _runtime(
        build,
        transport=succeeding_transport,
        control=control,
        publisher=publisher,
    )
    second = succeeding_runtime.run(build, scope_id="retry-scope", attempt_no=2)
    assert second.status == "succeeded"
    assert len(succeeding_transport.calls) == 1


def test_acceptance_unknown_retains_allowance_and_never_retries() -> None:
    build = _build()
    control = InMemoryEmbeddingLedger(max_requests=1)
    unknown_transport = _Transport(failure="unknown")
    publisher = InMemorySnapshotPublicationStore()
    runtime, _, _, _ = _runtime(
        build, transport=unknown_transport, control=control, publisher=publisher
    )
    first = runtime.run(build, scope_id="unknown-scope", attempt_no=1)
    assert first.status == "acceptance_unknown"
    assert first.retry_allowed is False
    assert first.operations[0].state == "acceptance_unknown"
    second_transport = _Transport()
    second_runtime, _, _, _ = _runtime(
        build,
        transport=second_transport,
        control=control,
        publisher=publisher,
    )
    second = second_runtime.run(build, scope_id="unknown-scope", attempt_no=2)
    assert second.status == "failed"
    assert second.safe_error_code == "embedding_reservation_failed"
    assert second_transport.calls == []


def test_malformed_result_is_failed_and_never_published() -> None:
    build = _build()
    control = InMemoryEmbeddingLedger()
    publisher = InMemorySnapshotPublicationStore()
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=cast(Any, _BadResponseProvider()),
        publisher=publisher,
    )

    result = runtime.run(build, scope_id="malformed-scope")

    assert result.status == "failed"
    assert result.safe_error_code == "embedding_result_invalid"
    assert result.operations[0].state == "failed"
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "failure",
    ["wrong_model", "short", "reordered", "wrong_dimension", "nonfinite"],
)
def test_response_shape_failures_are_recorded_without_publication(failure: str) -> None:
    build = _build()
    transport = _Transport(failure=failure)
    runtime, _, _, publisher = _runtime(build, transport=transport)

    result = runtime.run(build, scope_id=f"response-{failure}")

    assert result.status == "failed"
    assert result.operations[0].state == "failed"
    assert len(transport.calls) == 1
    assert publisher.published_snapshot_ids == ()  # type: ignore[attr-defined]


def test_publication_failure_marks_accepted_operations_failed_without_new_snapshot() -> None:
    build = _build()
    runtime, transport, ledger, _ = _runtime(
        build,
        publisher=_FailingPublisher(),
    )

    result = runtime.run(build, scope_id="publish-failure")

    assert result.status == "failed"
    assert result.safe_error_code == "snapshot_publication_failed"
    assert len(transport.calls) == 1
    assert result.operations[0].state == "failed"
    assert ledger.operation(result.operations[0].id).state == "failed"


def test_fixed_resource_and_existing_snapshot_are_checked_before_provider_call() -> None:
    build = _build()
    runtime, transport, ledger, publisher = _runtime(build)

    with pytest.raises(SnapshotEmbeddingRuntimeError, match="fixed"):
        bad_provider = MockEmbeddingProvider(model_key="different-model")
        SnapshotEmbeddingRuntime(
            control=ledger,
            provider=bad_provider,
            publisher=publisher,
        ).run(build, scope_id="fixed-provider")

    with pytest.raises(SnapshotPublicationError):
        runtime.run(
            build,
            scope_id="existing-snapshot",
            existing_snapshot_ids=(build.knowledge_snapshot_id,),
        )
    assert transport.calls == []
    assert ledger.operations() == ()


def test_dashscope_config_rejects_non_workspace_endpoint_before_transport() -> None:
    with pytest.raises(SnapshotEmbeddingRuntimeError, match="endpoint"):
        SnapshotEmbeddingRuntime.with_dashscope(
            control=InMemoryEmbeddingLedger(),
            publisher=InMemorySnapshotPublicationStore(),
            config=DashScopeEmbeddingConfig(
                workspace_id="workspace",
                endpoint="https://evil.example/embedding",
            ),
            transport=_Transport(),
        )


def test_runtime_keeps_existing_mock_snapshot_path_at_256_dimensions() -> None:
    build = prepare_snapshot_build(
        agent_version_id="mock-agent-version",
        knowledge_snapshot_id="mock-snapshot",
        draft_revision=1,
        persona_spec_hash="mock-persona",
        documents=[
            {
                "document_id": "mock-document",
                "source_filename": "lesson.md",
                "text": "Existing Mock snapshot content.",
            }
        ],
    )
    provider = MockEmbeddingProvider()
    runtime = SnapshotEmbeddingRuntime(
        control=InMemoryEmbeddingLedger(),
        provider=provider,
        publisher=InMemorySnapshotPublicationStore(),
    )

    result = runtime.run(build, scope_id="mock-runtime")

    assert result.status == "succeeded"
    assert build.embedding_dimension == 256
    assert result.plan.dimension == 256
    assert provider.call_count == 1


def test_resume_from_complete_stages_publishes_without_provider_call() -> None:
    build = _build()
    control, stage_store, operations, stage = _accepted_stage_fixture(build)
    publisher = InMemorySnapshotPublicationStore()
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=_BadResponseProvider(),
        publisher=publisher,
        stage_store=stage_store,
    )

    result = runtime.resume_from_stages(
        build,
        operations=operations,
        stages=(stage,),
        scope_id="resume-scope",
    )

    assert result.status == "succeeded"
    assert publisher.get(build.knowledge_snapshot_id) is not None
    assert result.operations[0].state == "succeeded"


def test_resume_from_missing_or_corrupt_stage_is_unknown_and_never_published() -> None:
    build = _build()
    control, stage_store, operations, stage = _accepted_stage_fixture(build)
    publisher = InMemorySnapshotPublicationStore()
    runtime = SnapshotEmbeddingRuntime(
        control=control,
        provider=_BadResponseProvider(),
        publisher=publisher,
        stage_store=stage_store,
    )

    missing = runtime.resume_from_stages(
        build,
        operations=operations,
        stages=(),
        scope_id="resume-scope",
    )
    assert missing.status == "acceptance_unknown"
    assert missing.safe_error_code == "embedding_stage_missing"
    assert publisher.published_snapshot_ids == ()

    # Use an independent accepted operation so the first unknown transition
    # does not mask the corrupt-stage check.
    control2, stage_store2, operations2, stage2 = _accepted_stage_fixture(build)
    object.__setattr__(stage2, "dimension", 256)
    corrupt_runtime = SnapshotEmbeddingRuntime(
        control=control2,
        provider=_BadResponseProvider(),
        publisher=InMemorySnapshotPublicationStore(),
        stage_store=stage_store2,
    )
    corrupt = corrupt_runtime.resume_from_stages(
        build,
        operations=operations2,
        stages=(stage2,),
        scope_id="resume-scope",
    )
    assert corrupt.status == "acceptance_unknown"
    assert corrupt.safe_error_code == "embedding_stage_invalid"


def test_continuation_reuses_accepted_batch_and_sends_only_missing_next_attempt() -> None:
    build = _multi_batch_build()
    tokenizer = PinnedTokenizerV1("test", "a" * 64, lambda _: 1)
    control = InMemoryEmbeddingLedger(max_requests=2)
    stage_store = InMemoryEmbeddingStageStore()
    publisher = _CountingPublisher()
    first_transport = _SecondBatchNotSentTransport()
    first_runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=control,
        publisher=publisher,
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=first_transport,
        stage_store=stage_store,
        tokenizer=tokenizer,
    )

    first = first_runtime.run(build, scope_id="continuation-scope", current_build=build)

    assert first.status == "not_sent"
    assert [item.operation.state for item in first.outcomes] == ["accepted", "not_sent"]
    assert len(first_transport.calls) == 2
    assert len(stage_store.values()) == 1

    second_transport = _Transport()
    second_runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=control,
        publisher=publisher,
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=second_transport,
        stage_store=stage_store,
        tokenizer=tokenizer,
    )
    second = second_runtime.continue_from_stages(
        build,
        scope_id="continuation-scope",
        operations=first.operations,
        plan=first.plan,
        current_build=build,
    )

    assert second.status == "succeeded"
    assert len(second_transport.calls) == 1
    assert second_transport.calls[0][1]["input"]["texts"] == ["one"]  # type: ignore[index]
    assert publisher.calls == 1
    assert [item.status for item in second.outcomes] == ["succeeded", "succeeded"]
    assert [item.operation.attempt_no for item in second.outcomes] == [1, 2]
    history = control.operations(scope_id="continuation-scope")
    assert len(history) == 3
    initial_missing = next(item for item in first.operations if item.logical_item_id == "batch-1")
    retry = next(
        item for item in history if item.logical_item_id == "batch-1" and item.attempt_no == 2
    )
    assert retry.request_hash == initial_missing.request_hash
    assert len(stage_store.values()) == 2
    candidate = publisher.get(build.knowledge_snapshot_id)
    assert candidate is not None
    assert candidate.chunk_ids == tuple(chunk.chunk_id for chunk in build.chunks)

    repeated = second_runtime.continue_from_stages(
        build,
        scope_id="continuation-scope",
        operations=second.operations,
        plan=second.plan,
        current_build=build,
    )
    assert repeated.status == "succeeded"
    assert len(second_transport.calls) == 1
    assert publisher.calls == 1
    assert len(control.operations(scope_id="continuation-scope")) == 3


def test_continuation_unknown_or_request_mismatch_fails_before_provider_call() -> None:
    build = _multi_batch_build()
    tokenizer = PinnedTokenizerV1("test", "a" * 64, lambda _: 1)
    control = InMemoryEmbeddingLedger(max_requests=2)
    stage_store = InMemoryEmbeddingStageStore()
    publisher = _CountingPublisher()
    first_transport = _SecondBatchNotSentTransport()
    first_runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=control,
        publisher=publisher,
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=first_transport,
        stage_store=stage_store,
        tokenizer=tokenizer,
    )
    first = first_runtime.run(build, scope_id="fail-closed-scope", current_build=build)
    assert first.status == "not_sent"

    control.mark_acceptance_unknown(first.operations[0].id)
    unknown_transport = _Transport()
    unknown_runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=control,
        publisher=publisher,
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=unknown_transport,
        stage_store=stage_store,
        tokenizer=tokenizer,
    )
    unknown = unknown_runtime.continue_from_stages(
        build,
        scope_id="fail-closed-scope",
        operations=first.operations,
        plan=first.plan,
    )
    assert unknown.status == "acceptance_unknown"
    assert unknown_transport.calls == []

    # A separate ledger keeps the request-mismatch assertion independent from
    # the unknown transition above.
    control2 = InMemoryEmbeddingLedger(max_requests=2)
    stage_store2 = InMemoryEmbeddingStageStore()
    first_runtime2 = SnapshotEmbeddingRuntime.with_dashscope(
        control=control2,
        publisher=InMemorySnapshotPublicationStore(),
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=_SecondBatchNotSentTransport(),
        stage_store=stage_store2,
        tokenizer=tokenizer,
    )
    partial = first_runtime2.run(build, scope_id="hash-fail-scope", current_build=build)
    bad_operations = tuple(
        replace(operation, request_hash="0" * 64)
        if operation.logical_item_id == "batch-1"
        else operation
        for operation in partial.operations
    )
    mismatch_transport = _Transport()
    mismatch_runtime = SnapshotEmbeddingRuntime.with_dashscope(
        control=control2,
        publisher=InMemorySnapshotPublicationStore(),
        config=DashScopeEmbeddingConfig(workspace_id="workspace"),
        transport=mismatch_transport,
        stage_store=stage_store2,
        tokenizer=tokenizer,
    )
    mismatch = mismatch_runtime.continue_from_stages(
        build,
        scope_id="hash-fail-scope",
        operations=bad_operations,
        plan=partial.plan,
    )
    assert mismatch.status == "acceptance_unknown"
    assert mismatch_transport.calls == []
