"""Reject new LLM calls when the host is about to run out of RAM.

Classroom spikes used to freeze the 2 vCPU / 3.5 GB production host: in-flight
model calls keep holding memory for tens of seconds, and new ones pile on until
SSH and the gateway stop answering. This guard reads MemAvailable from
``/proc/meminfo`` (visible as host memory inside the production backend
containers) and refuses *new* LLM HTTP attempts when the free pool drops below
a configured floor. Requests already past the transport entry point keep
running; only admission of a fresh outbound call is blocked.

Hysteresis keeps the host from flapping around the floor: once pressure is
latched, new calls stay rejected until MemAvailable climbs to a higher resume
threshold (default reject below 500 MiB, resume at 550 MiB).
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
# Process-local sticky flag: once MemAvailable dips below the reject floor,
# keep refusing until it recovers to the resume threshold.
_under_pressure: bool = False


def set_mem_available_reader(reader: MemAvailableReader | None) -> None:
    """Override or clear the MemAvailable probe (tests only)."""

    global _reader
    _reader = reader


def reset_memory_guard_state() -> None:
    """Clear the sticky pressure latch (tests only)."""

    global _under_pressure
    _under_pressure = False


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
    """Raise ``host_memory_pressure`` when host RAM is under the admit floor.

    Uses a process-local sticky pressure flag with optional hysteresis:

    * Not under pressure: reject (and latch) when ``available < min_mb``.
    * Under pressure: keep rejecting until ``available >= resume_mb``, then
      clear the latch and admit.
    * When ``resume_mb <= min_mb``, hysteresis is off (resume equals min).
    * Floor 0 disables the guard entirely.
    * A missing or unreadable ``/proc/meminfo`` fails open so a broken probe
      cannot take every model call offline.
    """

    global _under_pressure

    runtime = settings if settings is not None else get_settings()
    minimum = int(runtime.memory_guard_min_available_mb)
    if minimum <= 0:
        return
    resume = int(runtime.memory_guard_resume_available_mb)
    if resume <= minimum:
        resume = minimum
    available = _active_reader()()
    if available is None:
        return

    if not _under_pressure:
        if available < minimum:
            _under_pressure = True
            raise host_memory_pressure_error(
                available_mb=available,
                minimum_mb=minimum,
                retry_after_seconds=int(runtime.memory_guard_retry_seconds),
            )
        return

    if available >= resume:
        _under_pressure = False
        return

    raise host_memory_pressure_error(
        available_mb=available,
        minimum_mb=minimum,
        retry_after_seconds=int(runtime.memory_guard_retry_seconds),
    )


__all__ = [
    "ensure_memory_for_new_llm",
    "host_memory_pressure_error",
    "read_mem_available_mb",
    "reset_memory_guard_state",
    "set_mem_available_reader",
]
