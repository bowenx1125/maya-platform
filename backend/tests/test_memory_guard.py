"""Host MemAvailable guard for new LLM HTTP attempts."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.core.config import Settings
from app.core.errors import PlatformError
from app.core.memory_guard import (
    ensure_memory_for_new_llm,
    read_mem_available_mb,
    set_mem_available_reader,
)
from app.providers.llm_transport import HttpxLLMTransport


@pytest.fixture(autouse=True)
def _clear_mem_reader() -> None:
    set_mem_available_reader(None)
    yield
    set_mem_available_reader(None)


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
        "memory_guard_min_available_mb": 500,
        "memory_guard_retry_seconds": 15,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_read_mem_available_mb_parses_kib_to_mib(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:       16386368 kB\n"
        "MemFree:          176132 kB\n"
        "MemAvailable:    1048576 kB\n"
        "Buffers:          848252 kB\n",
        encoding="utf-8",
    )
    assert read_mem_available_mb(meminfo) == 1024


def test_read_mem_available_mb_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_mem_available_mb(tmp_path / "no-such-meminfo") is None


def test_read_mem_available_mb_returns_none_without_line(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1024 kB\n", encoding="utf-8")
    assert read_mem_available_mb(meminfo) is None


def test_ensure_memory_rejects_below_floor() -> None:
    set_mem_available_reader(lambda: 499)
    with pytest.raises(PlatformError) as raised:
        ensure_memory_for_new_llm(_settings(memory_guard_min_available_mb=500))
    error = raised.value
    assert error.code == "host_memory_pressure"
    assert error.status_code == 503
    assert error.details["retryable"] is True
    assert error.details["retry_after_seconds"] == 15
    assert error.details["mem_available_mb"] == 499
    assert error.details["mem_minimum_mb"] == 500


def test_ensure_memory_allows_at_or_above_floor() -> None:
    set_mem_available_reader(lambda: 500)
    ensure_memory_for_new_llm(_settings(memory_guard_min_available_mb=500))
    set_mem_available_reader(lambda: 501)
    ensure_memory_for_new_llm(_settings(memory_guard_min_available_mb=500))


def test_ensure_memory_fails_open_when_unreadable() -> None:
    set_mem_available_reader(lambda: None)
    ensure_memory_for_new_llm(_settings(memory_guard_min_available_mb=500))


def test_ensure_memory_disabled_when_floor_zero() -> None:
    set_mem_available_reader(lambda: 0)
    ensure_memory_for_new_llm(_settings(memory_guard_min_available_mb=0))


def test_transport_checks_memory_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"ok": True})

    def refuse() -> None:
        raise PlatformError(
            "host_memory_pressure",
            "The server is low on memory. Wait a moment and try again.",
            503,
            {"retryable": True, "retry_after_seconds": 15},
        )

    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_memory_for_new_llm",
        refuse,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PlatformError) as raised:
            HttpxLLMTransport(client).post(
                "https://example.invalid/v1/chat/completions",
                headers={"Authorization": "Bearer fixture"},
                json={"model": "qwen", "messages": []},
            )
    assert raised.value.code == "host_memory_pressure"
    assert http_calls == 0


def test_transport_post_bytes_also_checks_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    http_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal http_calls
        http_calls += 1
        return httpx.Response(200, json={"ok": True})

    def refuse() -> None:
        raise PlatformError(
            "host_memory_pressure",
            "The server is low on memory. Wait a moment and try again.",
            503,
            {"retryable": True, "retry_after_seconds": 15},
        )

    monkeypatch.setattr(
        "app.providers.llm_transport.ensure_memory_for_new_llm",
        refuse,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PlatformError) as raised:
            HttpxLLMTransport(client).post_bytes(
                "https://example.invalid/v1/chat/completions",
                headers={"Authorization": "Bearer fixture"},
                content=b'{"model":"qwen"}',
            )
    assert raised.value.code == "host_memory_pressure"
    assert http_calls == 0
