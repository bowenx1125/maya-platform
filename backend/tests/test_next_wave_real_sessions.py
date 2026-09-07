"""Transport-fake checks for the bounded Next Wave HTTP runner."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from next_wave_real_sessions import (  # noqa: E402, I001
    ExecutionConfig,
    NextWaveRealSessionRunner,
    RunnerFailure,
    WireResponse,
    _preview_poll,
    dry_run,
    select_sessions,
)
from tests.fixtures.next_wave_rag import load_fixture_bundle  # noqa: E402


def _uuid() -> str:
    return str(uuid4())


class FakeSocket:
    def __init__(self, transport: FakeTransport) -> None:
        self.transport = transport
        self.messages: list[dict[str, object]] = [
            {
                "event_type": "snapshot",
                "payload": {
                    "playback": {
                        "control_version": transport.control_version,
                    }
                },
            }
        ]
        self.closed = False

    def send(self, data: str) -> None:
        command = json.loads(data)
        self.transport.ws_commands.append(command)
        command_type = command["command_type"]
        if command_type == "playback.controller.acquire":
            self.messages.append(
                {
                    "message_type": "controller.acquired",
                    "controller_epoch": self.transport.epoch,
                    "control_version": self.transport.control_version,
                }
            )
            return
        turn_id = str(command.get("turn_id"))
        if command_type == "playback.media.prepare":
            self.messages.append(
                {
                    "message_type": "media.prepared",
                    "media_url": (
                        f"/api/v1/debates/{self.transport.debate_id}/audio/{turn_id}"
                        f"?media_ticket={'T' * 43}"
                    ),
                }
            )
        elif command_type == "playback.started_ack":
            reply = "B1" if turn_id in self.transport.final_turn_ids else None
            self.messages.append(
                {
                    "event_type": "playback.started",
                    "payload": {
                        "turn_id": turn_id,
                        "speech": "A synthetic public speech.",
                        "sources": [],
                        "segment_turn": {
                            "schema_version": "segment_turn_v2",
                            "segments": [
                                {
                                    "text": "A synthetic paragraph.",
                                    "source_ids": [],
                                    "reply_to": reply,
                                }
                            ],
                        },
                    },
                }
            )
        elif command_type == "playback.ended_ack":
            self.transport.control_version += 1
            self.messages.append(
                {
                    "event_type": "playback.completed",
                    "payload": {
                        "turn_id": turn_id,
                        "control_version": self.transport.control_version,
                    },
                }
            )
            if turn_id != self.transport.final_turn_ids[-1]:
                self.transport.waiting_for_next = True
                delayed = turn_id in self.transport.delayed_waiting_turn_ids
                self.transport.rest_next_ready = not delayed
                self.transport.waiting_event_history.append((turn_id, False if delayed else True))
                if delayed:
                    self.messages.append(
                        {
                            "event_type": "playback.waiting_next",
                            "payload": {
                                "completed_turn_id": turn_id,
                                "control_version": self.transport.control_version,
                                "mode": "live",
                                "next_turn_ready": False,
                            },
                        }
                    )
                self.messages.append(
                    {
                        "event_type": "playback.waiting_next",
                        "payload": {
                            "completed_turn_id": turn_id,
                            "control_version": self.transport.control_version,
                            "mode": "live",
                            "next_turn_ready": True,
                        },
                    }
                )
                if delayed:
                    self.transport.waiting_event_history.append((turn_id, True))
            else:
                self.transport.debate_status = "debate_finished"
                self.transport.waiting_for_next = False
                self.transport.rest_next_ready = False

    def recv(self, timeout: float | None = None) -> str:
        del timeout
        if not self.messages:
            raise TimeoutError("fake WebSocket queue exhausted")
        message = self.messages.pop(0)
        if message.get("event_type") == "playback.waiting_next":
            payload = message.get("payload")
            if (
                isinstance(payload, Mapping)
                and payload.get("next_turn_ready") is True
                and payload.get("completed_turn_id") == self.transport.current_turn_id
            ):
                self.transport.rest_next_ready = True
        return json.dumps(message)

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, role: str, agent_ids: tuple[str, ...]) -> None:
        self.role = role
        self.agent_ids = agent_ids
        self.debate_id = _uuid()
        self.pre_turn_ids = [_uuid(), _uuid()]
        self.final_turn_ids = [_uuid(), _uuid()]
        self.current_turn_id = self.pre_turn_ids[0]
        self.control_version = 0
        self.epoch = _uuid()
        self.debate_status = "running"
        self.calls: list[tuple[str, str, object | None]] = []
        self.ws_commands: list[dict[str, object]] = []
        self.barrages: list[dict[str, object]] = []
        self.report_ready = False
        self.closed = False
        self.peer: FakeTransport | None = None
        self.waiting_for_next = False
        self.rest_next_ready = False
        self.delayed_waiting_turn_ids: set[str] = set()
        self.waiting_event_history: list[tuple[str, bool]] = []

    def quick_login(self, user_id: str) -> Mapping[str, object]:
        self.calls.append(("quick-login", self.role, user_id))
        return {"user": {"id": user_id}, "csrf_token": "C" * 32}

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
        del idempotency_key, csrf
        self.calls.append((method, path, payload))
        if self.role == "student":
            if self.peer is not None:
                self.current_turn_id = self.peer.current_turn_id
            return self._student(method, path, payload, raw)
        return self._teacher(method, path, payload, raw)

    def _student(self, method: str, path: str, payload: object | None, raw: bool) -> WireResponse:
        if method == "GET" and "/classroom-interactions/" in path:
            return WireResponse(
                200,
                {
                    "topic": "Synthetic",
                    "participants": [],
                    "current_turn_id": self.current_turn_id,
                    "barrage_open": True,
                },
                {},
            )
        if method == "POST" and path.endswith("/barrages"):
            assert isinstance(payload, dict)
            self.barrages.append(payload)
            if self.peer is not None:
                self.peer.barrages.append(payload)
            return WireResponse(201, {"barrage_submitted": True}, {})
        raise AssertionError(f"unexpected student call {method} {path} {raw}")

    def _teacher(self, method: str, path: str, payload: object | None, raw: bool) -> WireResponse:
        if method == "GET" and path.endswith("/published-agents"):
            rows = [
                {
                    "agent": {"id": agent_id},
                    "current_version": {
                        "id": _uuid(),
                        "agent_id": agent_id,
                        "state": "published",
                        "persona_compiler_version": "persona_template_v2",
                        "knowledge_snapshot_id": _uuid(),
                    },
                }
                for agent_id in self.agent_ids
            ]
            return WireResponse(200, rows, {})
        if method == "POST" and path.endswith("/debates"):
            return WireResponse(201, self.detail("draft"), {})
        if method == "GET" and path.endswith("self.debate_id"):
            return WireResponse(200, self.detail(self.debate_status), {})
        if method == "GET" and path == f"/api/v1/debates/{self.debate_id}":
            return WireResponse(200, self.detail(self.debate_status), {})
        if method == "POST" and path.endswith("/start"):
            self.debate_status = "running"
            return WireResponse(200, self.detail("running"), {})
        if method == "POST" and path.endswith("/interaction/open"):
            return WireResponse(
                200,
                {
                    "status": "open",
                    "public_url": "http://classroom.test/classroom/v1." + "A" * 64 + "." + "B" * 43,
                    "votes": [],
                    "barrages": [],
                },
                {},
            )
        if method == "POST" and path.endswith("/final-input"):
            self.waiting_for_next = True
            self.rest_next_ready = True
            return WireResponse(
                200,
                {
                    "ready": True,
                    "barrage_count": len(self.barrages),
                    "cutoff_sequence": len(self.barrages),
                },
                {},
            )
        if method == "POST" and path.endswith("/next"):
            assert isinstance(payload, dict)
            assert self.waiting_for_next and self.rest_next_ready, "next_before_ready"
            expected = payload["expected_current_turn_id"]
            if expected == self.pre_turn_ids[0]:
                self.current_turn_id = self.pre_turn_ids[1]
            elif expected == self.pre_turn_ids[1]:
                self.current_turn_id = self.final_turn_ids[0]
            elif expected == self.final_turn_ids[0]:
                self.current_turn_id = self.final_turn_ids[1]
            else:
                raise AssertionError(f"unexpected next predecessor {expected}")
            self.waiting_for_next = False
            self.rest_next_ready = False
            self.control_version += 1
            return WireResponse(200, self.playback(), {})
        if method == "GET" and path.endswith("/interaction"):
            status = "finalized" if self.debate_status == "completed" else "open"
            public_url = (
                "http://classroom.test/classroom/v1." + "A" * 64 + "." + "B" * 43
                if status == "open"
                else None
            )
            return WireResponse(
                200,
                {"status": status, "public_url": public_url, "votes": [], "barrages": []},
                {},
            )
        if method == "POST" and path.endswith("/interaction/close"):
            self.debate_status = "completed"
            return WireResponse(
                202, {"status": "finalized", "public_url": None, "votes": [], "barrages": []}, {}
            )
        if method == "POST" and path.endswith("/report/generate"):
            return WireResponse(
                202,
                {
                    "generation_status": "generating",
                    "latest_attempt_status": "generating",
                    "insight": {},
                },
                {},
            )
        if method == "GET" and path.endswith("/report"):
            self.report_ready = True
            return WireResponse(
                200,
                {"generation_status": "ready", "latest_attempt_status": "ready", "insight": {}},
                {},
            )
        if method == "GET" and path.endswith("/report/download?language=en"):
            return WireResponse(200, None, {"content-type": "text/markdown"}, 32 if raw else None)
        if method == "GET" and "/audio/" in path:
            return WireResponse(200, None, {"content-type": "audio/wav"}, 8 if raw else None)
        raise AssertionError(f"unexpected teacher call {method} {path}")

    def detail(self, status: str) -> dict[str, object]:
        preview = [
            {
                "id": self.pre_turn_ids[0],
                "round_no": 1,
                "turn_index": 0,
                "speech": "Preview A",
                "generation_status": "final_ready",
                "audio_ready": True,
            },
            {
                "id": self.pre_turn_ids[1],
                "round_no": 1,
                "turn_index": 1,
                "speech": "Preview B",
                "generation_status": "final_ready",
                "audio_ready": True,
            },
        ]
        playback_status = "completed" if status in {"debate_finished", "completed"} else "ready"
        if self.waiting_for_next and status == "running":
            playback_status = "waiting_next"
        return {
            "id": self.debate_id,
            "turn_protocol": "segments_v2",
            "output_language": "en",
            "round_count": 2,
            "revision": 0,
            "participants": [
                {
                    "agent_id": agent_id,
                    "agent_version_id": _uuid(),
                    "knowledge_snapshot_id": _uuid(),
                }
                for agent_id in self.agent_ids
            ],
            "preview": {"prepared_turns": 2, "expected_turns": 2, "ready": True},
            "preview_turns": preview,
            "playback": self.playback(status, playback_status),
            "status": status,
        }

    def playback(
        self, status: str = "running", playback_status: str = "ready"
    ) -> dict[str, object]:
        return {
            "status": playback_status,
            "mode": "live",
            "current_turn_id": self.current_turn_id,
            "cursor_ms": 0,
            "playback_rate": 1.0,
            "control_version": self.control_version,
            "next_turn_ready": self.waiting_for_next
            and self.rest_next_ready
            and status == "running",
        }

    def open_events(self, path: str) -> FakeSocket:
        assert path.endswith(f"/debates/{self.debate_id}/events")
        return FakeSocket(self)

    def close(self) -> None:
        self.closed = True


class PreviewClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class SequentialPreviewTransport:
    def __init__(self, clock: PreviewClock) -> None:
        self.clock = clock
        self.turn_ids = [_uuid(), _uuid(), _uuid()]

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
        del path, payload, idempotency_key, csrf, raw
        assert method == "GET"
        elapsed = self.clock.monotonic()
        rows: list[dict[str, object]] = []
        for index, turn_id in enumerate(self.turn_ids):
            if elapsed < 90 * index:
                status = "pending"
                audio_ready = False
            elif elapsed < 90 * (index + 1):
                status = "running"
                audio_ready = False
            else:
                status = "final_ready"
                audio_ready = True
            rows.append(
                {
                    "id": turn_id,
                    "round_no": 1,
                    "turn_index": index,
                    "speech": f"Preview {index}",
                    "generation_status": status,
                    "audio_ready": audio_ready,
                }
            )
        ready_count = sum(bool(row["audio_ready"]) for row in rows)
        return WireResponse(
            200,
            {
                "preview": {
                    "prepared_turns": ready_count,
                    "expected_turns": len(rows),
                    "ready": ready_count == len(rows),
                },
                "preview_turns": rows,
            },
            {},
        )

    def open_events(self, path: str) -> Any:
        raise AssertionError(f"unexpected WebSocket call {path}")

    def close(self) -> None:
        pass


def test_preview_allows_sequential_turns_over_180_seconds() -> None:
    clock = PreviewClock()
    result = _preview_poll(
        SequentialPreviewTransport(clock),
        "/api/v1/debates/synthetic",
        expected=3,
        poll_interval_seconds=30,
        clock=clock.monotonic,
        sleeper=clock.sleep,
    )
    overall_ms = result.audit["overall_wall_ms"]
    turn_timeout_ms = result.audit["turn_timeout_ms"]
    assert overall_ms == 270_000
    assert isinstance(overall_ms, int) and isinstance(turn_timeout_ms, int)
    assert overall_ms > turn_timeout_ms
    assert result.audit["poll_resolution_ms"] == 30_000
    turns = result.audit["turns"]
    assert isinstance(turns, list) and len(turns) == 3
    assert [row["latency_ms"] for row in turns] == [90_000, 90_000, 90_000]
    assert all(row["latency_basis"] == "running_to_audio_ready" for row in turns)
    assert all(len(row["status_progress"]) >= 2 for row in turns)


def test_dry_run_uses_frozen_matrix_without_transport() -> None:
    bundle = load_fixture_bundle()
    sessions = select_sessions(bundle, debug_2x2=True)
    plan = dry_run(bundle, sessions)
    assert plan["status"] == "dry_run"
    assert plan["sessions_expected"] == 1
    assert plan["turns_expected"] == 4
    assert plan["real_calls_made"] == 0


def test_fake_transport_drives_http_ws_cas_and_report() -> None:
    bundle = load_fixture_bundle()
    sessions = select_sessions(bundle, debug_2x2=True)
    agent_ids = tuple(_uuid() for _ in range(2))
    transports: dict[str, FakeTransport] = {}

    def factory(role: str) -> FakeTransport:
        transports[role] = FakeTransport(role, agent_ids)
        if role == "teacher":
            # Model the real slow successor path: Final-1 first reports
            # waiting_next=false and only later reports readiness.
            transports[role].delayed_waiting_turn_ids.add(transports[role].final_turn_ids[0])
        if role == "student" and "teacher" in transports:
            transports[role].peer = transports["teacher"]
        return transports[role]

    runner = NextWaveRealSessionRunner(bundle, transport_factory=factory, run_id=_uuid())
    result = runner.execute(
        sessions,
        ExecutionConfig(
            _uuid(), _uuid(), _uuid(), agent_ids, timeout_seconds=0.2, poll_interval_seconds=0
        ),
    )
    assert result["status"] == "api_flow_complete_pending_browser_review"
    reports = result["reports"]
    assert isinstance(reports, list)
    report = reports[0]
    assert isinstance(report, Mapping)
    assert report["status"] == "api_flow_complete_pending_browser_review"
    assert report["observed"]["turns"] == 4
    assert report["observed"]["audio_fetches"] == 4
    assert len(report["observed"]["turn_wall_ms"]) == 4
    assert report["observed"]["provider_attempts"] == "unavailable"
    preview_progress = report["preview_progress"]
    assert isinstance(preview_progress, Mapping)
    assert preview_progress["turn_timeout_ms"] == 180_000
    assert len(preview_progress["turns"]) == 2
    assert report["conclude_action"] == "natural_completion+interaction_close"
    assert report["provider_evidence"]["tts"] == "unavailable"
    assert report["provider_evidence"]["three_d_browser"] == "unavailable"
    assert len(transports["student"].barrages) == 1
    assert transports["teacher"].closed and transports["student"].closed
    assert (transports["teacher"].final_turn_ids[0], False) in transports[
        "teacher"
    ].waiting_event_history
    assert (transports["teacher"].final_turn_ids[0], True) in transports[
        "teacher"
    ].waiting_event_history
    assert not any(call[1] == "retry" for call in transports["teacher"].calls)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "media_ticket" not in serialized
    assert "raw_text" not in serialized


def test_acceptance_unknown_stops_setup_without_claiming_success() -> None:
    bundle = load_fixture_bundle()
    sessions = select_sessions(bundle, debug_2x2=True)

    class UnknownTransport(FakeTransport):
        def request(self, method: str, path: str, **kwargs: Any) -> WireResponse:
            if method == "GET" and path.endswith("/published-agents"):
                raise RunnerFailure("acceptance_unknown")
            return super().request(method, path, **kwargs)

    ids = tuple(_uuid() for _ in range(2))
    result = NextWaveRealSessionRunner(
        bundle,
        transport_factory=lambda role: UnknownTransport(role, ids),
        run_id=_uuid(),
    ).execute(
        sessions,
        ExecutionConfig(
            _uuid(), _uuid(), _uuid(), ids, timeout_seconds=0.1, poll_interval_seconds=0
        ),
    )
    assert result["status"] == "acceptance_unknown"
    assert result["sessions_observed"] == 0
    assert result["stopped_reason"] == "acceptance_unknown"


def test_debug_resume_reuses_started_debate_without_create_or_start() -> None:
    bundle = load_fixture_bundle()
    sessions = select_sessions(bundle, debug_2x2=True)
    ids = tuple(_uuid() for _ in range(2))
    teacher = FakeTransport("teacher", ids)
    student = FakeTransport("student", ids)
    student.peer = teacher
    transports = {"teacher": teacher, "student": student}
    result = NextWaveRealSessionRunner(
        bundle,
        transport_factory=lambda role: transports[role],
        run_id=_uuid(),
    ).execute(
        sessions,
        ExecutionConfig(
            _uuid(), _uuid(), _uuid(), ids, timeout_seconds=0.2, poll_interval_seconds=0
        ),
        resume_debug_debate_id=teacher.debate_id,
    )
    assert result["status"] == "api_flow_complete_pending_browser_review"
    reports = result["reports"]
    assert isinstance(reports, list) and isinstance(reports[0], Mapping)
    assert reports[0]["resumed_debug"] is True
    mutation_paths = [path for method, path, _payload in teacher.calls if method == "POST"]
    assert not any(path.endswith("/debates") for path in mutation_paths)
    assert not any(path.endswith("/start") for path in mutation_paths)
    assert not any(path.endswith("/interaction/open") for path in mutation_paths)
