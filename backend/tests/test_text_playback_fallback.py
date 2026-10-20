"""Text publication uses the same teacher, prefix and durable generation fences."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.modules.debates.models import DebateTurn
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    PreparedTurn,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository
from app.providers.llm import MockLLMProvider
from app.providers.tts import (
    MockTTSProvider,
    TTSProviderError,
    TTSProviderTimeout,
    TTSProviderUnavailableError,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.test_pw3_playback_sql import TEACHER_ID, _add_live_successor, _seed_one_turn
from tests.test_wave2_playback import (
    COURSE_ID,
    GROUP_DEMO_ID,
    _headers,
    _insert_published_agent,
    _valid_speech,
)


class UnavailableTTS(MockTTSProvider):
    def synthesize(self, *args: Any, **kwargs: Any) -> Any:
        raise TTSProviderTimeout()


def _wait(client: TestClient, debate_id: str, predicate: Any) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/debates/{debate_id}")
        assert response.status_code == 200, response.text
        detail = response.json()
        if predicate(detail):
            return detail
        time.sleep(0.02)
    raise AssertionError(f"Text playback did not settle: {detail}")


@pytest.mark.parametrize("voice_missing", [False, True])
def test_four_round_text_only_http_lifecycle(app_factory: Any, voice_missing: bool) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        app.state.prewarm_scheduler._closed = False
        llm = MockLLMProvider()
        service = app.state.playback_service
        service.turn_preparer = SqlTurnPreparer(settings=settings, llm=llm)
        service.audio_store.tts_provider = UnavailableTTS()
        if voice_missing:
            # The selected voice adapter is never invoked: no ready profile exists.
            settings.voice_provider = "dashscope"
            settings.tts_provider = "dashscope"
        agents = [
            _insert_published_agent(
                database,
                group_id=GROUP_DEMO_ID,
                name=f"Text only {index}",
                evidence="A classroom can compare evidence and respect different viewpoints.",
            )
            for index in range(2)
        ]
        _, csrf = login(client)
        headers = _headers(csrf, **{"Idempotency-Key": str(uuid4())})
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=headers,
            json={
                "topic": "How should a classroom compare different viewpoints?",
                "round_count": 4,
                "output_language": "en",
                "participants": [{"agent_id": item, "stance_mode": "open"} for item in agents],
            },
        )
        if voice_missing:
            # Real TTS + no ready voice is refused up front; text-only lifecycle
            # under a mock provider is covered by voice_missing=False below.
            assert created.status_code == 422, created.text
            error = created.json().get("error", created.json())
            assert error["code"] == "agent_voice_missing"
            assert error["details"]["agent_names"] == ["Text only 0", "Text only 1"]
            return
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        detail = _wait(client, debate_id, lambda item: item["preview"]["ready"])
        assert detail["preview"]["prepared_turns"] == 6
        assert detail["public_turns"] == []
        assert llm.calls == 6
        summaries = client.get(f"/api/v1/courses/{COURSE_ID}/debates")
        assert summaries.status_code == 200, summaries.text
        summary = next(item for item in summaries.json() if item["id"] == debate_id)
        assert summary["preview"]["ready"] is True
        assert summary["preview"]["prepared_turns"] == 6
        assert summary["audio_restore_needed"] is True
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            json={
                "expected_revision": detail["revision"],
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        detail = _wait(client, debate_id, lambda item: len(item["public_turns"]) == 1)
        assert detail["playback"]["status"] == "waiting_next"
        assert detail["playback"]["next_turn_ready"] is True
        for index in range(1, 8):
            if index == 6:
                assert llm.calls == 6
                assert detail["playback"]["next_turn_ready"] is False
                frozen = client.post(
                    f"/api/v1/debates/{debate_id}/final-input",
                    headers=_headers(csrf),
                    json={"expected_control_version": detail["playback"]["control_version"]},
                )
                assert frozen.status_code == 200, frozen.text
            detail = _wait(client, debate_id, lambda item: item["playback"]["next_turn_ready"])
            state = detail["playback"]
            advanced = client.post(
                f"/api/v1/debates/{debate_id}/next",
                headers=_headers(csrf),
                json={
                    "expected_control_version": state["control_version"],
                    "expected_current_turn_id": state["current_turn_id"],
                },
            )
            assert advanced.status_code == 200, advanced.text
            assert advanced.json()["status"] == "waiting_next"
            detail = _wait(
                client, debate_id, lambda item, count=index + 1: len(item["public_turns"]) == count
            )
            assert all(turn["audio_ready"] is False for turn in detail["public_turns"])
        assert llm.calls == 8
        assert detail["playback"]["next_turn_ready"] is False
        state = detail["playback"]
        finished = client.post(
            f"/api/v1/debates/{debate_id}/finish",
            headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            json={
                "expected_control_version": state["control_version"],
                "expected_current_turn_id": state["current_turn_id"],
            },
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["playback"]["status"] == "completed"
        assert len(client.get(f"/api/v1/debates/{debate_id}").json()["public_turns"]) == 8
        assert llm.calls == 8
        with database.session() as db:
            turns = db.scalars(select(DebateTurn).where(DebateTurn.debate_id == debate_id)).all()
            assert len(turns) == 8
            assert all(turn.generation_status == "final_ready" for turn in turns)
            assert all(turn.audio_file_id is None for turn in turns)
            assert all(turn.safe_error_code == "tts_timeout" for turn in turns)
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM debate_events WHERE debate_id=:id "
                        "AND event_type='playback.started'"
                    ),
                    {"id": debate_id},
                ).scalar_one()
                == 0
            )


@pytest.mark.parametrize("error_code", [None, "acceptance_unknown", "tts_unreviewed", "tts_failed"])
def test_missing_audio_without_known_tts_failure_cannot_advance(
    app_factory: Any, error_code: str | None
) -> None:
    database, _settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code=:code WHERE id=:id"
            ),
            {"id": successor, "code": error_code},
        )
    repo = SqlPlaybackRepository(session_factory=database.session_factory)
    assert not repo.claim_next_playback(
        debate_id=debate_id,
        expected_control_version=8,
        expected_current_turn_id=first,
        successor_turn_id=successor,
        teacher_user_id=TEACHER_ID,
    )


def test_text_next_has_one_cross_process_winner_and_one_publication(app_factory: Any) -> None:
    database, _settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code='tts_timeout' WHERE id=:id"
            ),
            {"id": successor},
        )

    def advance() -> bool:
        return SqlPlaybackRepository(session_factory=database.session_factory).claim_next_playback(
            debate_id=debate_id,
            expected_control_version=8,
            expected_current_turn_id=first,
            successor_turn_id=successor,
            teacher_user_id=TEACHER_ID,
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(lambda _index: advance(), range(2))) == [False, True]
    with database.session() as db:
        assert db.get(DebateTurn, successor).publication_status == "public"
        assert db.execute(
            text(
                "SELECT status, current_turn_id, control_version FROM playback_states "
                "WHERE debate_id=:id"
            ),
            {"id": debate_id},
        ).one() == ("waiting_next", successor, 10)
        assert (
            db.execute(
                text(
                    "SELECT COUNT(*) FROM debate_events WHERE debate_id=:id "
                    "AND event_type='playback.waiting_next'"
                ),
                {"id": debate_id},
            ).scalar_one()
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["playing", "paused"])
async def test_text_successor_does_not_interrupt_current_audio(tmp_path: Path, status: str) -> None:
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            status="running",
            participants=[MemoryParticipant(), MemoryParticipant(slot="B", order_index=1)],
        )
    )
    turns = repository.ensure_turn_plan(None, debate)
    turns[0].generation_status = "final_ready"
    turns[0].publication_status = "public"
    turns[0].speech = "An already public current turn."
    debate.playback.current_turn_id = turns[0].id
    debate.playback.status = status
    service = PlaybackService(
        repository, audio_store=AudioStore(tmp_path, tts_provider=UnavailableTTS())
    )
    try:
        await service.prepare_turn(None, debate.id, turns[1].id)
        assert turns[1].generation_status == "final_ready"
        assert turns[1].publication_status == "unpublished"
        assert turns[1].failed_code == "tts_timeout"
        assert debate.playback.status == status
        assert debate.playback.current_turn_id == turns[0].id
        assert all(
            event.event_type != "playback.waiting_next"
            for event in service.event_hub.store.events_after(debate.id, 0)
        )
    finally:
        await service.task_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["runtime", "unreviewed_tts"])
async def test_unknown_audio_errors_are_not_text_success(tmp_path: Path, kind: str) -> None:
    class FailedTTS(MockTTSProvider):
        def synthesize(self, *args: Any, **kwargs: Any) -> Any:
            if kind == "runtime":
                raise RuntimeError("local failure")
            raise TTSProviderError(safe_code="tts_unreviewed")

    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            status="running",
            participants=[MemoryParticipant(), MemoryParticipant(slot="B", order_index=1)],
        )
    )
    turn = repository.ensure_turn_plan(None, debate)[0]
    debate.playback.current_turn_id = turn.id
    service = PlaybackService(
        repository, audio_store=AudioStore(tmp_path, tts_provider=FailedTTS())
    )
    try:
        await service.prepare_turn(None, debate.id, turn.id)
        assert turn.generation_status != "final_ready"
        assert turn.publication_status == "unpublished"
    finally:
        await service.task_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("recovery", ["startup", "controller"])
async def test_selected_text_recovers_without_supplier_calls(
    app_factory: Any, recovery: str
) -> None:
    database, settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code='tts_timeout' WHERE id=:id"
            ),
            {"id": successor},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', current_turn_id=:turn_id "
                "WHERE debate_id=:id"
            ),
            {"id": debate_id, "turn_id": successor},
        )

    def no_provider(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("recovering final-ready text must not call a supplier")

    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        turn_preparer=no_provider,
        session_factory=database.session_factory,
        settings=settings,
    )
    try:
        with database.session() as db:
            if recovery == "startup":
                await service._resume_running_debates(db)
                await service._resume_running_debates(db)
            else:
                await service.controller_acquire(
                    db,
                    debate_id,
                    command_id=str(uuid4()),
                    expected_control_version=8,
                    session_hash="isolated-session",
                    connection_id="isolated-tab",
                    context=SimpleNamespace(user=SimpleNamespace(id=TEACHER_ID)),
                )
        with database.session() as db:
            assert db.get(DebateTurn, successor).publication_status == "public"
            assert (
                db.execute(
                    text("SELECT status FROM playback_states WHERE debate_id=:id"),
                    {"id": debate_id},
                ).scalar_one()
                == "waiting_next"
            )
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM debate_events WHERE debate_id=:id "
                        "AND event_type='playback.waiting_next'"
                    ),
                    {"id": debate_id},
                ).scalar_one()
                == 1
            )
    finally:
        await service.task_manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_unavailable", [False, True])
async def test_legacy_two_round_text_flow_never_regenerates_successful_text(
    tmp_path: Path, provider_unavailable: bool
) -> None:
    class UnavailableProviderTTS(MockTTSProvider):
        key = "dashscope"

        def synthesize(self, *args: Any, **kwargs: Any) -> Any:
            raise TTSProviderUnavailableError()

    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            status="running",
            participants=[MemoryParticipant(), MemoryParticipant(slot="B", order_index=1)],
        )
    )
    turns = repository.ensure_turn_plan(None, debate)
    debate.playback.current_turn_id = turns[0].id
    calls: list[str] = []

    def prepare(_db: Any, _debate: Any, turn: Any, **kwargs: Any) -> PreparedTurn:
        calls.append(turn.id)
        return PreparedTurn(speech=_valid_speech())

    async def no_background(_debate: Any, _turn: Any) -> bool:
        return False

    tts = UnavailableProviderTTS() if provider_unavailable else UnavailableTTS()
    service = PlaybackService(
        repository,
        turn_preparer=prepare,
        tts_provider=tts,
        audio_store=AudioStore(tmp_path, tts_provider=tts),
    )
    service._enqueue = no_background
    try:
        for index, turn in enumerate(turns):
            await service.prepare_turn(None, debate.id, turn.id)
            if index:
                assert turn.publication_status == "unpublished"
                state = debate.playback
                await service.next(
                    None,
                    debate.id,
                    expected_control_version=state.control_version,
                    expected_current_turn_id=state.current_turn_id,
                )
            assert turn.publication_status == "public"
            assert debate.playback.status == "waiting_next"
            await service.prepare_turn(None, debate.id, turn.id)
        assert calls == [turn.id for turn in turns]
        expected = "tts_provider_unavailable" if provider_unavailable else "tts_timeout"
        assert all(turn.failed_code == expected and turn.audio_file_id is None for turn in turns)
        result = await service.finish(
            None,
            debate.id,
            expected_control_version=debate.playback.control_version,
            expected_current_turn_id=turns[-1].id,
        )
        assert result.status == "completed"
    finally:
        await service.task_manager.close()


def test_non_speech_provider_gate_remains_closed() -> None:
    from app.core.errors import PlatformError

    service = PlaybackService(settings=SimpleNamespace(embedding_provider="unsupported"))
    with pytest.raises(PlatformError) as error:
        service._provider_allowed()
    assert error.value.code == "provider_unavailable"


@pytest.mark.parametrize(
    "change",
    ["draft", "stopped", "cancelled", "controller", "current", "prefix", "job", "cutoff", "replay"],
)
def test_text_publication_rechecks_durable_fences(app_factory: Any, change: str) -> None:
    database, _settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code='tts_timeout' WHERE id=:id"
            ),
            {"id": successor},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='preparing', current_turn_id=:turn_id "
                "WHERE debate_id=:id"
            ),
            {"id": debate_id, "turn_id": successor},
        )
        changes = {
            "draft": ("UPDATE debates SET status='draft' WHERE id=:id", debate_id),
            "stopped": ("UPDATE debates SET status='debate_finished' WHERE id=:id", debate_id),
            "cancelled": ("UPDATE debates SET cancellation_generation=1 WHERE id=:id", debate_id),
            "controller": (
                "UPDATE playback_states SET control_version=9 WHERE debate_id=:id",
                debate_id,
            ),
            "current": (
                "UPDATE playback_states SET current_turn_id=NULL WHERE debate_id=:id",
                debate_id,
            ),
            "prefix": (
                "UPDATE debate_turns SET publication_status='unpublished' WHERE id=:id",
                first,
            ),
            "job": ("UPDATE jobs SET state='pending' WHERE turn_id=:id", successor),
            "cutoff": ("UPDATE debate_turns SET cutoff_turn_index=0 WHERE id=:id", successor),
            "replay": ("UPDATE playback_states SET mode='replay' WHERE debate_id=:id", debate_id),
        }
        statement, target = changes[change]
        db.execute(text(statement), {"id": target})
    repo = SqlPlaybackRepository(session_factory=database.session_factory)
    assert (
        repo.claim_text_playback(
            debate_id=debate_id,
            expected_control_version=8,
            turn_id=successor,
            expected_generation=0,
        )
        is None
    )
    with database.session() as db:
        assert db.get(DebateTurn, successor).publication_status == "unpublished"


def test_text_next_keeps_teacher_authorization(app_factory: Any) -> None:
    database, _settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code='tts_timeout' WHERE id=:id"
            ),
            {"id": successor},
        )
    repo = SqlPlaybackRepository(session_factory=database.session_factory)
    assert not repo.claim_next_playback(
        debate_id=debate_id,
        expected_control_version=8,
        expected_current_turn_id=first,
        successor_turn_id=successor,
        teacher_user_id=str(uuid4()),
    )
    with database.session() as db:
        assert db.get(DebateTurn, successor).publication_status == "unpublished"
