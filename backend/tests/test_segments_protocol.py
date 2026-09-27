"""Offline contract tests for the provider-neutral segment protocol."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.modules.agents.persona import PersonaSpecV1, compile_persona_or_raise
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    KeyClaimV1,
    MutualLearningPolicy,
    MutualLearningTurnResultV1,
    ParticipantContext,
    SnapshotRetrievalReceipt,
    TurnGenerationService,
)
from app.modules.debates.generation.retrieval import build_turn_subqueries
from app.modules.debates.generation.segments import (
    SEGMENT_SYSTEM_BRIEF,
    SegmentInputSnapshot,
    SegmentProtocolError,
    SegmentRound,
    SegmentTurnResult,
    build_segment_input,
    build_segment_system_prompt,
    freeze_barrages,
    load_stored_segment_turn_result,
    parse_segment_output_json,
    validate_segment_output,
)
from app.modules.debates.generation.segments_runtime import SegmentLLMRuntime, SegmentRuntimeError
from app.providers.control import InMemoryProviderOperationRepository, ProviderScopeBudgetV1
from app.providers.llm import MockLLMProvider
from app.providers.llm_adapter import LLMUsageV1
from app.providers.llm_privacy import validate_anonymous_barrage_text
from app.providers.llm_segments import (
    SegmentAcceptedCandidateV2,
    SegmentLLMRequestV2,
    SegmentMessageV2,
    load_segment_request_v2,
)
from sqlalchemy import text


def _persona() -> PersonaSpecV1:
    return cast(
        PersonaSpecV1,
        compile_persona_or_raise(
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
        ),
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
            persona=_persona(),
        ),
        ParticipantContext(
            participant_id="participant-1",
            agent_id="agent-1",
            agent_name="Other Persona",
            slot="B",
            order_index=1,
            snapshot_id="snapshot-1",
            persona=_persona(),
        ),
    )


def _ready(
    turn_id: str,
    participant_id: str,
    round_no: int,
    turn_index: int,
    speech: str,
) -> FinalReadyTurn:
    result = MutualLearningTurnResultV1(
        speech=speech,
        key_claims=[
            KeyClaimV1(
                claim_id=f"{turn_id}:claim",
                claim_text=speech,
                claim_type="proposal",
            )
        ],
        position_summary="A public position.",
        used_evidence_id=[],
    )
    return FinalReadyTurn(
        turn_id=turn_id,
        participant_id=participant_id,
        snapshot_id="snapshot-0",
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


def _context(round_no: int = 2) -> GenerationContext:
    people = _participants()
    plans = MutualLearningPolicy().plan(people, round_count=3)
    plan = plans[(round_no - 1) * len(people)]
    return GenerationContext(
        debate_id="debate-1",
        topic="How should a platform protect community agency?",
        turn=plan,
        participant=people[0],
        participants=people,
        predecessors=(
            _ready("turn-0", "participant-0", 1, 0, "The complete first speech remains exact."),
            _ready("turn-1", "participant-1", 1, 1, "A second earlier-round speech remains exact."),
            _ready("turn-2", "participant-0", 2, 2, "Same-round text is not visible."),
        ),
    )


def _receipt(snapshot_id: str, chunk_id: str, text: str) -> SnapshotRetrievalReceipt:
    return SnapshotRetrievalReceipt(
        snapshot_id=snapshot_id,
        query_kind="viewpoint",
        query_hash=f"query-{chunk_id}",
        threshold_key="strict",
        rank=1,
        score=0.8,
        chunk_id=chunk_id,
        source_filename="private-source.md",
        text=text,
    )


def _snapshot(*, round_number: int = 2, barrages: tuple[object, ...] = ()) -> SegmentInputSnapshot:
    receipts = (
        _receipt("snapshot-0", "chunk-a", "A useful evidence excerpt."),
        _receipt("snapshot-0", "chunk-b", "A second candidate receipt."),
    )
    return SegmentInputSnapshot.from_groups(
        topic="How should a platform protect community agency?",
        language="en",
        round_number=round_number,
        round_total=3,
        persona=_persona(),
        history=({"speaker": "River Keeper", "round": 1, "text": "Earlier speech."},),
        receipts=receipts,
        barrages=barrages,
        snapshot_id="snapshot-0",
    )


def test_context_adapter_preserves_complete_prior_rounds_and_display_names() -> None:
    snapshot = build_segment_input(_context(), persona=_persona(), round_total=3)
    assert [item.round for item in snapshot.history] == [1, 1]
    assert [item.speaker for item in snapshot.history] == ["River Keeper", "Other Persona"]
    assert all("participant-" not in item.speaker for item in snapshot.history)
    assert "Same-round text is not visible." not in snapshot.to_user_json()


def test_user_payload_has_only_seven_groups_and_hides_receipt_metadata() -> None:
    snapshot = _snapshot()
    payload = snapshot.to_user_payload()
    assert set(payload) == {
        "topic",
        "language",
        "round",
        "persona",
        "history",
        "sources",
        "barrages",
    }
    encoded = snapshot.to_user_json()
    assert "private-source.md" not in encoded
    assert "query_hash" not in encoded
    assert "snapshot-0" not in encoded
    assert "debate_strategy" not in encoded
    assert "boundaries" not in encoded
    assert payload["sources"] == [
        {"id": "S1", "text": "A useful evidence excerpt."},
        {"id": "S2", "text": "A second candidate receipt."},
    ]


def test_snapshot_is_immutable_and_retains_full_receipts_separately_from_used_subset() -> None:
    snapshot = _snapshot()
    with pytest.raises((AttributeError, TypeError)):
        snapshot.topic = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.source_map["S1"] = snapshot.receipts[1]  # type: ignore[index]
    result = validate_segment_output(
        {"segments": [{"text": "Grounded.", "source_ids": ["S1"], "reply_to": None}]},
        snapshot,
    )
    assert result.used_source_ids == ("S1",)
    assert result.used_receipts == (snapshot.receipts[0],)
    assert snapshot.full_receipts == snapshot.receipts
    assert len(snapshot.full_receipts) == 2


def test_snapshot_loader_round_trips_the_public_payload_with_server_receipts() -> None:
    snapshot = _snapshot()
    loaded = SegmentInputSnapshot.from_user_payload(
        snapshot.to_user_payload(), receipts=snapshot.receipts, snapshot_id="snapshot-0"
    )
    assert loaded.to_user_json() == snapshot.to_user_json()
    assert loaded.receipt_hash == snapshot.receipt_hash


def test_server_snapshot_roundtrip_keeps_full_receipts_out_of_user_json() -> None:
    snapshot = _snapshot()
    server_payload = snapshot.to_server_payload()
    assert set(server_payload) == {"snapshot_id", "receipt_hash", "input", "receipts"}
    assert "query_hash" not in snapshot.to_user_json()
    assert "query_hash" in json.dumps(server_payload, ensure_ascii=False)
    loaded = SegmentInputSnapshot.from_server_payload(server_payload)
    assert loaded.to_user_json() == snapshot.to_user_json()
    assert loaded.receipts == snapshot.receipts
    with pytest.raises(SegmentProtocolError) as error:
        SegmentInputSnapshot.from_server_payload({**server_payload, "receipt_hash": "0" * 64})
    assert error.value.code == "receipt_hash_invalid"


def test_frozen_segment_request_loader_rebuilds_snapshot_without_provider_wire_data() -> None:
    snapshot = _snapshot()
    message = SegmentMessageV2(role="user", content=snapshot.to_user_json())
    request = SegmentLLMRequestV2(
        snapshot=snapshot,
        endpoint="https://offline.invalid/segments",
        method="POST",
        body={"secret": "omitted"},
        messages=(message, message),
        budget=SimpleNamespace(),
        request_hash="a" * 64,
        schema_hash="b" * 64,
        prompt_hash=snapshot.input_hash,
        debate_id="debate-1",
        turn_id="turn-2",
        generation_fence="fence",
        policy_hash="c" * 64,
        export_manifest_hash="d" * 64,
        build_manifest_hash="e" * 64,
    )
    frozen = request.frozen_payload()
    assert "body" not in frozen and "endpoint" not in frozen
    loaded = load_segment_request_v2(frozen)
    assert loaded.snapshot.to_user_json() == snapshot.to_user_json()
    assert loaded.request_hash == request.request_hash
    assert loaded.turn_id == "turn-2"


def test_stored_result_uses_canonical_ids_and_loads_without_the_input_snapshot() -> None:
    snapshot = _snapshot()
    result = validate_segment_output(
        {"segments": [{"text": "Grounded.", "source_ids": ["S2"], "reply_to": None}]},
        snapshot,
    )
    stored = result.as_stored_payload()
    assert set(stored) == {"schema_version", "segments"}
    assert stored["schema_version"] == "segment_turn_v2"
    assert stored["segments"] == [
        {
            "text": "Grounded.",
            "source_ids": [snapshot.receipts[1].resolved_evidence_id()],
            "reply_to": None,
        }
    ]
    loaded = load_stored_segment_turn_result(stored)
    assert loaded.speech == "Grounded."
    assert loaded.used_evidence_ids == (snapshot.receipts[1].resolved_evidence_id(),)
    assert loaded.lineage[0].speech_span == (0, len("Grounded."))
    with pytest.raises(SegmentProtocolError):
        load_stored_segment_turn_result(
            {
                **stored,
                "segments": [
                    {
                        "text": "Grounded.",
                        "source_ids": [
                            snapshot.receipts[1].resolved_evidence_id(),
                            snapshot.receipts[1].resolved_evidence_id(),
                        ],
                        "reply_to": None,
                    }
                ],
            }
        )


def test_output_joins_paragraphs_exactly_and_returns_lineage_offsets() -> None:
    snapshot = _snapshot()
    result = validate_segment_output(
        {
            "segments": [
                {"text": "First paragraph.", "source_ids": [], "reply_to": None},
                {"text": "第二段。", "source_ids": ["S2"], "reply_to": None},
            ]
        },
        snapshot,
    )
    assert result.speech == "First paragraph.\n\n第二段。"
    assert result.lineage[0].speech_span == (0, len("First paragraph."))
    assert result.lineage[1].speech_span == (len("First paragraph.") + 2, len(result.speech))
    assert result.lineage[1].source_ids == ("S2",)


def test_empty_sources_and_short_text_are_valid_without_a_word_minimum() -> None:
    result = validate_segment_output(
        {"segments": [{"text": "x", "source_ids": [], "reply_to": None}]}, _snapshot()
    )
    assert result.speech == "x"


def test_unknown_source_metadata_does_not_discard_speech_or_bind_external_evidence() -> None:
    snapshot = _snapshot()
    result = validate_segment_output(
        {
            "segments": [
                {"text": "x", "source_ids": [f"S{i}" for i in range(1, 8)], "reply_to": None}
            ]
        },
        snapshot,
    )
    assert result.speech == "x"
    assert result.segments[0].source_ids == ("S1", "S2")


def test_final_reply_is_prompt_only_and_valid_links_are_retained() -> None:
    with_barrage = _snapshot(
        round_number=3,
        barrages=({"id": "B1", "text": "What about local agency?"},),
    )
    without_reply = validate_segment_output(
        {"segments": [{"text": "Conclusion.", "source_ids": [], "reply_to": None}]}, with_barrage
    )
    assert without_reply.speech == "Conclusion."
    assert without_reply.final_reply_to is None
    result = validate_segment_output(
        {"segments": [{"text": "Conclusion.", "source_ids": [], "reply_to": "B1"}]},
        with_barrage,
    )
    assert result.final_reply_to == "B1"
    no_barrage = _snapshot(round_number=3)
    result = validate_segment_output(
        {"segments": [{"text": "Conclusion.", "source_ids": [], "reply_to": None}]}, no_barrage
    )
    assert result.final_reply_to is None


def test_extra_fields_duplicate_refs_and_long_text_do_not_reject_speech() -> None:
    snapshot = _snapshot()
    result = validate_segment_output(
        {
            "extra": "metadata",
            "segments": [
                {"text": "x", "source_ids": ["S1", "S1"], "reply_to": "unknown", "phase": "opening"}
            ],
        },
        snapshot,
    )
    assert result.speech == "x"
    assert result.segments[0].source_ids == ("S1",)
    assert result.segments[0].reply_to is None
    long_segments: list[dict[str, object]] = [
        {"text": "x" * 1000, "source_ids": [], "reply_to": None} for _ in range(8)
    ]
    result = validate_segment_output({"segments": long_segments}, snapshot)
    assert result.speech == "\n\n".join(str(item["text"]) for item in long_segments)


def test_freeze_barrages_applies_cutoff_round_barrier_identity_redaction_and_dedupe() -> None:
    rows = [
        {"round": 1, "sequence": 1, "nickname": "Private", "text": "Ask a@b.com"},
        {"round": 1, "sequence": 2, "nickname": "Private", "text": " Ask   a@b.com "},
        {"round": 1, "sequence": 3, "text": "Late"},
        {"round": 2, "sequence": 2, "text": "Current-round input"},
    ]
    frozen = freeze_barrages(rows, final_round=2, cutoff_sequence=2, identity_tokens=("Private",))
    assert [item.id for item in frozen] == ["B1"]
    assert frozen[0].text == "Ask [redacted email]"
    assert "Private" not in frozen[0].text


def test_segment_retrieval_dispatch_is_focused_and_final_query_covers_every_barrage() -> None:
    context = replace(
        _context(round_no=3),
        turn_protocol="segments_v2",
        round_count=3,
        barrages=(
            {"id": "B1", "text": "Should local knowledge guide policy?"},
            {"id": "B2", "text": "How do we preserve community agency?"},
        ),
    )
    queries = build_turn_subqueries(context)
    assert [item.query_kind for item in queries] == ["updated_position", "rebuttal", "barrage"]
    assert queries[0].text.startswith(context.topic)
    barrage_query = queries[-1].text
    assert all(
        text in barrage_query for text in ("B1", "local knowledge", "B2", "community agency")
    )
    assert "The complete first speech remains exact." not in "\n".join(
        item.text for item in queries
    )
    assert len(queries) <= 3


def test_anonymous_barrage_boundary_keeps_authored_text() -> None:
    assert validate_anonymous_barrage_text("A general classroom question.") == (
        "A general classroom question."
    )
    assert (
        validate_anonymous_barrage_text("Contact private@example.com", identity_tokens=("Private",))
        == "Contact private@example.com"
    )


def test_explicit_segments_service_uses_mock_segment_output_without_legacy_fields() -> None:
    context = replace(
        _context(round_no=2),
        turn_protocol="segments_v2",
        round_count=3,
    )
    receipt = _receipt("snapshot-0", "chunk-v2", "A public evidence excerpt.")

    class _Retriever:
        def retrieve(self, snapshot_id: str, queries: object) -> object:
            assert snapshot_id == "snapshot-0"
            assert len(tuple(queries)) == 3  # type: ignore[arg-type]
            return SimpleNamespace(receipts=(receipt,))

    provider = MockLLMProvider()
    generated = TurnGenerationService(_Retriever(), cast(Any, provider)).generate(context)
    assert provider.call_count == 1
    assert getattr(generated.final_ready.structured, "schema_version", None) == "segment_turn_v2"
    assert generated.final_ready.speech == generated.final_ready.structured.speech
    assert getattr(generated.final_ready.structured, "used_evidence_ids", None) == (
        receipt.resolved_evidence_id(),
    )
    assert not hasattr(generated.final_ready.structured, "key_claims")


def test_segment_result_can_leave_a_retrieval_candidate_unused() -> None:
    context = replace(_context(round_no=2), turn_protocol="segments_v2", round_count=3)
    receipt = _receipt("snapshot-0", "chunk-v2-unused", "A candidate passage.")

    class _Retriever:
        def retrieve(self, snapshot_id: str, queries: object) -> object:
            del queries
            assert snapshot_id == "snapshot-0"
            return SimpleNamespace(receipts=(receipt,))

    generated = TurnGenerationService(
        _Retriever(),
        cast(Any, MockLLMProvider(failures=("matched_but_unused",))),
    ).generate(context)
    assert generated.final_ready.retrieval_status == "matched"
    assert generated.final_ready.grounding_mode == "general_reasoning"
    assert generated.final_ready.used_receipts == ()


def test_segment_runtime_stages_canonical_result_once_before_success() -> None:
    snapshot = _snapshot()
    context = replace(
        _context(round_no=2),
        turn_protocol="segments_v2",
        round_count=3,
    )
    output = {"segments": [{"text": "Stored paragraph.", "source_ids": ["S2"], "reply_to": None}]}

    class _Adapter:
        tokenizer = SimpleNamespace()

        def build_request(
            self, frozen: SegmentInputSnapshot, **kwargs: object
        ) -> SegmentLLMRequestV2:
            message = SegmentMessageV2(role="user", content=frozen.to_user_json())
            return SegmentLLMRequestV2(
                snapshot=frozen,
                endpoint="https://offline.invalid/segments",
                method="POST",
                body={},
                messages=(message, message),
                budget=SimpleNamespace(),
                request_hash="a" * 64,
                schema_hash="b" * 64,
                prompt_hash=frozen.input_hash,
                debate_id=str(kwargs["debate_id"]),
                turn_id=str(kwargs["turn_id"]),
                policy_hash=str(kwargs["policy_hash"]),
                export_manifest_hash=str(kwargs["export_manifest_hash"]),
                build_manifest_hash=str(kwargs["build_manifest_hash"]),
            )

        def send_accepted(self, request: SegmentLLMRequestV2) -> SegmentAcceptedCandidateV2:
            return SegmentAcceptedCandidateV2(
                request=request,
                http_status=200,
                finish_reason="stop",
                usage=LLMUsageV1(1, 0, 1, 2),
                output_json=json.dumps(output, ensure_ascii=False, separators=(",", ":")),
                output_hash="c" * 64,
                provider_output=output,
            )

        def validate_accepted(self, candidate: SegmentAcceptedCandidateV2) -> SegmentTurnResult:
            return validate_segment_output(candidate.provider_output, candidate.request.snapshot)

    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=4,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket="llm_debate_turn",
        )
    )
    runtime = SegmentLLMRuntime(ledger=ledger, adapter=_Adapter())
    prepared = runtime.prepare(
        snapshot,
        debate_id="debate-1",
        turn_id="turn-2",
        policy_hash="d" * 64,
        manifest_hash="e" * 64,
        build_manifest_hash="f" * 64,
    )
    outcome = runtime.run(prepared, context=context, confirmed=True)
    assert outcome.status == "succeeded"
    assert outcome.final_ready is not None
    assert outcome.final_ready.predecessor_turn_ids == ("turn-0", "turn-1")
    assert outcome.operation is not None and cast(Any, outcome.operation).state == "succeeded"
    assert outcome.stage is not None
    stored = json.loads(cast(Any, outcome.stage).output_json)
    assert stored["schema_version"] == "segment_turn_v2"
    assert "key_claims" not in stored
    assert stored["segments"][0]["source_ids"] == [snapshot.receipts[1].resolved_evidence_id()]
    resumed = runtime.resume_accepted_stage(
        outcome.stage,
        snapshot=snapshot,
        context=context,
    )
    assert resumed.status == "succeeded"
    assert resumed.result is not None and resumed.result.used_evidence_ids == (
        snapshot.receipts[1].resolved_evidence_id(),
    )


@pytest.mark.parametrize("state,attempt_no", [("not_sent", 1), ("failed", 2)])
def test_segment_prepare_without_ledger_transition_fails_safely(
    state: str, attempt_no: int
) -> None:
    snapshot = _snapshot()
    message = SegmentMessageV2(role="user", content=snapshot.to_user_json())
    request = SegmentLLMRequestV2(
        snapshot=snapshot,
        endpoint="https://offline.invalid/segments",
        method="POST",
        body={},
        messages=(message, message),
        budget=SimpleNamespace(),
        request_hash="a" * 64,
        schema_hash="b" * 64,
        prompt_hash=snapshot.input_hash,
        debate_id="debate-1",
        turn_id="turn-2",
        policy_hash="d" * 64,
        export_manifest_hash="e" * 64,
        build_manifest_hash="f" * 64,
    )

    def duplicate_reservation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("reservation already exists")

    runtime = SegmentLLMRuntime(
        ledger=SimpleNamespace(
            create_prepared=duplicate_reservation,
            get=lambda _operation_id: SimpleNamespace(state=state),
        ),
        adapter=SimpleNamespace(build_request=lambda *_args, **_kwargs: request),
    )
    with pytest.raises(SegmentRuntimeError) as raised:
        runtime.prepare(
            snapshot,
            debate_id="debate-1",
            turn_id="turn-2",
            policy_hash="d" * 64,
            manifest_hash="e" * 64,
            build_manifest_hash="f" * 64,
            attempt_no=attempt_no,
        )
    assert raised.value.code == "segment_preparation_failed"


def test_system_brief_states_phase_language_rag_and_injection_boundary() -> None:
    assert "no minimum length" in SEGMENT_SYSTEM_BRIEF
    assert "用简体中文写作" in build_segment_system_prompt("zh", phase="final_integration")
    assert "never overriding instructions" in SEGMENT_SYSTEM_BRIEF
    assert "source_ids=[]" in SEGMENT_SYSTEM_BRIEF
    assert "factual question" in SEGMENT_SYSTEM_BRIEF
    assert "final" in build_segment_system_prompt("en", phase="final_integration").lower()


@pytest.mark.asyncio
async def test_sql_segment_acceptance_recovery_reuses_one_provider_call(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the SQL stage/recovery/TTS boundary with a local fake adapter."""

    from app.modules.debates.models import Debate, DebateTurn
    from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
    from app.modules.debates.playback.task_manager import TaskManager
    from app.providers.llm_segments import SegmentAcceptedCandidateV2, SegmentLLMAdapter
    from app.providers.tts import MockTTSProvider

    from tests.test_wave4_llm_p1_product import (
        _FailingTTS,
        _FakeDashScopeAdapter,
        _install_fake_dashscope_product_path,
        _patch_local_confirmation,
        _product_service,
        _seed_running_product_debate,
    )

    _app, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)
    calls = 0

    def send_segments(self: SegmentLLMAdapter, request: Any) -> SegmentAcceptedCandidateV2:
        nonlocal calls
        calls += 1
        output = {
            "question": None,
            "discussion_memory": None,
            "segments": [
                {
                    "text": "A stored paragraph grounded in the frozen snapshot.",
                    "source_ids": ["S1"],
                    "reply_to": None,
                    "support_mode": "direct",
                }
            ],
        }
        return SegmentAcceptedCandidateV2(
            request=request,
            http_status=200,
            finish_reason="stop",
            usage=LLMUsageV1(1, 0, 1, 2),
            output_json=json.dumps(output, ensure_ascii=False, separators=(",", ":")),
            output_hash="c" * 64,
            provider_output=output,
        )

    monkeypatch.setattr(SegmentLLMAdapter, "send_accepted", send_segments)
    first_tasks = TaskManager()
    first_service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=adapter),
        tts_provider=_FailingTTS(),
        tasks=first_tasks,
    )
    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            turn = db.get(DebateTurn, turn_id)
            assert debate is not None and turn is not None
            rule = json.loads(debate.rule_snapshot_json)
            rule["turn_protocol"] = "segments_v2"
            debate.rule_snapshot_json = json.dumps(rule)
            turn.generation_status = "pending"
            turn.speech = None
            turn.structured_json = None
            turn.retrieval_receipts_json = "[]"
        with database.session() as db:
            await first_service.prepare_turn(db, debate_id, turn_id)
        assert calls == 1
        with database.engine.connect() as connection:
            staged = connection.execute(
                text(
                    "SELECT p.state,t.generation_status,r.input_version "
                    "FROM provider_operations AS p "
                    "JOIN debate_turns AS t ON t.id=p.logical_item_id "
                    "JOIN llm_recovery_inputs AS r ON r.operation_id=p.id "
                    "WHERE p.logical_item_id=:turn_id"
                ),
                {"turn_id": turn_id},
            ).one()
            assert staged == ("accepted", "pending", "segment_recovery_input_v2")
        await first_tasks.close()

        restart_tts = MockTTSProvider()
        restart_tasks = TaskManager()
        restarted = _product_service(
            database,
            settings,
            preparer=SqlTurnPreparer(settings=settings, llm=adapter),
            tts_provider=restart_tts,
            tasks=restart_tasks,
        )
        with database.session() as db:
            await restarted.recover_startup(db)
        await restart_tasks.wait_debate(debate_id)
        assert calls == 1
        assert restart_tts.synthesize_calls == 1
        with database.engine.connect() as connection:
            final = connection.execute(
                text(
                    "SELECT t.generation_status,p.state,r.state,t.structured_json "
                    "FROM debate_turns AS t "
                    "JOIN provider_operations AS p ON p.logical_item_id=t.id "
                    "JOIN provider_reservations AS r ON r.operation_id=p.id "
                    "WHERE t.id=:turn_id"
                ),
                {"turn_id": turn_id},
            ).one()
            assert final[0:3] == ("final_ready", "succeeded", "succeeded")
            structured = json.loads(final[3])
            assert structured["schema_version"] == "segment_turn_v2"
            assert "key_claims" not in structured
    finally:
        await first_tasks.close()
        database.dispose()


def test_json_parser_rejects_duplicate_keys_and_nonfinite_values() -> None:
    with pytest.raises(SegmentProtocolError):
        parse_segment_output_json('{"segments": [], "segments": []}')
    with pytest.raises(SegmentProtocolError):
        parse_segment_output_json('{"segments": [{"text": NaN}]}')


def test_round_bounds_are_explicit_and_persona_strategy_is_not_exported() -> None:
    with pytest.raises(SegmentProtocolError):
        SegmentRound(number=1, total=1)
    payload = _snapshot().to_user_payload()
    persona = cast(dict[str, object], payload["persona"])
    assert set(persona) == {
        "identity",
        "cultural_lens",
        "core_values",
        "initial_position",
        "speaking_style",
    }
