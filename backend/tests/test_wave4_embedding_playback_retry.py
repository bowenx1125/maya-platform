"""Provider confirmation pauses generation without terminating the Debate."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Job
from app.modules.debates.generation.mutual_learning_policy import (
    MUTUAL_LEARNING_RULE_SET_ID,
)
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    TurnPreparer,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.modules.debates.playback.task_manager import TaskManager
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


def _speech() -> str:
    return " ".join(f"classroom-word-{index}" for index in range(80))


@pytest.mark.asyncio
async def test_confirmation_required_is_nonterminal_and_explicit_retry_resumes(
    tmp_path: Path,
) -> None:
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            topic="How should recommendation systems be governed?",
            participants=[
                MemoryParticipant(slot="A", order_index=0, name="A"),
                MemoryParticipant(slot="B", order_index=1, name="B"),
            ],
        )
    )
    calls: list[int] = []

    async def preparer(_db: Any, _debate: Any, _turn: Any, **_kwargs: Any) -> Any:
        calls.append(int(_turn.turn_index))
        if len(calls) == 1:
            raise PlatformError(
                "provider_confirmation_required",
                "private details must not cross the playback event",
                409,
                {"manifest_hash": "a" * 64, "provider": "private-supplier"},
            )
        return {"speech": _speech()}

    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=AudioStore(tmp_path),
        task_manager=tasks,
        turn_preparer=cast(TurnPreparer, preparer),
    )
    started = await service.start(
        None,
        debate.id,
        expected_revision=0,
        expected_current_audio_debate_id=None,
        confirm_previous_audio_cleanup=False,
    )
    await tasks.wait_debate(debate.id)

    first = debate.turns[0]
    assert started.status == "preparing"
    assert debate.status == "running"
    assert first.generation_status == "pending"
    assert first.failed_code == "provider_confirmation_required"
    assert service._state(None, debate).status == "preparing"
    events = tuple(service.event_hub.store.events_after(debate.id, 0))
    assert [event.event_type for event in events] == [
        "debate.started",
        "round.started",
        "turn.preparing",
        "error",
    ]
    error_payload = events[-1].payload
    assert error_payload == {
        "code": "provider_confirmation_required",
        "message": "Teacher confirmation is required before this turn can continue.",
        "request_id": None,
        "recoverable": True,
    }
    assert "manifest" not in str(error_payload).lower()
    assert "supplier" not in str(error_payload).lower()

    retried = await service.retry_preparation(
        None,
        debate.id,
        turn_id=first.id,
        expected_control_version=0,
        idempotency_key=str(uuid4()),
    )
    assert retried.control_version == 1
    await tasks.wait_debate(debate.id)
    # The successful current turn keeps the existing bounded one-turn
    # prefetch behavior, so the adjacent turn is prepared exactly once too.
    assert calls == [0, 0, 1]
    assert debate.status == "running"
    assert first.generation_status == "final_ready"
    assert first.failed_code is None
    assert service._state(None, debate).status == "ready"
    await tasks.close()


@pytest.mark.asyncio
async def test_only_deferred_current_or_adjacent_turn_can_retry(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            topic="How should recommendation systems be governed?",
            participants=[
                MemoryParticipant(slot="A", order_index=0, name="A"),
                MemoryParticipant(slot="B", order_index=1, name="B"),
            ],
        )
    )
    repository.ensure_turn_plan(None, debate)
    debate.status = "running"
    debate.playback.status = "preparing"
    debate.playback.current_turn_id = debate.turns[0].id
    debate.turns[2].generation_status = "pending"
    debate.turns[2].failed_code = "provider_confirmation_required"
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path))

    with pytest.raises(PlatformError) as raised:
        await service.retry_preparation(
            None,
            debate.id,
            turn_id=debate.turns[2].id,
            expected_control_version=0,
        )
    assert raised.value.code == "invalid_state"


def test_sql_defer_restores_pending_job_and_turn_without_failing_debate(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        first_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Deferred A",
            evidence="Evidence for the deferred query.",
            confirmed_persona=True,
        )
        second_agent_id = _insert_sql_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Deferred B",
            evidence="A second view for the deferred query.",
            confirmed_persona=True,
        )
        _teacher, csrf = login(client, "teacher-demo")
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "defer-query-debate-create-001"}),
            json={
                "topic": "How should recommendation systems be governed?",
                "participants": [
                    {"agent_id": first_agent_id, "stance_mode": "open"},
                    {"agent_id": second_agent_id, "stance_mode": "open"},
                ],
                "rule_set_id": MUTUAL_LEARNING_RULE_SET_ID,
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]

        claim_token = str(uuid4())
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            turns = commit_start_plan(db, debate_id=debate_id)
            first = turns[0]
            debate.status = "running"
            first.generation_status = "running"
            first.preparation_stage = "generation"
            first.transcript_hash = "a" * 64
            playback = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
            assert playback is not None
            playback.status = "preparing"
            playback.current_turn_id = first.id
            job = Job(
                id=str(uuid4()),
                document_id=None,
                debate_id=debate_id,
                turn_id=first.id,
                idempotency_key=f"{debate_id}:{first.id}",
                claim_token=claim_token,
                cancellation_generation=0,
                operation="debate_turn_prepare",
                state="running",
                safe_error_code=None,
                attempt=1,
                created_at=first.created_at,
                updated_at=first.updated_at,
            )
            db.add(job)
            db.flush()
            repository = SqlPlaybackRepository(session_factory=database.session_factory)
            debate_row = repository.get_debate(db, debate_id)
            assert debate_row is not None
            turn_row = next(
                item for item in repository.turns(db, debate_row) if str(item.id) == first.id
            )
            assert repository.defer_turn_job(
                db,
                debate_row,
                turn_row,
                claim_token,
                "provider_confirmation_required",
            )

        with database.session() as db:
            debate = db.get(Debate, debate_id)
            first = db.scalar(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            )
            job = db.scalar(select(Job).where(Job.debate_id == debate_id))
            assert debate is not None and debate.status == "running"
            assert first is not None
            assert (
                first.generation_status,
                first.preparation_stage,
                first.transcript_hash,
                first.safe_error_code,
            ) == (
                "pending",
                "generation",
                None,
                "provider_confirmation_required",
            )
            assert job is not None
            assert (job.state, job.claim_token, job.safe_error_code) == (
                "pending",
                None,
                "provider_confirmation_required",
            )
