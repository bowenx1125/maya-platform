"""Host MemAvailable guard for new LLM HTTP attempts."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.memory_guard import (
    read_mem_available_mb,
    reset_memory_guard_state,
    set_mem_available_reader,
)


@pytest.fixture(autouse=True)
def _clear_mem_reader() -> None:
    set_mem_available_reader(None)
    reset_memory_guard_state()
    yield
    set_mem_available_reader(None)
    reset_memory_guard_state()


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
        "memory_guard_resume_available_mb": 550,
        "host_load_reject_threshold": 0,
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
