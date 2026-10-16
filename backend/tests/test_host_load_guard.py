"""Host 1-minute loadavg guard for new LLM / write / create admissions."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.host_load_guard import (
    ensure_host_load_ok,
    read_load_avg_1m,
    reset_host_load_guard_state,
    set_load_avg_reader,
)
from app.core.write_guard import reset_write_guard_state, write_guard_slot
from app.providers.llm_transport import HttpxLLMTransport


@pytest.fixture(autouse=True)
def _clear_load_reader() -> None:
    set_load_avg_reader(None)
    reset_host_load_guard_state()
    reset_write_guard_state()
    yield
    set_load_avg_reader(None)
    reset_host_load_guard_state()
    reset_write_guard_state()


def _settings(**overrides: object) -> Settings:
    base = {
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
        "host_load_reject_threshold": 6.0,
        "host_load_resume_threshold": 4.0,
        "host_load_retry_seconds": 15,
        "memory_guard_min_available_mb": 0,
        "llm_admission_limit": 0,
        "write_guard_limit": 12,
        "write_guard_queue_max": 100,
        "write_guard_wait_seconds": 180,
        "write_guard_retry_seconds": 5,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_read_load_avg_1m_parses_first_field(tmp_path: Path) -> None:
    loadavg = tmp_path / "loadavg"
    loadavg.write_text("1.23 0.45 0.12 1/234 5678\n", encoding="utf-8")
    assert read_load_avg_1m(loadavg) == pytest.approx(1.23)


def test_read_load_avg_1m_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_load_avg_1m(tmp_path / "no-such-loadavg") is None


def test_read_load_avg_1m_returns_none_on_garbage(tmp_path: Path) -> None:
    loadavg = tmp_path / "loadavg"
    loadavg.write_text("not-a-number rest\n", encoding="utf-8")
    assert read_load_avg_1m(loadavg) is None


def test_ensure_load_rejects_at_or_above_threshold() -> None:
    set_load_avg_reader(lambda: 6.0)
    with pytest.raises(PlatformError) as raised:
        ensure_host_load_ok(_settings(host_load_reject_threshold=6.0))
    error = raised.value
    assert error.code == "host_load_pressure"
    assert error.status_code == 503
    assert error.details["retryable"] is True
    assert error.details["retry_after_seconds"] == 15
    assert error.details["load_1m"] == 6.0
    assert error.details["load_reject_threshold"] == 6.0


def test_ensure_load_allows_below_threshold() -> None:
    set_load_avg_reader(lambda: 5.99)
    ensure_host_load_ok(_settings(host_load_reject_threshold=6.0))


def test_ensure_load_hysteresis_keeps_rejecting_between_resume_and_reject() -> None:
    settings = _settings(
        host_load_reject_threshold=6.0,
        host_load_resume_threshold=4.0,
    )
    set_load_avg_reader(lambda: 8.0)
    with pytest.raises(PlatformError):
        ensure_host_load_ok(settings)
    # Still above resume — sticky pressure must keep rejecting.
    set_load_avg_reader(lambda: 5.0)
    with pytest.raises(PlatformError) as raised:
        ensure_host_load_ok(settings)
    assert raised.value.code == "host_load_pressure"
    assert raised.value.details["load_1m"] == 5.0


def test_ensure_load_recovers_at_or_below_resume() -> None:
    settings = _settings(
        host_load_reject_threshold=6.0,
        host_load_resume_threshold=4.0,
    )
    set_load_avg_reader(lambda: 9.0)
    with pytest.raises(PlatformError):
        ensure_host_load_ok(settings)
    set_load_avg_reader(lambda: 4.01)
    with pytest.raises(PlatformError):
        ensure_host_load_ok(settings)
    set_load_avg_reader(lambda: 4.0)
    ensure_host_load_ok(settings)
    set_load_avg_reader(lambda: 2.0)
    ensure_host_load_ok(settings)


def test_ensure_load_between_resume_and_reject_admits_without_prior_pressure() -> None:
    settings = _settings(
        host_load_reject_threshold=6.0,
        host_load_resume_threshold=4.0,
    )
    set_load_avg_reader(lambda: 5.0)
    ensure_host_load_ok(settings)


def test_ensure_load_no_hysteresis_when_resume_ge_reject() -> None:
    settings = _settings(
        host_load_reject_threshold=6.0,
        host_load_resume_threshold=7.0,
    )
    set_load_avg_reader(lambda: 8.0)
    with pytest.raises(PlatformError):
        ensure_host_load_ok(settings)
    # resume clamped to reject → recovering to reject admits.
    set_load_avg_reader(lambda: 6.0)
    ensure_host_load_ok(settings)


def test_ensure_load_fails_open_when_unreadable() -> None:
    set_load_avg_reader(lambda: None)
    ensure_host_load_ok(_settings(host_load_reject_threshold=6.0))


def test_ensure_load_disabled_when_threshold_zero() -> None:
    set_load_avg_reader(lambda: 99.0)
    ensure_host_load_ok(_settings(host_load_reject_threshold=0))


def test_transport_checks_load_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"ok": True})

    def refuse() -> None:
        raise PlatformError(
            "host_load_pressure",
            "The server is under high load. Wait a moment and try again.",
            503,
            {"retryable": True, "retry_after_seconds": 15},
        )

    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_memory_for_new_llm",
        lambda settings=None: None,
    )
    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_host_load_ok",
        refuse,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PlatformError) as raised:
            HttpxLLMTransport(client).post(
                "https://example.invalid/v1/chat/completions",
                headers={"Authorization": "Bearer fixture"},
                json={"model": "qwen", "messages": []},
            )
    assert raised.value.code == "host_load_pressure"
    assert http_calls == 0


def test_write_guard_checks_load_at_entry() -> None:
    set_load_avg_reader(lambda: 10.0)
    with pytest.raises(PlatformError) as raised:
        with write_guard_slot(
            _settings(
                write_guard_limit=12,
                host_load_reject_threshold=6.0,
                host_load_resume_threshold=4.0,
            )
        ):
            pass
    assert raised.value.code == "host_load_pressure"
