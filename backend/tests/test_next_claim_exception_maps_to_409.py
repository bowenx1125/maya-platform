"""Next claim: rowid→id CAS, soft-fail to 409, text path with tts_voice_unavailable."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from app.core.errors import PlatformError
from app.modules.debates.playback import sql_repository as sql_repository_module
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    MemoryTurn,
)
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository


def _ready_pair(
    *,
    failed_code: str = "tts_voice_unavailable",
    preparation_stage: str | None = "ready",
) -> tuple[MemoryDebate, MemoryTurn, MemoryTurn, PlaybackService]:
    repository = MemoryPlaybackRepository()
    debate = MemoryDebate(
        status="running",
        participants=[MemoryParticipant(name="A"), MemoryParticipant(name="B")],
    )
    repository.add_debate(debate)
    current = MemoryTurn(
        participant_id=debate.participants[0].id,
        round_no=1,
        turn_index=0,
        generation_status="final_ready",
        publication_status="public",
        preparation_stage="ready",
        speech="A complete classroom speech for the current turn.",
        audio_file_id="audio-0",
    )
    # D2 text-fallback successor: final_ready + ready + unpublished +
    # tts_voice_unavailable + speech + audio null (prepare completed implied).
    successor = MemoryTurn(
        participant_id=debate.participants[1].id,
        round_no=1,
        turn_index=1,
        generation_status="final_ready",
        publication_status="unpublished",
        preparation_stage=preparation_stage,
        speech="Successor speech ready for next.",
        audio_file_id=None,
        audio_duration_ms=None,
        failed_code=failed_code,
    )
    debate.turns = [current, successor]
    debate.playback.status = "waiting_next"
    debate.playback.mode = "live"
    debate.playback.current_turn_id = current.id
    service = PlaybackService(repository)
    return debate, current, successor, service


@pytest.mark.asyncio
async def test_next_claim_runtime_error_maps_to_next_not_ready_not_503() -> None:
    debate, current, _successor, service = _ready_pair()

    def boom(**_kwargs: Any) -> bool:
        raise RuntimeError("text publication lost its current turn fence")

    service.repository.claim_next_playback = boom  # type: ignore[method-assign]

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=debate.playback.control_version,
            expected_current_turn_id=current.id,
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "next_not_ready"
    assert raised.value.code != "provider_unavailable"
    assert debate.playback.current_turn_id == current.id
    assert debate.playback.control_version == 0


@pytest.mark.asyncio
async def test_next_claim_integrity_error_maps_to_next_not_ready() -> None:
    debate, current, _successor, service = _ready_pair()

    def boom(**_kwargs: Any) -> bool:
        raise RuntimeError("simulated SQL integrity failure")

    service.repository.claim_next_playback = boom  # type: ignore[method-assign]

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=0,
            expected_current_turn_id=current.id,
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "next_not_ready"


def test_claim_next_playback_swallows_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _FakeSession:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("unexpected claim SQL failure")

        def rollback(self) -> None:
            calls.append("rollback")

        def close(self) -> None:
            calls.append("close")

        def commit(self) -> None:
            calls.append("commit")

    repo = SqlPlaybackRepository(session_factory=lambda: _FakeSession())
    monkeypatch.setattr(
        "app.modules.debates.playback.sql_repository.begin_immediate",
        lambda _session: None,
    )
    assert (
        repo.claim_next_playback(
            debate_id="debate",
            expected_control_version=1,
            expected_current_turn_id="current",
            successor_turn_id="successor",
            teacher_user_id="teacher",
        )
        is False
    )
    assert "rollback" in calls
    assert "close" in calls
    assert "commit" not in calls


@pytest.mark.asyncio
async def test_next_not_ready_when_preparation_stage_not_ready() -> None:
    debate, current, successor, service = _ready_pair()
    successor.preparation_stage = "generation"

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=0,
            expected_current_turn_id=current.id,
        )

    assert raised.value.code == "next_not_ready"
    assert debate.playback.current_turn_id == current.id


@pytest.mark.asyncio
async def test_next_advances_for_tts_voice_unavailable_text_successor() -> None:
    """Successor final_ready + tts_voice_unavailable + speech + audio null → Next OK."""
    debate, current, successor, service = _ready_pair(
        failed_code="tts_voice_unavailable",
        preparation_stage="ready",
    )

    def claim_ok(**_kwargs: Any) -> bool:
        # Mimic durable claim success: bump CAS and point at successor.
        debate.playback.current_turn_id = successor.id
        debate.playback.control_version += 1
        debate.playback.status = "ready"
        return True

    service.repository.claim_next_playback = claim_ok  # type: ignore[method-assign]

    state = await service.next(
        None,
        debate.id,
        expected_control_version=0,
        expected_current_turn_id=current.id,
    )

    assert str(state.current_turn_id) == successor.id
    assert state.control_version == 1
    assert debate.playback.current_turn_id == successor.id


def test_playback_states_claim_sql_uses_id_not_sqlite_rowid() -> None:
    """Postgres has no ps.rowid; playback_states CAS must use the id PK."""
    source = inspect.getsource(sql_repository_module.SqlPlaybackRepository)
    assert "ps.rowid" not in source
    assert "WHERE rowid=" not in source
    assert "AS claim_rowid" not in source
    assert "ps.id AS claim_id" in source
    assert "WHERE id=:claim_id" in source
    # Pause/resume/finish/replay claims also bind the real PK.
    assert source.count("SELECT ps.id") >= 3
