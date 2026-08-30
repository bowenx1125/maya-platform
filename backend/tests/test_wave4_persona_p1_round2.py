"""Second-pass Persona bounds and generation fail-closed regressions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest
from app.core.errors import PlatformError
from app.modules.agents.persona import (
    PERSONA_COMPILER_VERSION,
    PersonaIdentity,
    PersonaSpeakingStyle,
    PersonaSpecV1,
    persona_spec_hash,
)
from app.modules.agents.persona_mock import (
    SPEECH_DIMENSION_WORD_LIMIT,
    bounded_dimension_sentence,
)
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    MutualLearningTurnResultV1,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    TurnGenerationService,
    TurnQuestion,
    count_turn_words,
)
from app.modules.debates.generation.mutual_learning_policy import MutualLearningPolicy
from app.modules.debates.generation.retrieval import TurnSubquery
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.providers.llm import MockLLMProvider

_RULE_SET = "ordered_multi_expert_mutual_learning_v1"
_EVIDENCE_TEXT = "A short complete evidence sentence that remains within limits."
_MAX_FIELDS = (
    "role",
    "historical_or_cultural_context",
    "initial_position",
    "tone",
    "argument_pattern",
    "concession_style",
    "question_style",
    "cultural_lens",
    "core_values",
    "debate_strategy",
    "boundaries",
)


def _max_text(prefix: str, limit: int) -> str:
    """Build a legal value at the exact character boundary."""

    words = [f"{prefix}{index}" for index in range(limit)]
    value = " ".join(words)
    return value[:limit].rstrip()


def _max_list(prefix: str) -> tuple[str, ...]:
    return tuple(_max_text(f"{prefix}{index}-", 240) for index in range(8))


def _persona(*, max_field: str | None = None) -> PersonaSpecV1:
    role: str = "Classroom technology ethics expert"
    historical: str = "A fictional cross-cultural classroom perspective."
    initial: str = "Prefer evidence-aware proportional safeguards."
    tone: str = "Careful and respectful"
    argument: str = "State a claim, examine evidence, then qualify it"
    concession: str = "Acknowledge a sound point before refining it"
    question: str = "Ask one focused and answerable question"
    cultural: tuple[str, ...] = ("Community accountability",)
    values: tuple[str, ...] = ("Fairness", "Transparency")
    strategy: tuple[str, ...] = ("Compare trade-offs without manufacturing conflict",)
    boundaries: tuple[str, ...] = ("Never invent evidence outside the assigned snapshot",)

    if max_field == "role":
        role = _max_text("role-", 120)
    elif max_field == "historical_or_cultural_context":
        historical = _max_text("context-", 1_000)
    elif max_field == "initial_position":
        initial = _max_text("position-", 1_000)
    elif max_field == "tone":
        tone = _max_text("tone-", 240)
    elif max_field == "argument_pattern":
        argument = _max_text("argument-", 240)
    elif max_field == "concession_style":
        concession = _max_text("concession-", 240)
    elif max_field == "question_style":
        question = _max_text("question-", 240)
    elif max_field == "cultural_lens":
        cultural = _max_list("lens-")
    elif max_field == "core_values":
        values = _max_list("value-")
    elif max_field == "debate_strategy":
        strategy = _max_list("strategy-")
    elif max_field == "boundaries":
        boundaries = _max_list("boundary-")
    elif max_field is not None:
        raise AssertionError(f"unknown max Persona field: {max_field}")

    return PersonaSpecV1(
        identity=PersonaIdentity(
            name="Bounded Expert",
            role=role,
            historical_or_cultural_context=historical,
        ),
        cultural_lens=cultural,
        core_values=values,
        initial_position=initial,
        speaking_style=PersonaSpeakingStyle(
            tone=tone,
            argument_pattern=argument,
            concession_style=concession,
            question_style=question,
        ),
        debate_strategy=strategy,
        boundaries=boundaries,
        source_agent_md_hash="sha256:" + "0" * 64,
        compiler_version=PERSONA_COMPILER_VERSION,
    )


@dataclass(frozen=True)
class _FixedRetriever:
    """Provider-free retriever retaining server-derived source locators."""

    evidence_text: str = _EVIDENCE_TEXT

    def retrieve(self, snapshot_id: str, subqueries: Sequence[TurnSubquery | str]) -> object:
        query = subqueries[0]
        return SimpleNamespace(
            receipts=(
                SnapshotRetrievalReceipt(
                    snapshot_id=snapshot_id,
                    query_kind=str(getattr(query, "query_kind", "viewpoint")),
                    query_hash=str(getattr(query, "query_hash", "query-hash")),
                    threshold_key="strict",
                    rank=1,
                    score=1.0,
                    chunk_id=f"chunk-{snapshot_id}",
                    source_filename="assigned-evidence.md",
                    text=self.evidence_text,
                    evidence_id=f"receipt-{snapshot_id}",
                    source_document_id=f"document-{snapshot_id}",
                    source_start_offset=0,
                    source_end_offset=len(self.evidence_text),
                ),
            )
        )


def _participants(
    persona: PersonaSpecV1,
    *,
    first_name: str = "Expert 0",
) -> tuple[ParticipantContext, ...]:
    other = _persona()
    return tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=first_name if index == 0 else f"Expert {index}",
            slot=chr(65 + index),
            order_index=index,
            snapshot_id=f"snapshot-{index}",
            persona=current,
            persona_spec_hash=persona_spec_hash(current),
        )
        for index, current in enumerate((persona, other))
    )


def _generate_three_protocol_phases(
    persona: PersonaSpecV1,
    *,
    first_name: str = "Expert 0",
    pending_text: str | None = None,
    evidence_text: str = _EVIDENCE_TEXT,
) -> tuple[FinalReadyTurn, ...]:
    people = _participants(persona, first_name=first_name)
    plans = MutualLearningPolicy().plan(people, round_count=3)

    def generate(
        index: int,
        predecessors: tuple[FinalReadyTurn, ...],
    ) -> FinalReadyTurn:
        participant = people[index % len(people)]
        context = GenerationContext(
            debate_id="persona-p1-round2",
            topic="How should a community share a scarce resource?",
            turn=plans[index],
            participant=participant,
            participants=people,
            predecessors=predecessors,
        )
        return TurnGenerationService(
            _FixedRetriever(evidence_text=evidence_text),
            MockLLMProvider(),
            rule_set_id=_RULE_SET,
        ).generate(context).final_ready

    opening_a = generate(0, ())
    opening_b = generate(1, ())
    opening = (opening_a, opening_b)
    exchange_a = generate(2, opening)
    exchange_b = generate(3, opening)
    if pending_text is not None:
        exchange_b = replace(
            exchange_b,
            structured=exchange_b.structured.model_copy(
                update={
                    "question": TurnQuestion(
                        type="agent",
                        target_participant_id=people[0].participant_id,
                        text=pending_text,
                    )
                }
            ),
        )
    exchange = (exchange_a, exchange_b)
    final_a = generate(4, opening + exchange)
    return (opening_a, exchange_a, final_a)


@pytest.mark.parametrize("max_field", _MAX_FIELDS)
def test_max_persona_field_keeps_all_strict_mock_phases_bounded_and_traceable(
    max_field: str,
) -> None:
    opening, exchange, final = _generate_three_protocol_phases(_persona(max_field=max_field))
    for result in (opening, exchange, final):
        speech = result.speech
        question = result.structured.question
        question_text = question.text if question.type != "none" else None
        assert 80 <= count_turn_words(speech, question_text) <= 200
        assert speech.strip().endswith((".", "!", "?"))
        assert result.evidence_trace
        assert isinstance(result.structured, MutualLearningTurnResultV1)
        assert result.structured.used_evidence_ids == (result.used_receipts[0].evidence_id,)
        assert all(row["turn_id"] == result.turn_id for row in result.evidence_trace)


def test_combined_max_persona_fields_have_a_small_complete_projection() -> None:
    persona = _persona(max_field="tone")
    # Exercise all bounded scalar/list dimensions together, including the
    # exact list cardinality and item character limits.
    persona = persona.model_copy(
        update={
            "identity": persona.identity.model_copy(
                update={
                    "role": _max_text("role-", 120),
                    "historical_or_cultural_context": _max_text("context-", 1_000),
                }
            ),
            "cultural_lens": _max_list("lens-"),
            "core_values": _max_list("value-"),
            "initial_position": _max_text("position-", 1_000),
            "speaking_style": PersonaSpeakingStyle(
                tone=_max_text("tone-", 240),
                argument_pattern=_max_text("argument-", 240),
                concession_style=_max_text("concession-", 240),
                question_style=_max_text("question-", 240),
            ),
            "debate_strategy": _max_list("strategy-"),
            "boundaries": _max_list("boundary-"),
        }
    )
    results = _generate_three_protocol_phases(persona)
    assert all(80 <= count_turn_words(item.speech) <= 200 for item in results)
    assert all(item.evidence_trace for item in results)


_WORST_CASES = ("identity", "pending_question", "receipt", "all")


@pytest.mark.parametrize("worst_case", _WORST_CASES)
def test_worst_prompt_text_projections_leave_strict_word_budget_headroom(
    worst_case: str,
) -> None:
    long_identity = "Long Expert Name " + "authored descriptor " * 10
    long_pending = "What " + "question context " * 100 + "should we test?"
    long_receipt = "A receipt passage " + "with assigned context " * 100 + "."
    results = _generate_three_protocol_phases(
        _persona(max_field="tone"),
        first_name=long_identity if worst_case in {"identity", "all"} else "Expert 0",
        pending_text=long_pending if worst_case in {"pending_question", "all"} else None,
        evidence_text=long_receipt if worst_case in {"receipt", "all"} else _EVIDENCE_TEXT,
    )
    assert all(80 <= count_turn_words(item.speech) <= 190 for item in results)
    assert all(item.speech.strip().endswith(".") for item in results)


def test_long_dimension_projection_preserves_complete_sentence_boundary() -> None:
    value = " ".join(f"descriptor-{index}" for index in range(40))
    sentence = bounded_dimension_sentence("tone", value)
    assert sentence.endswith(".")
    assert len(sentence.split()) <= 12
    assert "descriptor" in sentence
    assert "39" not in sentence
    assert SPEECH_DIMENSION_WORD_LIMIT == 8


@pytest.mark.parametrize(
    "rule_set_id",
    (
        "ordered_multi_agent_rounds_demo_v1",
        "ordered_multi_agent_rounds_demo_v2",
        _RULE_SET,
    ),
)
def test_sql_adapter_rejects_unconfirmed_running_legacy_or_mutual_before_provider(
    app_factory: object,
    rule_set_id: str,
) -> None:
    """A migration-era pending run fails closed before retrieval or Mock calls."""

    from app.core.models import AgentVersion
    from app.modules.debates.models import Debate, DebateParticipant
    from app.modules.debates.setup.rules import canonical_rule_snapshot_json
    from app.modules.debates.setup.service import commit_start_plan
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from tests.conftest import login
    from tests.test_wave3_mock_rag_delta import (
        COURSE_ID,
        GROUP_BOWEN_ID,
        GROUP_KAIKAI_ID,
        _headers,
        _insert_sql_published_agent,
    )

    app, database, settings = app_factory()  # type: ignore[operator]
    with TestClient(app) as client:
        first = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name=f"Pending Legacy A {rule_set_id[-2:]}",
            evidence="A bounded source passage for the migration-era pending run.",
            confirmed_persona=True,
        )
        second = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name=f"Pending Legacy B {rule_set_id[-2:]}",
            evidence="A second bounded source passage for the migration-era pending run.",
            confirmed_persona=True,
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(
                csrf,
                **{"Idempotency-Key": f"persona-p1-round2-{rule_set_id}"},
            ),
            json={
                "topic": "How should communities discuss fairness in technology?",
                "participants": [
                    {"agent_id": first, "stance_mode": "open"},
                    {"agent_id": second, "stance_mode": "open"},
                ],
                "rule_set_id": _RULE_SET,
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            # Write the deterministic plan while the current integration
            # Persona is still confirmed, then model the pre-activation
            # running row: old Persona columns are all NULL and only pending
            # turns remain.  No historical row is rewritten by production code.
            turns = commit_start_plan(db, debate_id=debate_id)
            assert len(turns) == 4
            debate.rule_set_id = rule_set_id
            debate.rule_snapshot_json = canonical_rule_snapshot_json(
                rule_set_id=rule_set_id  # type: ignore[arg-type]
            )
            debate.status = "running"
            participant_rows = list(
                db.scalars(
                    select(DebateParticipant)
                    .where(DebateParticipant.debate_id == debate_id)
                    .order_by(DebateParticipant.order_index)
                ).all()
            )
            assert len(participant_rows) == 2
            for participant in participant_rows:
                version = db.get(AgentVersion, participant.agent_version_id)
                assert version is not None
                version.raw_agent_md_hash = None
                version.persona_spec_json = None
                version.persona_spec_hash = None
                version.persona_compiler_version = None
                version.persona_diagnostics_json = None
                version.persona_confirmation_revision = None
                version.student_confirmed_at = None
                version.persona_confirming_user_id = None
            db.flush()
            assert all(turn.generation_status == "pending" for turn in turns)
            llm = MockLLMProvider()
            with pytest.raises(PlatformError) as raised:
                SqlTurnPreparer(settings=settings, llm=llm)(
                    db,
                    debate,
                    turns[0],
                    attempt=1,
                    cancellation_generation=0,
                )
            assert raised.value.code == "persona_confirmation_required"
            assert raised.value.details == {
                "agent_version_ids": [row.agent_version_id for row in participant_rows]
            }
            assert llm.call_count == 0
