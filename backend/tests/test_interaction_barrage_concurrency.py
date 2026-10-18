"""Concurrent barrages must keep a distinct sequence per submission.

``MAX(sequence)+1`` collides on Postgres and on SQLite once ``BEGIN IMMEDIATE``
is a no-op. The unique violation used to be reported as ``idempotency_conflict``
for a client id that was never stored.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.db import create_engine as _create_engine
from app.core.errors import PlatformError
from app.main import create_app
from app.modules.debates.models import DebateEvent
from app.modules.interactions import service as interaction_service
from app.modules.interactions.models import BarrageMessage, ClassroomInteractionWindow
from app.modules.interactions.schemas import BarrageRequest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.pool import NullPool

from tests.test_wave3_interactions import TEACHER_ID, _seed_finished_debate, _service

_WORKERS = 40
_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")


def _disable_immediate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        interaction_service,
        "begin_immediate",
        lambda session, lock_key=None: None,
    )


def _sqlite_null_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    def create_engine(url: str, **kwargs: Any) -> Any:
        if str(url).startswith("sqlite") and "poolclass" not in kwargs:
            kwargs["poolclass"] = NullPool
        return _create_engine(url, **kwargs)

    monkeypatch.setattr("app.core.db.create_engine", create_engine)


def _open_interaction(database: Database, settings: Settings) -> tuple[Any, str]:
    debate_id, _participant_ids = _seed_finished_debate(database)
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    service, _collector = _service(database, settings)
    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key=f"barrage-race-open-{uuid4()}",
    )
    token = opened.public_url.rsplit("/", 1)[-1]
    return service, token


def _sequences(database: Database) -> list[int]:
    with database.session() as session:
        return sorted(session.scalars(select(BarrageMessage.sequence)).all())


def _submit_many(service: Any, token: str) -> list[str]:
    barrier = Barrier(_WORKERS)

    def one(index: int) -> str:
        barrier.wait(timeout=30)
        try:
            service.submit_barrage(
                access_token=token,
                payload=BarrageRequest(
                    nickname=f"s{index}",
                    raw_text=f"hello {index}",
                    client_submission_id=uuid4(),
                ),
            )
        except PlatformError as exc:
            return exc.code
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}:{exc}"
        return "ok"

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        return list(pool.map(one, range(_WORKERS)))


def test_concurrent_barrages_without_immediate_keep_every_sequence(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sqlite_null_pool(monkeypatch)
    _disable_immediate(monkeypatch)
    app, database, settings = app_factory()
    with TestClient(app):
        service, token = _open_interaction(database, settings)
        results = _submit_many(service, token)
        sequences = _sequences(database)
        with database.session() as session:
            events = list(
                session.scalars(select(DebateEvent.sequence).order_by(DebateEvent.sequence)).all()
            )
            stored = session.scalars(select(BarrageMessage.client_submission_id)).all()
    assert results == ["ok"] * _WORKERS, results
    assert sequences == list(range(1, _WORKERS + 1))
    assert len(set(stored)) == _WORKERS
    assert events == list(range(1, len(events) + 1))
    assert len(events) == _WORKERS + 1


def test_forced_sequence_collision_is_not_idempotency(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, database, settings = app_factory()
    real_allocate = interaction_service._allocate_barrage_sequence

    def collide(session: Any, window: Any) -> int:
        del session, window
        return 1

    monkeypatch.setattr(interaction_service, "_allocate_barrage_sequence", collide)
    with TestClient(app):
        service, token = _open_interaction(database, settings)
        monkeypatch.setattr(interaction_service, "_allocate_barrage_sequence", real_allocate)
        service.submit_barrage(
            access_token=token,
            payload=BarrageRequest(
                nickname="first",
                raw_text="stored",
                client_submission_id=uuid4(),
            ),
        )
        monkeypatch.setattr(interaction_service, "_allocate_barrage_sequence", collide)
        with pytest.raises(PlatformError) as caught:
            service.submit_barrage(
                access_token=token,
                payload=BarrageRequest(
                    nickname="second",
                    raw_text="different",
                    client_submission_id=uuid4(),
                ),
            )
        sequences = _sequences(database)
    assert caught.value.code == "stale_sequence"
    assert sequences == [1]


def test_one_sequence_collision_retries_and_stores_the_barrage(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, database, settings = app_factory()
    real_allocate = interaction_service._allocate_barrage_sequence
    calls = {"n": 0}

    def collide_once(session: Any, window: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            return 1
        return real_allocate(session, window)

    monkeypatch.setattr(interaction_service, "_allocate_barrage_sequence", collide_once)
    with TestClient(app):
        service, token = _open_interaction(database, settings)
        for nickname in ("first", "second"):
            service.submit_barrage(
                access_token=token,
                payload=BarrageRequest(
                    nickname=nickname,
                    raw_text=nickname,
                    client_submission_id=uuid4(),
                ),
            )
        sequences = _sequences(database)
    assert calls["n"] >= 3
    assert sequences == [1, 2]


def test_counter_allocation_is_unique_without_immediate(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counter update is the first statement, so SQLite cannot hide a race."""

    _sqlite_null_pool(monkeypatch)
    _disable_immediate(monkeypatch)
    app, database, settings = app_factory()
    with TestClient(app):
        _open_interaction(database, settings)
        with database.session() as session:
            window_id = session.scalar(select(ClassroomInteractionWindow.id))
        assert isinstance(window_id, str)
        barrier = Barrier(_WORKERS)

        def one(_index: int) -> str:
            session = database.session_factory()
            try:
                window = session.get(ClassroomInteractionWindow, window_id)
                assert window is not None
                session.commit()
                barrier.wait(timeout=30)
                sequence = interaction_service._allocate_barrage_sequence(session, window)
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                return f"{type(exc).__name__}:{exc}"
            finally:
                session.close()
            return str(sequence)

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(one, range(_WORKERS)))
    numbers = sorted(int(item) for item in results)
    assert numbers == list(range(1, _WORKERS + 1))


@pytest.fixture
def postgres_interaction(app_factory: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    monkeypatch.setattr("app.core.db.POSTGRES_POOL_SIZE", 10)
    monkeypatch.setattr("app.core.db.POSTGRES_MAX_OVERFLOW", 50)
    _disable_immediate(monkeypatch)
    _app, _database, settings = app_factory()
    engine = _create_engine(_POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()
    pg_settings = settings.model_copy(update={"database_url": _POSTGRES_URL, "data_root": tmp_path})
    database = Database(pg_settings.database_url, pg_settings.data_root)
    app = create_app(pg_settings, database)
    with TestClient(app):
        yield database, pg_settings
    database.engine.dispose()


def test_postgres_concurrent_barrages_commit_every_row(postgres_interaction: Any) -> None:
    database, settings = postgres_interaction
    service, token = _open_interaction(database, settings)
    results = _submit_many(service, token)
    sequences = _sequences(database)
    with database.session() as session:
        events = list(
            session.scalars(select(DebateEvent.sequence).order_by(DebateEvent.sequence)).all()
        )
    assert results == ["ok"] * _WORKERS, results
    assert sequences == list(range(1, _WORKERS + 1))
    assert events == list(range(1, len(events) + 1))
    assert len(events) == _WORKERS + 1
