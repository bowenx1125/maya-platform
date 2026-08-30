"""Focused PromptRequestV1/PromptBudgetV1 tests; all boundaries are local."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from app.modules.agents.persona import PersonaSpecV1, compile_persona_or_raise, persona_spec_hash
from app.modules.debates.generation import (
    FinalReadyTurn,
    FrozenPromptIdentity,
    GenerationContext,
    KeyClaimV1,
    MutualLearningPolicy,
    MutualLearningTurnResultV1,
    ParticipantContext,
    PromptAcceptanceState,
    PromptAttemptPolicy,
    PromptBudgetError,
    PromptFailureKind,
    PromptRequestError,
    SnapshotRetrievalReceipt,
    TurnSubquery,
    build_provider_prompt,
    compute_mutual_transcript_hash,
    confirmed_persona_provider_view,
    repair_prompt_request,
)


def _persona() -> PersonaSpecV1:
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

Protect shared resources through careful stewardship.

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


def _participants() -> tuple[ParticipantContext, ParticipantContext]:
    return (
        ParticipantContext(
            participant_id="participant-0",
            agent_id="agent-0",
            agent_name="River Keeper",
            slot="A",
            order_index=0,
            snapshot_id="snapshot-0",
            agent_md="PRIVATE RAW AGENT MARKDOWN",
            teacher_note="PRIVATE TEACHER NOTE",
        ),
        ParticipantContext(
            participant_id="participant-1",
            agent_id="agent-1",
            agent_name="Other Persona",
            slot="B",
            order_index=1,
            snapshot_id="snapshot-1",
            agent_md="OTHER RAW PERSONA",
            teacher_note="OTHER PRIVATE NOTE",
        ),
    )


def _ready(
    turn_id: str,
    participant_id: str,
    round_no: int,
    turn_index: int,
    speech: str,
    *,
    evidence_ids: tuple[str, ...] = (),
) -> FinalReadyTurn:
    result = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=[
            KeyClaimV1(
                claim_id=f"{turn_id}:claim",
                claim_text="The opening identifies a responsible proposal.",
                claim_type="proposal",
                used_evidence_ids=list(evidence_ids),
            )
        ],
        position_summary="An independent public position.",
        remaining_uncertainty=["Local effects remain uncertain."],
        used_evidence_id=list(evidence_ids),
    )
    from app.modules.debates.generation import FinalReadyTurn

    return FinalReadyTurn(
        turn_id=turn_id,
        participant_id=participant_id,
        snapshot_id=f"snapshot-{participant_id.rsplit('-', 1)[-1]}",
        round_no=round_no,
        turn_index=turn_index,
        speech=speech,
        structured=result,
        retrieval_status="no_match",
        grounding_mode="general_reasoning",
        used_receipts=(),
        predecessor_turn_ids=(),
        cutoff_turn_index=-1,
        transcript_hash="prior",
        attempt=1,
    )


def _context(
    round_no: int = 2, *, predecessors: tuple[FinalReadyTurn, ...] = ()
) -> GenerationContext:
    people = _participants()
    plans = MutualLearningPolicy().plan(people, round_count=3)
    plan = plans[(round_no - 1) * len(people)]
    return GenerationContext(
        debate_id="debate-1",
        topic="How should a platform protect community agency?",
        turn=plan,
        participant=people[0],
        participants=people,
        predecessors=predecessors,
    )


def test_provider_prompt_has_exactly_two_messages_and_safe_persona_projection() -> None:
    first = _ready(
        "turn-0", "participant-0", 1, 0, "The complete first speech is never summarized."
    )
    second = _ready("turn-1", "participant-1", 1, 1, "The complete second speech remains exact.")
    prompt = build_provider_prompt(
        _context(2, predecessors=(first, second)),
        persona=_persona(),
        queries=(TurnSubquery("viewpoint", "the independent viewpoint"),),
    )
    assert [message.role for message in prompt.messages] == ["system", "user"]
    assert prompt.user_message.content == prompt.request.canonical_json()
    payload = json.loads(prompt.user_message.content)
    assert payload["request_version"] == "prompt_request_v1"
    assert len(payload["persona_provider_view"]) == 8
    assert "agent_md" not in prompt.user_message.content
    assert "teacher_note" not in prompt.user_message.content
    assert "PRIVATE RAW" not in prompt.user_message.content
    assert "OTHER PRIVATE" not in prompt.user_message.content
    assert "snapshot-1" not in prompt.user_message.content
    assert prompt.user_message.content.count(first.speech) == 1
    assert prompt.user_message.content.count(second.speech) == 1
    assert "turn_summary" not in prompt.user_message.content


def test_canonical_prompt_is_stable_and_evidence_queries_are_deduplicated() -> None:
    first = _ready("turn-0", "participant-0", 1, 0, "An exact public speech.")
    second = _ready("turn-1", "participant-1", 1, 1, "Another exact public speech.")
    context = _context(2, predecessors=(first, second))
    query = TurnSubquery("viewpoint", "same query")
    receipt_a = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-0",
        query_kind="viewpoint",
        query_hash=query.query_hash,
        threshold_key="strict",
        rank=1,
        score=0.5,
        chunk_id="chunk-a",
        source_filename="private-source.md",
        text="One excerpt is enough.",
    )
    receipt_duplicate = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-0",
        query_kind="viewpoint",
        query_hash=query.query_hash,
        threshold_key="relaxed",
        rank=2,
        score=0.2,
        chunk_id="chunk-b",
        source_filename="another-private-source.md",
        text="One excerpt is enough.",
    )
    first_prompt = build_provider_prompt(
        context,
        persona=_persona(),
        queries=(query, query),
        receipts=(receipt_a, receipt_duplicate),
    )
    second_prompt = build_provider_prompt(
        context,
        persona=_persona(),
        queries=(query,),
        receipts=(receipt_a, receipt_duplicate),
    )
    assert first_prompt.user_message.content == second_prompt.user_message.content
    assert len(first_prompt.request.query_catalog) == 1
    assert len(first_prompt.request.evidence_catalog) == 1
    assert first_prompt.request.evidence_catalog[0].excerpt == "One excerpt is enough."
    assert "private-source.md" not in first_prompt.user_message.content
    assert "another-private-source.md" not in first_prompt.user_message.content


def test_conservative_preflight_rejects_before_any_provider_boundary() -> None:
    with pytest.raises(PromptBudgetError) as error:
        from app.modules.debates.generation import preflight_prompt_budget

        preflight_prompt_budget(("x" * 32_001,), request_bytes=1)
    assert error.value.code == "prompt_input_tokens_exceeded"
    with pytest.raises(PromptBudgetError) as error:
        preflight_prompt_budget(("ok",), request_bytes=96 * 1024 + 1)
    assert error.value.code == "prompt_request_bytes_exceeded"
    with pytest.raises(PromptBudgetError) as error:
        preflight_prompt_budget(("ok",), requested_output_tokens=1_501)
    assert error.value.code == "prompt_output_tokens_exceeded"


def test_attempt_policy_allows_only_frozen_structure_or_proven_not_sent_retry() -> None:
    policy = PromptAttemptPolicy()
    repair = policy.decide(
        attempt_no=1,
        failure=PromptFailureKind.STRUCTURE_INVALID,
        acceptance=PromptAcceptanceState.ACCEPTED,
    )
    assert repair.retry and repair.action == "retry_structure"
    assert repair.reuse_retrieval and not repair.reuse_request
    transport = policy.decide(
        attempt_no=1,
        failure=PromptFailureKind.TRANSPORT_NOT_SENT,
        acceptance=PromptAcceptanceState.NOT_SENT,
    )
    assert transport.retry and transport.reuse_request and transport.reuse_retrieval
    retrieval = policy.decide(
        attempt_no=1,
        failure=PromptFailureKind.RETRIEVAL_TECHNICAL,
        acceptance=PromptAcceptanceState.NOT_SENT,
    )
    assert retrieval.retry and retrieval.action == "retry_retrieval"
    assert not retrieval.reuse_request and not retrieval.reuse_retrieval
    unknown = policy.decide(
        attempt_no=1,
        failure=PromptFailureKind.STRUCTURE_INVALID,
        acceptance=PromptAcceptanceState.UNKNOWN,
    )
    assert not unknown.retry
    assert not policy.decide(
        attempt_no=1,
        failure=PromptFailureKind.BUDGET,
        acceptance=PromptAcceptanceState.NOT_SENT,
    ).retry


def test_structure_repair_preserves_frozen_hashes_and_only_adds_safe_feedback() -> None:
    prompt = build_provider_prompt(
        _context(1),
        persona=_persona(),
        queries=(TurnSubquery("viewpoint", "independent viewpoint"),),
    ).request
    repaired = repair_prompt_request(
        prompt,
        safe_error_code="output_schema_invalid",
        json_pointers=("/speech", "/key_claims"),
    )
    assert repaired.repair_feedback is not None
    assert repaired.rule_set_hash == prompt.rule_set_hash
    assert repaired.persona_spec_hash == prompt.persona_spec_hash
    assert repaired.transcript_hash == prompt.transcript_hash
    assert repaired.receipt_hash == prompt.receipt_hash
    assert repaired.model_copy(update={"repair_feedback": None}) == prompt
    assert FrozenPromptIdentity.from_request(prompt).matches(repaired)
    with pytest.raises(ValueError):
        repair_prompt_request(repaired, safe_error_code="again")


def test_context_requires_confirmed_structured_persona_and_does_not_fallback_to_raw_markdown() -> (
    None
):
    with pytest.raises(PromptRequestError) as error:
        build_provider_prompt(_context(1), queries=(TurnSubquery("viewpoint", "view"),))
    assert error.value.code == "persona_provider_view_required"


def test_persisted_persona_connection_requires_canonical_json_and_matching_hash() -> None:
    persona = _persona()
    canonical = json.dumps(
        persona.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    view, resolved_hash = confirmed_persona_provider_view(canonical)
    assert view.schema_version == "persona_provider_view_v1"
    assert "source_agent_md_hash" not in view.model_dump()
    assert "compiler_version" not in view.model_dump()
    assert resolved_hash
    with pytest.raises(PromptRequestError) as error:
        confirmed_persona_provider_view(canonical + " ")
    assert error.value.code == "persona_hash_changed"
    with pytest.raises(PromptRequestError) as error:
        confirmed_persona_provider_view(canonical, expected_persona_spec_hash="0" * 64)
    assert error.value.code == "persona_hash_changed"


def test_prompt_hash_matches_existing_mutual_transcript_fence() -> None:
    first = _ready("turn-0", "participant-0", 1, 0, "Opening text.")
    second = _ready("turn-1", "participant-1", 1, 1, "Second opening text.")
    context = _context(2, predecessors=(first, second))
    prompt = build_provider_prompt(
        context,
        persona=_persona(),
        queries=(TurnSubquery("viewpoint", "view"),),
    )
    assert prompt.request.transcript_hash == compute_mutual_transcript_hash((first, second))


def test_strict_persona_service_path_sends_two_safe_messages_and_reuses_retrieval_on_repair() -> (
    None
):
    from app.modules.debates.generation import SnapshotRetriever, TurnGenerationService
    from app.providers.llm import MockLLMProvider

    persona = _persona()
    persona_hash = persona_spec_hash(persona)
    people = tuple(
        replace(item, persona=persona, persona_spec_hash=persona_hash) for item in _participants()
    )
    plans = MutualLearningPolicy().plan(people, round_count=3)

    class StableSearch:
        calls = 0

        def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
            self.calls += 1
            del snapshot_id, query, top_k
            return ()

    # ``rule`` makes the first accepted Mock output structurally invalid; the
    # strict service must append pointer feedback and call the same frozen
    # retrieval result, not search again.
    search = StableSearch()
    provider = MockLLMProvider(failures=("rule",))
    service = TurnGenerationService(
        SnapshotRetriever(search),
        provider,
        rule_set_id="ordered_multi_expert_mutual_learning_v1",
    )
    result = service.generate(
        GenerationContext(
            "strict-debate",
            "A strict request topic",
            plans[0],
            people[0],
            people,
        )
    )
    assert result.final_ready.attempt == 2
    assert provider.call_count == 2
    assert len(provider.prompts) == 2
    first_call, second_call = provider.prompts
    assert [role for role, _content in first_call.messages] == ["system", "user"]
    assert [role for role, _content in second_call.messages] == ["system", "user"]
    assert "repair_feedback" not in first_call.messages[1][1]
    assert "repair_feedback" in second_call.messages[1][1]
    assert "PRIVATE RAW" not in first_call.messages[1][1]
    assert "PRIVATE TEACHER" not in first_call.messages[1][1]
    assert "Other Persona" not in first_call.messages[1][1]
    assert "snapshot-1" not in first_call.messages[1][1]
    assert first_call.receipt_hash == second_call.receipt_hash
    assert search.calls == 2  # one strict + one relaxed local search, no repair search


@pytest.mark.parametrize("failure", ("json", "technical"))
def test_strict_service_retries_only_known_safe_mock_outcomes_without_retrieval_duplication(
    failure: str,
) -> None:
    from app.modules.debates.generation import SnapshotRetriever, TurnGenerationService
    from app.providers.llm import MockLLMProvider

    persona = _persona()
    persona_hash = persona_spec_hash(persona)
    people = tuple(
        replace(item, persona=persona, persona_spec_hash=persona_hash) for item in _participants()
    )
    plan = MutualLearningPolicy().plan(people, round_count=3)[0]

    class StableSearch:
        calls = 0

        def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
            self.calls += 1
            del snapshot_id, query, top_k
            return ()

    search = StableSearch()
    provider = MockLLMProvider(failures=(failure,))
    result = TurnGenerationService(
        SnapshotRetriever(search),
        provider,
        rule_set_id="ordered_multi_expert_mutual_learning_v1",
    ).generate(GenerationContext("d", "Topic", plan, people[0], people))
    assert result.final_ready.attempt == 2
    assert provider.call_count == 2
    assert search.calls == 2
