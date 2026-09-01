"""Focused deterministic checks for the M14 report boundary."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.core.models import IdempotencyRecord, Job
from app.modules.debates.models import Debate
from app.modules.interactions.schemas import BarrageRequest
from app.modules.interactions.service import InteractionService
from app.modules.reports import service as reports_service
from app.modules.reports.models import (
    BarrageInsightItem,
    BarrageInsightSnapshot,
    CivilizationReportRevision,
)
from app.modules.reports.policy import (
    canonical_insight_output_json,
    classify_barrage_text,
    mock_barrage_insight_v1,
    normalize_barrage_text,
    validate_insight_partition,
)
from app.modules.reports.schemas import (
    BarrageInsightInput,
    ManifestInsight,
    ManifestInsightItem,
    ManifestParticipant,
    ManifestTurn,
    ManifestTurnSource,
    ManifestVote,
    ReportInputManifestV1,
    _reject_floats,
)
from app.modules.reports.service import (
    ReportContext,
    ReportInsightEnqueuer,
    ReportSourceContext,
    ReportTurnContext,
    generate_mock_report,
    process_insight_job,
    process_report_job,
    recover_report_jobs,
    regenerate_report,
    report_word_count,
    validate_report_markdown,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def test_mock_insight_normalizes_exact_duplicates_and_keeps_critical_minorities() -> None:
    first = uuid4()
    second = uuid4()
    third = uuid4()
    fourth = uuid4()
    result = mock_barrage_insight_v1(
        [
            {"message_id": first, "raw_text": "  I SUPPORT this   policy  "},
            {"message_id": second, "raw_text": "i support this policy"},
            {"message_id": third, "raw_text": "I disagree with the premise"},
            {"message_id": fourth, "raw_text": "!!!"},
        ]
    )
    assert normalize_barrage_text("  I SUPPORT this   policy  ") == "i support this policy"
    assert result.included_count == 3
    assert result.filtered_count == 1
    assert [item.category for item in result.items] == ["support", "challenge"]
    assert result.items[0].summary == "  I SUPPORT this   policy  "
    assert result.items[0].first_order == 0
    assert result.items[1].summary == "I disagree with the premise"
    assert result.assignments[-1].filter_reason == ("mock_barrage_insight_v1:no_letter_or_number")


def test_mock_insight_classification_priority_and_cjk_markers() -> None:
    assert classify_barrage_text("Why should we do this? I disagree") == "question"
    assert classify_barrage_text("I disagree with premise") == "challenge"
    assert classify_barrage_text("为什么要这样做") == "question"
    assert classify_barrage_text("我不同意这个取舍") == "challenge"
    assert classify_barrage_text("Helpful contribution") == "support"


def test_insight_boundary_rejects_nickname_and_partition_tampering() -> None:
    with pytest.raises(ValueError, match="forbidden keys"):
        mock_barrage_insight_v1([{"message_id": uuid4(), "raw_text": "hello", "nickname": "Alice"}])
    message_id = uuid4()
    result = mock_barrage_insight_v1([{"message_id": message_id, "raw_text": "hello"}])
    with pytest.raises(ValueError, match="more than once"):
        validate_insight_partition(
            [message_id],
            result.model_copy(update={"assignments": [*result.assignments, result.assignments[0]]}),
        )
    with pytest.raises(ValueError, match="unknown"):
        validate_insight_partition([uuid4()], result)


def test_identical_typed_policy_output_is_byte_stable() -> None:
    message_id = uuid4()
    left = mock_barrage_insight_v1(
        [BarrageInsightInput(message_id=message_id, raw_text="Same text")]
    )
    right = mock_barrage_insight_v1(
        [BarrageInsightInput(message_id=message_id, raw_text="Same text")]
    )
    assert canonical_insight_output_json(left) == canonical_insight_output_json(right)


def _manifest() -> ReportInputManifestV1:
    participant_a = UUID("00000000-0000-4000-8000-000000000001")
    participant_b = UUID("00000000-0000-4000-8000-000000000002")
    return ReportInputManifestV1(
        participants=[
            ManifestParticipant(
                participant_id=participant_b,
                slot="B",
                order_index=1,
                agent_name="B",
                stance_mode="assigned",
                initial_stance="oppose",
                current_stance="oppose",
                initial_position_summary="second",
                current_position_summary="second",
            ),
            ManifestParticipant(
                participant_id=participant_a,
                slot="A",
                order_index=0,
                agent_name="A",
                stance_mode="assigned",
                initial_stance="support",
                current_stance="support",
                initial_position_summary="first",
                current_position_summary="first",
            ),
        ],
        turns=[],
        turn_sources=[],
        votes=[
            ManifestVote(participant_id=participant_b, order_index=1, count=0),
            ManifestVote(participant_id=participant_a, order_index=0, count=0),
        ],
        insight=ManifestInsight(
            snapshot_id=UUID("00000000-0000-4000-8000-000000000010"),
            revision=1,
            included_count=0,
            filtered_count=0,
            items=[],
        ),
    )


def test_report_manifest_canonical_json_sorts_arrays_and_rejects_float() -> None:
    manifest = _manifest()
    payload = manifest.canonical_payload()
    assert [item["order_index"] for item in payload["participants"]] == [0, 1]
    assert [item["order_index"] for item in payload["votes"]] == [0, 1]
    assert manifest.canonical_json().encode("utf-8") == manifest.canonical_json_bytes()
    assert manifest.input_hash() == manifest.input_hash().lower()
    with pytest.raises(ValueError, match="floating-point"):
        _reject_floats({"bad": 1.0})


def test_mock_maya_report_has_exact_headings_zero_interaction_phrase_and_word_count() -> None:
    manifest = _manifest()
    turns = tuple(
        ReportTurnContext(
            turn_id=uuid4(),
            participant_id=manifest.participants[index % 2].participant_id,
            participant_name=manifest.participants[index % 2].agent_name,
            round_no=1 if index < 2 else 2,
            turn_index=index,
            speech=" ".join(["careful", "reasoning"] * 50),
        )
        for index in range(4)
    )
    context = ReportContext(
        debate=SimpleNamespace(topic="A careful classroom question"),  # type: ignore[arg-type]
        manifest=manifest,
        turns=turns,
        sources=(),
        vote_total=0,
        barrage_total=0,
    )
    markdown, count = generate_mock_report(context)
    assert 600 <= count <= 900
    assert report_word_count(markdown) == count
    assert "This session had no classroom interaction data." in markdown
    assert "winner" not in markdown.lower()
    assert markdown.index("## Debate Overview") < markdown.index("## Evidence and Arguments")
    assert markdown.index("## Evidence and Arguments") < markdown.index("## Areas of Convergence")
    assert markdown.index("## Areas of Convergence") < markdown.index(
        "## Continuing Tensions and Questions"
    )
    assert markdown.index("## Continuing Tensions and Questions") < markdown.index(
        "## Classroom Perspectives"
    )
    assert markdown.index("## Classroom Perspectives") < markdown.index(
        "## Mutual Learning Reflection"
    )


def _bounded_report_context(
    participant_count: int,
    source_count: int,
    insight_count: int = 0,
) -> ReportContext:
    participants = [
        ManifestParticipant(
            participant_id=uuid4(),
            slot=chr(65 + index),  # type: ignore[arg-type]
            order_index=index,
            agent_name="Long participant display name repeated many times",
            stance_mode="assigned",
            initial_stance="support",
            current_stance="neutral",
            initial_position_summary=" ".join(["initial"] * 80),
            current_position_summary=" ".join(["current"] * 80),
        )
        for index in range(participant_count)
    ]
    turn_count = participant_count * 2
    turn_ids = [uuid4() for _ in range(turn_count)]
    manifest_turns = [
        ManifestTurn(
            turn_id=turn_id,
            participant_id=participants[index % participant_count].participant_id,
            round_no=1 if index < participant_count else 2,
            turn_index=index,
            text_hash="a" * 64,
        )
        for index, turn_id in enumerate(turn_ids)
    ]
    turns = tuple(
        ReportTurnContext(
            turn_id=turn_id,
            participant_id=participants[index % participant_count].participant_id,
            participant_name=participants[index % participant_count].agent_name,
            round_no=1 if index < participant_count else 2,
            turn_index=index,
            speech=" ".join(["argument"] * 200),
        )
        for index, turn_id in enumerate(turn_ids)
    )
    source_ranks = [0] * turn_count
    manifest_sources: list[ManifestTurnSource] = []
    sources: list[ReportSourceContext] = []
    for index in range(source_count):
        turn_index = index % turn_count
        source_ranks[turn_index] += 1
        source_id = uuid4()
        snapshot_id = uuid4()
        chunk_id = uuid4()
        manifest_sources.append(
            ManifestTurnSource(
                turn_source_id=source_id,
                turn_id=turn_ids[turn_index],
                turn_index=turn_index,
                rank=source_ranks[turn_index],
                snapshot_id=snapshot_id,
                chunk_id=chunk_id,
                chunk_content_hash="b" * 64,
                source_filename="very long source filename.md",
            )
        )
        sources.append(
            ReportSourceContext(
                turn_source_id=source_id,
                turn_id=turn_ids[turn_index],
                turn_index=turn_index,
                rank=source_ranks[turn_index],
                snapshot_id=snapshot_id,
                chunk_id=chunk_id,
                source_filename="very long source filename.md",
                chunk_text=" ".join(["evidence"] * 200),
            )
        )
    manifest = ReportInputManifestV1(
        topic=" ".join(["topic"] * 100),
        participants=participants,
        turns=manifest_turns,
        turn_sources=manifest_sources,
        votes=[
            ManifestVote(
                participant_id=participant.participant_id,
                order_index=participant.order_index,
                count=0,
            )
            for participant in participants
        ],
        insight=ManifestInsight(
            snapshot_id=uuid4(),
            revision=1,
            included_count=insight_count,
            filtered_count=0,
            items=[
                ManifestInsightItem(
                    item_id=uuid4(),
                    order_index=index + 1,
                    category="challenge",
                    summary=" ".join(["classroom"] * 100),
                    count=1,
                )
                for index in range(insight_count)
            ],
        ),
    )
    return ReportContext(
        debate=SimpleNamespace(topic=manifest.topic),  # type: ignore[arg-type]
        manifest=manifest,
        turns=turns,
        sources=tuple(sources),
        vote_total=0,
        barrage_total=insight_count,
    )


@pytest.mark.parametrize(
    ("participant_count", "source_count", "insight_count"),
    ((5, 0, 0), (2, 8, 0), (5, 60, 100)),
)
def test_mock_report_stays_in_word_bound_for_legal_input_extremes(
    participant_count: int,
    source_count: int,
    insight_count: int,
) -> None:
    markdown, count = generate_mock_report(
        _bounded_report_context(participant_count, source_count, insight_count)
    )
    assert 600 <= count <= 900
    assert markdown.count("[evidence:") == source_count


def test_report_validator_rejects_wrong_word_bound_and_unknown_citation() -> None:
    manifest = _manifest()
    markdown = "# Civilization Mutual Learning Report\n\n" + "\n\n".join(
        [
            "## Debate Overview",
            "## Evidence and Arguments",
            "## Areas of Convergence",
            "## Continuing Tensions and Questions",
            "## Classroom Perspectives",
            "## Mutual Learning Reflection",
        ]
    )
    with pytest.raises(ValueError, match="word count"):
        validate_report_markdown(
            markdown + "\n\nThis session had no classroom interaction data.",
            manifest=manifest,
            vote_total=0,
            barrage_total=0,
        )
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_report_markdown(
            markdown + "\n\n[evidence:00000000-0000-4000-8000-000000000099]",
            manifest=manifest,
            vote_total=0,
            barrage_total=0,
        )


def _finalize_interaction(
    database,
    settings,
    *,
    barrages: tuple[tuple[str, str], ...] = (),
) -> tuple[str, str]:
    from tests.test_wave3_interactions import _seed_finished_debate

    debate_id, _participant_ids = _seed_finished_debate(database)
    interaction = InteractionService(
        session_factory=database.session_factory,
        settings=settings,
        insight_enqueuer=ReportInsightEnqueuer(),
    )
    opened = interaction.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key=f"m14-open-{uuid4()}",
    )
    assert opened.status == "open" and opened.public_url is not None
    access_token = str(opened.public_url).rsplit("/", 1)[-1]
    for nickname, raw_text in barrages:
        interaction.submit_barrage(
            access_token=access_token,
            payload=BarrageRequest(
                nickname=nickname,
                raw_text=raw_text,
                client_submission_id=uuid4(),
            ),
        )
    closed = interaction.close_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key=f"m14-close-{uuid4()}",
    )
    assert closed.status == "finalized"
    with database.session() as session:
        snapshot = session.scalar(
            select(BarrageInsightSnapshot).where(BarrageInsightSnapshot.debate_id == debate_id)
        )
        assert snapshot is not None
        return debate_id, snapshot.id


def test_persisted_insight_item_order_is_earliest_barrage_sequence(app_factory) -> None:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        _debate_id, snapshot_id = _finalize_interaction(
            database,
            settings,
            barrages=(("First name", "Same Insight"), ("Different name", "same insight")),
        )
        with database.session() as session:
            process_insight_job(session, snapshot_id)
        with database.session() as session:
            item = session.scalar(
                select(BarrageInsightItem).where(BarrageInsightItem.snapshot_id == snapshot_id)
            )
            assert item is not None
            assert item.order_index == 1


def test_insight_rejects_mismatched_frozen_input_hash(app_factory) -> None:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(
            database,
            settings,
            barrages=(("Observer", "A classroom thought"),),
        )
        with database.session() as session:
            snapshot = session.get(BarrageInsightSnapshot, snapshot_id)
            assert snapshot is not None
            snapshot.input_hash = "f" * 64
        with database.session() as session:
            processed = process_insight_job(session, snapshot_id)
            assert processed.status == "failed"
            assert processed.safe_error_code == "insight_input_integrity_failed"
            assert processed.included_count == 0
            assert processed.filtered_count == 0
        with database.session() as session:
            assert (
                session.scalar(select(Job.state).where(Job.insight_snapshot_id == snapshot_id))
                == "failed"
            )
            assert session.get(Debate, debate_id).status == "completed"


def test_running_claim_survives_crash_and_recovery_completes_debate(
    app_factory,
    monkeypatch,
) -> None:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)

        def crash_after_claim(*_args, **_kwargs):
            raise RuntimeError("simulated process crash")

        monkeypatch.setattr(reports_service, "process_insight_snapshot", crash_after_claim)
        session = database.session_factory()
        try:
            with pytest.raises(RuntimeError, match="simulated process crash"):
                process_insight_job(session, snapshot_id)
        finally:
            session.close()

        with database.session() as check:
            assert (
                check.scalar(select(Job.state).where(Job.insight_snapshot_id == snapshot_id))
                == "running"
            )
        with database.session() as recovery:
            assert recover_report_jobs(recovery) == 1
        with database.session() as check:
            snapshot = check.get(BarrageInsightSnapshot, snapshot_id)
            debate = check.get(Debate, debate_id)
            assert snapshot is not None and snapshot.status == "failed"
            assert snapshot.safe_error_code == "operation_interrupted"
            assert debate is not None and debate.status == "completed"
            assert (
                check.scalar(select(Job.state).where(Job.insight_snapshot_id == snapshot_id))
                == "failed"
            )


def test_m14_enqueuer_runs_empty_interaction_to_ready_report(app_factory) -> None:
    """Exercise the M13 close adapter and M14 job chain on real ORM rows."""

    # Reuse the audited M13 seed helper rather than maintaining a second
    # Debate/Participant fixture in this module.
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)
        with database.session() as session:
            regenerate_report(
                session,
                actor_user_id=TEACHER_ID,
                debate_id=debate_id,
                idempotency_key="m14-report-generate-namespace-0001",
            )
            assert (
                session.scalar(
                    select(IdempotencyRecord.operation).where(
                        IdempotencyRecord.key == "m14-report-generate-namespace-0001"
                    )
                )
                == "report.generate"
            )
        with database.session() as session:
            process_insight_job(session, snapshot_id)
            session.commit()
            revision = session.scalar(
                select(CivilizationReportRevision).where(
                    CivilizationReportRevision.debate_id == debate_id
                )
            )
            assert revision is not None
            revision_id = revision.id
        with database.session() as session:
            process_report_job(session, revision_id)
            session.commit()
            ready = session.get(CivilizationReportRevision, revision_id)
            assert ready is not None
            assert ready.status == "ready"
            assert ready.word_count is not None and 600 <= ready.word_count <= 900
            assert (
                session.scalar(
                    select(Job.state).where(Job.idempotency_key == f"report.generate:{revision_id}")
                )
                == "completed"
            )
