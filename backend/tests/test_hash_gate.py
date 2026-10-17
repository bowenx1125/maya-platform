"""Argon2 concurrency cap (AUTH_HASH_CONCURRENCY, default 3 per process)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from app.core import adaptive_admission as aa
from app.core import hash_gate
from app.core.config import Settings
from app.core.errors import PlatformError
from app.modules.auth import registration
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


def test_default_cap_is_three() -> None:
    assert Settings().auth_hash_concurrency == 3


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

    class _Credential:
        password_hash = "x"
        user_id = "u"

    class _Db:
        def scalar(self, _stmt: object) -> _Credential:
            return _Credential()

    with pytest.raises(PlatformError) as excinfo:
        registration.verify_database_password(_Db(), "someone", "pw")  # type: ignore[arg-type]
    assert excinfo.value.status_code == 503


def test_zero_disables_cap() -> None:
    settings = _settings(auth_hash_concurrency=0)
    assert hash_gate.run_hash(lambda: 7, settings) == 7
