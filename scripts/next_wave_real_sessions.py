"""Run the frozen Next Wave classroom sessions through the deployed HTTP API.

The default command is a read-only plan.  ``--execute-real`` is an explicit
operator boundary and requires all identities and Agent IDs on the command
line.  A real run uses the public HTTP routes and the teacher playback
WebSocket; it never falls back to a fixture, Mock answer, or a direct database
write.  The resulting report contains only safe IDs, counts, statuses and
latencies.  Provider attempt details and browser/3D/TTS evidence are reported
as unavailable unless a reviewed public evidence route exposes them.

This runner is intentionally a transport harness rather than a second Maya
runtime.  Knowledge import, snapshot embedding, turn generation, audio
synthesis and Report generation remain owned by the deployed application.
The harness only checks their public lifecycle and refuses to call a manual
retry route during the normal suite.  ``acceptance_unknown`` is terminal for
the run and stops subsequent cases.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlsplit, urlunsplit
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tests.fixtures.next_wave_rag.harness import (  # noqa: E402
    FixtureBundle,
    FixtureValidationError,
    SessionSpec,
    load_fixture_bundle,
)

RUN_SCHEMA_VERSION = "next_wave_real_sessions_v1"
UNAVAILABLE = "unavailable"
PREVIEW_TURN_TIMEOUT_SECONDS = 180.0
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,79}$")
_TOKEN = re.compile(r"^v1\.[A-Za-z0-9_-]{64}\.[A-Za-z0-9_-]{43}$")


class RunnerFailure(RuntimeError):
    """A safe, classification-only failure from one transport stage."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        safe = code if _SAFE_CODE.fullmatch(code) else "runner_failure"
        super().__init__(safe)
        self.code = safe
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class WireResponse:
    """Parsed HTTP response without retaining raw response bytes."""

    status_code: int
    data: object | None
    headers: Mapping[str, str]
    byte_count: int | None = None


@dataclass(frozen=True, slots=True)
class PreviewPollResult:
    """Final Preview detail plus safe timing/progress evidence."""

    detail: dict[str, object]
    audit: dict[str, object]


class EventSocket(Protocol):
    def send(self, data: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


class SessionTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        idempotency_key: str | None = None,
        csrf: bool = True,
        raw: bool = False,
    ) -> WireResponse: ...

    def open_events(self, path: str) -> EventSocket: ...

    def close(self) -> None: ...


def _safe_error_code(value: object, default: str = "http_error") -> str:
    if isinstance(value, Mapping):
        for key in ("code", "safe_error_code", "error_code"):
            candidate = value.get(key)
            if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate):
                return candidate
    return default


def _contains_acceptance_unknown(value: object, *, depth: int = 0) -> bool:
    """Inspect only reviewed safe status fields, never arbitrary raw text."""

    if depth > 4:
        return False
    if isinstance(value, Mapping):
        for key in (
            "code",
            "safe_error_code",
            "error_code",
            "status_code",
            "state",
            "status",
        ):
            if value.get(key) == "acceptance_unknown":
                return True
        for key in (
            "stall",
            "preview",
            "playback",
            "report",
            "insight",
            "public_turns",
            "preview_turns",
            "turns",
        ):
            if _contains_acceptance_unknown(value.get(key), depth=depth + 1):
                return True
    elif isinstance(value, list):
        return any(
            _contains_acceptance_unknown(item, depth=depth + 1) for item in value
        )
    return False


class HttpTransport:
    """Small authenticated HTTP + WebSocket transport for the live runner."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query:
            raise RunnerFailure("base_url_invalid")
        self._base_url = base_url.rstrip("/")
        self._origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        self._timeout = timeout_seconds
        try:
            import httpx
        except ImportError:
            raise RunnerFailure("http_transport_unavailable") from None
        self._client: Any = httpx.Client(
            base_url=self._base_url, timeout=timeout_seconds, follow_redirects=False
        )
        self._csrf_token: str | None = None

    def quick_login(self, user_id: str) -> Mapping[str, object]:
        response = self.request(
            "POST",
            "/api/v1/auth/quick-login",
            payload={"user_id": user_id},
            csrf=False,
        )
        data = _mapping(response.data, "quick_login_response")
        csrf = data.get("csrf_token")
        if not isinstance(csrf, str) or len(csrf) < 32:
            raise RunnerFailure("auth_session_invalid")
        self._csrf_token = csrf
        user = _mapping(data.get("user"), "auth_user")
        if not isinstance(user.get("id"), str) or user["id"] != user_id:
            raise RunnerFailure("auth_identity_mismatch")
        return data

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        idempotency_key: str | None = None,
        csrf: bool = True,
        raw: bool = False,
    ) -> WireResponse:
        return self._request(
            method,
            path,
            payload=payload,
            idempotency_key=idempotency_key,
            csrf=csrf,
            raw=raw,
        )

    def request_multipart(
        self,
        method: str,
        path: str,
        *,
        fields: Mapping[str, str],
        file_name: str,
        file_content: bytes,
        content_type: str,
        idempotency_key: str | None = None,
        csrf: bool = True,
    ) -> WireResponse:
        return self._request(
            method,
            path,
            idempotency_key=idempotency_key,
            csrf=csrf,
            multipart={"file": (file_name, file_content, content_type)},
            fields=fields,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        idempotency_key: str | None = None,
        csrf: bool = True,
        raw: bool = False,
        multipart: Mapping[str, object] | None = None,
        fields: Mapping[str, str] | None = None,
    ) -> WireResponse:
        if not path.startswith("/") or path.startswith("//"):
            raise RunnerFailure("relative_path_required")
        headers = {"Accept": "application/json", "Origin": self._origin}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            if len(idempotency_key) < 16:
                raise RunnerFailure("idempotency_key_invalid")
            headers["Idempotency-Key"] = idempotency_key
        if csrf and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            if self._csrf_token is None:
                raise RunnerFailure("csrf_token_missing")
            headers["X-CSRF-Token"] = self._csrf_token
        try:
            response = self._client.request(
                method,
                path,
                headers=headers,
                **(
                    {"files": multipart, "data": fields}
                    if multipart is not None
                    else {"json": payload}
                ),
            )
        except Exception as exc:
            del exc
            raise RunnerFailure("transport_unavailable") from None
        if raw:
            if response.status_code >= 400:
                try:
                    body: object = response.json()
                except (ValueError, json.JSONDecodeError):
                    body = None
                code = _safe_error_code(body, "http_error")
                if code == "acceptance_unknown":
                    raise RunnerFailure(code, status_code=response.status_code)
                raise RunnerFailure(code, status_code=response.status_code)
            return WireResponse(
                response.status_code,
                None,
                dict(response.headers),
                len(response.content),
            )
        try:
            data = response.json() if response.content else None
        except (ValueError, json.JSONDecodeError):
            data = None
        if response.status_code >= 400:
            code = _safe_error_code(data)
            raise RunnerFailure(code, status_code=response.status_code)
        if _contains_acceptance_unknown(data):
            raise RunnerFailure("acceptance_unknown", status_code=response.status_code)
        return WireResponse(response.status_code, data, dict(response.headers))

    def open_events(self, path: str) -> EventSocket:
        if not path.startswith("/"):
            raise RunnerFailure("relative_path_required")
        parsed = urlsplit(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        ws_url = urlunsplit((scheme, parsed.netloc, path, "", ""))
        cookie_header = "; ".join(
            f"{key}={value}" for key, value in self._client.cookies.items()
        )
        headers = {"Cookie": cookie_header} if cookie_header else None
        try:
            from websockets.sync.client import connect

            return cast(
                EventSocket,
                connect(
                    ws_url,
                    origin=cast(Any, self._origin),
                    additional_headers=headers,
                    open_timeout=self._timeout,
                ),
            )
        except Exception as exc:
            del exc
            raise RunnerFailure("websocket_unavailable") from None

    def close(self) -> None:
        self._client.close()


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    course_id: str
    teacher_user_id: str
    student_user_id: str
    agent_ids: tuple[str, ...]
    expected_version_ids: tuple[str, ...] = ()
    timeout_seconds: float = 180.0
    poll_interval_seconds: float = 1.0
    group_id: str | None = None
    corpus_path: Path | None = None


def _mapping(value: object, code: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise RunnerFailure(code)
    result = dict(cast(Mapping[str, object], value))
    if _contains_acceptance_unknown(result):
        raise RunnerFailure("acceptance_unknown")
    return result


def _int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunnerFailure(code)
    return value


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunnerFailure(code)
    return value


def _uuid(value: object, code: str) -> str:
    text = _text(value, code)
    try:
        return str(UUID(text))
    except (ValueError, AttributeError):
        raise RunnerFailure(code) from None


def _idempotency(run_id: str, session_id: str, stage: str) -> str:
    """Create a fresh mutation receipt for every state-changing request."""

    return f"nw-{run_id[:12]}-{session_id[:30]}-{stage}-{uuid4().hex[:8]}"


def _topic(language: str) -> str:
    return (
        "How should a classroom balance memory and change?"
        if language == "en"
        else "课堂应如何平衡记忆与变化？"
    )


def _barrage_text(language: str, round_no: int) -> str:
    return (
        f"Which source-supported reason should the class examine in round {round_no}?"
        if language == "en"
        else f"课堂应在第{round_no}轮依据哪一条来源理由继续讨论？"
    )


def _safe_media_path(value: object, debate_id: str, turn_id: str) -> str:
    path = _text(value, "media_url_invalid")
    parsed = urlsplit(path)
    prefix = f"/api/v1/debates/{debate_id}/audio/{turn_id}"
    if parsed.scheme or parsed.netloc or parsed.path != prefix:
        raise RunnerFailure("media_url_invalid")
    ticket = parse_qs(parsed.query).get("media_ticket", [])
    if len(ticket) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket[0]):
        raise RunnerFailure("media_url_invalid")
    return path


def _event_mapping(value: object) -> dict[str, object]:
    data = _mapping(value, "websocket_message_invalid")
    if _contains_acceptance_unknown(data):
        raise RunnerFailure("acceptance_unknown")
    if data.get("message_type") == "command.rejected":
        code = data.get("code")
        safe = (
            code
            if isinstance(code, str) and _SAFE_CODE.fullmatch(code)
            else "command_rejected"
        )
        raise RunnerFailure(safe)
    return data


class PlaybackController:
    """Drive the exact controller/media/ack protocol used by the Bench."""

    def __init__(
        self,
        transport: SessionTransport,
        socket: EventSocket,
        *,
        debate_id: str,
        timeout_seconds: float,
        poll_interval_seconds: float = 1.0,
        require_grades: bool = False,
    ) -> None:
        self.transport = transport
        self.socket = socket
        self.debate_id = debate_id
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)
        self.require_grades = require_grades
        self.audio_fetches = 0
        self.audio_bytes = 0
        self.turn_latencies_ms: list[int] = []
        self.started_events: list[dict[str, object]] = []

    def _recv(self, timeout_seconds: float | None = None) -> dict[str, object]:
        try:
            timeout = (
                self.timeout_seconds if timeout_seconds is None else timeout_seconds
            )
            raw = self.socket.recv(timeout)
        except TypeError:
            raw = self.socket.recv()
        except TimeoutError:
            raise RunnerFailure("websocket_receive_timeout") from None
        except Exception as exc:
            del exc
            raise RunnerFailure("websocket_receive_failed") from None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw)
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
            raise RunnerFailure("websocket_message_invalid") from None
        return _event_mapping(value)

    def _until(
        self,
        field: str,
        expected: str,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        deadline = time.monotonic() + (
            self.timeout_seconds
            if timeout_seconds is None
            else max(0.0, timeout_seconds)
        )
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                message = self._recv(min(self.timeout_seconds, remaining))
            except RunnerFailure as exc:
                if exc.code == "websocket_receive_timeout":
                    continue
                raise
            if message.get(field) == expected:
                return message
        raise RunnerFailure("websocket_stage_timeout")

    def _send(self, body: dict[str, object]) -> None:
        try:
            self.socket.send(json.dumps(body, separators=(",", ":")))
        except Exception as exc:
            del exc
            raise RunnerFailure("websocket_send_failed") from None

    def _command(
        self, command_type: str, expected_control_version: int, **fields: object
    ) -> None:
        self._send(
            {
                "command_id": str(uuid4()),
                "command_type": command_type,
                "command_version": 1,
                "debate_id": self.debate_id,
                "expected_control_version": expected_control_version,
                **fields,
            }
        )

    def acquire(self, expected_control_version: int) -> tuple[str, int]:
        snapshot = self._until("event_type", "snapshot")
        payload = _mapping(snapshot.get("payload"), "snapshot_invalid")
        playback = _mapping(payload.get("playback"), "snapshot_playback_invalid")
        snapshot_version = _int(
            playback.get("control_version"), "control_version_invalid"
        )
        if snapshot_version != expected_control_version:
            expected_control_version = snapshot_version
        self._command(
            "playback.controller.acquire",
            expected_control_version,
        )
        acquired = self._until("message_type", "controller.acquired")
        epoch = _uuid(acquired.get("controller_epoch"), "controller_epoch_invalid")
        version = _int(acquired.get("control_version"), "control_version_invalid")
        return epoch, version

    def play_one(
        self,
        *,
        turn_id: str,
        expected_control_version: int,
        epoch: str,
        action: str,
        after_started: Callable[[dict[str, object]], None] | None = None,
    ) -> tuple[dict[str, object], dict[str, object], int]:
        turn_started = time.monotonic()
        self._command(
            "playback.media.prepare",
            expected_control_version,
            controller_epoch=epoch,
            turn_id=turn_id,
            playback_action=action,
        )
        prepared = self._until("message_type", "media.prepared")
        media_path = _safe_media_path(
            prepared.get("media_url"), self.debate_id, turn_id
        )
        audio = self.transport.request("GET", media_path, raw=True, csrf=False)
        if (
            audio.status_code not in {200, 206}
            or audio.byte_count is None
            or audio.byte_count <= 0
        ):
            raise RunnerFailure("audio_unavailable", status_code=audio.status_code)
        self.audio_fetches += 1
        self.audio_bytes += audio.byte_count

        self._command(
            "playback.started_ack",
            expected_control_version,
            controller_epoch=epoch,
            turn_id=turn_id,
            playback_action=action,
        )
        started = self._until("event_type", "playback.started")
        started_payload = _mapping(started.get("payload"), "playback_started_invalid")
        _text(started_payload.get("speech"), "public_speech_missing")
        if not isinstance(started_payload.get("sources"), list):
            raise RunnerFailure("public_sources_invalid")
        segment = _mapping(
            started_payload.get("segment_turn"), "segment_payload_missing"
        )
        if segment.get("schema_version") != "segment_turn_v2":
            raise RunnerFailure("segment_schema_invalid")
        segments = segment.get("segments")
        if not isinstance(segments, list) or not segments:
            raise RunnerFailure("segment_list_invalid")
        for item in segments:
            row = _mapping(item, "segment_invalid")
            _text(row.get("text"), "segment_text_missing")
            source_ids = row.get("source_ids")
            if not isinstance(source_ids, list):
                raise RunnerFailure("segment_sources_invalid")
            if self.require_grades:
                if any(
                    not isinstance(source_id, str) or not source_id.strip()
                    for source_id in source_ids
                ):
                    raise RunnerFailure("segment_sources_invalid")
                support_mode = row.get("support_mode")
                if support_mode not in {"direct", "contextual", "no_match"}:
                    raise RunnerFailure("segment_grade_missing")
                if support_mode in {"direct", "contextual"} and not source_ids:
                    raise RunnerFailure("segment_grade_source_mismatch")
                if support_mode == "no_match" and source_ids:
                    raise RunnerFailure("segment_grade_source_mismatch")
            reply = row.get("reply_to")
            if reply is not None and (
                not isinstance(reply, str) or not re.fullmatch(r"B[1-9][0-9]*", reply)
            ):
                raise RunnerFailure("segment_reply_binding_invalid")
        self.started_events.append(started)
        if after_started is not None:
            after_started(started)

        self._command(
            "playback.ended_ack",
            expected_control_version,
            controller_epoch=epoch,
            turn_id=turn_id,
        )
        completed = self._until("event_type", "playback.completed")
        completed_payload = _mapping(
            completed.get("payload"), "playback_completed_invalid"
        )
        next_version = _int(
            completed_payload.get("control_version"), "control_version_invalid"
        )
        self.turn_latencies_ms.append(
            max(0, int((time.monotonic() - turn_started) * 1000))
        )
        return started, completed, next_version


def _stage(
    name: str, started: float, *, status: str = "passed", code: str | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "stage": name,
        "status": status,
        "wall_ms": max(0, int((time.monotonic() - started) * 1000)),
        "first_attempt": UNAVAILABLE,
        "repair_count": UNAVAILABLE,
        "evidence": "provider_attempt_api_unavailable",
    }
    if code is not None:
        result["error_code"] = code
    return result


def _run_timed(
    report: dict[str, object],
    name: str,
    operation: Callable[[], Any],
) -> Any:
    started = time.monotonic()
    try:
        result = operation()
    except RunnerFailure as exc:
        _stages(report).append(_stage(name, started, status="failed", code=exc.code))
        raise
    except Exception as exc:
        del exc
        _stages(report).append(
            _stage(name, started, status="failed", code="runner_failure")
        )
        raise RunnerFailure("runner_failure") from None
    _stages(report).append(_stage(name, started))
    return result


def _stages(report: dict[str, object]) -> list[dict[str, object]]:
    value = report.setdefault("stages", [])
    if not isinstance(value, list):
        raise RunnerFailure("stage_report_invalid")
    return cast(list[dict[str, object]], value)


def _poll(
    transport: SessionTransport,
    path: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    predicate: Callable[[dict[str, object]], bool],
    timeout_code: str,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, object] | None = None
    while True:
        response = transport.request("GET", path, csrf=False)
        last = _mapping(response.data, "http_response_invalid")
        if predicate(last):
            return last
        if time.monotonic() >= deadline:
            del last
            raise RunnerFailure(timeout_code)
        if poll_interval_seconds > 0:
            time.sleep(
                min(poll_interval_seconds, max(0.0, deadline - time.monotonic()))
            )


def _preview_turns(
    detail: Mapping[str, object], expected: int
) -> list[dict[str, object]]:
    raw = detail.get("preview_turns")
    if not isinstance(raw, list) or len(raw) != expected:
        raise RunnerFailure("preview_turn_count_invalid")
    rows = [_mapping(item, "preview_turn_invalid") for item in raw]
    rows.sort(
        key=lambda item: _int(item.get("turn_index"), "preview_turn_index_invalid")
    )
    if [item.get("turn_index") for item in rows] != list(range(expected)):
        raise RunnerFailure("preview_turn_order_invalid")
    for row in rows:
        _uuid(row.get("id"), "preview_turn_id_invalid")
        _text(row.get("speech"), "preview_speech_missing")
        if row.get("audio_ready") is not True:
            raise RunnerFailure("preview_audio_missing")
        if row.get("generation_status") not in {"final_ready", "ready", "completed"}:
            raise RunnerFailure("preview_generation_incomplete")
    return rows


def _preview_poll_rows(
    detail: Mapping[str, object], expected: int
) -> list[dict[str, object]]:
    raw = detail.get("preview_turns")
    if not isinstance(raw, list) or len(raw) != expected:
        raise RunnerFailure("preview_turn_count_invalid")
    rows = [_mapping(item, "preview_turn_invalid") for item in raw]
    seen_indices: set[int] = set()
    for row in rows:
        index = _int(row.get("turn_index"), "preview_turn_index_invalid")
        if index in seen_indices:
            raise RunnerFailure("preview_turn_order_invalid")
        seen_indices.add(index)
        _uuid(row.get("id"), "preview_turn_id_invalid")
        status = row.get("generation_status")
        if (
            not isinstance(status, str)
            or not status.strip()
            or not _SAFE_CODE.fullmatch(status)
        ):
            raise RunnerFailure("preview_turn_status_invalid")
        if not isinstance(row.get("audio_ready"), bool):
            raise RunnerFailure("preview_audio_status_invalid")
    if seen_indices != set(range(expected)):
        raise RunnerFailure("preview_turn_order_invalid")
    rows.sort(
        key=lambda item: _int(item.get("turn_index"), "preview_turn_index_invalid")
    )
    return rows


def _preview_row_ready(row: Mapping[str, object]) -> bool:
    return (
        row.get("generation_status") in {"final_ready", "ready", "completed"}
        and row.get("audio_ready") is True
    )


def _preview_poll(
    transport: SessionTransport,
    path: str,
    *,
    expected: int,
    poll_interval_seconds: float,
    turn_timeout_seconds: float = PREVIEW_TURN_TIMEOUT_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> PreviewPollResult:
    """Poll Preview with a per-turn timeout and a bounded aggregate budget.

    The preparation queue is sequential in the real service, so a 5x4 case
    may legitimately spend more than 180 seconds in Preview while every turn
    stays within the approved 180-second running-to-audio-ready limit.  The
    monitor records observed status transitions instead of deriving fake
    per-turn timings from the aggregate wall clock.
    """

    if expected < 1 or turn_timeout_seconds <= 0 or poll_interval_seconds < 0:
        raise RunnerFailure("preview_timeout_config_invalid")
    started = clock()
    overall_timeout_seconds = expected * turn_timeout_seconds
    progress: dict[str, dict[str, object]] = {}
    last_detail: dict[str, object] | None = None
    while True:
        now = clock()
        elapsed_ms = max(0, int((now - started) * 1000))
        response = transport.request("GET", path, csrf=False)
        detail = _mapping(response.data, "http_response_invalid")
        last_detail = detail
        if (
            detail.get("preview_turns") == []
            and isinstance(detail.get("preview"), Mapping)
            and not detail["preview"].get("ready")
        ):
            if clock() - started > overall_timeout_seconds:
                raise RunnerFailure("preview_turn_stalled")
            sleeper(poll_interval_seconds)
            continue
        rows = _preview_poll_rows(detail, expected)
        all_ready = True
        for row in rows:
            turn_id = _uuid(row.get("id"), "preview_turn_id_invalid")
            index = _int(row.get("turn_index"), "preview_turn_index_invalid")
            status = cast(str, row.get("generation_status"))
            audio_ready = cast(bool, row.get("audio_ready"))
            item = progress.setdefault(
                turn_id,
                {
                    "turn_id": turn_id,
                    "turn_index": index,
                    "running_at_ms": None,
                    "audio_ready_at_ms": None,
                    "latency_ms": UNAVAILABLE,
                    "latency_basis": UNAVAILABLE,
                    "status_progress": [],
                },
            )
            status_progress = item["status_progress"]
            if not isinstance(
                status_progress, list
            ):  # pragma: no cover - internal invariant
                raise RunnerFailure("preview_progress_invalid")
            previous = status_progress[-1] if status_progress else None
            current = {
                "at_ms": elapsed_ms,
                "generation_status": status,
                "audio_ready": audio_ready,
            }
            if previous != current:
                status_progress.append(current)

            ready = _preview_row_ready(row)
            all_ready = all_ready and ready
            if status in {"failed", "turn_generation_failed"}:
                raise RunnerFailure("preview_turn_failed")
            running_at_value = item.get("running_at_ms")
            running_at_ms = (
                running_at_value if isinstance(running_at_value, int) else None
            )
            if running_at_ms is None and status == "running":
                item["running_at_ms"] = elapsed_ms
                running_at_ms = elapsed_ms
            if (
                not ready
                and running_at_ms is None
                and status not in {"pending", "queued"}
            ):
                # A turn can be in the audio stage after generation has
                # completed.  Start its bounded active timer at that point.
                item["running_at_ms"] = elapsed_ms
                running_at_ms = elapsed_ms
                item["latency_basis"] = "active_to_audio_ready"
            if ready:
                if item.get("audio_ready_at_ms") is None:
                    item["audio_ready_at_ms"] = elapsed_ms
                    if running_at_ms is not None:
                        item["latency_ms"] = max(0, elapsed_ms - running_at_ms)
                        item["latency_basis"] = "running_to_audio_ready"
                    else:
                        item["latency_ms"] = 0
                        item["latency_basis"] = "ready_at_first_observation"
            elif running_at_ms is not None and elapsed_ms - running_at_ms > int(
                turn_timeout_seconds * 1000
            ):
                raise RunnerFailure("preview_turn_stalled")

        if all_ready:
            _preview_turns(detail, expected)
            ordered_progress = sorted(
                progress.values(), key=lambda item: int(cast(int, item["turn_index"]))
            )
            audit = {
                "overall_wall_ms": elapsed_ms,
                "overall_timeout_ms": int(overall_timeout_seconds * 1000),
                "turn_timeout_ms": int(turn_timeout_seconds * 1000),
                "poll_resolution_ms": int(poll_interval_seconds * 1000),
                "turns": ordered_progress,
            }
            return PreviewPollResult(detail=detail, audit=audit)
        if elapsed_ms >= int(overall_timeout_seconds * 1000):
            del last_detail
            raise RunnerFailure("preview_timeout")
        remaining = max(0.0, overall_timeout_seconds - (elapsed_ms / 1000))
        if poll_interval_seconds > 0:
            sleeper(min(poll_interval_seconds, remaining))
        else:
            # Keep a zero-interval test/operator setting bounded without
            # turning the loop into a tight spin.
            sleeper(min(0.01, remaining))


def _validate_created_detail(
    detail: Mapping[str, object], spec: SessionSpec, config: ExecutionConfig
) -> None:
    if detail.get("turn_protocol") != "segments_v2":
        raise RunnerFailure("turn_protocol_invalid")
    if detail.get("output_language") != spec.language:
        raise RunnerFailure("language_mismatch")
    if _int(detail.get("round_count"), "round_count_invalid") != spec.round_count:
        raise RunnerFailure("round_count_mismatch")
    participants = detail.get("participants")
    if not isinstance(participants, list) or len(participants) != spec.agent_count:
        raise RunnerFailure("participant_count_mismatch")
    for index, item in enumerate(participants):
        row = _mapping(item, "participant_invalid")
        if (
            _uuid(row.get("agent_id"), "participant_agent_invalid")
            != config.agent_ids[index]
        ):
            raise RunnerFailure("participant_order_mismatch")
        _uuid(row.get("agent_version_id"), "participant_version_invalid")
        _uuid(row.get("knowledge_snapshot_id"), "participant_snapshot_invalid")
        if config.expected_version_ids:
            if (
                _uuid(row.get("agent_version_id"), "participant_version_invalid")
                != config.expected_version_ids[index]
            ):
                raise RunnerFailure("participant_version_mismatch")


def _extract_access_token(public_url: object) -> str:
    value = _text(public_url, "interaction_url_missing")
    parsed = urlsplit(value)
    token = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not _TOKEN.fullmatch(token):
        raise RunnerFailure("interaction_token_invalid")
    return token


def _validate_agents(
    transport: SessionTransport,
    config: ExecutionConfig,
) -> None:
    response = transport.request(
        "GET", f"/api/v1/courses/{config.course_id}/published-agents", csrf=False
    )
    if not isinstance(response.data, list):
        raise RunnerFailure("published_agents_invalid")
    rows = [_mapping(item, "published_agent_invalid") for item in response.data]
    by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        agent = _mapping(row.get("agent"), "published_agent_invalid")
        agent_id = _uuid(agent.get("id"), "published_agent_id_invalid")
        by_id[agent_id] = row
    for index, agent_id in enumerate(config.agent_ids):
        selected = by_id.get(agent_id)
        if selected is None:
            raise RunnerFailure("agent_not_published")
        version = _mapping(selected.get("current_version"), "published_version_invalid")
        if (
            _uuid(version.get("agent_id"), "published_version_agent_invalid")
            != agent_id
        ):
            raise RunnerFailure("published_version_agent_invalid")
        if version.get("state") != "published":
            raise RunnerFailure("agent_not_published")
        if version.get("persona_compiler_version") != "persona_template_v2":
            raise RunnerFailure("agent_persona_v2_required")
        _uuid(version.get("knowledge_snapshot_id"), "knowledge_snapshot_missing")
        if (
            config.expected_version_ids
            and _uuid(version.get("id"), "published_version_id_invalid")
            != config.expected_version_ids[index]
        ):
            raise RunnerFailure("published_version_mismatch")


def _validate_fresh_composition(transport: SessionTransport) -> dict[str, str]:
    """Require the reviewed Real/Mock slice before a fresh acceptance case."""

    response = transport.request("GET", "/api/v1/demo/composition", csrf=False)
    body = _mapping(response.data, "composition_response_invalid")
    raw_components = body.get("components")
    if not isinstance(raw_components, list):
        raise RunnerFailure("composition_components_invalid")
    expected = {"embedding", "llm", "tts", "voice", "report"}
    modes: dict[str, str] = {}
    for item in raw_components:
        component = _mapping(item, "composition_component_invalid")
        key = _text(component.get("key"), "composition_component_key_invalid")
        mode = _text(component.get("mode"), "composition_component_mode_invalid")
        if key not in expected or key in modes or mode not in {"real", "mock"}:
            raise RunnerFailure("composition_component_invalid")
        unreviewed = component.get("policy_unreviewed")
        if not isinstance(unreviewed, bool):
            raise RunnerFailure("composition_policy_status_invalid")
        if key in {"embedding", "llm", "report"}:
            if mode != "real":
                raise RunnerFailure("composition_real_required")
            if unreviewed:
                raise RunnerFailure("composition_policy_unreviewed")
        elif mode != "mock":
            raise RunnerFailure("composition_mock_required")
        modes[key] = mode
    if set(modes) != expected:
        raise RunnerFailure("composition_component_missing")
    return modes


def _next_turn_ready_detail(
    detail: Mapping[str, object], completed_turn_id: str
) -> bool:
    playback = detail.get("playback")
    if not isinstance(playback, Mapping):
        return False
    return (
        playback.get("status") == "waiting_next"
        and playback.get("next_turn_ready") is True
        and playback.get("current_turn_id") == completed_turn_id
    )


def _wait_for_next_ready(
    teacher: SessionTransport,
    controller: PlaybackController,
    debate_id: str,
    completed_turn_id: str,
) -> int:
    """Wait for successor readiness before issuing the teacher Next CAS.

    A completed turn first emits ``playback.waiting_next`` with
    ``next_turn_ready=false`` while the successor is generated and voiced.
    The preparation worker later emits a second event with the readiness bit
    set.  REST detail is checked as the authoritative bounded fallback so a
    reconnect or a missed event cannot make the runner send an early Next.
    """

    deadline = time.monotonic() + controller.timeout_seconds
    event_slice = min(
        controller.timeout_seconds,
        max(0.25, controller.poll_interval_seconds or 0.25),
    )
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            waiting = controller._until(
                "event_type",
                "playback.waiting_next",
                timeout_seconds=min(event_slice, remaining),
            )
            payload = _mapping(waiting.get("payload"), "waiting_next_invalid")
            # Ignore a stale event left in a resumed socket.  The REST check
            # below still requires the current turn to be this predecessor.
            if payload.get("completed_turn_id") != completed_turn_id:
                continue
        except RunnerFailure as exc:
            # A healthy WebSocket can be quiet while the preparation worker is
            # finishing.  In that case the bounded REST check below is enough;
            # transport failures remain hard failures.
            if exc.code != "websocket_stage_timeout":
                raise

        detail = _mapping(
            teacher.request("GET", f"/api/v1/debates/{debate_id}", csrf=False).data,
            "next_detail_invalid",
        )
        if _next_turn_ready_detail(detail, completed_turn_id):
            playback = _mapping(detail.get("playback"), "next_playback_invalid")
            return _int(playback.get("control_version"), "control_version_invalid")
        if time.monotonic() >= deadline:
            break
        if controller.poll_interval_seconds > 0:
            time.sleep(
                min(
                    controller.poll_interval_seconds,
                    max(0.0, deadline - time.monotonic()),
                )
            )
    raise RunnerFailure("next_preparation_timeout")


def _advance(
    teacher: SessionTransport,
    controller: PlaybackController,
    debate_id: str,
    completed_turn_id: str,
    expected_next_id: str | None = None,
) -> tuple[str, int]:
    # Never use the first waiting event's control version blindly: it may
    # explicitly say that the adjacent turn is still being prepared.
    waiting_version = _wait_for_next_ready(
        teacher,
        controller,
        debate_id,
        completed_turn_id,
    )
    next_state = _mapping(
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/next",
            payload={
                "expected_control_version": waiting_version,
                "expected_current_turn_id": completed_turn_id,
            },
        ).data,
        "next_response_invalid",
    )
    playback = _mapping(next_state, "next_response_invalid")
    next_version = _int(playback.get("control_version"), "control_version_invalid")
    next_id = _uuid(playback.get("current_turn_id"), "current_turn_invalid")
    if expected_next_id is not None and next_id != expected_next_id:
        raise RunnerFailure("next_turn_mismatch")
    return next_id, next_version


def _reply_binding_ids(event: Mapping[str, object]) -> set[str]:
    payload = _mapping(event.get("payload"), "playback_started_invalid")
    segment = _mapping(payload.get("segment_turn"), "segment_payload_missing")
    rows = segment.get("segments")
    if not isinstance(rows, list):
        raise RunnerFailure("segment_list_invalid")
    return {
        cast(str, row["reply_to"])
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("reply_to"), str)
    }


def _play_many(
    controller: PlaybackController,
    teacher: SessionTransport,
    debate_id: str,
    *,
    turn_ids: Sequence[str] | None,
    turn_count: int | None = None,
    first_turn_id: str,
    control_version: int,
    epoch: str,
    action: str,
    on_started: Callable[[str, int], None] | None = None,
    round_by_id: Mapping[str, int] | None = None,
    require_reply_binding: bool = False,
    allowed_reply_ids: set[str] | None = None,
) -> tuple[list[dict[str, object]], int, int]:
    count = len(turn_ids) if turn_ids is not None else (turn_count or 0)
    current = first_turn_id
    events: list[dict[str, object]] = []
    reply_bound = 0
    if count < 1:
        raise RunnerFailure("turn_plan_missing")
    for index in range(count):
        expected_id = turn_ids[index] if turn_ids is not None else current
        if current != expected_id:
            raise RunnerFailure("current_turn_mismatch")
        callback: Callable[[dict[str, object]], None] | None = None
        if on_started is not None and round_by_id is not None:

            def started_callback(
                _event: dict[str, object],
                turn_id: str = expected_id,
                round_no: int = round_by_id[expected_id],
            ) -> None:
                on_started(turn_id, round_no)

            callback = started_callback
        started, _completed, ended_version = controller.play_one(
            turn_id=expected_id,
            expected_control_version=control_version,
            epoch=epoch,
            action=action if index == 0 else "next",
            after_started=callback,
        )
        events.append(started)
        if require_reply_binding:
            binding_ids = _reply_binding_ids(started)
            if not binding_ids:
                raise RunnerFailure("final_reply_binding_missing")
            if allowed_reply_ids is not None and not binding_ids <= allowed_reply_ids:
                raise RunnerFailure("final_reply_binding_unknown")
            reply_bound += 1
        if index + 1 < count:
            current, control_version = _advance(
                teacher,
                controller,
                debate_id,
                expected_id,
                expected_next_id=(
                    turn_ids[index + 1] if turn_ids is not None else None
                ),
            )
        else:
            control_version = ended_version
    return events, control_version, reply_bound


def _safe_case_report(
    spec: SessionSpec,
    *,
    composition_modes: Mapping[str, str] | None = None,
) -> dict[str, object]:
    provider_evidence: dict[str, object] = {
        "embedding": UNAVAILABLE,
        "llm": UNAVAILABLE,
        "report": UNAVAILABLE,
        "tts": UNAVAILABLE,
        "three_d_browser": UNAVAILABLE,
    }
    result: dict[str, object] = {
        "session_id": spec.session_id,
        "session_kind": spec.session_kind,
        "language": spec.language,
        "agent_count": spec.agent_count,
        "round_count": spec.round_count,
        "expected_turns": spec.expected_turns,
        "barrage_mode": spec.barrage_mode,
        "expected_final_replies": spec.expected_final_replies,
        "status": "running",
        "stages": [],
        "provider_evidence": provider_evidence,
        "audio_playback_evidence": "http_bytes_only",
    }
    if composition_modes is not None:
        observed = dict(composition_modes)
        result["composition_modes"] = observed
        provider_evidence.update(observed)
    return result


def _observed_turns(item: Mapping[str, object]) -> int:
    observed = item.get("observed")
    if not isinstance(observed, Mapping):
        return 0
    value = observed.get("turns")
    return value if isinstance(value, int) else 0


class NextWaveRealSessionRunner:
    """Execute selected SessionSpec rows using injected transports."""

    def __init__(
        self,
        bundle: FixtureBundle,
        *,
        transport_factory: Callable[[str], SessionTransport],
        run_id: str | None = None,
    ) -> None:
        self.bundle = bundle
        self.transport_factory = transport_factory
        self.run_id = run_id or str(uuid4())

    def execute(
        self,
        sessions: Sequence[SessionSpec],
        config: ExecutionConfig,
        *,
        resume_debug_debate_id: str | None = None,
    ) -> dict[str, object]:
        _validate_config(sessions, config)
        teacher = self.transport_factory("teacher")
        student = self.transport_factory("student")
        reports: list[dict[str, object]] = []
        stopped_reason: str | None = None
        composition_modes: dict[str, str] | None = None
        try:
            setup: list[dict[str, object]] = []
            started = time.monotonic()
            try:
                quick_login = getattr(teacher, "quick_login", None)
                student_login = getattr(student, "quick_login", None)
                if not callable(quick_login) or not callable(student_login):
                    raise RunnerFailure("quick_login_unavailable")
                quick_login(config.teacher_user_id)
                student_login(config.student_user_id)
                setup.append(_stage("quick_login", started))
                started = time.monotonic()
                if config.group_id is not None and resume_debug_debate_id is None:
                    composition_modes = _validate_fresh_composition(teacher)
                    setup.append(_stage("composition_preflight", started))
                elif config.group_id is None:
                    _validate_agents(teacher, config)
                    setup.append(_stage("agent_preflight", started))
            except RunnerFailure as exc:
                setup.append(_stage("setup", started, status="failed", code=exc.code))
                return self._run_summary(
                    sessions, reports, setup, stopped_reason=exc.code
                )

            for spec in sessions:
                report = self._run_case(
                    spec,
                    config,
                    teacher,
                    student,
                    resume_debug_debate_id=resume_debug_debate_id,
                    composition_modes=composition_modes,
                )
                reports.append(report)
                if report.get("status") in {"acceptance_unknown", "failed"}:
                    stopped_reason = str(
                        report.get("safe_error_code")
                        or report.get("error_code")
                        or report.get("status")
                    )
                    break
        finally:
            teacher.close()
            student.close()
        return self._run_summary(
            sessions, reports, setup, stopped_reason=stopped_reason
        )

    def _run_summary(
        self,
        sessions: Sequence[SessionSpec],
        reports: Sequence[Mapping[str, object]],
        setup: Sequence[Mapping[str, object]],
        *,
        stopped_reason: str | None,
    ) -> dict[str, object]:
        if stopped_reason == "acceptance_unknown":
            status = "acceptance_unknown"
        elif any(item.get("status") == "failed" for item in reports):
            status = "real_failed"
        elif len(reports) == len(sessions):
            status = "api_flow_complete_pending_browser_review"
        else:
            status = "real_failed"
        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_receipt_id": self.run_id,
            "status": status,
            "execution_mode": "http_ws",
            "sessions_expected": len(sessions),
            "turns_expected": sum(item.expected_turns for item in sessions),
            "reports_expected": len(sessions),
            "fixture_hash": self.bundle.fixture_hash,
            "sessions_observed": len(reports),
            "turns_observed": sum(_observed_turns(item) for item in reports),
            "real_calls_made": UNAVAILABLE,
            "setup_stages": list(setup),
            "stopped_reason": stopped_reason,
            "pending_evidence": [
                "provider_attempt_counts",
                "configured_tts_audio_identity",
                "audio_playback_evidence",
                "browser_audio_playback",
                "three_d_face_playback",
            ],
            "reports": list(reports),
        }

    def _run_case(
        self,
        spec: SessionSpec,
        config: ExecutionConfig,
        teacher: SessionTransport,
        student: SessionTransport,
        *,
        resume_debug_debate_id: str | None = None,
        composition_modes: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        report = _safe_case_report(spec, composition_modes=composition_modes)
        session_receipt = _idempotency(self.run_id, spec.session_id, "case")
        report["case_receipt_id"] = session_receipt
        if resume_debug_debate_id is not None:
            report["resumed_debug"] = True
            report["resume_debate_id"] = resume_debug_debate_id
        debate_id: str | None = None
        socket: EventSocket | None = None
        controller: PlaybackController | None = None
        try:
            if config.group_id is not None and resume_debug_debate_id is None:
                from next_wave_session_authoring import (
                    AuthoringFailure,
                    author_session_agents,
                )

                try:
                    authored = author_session_agents(
                        spec,
                        student=student,
                        teacher=teacher,
                        group_id=config.group_id,
                        corpus=config.corpus_path,
                        run_id=self.run_id,
                    )
                except AuthoringFailure as exc:
                    report["agent_authoring"] = exc.partial_audit
                    raise RunnerFailure(exc.code) from None
                report["agent_authoring"] = authored
                config = replace(
                    config,
                    agent_ids=tuple(
                        _uuid(item, "authored_agent_id_invalid")
                        for item in cast(list[object], authored["agent_ids"])
                    ),
                    expected_version_ids=tuple(
                        _uuid(item, "authored_version_id_invalid")
                        for item in cast(list[object], authored["version_ids"])
                    ),
                )
                _validate_agents(teacher, config)
            selected_agents = config.agent_ids[: spec.agent_count]
            selected_versions = (
                config.expected_version_ids[: spec.agent_count]
                if config.expected_version_ids
                else ()
            )
            case_config = ExecutionConfig(
                config.course_id,
                config.teacher_user_id,
                config.student_user_id,
                selected_agents,
                selected_versions,
                config.timeout_seconds,
                config.poll_interval_seconds,
            )

            if resume_debug_debate_id is None:
                created_response = _run_timed(
                    report,
                    "create",
                    lambda: teacher.request(
                        "POST",
                        f"/api/v1/courses/{config.course_id}/debates",
                        payload={
                            "topic": _topic(spec.language),
                            "output_language": spec.language,
                            "turn_protocol": "segments_v2",
                            "round_count": spec.round_count,
                            "participants": [
                                {"agent_id": agent_id, "stance_mode": "open"}
                                for agent_id in selected_agents
                            ],
                        },
                        idempotency_key=_idempotency(
                            self.run_id, spec.session_id, "create"
                        ),
                    ),
                )
                created = _mapping(created_response.data, "create_response_invalid")
                debate_id = _uuid(created.get("id"), "debate_id_invalid")
                report["debate_id"] = debate_id
                _validate_created_detail(created, spec, case_config)
            else:
                debate_id = _uuid(resume_debug_debate_id, "resume_debate_id_invalid")
                report["debate_id"] = debate_id
                resumed = _run_timed(
                    report,
                    "resume_read",
                    lambda: _mapping(
                        teacher.request(
                            "GET", f"/api/v1/debates/{debate_id}", csrf=False
                        ).data,
                        "resume_detail_invalid",
                    ),
                )
                _validate_created_detail(resumed, spec, case_config)

            expected_preview = spec.agent_count * (spec.round_count - 1)
            preview_result = _run_timed(
                report,
                "preview_resume" if resume_debug_debate_id is not None else "preview",
                lambda: _preview_poll(
                    teacher,
                    f"/api/v1/debates/{debate_id}",
                    expected=expected_preview,
                    poll_interval_seconds=config.poll_interval_seconds,
                ),
            )
            if not isinstance(
                preview_result, PreviewPollResult
            ):  # pragma: no cover - invariant
                raise RunnerFailure("preview_result_invalid")
            report["preview_progress"] = preview_result.audit
            preview_detail = preview_result.detail
            preview_rows = _preview_turns(preview_detail, expected_preview)
            pre_ids = [
                str(_uuid(row.get("id"), "preview_turn_id_invalid"))
                for row in preview_rows
            ]
            pre_rounds = {
                str(_uuid(row.get("id"), "preview_turn_id_invalid")): _int(
                    row.get("round_no"), "preview_round_invalid"
                )
                for row in preview_rows
            }

            if resume_debug_debate_id is None:
                start_detail = _run_timed(
                    report,
                    "start",
                    lambda: _mapping(
                        teacher.request(
                            "POST",
                            f"/api/v1/debates/{debate_id}/start",
                            payload={
                                "expected_revision": _int(
                                    preview_detail.get("revision"), "revision_invalid"
                                ),
                                "expected_current_audio_debate_id": None,
                                "confirm_previous_audio_cleanup": False,
                                "output_language": spec.language,
                            },
                            idempotency_key=_idempotency(
                                self.run_id, spec.session_id, "start"
                            ),
                        ).data,
                        "start_response_invalid",
                    ),
                )
            else:
                start_detail = preview_detail
            playback = _mapping(start_detail.get("playback"), "start_playback_invalid")
            control_version = _int(
                playback.get("control_version"), "control_version_invalid"
            )
            current_turn_id = _uuid(
                playback.get("current_turn_id"), "current_turn_invalid"
            )
            if current_turn_id != pre_ids[0]:
                raise RunnerFailure("initial_turn_mismatch")

            if resume_debug_debate_id is None:
                opened = _run_timed(
                    report,
                    "interaction_open",
                    lambda: _mapping(
                        teacher.request(
                            "POST",
                            f"/api/v1/debates/{debate_id}/interaction/open",
                            idempotency_key=_idempotency(
                                self.run_id, spec.session_id, "open"
                            ),
                        ).data,
                        "interaction_response_invalid",
                    ),
                )
            else:
                opened = _run_timed(
                    report,
                    "interaction_resume",
                    lambda: _mapping(
                        teacher.request(
                            "GET",
                            f"/api/v1/debates/{debate_id}/interaction",
                            csrf=False,
                        ).data,
                        "interaction_response_invalid",
                    ),
                )
            if opened.get("status") != "open":
                raise RunnerFailure("interaction_not_open")
            access_token = _extract_access_token(opened.get("public_url"))
            sent_rounds: set[int] = set()
            pre_started_events: list[dict[str, object]] = []
            socket = _run_timed(
                report,
                "websocket_open",
                lambda: teacher.open_events(f"/api/v1/debates/{debate_id}/events"),
            )
            controller = PlaybackController(
                teacher,
                socket,
                debate_id=debate_id,
                timeout_seconds=config.timeout_seconds,
                poll_interval_seconds=config.poll_interval_seconds,
                require_grades=config.group_id is not None,
            )
            assert controller is not None
            epoch, control_version = _run_timed(
                report,
                "controller_acquire",
                lambda: controller.acquire(control_version),
            )

            def submit_for_turn(turn_id: str, round_no: int) -> None:
                if (
                    spec.barrage_mode != "with_barrage"
                    or round_no not in spec.eligible_turns
                ):
                    return
                if round_no in sent_rounds:
                    return
                form = student.request(
                    "GET", f"/api/v1/classroom-interactions/{access_token}", csrf=False
                ).data
                form_data = _mapping(form, "public_form_invalid")
                if (
                    form_data.get("barrage_open") is not True
                    or form_data.get("current_turn_id") != turn_id
                ):
                    raise RunnerFailure("barrage_turn_changed")
                student.request(
                    "POST",
                    f"/api/v1/classroom-interactions/{access_token}/barrages",
                    payload={
                        "nickname": "Student",
                        "raw_text": _barrage_text(spec.language, round_no),
                        "client_submission_id": str(uuid4()),
                        "turn_id": turn_id,
                    },
                    csrf=False,
                )
                sent_rounds.add(round_no)

            playback_started = time.monotonic()
            pre_started_events, control_version, _ = _play_many(
                controller,
                teacher,
                debate_id,
                turn_ids=pre_ids,
                first_turn_id=current_turn_id,
                control_version=control_version,
                epoch=epoch,
                action="start",
                on_started=submit_for_turn,
                round_by_id=pre_rounds,
            )
            _stages(report).append(_stage("playback_nonfinal", playback_started))
            report["barrages_submitted"] = len(sent_rounds)

            frozen = _run_timed(
                report,
                "final_freeze",
                lambda: _mapping(
                    teacher.request(
                        "POST",
                        f"/api/v1/debates/{debate_id}/final-input",
                        payload={"expected_control_version": control_version},
                    ).data,
                    "final_input_response_invalid",
                ),
            )
            if frozen.get("ready") is not True:
                raise RunnerFailure("final_input_not_ready")
            if _int(frozen.get("barrage_count"), "barrage_count_invalid") != len(
                sent_rounds
            ):
                raise RunnerFailure("barrage_count_mismatch")
            report["final_input"] = {
                "barrage_count": frozen.get("barrage_count"),
                "cutoff_sequence": frozen.get("cutoff_sequence"),
            }

            final_waiting = _run_timed(
                report,
                "final_preparation",
                lambda: _poll(
                    teacher,
                    f"/api/v1/debates/{debate_id}",
                    timeout_seconds=config.timeout_seconds,
                    poll_interval_seconds=config.poll_interval_seconds,
                    predicate=lambda item: _final_ready(item, set(pre_ids)),
                    timeout_code="final_preparation_timeout",
                ),
            )
            final_playback = _mapping(
                final_waiting.get("playback"), "final_playback_invalid"
            )
            control_version = _int(
                final_playback.get("control_version"), "control_version_invalid"
            )
            prior_id = _uuid(
                final_playback.get("current_turn_id"), "current_turn_invalid"
            )
            if prior_id != pre_ids[-1]:
                raise RunnerFailure("final_boundary_turn_mismatch")
            next_state = _mapping(
                teacher.request(
                    "POST",
                    f"/api/v1/debates/{debate_id}/next",
                    payload={
                        "expected_control_version": control_version,
                        "expected_current_turn_id": prior_id,
                    },
                ).data,
                "final_next_response_invalid",
            )
            next_playback = _mapping(next_state, "final_next_response_invalid")
            control_version = _int(
                next_playback.get("control_version"), "control_version_invalid"
            )
            current_turn_id = _uuid(
                next_playback.get("current_turn_id"), "final_turn_invalid"
            )
            final_playback_started = time.monotonic()
            final_started_events, control_version, final_reply_bound_turns = _play_many(
                controller,
                teacher,
                debate_id,
                turn_ids=None,
                turn_count=spec.agent_count,
                first_turn_id=current_turn_id,
                control_version=control_version,
                epoch=epoch,
                action="next",
                require_reply_binding=spec.barrage_mode == "with_barrage",
                allowed_reply_ids={
                    f"B{index}" for index in range(1, len(sent_rounds) + 1)
                },
            )
            _stages(report).append(_stage("playback_final", final_playback_started))

            if socket is not None:
                socket.close()
                socket = None

            conclude_action = _run_timed(
                report,
                "finish_conclude",
                lambda: _finish_and_conclude(
                    teacher, debate_id, config, spec, control_version
                ),
            )
            report["conclude_action"] = conclude_action
            generated = _run_timed(
                report,
                "report_generate",
                lambda: teacher.request(
                    "POST",
                    f"/api/v1/debates/{debate_id}/report/generate",
                    idempotency_key=_idempotency(
                        self.run_id, spec.session_id, "report"
                    ),
                ),
            )
            _mapping(generated.data, "report_response_invalid")
            report_body = _run_timed(
                report,
                "report_poll",
                lambda: _poll(
                    teacher,
                    f"/api/v1/debates/{debate_id}/report",
                    timeout_seconds=config.timeout_seconds,
                    poll_interval_seconds=config.poll_interval_seconds,
                    predicate=_report_ready,
                    timeout_code="report_timeout",
                ),
            )
            if report_body.get("generation_status") != "ready":
                raise RunnerFailure("report_not_ready")
            downloaded = _run_timed(
                report,
                "report_download",
                lambda: teacher.request(
                    "GET",
                    f"/api/v1/debates/{debate_id}/report/download?language=en",
                    csrf=False,
                    raw=True,
                ),
            )
            if downloaded.status_code != 200 or not downloaded.byte_count:
                raise RunnerFailure(
                    "report_download_failed", status_code=downloaded.status_code
                )
            observed: dict[str, object] = {
                "turns": len(pre_started_events) + len(final_started_events),
                "nonfinal_turns": len(pre_started_events),
                "final_turns": len(final_started_events),
                "audio_fetches": controller.audio_fetches if controller else 0,
                "audio_bytes": controller.audio_bytes if controller else 0,
                "turn_wall_ms": controller.turn_latencies_ms if controller else [],
                "provider_attempts": UNAVAILABLE,
                "final_reply_bound_turns": final_reply_bound_turns,
            }
            report["observed"] = observed
            if observed["turns"] != spec.expected_turns:
                raise RunnerFailure("turn_count_observed_mismatch")
            if spec.barrage_mode == "with_barrage" and (
                observed["final_reply_bound_turns"] != spec.expected_final_replies
            ):
                raise RunnerFailure("final_reply_count_mismatch")
            report["status"] = "api_flow_complete_pending_browser_review"
            return report
        except RunnerFailure as exc:
            report["status"] = (
                "acceptance_unknown" if exc.code == "acceptance_unknown" else "failed"
            )
            report["error_code"] = exc.code
            if exc.status_code is not None:
                report["http_status"] = exc.status_code
            return report
        finally:
            if socket is not None:
                try:
                    socket.close()
                except Exception:
                    pass


def _preview_ready(detail: Mapping[str, object], expected: int) -> bool:
    stall = detail.get("stall")
    if isinstance(stall, Mapping):
        code = stall.get("safe_error_code")
        if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
            raise RunnerFailure(code)
    rows = detail.get("preview_turns")
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, Mapping):
                code = item.get("safe_error_code")
                if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
                    raise RunnerFailure(code)
    preview = detail.get("preview")
    if isinstance(preview, Mapping):
        prepared = preview.get("prepared_turns")
        total = preview.get("expected_turns")
        if prepared == expected and total == expected and preview.get("ready") is True:
            return True
    return False


def _final_ready(detail: Mapping[str, object], pre_ids: set[str]) -> bool:
    stall = detail.get("stall")
    if isinstance(stall, Mapping):
        code = stall.get("safe_error_code")
        if isinstance(code, str) and _SAFE_CODE.fullmatch(code):
            raise RunnerFailure(code)
    playback = detail.get("playback")
    if not isinstance(playback, Mapping):
        return False
    current = playback.get("current_turn_id")
    return (
        playback.get("status") == "waiting_next"
        and playback.get("next_turn_ready") is True
        and isinstance(current, str)
        and current in pre_ids
    )


def _report_ready(detail: Mapping[str, object]) -> bool:
    if detail.get("generation_status") == "failed":
        raise RunnerFailure("report_failed")
    return detail.get("generation_status") == "ready"


def _finish_and_conclude(
    teacher: SessionTransport,
    debate_id: str,
    config: ExecutionConfig,
    spec: SessionSpec,
    control_version: int,
) -> str:
    del config, spec
    detail = _mapping(
        teacher.request("GET", f"/api/v1/debates/{debate_id}", csrf=False).data,
        "finish_detail_invalid",
    )
    status = detail.get("status")
    playback = _mapping(detail.get("playback"), "finish_playback_invalid")
    action = "natural_completion"
    if status == "running" and playback.get("status") not in {"completed", "stopped"}:
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/finish",
            payload={
                "expected_control_version": control_version,
                "expected_current_turn_id": playback.get("current_turn_id"),
            },
            idempotency_key=f"nw-finish-{uuid4().hex}",
        )
        action = "finish_route"
    elif status not in {"debate_finished", "completed"}:
        raise RunnerFailure("debate_not_terminal")
    interaction = teacher.request(
        "GET", f"/api/v1/debates/{debate_id}/interaction", csrf=False
    ).data
    interaction_data = _mapping(interaction, "interaction_response_invalid")
    if interaction_data.get("status") == "open":
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/interaction/close",
            idempotency_key=f"nw-close-{uuid4().hex}",
        )
        return f"{action}+interaction_close"
    elif interaction_data.get("status") != "finalized":
        raise RunnerFailure("interaction_not_concludable")
    return f"{action}+already_finalized"


def _validate_config(sessions: Sequence[SessionSpec], config: ExecutionConfig) -> None:
    if config.group_id is None and not 2 <= len(config.agent_ids) <= 5:
        raise RunnerFailure("agent_count_invalid")
    if config.group_id is not None:
        _uuid(config.group_id, "group_id_invalid")
        if config.agent_ids or config.expected_version_ids:
            raise RunnerFailure("authoring_agent_ids_conflict")
    if config.timeout_seconds <= 0 or config.poll_interval_seconds < 0:
        raise RunnerFailure("timeout_config_invalid")
    if len(config.expected_version_ids) not in {0, len(config.agent_ids)}:
        raise RunnerFailure("version_mapping_invalid")
    if any(
        not isinstance(value, str) or not value
        for value in (config.course_id, config.teacher_user_id, config.student_user_id)
    ):
        raise RunnerFailure("identity_config_invalid")
    if not sessions:
        raise RunnerFailure("session_selection_empty")
    max_agents = max(item.agent_count for item in sessions)
    if config.group_id is None and len(config.agent_ids) < max_agents:
        raise RunnerFailure("agent_ids_insufficient")
    for value in (*config.agent_ids, *config.expected_version_ids):
        try:
            UUID(value)
        except (ValueError, AttributeError):
            raise RunnerFailure("identity_uuid_invalid") from None


def select_sessions(
    bundle: FixtureBundle,
    *,
    session_ids: Sequence[str] = (),
    debug_2x2: bool = False,
) -> tuple[SessionSpec, ...]:
    if debug_2x2 and session_ids:
        raise RunnerFailure("selection_flags_conflict")
    if debug_2x2:
        selected = next(
            (
                item
                for item in bundle.sessions
                if item.agent_count == 2 and item.round_count == 2
            ),
            None,
        )
        if selected is None:
            raise RunnerFailure("debug_session_missing")
        return (selected,)
    requested = tuple(session_ids)
    by_id = {item.session_id: item for item in bundle.sessions}
    if len(set(requested)) != len(requested):
        raise RunnerFailure("selection_duplicate_session")
    if any(value not in by_id for value in requested):
        raise RunnerFailure("selection_unknown_session")
    if not requested:
        return bundle.sessions
    requested_set = set(requested)
    return tuple(item for item in bundle.sessions if item.session_id in requested_set)


def dry_run(
    bundle: FixtureBundle, sessions: Sequence[SessionSpec]
) -> dict[str, object]:
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "dry_run",
        "execution_mode": "offline_plan",
        "real_calls_made": 0,
        "sessions_expected": len(sessions),
        "turns_expected": sum(item.expected_turns for item in sessions),
        "reports_expected": len(sessions),
        "barrage_assignments": {
            "with_barrage": sum(
                item.barrage_mode == "with_barrage" for item in sessions
            ),
            "without_barrage": sum(
                item.barrage_mode == "without_barrage" for item in sessions
            ),
        },
        "fixture_hash": bundle.fixture_hash,
        "session_ids": [item.session_id for item in sessions],
        "pending_integrations": [
            "published_v2_real_snapshot_ids",
            "provider_attempt_evidence_api",
            "browser_audio_and_three_d_evidence",
        ],
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_output(value: Mapping[str, object], path: Path | None) -> None:
    rendered = _json(value) + "\n"
    if path is None:
        print(rendered, end="")
        return
    path.expanduser().resolve().write_text(rendered, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=ROOT / "backend/tests/fixtures/next_wave_rag",
    )
    parser.add_argument("--session-id", action="append", default=[])
    parser.add_argument(
        "--debug-2x2",
        action="store_true",
        help="run one deterministic 2x2 debug session",
    )
    parser.add_argument(
        "--resume-debug-debate-id",
        help="resume an already started debug 2x2 Debate; debug-only recovery path",
    )
    parser.add_argument(
        "--execute-real", action="store_true", help="perform the explicit HTTP/WS run"
    )
    parser.add_argument("--base-url")
    parser.add_argument("--course-id")
    parser.add_argument("--teacher-user-id")
    parser.add_argument("--student-user-id")
    parser.add_argument(
        "--group-id", help="author fresh Agents and knowledge for every session"
    )
    parser.add_argument(
        "--corpus-path", type=Path, help="synthetic Markdown knowledge for fresh Agents"
    )
    parser.add_argument("--agent-id", action="append", default=[])
    parser.add_argument("--agent-version-id", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        bundle = load_fixture_bundle(args.fixture_root)
        sessions = select_sessions(
            bundle, session_ids=args.session_id, debug_2x2=args.debug_2x2
        )
        if args.resume_debug_debate_id and (
            not args.execute_real or not args.debug_2x2 or len(sessions) != 1
        ):
            _write_output(
                {
                    "schema_version": RUN_SCHEMA_VERSION,
                    "status": "configuration_invalid",
                    "real_calls_made": 0,
                    "error_code": "resume_debug_requires_execute_debug_2x2",
                },
                args.output,
            )
            return 2
        if args.resume_debug_debate_id:
            if args.group_id:
                raise RunnerFailure("fresh_authoring_cannot_resume")
            try:
                UUID(args.resume_debug_debate_id)
            except (ValueError, AttributeError):
                raise RunnerFailure("resume_debate_id_invalid") from None
        if not args.execute_real:
            _write_output(dry_run(bundle, sessions), args.output)
            return 0
        required = {
            "base_url": args.base_url,
            "course_id": args.course_id,
            "teacher_user_id": args.teacher_user_id,
            "student_user_id": args.student_user_id,
        }
        if any(not isinstance(value, str) or not value for value in required.values()):
            _write_output(
                {
                    "schema_version": RUN_SCHEMA_VERSION,
                    "status": "configuration_invalid",
                    "real_calls_made": 0,
                    "error_code": "real_execution_requires_explicit_config",
                },
                args.output,
            )
            return 2
        config = ExecutionConfig(
            cast(str, args.course_id),
            cast(str, args.teacher_user_id),
            cast(str, args.student_user_id),
            tuple(args.agent_id),
            tuple(args.agent_version_id),
            args.timeout_seconds,
            args.poll_interval_seconds,
            args.group_id,
            args.corpus_path,
        )
        _validate_config(sessions, config)
        runner = NextWaveRealSessionRunner(
            bundle,
            transport_factory=lambda _role: HttpTransport(
                cast(str, args.base_url),
                timeout_seconds=min(30.0, args.timeout_seconds),
            ),
        )
        result = runner.execute(
            sessions,
            config,
            resume_debug_debate_id=args.resume_debug_debate_id,
        )
        _write_output(result, args.output)
        # API completion intentionally remains non-zero until the separate
        # browser/3D/TTS evidence exists; this cannot be mistaken for the
        # frozen full acceptance gate.
        return (
            2 if result["status"] == "api_flow_complete_pending_browser_review" else 1
        )
    except FixtureValidationError as exc:
        _write_output(
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "status": "fixtures_invalid",
                "real_calls_made": 0,
                "error_codes": list(
                    dict.fromkeys(exc.codes or ("fixture_validation_failed",))
                ),
            },
            args.output,
        )
        return 1
    except RunnerFailure as exc:
        _write_output(
            {
                "schema_version": RUN_SCHEMA_VERSION,
                "status": "configuration_invalid"
                if not args.execute_real
                else "real_failed",
                "real_calls_made": 0,
                "error_code": exc.code,
            },
            args.output,
        )
        return (
            2
            if exc.code.startswith(
                ("configuration", "selection", "agent_", "identity", "version_")
            )
            else 1
        )


if __name__ == "__main__":
    raise SystemExit(main())
