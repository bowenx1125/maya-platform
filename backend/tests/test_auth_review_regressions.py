"""Auth regressions observed during the performance review."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.models import Base, SessionRecord, User
from app.modules.auth import profile, registration
from app.modules.auth import router as auth_router
from app.modules.auth.models import UserCredential
from app.modules.auth.router import _login_admitted
from app.modules.auth.schemas import LoginRequest
from fastapi import Request, Response
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker


def test_password_reset_during_login_verification_prevents_stale_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'reset-race.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(maya_env="test", session_secret="x" * 32)
    user_id = str(uuid4())
    now = datetime.now(UTC)
    with factory() as seed:
        seed.add(
            User(
                id=user_id,
                username="reset-user",
                display_name="Reset User",
                status="active",
                created_at=now,
            )
        )
        seed.add(
            UserCredential(
                user_id=user_id,
                username="reset-user",
                password_hash="old-hash",
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()

    class Hasher:
        def verify(self, password: str, hash_value: str) -> bool:
            # The login already read the old hash; a teacher reset commits
            # while this request is queued or doing the expensive verify.
            with factory() as reset:
                credential = reset.get(UserCredential, user_id)
                assert credential is not None
                credential.password_hash = "new-hash"
                credential.updated_at = datetime.now(UTC)
                reset.commit()
            return password == "old-password" and hash_value == "old-hash"

    monkeypatch.setattr(registration, "_hasher", Hasher)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    try:
        with factory() as db:
            with pytest.raises(PlatformError) as caught:
                _login_admitted(
                    LoginRequest(username="reset-user", password="old-password"),
                    request,
                    Response(),
                    db,
                    settings,
                )
            assert caught.value.status_code == 401
        with factory() as db:
            assert db.scalar(select(SessionRecord)) is None
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("operation", "source"), [("reset", "database"), ("change", "database"), ("change", "catalog")]
)
def test_password_update_after_login_lock_revokes_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, source: str
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'login-first.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(maya_env="test", session_secret="x" * 32)
    user_id = str(uuid4())
    now = datetime.now(UTC)
    with factory() as seed:
        seed.add(
            User(
                id=user_id,
                username="reset-user",
                display_name="Reset User",
                status="active",
                created_at=now,
            )
        )
        if source == "database":
            seed.add(
                UserCredential(
                    user_id=user_id,
                    username="reset-user",
                    password_hash="old-hash",
                    created_at=now,
                    updated_at=now,
                )
            )
        seed.commit()

    class Hasher:
        def verify(self, password: str, hash_value: str) -> bool:
            return password == "old-password" and hash_value == "old-hash"

        def hash(self, password: str) -> str:
            return "new-hash"

    monkeypatch.setattr(registration, "_hasher", Hasher)
    monkeypatch.setattr(registration, "_DUMMY_HASH", "dummy-hash")
    monkeypatch.setattr(auth_router, "verify_password", lambda *_args: user_id)
    monkeypatch.setattr(profile, "verify_password", lambda *_args: user_id)
    monkeypatch.setattr(profile, "_password_matches", lambda _hash, _password: True)
    monkeypatch.setattr(profile, "run_hash", lambda _fn, _settings: "new-hash")
    reset_write_started = threading.Event()
    reset_finished = threading.Event()
    failures: list[BaseException] = []

    @event.listens_for(engine, "before_cursor_execute")
    def observe_update(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement == "BEGIN IMMEDIATE" and threading.current_thread() is worker:
            reset_write_started.set()

    def update_password() -> None:
        try:
            with factory() as db:
                user = db.get(User, user_id)
                assert user is not None
                if operation == "reset":
                    registration.reset_student_password(
                        db, target=user, new_password="new-password"
                    )
                else:
                    profile.change_password(
                        db,
                        settings,
                        user=user,
                        current_password="old-password",
                        new_password="new-password",
                        current_session_id_hash="existing-session",
                    )
                db.commit()
        except BaseException as exc:
            failures.append(exc)
        finally:
            reset_finished.set()

    worker = threading.Thread(target=update_password)
    original_create = auth_router.create_rotated_session

    def create_while_reset_waits(*args, **kwargs):
        worker.start()
        assert reset_write_started.wait(5)
        assert not reset_finished.is_set()
        return original_create(*args, **kwargs)

    monkeypatch.setattr(auth_router, "create_rotated_session", create_while_reset_waits)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    try:
        with factory() as db:
            _login_admitted(
                LoginRequest(username="reset-user", password="old-password"),
                request,
                Response(),
                db,
                settings,
            )
        worker.join(10)
        assert not worker.is_alive()
        assert failures == []
        with factory() as db:
            sessions = db.scalars(select(SessionRecord)).all()
            assert len(sessions) == 1
            assert sessions[0].revoked_at is not None
    finally:
        if worker.is_alive():
            worker.join(10)
        engine.dispose()


def test_first_catalog_password_change_during_login_rejects_catalog_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-change.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    settings = Settings(maya_env="test", session_secret="x" * 32)
    user_id = str(uuid4())
    with factory() as seed:
        seed.add(
            User(
                id=user_id,
                username="catalog-user",
                display_name="Catalog User",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        seed.commit()

    monkeypatch.setattr(registration, "_DUMMY_HASH", "dummy-hash")
    monkeypatch.setattr(profile, "verify_password", lambda *_args: user_id)
    monkeypatch.setattr(profile, "run_hash", lambda *_args: "new-hash")

    class Hasher:
        def verify(self, *_args) -> bool:
            return False

    monkeypatch.setattr(registration, "_hasher", Hasher)

    def catalog_verify(*_args):
        with factory() as db:
            user = db.get(User, user_id)
            assert user is not None
            profile.change_password(
                db,
                settings,
                user=user,
                current_password="catalog-password",
                new_password="new-password",
                current_session_id_hash="existing-session",
            )
            db.commit()
        return user_id

    monkeypatch.setattr(auth_router, "verify_password", catalog_verify)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/login",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    try:
        with factory() as db:
            with pytest.raises(PlatformError) as caught:
                _login_admitted(
                    LoginRequest(username="catalog-user", password="catalog-password"),
                    request,
                    Response(),
                    db,
                    settings,
                )
            assert caught.value.status_code == 401
        with factory() as db:
            assert db.scalar(select(SessionRecord)) is None
    finally:
        engine.dispose()
