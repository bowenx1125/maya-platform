"""Password changes release read connections before bounded hashing work."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.core import hash_gate
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.models import Base, SessionRecord, User
from app.modules.auth import profile, registration
from app.modules.auth.models import UserCredential
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture(params=["sqlite", "postgres"])
def password_database(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    engine = None
    schema_engine = None
    schema_name = None
    try:
        connect_args = {}
        if request.param == "postgres":
            url = os.environ.get("MAYA_TEST_POSTGRES_URL")
            if not url:
                pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
            if make_url(url).get_backend_name() != "postgresql":
                pytest.fail("MAYA_TEST_POSTGRES_URL must name a PostgreSQL test database")
            schema_engine = create_engine(url, poolclass=NullPool)
            candidate_schema = f"maya_hash_pool_{uuid4().hex}"
            with schema_engine.begin() as connection:
                connection.execute(CreateSchema(candidate_schema))
            schema_name = candidate_schema
            # Each connection, including the worker's, can see only this test's
            # schema. No public tables or another test's schema are changed.
            connect_args = {"options": f"-csearch_path={schema_name}"}
        else:
            url = f"sqlite:///{tmp_path / 'hash-pool.sqlite3'}"
        engine = create_engine(
            url,
            connect_args=connect_args,
            poolclass=QueuePool,
            pool_size=1,
            max_overflow=0,
            pool_timeout=0.05,
        )
        if schema_name is not None:
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT current_schema()")) == schema_name
        Base.metadata.create_all(
            engine, tables=[User.__table__, UserCredential.__table__, SessionRecord.__table__]
        )
        yield engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        if engine is not None:
            engine.dispose()
        if schema_engine is not None:
            try:
                if schema_name is not None:
                    with schema_engine.begin() as connection:
                        connection.execute(DropSchema(schema_name, cascade=True))
            finally:
                schema_engine.dispose()


def _seed(factory: sessionmaker[Session], *, source: str = "database") -> str:
    user_id = str(uuid4())
    now = datetime.now(UTC)
    with factory() as db:
        db.add(
            User(
                id=user_id,
                username="pool-test",
                display_name="Pool Test",
                status="active",
                created_at=now,
            )
        )
        db.flush()
        if source == "database":
            db.add(
                UserCredential(
                    user_id=user_id,
                    username="pool-test",
                    password_hash="old-hash",
                    created_at=now,
                    updated_at=now,
                )
            )
        for session_id in ("current", "other"):
            db.add(
                SessionRecord(
                    id_hash=session_id,
                    user_id=user_id,
                    csrf_hash="csrf-hash",
                    created_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
        db.commit()
    return user_id


@pytest.mark.parametrize(
    ("operation", "source"), [("change", "database"), ("change", "catalog"), ("reset", "database")]
)
def test_password_queue_and_hash_leave_connection_for_other_requests(
    password_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    source: str,
) -> None:
    engine, factory = password_database
    user_id = _seed(factory, source=source)
    settings = Settings(maya_env="test", session_secret="x" * 32, auth_hash_concurrency=1)
    hash_gate.reset_hash_gate_state()
    monkeypatch.setattr(hash_gate, "get_settings", lambda: settings)
    entered_queue = threading.Event()
    failures: list[BaseException] = []
    hash_phases: list[str] = []

    def check_connection(phase: str) -> None:
        assert engine.pool.checkedout() == 0
        with factory() as other:
            assert other.scalar(select(User.id).where(User.id == user_id)) == user_id
        hash_phases.append(phase)

    class Hasher:
        def verify(self, password: str, stored: str) -> bool:
            check_connection("verify")
            return password == "old-password" and stored == "old-hash"

        def hash(self, _password: str) -> str:
            check_connection("hash")
            return "new-hash"

    def catalog_verify(_settings: Settings, username: str, password: str) -> str | None:
        assert username == "pool-test"
        with hash_gate.hash_slot(settings):
            return user_id if Hasher().verify(password, "old-hash") else None

    monkeypatch.setattr(profile.PasswordHash, "recommended", Hasher)
    monkeypatch.setattr(registration, "_hasher", Hasher)
    monkeypatch.setattr(profile, "verify_password", catalog_verify)
    original_acquire = hash_gate._GATE.acquire

    def observe_acquire(**kwargs):
        if threading.current_thread() is worker:
            entered_queue.set()
        return original_acquire(**kwargs)

    monkeypatch.setattr(hash_gate._GATE, "acquire", observe_acquire)

    def update_password() -> None:
        try:
            with factory() as db:
                user = db.get(User, user_id)
                assert user is not None
                if operation == "change":
                    profile.change_password(
                        db,
                        settings,
                        user=user,
                        current_password="old-password",
                        new_password="new-password",
                        current_session_id_hash="current",
                    )
                else:
                    registration.reset_student_password(
                        db, target=user, new_password="new-password"
                    )
                db.commit()
        except BaseException as exc:
            failures.append(exc)

    worker = threading.Thread(target=update_password)
    try:
        with hash_gate.hash_slot(settings):
            worker.start()
            assert entered_queue.wait(5)
            assert worker.is_alive()
            check_connection("queue")
        worker.join(5)
        assert not worker.is_alive()
        assert failures == []
        assert hash_phases == (
            ["queue", "verify", "hash"] if operation == "change" else ["queue", "hash"]
        )
        with factory() as db:
            credential = db.get(UserCredential, user_id)
            assert credential is not None and credential.password_hash == "new-hash"
            sessions = {row.id_hash: row for row in db.scalars(select(SessionRecord)).all()}
            assert sessions["other"].revoked_at is not None
            assert (sessions["current"].revoked_at is None) == (operation == "change")
    finally:
        if worker.is_alive():
            worker.join(5)
        hash_gate.reset_hash_gate_state()


@pytest.mark.parametrize("source", ["database", "catalog"])
def test_password_change_rechecks_credential_after_releasing_connection(
    password_database: tuple[Engine, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    _engine, factory = password_database
    user_id = _seed(factory, source=source)
    settings = Settings(maya_env="test", session_secret="x" * 32)
    monkeypatch.setattr(profile, "_password_matches", lambda *_args: True)
    monkeypatch.setattr(profile, "verify_password", lambda *_args: user_id)

    def hash_while_another_change_commits(*_args) -> str:
        with factory() as other:
            credential = other.get(UserCredential, user_id)
            if credential is None:
                now = datetime.now(UTC)
                credential = UserCredential(
                    user_id=user_id,
                    username="pool-test",
                    password_hash="concurrent-hash",
                    created_at=now,
                    updated_at=now,
                )
                other.add(credential)
            else:
                credential.password_hash = "concurrent-hash"
            other.commit()
        return "stale-hash"

    monkeypatch.setattr(profile, "run_hash", hash_while_another_change_commits)
    with factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        with pytest.raises(PlatformError) as caught:
            profile.change_password(
                db,
                settings,
                user=user,
                current_password="old-password",
                new_password="new-password",
                current_session_id_hash="current",
            )
        assert caught.value.code == "password_incorrect"
        db.rollback()
    with factory() as db:
        credential = db.get(UserCredential, user_id)
        assert credential is not None and credential.password_hash == "concurrent-hash"
        assert all(row.revoked_at is None for row in db.scalars(select(SessionRecord)))
