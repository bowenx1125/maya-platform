"""Complete offline lessons through the actual generation and paragraph protocol."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from app.modules.debates.generation.four_round import body_count
from app.modules.debates.generation.mutual_learning_policy import MutualLearningPolicy
from app.modules.debates.generation.mutual_learning_prompts import compute_mutual_transcript_hash
from app.modules.debates.generation.retrieval import RetrievalResult
from app.modules.debates.generation.segments import load_stored_segment_turn_result
from app.modules.debates.generation.service import TurnGenerationService
from app.modules.debates.generation.types import GenerationContext, ParticipantContext
from app.modules.debates.playback.audio import AudioStore
from app.providers.llm import MockLLMProvider
from app.providers.tts import MockTTSProvider

from tests.test_segments_protocol import _persona, _receipt


class RecordingRetrieval:
    def __init__(self):
        self.calls = []

    def retrieve(self, snapshot_id, queries):
        self.calls.append((snapshot_id, queries))
        receipt = replace(
            _receipt(
                snapshot_id,
                f"{snapshot_id}-{len(self.calls)}",
                "A classroom trial recorded who could question its evidence.",
            ),
            query_kind=queries[0].query_kind,
            query_hash=queries[0].query_hash,
        )
        return RetrievalResult(snapshot_id, (receipt,), queries, 1, 0)


class RecordingMock(MockLLMProvider):
    def __init__(self):
        super().__init__()
        self.snapshots = []

    def generate_segments(self, snapshot, *, repair_feedback=None):
        self.snapshots.append(snapshot)
        return super().generate_segments(snapshot, repair_feedback=repair_feedback)


@pytest.mark.parametrize("agent_count", [2, 3])
@pytest.mark.parametrize("language", ["en", "zh"])
@pytest.mark.parametrize("with_barrages", [False, True])
def test_complete_four_round_lesson_freezes_inputs_and_preserves_metadata(
    agent_count, language, with_barrages, tmp_path
):
    people = tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=f"Agent {chr(65 + index)}",
            slot=chr(65 + index),
            order_index=index,
            snapshot_id=f"snapshot-{index}",
            persona=_persona(),
        )
        for index in range(agent_count)
    )
    plan = MutualLearningPolicy().plan(people, round_count=4, teaching_protocol="four_round_v1")
    retrieval = RecordingRetrieval()
    llm = RecordingMock()
    generator = TurnGenerationService(
        retrieval, llm, rule_set_id="ordered_multi_expert_mutual_learning_v1"
    )
    turns = []
    tts = MockTTSProvider()
    audio = AudioStore(tmp_path, tts_provider=tts)
    course_id, debate_id = str(uuid4()), str(uuid4())
    saved_audio = []
    for entry in plan:
        owner = next(person for person in people if person.participant_id == entry.participant_id)
        barrages = (
            ({"id": "B1", "text": "How can a quiet student challenge the evidence?"},)
            if with_barrages and entry.round_no == 4
            else ()
        )
        context = GenerationContext(
            debate_id="offline-teaching",
            topic="How should a classroom use evidence?",
            turn=entry,
            participant=owner,
            participants=people,
            predecessors=tuple(turns),
            output_language=language,
            turn_protocol="segments_v2",
            round_count=4,
            teaching_protocol="four_round_v1",
            barrages=barrages,
        )
        calls_before = len(retrieval.calls)
        final = generator.generate(context).final_ready
        snapshot = llm.snapshots[-1]
        # The backend no longer bounds a speech; the round guidance exists only
        # in the Prompt, so this asserts readable output inside that guidance.
        guidance = {"zh": [500, 450, 550, 650], "en": [320, 280, 350, 420]}
        high = guidance[language][entry.round_no - 1]
        assert 0 < body_count(final.speech, language) <= high
        assert final.attempt == 1
        # Every round now retrieves from the current Agent's own RAG. The
        # round-specific query changes emphasis; it does not disable RAG.
        assert len(retrieval.calls) - calls_before == 1
        assert retrieval.calls[-1][0] == owner.snapshot_id
        assert len(snapshot.history) == (0 if entry.round_no == 1 else entry.turn_index)
        if entry.round_no == 1:
            assert {receipt.snapshot_id for receipt in snapshot.receipts} == {owner.snapshot_id}
        if entry.round_no == 2:
            question = final.structured.question
            assert question["target_agent_id"] == entry.next_participant_id
            assert question["text"] in final.speech
        if entry.round_no == 3:
            received = snapshot.discussion["received_questions"]
            assert len(received) == 1
            assert received[0]["text"] in " ".join(query.text for query in retrieval.calls[-1][1])
            assert final.structured.discussion_memory["change"] == "qualified"
        if entry.round_no == 4:
            assert len(snapshot.discussion["memories"]) == agent_count
            assert bool(final.structured.segments[0].reply_to) is with_barrages
            assert final.structured.discussion_memory is None
        stored = load_stored_segment_turn_result(final.structured.as_stored_payload())
        reloaded = replace(final, structured=stored)
        assert compute_mutual_transcript_hash((final,)) == compute_mutual_transcript_hash(
            (reloaded,)
        )
        assert final.speech == stored.speech
        if entry.round_no < 4:
            metadata = audio.synthesize_and_store(
                course_id=course_id,
                debate_id=debate_id,
                turn_id=str(uuid4()),
                speech=stored.speech,
                voice_token="mock",
                language=language,
            )
            assert tts.last_text == final.speech
            assert metadata.duration_ms > 0
            saved_audio.append(metadata)
        turns.append(reloaded)
    assert len(turns) == agent_count * 4
    assert llm.calls == agent_count * 4
    assert len(retrieval.calls) == agent_count * 4
    assert tts.synthesize_calls == agent_count * 3
    reloaded_audio = AudioStore(tmp_path, tts_provider=tts)
    for metadata in saved_audio:
        assert reloaded_audio.read(debate_id, metadata.turn_id) == audio.read(
            debate_id, metadata.turn_id
        )
    assert tts.synthesize_calls == agent_count * 3
    assert llm.calls == agent_count * 4
