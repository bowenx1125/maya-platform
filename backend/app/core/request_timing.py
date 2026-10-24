"""One structured timing line per HTTP request, for finding slow endpoints.

A collector lives in a ContextVar for the duration of one request. SQLAlchemy
cursor events add database time and query counts; provider transports (LLM,
embedding, TTS/voice) add their wall time. Sync handlers run in a threadpool
copy of the context and share the collector by reference, so their work is
counted. Background tasks started during the request also inherit it; once
the request line is written the collector is closed and ignores them.

The line (``"event":"request_timing"`` on ``maya.request_timing``) carries only
the method, the route template (``/api/v1/debates/{debate_id}``, never the
concrete path), status, timings, counts and the replica host name: no ids,
query strings, user data or provider payloads.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("maya.request_timing")

SLOW_REQUEST_MS = 1000.0
PROVIDER_KINDS = ("llm", "embedding", "tts", "voice")
HOST = socket.gethostname()[:64]


class RequestTiming:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.db_ms = 0.0
        self.db_queries = 0
        self.provider_ms: dict[str, float] = {}
        self.provider_calls = 0
        self.closed = False
        self._lock = threading.Lock()

    def add_query(self, ms: float) -> None:
        with self._lock:
            if not self.closed:
                self.db_ms += ms
                self.db_queries += 1

    def add_provider(self, kind: str, ms: float) -> None:
        with self._lock:
            if not self.closed:
                self.provider_ms[kind] = self.provider_ms.get(kind, 0.0) + ms
                self.provider_calls += 1

    def close(self, *, method: str, route: str, status: int, stream: bool) -> dict[str, Any]:
        total_ms = (time.perf_counter() - self.started) * 1000.0
        with self._lock:
            self.closed = True
            record: dict[str, Any] = {
                "event": "request_timing",
                "method": method,
                "route": route,
                "status": status,
                "ms": round(total_ms, 1),
                "db_ms": round(self.db_ms, 1),
                "db_queries": self.db_queries,
                "provider_ms": round(sum(self.provider_ms.values()), 1),
                "provider_calls": self.provider_calls,
                "host": HOST,
                "slow": total_ms >= SLOW_REQUEST_MS,
            }
            for kind, ms in self.provider_ms.items():
                record[f"{kind}_ms"] = round(ms, 1)
            if stream:
                # Streams (SSE, audio files) are timed to their headers; the
                # body keeps flowing after this line is written.
                record["stream"] = True
            return record


_CURRENT: ContextVar[RequestTiming | None] = ContextVar("maya_request_timing", default=None)


def current() -> RequestTiming | None:
    return _CURRENT.get()


def begin() -> tuple[RequestTiming, object]:
    timing = RequestTiming()
    return timing, _CURRENT.set(timing)


def finish(
    timing: RequestTiming,
    token: object,
    *,
    method: str,
    route: str,
    status: int,
    stream: bool,
    log: bool = True,
) -> dict[str, Any]:
    _CURRENT.reset(token)  # type: ignore[arg-type]
    record = timing.close(method=method, route=route, status=status, stream=stream)
    if log:
        log_record(record)
    return record


def log_record(record: dict[str, Any]) -> None:
    try:
        logger.info(json.dumps(record, separators=(",", ":")))
    except Exception:  # pragma: no cover - logging must never break a response
        pass


def route_template(scope: Mapping[str, Any]) -> str:
    """The matched route's template including its mount prefix, or "unmatched".

    An included router's route reports only its own template
    (``/debates/{debate_id}``); the prefix (``/api/v1``) is the matching
    number of leading segments of the real path, which carry no ids.
    """

    template = getattr(scope.get("route"), "path", None)
    if not isinstance(template, str) or not template:
        return "unmatched"
    path_parts = str(scope.get("path") or "").split("/")
    template_parts = template.split("/")
    prefix_length = len(path_parts) - len(template_parts)
    if prefix_length <= 0:
        return template
    return "/".join(path_parts[: prefix_length + 1]) + template


def add_provider_time(kind: str, ms: float) -> None:
    timing = _CURRENT.get()
    if timing is not None:
        timing.add_provider(kind if kind in PROVIDER_KINDS else "other", ms)


@contextmanager
def provider_call(kind: str) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        add_provider_time(kind, (time.perf_counter() - started) * 1000.0)


_QUERY_STARTED = "maya_request_timing_started"


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
    if _CURRENT.get() is not None:
        conn.info.setdefault(_QUERY_STARTED, []).append(time.perf_counter())


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
    timing = _CURRENT.get()
    if timing is None:
        return
    starts = conn.info.get(_QUERY_STARTED)
    if starts:
        timing.add_query((time.perf_counter() - starts.pop()) * 1000.0)


def _handle_error(exception_context):  # type: ignore[no-untyped-def]
    # A failed statement never reaches after_cursor_execute; drop its start so
    # the next query on this connection is not timed from the wrong moment.
    conn = exception_context.connection
    if conn is not None:
        starts = conn.info.get(_QUERY_STARTED)
        if starts:
            starts.pop()


_installed = False
_install_lock = threading.Lock()


def install_query_timing() -> None:
    """Listen on every Engine once; a query outside a request costs one lookup."""

    global _installed
    with _install_lock:
        if _installed:
            return
        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
        event.listen(Engine, "handle_error", _handle_error)
        _installed = True
