"""Argon2 concurrency cap (AUTH_HASH_CONCURRENCY, default 2 per process)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.core import adaptive_admission as aa
from app.core import hash_gate
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.models import Base, User
from app.modules.auth import registration
from app.modules.auth.models import UserCredential
from pwdlib import PasswordHash


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    hash_gate.reset_hash_gate_state()
    aa.reset_adaptive_admission_state()
    yield
    hash_gate.reset_hash_gate_state()
    aa.reset_adaptive_admission_state()


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]


def test_default_cap_is_two() -> None:
    # Memory protection, not a rate limit: ~64 MiB per in-flight Argon2, so the
    # default tracks the classroom host's CPU cores.
    assert Settings().auth_hash_concurrency == 2


def test_parallel_hashes_never_exceed_cap() -> None:
    settings = _settings(auth_hash_concurrency=3, adaptive_admission_wait_seconds=30)
    lock = threading.Lock()
    current = 0
    peak = 0

    def work() -> None:
        nonlocal current, peak
        with lock:
            current += 1
            peak = max(peak, current)
        time.sleep(0.02)
        with lock:
            current -= 1

    threads = [
        threading.Thread(target=hash_gate.run_hash, args=(work, settings)) for _ in range(12)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 3
    assert hash_gate.hash_gate_in_flight() == 0


def test_real_argon2_verifies_respect_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the hasher so real verify calls are observed while in flight."""

    real = PasswordHash.recommended()
    stored = real.hash("demo-password-123")
    lock = threading.Lock()
    current = 0
    peak = 0

    class _Observed:
        def verify(self, password: str, hash_value: str) -> bool:
            nonlocal current, peak
            with lock:
                current += 1
                peak = max(peak, current)
            try:
                return real.verify(password, hash_value)
            finally:
                with lock:
                    current -= 1

    monkeypatch.setattr(registration, "_hasher", lambda: _Observed())
    results: list[bool] = []

    def one() -> None:
        results.append(
            hash_gate.run_hash(lambda: registration._hasher().verify("demo-password-123", stored))
        )

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [True] * 8
    assert 1 <= peak <= 3


def test_wait_respects_shared_admission_deadline() -> None:
    settings = _settings(auth_hash_concurrency=1, adaptive_admission_wait_seconds=1)
    release = threading.Event()
    entered = threading.Event()

    def holder() -> None:
        with hash_gate.hash_slot(settings):
            entered.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    assert entered.wait(2)
    try:
        started = time.monotonic()
        # Inside an admission slot the gate waits only for what is left of
        # that request's single deadline (1 s here), then returns busy 503.
        with aa.adaptive_slot("login", settings):
            with pytest.raises(PlatformError) as excinfo:
                with hash_gate.hash_slot(settings):
                    pass
        elapsed = time.monotonic() - started
    finally:
        release.set()
        t.join()
    assert excinfo.value.code == "adaptive_admission_busy"
    assert excinfo.value.status_code == 503
    assert excinfo.value.details["reason"] == "hash_wait_timeout"
    assert elapsed < 3


def test_busy_is_not_swallowed_as_wrong_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_database_password must surface the 503, not report 'invalid'."""

    def busy(settings: Settings | None = None) -> Iterator[None]:
        raise hash_gate.auth_hash_busy_error(reason="wait_timeout", limit=3, retry_after_seconds=5)
        yield  # pragma: no cover

    from contextlib import contextmanager

    monkeypatch.setattr(registration, "hash_slot", contextmanager(busy))

    class _Row(tuple):  # mimics a (user_id, password_hash) result row
        pass

    class _Result:
        def first(self) -> _Row:
            return _Row(("u", "x"))

    class _Db:
        def execute(self, _stmt: object) -> _Result:
            return _Result()

        def rollback(self) -> None:
            pass

    with pytest.raises(PlatformError) as excinfo:
        registration.verify_database_password(_Db(), "someone", "pw")  # type: ignore[arg-type]
    assert excinfo.value.status_code == 503


def test_rollback_releases_connection_before_argon2_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pooled connection is checked in before any Argon2 work runs."""

    events: list[str] = []
    real = PasswordHash.recommended()
    stored_hash = real.hash("demo-password-123")

    class _Observed:
        def verify(self, password: str, hash_value: str) -> bool:
            events.append("verify")
            return real.verify(password, hash_value)

    monkeypatch.setattr(registration, "_hasher", lambda: _Observed())
    monkeypatch.setattr(
        registration, "lock_password_identity", lambda _db, _user_id: events.append("writer_lock")
    )

    class _Result:
        def first(self) -> tuple[str, str] | None:
            return ("user-id", stored_hash)

    class _Db:
        def execute(self, _stmt: object) -> _Result:
            return _Result()

        def scalar(self, _stmt: object) -> str:
            events.append("credential_recheck")
            return stored_hash

        def rollback(self) -> None:
            events.append("rollback")

    ok, user_id = registration.verify_database_password(_Db(), "someone", "demo-password-123")
    assert ok is True
    assert user_id == "user-id"
    # rollback must precede the first verify call, not merely happen somewhere.
    assert events == ["rollback", "verify", "writer_lock", "credential_recheck"]


def test_unknown_username_still_runs_dummy_argon2_after_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing credential row burns the same Argon2 work, after rollback."""

    verify_calls: list[str] = []
    real = PasswordHash.recommended()

    class _Observed:
        def verify(self, password: str, hash_value: str) -> bool:
            verify_calls.append(hash_value)
            return real.verify(password, hash_value)

    monkeypatch.setattr(registration, "_hasher", lambda: _Observed())
    monkeypatch.setattr(registration, "_DUMMY_HASH", real.hash("seeded-dummy"))

    rollbacks: list[bool] = []

    class _Result:
        def first(self) -> None:
            return None

    class _Db:
        def execute(self, _stmt: object) -> _Result:
            return _Result()

        def rollback(self) -> None:
            rollbacks.append(True)

    ok, user_id = registration.verify_database_password(_Db(), "nobody", "whatever")
    assert ok is False
    assert user_id is None
    assert rollbacks == [True]
    # Exactly one dummy verify ran, and the dummy hash was precomputed so no
    # Argon2 hash ran inside the gate either.
    assert len(verify_calls) == 1


def test_verify_runs_with_pool_connection_checked_out_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While Argon2 verify runs, the engine pool reports zero checked-out."""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import QueuePool

    engine = create_engine(f"sqlite:///{tmp_path / 'pool.sqlite3'}", poolclass=QueuePool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    password_hash = PasswordHash.recommended().hash("demo-password-123")
    with factory() as seed_session:
        seed_session.add(
            User(
                id="pool-user",
                username="pool-user",
                display_name="Pool User",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        seed_session.add(
            UserCredential(
                user_id="pool-user",
                username="pool-user",
                password_hash=password_hash,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        seed_session.commit()

    pool = engine.pool
    assert isinstance(pool, QueuePool)
    observed: list[int] = []
    real = PasswordHash.recommended()

    class _Observed:
        def verify(self, password: str, hash_value: str) -> bool:
            observed.append(int(pool.checkedout()))
            return real.verify(password, hash_value)

    monkeypatch.setattr(registration, "_hasher", lambda: _Observed())
    session = factory()
    ok, _user_id = registration.verify_database_password(session, "pool-user", "demo-password-123")
    session.close()
    engine.dispose()
    assert ok is True
    assert observed and observed[0] == 0


def test_zero_disables_cap() -> None:
    settings = _settings(auth_hash_concurrency=0)
    assert hash_gate.run_hash(lambda: 7, settings) == 7
