"""Offline checks of teaching inputs, metadata and exact body boundaries."""

from dataclasses import replace

import pytest
from app.modules.debates.generation import GenerationContext, MutualLearningPolicy
from app.modules.debates.generation.four_round import BODY_LIMITS, body_count, visible_predecessors
from app.modules.debates.generation.mutual_learning_prompts import compute_mutual_transcript_hash
from app.modules.debates.generation.retrieval import build_turn_subqueries
from app.modules.debates.generation.segments import (
    SegmentProtocolError,
    StoredSegment,
    StoredSegmentTurnResult,
    build_segment_input,
    build_segment_system_prompt,
    load_segment_turn_result,
    validate_segment_output,
)

from tests.test_segments_protocol import _participants, _ready, _receipt


def context(round_no=1, language="en", predecessors=()):
    people = _participants()
    plans = MutualLearningPolicy().plan(people, round_count=4, teaching_protocol="four_round_v1")
    plan = next(item for item in plans if item.round_no == round_no)
    person = next(item for item in people if item.participant_id == plan.participant_id)
    if plan.barrier == "prefix":
        provided = {item.turn_index: item for item in predecessors}
        predecessors = tuple(
            provided.get(item.turn_index)
            or _ready(
                item.turn_id,
                item.participant_id,
                item.round_no,
                item.turn_index,
                "An already completed discussion point.",
            )
            for item in plans
            if item.turn_index < plan.turn_index
        )
    return GenerationContext(
        debate_id="test",
        topic="How should shared water be managed?",
        turn=plan,
        participant=person,
        participants=people,
        predecessors=predecessors,
        round_count=4,
        turn_protocol="segments_v2",
        teaching_protocol="four_round_v1",
        output_language=language,
    )


def output(snapshot, count):
    discussion = snapshot.discussion
    return {
        "segments": [
            {
                "text": "水。" * (count // 2) + ("水" if count % 2 else "")
                if snapshot.language == "zh"
                else " ".join(["evidence"] * count),
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ],
        "question": {
            "target_agent_id": discussion["question_target_id"],
            "text": "How would your plan share water?",
        }
        if snapshot.round.number == 2
        else None,
        "discussion_memory": {
            "position": "Keep shared access.",
            "change": "qualified",
            "reason": "The other Agent identified scarcity.",
            "influence": {"agent_id": "participant-1", "point": "Account for dry seasons."},
            "unresolved_question": "Who decides the threshold?",
        }
        if snapshot.round.number == 3
        else None,
    }


@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("round_no", [1, 2, 3, 4])
def test_exact_body_boundaries_count_only_displayed_paragraphs(language, round_no):
    ctx = context(round_no, language)
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    _, high = BODY_LIMITS[language][round_no - 1]
    for count in (1, high, high + 1):
        value = output(snapshot, count)
        result = validate_segment_output(value, snapshot)
        assert body_count(result.speech, language) == count
        assert result.speech == value["segments"][0]["text"]
        loaded = load_segment_turn_result(result.as_stored_payload(), snapshot)
        assert loaded.output == result.output
    assert f"最多{high}" in build_segment_system_prompt(snapshot)


def test_counter_punctuation_whitespace_and_english_compounds():
    assert body_count("水，\n 风。 ", "zh") == 4
    assert body_count("Don't re-read evidence-based claims, please!", "en") == 5


def test_context_is_independent_then_sequential_with_linked_sources():
    own = _receipt("snapshot-0", "chunk-a", "A shared canal is maintained in winter.")
    other = _receipt("snapshot-1", "chunk-b", "Dry seasons reduce the flow.")
    a = _ready("turn-0", "participant-0", 1, 0, "First opening")
    a = replace(
        a,
        retrieval_status="matched",
        grounding_mode="rag_grounded",
        used_receipts=(own,),
        structured=a.structured.model_copy(
            update={"used_evidence_id": [own.resolved_evidence_id()]}
        ),
    )
    b = _ready("turn-1", "participant-1", 1, 1, "Second opening")
    b = replace(
        b,
        retrieval_status="matched",
        grounding_mode="rag_grounded",
        snapshot_id="snapshot-1",
        used_receipts=(other,),
        structured=b.structured.model_copy(
            update={"used_evidence_id": [other.resolved_evidence_id()]}
        ),
    )
    assert visible_predecessors(context(1, predecessors=(a,))) == ()
    current = _ready("turn-2", "participant-1", 2, 2, "An actual same-round question.")
    discussion = replace(
        context(2), turn=replace(context(2).turn, turn_index=3), predecessors=(a, b, current)
    )
    snapshot = build_segment_input(discussion, persona=discussion.participant.persona)
    assert [item.text for item in snapshot.history][-1] == current.speech
    assert snapshot.history[0].source_ids == ("S1",)
    assert snapshot.history[1].source_ids == ("S2",)
    assert snapshot.receipts == (own, other)
    assert build_turn_subqueries(discussion) == ()
    assert build_turn_subqueries(context(4)) == ()


def test_response_query_contains_actual_question_and_memory_changes_hash():
    ctx = context(3)
    question = {
        "target_agent_id": ctx.participant.participant_id,
        "text": "Who closes the canal during the dry season?",
    }
    predecessor = replace(
        _ready("turn-3", "participant-1", 2, 3, "Explain dry-season control."),
        structured=StoredSegmentTurnResult(
            segments=(StoredSegment("Explain dry-season control.", (), None),),
            speech="Explain dry-season control.",
            question=question,
        ),
    )
    ctx = context(3, predecessors=(predecessor,))
    queries = build_turn_subqueries(ctx)
    assert len(queries) == 1
    assert question["text"] in queries[0].text
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    assert snapshot.discussion["received_questions"][0]["text"] == question["text"]
    result = validate_segment_output(output(snapshot, 70), snapshot)
    turn = replace(
        predecessor,
        round_no=3,
        turn_index=4,
        speech=result.speech,
        structured=result.to_stored_result(),
    )
    changed = replace(
        turn,
        structured=replace(
            result.to_stored_result(),
            discussion_memory={**result.discussion_memory, "reason": "A changed rationale."},
        ),
    )
    assert compute_mutual_transcript_hash((turn,)) != compute_mutual_transcript_hash((changed,))
    final_ctx = context(4, predecessors=(turn,))
    final = build_segment_input(final_ctx, persona=final_ctx.participant.persona)
    assert final.discussion["memories"][0]["memory"] == result.discussion_memory
    assert "A changed rationale" not in result.speech


def test_question_routing_cannot_use_a_barrage_id():
    ctx = context(2)
    snapshot = build_segment_input(ctx, persona=ctx.participant.persona)
    value = output(snapshot, 60)
    value["question"]["target_agent_id"] = "B1"
    with pytest.raises(SegmentProtocolError) as error:
        validate_segment_output(value, snapshot)
    assert error.value.code == "question_route_invalid"
