"""Focused provider-neutral LLM-A runtime and product-path tests."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.modules.agents.persona import compile_persona_or_raise, persona_spec_hash
from app.modules.debates.generation import (
    GenerationContext,
    LLMRecoveryService,
    LLMTurnRuntime,
    MutualLearningPolicy,
    ParticipantContext,
    SnapshotRetriever,
    TurnGenerationService,
    build_provider_prompt,
)
from app.modules.debates.generation.prompt_request import PromptMessageV1, ProviderPromptV1
from app.modules.provider_disclosure import (
    InMemoryProviderDisclosureStore,
    ProviderDataCallDebateManifestListResponseV1,
    ProviderDisclosureError,
    ProviderDisclosureService,
)
from app.providers.control import (
    FIXED_MODELS,
    LLM_DEBATE_TURN_BUCKET,
    REPAIR_FEEDBACK_POLICY_HASH,
    REPAIR_FEEDBACK_POLICY_VERSION,
    ExportFieldV1,
    ExportManifestV1,
    InMemoryProviderOperationRepository,
    ProviderPolicySnapshotV1,
    ProviderScopeBudgetV1,
)
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import (
    LLMRequestV1,
    LLMUsageV1,
    LLMValidatedResultV1,
)
from app.providers.llm_output import MappedLLMTurnV1
from app.providers.llm_transport import LLMAcceptanceUnknown


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disclosure_policy() -> ProviderPolicySnapshotV1:
    return ProviderPolicySnapshotV1(
        privacy_notice_retrieved_at="2026-08-30T00:00:00Z",
        privacy_notice_sha256=_hash("privacy"),
        service_terms_retrieved_at="2026-08-30T00:00:00Z",
        service_terms_sha256=_hash("terms"),
        faq_retrieved_at="2026-08-30T00:00:00Z",
        faq_sha256=_hash("faq"),
        no_training_basis="payg-api-terms-2026-08-30",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def _llm_manifest(policy: ProviderPolicySnapshotV1) -> ExportManifestV1:
    return ExportManifestV1(
        scope_id="debate-runtime",
        provider_operation="llm_debate_turn",
        model_key=FIXED_MODELS["llm_debate_turn"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_hash("build"),
        persona_spec_hash=_hash("persona"),
        fields=tuple(
            ExportFieldV1(field_class, _hash(field_class))
            for field_class in (
                "topic_and_platform_rules",
                "confirmed_structured_persona",
                "public_predecessor_speech",
                "current_evidence_excerpt",
                "opaque_local_id",
                "server_authored_structure_repair_feedback",
            )
        ),
        debate_id="debate-runtime",
        turn_id="turn-0",
        max_attempts=2,
        max_total_tokens=120_000,
        max_cost_cny=1.2,
        repair_policy_version=REPAIR_FEEDBACK_POLICY_VERSION,
        repair_policy_hash=REPAIR_FEEDBACK_POLICY_HASH,
    )


def _persona():
    return compile_persona_or_raise(
        """# River Keeper

## Identity

- Role: Watershed steward
- Historical or cultural context: A fictional community keeper.

## Cultural lens

- Intergenerational responsibility

## Core values

- Reciprocity

## Initial position

Protect shared resources through careful, long-term stewardship.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
""",
        expected_name="River Keeper",
    )


class _EmptySearch:
    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
        del snapshot_id, query, top_k
        return ()


class _FakeAdapter:
    """Adapter-shaped fake; it never owns persistence or network behavior."""

    def __init__(self) -> None:
        self.provider = MockLLMProvider()
        self.calls = 0

    def build_request(self, prompt: object, **metadata: object) -> LLMRequestV1:
        request_prompt = prompt
        request = request_prompt.request  # type: ignore[attr-defined]
        return LLMRequestV1(
            endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
            method="POST",
            body={},
            messages=request_prompt.messages,  # type: ignore[attr-defined]
            prompt=request_prompt,  # type: ignore[arg-type]
            budget=request_prompt.budget,  # type: ignore[attr-defined]
            request_hash=_hash(json.dumps(metadata, sort_keys=True) + request.request_hash),
            prompt_contract_version="prompt_request_v1",
            schema_hash=_hash("schema"),
            tokenizer_id="pinned-test-tokenizer",
            tokenizer_asset_hash=_hash("pinned-test-tokenizer"),
            rule_set_hash=request.rule_set_hash,
            persona_spec_hash=request.persona_spec_hash,
            transcript_hash=request.transcript_hash,
            receipt_hash=request.receipt_hash,
            turn_id=request.turn_id,
            generation_fence=str(metadata.get("generation_fence", "")),
            policy_hash=str(metadata.get("policy_hash", "")),
            export_manifest_hash=str(metadata.get("export_manifest_hash", "")),
            repair_policy_hash=_hash("repair-policy"),
            build_manifest_hash=str(metadata.get("build_manifest_hash", "")) or _hash("build"),
            attempt_no=int(metadata.get("attempt_no", 1)),
            retrieval_reused=bool(metadata.get("retrieval_reused", False)),
        )

    def execute(self, prompt: object, **metadata: object) -> LLMValidatedResultV1:
        self.calls += 1
        request = self.build_request(prompt, **metadata)
        result = self.provider.generate_turn(prompt)  # type: ignore[arg-type]
        payload = result.model_dump(mode="json")
        output_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        mapped = MappedLLMTurnV1(
            result=result,
            provider_output=payload,
            provider_output_json=output_json,
            provider_output_hash=_hash(output_json),
        )
        return LLMValidatedResultV1(
            status="succeeded",
            acceptance="accepted",
            failure_kind="none",
            safe_error_code=None,
            request=request,
            usage=LLMUsageV1(1, 0, 1, 2),
            mapped=mapped,
            estimated_cost_cny=Decimal("0"),
            actual_cost_cny=Decimal("0"),
        )


class _NotSentOnceAdapter(_FakeAdapter):
    def execute(self, prompt: object, **metadata: object) -> object:
        if self.calls == 0:
            self.calls += 1
            return SimpleNamespace(
                acceptance="not_sent",
                safe_error_code="llm_transport_not_sent",
                retry_allowed=True,
            )
        return super().execute(prompt, **metadata)


class _AcceptanceUnknownAdapter(_FakeAdapter):
    def execute(self, prompt: object, **metadata: object) -> object:
        del prompt, metadata
        self.calls += 1
        raise LLMAcceptanceUnknown()


def _participants() -> tuple[ParticipantContext, ...]:
    persona = _persona()
    digest = persona_spec_hash(persona)
    return tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=f"Expert {index}",
            slot=chr(65 + index),
            order_index=index,
            snapshot_id=f"snapshot-{index}",
            agent_md="private source omitted",
            teacher_note="private note omitted",
            persona=persona,
            persona_spec_hash=digest,
        )
        for index in range(2)
    )


def test_fake_two_agent_two_round_path_stages_and_publishes_every_turn(monkeypatch) -> None:
    # Public server-derived claim IDs are UUID-shaped in the current mapper;
    # the focused fake path isolates runtime lifecycle from the provider
    # privacy scanner's separate path-aware UUID policy.
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plans = MutualLearningPolicy().plan(people, round_count=2)
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(
        ledger=ledger,
        adapter=adapter,
        agent_count=2,
    )
    service = TurnGenerationService(
        SnapshotRetriever(_EmptySearch()),
        adapter,
        rule_set_id="ordered_multi_expert_mutual_learning_v1",
        llm_runtime=runtime,
        llm_runtime_options={
            "policy_hash": _hash("policy"),
            "manifest_hash": _hash("manifest"),
            "build_manifest_hash": _hash("build"),
            "confirmed": True,
        },
    )
    turns = []
    for index, plan in enumerate(plans):
        context = GenerationContext(
            debate_id="debate-runtime",
            topic="Should a platform restrict recommendation algorithms?",
            turn=plan,
            participant=people[index % 2],
            participants=people,
            predecessors=tuple(turns),
        )
        turns.append(service.generate(context).final_ready)

    assert len(turns) == 4
    assert adapter.calls == 4
    assert all(turn.evidence_trace for turn in turns)
    assert all(operation.state == "succeeded" for operation in ledger.operations())
    assert all(
        ledger.get_llm_accepted_stage(operation.id) is not None for operation in ledger.operations()
    )


def test_confirmation_gate_has_zero_reservation_and_zero_adapter_calls() -> None:
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_total_tokens=2_000_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=False)
    assert outcome.status == "provider_confirmation_required"
    assert adapter.calls == 0
    assert prepared.operation is not None
    assert prepared.operation.request_count == 0


def test_confirmation_then_explicit_retry_reuses_the_prepared_zero_use_operation(
    monkeypatch,
) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_total_tokens=2_000_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    first = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    waiting = runtime.run(first, confirmed=False)
    assert waiting.status == "provider_confirmation_required"
    second = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    assert second.operation_id == first.operation_id
    assert second.operation is not None and second.operation.request_count == 0
    assert runtime.run(second, confirmed=True).status == "succeeded"
    assert adapter.calls == 1


def test_proven_not_sent_uses_one_frozen_second_attempt(monkeypatch) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _NotSentOnceAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "succeeded"
    assert adapter.calls == 2
    assert len(outcome.attempts) == 2
    operations = ledger.operations()
    assert [item.state for item in operations] == ["not_sent", "succeeded"]


def _prompt_with_request(prompt: ProviderPromptV1, request: object) -> ProviderPromptV1:
    request_value = request
    return ProviderPromptV1(
        request=request_value,  # type: ignore[arg-type]
        messages=(
            prompt.messages[0],
            PromptMessageV1(role="user", content=request_value.canonical_json()),  # type: ignore[attr-defined]
        ),
        budget=prompt.budget,
        request_hash=request_value.request_hash,  # type: ignore[attr-defined]
        system_rules_hash=prompt.system_rules_hash,
    )


def test_acceptance_unknown_is_retained_and_startup_recovery_makes_no_call(monkeypatch) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_total_tokens=2_000_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _AcceptanceUnknownAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "acceptance_unknown"
    assert adapter.calls == 1
    assert ledger.operations()[0].state == "acceptance_unknown"
    stranded_prompt = _prompt_with_request(
        prompt,
        prompt.request.model_copy(update={"turn_id": "turn-startup"}),
    )
    stranded = runtime.prepare(
        stranded_prompt,
        debate_id="debate-runtime",
        turn_id="turn-startup",
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    ledger.reserve(stranded.operation_id or "")
    ledger.transition(stranded.operation_id or "", expected="reserved", state="sending")
    recovery = LLMRecoveryService(ledger)
    report = recovery.recover_startup()
    assert report.acceptance_unknown_operations == (stranded.operation_id,)
    assert adapter.calls == 1


def test_accepted_stage_resumes_locally_without_adapter_call(monkeypatch) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_total_tokens=2_000_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    ledger.reserve(prepared.operation_id or "")
    ledger.transition(prepared.operation_id or "", expected="reserved", state="sending")
    response = adapter.execute(
        prompt,
        generation_fence=prepared.generation_fence_hash,
        policy_hash=prepared.policy_hash,
        export_manifest_hash=prepared.manifest_hash,
        build_manifest_hash=prepared.build_manifest_hash,
        attempt_no=1,
    )
    operation, stage = runtime._stage(prepared, response)
    assert stage is not None
    assert operation.state == "accepted"
    calls_before = adapter.calls
    result = response.result
    assert result is not None
    outcome = LLMRecoveryService(
        ledger,
        stage_store=ledger,
        runtime=runtime,
    ).resume_accepted(
        prepared.operation_id or "",
        result_loader=lambda _stage: result,
    )
    assert outcome.status == "succeeded"
    assert adapter.calls == calls_before
    assert ledger.operations()[0].state == "succeeded"


def test_atomic_publication_failure_rolls_operation_back(monkeypatch) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )

    class _Publication:
        calls = 0

        def commit_turn_success(self, **kwargs: object) -> None:
            del kwargs
            self.calls += 1
            raise RuntimeError("rollback")

    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_total_tokens=2_000_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    publication = _Publication()
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter, publication=publication)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "failed"
    assert outcome.safe_error_code == "llm_publication_failed"
    assert publication.calls == 1
    assert adapter.calls == 1
    assert ledger.operations()[0].state == "failed"


def test_scope_estimate_does_not_stop_the_ninth_call(monkeypatch) -> None:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    people = _participants()
    base_plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    base_prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=base_plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=2_000_000,
            max_cost_cny=1.2,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    outcomes = []
    for index in range(9):
        prompt = _prompt_with_request(
            base_prompt,
            base_prompt.request.model_copy(update={"turn_id": f"turn-cap-{index}"}),
        )
        prepared = runtime.prepare(
            prompt,
            debate_id="debate-runtime",
            turn_id=f"turn-cap-{index}",
            policy_hash=_hash("policy"),
            manifest_hash=_hash("manifest"),
            build_manifest_hash=_hash("build"),
        )
        outcomes.append(runtime.run(prepared, confirmed=True))
    assert [item.status for item in outcomes] == ["succeeded"] * 9
    assert adapter.calls == 9
    assert all(operation.state == "succeeded" for operation in ledger.operations())
    assert sum(operation.charged_request_count for operation in ledger.operations()) == 9


def test_teacher_debate_manifest_listing_has_stable_auth_and_exact_dto() -> None:
    policy = _disclosure_policy()
    manifest = _llm_manifest(policy)
    store = InMemoryProviderDisclosureStore(
        policy,
        manifest,
        debate_id="debate-runtime",
        debate_manifests=(manifest,),
        turn_ids_by_manifest={manifest.manifest_hash: "turn-0"},
    )
    service = ProviderDisclosureService(store)
    listing = service.list_llm_manifests_for_debate("teacher", debate_id="debate-runtime")
    assert isinstance(listing, ProviderDataCallDebateManifestListResponseV1)
    assert listing.model_dump(mode="json") == {
        "debate_id": "debate-runtime",
        "items": [
            {
                "turn_id": "turn-0",
                "manifest_hash": manifest.manifest_hash,
                "confirmation_revision": 1,
                "confirmed": False,
            }
        ],
    }
    encoded = json.dumps(listing.model_dump(mode="json"), sort_keys=True).casefold()
    for forbidden in (
        "qwen3.7-plus",
        "endpoint",
        "policy_hash",
        "build_manifest_hash",
        "persona_spec_hash",
        "provider_operation",
        "ledger",
        "prompt",
    ):
        assert forbidden not in encoded
    with pytest.raises(ProviderDisclosureError) as missing:
        service.list_llm_manifests_for_debate("teacher", debate_id="missing-debate")
    assert missing.value.code == "not_found"
    with pytest.raises(ProviderDisclosureError) as forbidden:
        service.list_llm_manifests_for_debate("student", debate_id="debate-runtime")
    assert forbidden.value.code == "forbidden"


def test_teacher_can_open_exact_current_llm_manifest_disclosure() -> None:
    policy = _disclosure_policy()
    manifest = _llm_manifest(policy)
    service = ProviderDisclosureService(
        InMemoryProviderDisclosureStore(
            policy,
            manifest,
            debate_id="debate-runtime",
            debate_manifests=(manifest,),
            turn_ids_by_manifest={manifest.manifest_hash: "turn-0"},
        )
    )

    disclosure = service.disclose("teacher")

    assert disclosure.manifest_hash == manifest.manifest_hash
    assert disclosure.disclosure.purpose == (
        "Generate the teacher-approved classroom debate speech."
    )
    encoded = json.dumps(disclosure.model_dump(mode="json"), sort_keys=True).casefold()
    for forbidden in ("qwen3.7-plus", "endpoint", "workspace", "prompt", "usage"):
        assert forbidden not in encoded


def test_fixed_adapter_uses_send_stage_then_local_validate_without_second_transport() -> None:
    from tests.test_wave4_llm_adapter import _adapter, _FakeTransport, _output, _prompt, _response

    transport = _FakeTransport(_response(_output()))
    adapter = _adapter(transport)
    prompt = _prompt()
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=2_000_000,
            max_cost_cny=1.2,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "succeeded"
    assert len(transport.calls) == 1
    assert outcome.stage is not None
    assert ledger.get_llm_accepted_stage(prepared.operation_id or "") is not None


def test_fixed_adapter_reference_failure_repairs_once_after_stage(monkeypatch) -> None:
    from app.providers.llm_transport import LLMTransportResponse

    from tests.test_wave4_llm_adapter import _adapter, _FakeTransport, _output, _prompt, _response

    invalid = _output()
    casted_claims = invalid["key_claims"]
    assert isinstance(casted_claims, list)
    casted_claims[0]["used_evidence_refs"] = [0]
    valid = _output(speech="A transparent policy protects agency over time.")
    transport = _FakeTransport(_response(invalid))
    adapter = _adapter(transport)
    original_post = transport.post
    calls = 0

    def post(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            del args, kwargs
            return LLMTransportResponse(200, _response(valid))
        return original_post(*args, **kwargs)  # type: ignore[arg-type]

    transport.post = post  # type: ignore[method-assign]
    prompt = _prompt()
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=2_000_000,
            max_cost_cny=1.2,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "succeeded"
    assert calls == 2
    assert len(ledger.operations()) == 2
    assert ledger.operations()[0].state == "failed"
    assert ledger.operations()[1].state == "succeeded"


def test_fixed_adapter_proven_not_sent_retries_but_unknown_does_not(monkeypatch) -> None:
    from app.providers.llm_transport import LLMTransportNotSent

    from tests.test_wave4_llm_adapter import _adapter, _prompt

    class _NotSentTransport:
        calls = 0

        def post(
            self,
            url: str,
            *,
            headers: object,
            json: object,
            timeout: object,
        ) -> object:
            del url, headers, json, timeout
            self.calls += 1
            raise LLMTransportNotSent()

    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    transport = _NotSentTransport()
    adapter = _adapter(transport)
    prompt = _prompt()
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=2_000_000,
            max_cost_cny=1.2,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "not_sent"
    assert transport.calls == 2
    assert [item.state for item in ledger.operations()] == ["not_sent", "not_sent"]


def test_fixed_adapter_acceptance_unknown_is_one_charged_nonterminal_attempt(monkeypatch) -> None:
    from app.providers.llm_transport import LLMAcceptanceUnknown

    from tests.test_wave4_llm_adapter import _adapter, _prompt

    class _UnknownTransport:
        calls = 0

        def post(
            self,
            url: str,
            *,
            headers: object,
            json: object,
            timeout: object,
        ) -> object:
            del url, headers, json, timeout
            self.calls += 1
            raise LLMAcceptanceUnknown()

    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    transport = _UnknownTransport()
    adapter = _adapter(transport)
    prompt = _prompt()
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=2_000_000,
            max_cost_cny=1.2,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    outcome = runtime.run(prepared, confirmed=True)
    assert outcome.status == "acceptance_unknown"
    assert transport.calls == 1
    assert len(ledger.operations()) == 1
    assert ledger.operations()[0].state == "acceptance_unknown"


def _admission_runtime(monkeypatch, slot) -> tuple[object, object, object, object]:
    from app.modules.debates.generation import runtime as runtime_module

    monkeypatch.setattr(runtime_module, "scan_llm_outbound_messages", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_module, "llm_admission_slot", slot)
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="A safe topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=8,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket=LLM_DEBATE_TURN_BUCKET,
        )
    )
    adapter = _FakeAdapter()
    runtime = LLMTurnRuntime(ledger=ledger, adapter=adapter)
    prepared = runtime.prepare(
        prompt,
        policy_hash=_hash("policy"),
        manifest_hash=_hash("manifest"),
        build_manifest_hash=_hash("build"),
    )
    return runtime, prepared, ledger, adapter


def test_debate_call_takes_its_llm_slot_before_it_is_marked_sending(monkeypatch) -> None:
    """#141: a crash while queued for a slot must not leave a "sending" call."""

    from contextlib import contextmanager

    seen: dict[str, object] = {"held": False}
    holder: dict[str, object] = {}

    @contextmanager
    def slot():
        seen["at_admission"] = [item.state for item in holder["ledger"].operations()]
        seen["held"] = True
        try:
            yield
        finally:
            seen["held"] = False

    runtime, prepared, ledger, adapter = _admission_runtime(monkeypatch, slot)
    holder["ledger"] = ledger
    original = adapter.execute

    def execute(prompt: object, **metadata: object) -> object:
        assert seen["held"], "the model call must run inside the LLM slot"
        return original(prompt, **metadata)

    monkeypatch.setattr(adapter, "execute", execute)
    outcome = runtime.run(prepared, confirmed=True)

    assert outcome.status == "succeeded"
    assert seen["at_admission"] == ["reserved"]
    assert seen["held"] is False


def test_debate_admission_refusal_is_not_sent_not_acceptance_unknown(monkeypatch) -> None:
    """#141: a refused slot used to fall into the transport classifier as unknown."""

    from contextlib import contextmanager

    from app.core.errors import PlatformError

    @contextmanager
    def busy():
        raise PlatformError("adaptive_admission_busy", "busy", 503, {"retryable": True})
        yield  # pragma: no cover

    runtime, prepared, ledger, adapter = _admission_runtime(monkeypatch, busy)
    outcome = runtime.run(prepared, confirmed=True)

    assert outcome.status == "not_sent"
    assert outcome.safe_error_code == "provider_not_sent"
    assert adapter.calls == 0
    assert [item.state for item in ledger.operations()] == ["not_sent"]
