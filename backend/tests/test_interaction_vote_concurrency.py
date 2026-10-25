"""Concurrent votes must not lose to a stale debate sequence.

SQLite's writer lock hides a compare-and-swap on ``debates.last_sequence``.
Postgres lets two transactions observe the same watermark. These tests disable
``BEGIN IMMEDIATE`` and either start from a stale identity map or run on
Postgres.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.db import create_engine as _create_engine
from app.core.errors import PlatformError
from app.main import create_app
from app.modules.debates.models import Debate, DebateEvent
from app.modules.interactions import service as interaction_service
from app.modules.interactions.models import Vote
from app.modules.interactions.schemas import VoteRequest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from tests.postgres_db import named_url
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


def _open_interaction(database: Database, settings: Settings) -> tuple[Any, str, list[str], str]:
    debate_id, participant_ids = _seed_finished_debate(database)
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    service, _collector = _service(database, settings)
    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key=f"vote-race-open-{uuid4()}",
    )
    token = opened.public_url.rsplit("/", 1)[-1]
    return service, token, participant_ids, debate_id


def _event_sequences(database: Database) -> list[int]:
    with database.session() as session:
        return list(
            session.scalars(select(DebateEvent.sequence).order_by(DebateEvent.sequence)).all()
        )


def test_stale_identity_map_still_allocates_unique_event_sequences(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """40 callers share one watermark, then append. CAS used to keep one."""

    _sqlite_null_pool(monkeypatch)
    _disable_immediate(monkeypatch)
    app, database, settings = app_factory()
    with TestClient(app):
        _open_interaction(database, settings)
        with database.session() as session:
            debate_id = session.scalar(select(Debate.id))
        assert isinstance(debate_id, str)
        barrier = Barrier(_WORKERS)

        def one(index: int) -> str:
            session = database.session_factory()
            try:
                debate = session.get(Debate, debate_id)
                assert debate is not None
                # End the read so the next statement is the sequence update.
                # The in-memory watermark stays stale (expire_on_commit is off).
                session.commit()
                barrier.wait(timeout=30)
                interaction_service._event(
                    session,
                    debate,
                    "interaction.vote_created",
                    {"n": index},
                )
                session.commit()
            except PlatformError as exc:
                session.rollback()
                return exc.code
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                return f"{type(exc).__name__}:{exc}"
            finally:
                session.close()
            return "ok"

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(one, range(_WORKERS)))
        sequences = _event_sequences(database)
    assert results == ["ok"] * _WORKERS
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(sequences) == _WORKERS + 1


def test_concurrent_votes_without_immediate_keep_every_submission(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sqlite_null_pool(monkeypatch)
    _disable_immediate(monkeypatch)
    app, database, settings = app_factory()
    with TestClient(app):
        service, token, participant_ids, _debate_id = _open_interaction(database, settings)
        barrier = Barrier(_WORKERS)

        def one(index: int) -> str:
            barrier.wait(timeout=30)
            try:
                service.submit_vote(
                    access_token=token,
                    payload=VoteRequest(
                        participant_id=UUID(participant_ids[index % len(participant_ids)]),
                        client_submission_id=uuid4(),
                    ),
                )
            except PlatformError as exc:
                return exc.code
            except Exception as exc:  # noqa: BLE001
                return f"{type(exc).__name__}:{exc}"
            return "ok"

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(one, range(_WORKERS)))
        with database.session() as session:
            stored = session.scalars(select(Vote.client_submission_id)).all()
        sequences = _event_sequences(database)
    assert results == ["ok"] * _WORKERS
    assert len(set(stored)) == _WORKERS
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(sequences) == _WORKERS + 1


def test_event_sequence_collision_retries_then_stores_the_vote(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, database, settings = app_factory()
    real_event = interaction_service._event
    calls = {"n": 0}

    def collide_once(session: Any, debate: Any, event_type: str, payload: Any) -> Any:
        if event_type != "interaction.vote_created":
            return real_event(session, debate, event_type, payload)
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError(
                "INSERT",
                {},
                Exception(
                    "UNIQUE constraint failed: debate_events.debate_id, debate_events.sequence"
                ),
            )
        return real_event(session, debate, event_type, payload)

    monkeypatch.setattr(interaction_service, "_event", collide_once)
    with TestClient(app):
        service, token, participant_ids, _debate_id = _open_interaction(database, settings)
        service.submit_vote(
            access_token=token,
            payload=VoteRequest(
                participant_id=UUID(participant_ids[0]),
                client_submission_id=uuid4(),
            ),
        )
        with database.session() as session:
            stored = session.scalars(select(Vote.id)).all()
    assert calls["n"] == 2
    assert len(stored) == 1


def test_exhausted_event_sequence_collision_is_not_idempotency(
    app_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, database, settings = app_factory()
    real_event = interaction_service._event

    def always_collide(session: Any, debate: Any, event_type: str, payload: Any) -> Any:
        if event_type != "interaction.vote_created":
            return real_event(session, debate, event_type, payload)
        raise IntegrityError(
            "INSERT",
            {},
            Exception(
                'duplicate key value violates unique constraint "uq_debate_events_debate_sequence"'
            ),
        )

    monkeypatch.setattr(interaction_service, "_event", always_collide)
    with TestClient(app):
        service, token, participant_ids, _debate_id = _open_interaction(database, settings)
        with pytest.raises(PlatformError) as caught:
            service.submit_vote(
                access_token=token,
                payload=VoteRequest(
                    participant_id=UUID(participant_ids[0]),
                    client_submission_id=uuid4(),
                ),
            )
        with database.session() as session:
            stored = session.scalars(select(Vote.id)).all()
    assert caught.value.code == "stale_sequence"
    assert stored == []


@pytest.fixture
def postgres_interaction(app_factory: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    monkeypatch.setattr("app.core.db.POSTGRES_POOL_SIZE", 10)
    monkeypatch.setattr("app.core.db.POSTGRES_MAX_OVERFLOW", 50)
    _disable_immediate(monkeypatch)
    _app, _database, settings = app_factory()
    engine = _create_engine(named_url("pg", schema=False))
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    engine.dispose()
    pg_settings = settings.model_copy(
        update={"database_url": named_url("pg", schema=False), "data_root": tmp_path}
    )
    database = Database(pg_settings.database_url, pg_settings.data_root)
    app = create_app(pg_settings, database)
    with TestClient(app):
        yield database, pg_settings
    database.engine.dispose()


def test_postgres_concurrent_votes_commit_every_row(postgres_interaction: Any) -> None:
    database, settings = postgres_interaction
    service, token, participant_ids, _debate_id = _open_interaction(database, settings)
    barrier = Barrier(_WORKERS)

    def one(index: int) -> str:
        barrier.wait(timeout=30)
        try:
            service.submit_vote(
                access_token=token,
                payload=VoteRequest(
                    participant_id=UUID(participant_ids[index % len(participant_ids)]),
                    client_submission_id=uuid4(),
                ),
            )
        except PlatformError as exc:
            return exc.code
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}:{exc}"
        return "ok"

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(one, range(_WORKERS)))
    with database.session() as session:
        stored = session.scalars(select(Vote.client_submission_id)).all()
    sequences = _event_sequences(database)
    assert results == ["ok"] * _WORKERS, results
    assert len(set(stored)) == _WORKERS
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(sequences) == _WORKERS + 1
