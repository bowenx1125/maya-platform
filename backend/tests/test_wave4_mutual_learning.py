"""Deterministic acceptance tests for the ordered mutual-learning RuleSet."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from app.modules.debates.generation import (
    EngagementV1,
    FinalReadyTurn,
    GenerationContext,
    KeyClaimV1,
    MutualLearningPolicy,
    MutualLearningTurnResultV1,
    MutualLearningValidator,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    SnapshotRetriever,
    TurnGenerationService,
    TurnPolicy,
    TurnQuestion,
    TurnValidationError,
    ValidatedTurn,
    build_mutual_learning_prompt,
    build_mutual_learning_synthesis,
    compute_mutual_transcript_hash,
    make_mutual_learning_prompt_input,
    phase_for_round,
    resolve_round_phase,
)
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
)
from app.providers.llm import MockLLMProvider

RULE_SET = "ordered_multi_expert_mutual_learning_v1"


class EmptySearch:
    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> tuple[object, ...]:
        del snapshot_id, query, top_k
        return ()


def participant(index: int) -> ParticipantContext:
    return ParticipantContext(
        participant_id=f"participant-{index}",
        agent_id=f"agent-{index}",
        agent_name=f"Agent {index}",
        slot=chr(65 + index),
        order_index=index,
        snapshot_id=f"snapshot-{index}",
        agent_md=f"# Persona\nPrivate persona {index}",
        teacher_note=f"private teacher note {index}",
    )


def generated_turns(
    participant_count: int,
    round_count: int,
) -> tuple[FinalReadyTurn, ...]:
    people = tuple(participant(index) for index in range(participant_count))
    plans = MutualLearningPolicy().plan(people, round_count=round_count)
    service = TurnGenerationService(
        SnapshotRetriever(EmptySearch()),
        MockLLMProvider(),
        rule_set_id=RULE_SET,
    )
    turns: list[FinalReadyTurn] = []
    for index, plan in enumerate(plans):
        turns.append(
            service.generate(
                GenerationContext(
                    debate_id="debate-wave4",
                    topic="Should a platform restrict recommendation algorithms?",
                    turn=plan,
                    participant=people[index % participant_count],
                    participants=people,
                    predecessors=tuple(turns),
                )
            ).final_ready
        )
    return tuple(turns)


def test_phase_resolver_and_dynamic_plan_cover_two_three_and_five_rounds() -> None:
    assert resolve_round_phase(1, False).value == "opening"
    assert resolve_round_phase(3, False).value == "exchange"
    assert resolve_round_phase(5, True).value == "final_integration"
    for round_count, expected_exchange_count in ((2, 0), (3, 1), (5, 3)):
        plans = MutualLearningPolicy().plan(
            [participant(0), participant(1)], round_count=round_count
        )
        assert [item.phase for item in plans] == [
            "opening",
            "opening",
            *(["exchange", "exchange"] * expected_exchange_count),
            "final_integration",
            "final_integration",
        ]
        assert all(item.barrier == "round" for item in plans)
        assert all(item.is_final_round for item in plans[-2:])
        assert plans[0].predecessor_turn_ids == ()
        assert plans[-1].predecessor_turn_ids == tuple(
            f"turn-{index}" for index in range((round_count - 1) * 2)
        )
        assert phase_for_round(round_count, round_count).value == "final_integration"


@pytest.mark.parametrize(
    ("participant_count", "round_count"),
    ((2, 2), (3, 3), (5, 5)),
)
def test_complete_generation_matrix_has_one_opening_exchange_span_and_final(
    participant_count: int,
    round_count: int,
) -> None:
    """Run the provider-neutral Mock through every required acceptance matrix."""

    turns = generated_turns(participant_count, round_count)
    assert len(turns) == participant_count * round_count
    expected_phases = (
        ["opening"] * participant_count
        + ["exchange"] * participant_count * (round_count - 2)
        + ["final_integration"] * participant_count
    )
    plans = MutualLearningPolicy().plan(
        tuple(participant(index) for index in range(participant_count)),
        round_count=round_count,
    )
    assert [item.phase for item in plans] == expected_phases
    assert [item.round_no for item in plans] == [
        round_no for round_no in range(1, round_count + 1) for _ in range(participant_count)
    ]
    assert all(isinstance(turn.structured, MutualLearningTurnResultV1) for turn in turns)
    for turn in turns:
        assert isinstance(turn.structured, MutualLearningTurnResultV1)
        claims = turn.structured.key_claims
        assert 1 <= len(claims) <= 12
        claim_texts = [claim.claim_text for claim in claims]
        assert len(claim_texts) == len(set(claim_texts))
        assert all(text and text in turn.speech for text in claim_texts)
        assert turn.evidence_trace
        assert {claim.claim_id for claim in claims} == {
            row["claim_id"] for row in turn.evidence_trace
        }
    assert all(
        turn.structured.final_recommendation
        for turn in turns[-participant_count:]
        if isinstance(turn.structured, MutualLearningTurnResultV1)
    )


def test_mutual_rule_modules_do_not_encode_a_round_two_business_branch() -> None:
    """Keep fixed-round assumptions out of the versioned protocol path."""

    module_dir = Path(__file__).parents[1] / "app/modules/debates/generation"
    paths = (
        module_dir / "round_phase.py",
        module_dir / "mutual_learning_policy.py",
        module_dir / "mutual_learning_prompts.py",
        module_dir / "mutual_learning_validator.py",
        module_dir / "mutual_learning_synthesis.py",
    )
    forbidden = ("round_no == 2", "round_no==2", "round_no != 2", "round_no!=2")
    for path in paths:
        source = path.read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden), path.name


def test_turn_policy_dispatches_new_rule_without_changing_legacy_fixed_plan() -> None:
    plans = TurnPolicy(rule_set_id=RULE_SET).plan(["a", "b"], round_count=3)
    assert [item.phase for item in plans] == [
        "opening",
        "opening",
        "exchange",
        "exchange",
        "final_integration",
        "final_integration",
    ]
    legacy = TurnPolicy().plan(["a", "b"])
    assert [item.phase for item in legacy] == ["opening", "opening", "rebuttal", "rebuttal"]


def test_round_barrier_hides_same_round_and_shares_all_prior_rounds() -> None:
    turns = generated_turns(3, 3)
    people = tuple(participant(index) for index in range(3))
    plans = MutualLearningPolicy().plan(people, round_count=3)
    exchange_context = GenerationContext(
        debate_id="d",
        topic="Topic",
        turn=plans[3],
        participant=people[0],
        participants=people,
        predecessors=turns[:4],
    )
    exchange_prompt = make_mutual_learning_prompt_input(exchange_context)
    assert [item.turn_id for item in exchange_prompt.predecessors] == [
        item.turn_id for item in turns[:3]
    ]
    assert turns[3].speech not in build_mutual_learning_prompt(exchange_prompt)
    final_context = GenerationContext(
        debate_id="d",
        topic="Topic",
        turn=plans[-1],
        participant=people[2],
        participants=people,
        predecessors=turns,
    )
    final_prompt = make_mutual_learning_prompt_input(final_context)
    assert len(final_prompt.predecessors) == 6
    assert {item.round_no for item in final_prompt.predecessors} == {1, 2}
    assert turns[6].turn_id not in build_mutual_learning_prompt(final_prompt)
    assert "Private persona 1" not in build_mutual_learning_prompt(final_prompt)
    assert "private teacher note 1" not in build_mutual_learning_prompt(final_prompt)


def test_sql_turn_preparer_keeps_final_ready_opening_out_of_same_round_context(
    app_factory: object,
) -> None:
    """The SQL adapter must enforce the barrier before the Mock sees a prompt."""

    import json
    from typing import Any

    from app.modules.debates.models import Debate
    from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
    from app.modules.debates.setup.service import commit_start_plan
    from fastapi.testclient import TestClient

    from tests.conftest import login
    from tests.test_wave3_mock_rag_delta import (
        COURSE_ID,
        GROUP_BOWEN_ID,
        GROUP_KAIKAI_ID,
        _headers,
        _insert_sql_published_agent,
    )

    class CaptureMock(MockLLMProvider):
        inputs: list[Any]

        def __init__(self) -> None:
            super().__init__()
            self.inputs = []

        def generate_turn(self, prompt: Any) -> Any:
            self.inputs.append(prompt)
            return super().generate_turn(prompt)

    app, database, settings = app_factory()  # type: ignore[operator]
    with TestClient(app) as client:
        first_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Barrier A",
            evidence="Unrelated mineral carving notes do not answer this classroom topic.",
            confirmed_persona=True,
        )
        second_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Barrier B",
            evidence="Another unrelated geological passage for a separate snapshot.",
            confirmed_persona=True,
        )
        _session, csrf = login(client)
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave4-sql-opening-barrier"}),
            json={
                "topic": "How should communities discuss fairness in technology?",
                "participants": [
                    {"agent_id": first_agent, "stance_mode": "open"},
                    {"agent_id": second_agent, "stance_mode": "open"},
                ],
                "rule_set_id": RULE_SET,
                "round_count": 2,
            },
        )
        assert response.status_code == 201, response.text
        debate_id = response.json()["id"]
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            turns = commit_start_plan(db, debate_id=debate_id)
            assert len(turns) == 4
            assert turns[0].round_no == turns[1].round_no == 1

            llm = CaptureMock()
            preparer = SqlTurnPreparer(settings=settings, llm=llm)
            first_prepared = preparer(
                db,
                debate,
                turns[0],
                attempt=1,
                cancellation_generation=0,
            )
            prepared_result = MutualLearningTurnResultV1.model_validate(first_prepared.structured)
            assert first_prepared.evidence_trace
            claim_ids = {claim.claim_id for claim in prepared_result.key_claims}
            trace_ids = {row["claim_id"] for row in first_prepared.evidence_trace}
            assert claim_ids == trace_ids
            assert all(
                claim.claim_text == row["claim_text"]
                for claim in prepared_result.key_claims
                for row in first_prepared.evidence_trace
                if row["claim_id"] == claim.claim_id
            )
            # Make A genuinely final-ready in the same SQL transaction.  B's
            # prompt must still omit it because both rows belong to opening.
            turns[0].generation_status = "final_ready"
            turns[0].preparation_stage = "ready"
            turns[0].speech = first_prepared.speech
            turns[0].structured_json = json.dumps(
                dict(first_prepared.structured), sort_keys=True, separators=(",", ":")
            )
            turns[0].retrieval_status = first_prepared.retrieval_status
            turns[0].grounding_mode = first_prepared.grounding_mode
            turns[0].retrieval_receipts_json = "[]"
            turns[0].word_count = first_prepared.word_count
            turns[0].transcript_hash = first_prepared.transcript_hash
            turns[0].cutoff_turn_index = first_prepared.cutoff_turn_index
            db.flush()
            assert turns[0].generation_status == "final_ready"

            second_prepared = preparer(
                db,
                debate,
                turns[1],
                attempt=1,
                cancellation_generation=0,
            )
            assert second_prepared.predecessor_turn_ids == ()
            assert len(llm.inputs) == 2
            assert llm.inputs[1].request.predecessors == ()
            assert llm.inputs[1].request.transcript_hash == compute_mutual_transcript_hash(())


@pytest.mark.parametrize("round_count", (3, 5))
def test_sql_draft_projection_preserves_frozen_three_and_five_round_counts(
    app_factory: object,
    round_count: int,
) -> None:
    """Setup/detail reads the persisted snapshot rather than defaulting to two."""

    from fastapi.testclient import TestClient

    from tests.conftest import login
    from tests.test_wave3_mock_rag_delta import (
        COURSE_ID,
        GROUP_BOWEN_ID,
        GROUP_KAIKAI_ID,
        _headers,
        _insert_sql_published_agent,
    )

    app, database, _settings = app_factory()  # type: ignore[operator]
    with TestClient(app) as client:
        first_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name=f"Projection A {round_count}",
            evidence="A snapshot passage for the projection test.",
            confirmed_persona=True,
        )
        second_agent = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name=f"Projection B {round_count}",
            evidence="A second snapshot passage for the projection test.",
            confirmed_persona=True,
        )
        _session, csrf = login(client)
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": f"wave4-sql-round-count-{round_count}"}),
            json={
                "topic": "How should communities discuss fairness in technology?",
                "participants": [
                    {"agent_id": first_agent, "stance_mode": "open"},
                    {"agent_id": second_agent, "stance_mode": "open"},
                ],
                "rule_set_id": RULE_SET,
                "round_count": round_count,
            },
        )
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["rule_set_id"] == RULE_SET
        assert payload["round_count"] == round_count
        detail = client.get(f"/api/v1/debates/{payload['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["round_count"] == round_count


def test_every_new_debate_requires_confirmed_persona_but_legacy_history_stays_compatible(
    app_factory: object,
) -> None:
    from fastapi.testclient import TestClient

    from tests.conftest import login
    from tests.test_wave3_mock_rag_delta import (
        COURSE_ID,
        GROUP_BOWEN_ID,
        GROUP_KAIKAI_ID,
        _headers,
        _insert_sql_published_agent,
    )

    app, database, _settings = app_factory()  # type: ignore[operator]
    with TestClient(app) as client:
        first = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Legacy Persona A",
            evidence="A legacy immutable snapshot.",
            confirmed_persona=False,
        )
        second = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Legacy Persona B",
            evidence="A second legacy immutable snapshot.",
            confirmed_persona=False,
        )
        _session, csrf = login(client)
        payload = {
            "topic": "How should communities discuss fairness in technology?",
            "participants": [
                {"agent_id": first, "stance_mode": "open"},
                {"agent_id": second, "stance_mode": "open"},
            ],
            "rule_set_id": RULE_SET,
            "round_count": 2,
        }
        rejected = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave4-persona-required"}),
            json=payload,
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "persona_confirmation_required"

        legacy = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave4-persona-legacy-ok"}),
            json={
                **payload,
                "rule_set_id": "ordered_multi_agent_rounds_demo_v2",
            },
        )
        assert legacy.status_code == 422, legacy.text
        assert legacy.json()["code"] == "persona_confirmation_required"


def _opening_result(turn_id: str, evidence_ids: Sequence[str] = ()) -> MutualLearningTurnResultV1:
    return MutualLearningTurnResultV1(
        speech=" ".join(["opening"] * 80),
        key_claims=[
            KeyClaimV1(
                claim_id=f"{turn_id}:claim-1",
                claim_text="A value judgement about agency.",
                claim_type="value_judgement",
                used_evidence_ids=list(evidence_ids),
            ),
            KeyClaimV1(
                claim_id=f"{turn_id}:claim-2",
                claim_text="A proposal for transparent safeguards.",
                claim_type="proposal",
            ),
        ],
        position_summary="An independent opening position.",
        position_update="unchanged",
        remaining_uncertainty=["Local effects remain uncertain."],
        missing_information=["Local impact details are missing."],
        used_evidence_id=list(evidence_ids),
    )


def _ready(
    turn_id: str,
    participant_id: str,
    round_no: int,
    turn_index: int,
    result: MutualLearningTurnResultV1,
) -> FinalReadyTurn:
    return FinalReadyTurn(
        turn_id=turn_id,
        participant_id=participant_id,
        snapshot_id=f"snapshot-{participant_id}",
        round_no=round_no,
        turn_index=turn_index,
        speech=result.speech,
        structured=result,
        retrieval_status="no_match",
        grounding_mode="general_reasoning",
        used_receipts=(),
        predecessor_turn_ids=(),
        cutoff_turn_index=-1,
        transcript_hash="hash",
        attempt=1,
    )


def test_validator_accepts_all_relations_but_requires_prior_claim_engagement() -> None:
    first = _ready("turn-0", "participant-0", 1, 0, _opening_result("turn-0"))
    second = _ready("turn-1", "participant-1", 1, 1, _opening_result("turn-1"))
    person = participant(1)
    plan = MutualLearningPolicy().plan([participant(0), person], round_count=3)[3]
    validator = MutualLearningValidator()
    for relation in ("agree", "extend", "qualify", "challenge", "reconcile"):
        result = MutualLearningTurnResultV1(
            speech=" ".join(["exchange"] * 80) + " What would you test next?",
            key_claims=[
                KeyClaimV1(
                    claim_id="exchange:claim",
                    claim_text="A proposal for review.",
                    claim_type="proposal",
                )
            ],
            engagements=[
                EngagementV1(
                    target_turn_id=first.turn_id,
                    target_claim_id="turn-0:claim-1",
                    relation=relation,  # type: ignore[arg-type]
                    faithful_summary="The opening claim centers agency.",
                    response_summary="I respond while preserving room for review.",
                )
            ],
            position_summary="A clarified exchange position.",
            position_update="clarified",
            position_update_reason="The earlier claim clarified the trade-off.",
            remaining_uncertainty=["Implementation remains uncertain."],
            question=TurnQuestion(
                type="agent",
                target_participant_id="participant-0",
                text="What would you test next?",
            ),
        )
        validator.validate(
            result,
            plan=plan,
            participant=person,
            participants=(participant(0), person),
            predecessors=(first, second),
        )
    invalid = result.model_copy(update={"engagements": []})
    with pytest.raises(TurnValidationError):
        validator.validate(
            invalid,
            plan=plan,
            participant=person,
            participants=(participant(0), person),
            predecessors=(first, second),
        )


def test_validator_rejects_same_future_or_missing_engagement_targets() -> None:
    first = _ready("turn-0", "participant-0", 1, 0, _opening_result("turn-0"))
    same = _ready("turn-2", "participant-0", 2, 2, _opening_result("turn-2"))
    person = participant(1)
    plan = MutualLearningPolicy().plan([participant(0), person], round_count=3)[3]
    base = MutualLearningTurnResultV1(
        speech=" ".join(["exchange"] * 80),
        key_claims=[KeyClaimV1(claim_id="claim", claim_text="A proposal.", claim_type="proposal")],
        engagements=[
            EngagementV1(
                target_turn_id="turn-0",
                relation="agree",
                faithful_summary="A faithful opening summary.",
                response_summary="A reasoned response.",
            )
        ],
        position_summary="Updated position.",
        position_update="unchanged",
        position_update_reason="The prior view still fits.",
        remaining_uncertainty=["More context is needed."],
        question=TurnQuestion(
            type="agent", target_participant_id="participant-0", text="What do you think?"
        ),
    )
    validator = MutualLearningValidator()
    for target, predecessors in (
        (same.turn_id, (first, same)),
        ("future", (first,)),
        ("missing", (first,)),
    ):
        with pytest.raises(TurnValidationError):
            validator.validate(
                base.model_copy(
                    update={
                        "engagements": [
                            EngagementV1(
                                target_turn_id=target,
                                relation="agree",
                                faithful_summary="A faithful summary.",
                                response_summary="A response.",
                            )
                        ]
                    }
                ),
                plan=plan,
                participant=person,
                participants=(participant(0), person),
                predecessors=predecessors,
            )


def test_final_rules_and_question_queue_are_enforced_once() -> None:
    turns = generated_turns(2, 3)
    people = (participant(0), participant(1))
    final_plan = MutualLearningPolicy().plan(people, round_count=3)[-2]
    final = turns[-2]
    assert isinstance(final.structured, MutualLearningTurnResultV1)
    assert final.structured.question.type == "none"
    assert final.structured.learned_from_others
    assert final.structured.change_from_opening
    assert final.structured.final_recommendation
    bad = final.structured.model_copy(
        update={
            "question": TurnQuestion(
                type="agent", target_participant_id="participant-1", text="Why?"
            )
        }
    )
    with pytest.raises(TurnValidationError):
        MutualLearningValidator().validate(
            bad,
            plan=final_plan,
            participant=people[0],
            participants=people,
            predecessors=turns[:-2],
        )
    for missing_final_field in (
        {"learned_from_others": []},
        {"change_from_opening": None},
        {"final_recommendation": None},
        {"remaining_uncertainty": []},
    ):
        with pytest.raises(TurnValidationError):
            MutualLearningValidator().validate(
                final.structured.model_copy(update=missing_final_field),
                plan=final_plan,
                participant=people[0],
                participants=people,
                predecessors=turns[:-2],
            )

    exchange = turns[3]
    assert exchange.structured.question.type == "agent"
    # A question becomes pending only when the next round's context is built.
    next_plan = MutualLearningPolicy().plan(people, round_count=3)[-2]
    context = GenerationContext(
        debate_id="d",
        topic="Topic",
        turn=next_plan,
        participant=people[0],
        participants=people,
        predecessors=turns[:-2],
    )
    pending = context.effective_pending_question
    assert pending is not None
    assert pending.question_id == exchange.question_id
    assert pending.target_participant_id == people[0].participant_id
    assert context.effective_pending_question == pending


def test_evidence_is_current_snapshot_only_and_no_match_has_no_source() -> None:
    current = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-0",
        query_kind="viewpoint",
        query_hash="q" * 64,
        threshold_key="strict",
        rank=1,
        score=0.9,
        chunk_id="chunk-a",
        source_filename="evidence.md",
        text="The current snapshot passage.",
        evidence_id="evidence-a",
    )
    wrong = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-1",
        query_kind="viewpoint",
        query_hash="q" * 64,
        threshold_key="strict",
        rank=1,
        score=0.9,
        chunk_id="chunk-b",
        source_filename="other.md",
        text="Another private passage.",
        evidence_id="evidence-b",
    )
    people = (participant(0), participant(1))
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    result = _opening_result("opening", ["evidence-a"])
    assert MutualLearningValidator().validate(
        result,
        plan=plan,
        participant=people[0],
        participants=people,
        receipts=(current,),
    ).used_receipts == (current,)
    with pytest.raises(TurnValidationError):
        MutualLearningValidator().validate(
            result,
            plan=plan,
            participant=people[0],
            participants=people,
            receipts=(wrong,),
        )
    no_source = _opening_result("opening-no-source")
    assert (
        MutualLearningValidator()
        .validate(
            no_source,
            plan=plan,
            participant=people[0],
            participants=people,
        )
        .grounding_mode
        == "general_reasoning"
    )


def test_strict_trace_construction_fails_closed_instead_of_downgrading_to_empty() -> None:
    """A malformed exact-claim catalog cannot become an ungrounded turn."""

    from app.modules.debates.generation.service import TurnGenerationService

    people = (participant(0), participant(1))
    plan = MutualLearningPolicy().plan(people, round_count=2)[0]
    context = GenerationContext(
        debate_id="d",
        topic="Topic",
        turn=plan,
        participant=people[0],
        participants=people,
    )
    result = MutualLearningTurnResultV1(
        speech=" ".join(["speech"] * 80),
        key_claims=[
            KeyClaimV1(
                claim_id="provider-id",
                claim_text="This claim is absent from speech.",
                claim_type="proposal",
            )
        ],
        position_summary="An opening position.",
        remaining_uncertainty=["More context is needed."],
        missing_information=["Local details are missing."],
    )
    validated = ValidatedTurn(
        result=result,
        retrieval_status="no_match",
        grounding_mode="general_reasoning",
        used_receipts=(),
        public_sources=(),
        word_count=80,
    )
    with pytest.raises(TurnValidationError) as raised:
        TurnGenerationService._attach_mutual_learning_evidence_trace(
            validated,
            context=context,
            receipts=(),
            subqueries=(),
        )
    assert raised.value.code == "span_non_exact"


def test_deterministic_synthesis_preserves_disagreement_and_recommendations() -> None:
    turns = list(generated_turns(2, 2))
    synthesis = build_mutual_learning_synthesis(turns, topic="Topic")
    assert synthesis.direct_answer
    assert synthesis.consensus
    assert synthesis.position_changes
    assert synthesis.recommended_next_steps
    assert not hasattr(synthesis, "agent_md")


def test_memory_playback_plan_respects_frozen_mutual_round_count() -> None:
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            topic="Topic",
            rule_set_id=RULE_SET,
            round_count=5,
            participants=[
                MemoryParticipant(id="a"),
                MemoryParticipant(id="b", order_index=1, slot="B"),
            ],
        )
    )
    turns = repository.ensure_turn_plan(None, debate)
    assert len(turns) == 10
    assert [turn.round_no for turn in turns] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert turns[2].predecessor_turn_ids == ("turn-0", "turn-1")
    assert turns[4].predecessor_turn_ids == tuple(f"turn-{index}" for index in range(4))


def test_mutual_rule_failures_carry_the_position_a_repair_must_change() -> None:
    """A structure repair can only fix what the feedback names.

    The validator raises for a rule, not for a schema shape, so its failing
    position lives on the exception rather than on the mapped response. When it
    was missing, a second attempt received the bare ``rule_invalid`` code and
    had to guess which of several fields to change.
    """

    import re
    from pathlib import Path

    from app.modules.debates.generation.prompt_request import PromptRepairFeedbackV1

    source = (
        Path(__file__).resolve().parents[1]
        / "app/modules/debates/generation/mutual_learning_validator.py"
    ).read_text(encoding="utf-8")

    total = source.count("raise TurnValidationError(")
    annotated = source.count("json_pointers=")
    # Every rule a model can satisfy must name its position. The one exception
    # is the internal round-barrier invariant, which reports a server bug that
    # no provider reply could fix.
    assert total - annotated <= 1, "a mutual-learning rule has no failing position"

    pointers = {
        pointer
        for group in re.findall(r"json_pointers=\(([^)]*)\)", source)
        for pointer in re.findall(r'"([^"]+)"', group)
    }
    assert pointers, "no repair pointers were declared"
    for pointer in pointers:
        # An unusable pointer is silently replaced by the root, which loses the
        # whole benefit, so every declared position must survive the contract.
        PromptRepairFeedbackV1(safe_error_code="rule_invalid", json_pointers=(pointer,))
