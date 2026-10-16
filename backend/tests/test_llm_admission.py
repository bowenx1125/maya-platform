"""LLM admission slot: acquire/release, queue, cap, disable, transport wiring."""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.llm_admission import llm_admission_slot, reset_llm_admission_state
from app.providers.llm_transport import HttpxLLMTransport


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    reset_llm_admission_state()
    yield
    reset_llm_admission_state()


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
        "llm_admission_limit": 12,
        "llm_admission_queue_max": 100,
        "llm_admission_wait_seconds": 180,
        "llm_admission_retry_seconds": 5,
        "memory_guard_min_available_mb": 0,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_slot_admits_under_limit() -> None:
    with llm_admission_slot(_settings(llm_admission_limit=2)):
        pass


def test_slot_disabled_when_limit_zero() -> None:
    with llm_admission_slot(_settings(llm_admission_limit=0)):
        pass


def test_slot_rejects_when_queue_full() -> None:
    settings = _settings(
        llm_admission_limit=1,
        llm_admission_queue_max=1,
        llm_admission_wait_seconds=5,
        llm_admission_retry_seconds=5,
    )
    release = threading.Event()
    entered = threading.Event()

    def hold() -> None:
        with llm_admission_slot(settings):
            entered.set()
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    assert entered.wait(timeout=2.0)

    waiting = threading.Event()

    def waiter() -> None:
        waiting.set()
        with llm_admission_slot(settings):
            pass

    thread = threading.Thread(target=waiter)
    thread.start()
    assert waiting.wait(timeout=2.0)
    time.sleep(0.05)

    with pytest.raises(PlatformError) as raised:
        with llm_admission_slot(settings):
            pass
    error = raised.value
    assert error.code == "llm_admission_busy"
    assert error.status_code == 503
    assert error.details["retryable"] is True
    assert error.details["reason"] == "queue_full"
    assert error.details["retry_after_seconds"] == 5

    release.set()
    holder.join(timeout=2.0)
    thread.join(timeout=2.0)


def test_waiter_proceeds_when_slot_frees() -> None:
    settings = _settings(
        llm_admission_limit=1,
        llm_admission_queue_max=4,
        llm_admission_wait_seconds=5,
    )
    release = threading.Event()
    got = threading.Event()

    def hold() -> None:
        with llm_admission_slot(settings):
            release.wait(timeout=5.0)

    holder = threading.Thread(target=hold)
    holder.start()
    time.sleep(0.05)

    def wait_slot() -> None:
        with llm_admission_slot(settings):
            got.set()

    waiter = threading.Thread(target=wait_slot)
    waiter.start()
    time.sleep(0.05)
    assert not got.is_set()
    release.set()
    waiter.join(timeout=2.0)
    holder.join(timeout=2.0)
    assert got.is_set()


def test_transport_holds_admission_around_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls = 0
    seen_in_flight: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        from app.core import llm_admission as mod

        seen_in_flight.append(mod._GATE.in_flight)  # noqa: SLF001
        return httpx.Response(200, json={"ok": True})

    # Force a tiny limit so we can observe the slot is held during HTTP.
    monkeypatch.setattr(
        "app.providers.llm_transport.llm_admission_slot",
        lambda settings=None: llm_admission_slot(
            _settings(llm_admission_limit=2, memory_guard_min_available_mb=0)
        ),
    )
    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_memory_for_new_llm",
        lambda settings=None: None,
    )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        HttpxLLMTransport(client).post(
            "https://example.invalid/v1/chat/completions",
            headers={"Authorization": "Bearer fixture"},
            json={"model": "qwen", "messages": []},
        )
    assert http_calls == 1
    assert seen_in_flight == [1]


def test_transport_rejects_before_http_when_admission_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"ok": True})

    def refuse():
        raise PlatformError(
            "llm_admission_busy",
            "busy",
            503,
            {"retryable": True, "retry_after_seconds": 5, "reason": "queue_full"},
        )

    class _Refuse:
        def __enter__(self):
            refuse()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_memory_for_new_llm",
        lambda settings=None: None,
    )
    monkeypatch.setattr(
        "app.providers.llm_transport.llm_admission_slot",
        lambda settings=None: _Refuse(),
    )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PlatformError) as raised:
            HttpxLLMTransport(client).post(
                "https://example.invalid/v1/chat/completions",
                headers={"Authorization": "Bearer fixture"},
                json={"model": "qwen", "messages": []},
            )
    assert raised.value.code == "llm_admission_busy"
    assert http_calls == 0
