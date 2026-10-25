"""Host 1-minute loadavg guard for new LLM / write / create admissions."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.host_load_guard import (
    read_load_avg_1m,
    reset_host_load_guard_state,
    set_load_avg_reader,
)

from tests.postgres_db import named_url


@pytest.fixture(autouse=True)
def _clear_load_reader() -> None:
    set_load_avg_reader(None)
    reset_host_load_guard_state()
    yield
    set_load_avg_reader(None)
    reset_host_load_guard_state()


def _settings(**overrides: object) -> Settings:
    base = {
        "maya_env": "test",
        "session_secret": "x" * 32,
        "demo_mode": True,
        "database_url": named_url("settings"),
        "data_root": "/tmp",
        "llm_provider": "mock",
        "embedding_provider": "mock",
        "tts_provider": "mock",
        "voice_provider": "mock",
        "report_provider": "mock",
        "host_load_reject_threshold": 6.0,
        "host_load_resume_threshold": 4.0,
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
