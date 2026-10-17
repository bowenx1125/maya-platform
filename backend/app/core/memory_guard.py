"""Host MemAvailable probe for the unified pressure signal.

``/proc/meminfo`` is host memory inside the production backend containers.
The 500 / 550 MiB latch lives in ``adaptive_admission`` together with the
load threshold; under pressure new work queues until recovery instead of
being rejected with ``host_memory_pressure``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

MemAvailableReader = Callable[[], int | None]

_DEFAULT_MEMINFO = Path("/proc/meminfo")
# Tests and operators can replace the reader without patching Path.open.
_reader: MemAvailableReader | None = None


def set_mem_available_reader(reader: MemAvailableReader | None) -> None:
    """Override or clear the MemAvailable probe (tests only)."""

    global _reader
    _reader = reader


def reset_memory_guard_state() -> None:
    """Clear the unified pressure latch (tests only)."""

    from app.core.adaptive_admission import reset_adaptive_admission_state

    reset_adaptive_admission_state()


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


def active_reader() -> MemAvailableReader:
    if _reader is not None:
        return _reader
    return read_mem_available_mb


__all__ = [
    "read_mem_available_mb",
    "reset_memory_guard_state",
    "set_mem_available_reader",
]
