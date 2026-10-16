"""Reject new LLM calls when the host is about to run out of RAM.

Classroom spikes used to freeze the 2 vCPU / 3.5 GB production host: in-flight
model calls keep holding memory for tens of seconds, and new ones pile on until
SSH and the gateway stop answering. This guard reads MemAvailable from
``/proc/meminfo`` (visible as host memory inside the production backend
containers) and refuses *new* LLM HTTP attempts when the free pool drops below
a configured floor. Requests already past the transport entry point keep
running; only admission of a fresh outbound call is blocked.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import PlatformError

MemAvailableReader = Callable[[], int | None]

_DEFAULT_MEMINFO = Path("/proc/meminfo")
# Tests and operators can replace the reader without patching Path.open.
_reader: MemAvailableReader | None = None


def set_mem_available_reader(reader: MemAvailableReader | None) -> None:
    """Override or clear the MemAvailable probe (tests only)."""

    global _reader
    _reader = reader


def read_mem_available_mb(meminfo_path: Path | str = _DEFAULT_MEMINFO) -> int | None:
    """Return MemAvailable in whole MiB, or None when the file is unreadable."""

    try:
        text = Path(meminfo_path).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("MemAvailable:"):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            kib = int(parts[1])
        except ValueError:
            return None
        if kib < 0:
            return None
        return kib // 1024
    return None


def _active_reader() -> MemAvailableReader:
    if _reader is not None:
        return _reader
    return read_mem_available_mb


def host_memory_pressure_error(
    *,
    available_mb: int,
    minimum_mb: int,
    retry_after_seconds: int,
) -> PlatformError:
    """Build the 503 clients should treat as a short, retryable pause."""

    return PlatformError(
        "host_memory_pressure",
        "The server is low on memory. Wait a moment and try again.",
        503,
        {
            "retryable": True,
            "retry_after_seconds": max(1, retry_after_seconds),
            "mem_available_mb": available_mb,
            "mem_minimum_mb": minimum_mb,
        },
    )


def ensure_memory_for_new_llm(settings: Settings | None = None) -> None:
    """Raise ``host_memory_pressure`` when MemAvailable is below the floor.

    A missing or unreadable ``/proc/meminfo`` fails open so a broken probe
    cannot take every model call offline. Setting the floor to 0 disables the
    guard (used in unit tests that never touch the host).
    """

    runtime = settings if settings is not None else get_settings()
    minimum = int(runtime.memory_guard_min_available_mb)
    if minimum <= 0:
        return
    available = _active_reader()()
    if available is None:
        return
    if available < minimum:
        raise host_memory_pressure_error(
            available_mb=available,
            minimum_mb=minimum,
            retry_after_seconds=int(runtime.memory_guard_retry_seconds),
        )


__all__ = [
    "ensure_memory_for_new_llm",
    "host_memory_pressure_error",
    "read_mem_available_mb",
    "set_mem_available_reader",
]
