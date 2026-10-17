"""Create-path admission slot: acquire/release, queue, cap, disable, load check."""

from __future__ import annotations

import threading
import time

import pytest
from app.core.config import Settings
from app.core.create_admission import create_admission_slot, reset_create_admission_state
from app.core.errors import PlatformError
from app.core.host_load_guard import reset_host_load_guard_state, set_load_avg_reader


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    reset_create_admission_state()
    reset_host_load_guard_state()
    set_load_avg_reader(None)
    yield
    reset_create_admission_state()
    reset_host_load_guard_state()
    set_load_avg_reader(None)


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
        "create_admission_limit": 4,
        "create_admission_queue_max": 100,
        "create_admission_wait_seconds": 180,
        "create_admission_retry_seconds": 5,
        "host_load_reject_threshold": 0,  # disable load guard in unit tests
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_slot_admits_under_limit() -> None:
    with create_admission_slot(_settings(create_admission_limit=2)):
        pass


def test_slot_disabled_when_limit_zero() -> None:
    with create_admission_slot(_settings(create_admission_limit=0)):
        pass


def test_slot_rejects_when_queue_full() -> None:
    settings = _settings(
        create_admission_limit=1,
        create_admission_queue_max=0,
        create_admission_wait_seconds=1,
        create_admission_retry_seconds=5,
    )
    release = threading.Event()
    entered = threading.Event()

    def hold() -> None:
        with create_admission_slot(
            _settings(create_admission_limit=1, create_admission_queue_max=4)
        ):
            entered.set()
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    assert entered.wait(timeout=2.0)

    with pytest.raises(PlatformError) as raised:
        with create_admission_slot(settings):
            pass
    error = raised.value
    assert error.code == "create_admission_busy"
    assert error.status_code == 503
    assert error.details["retryable"] is True
    assert error.details["reason"] == "queue_full"
    assert error.details["retry_after_seconds"] == 5

    release.set()
    holder.join(timeout=2.0)


def test_waiter_proceeds_when_slot_frees() -> None:
    settings = _settings(
        create_admission_limit=1,
        create_admission_queue_max=4,
        create_admission_wait_seconds=5,
    )
    release = threading.Event()
    got = threading.Event()

    def hold() -> None:
        with create_admission_slot(settings):
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    time.sleep(0.05)

    def wait_slot() -> None:
        with create_admission_slot(settings):
            got.set()

    waiter = threading.Thread(target=wait_slot)
    waiter.start()
    time.sleep(0.05)
    assert not got.is_set()
    release.set()
    waiter.join(timeout=2.0)
    holder.join(timeout=2.0)
    assert got.is_set()


def test_host_load_pressure_suspends_instead_of_rejecting() -> None:
    # #96 no longer rejects directly: the unified queue holds the create and
    # only its wait budget expiring yields a retryable 503.
    from app.core.adaptive_admission import reset_adaptive_admission_state

    reset_adaptive_admission_state()
    set_load_avg_reader(lambda: 9.0)
    try:
        with pytest.raises(PlatformError) as raised:
            with create_admission_slot(
                _settings(
                    create_admission_limit=4,
                    adaptive_admission_wait_seconds=1,
                    host_load_reject_threshold=6.0,
                    host_load_resume_threshold=4.0,
                )
            ):
                pass
    finally:
        set_load_avg_reader(None)
        reset_adaptive_admission_state()
    assert raised.value.code == "adaptive_admission_busy"
    assert raised.value.status_code == 503
    assert raised.value.details["reason"] == "wait_timeout"


def test_create_admission_default_wait_aligns_with_unified_deadline() -> None:
    field = Settings.model_fields["create_admission_wait_seconds"]
    assert field.default == 180
