"""Next claim: rowid→id CAS, soft-fail to 409, false-race→next_not_ready, text path."""

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


@pytest.mark.asyncio
async def test_next_claim_false_unchanged_still_ready_is_next_not_ready_not_controller() -> None:
    """Hard rule: claim miss + unchanged CAS must never say another controller.

    Prod A @ 201bcff: single-tab Next got stale_control_version while successor
    was still text-ready — claim was stricter than _next_turn_ready.
    """
    debate, current, _successor, service = _ready_pair()

    def claim_miss(**_kwargs: Any) -> bool:
        return False

    service.repository.claim_next_playback = claim_miss  # type: ignore[method-assign]

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=debate.playback.control_version,
            expected_current_turn_id=current.id,
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "next_not_ready"
    assert raised.value.code != "stale_control_version"
    assert "another controller" not in raised.value.message.lower()
    assert debate.playback.current_turn_id == current.id
    assert debate.playback.control_version == 0


@pytest.mark.asyncio
async def test_next_claim_false_bumped_version_is_controller_race() -> None:
    """True race: claim miss after control_version bump → another controller."""
    debate, current, _successor, service = _ready_pair()

    def claim_miss_after_bump(**_kwargs: Any) -> bool:
        debate.playback.control_version += 1
        return False

    service.repository.claim_next_playback = claim_miss_after_bump  # type: ignore[method-assign]

    with pytest.raises(PlatformError) as raised:
        await service.next(
            None,
            debate.id,
            expected_control_version=0,
            expected_current_turn_id=current.id,
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "stale_control_version"
    assert "another controller" in raised.value.message.lower()
    assert debate.playback.current_turn_id == current.id


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


def test_tts_voice_unavailable_text_claim_advances(app_factory) -> None:
    """Prod D2: waiting_next + final_ready + tts_voice_unavailable → claim True via id PK."""
    from sqlalchemy import text

    from tests.test_pw3_playback_sql import TEACHER_ID, _add_live_successor, _seed_one_turn

    database, _settings, debate_id, first = _seed_one_turn(app_factory)
    successor = _add_live_successor(database, debate_id, first)
    with database.session() as db:
        db.execute(
            text(
                "UPDATE debate_turns SET audio_file_id=NULL, audio_duration_ms=NULL, "
                "predecessor_turn_ids_json='[]', cutoff_turn_index=-1, "
                "safe_error_code='tts_voice_unavailable' WHERE id=:id"
            ),
            {"id": successor},
        )
        db.execute(
            text(
                "UPDATE playback_states SET status='waiting_next', mode='live', "
                "current_turn_id=:turn_id, control_version=8, "
                "replay_scope=NULL, replay_index=NULL WHERE debate_id=:debate_id"
            ),
            {"turn_id": first, "debate_id": debate_id},
        )
    repo = SqlPlaybackRepository(session_factory=database.session_factory)
    assert repo.claim_next_playback(
        debate_id=debate_id,
        expected_control_version=8,
        expected_current_turn_id=first,
        successor_turn_id=successor,
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
        assert row[0] in {"waiting_next", "ready"}
        assert row[1] == successor
        assert int(row[2]) >= 9


def test_claim_next_playback_sql_has_no_sqlite_rowid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres dialect path must emit ps.id, never rowid."""
    captured: list[str] = []

    class _Result:
        def first(self) -> None:
            return None

    class _FakeBind:
        class dialect:
            name = "postgresql"

    class _FakeSession:
        def get_bind(self) -> _FakeBind:
            return _FakeBind()

        def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
            captured.append(str(getattr(statement, "text", statement)))
            return _Result()

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

        def commit(self) -> None:
            return None

    repo = SqlPlaybackRepository(session_factory=lambda: _FakeSession())
    monkeypatch.setattr(
        "app.modules.debates.playback.sql_repository.begin_immediate",
        lambda _session, **_kwargs: None,
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
    assert captured
    joined = "\n".join(captured).lower()
    assert "rowid" not in joined
    assert "ps.id" in joined or " id=" in joined
    # R1: AmbiguousParameter — never bind ``:teacher_user_id IS NOT NULL``.
    assert "teacher_user_id is not null" not in joined
    assert ":teacher_user_id is not null" not in joined
    # R1 secondary: PG predecessor compare must be jsonb, not spaced json_agg::text.
    assert "jsonb_agg" in joined
    assert "::jsonb" in joined


def test_claim_next_rejects_missing_teacher_without_sql() -> None:
    """Python gate avoids Postgres AmbiguousParameter on IS NOT NULL bind."""
    repo = SqlPlaybackRepository(
        session_factory=lambda: (_ for _ in ()).throw(RuntimeError("no sql"))
    )
    assert (
        repo.claim_next_playback(
            debate_id="debate",
            expected_control_version=1,
            expected_current_turn_id="current",
            successor_turn_id="successor",
            teacher_user_id=None,
        )
        is False
    )


def test_claim_next_source_has_no_teacher_is_not_null_bind() -> None:
    source = inspect.getsource(sql_repository_module.SqlPlaybackRepository.claim_next_playback)
    # Comment may mention the old bind; SQL string must not emit it.
    assert '"AND :teacher_user_id IS NOT NULL "' not in source
    assert "AND :teacher_user_id IS NOT NULL" not in source.replace(
        "``:teacher_user_id IS NOT NULL``", ""
    )
    assert "jsonb_agg" in source
    assert "predecessor_eq" in source
