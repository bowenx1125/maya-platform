"""Focused provider-neutral LLM-A runtime and product-path tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.modules.agents.persona import compile_persona_or_raise, persona_spec_hash
from app.modules.debates.generation import (
    GenerationContext,
    LLMTurnRuntime,
    MutualLearningPolicy,
    MutualLearningTurnResultV1,
    ParticipantContext,
    SnapshotRetriever,
    TurnGenerationService,
    build_provider_prompt,
)
from app.providers.control import (
    InMemoryProviderOperationRepository,
    LLM_DEBATE_TURN_BUCKET,
    ProviderScopeBudgetV1,
)
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import (
    LLMRequestV1,
    LLMUsageV1,
    LLMValidatedResultV1,
)
from app.providers.llm_output import MappedLLMTurnV1


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    assert all(ledger.get_llm_accepted_stage(operation.id) is not None for operation in ledger.operations())


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
        default_budget=ProviderScopeBudgetV1(budget_bucket=LLM_DEBATE_TURN_BUCKET)
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


def test_manifest_scan_rejects_identity_before_persistence() -> None:
    people = _participants()
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    prompt = build_provider_prompt(
        GenerationContext(
            debate_id="debate-runtime",
            topic="student-alice's forbidden topic",
            turn=plan,
            participant=people[0],
            participants=people,
        ),
        persona=people[0].persona,
    )

    class _ManifestStore:
        calls = 0

        def ensure_export_manifest(self, manifest: object, **kwargs: object) -> None:
            del manifest, kwargs
            self.calls += 1

    store = _ManifestStore()
    runtime = LLMTurnRuntime(ledger=object(), adapter=_FakeAdapter(), manifest_store=store)
    with pytest.raises(Exception) as error:
        runtime.prepare_manifest(
            prompt,
            debate_id="debate-runtime",
            turn_id="turn-0",
            policy_hash=_hash("policy"),
            build_manifest_hash=_hash("build"),
            policy_snapshot_id="policy-row",
            identity_tokens=("student-alice",),
        )
    assert getattr(error.value, "code", None) == "llm_outbound_data_forbidden"
    assert store.calls == 0
