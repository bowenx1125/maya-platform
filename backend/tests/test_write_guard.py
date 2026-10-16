"""Write-path guard: acquire/release, queue, cap, disable."""

from __future__ import annotations

import threading
import time

import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.write_guard import reset_write_guard_state, write_guard_slot


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    reset_write_guard_state()
    yield
    reset_write_guard_state()


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "maya_env": "test",
        "session_secret": "x" * 32,
        "demo_mode": True,
        "database_url": "sqlite://",
        "data_root": "/tmp",
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "tts_provider": "mock",
        "voice_provider": "mock",
        "report_provider": "mock",
        "write_guard_limit": 12,
        "write_guard_queue_max": 100,
        "write_guard_wait_seconds": 180,
        "write_guard_retry_seconds": 5,
        "host_load_reject_threshold": 0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_write_slot_admits_under_limit() -> None:
    with write_guard_slot(_settings(write_guard_limit=2)):
        pass


def test_write_slot_disabled_when_limit_zero() -> None:
    with write_guard_slot(_settings(write_guard_limit=0)):
        pass


def test_write_slot_rejects_when_queue_full() -> None:
    settings = _settings(
        write_guard_limit=1,
        write_guard_queue_max=0,
        write_guard_wait_seconds=1,
        write_guard_retry_seconds=5,
    )
    release = threading.Event()
    entered = threading.Event()

    def hold() -> None:
        with write_guard_slot(_settings(write_guard_limit=1, write_guard_queue_max=4)):
            entered.set()
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    assert entered.wait(timeout=2.0)

    with pytest.raises(PlatformError) as raised:
        with write_guard_slot(settings):
            pass
    error = raised.value
    assert error.code == "write_pressure"
    assert error.status_code == 503
    assert error.details["retryable"] is True
    assert error.details["reason"] == "queue_full"

    release.set()
    holder.join(timeout=2.0)


def test_write_waiter_proceeds_when_slot_frees() -> None:
    settings = _settings(
        write_guard_limit=1,
        write_guard_queue_max=4,
        write_guard_wait_seconds=5,
    )
    release = threading.Event()
    got = threading.Event()

    def hold() -> None:
        with write_guard_slot(settings):
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    time.sleep(0.05)

    def wait_slot() -> None:
        with write_guard_slot(settings):
            got.set()

    waiter = threading.Thread(target=wait_slot)
    waiter.start()
    time.sleep(0.05)
    assert not got.is_set()
    release.set()
    waiter.join(timeout=2.0)
    holder.join(timeout=2.0)
    assert got.is_set()
