"""Adversarial pure tests for the Wave 2 M11 generation boundary."""

from __future__ import annotations

import json
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.config import Settings
from app.modules.debates.generation import (
    FinalReadyTurn,
    GenerationContext,
    GenerationFence,
    ParticipantContext,
    PreparationCap,
    SnapshotRetrievalReceipt,
    SnapshotRetriever,
)
from app.modules.debates.generation.mutual_learning_policy import MUTUAL_LEARNING_RULE_SET_ID
from app.modules.debates.generation.mutual_learning_prompts import (
    compute_mutual_transcript_hash,
)
from app.modules.debates.generation.retrieval import RAGRetrievalError, TurnSubquery
from app.modules.debates.playback.generation_adapter import generation_fence
from app.modules.debates.setup.rules import canonical_rule_snapshot_json
from app.providers.llm import (
    LLMProviderError,
    MockLLMProvider,
    llm_provider,
    validate_llm_provider_selector,
)


class FakeSearch:
    def __init__(self, rows: Iterable[object]) -> None:
        self.rows = tuple(rows)
        self.calls: list[tuple[str, str, int]] = []

    def search(self, snapshot_id: str, query: str, *, top_k: int = 6) -> Iterable[object]:
        self.calls.append((snapshot_id, query, top_k))
        return self.rows


def participant(
    participant_id: str,
    *,
    agent_name: str | None = None,
    snapshot_id: str | None = None,
    slot: str = "",
    order_index: int = 0,
    stance_mode: str = "open",
    stance: str | None = None,
    agent_md: str = "# Persona\nA student-created perspective.",
) -> ParticipantContext:
    return ParticipantContext(
        participant_id=participant_id,
        agent_id=f"agent-{participant_id}",
        agent_name=agent_name or participant_id,
        slot=slot,
        order_index=order_index,
        snapshot_id=snapshot_id or f"snapshot-{participant_id}",
        agent_md=agent_md,
        stance_mode=stance_mode,  # type: ignore[arg-type]
        initial_stance=stance,  # type: ignore[arg-type]
        current_stance=stance if stance_mode == "assigned" else None,  # type: ignore[arg-type]
        initial_position_summary="An initial position." if stance_mode == "assigned" else "",
        current_position_summary="An initial position." if stance_mode == "assigned" else "",
        teacher_note="Private teacher note.",
    )


def receipt(
    *,
    snapshot_id: str = "snapshot-a",
    chunk_id: str = "chunk-a",
    query_kind: str = "viewpoint",
    score: float = 0.9,
    evidence_id: str = "evidence-a",
    text: str = "A real passage about agency, safety, and accountable recommendation systems.",
) -> SnapshotRetrievalReceipt:
    return SnapshotRetrievalReceipt(
        snapshot_id=snapshot_id,
        query_kind=query_kind,
        query_hash="q-hash",
        threshold_key="strict",
        rank=1,
        score=score,
        chunk_id=chunk_id,
        source_filename="evidence.md",
        text=text,
        evidence_id=evidence_id,
    )


def context_for(
    plans: tuple[object, ...],
    index: int,
    participants: tuple[ParticipantContext, ...],
    *,
    predecessors: tuple[FinalReadyTurn, ...] = (),
    pending_question: object | None = None,
) -> GenerationContext:
    return GenerationContext(
        debate_id="debate-1",
        topic="Should a platform restrict recommendation algorithms?",
        turn=plans[index],  # type: ignore[arg-type]
        participant=participants[index % len(participants)],
        participants=participants,
        predecessors=predecessors,
        pending_question=pending_question,  # type: ignore[arg-type]
    )


def _segment_snapshot() -> object:
    from tests.test_segments_protocol import _snapshot

    return _snapshot()


def _fence_debate() -> SimpleNamespace:
    return SimpleNamespace(
        id="debate-1",
        rule_set_id=MUTUAL_LEARNING_RULE_SET_ID,
        rule_snapshot_json=canonical_rule_snapshot_json(
            rule_set_id=MUTUAL_LEARNING_RULE_SET_ID, round_count=2
        ),
    )


def test_snapshot_retrieval_is_typed_bounded_and_deduplicated() -> None:
    search = FakeSearch(
        [
            {
                "chunk_id": "chunk-a",
                "source_filename": "a.md",
                "score": 0.84,
                "document_order": 0,
                "chunk_index": 0,
                "chunk_text": "The first real passage.",
            },
            {
                "chunk_id": "chunk-b",
                "source_filename": "b.md",
                "score": 0.43,
                "document_order": 1,
                "chunk_index": 0,
                "chunk_text": "The second real passage.",
            },
        ]
    )
    result = SnapshotRetriever(search).retrieve(
        "snapshot-a",
        (
            TurnSubquery("rebuttal", "a specific claim"),
            TurnSubquery("updated_position", "an updated position"),
        ),
    )
    assert result.matched
    assert len(result.receipts) == 2
    assert result.strict_calls == 2
    assert result.relaxed_calls == 0
    assert len(search.calls) == 2
    assert all(item.snapshot_id == "snapshot-a" for item in result.receipts)
    assert all(item.resolved_evidence_id().startswith("evidence-") for item in result.receipts)


def test_retrieval_runs_relaxed_only_after_strict_no_match_and_caps_subqueries() -> None:
    search = FakeSearch(
        [
            {
                "chunk_id": "chunk-a",
                "source_filename": "a.md",
                "score": 0.1,
                "chunk_text": "A weakly related passage.",
            }
        ]
    )
    result = SnapshotRetriever(search).retrieve("snapshot-a", (TurnSubquery("viewpoint", "topic"),))
    assert result.relaxed_calls == 1
    assert len(search.calls) == 2
    assert result.receipts[0].threshold_key == "relaxed"
    with pytest.raises(RAGRetrievalError):
        SnapshotRetriever(search).retrieve(
            "snapshot-a",
            tuple("q" for _ in range(4)),
        )


def test_generation_fence_binds_actual_hash_and_rejects_stale_release_or_late_result() -> None:
    fence = GenerationFence()
    fence.register("d", total_turns=4)
    first = fence.claim_turn(
        "d",
        turn_id="t0",
        turn_index=0,
        predecessor_turn_ids=(),
        transcript_hash="hash-0",
        claim_token="token-a",
    )
    assert first is not None
    from dataclasses import replace

    stale = replace(first, claim_token="stale")
    assert fence.release(stale) is False
    assert fence.complete(first, transcript_hash="wrong") is False
    assert fence.complete(first, transcript_hash="hash-0") is True
    assert fence.publish("t0", predecessor_turn_ids=()) is True
    successor = fence.claim_turn(
        "d",
        turn_id="t1",
        turn_index=1,
        predecessor_turn_ids=("t0",),
        transcript_hash="hash-1",
        claim_token="token-b",
    )
    assert successor is not None
    stale_successor = replace(successor, claim_token="wrong-token")
    assert fence.release(stale_successor) is False
    assert fence.stop("d") == 1
    assert fence.complete(successor, transcript_hash="hash-1") is False


def test_preparation_cap_allows_current_and_one_successor_but_not_recursive_next() -> None:
    cap = PreparationCap(current_turn_index=2, total_turns=6)
    assert cap.can_claim(2)
    assert cap.claim(2)
    assert not cap.can_claim(3)
    cap.mark_current_final_ready()
    assert cap.claim(3)
    assert not cap.can_claim(4)
    cap.advance()
    assert cap.current_turn_index == 3
    assert cap.current_final_ready
    assert cap.can_claim(4)


def test_llm_selector_is_callable_but_fail_closed_for_real_or_unknown() -> None:
    assert isinstance(llm_provider(), MockLLMProvider)
    validate_llm_provider_selector("mock")
    for selector in ("dashscope", "unknown"):
        with pytest.raises(RuntimeError):
            validate_llm_provider_selector(selector)
    with pytest.raises(RuntimeError):
        llm_provider(selector="dashscope")
    with pytest.raises(LLMProviderError):
        MockLLMProvider(["technical"]).generate_segments(_segment_snapshot())


@pytest.mark.parametrize(
    ("field", "selector"),
    (
        ("llm_provider", "dashscope"),
        ("embedding_provider", "dashscope"),
        ("tts_provider", "dashscope"),
        ("voice_provider", "dashscope"),
    ),
)
def test_startup_allows_only_one_reviewed_real_slice_with_mock_companions(
    field: str,
    selector: str,
) -> None:
    # Every selector not under test stays explicitly mock: a developer .env can
    # otherwise turn several real cores on at once and change what this asserts.
    values: dict[str, object] = {
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "tts_provider": "mock",
        "voice_provider": "mock",
        "report_provider": "mock",
        "dashscope_api_key": None,
        field: selector,
    }
    values.update(
        {
            "dashscope_api_key": "fixture-key",
            "dashscope_workspace_id": "workspace123",
            "dashscope_region": "cn-beijing",
            "provider_policy_hash": "a" * 64,
            "embedding_provider_policy_hash": None,
            "llm_provider_policy_hash": None,
            "report_provider_policy_hash": None,
        }
    )
    settings = Settings(maya_env="test", **values)  # type: ignore[arg-type]
    settings.validate_runtime()


def test_generation_fence_is_available_before_provider_and_rejects_stale_shape() -> None:
    class EmptyResult:
        def all(self) -> list[object]:
            return [
                SimpleNamespace(
                    id="turn-0",
                    turn_index=0,
                    round_no=1,
                    predecessor_turn_ids_json="[]",
                    transcript_hash=None,
                    cutoff_turn_index=-1,
                )
            ]

    from sqlalchemy.orm import Session

    # SQLAlchemy's Session check is deliberate in the adapter.  Use a real
    # unbound Session with its read method replaced so this remains a pure
    # no-provider fence check without creating a full migration fixture.
    db = Session()
    db.scalars = lambda _statement: EmptyResult()  # type: ignore[assignment]
    fence = generation_fence(db, _fence_debate(), SimpleNamespace(id="turn-0"))
    assert fence.predecessor_turn_ids == ()
    assert fence.transcript_hash == compute_mutual_transcript_hash(())
    assert fence.cutoff_turn_index == -1
    assert fence.attempt == 1

    stale_db = Session()

    class StaleResult:
        def all(self) -> list[object]:
            return [
                SimpleNamespace(
                    id="turn-0",
                    turn_index=0,
                    round_no=1,
                    predecessor_turn_ids_json='["unexpected"]',
                    transcript_hash=None,
                    cutoff_turn_index=-1,
                )
            ]

    stale_db.scalars = lambda _statement: StaleResult()  # type: ignore[assignment]
    with pytest.raises(ValueError, match="predecessor prefix"):
        generation_fence(stale_db, _fence_debate(), SimpleNamespace(id="turn-0"))


def test_sql_repository_generation_cas_rejects_stale_claim_prefix_hash_cutoff_attempt_and_window(
    app_factory: Any,
) -> None:
    """Exercise the shared SQL CAS contract without invoking a provider."""

    from datetime import UTC, datetime
    from uuid import uuid4

    from app.core.models import Agent, AgentVersion
    from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, PlaybackState
    from app.modules.debates.playback.protocols import PreparedGenerationFence
    from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from tests.test_wave2_playback import (
        COURSE_ID,
        GROUP_DEMO_ID,
        _insert_published_agent,
    )

    app, database, _settings = app_factory()
    with TestClient(app):
        first_agent = _insert_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="Fence A",
            evidence="A snapshot passage about accountable recommendation systems.",
        )
        second_agent = _insert_published_agent(
            database,
            group_id=GROUP_DEMO_ID,
            name="Fence B",
            evidence="A separate snapshot passage about user choice and safety.",
        )
        debate_id = str(uuid4())
        now = datetime.now(UTC)
        with database.session() as db:
            versions = []
            for agent_id in (first_agent, second_agent):
                agent = db.get(Agent, agent_id)
                assert agent is not None and agent.current_published_version_id
                version = db.get(AgentVersion, agent.current_published_version_id)
                assert version is not None and version.knowledge_snapshot_id
                versions.append((agent, version))

            db.add(
                Debate(
                    id=debate_id,
                    course_id=COURSE_ID,
                    topic="A CAS test debate",
                    rule_set_id="ordered_multi_agent_rounds_demo_v1",
                    rule_snapshot_json="{}",
                    status="running",
                    revision=0,
                    last_sequence=0,
                    cancellation_generation=0,
                    created_by="08b9de2d-bb75-5c71-a64b-231b48f9eb25",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            participants = []
            for index, (agent, version) in enumerate(versions):
                participants.append(
                    DebateParticipant(
                        id=str(uuid4()),
                        debate_id=debate_id,
                        course_id=COURSE_ID,
                        group_id=str(agent.group_id),
                        agent_id=str(agent.id),
                        agent_version_id=str(version.id),
                        knowledge_snapshot_id=str(version.knowledge_snapshot_id),
                        slot=chr(65 + index),
                        order_index=index,
                        agent_name=str(agent.name),
                        version_label="V1.0",
                        avatar_config_json="{}",
                        requested_voice_profile_id=None,
                        effective_voice_kind="mock_sentinel",
                        effective_voice_profile_id=None,
                        voice_fallback_active=True,
                        stance_mode="open",
                        initial_stance=None,
                        current_stance=None,
                        teacher_note="",
                        initial_position_summary="",
                        current_position_summary="",
                        created_at=now,
                        updated_at=now,
                    )
                )
            db.add_all(participants)
            db.flush()
            turn_ids = [str(uuid4()) for _ in range(4)]
            turns = [
                DebateTurn(
                    id=turn_id,
                    debate_id=debate_id,
                    participant_id=participants[index % 2].id,
                    knowledge_snapshot_id=participants[index % 2].knowledge_snapshot_id,
                    round_no=1 if index < 2 else 2,
                    turn_index=index,
                    generation_status="pending",
                    publication_status="unpublished",
                    preparation_stage="generation",
                    predecessor_turn_ids_json=json.dumps(turn_ids[:index], separators=(",", ":")),
                    cutoff_turn_index=index - 1,
                    attempt=1,
                    created_at=now,
                    updated_at=now,
                )
                for index, turn_id in enumerate(turn_ids)
            ]
            db.add_all(turns)
            db.flush()
            db.add(
                PlaybackState(
                    id=str(uuid4()),
                    debate_id=debate_id,
                    status="ready",
                    mode="live",
                    current_turn_id=turn_ids[0],
                    cursor_ms=0,
                    playback_rate=1.0,
                    control_version=0,
                    controller_epoch=None,
                    controller_owner_connection=None,
                    server_started_at=None,
                    replay_scope=None,
                    replay_index=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()

            repository = SqlPlaybackRepository()
            debate = repository.get_debate(db, debate_id)
            assert debate is not None
            rows = repository.turns(db, debate)
            assert len(rows) == 4

            def reset_turn(turn_id: str) -> None:
                db.execute(
                    text(
                        "UPDATE debate_turns SET generation_status='pending', "
                        "preparation_stage='generation', transcript_hash=NULL, attempt=1 "
                        "WHERE id=:turn_id"
                    ),
                    {"turn_id": turn_id},
                )
                db.execute(
                    text(
                        "UPDATE jobs SET state='pending', claim_token=NULL, attempt=0 "
                        "WHERE turn_id=:turn_id"
                    ),
                    {"turn_id": turn_id},
                )

            turn = rows[1]
            expected = PreparedGenerationFence(
                predecessor_turn_ids=(turn_ids[0],),
                transcript_hash="a" * 64,
                cutoff_turn_index=0,
                attempt=1,
            )
            token = repository.claim_turn_job(db, debate, turn, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    turn,
                    cancellation_generation=0,
                    claim_token=token + "-stale",
                    fence=expected,
                )
                is False
            )
            reset_turn(turn.id)

            stale_prefix = PreparedGenerationFence(
                predecessor_turn_ids=(),
                transcript_hash="a" * 64,
                cutoff_turn_index=0,
                attempt=1,
            )
            token = repository.claim_turn_job(db, debate, turn, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    turn,
                    cancellation_generation=0,
                    claim_token=token,
                    fence=stale_prefix,
                )
                is False
            )
            reset_turn(turn.id)

            db.execute(
                text("UPDATE debate_turns SET transcript_hash=:hash WHERE id=:turn_id"),
                {"hash": "b" * 64, "turn_id": turn.id},
            )
            token = repository.claim_turn_job(db, debate, turn, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    turn,
                    cancellation_generation=0,
                    claim_token=token,
                    fence=expected,
                )
                is False
            )
            reset_turn(turn.id)

            stale_cutoff = PreparedGenerationFence(
                predecessor_turn_ids=(turn_ids[0],),
                transcript_hash="a" * 64,
                cutoff_turn_index=1,
                attempt=1,
            )
            token = repository.claim_turn_job(db, debate, turn, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    turn,
                    cancellation_generation=0,
                    claim_token=token,
                    fence=stale_cutoff,
                )
                is False
            )
            reset_turn(turn.id)

            stale_attempt = PreparedGenerationFence(
                predecessor_turn_ids=(turn_ids[0],),
                transcript_hash="a" * 64,
                cutoff_turn_index=0,
                attempt=2,
            )
            token = repository.claim_turn_job(db, debate, turn, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    turn,
                    cancellation_generation=0,
                    claim_token=token,
                    fence=stale_attempt,
                )
                is False
            )
            reset_turn(turn.id)

            # A later-than-immediate successor must be fenced even when its
            # predecessor tuple is otherwise well-shaped.
            later = rows[2]
            later_fence = PreparedGenerationFence(
                predecessor_turn_ids=(turn_ids[0], turn_ids[1]),
                transcript_hash="c" * 64,
                cutoff_turn_index=1,
                attempt=1,
            )
            token = repository.claim_turn_job(db, debate, later, cancellation_generation=0)
            assert token
            assert (
                repository.mark_turn_running(
                    db,
                    later,
                    cancellation_generation=0,
                    claim_token=token,
                    fence=later_fence,
                )
                is False
            )

            # Stopping increments the generation in the owning transaction;
            # old running/pending jobs are then interrupted and cannot claim.
            db.execute(
                text("UPDATE debates SET cancellation_generation=1 WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            repository.mark_jobs_interrupted(db, debate, "debate_stopped")
            job_state = db.execute(
                text("SELECT state FROM jobs WHERE turn_id=:turn_id"),
                {"turn_id": later.id},
            ).scalar_one()
            assert job_state == "interrupted"
            assert (
                repository.claim_turn_job(
                    db,
                    debate,
                    later,
                    cancellation_generation=0,
                )
                is None
            )
