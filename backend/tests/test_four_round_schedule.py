"""Versioned classroom scheduling and persisted dependency checks, without providers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.core.models import Job, StoredFile
from app.modules.debates.generation.mutual_learning_policy import MutualLearningPolicy
from app.modules.debates.generation.policy import TurnPolicy
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, PlaybackState
from app.modules.debates.playback._core import PlaybackCore
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer, generation_fence
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.round_count import (
    debate_teaching_protocol,
    preview_turn_count,
    visible_turn_predecessors,
)
from app.modules.debates.schemas import DebateDraftRequest, DebateParticipantInput
from app.modules.debates.setup.rules import build_turn_plan
from app.modules.debates.setup.service import commit_start_plan, create_debate_draft
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from tests.postgres_db import new_database_url
from tests.test_wave2_setup import COURSE_ID, GROUP_DEMO_ID, TEACHER_ID, _insert_published_agent

RULE_SET = "ordered_multi_expert_mutual_learning_v1"
TEACHING = "four_round_v1"


def test_unattempted_recovery_never_retries_an_existing_llm_operation():
    engine = create_engine(new_database_url(schema=False))
    with Session(engine) as db:
        db.execute(
            text(
                "CREATE TABLE provider_operations (id TEXT, scope_id TEXT, "
                "logical_item_id TEXT, provider_operation TEXT)"
            )
        )
        repo = SqlPlaybackRepository()
        assert repo.unattempted_llm_turn(db, "debate", "turn")
        db.execute(
            text("INSERT INTO provider_operations VALUES ('op','debate','turn','llm_debate_turn')")
        )
        assert not repo.unattempted_llm_turn(db, "debate", "turn")
        assert repo.unattempted_llm_turn(db, "debate", "other-turn")
    engine.dispose()


def test_retryable_provider_llm_reject_allows_http_429_not_charged_accepts():
    engine = create_engine(new_database_url(schema=False))
    with Session(engine) as db:
        db.execute(
            text(
                "CREATE TABLE provider_operations ("
                "id TEXT, scope_id TEXT, logical_item_id TEXT, "
                "provider_operation TEXT, attempt_no INT, state TEXT, "
                "safe_error_code TEXT, updated_at TEXT)"
            )
        )
        repo = SqlPlaybackRepository()
        assert not repo.retryable_provider_llm_reject(db, "debate", "turn")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op1','debate','turn','llm_debate_turn',1,'failed',"
                "'llm_http_rejected','2026-01-01')"
            )
        )
        assert repo.retryable_provider_llm_reject(db, "debate", "turn")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op-busy','debate','busy','llm_debate_turn',1,'failed',"
                "'provider_busy','2026-01-01')"
            )
        )
        assert repo.retryable_provider_llm_reject(db, "debate", "busy")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op-rate','debate','rate','llm_debate_turn',1,'failed',"
                "'provider_rate_limited','2026-01-01')"
            )
        )
        assert repo.retryable_provider_llm_reject(db, "debate", "rate")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op-auth','debate','auth','llm_debate_turn',1,'failed',"
                "'provider_auth_failed','2026-01-01')"
            )
        )
        assert not repo.retryable_provider_llm_reject(db, "debate", "auth")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op2','debate','turn','llm_debate_turn',2,'succeeded',"
                "NULL,'2026-01-02')"
            )
        )
        assert not repo.retryable_provider_llm_reject(db, "debate", "turn")
        db.execute(
            text(
                "INSERT INTO provider_operations VALUES "
                "('op-unknown','debate','unknown','llm_debate_turn',1,"
                "'acceptance_unknown','llm_http_rejected','2026-01-01')"
            )
        )
        assert not repo.retryable_provider_llm_reject(db, "debate", "unknown")
    engine.dispose()


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_four_round_plan_rotates_speakers_without_moving_ids_or_question_targets(count):
    people = [str(uuid4()) for _ in range(count)]
    ids = [str(uuid4()) for _ in range(count * 4)]
    plan = TurnPolicy(rule_set_id=RULE_SET).plan_with_ids(
        people, ids, round_count=4, teaching_protocol=TEACHING
    )
    setup = build_turn_plan(people, round_count=4, rule_set_id=RULE_SET, teaching_protocol=TEACHING)
    for round_no in range(1, 5):
        current = plan[(round_no - 1) * count : round_no * count]
        offset = (round_no - 1) % count
        assert [entry.participant_id for entry in current] == people[offset:] + people[:offset]
        for entry in current:
            stable_index = people.index(entry.participant_id)
            assert entry.order_index == stable_index
            assert entry.slot == chr(65 + stable_index)
            expected_prefix = () if round_no == 1 else tuple(ids[: entry.turn_index])
            assert entry.predecessor_turn_ids == expected_prefix
            assert setup[entry.turn_index].predecessor_turn_indexes == tuple(
                range(len(expected_prefix))
            )
            assert str(setup[entry.turn_index].participant_id) == entry.participant_id
            if round_no == 2:
                assert entry.next_participant_id == people[(stable_index + 1) % count]
            else:
                assert entry.next_participant_id is None
    assert {entry.next_participant_id for entry in plan[count : count * 2]} == set(people)
    assert [entry.turn_id for entry in plan if entry.is_final] == [ids[-1]]


@pytest.mark.parametrize("rounds", [2, 3, 5])
def test_unmarked_plans_keep_their_own_round_count_order_and_barrier(rounds):
    people = [str(uuid4()) for _ in range(3)]
    plan = MutualLearningPolicy().plan(people, round_count=rounds)
    assert [entry.participant_id for entry in plan] == people * rounds
    for entry in plan:
        assert entry.barrier == "round"
        assert len(entry.predecessor_ids) == (entry.round_no - 1) * len(people)


def _payload(agent_ids):
    return DebateDraftRequest(
        topic="How should a classroom use evidence?",
        participants=[
            DebateParticipantInput(agent_id=UUID(agent), stance_mode="open") for agent in agent_ids
        ],
        round_unit_caps=[200, 200, 200, 200],
    )


@pytest.mark.parametrize("rounds", [2, 3, 5])
def test_new_request_rejects_non_four_round_creation(rounds):
    body = _payload([str(uuid4()), str(uuid4())]).model_dump()
    body["round_count"] = rounds
    with pytest.raises(ValidationError):
        DebateDraftRequest.model_validate(body)


@pytest.fixture
def four_round_db(app_factory):
    app, database, _ = app_factory()
    with TestClient(app):
        agent_ids = [
            _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
            for name in ("One", "Two", "Three")
        ]
        with database.session() as db:
            detail = create_debate_draft(
                db, actor_user_id=TEACHER_ID, course_id=COURSE_ID, payload=_payload(agent_ids)
            )
            turns = commit_start_plan(db, debate_id=str(detail.id))
            debate_id = str(detail.id)
            turn_ids = [turn.id for turn in turns]
        yield database, debate_id, turn_ids


def test_create_freezes_four_rounds_and_three_round_preview_with_stable_owners(four_round_db):
    database, debate_id, ids = four_round_db
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        assert debate_teaching_protocol(debate) == TEACHING
        assert json.loads(debate.rule_snapshot_json)["turn_protocol"] == "segments_v2"
        assert preview_turn_count(debate, 3) == 9
        people = list(
            db.scalars(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate_id)
                .order_by(DebateParticipant.order_index)
            )
        )
        turns = commit_start_plan(db, debate_id=debate_id)
        assert [turn.id for turn in turns] == ids
        assert [turn.participant_id for turn in turns[3:6]] == [
            people[1].id,
            people[2].id,
            people[0].id,
        ]
        assert len(turns) == 12


def _ready(db, debate, turn):
    fence = generation_fence(db, debate, turn)
    turn.generation_status = "final_ready"
    turn.preparation_stage = "ready"
    turn.speech = f"Saved speech for turn {turn.turn_index}."
    turn.structured_json = json.dumps(
        {
            "schema_version": "segment_turn_v2",
            "segments": [
                {
                    "text": turn.speech,
                    "source_ids": [],
                    "reply_to": None,
                    "support_mode": "no_match",
                }
            ],
        }
    )
    turn.retrieval_receipts_json = "[]"
    turn.retrieval_status = "no_match"
    turn.grounding_mode = "general_reasoning"
    turn.word_count = len(turn.speech.split())
    turn.transcript_hash = fence.transcript_hash
    db.flush()
    return fence


def test_sql_context_requires_complete_prior_round_and_same_round_successes(four_round_db):
    database, debate_id, _ = four_round_db
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        turns = commit_start_plan(db, debate_id=debate_id)
        assert generation_fence(db, debate, turns[2]).predecessor_turn_ids == ()
        with pytest.raises(ValueError, match="incomplete"):
            generation_fence(db, debate, turns[3])
        for turn in turns[:3]:
            _ready(db, debate, turn)
        first = _ready(db, debate, turns[3])
        assert first.predecessor_turn_ids == tuple(turn.id for turn in turns[:3])
        second = generation_fence(db, debate, turns[4])
        assert second.predecessor_turn_ids == tuple(turn.id for turn in turns[:4])
        assert second.transcript_hash != first.transcript_hash
        with pytest.raises(ValueError, match="incomplete"):
            generation_fence(db, debate, turns[6])
        for turn in turns[4:6]:
            _ready(db, debate, turn)
        assert generation_fence(db, debate, turns[6]).predecessor_turn_ids == tuple(
            turn.id for turn in turns[:6]
        )
        turns[3].speech = "A changed predecessor invalidates all dependent cached inputs."
        with pytest.raises(ValueError):
            generation_fence(db, debate, turns[6])


def test_saved_turn_recovery_keeps_prefix_and_never_calls_generation(four_round_db, monkeypatch):
    database, debate_id, _ = four_round_db
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        turns = commit_start_plan(db, debate_id=debate_id)
        for turn in turns[:5]:
            _ready(db, debate, turn)
        preparer = SqlTurnPreparer()

        def forbidden(*args, **kwargs):
            pytest.fail("completed speech must be reused without embedding or LLM calls")

        monkeypatch.setattr(preparer, "_query_embedding_service", forbidden)
        monkeypatch.setattr(preparer.llm, "generate_turn", forbidden)
        saved = preparer(db, debate, turns[4], attempt=1, cancellation_generation=0)
        assert saved.speech == turns[4].speech
        assert saved.predecessor_turn_ids == tuple(turn.id for turn in turns[:4])


def test_visibility_excludes_future_and_same_round_opening():
    debate = SimpleNamespace(rule_set_id=RULE_SET, teaching_protocol=TEACHING)
    turns = [SimpleNamespace(round_no=index // 2 + 1, turn_index=index) for index in range(8)]
    assert visible_turn_predecessors(debate, turns[1], turns) == []
    assert visible_turn_predecessors(debate, turns[5], turns) == turns[:5]


def test_sql_next_claim_accepts_all_round_boundaries_and_same_round_prefixes(four_round_db):
    database, debate_id, ids = four_round_db
    now = datetime.now(UTC)
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        turns = commit_start_plan(db, debate_id=debate_id)
        for turn in turns:
            _ready(db, debate, turn)
            audio_id = str(uuid4())
            db.add(
                StoredFile(
                    id=audio_id,
                    kind="debate_audio",
                    relative_path=f"test/{audio_id}.wav",
                    sha256="a" * 64,
                    size_bytes=48,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            turn.audio_file_id = audio_id
            turn.audio_duration_ms = 1000
            turn.actual_tts_voice_kind = "mock_sentinel"
            db.add(
                Job(
                    id=str(uuid4()),
                    debate_id=debate_id,
                    turn_id=turn.id,
                    operation="debate_turn_prepare",
                    state="completed",
                    cancellation_generation=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        debate.status = "running"
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    for index in range(len(ids) - 1):
        with database.session() as db:
            state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
            state.current_turn_id = ids[index]
            state.status = "waiting_next"
            db.get(DebateTurn, ids[index]).publication_status = "public"
            version = state.control_version
            turns = list(
                db.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                )
            )
            assert PlaybackCore._turn_fence_ready(
                turns, turns[index + 1], rule_set_id=RULE_SET, teaching_protocol=TEACHING
            )
            assert PlaybackCore._has_public_predecessor_prefix(
                turns, turns[index + 1], rule_set_id=RULE_SET, teaching_protocol=TEACHING
            )
        assert repository.claim_next_playback(
            debate_id=debate_id,
            expected_control_version=version,
            expected_current_turn_id=ids[index],
            successor_turn_id=ids[index + 1],
            teacher_user_id=TEACHER_ID,
        ), f"Next failed at turn {index}"


def test_sql_next_claim_advances_tts_voice_unavailable_with_nonempty_predecessors(four_round_db):
    """Prod R1/D2: turn3→4 text-fallback with compact predecessor JSON must claim True."""
    database, debate_id, ids = four_round_db
    now = datetime.now(UTC)
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        turns = commit_start_plan(db, debate_id=debate_id)
        for turn in turns:
            _ready(db, debate, turn)
            turn.audio_file_id = None
            turn.audio_duration_ms = None
            turn.safe_error_code = "tts_voice_unavailable"
            # Compact separators match setup writes; claim must not require spaced json_agg text.
            turn.predecessor_turn_ids_json = json.dumps(
                json.loads(turn.predecessor_turn_ids_json),
                separators=(",", ":"),
            )
            db.add(
                Job(
                    id=str(uuid4()),
                    debate_id=debate_id,
                    turn_id=turn.id,
                    operation="debate_turn_prepare",
                    state="completed",
                    cancellation_generation=int(debate.cancellation_generation or 0),
                    created_at=now,
                    updated_at=now,
                )
            )
        debate.status = "running"
        # Publish prefix through turn index 3 (ids[3]); claim successor ids[4] (non-empty preds).
        for turn in turns[:4]:
            turn.publication_status = "public"
        state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
        assert state is not None
        state.current_turn_id = ids[3]
        state.status = "waiting_next"
        state.mode = "live"
        state.control_version = 61
        state.replay_scope = None
        state.replay_index = None
        version = state.control_version
        successor = turns[4]
        assert json.loads(successor.predecessor_turn_ids_json)
        assert successor.cutoff_turn_index == 3

    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    assert repository.claim_next_playback(
        debate_id=debate_id,
        expected_control_version=version,
        expected_current_turn_id=ids[3],
        successor_turn_id=ids[4],
        teacher_user_id=TEACHER_ID,
    )
    with database.session() as db:
        row = db.execute(
            text(
                "SELECT status, current_turn_id, control_version FROM playback_states "
                "WHERE debate_id=:id"
            ),
            {"id": debate_id},
        ).one()
        assert row[1] == ids[4]
        assert int(row[2]) > version
        assert db.get(DebateTurn, ids[4]).publication_status == "public"
