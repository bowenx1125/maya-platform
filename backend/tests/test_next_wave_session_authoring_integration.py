"""Focused checks for wiring fresh Agent authoring into the HTTP runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from next_wave_real_sessions import (  # noqa: E402
    ExecutionConfig,
    HttpTransport,
    NextWaveRealSessionRunner,
    PlaybackController,
    RunnerFailure,
    SessionSpec,
    WireResponse,
)
from next_wave_session_authoring import (  # noqa: E402
    PERSONA_COMPILER_VERSION,
    AuthoringFailure,
    author_session_agents,
)

GROUP_ID = "11111111-1111-4111-8111-111111111111"
CORPUS = b"# Correct fixture\n\nA bounded synthetic knowledge source.\n"
VALID_COMPOSITION = {
    "components": [
        {"key": "embedding", "mode": "real", "policy_unreviewed": False},
        {"key": "llm", "mode": "real", "policy_unreviewed": False},
        {"key": "report", "mode": "real", "policy_unreviewed": False},
        {"key": "tts", "mode": "mock", "policy_unreviewed": False},
        {"key": "voice", "mode": "mock", "policy_unreviewed": False},
    ]
}


@dataclass
class _Version:
    agent_id: str
    version_id: str
    revision: int = 0
    snapshot_id: str = ""


class _AuthoringTransport:
    """Public-route fake used to inspect the authoring seam, without HTTP."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.versions: dict[str, _Version] = {}

    @staticmethod
    def _version(state: _Version, *, published: bool = False) -> dict[str, object]:
        if published and not state.snapshot_id:
            state.snapshot_id = str(uuid4())
        return {
            "id": state.version_id,
            "agent_id": state.agent_id,
            "state": "published" if published else "draft",
            "revision": state.revision,
            "persona_confirmed": published,
            "knowledge_snapshot_id": state.snapshot_id if published else None,
        }

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
        del csrf, raw
        self.calls.append(
            {
                "kind": "request",
                "method": method,
                "path": path,
                "payload": payload,
                "idempotency_key": idempotency_key,
            }
        )
        if method == "POST" and path.endswith("/agents"):
            agent_id, version_id = str(uuid4()), str(uuid4())
            state = _Version(agent_id, version_id)
            self.versions[version_id] = state
            return WireResponse(201, {"id": agent_id, "versions": [self._version(state)]}, {})
        version_id = path.split("/agent-versions/", 1)[1].split("/", 1)[0]
        state = self.versions[version_id]
        if method == "PATCH":
            assert isinstance(payload, dict)
            state.revision = int(payload["expected_revision"]) + 1
            return WireResponse(200, self._version(state), {})
        if method == "POST" and path.endswith("/persona/compile"):
            assert isinstance(payload, dict)
            assert payload["expected_revision"] == state.revision
            return WireResponse(
                200,
                {
                    "version_id": version_id,
                    "revision": state.revision,
                    "compiled": True,
                    "raw_agent_md_hash": "sha256:" + "c" * 64,
                    "persona_spec_hash": "d" * 64,
                    "compiler_version": PERSONA_COMPILER_VERSION,
                    "persona_spec": {"schema_version": "persona_spec_v2"},
                },
                {},
            )
        if method == "POST" and path.endswith("/persona/confirm"):
            assert isinstance(payload, dict)
            assert payload["expected_revision"] == state.revision
            return WireResponse(200, {**self._version(state), "persona_confirmed": True}, {})
        if method == "POST" and path.endswith("/publish"):
            assert isinstance(payload, dict)
            assert payload["expected_revision"] == state.revision
            return WireResponse(200, self._version(state, published=True), {})
        raise AssertionError(f"unexpected route {method} {path}")

    def request_multipart(
        self,
        method: str,
        path: str,
        *,
        fields: dict[str, str],
        file_name: str,
        file_content: bytes,
        content_type: str,
        idempotency_key: str | None = None,
        csrf: bool = True,
    ) -> WireResponse:
        del csrf
        self.calls.append(
            {
                "kind": "multipart",
                "method": method,
                "path": path,
                "fields": dict(fields),
                "file_name": file_name,
                "file_content": file_content,
                "content_type": content_type,
                "idempotency_key": idempotency_key,
            }
        )
        version_id = fields["target_agent_version_id"]
        state = self.versions[version_id]
        assert fields["expected_revision"] == str(state.revision)
        state.revision += 1
        return WireResponse(
            201,
            {
                "document": {"id": str(uuid4()), "index_status": "ready"},
                "agent_version": self._version(state),
            },
            {},
        )


class _CompositionTransport:
    def __init__(self, composition: dict[str, object]) -> None:
        self.composition = composition
        self.composition_requests = 0
        self.closed = False

    def quick_login(self, user_id: str) -> dict[str, object]:
        return {"user": {"id": user_id}}

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
        del payload, idempotency_key, csrf, raw
        if method == "GET" and path == "/api/v1/demo/composition":
            self.composition_requests += 1
            return WireResponse(200, self.composition, {})
        raise AssertionError(f"unexpected route {method} {path}")

    def close(self) -> None:
        self.closed = True


def test_cli_namespace_import_and_authoring_response_keys() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(SCRIPTS), str(REPO_ROOT / "backend")))
    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from next_wave_session_authoring import author_session_agents; "
                "print(author_session_agents.__name__)"
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert imported.stdout.strip() == "author_session_agents"

    transport = _AuthoringTransport()
    result = author_session_agents(
        SimpleNamespace(session_id="integration-shape-a2", agent_count=2),
        transport,
        group_id=GROUP_ID,
        corpus_bytes=CORPUS,
    )
    assert "version_ids" in result
    assert result["version_ids"] == [item["version_id"] for item in result["agents"]]
    assert result["snapshot_ids"] == [item["snapshot_id"] for item in result["agents"]]
    assert all(item["state"] == "published" for item in result["agents"])


def test_authoring_multipart_preserves_bytes_content_type_and_dynamic_revision() -> None:
    transport = _AuthoringTransport()
    author_session_agents(
        SimpleNamespace(session_id="multipart-a2", agent_count=2),
        student_transport=transport,
        group_id=GROUP_ID,
        corpus_path=None,
        corpus=CORPUS,
    )
    uploads = [item for item in transport.calls if item["kind"] == "multipart"]
    assert len(uploads) == 2
    assert all(item["file_content"] == CORPUS for item in uploads)
    assert all(item["content_type"] == "text/markdown" for item in uploads)
    assert all(item["fields"]["expected_revision"] == "1" for item in uploads)
    compile_payloads = [
        item["payload"]
        for item in transport.calls
        if item["kind"] == "request" and item["path"].endswith("/persona/compile")
    ]
    assert all(payload["expected_revision"] == 2 for payload in compile_payloads)


def test_runner_preserves_partial_audit_and_stops_real_cases_after_authoring_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import next_wave_session_authoring as authoring_module

    captured: dict[str, object] = {}

    def fail_authoring(spec: object, **kwargs: object) -> dict[str, object]:
        captured["session_id"] = getattr(spec, "session_id", None)
        captured.update(kwargs)
        raise AuthoringFailure(
            "provider_unavailable",
            stage="slot_1.knowledge_upload",
            steps=(
                {
                    "stage": "slot_1.create",
                    "status": "passed",
                    "wall_ms": 1,
                },
                {
                    "stage": "slot_1.knowledge_upload",
                    "status": "failed",
                    "wall_ms": 2,
                    "error_code": "provider_unavailable",
                },
            ),
        )

    monkeypatch.setattr(authoring_module, "author_session_agents", fail_authoring)

    class _QuickTransport:
        def __init__(self, composition: dict[str, object] | None = None) -> None:
            self.calls: list[str] = []
            self.closed = False
            self.composition = composition or VALID_COMPOSITION
            self.composition_requests = 0

        def quick_login(self, user_id: str) -> dict[str, object]:
            self.calls.append(f"login:{user_id}")
            return {"user": {"id": user_id}}

        def request(self, method: str, path: str, **kwargs: object) -> WireResponse:
            del kwargs
            self.calls.append(f"{method}:{path}")
            if method == "GET" and path == "/api/v1/demo/composition":
                self.composition_requests += 1
                return WireResponse(200, self.composition, {})
            raise AssertionError("debate route must not run after authoring failure")

        def open_events(self, path: str) -> object:
            raise AssertionError(f"unexpected WebSocket {path}")

        def close(self) -> None:
            self.closed = True

    transports: dict[str, _QuickTransport] = {}

    def factory(role: str) -> _QuickTransport:
        transports[role] = _QuickTransport()
        return transports[role]

    bundle = SimpleNamespace(fixture_hash="fixture-hash")
    runner = NextWaveRealSessionRunner(bundle, transport_factory=factory, run_id="integration-run")
    first = SessionSpec("fresh-01", "fresh", "en", 2, 2, 4, "without_barrage", (), (), 0)
    second = SessionSpec("fresh-02", "fresh", "en", 2, 2, 4, "without_barrage", (), (), 0)
    config = ExecutionConfig(
        "22222222-2222-4222-8222-222222222222",
        "teacher-user",
        "student-user",
        (),
        (),
        1,
        0,
        GROUP_ID,
        Path("/private/fixture/correct.md"),
    )

    summary = runner.execute((first, second), config)

    assert captured["session_id"] == "fresh-01"
    assert captured["group_id"] == GROUP_ID
    assert captured["corpus"] == Path("/private/fixture/correct.md")
    assert transports["teacher"].composition_requests == 1
    assert transports["student"].composition_requests == 0
    assert summary["status"] == "real_failed"
    assert summary["sessions_observed"] == 1
    assert summary["stopped_reason"] == "provider_unavailable"
    report = summary["reports"][0]
    assert report["status"] == "failed"
    assert report["composition_modes"] == {
        "embedding": "real",
        "llm": "real",
        "report": "real",
        "tts": "mock",
        "voice": "mock",
    }
    assert report["provider_evidence"]["tts"] == "mock"
    assert report["provider_evidence"]["voice"] == "mock"
    assert report["agent_authoring"] == {
        "status": "failed",
        "error_code": "provider_unavailable",
        "stage": "slot_1.knowledge_upload",
        "steps": [
            {"stage": "slot_1.create", "status": "passed", "wall_ms": 1},
            {
                "stage": "slot_1.knowledge_upload",
                "status": "failed",
                "wall_ms": 2,
                "error_code": "provider_unavailable",
            },
        ],
    }
    assert all(not any("/debates" in call for call in item.calls) for item in transports.values())
    assert all(item.closed for item in transports.values())


@pytest.mark.parametrize(
    ("changed", "expected_code"),
    [
        ({"embedding": {"mode": "mock"}}, "composition_real_required"),
        ({"llm": {"policy_unreviewed": True}}, "composition_policy_unreviewed"),
        ({"tts": {"mode": "real"}}, "composition_mock_required"),
    ],
)
def test_fresh_composition_preflight_requires_closed_real_mock_modes(
    changed: dict[str, dict[str, object]], expected_code: str
) -> None:
    composition = {"components": [dict(item) for item in VALID_COMPOSITION["components"]]}
    by_key = {item["key"]: item for item in composition["components"]}
    for key, values in changed.items():
        by_key[key].update(values)
    teacher = _CompositionTransport(composition)
    student = _CompositionTransport(composition)
    transports = {"teacher": teacher, "student": student}

    def factory(role: str) -> _CompositionTransport:
        return transports[role]

    runner = NextWaveRealSessionRunner(
        SimpleNamespace(fixture_hash="composition-fixture"),
        transport_factory=factory,
        run_id="composition-run",
    )
    spec = SessionSpec("fresh-composition", "fresh", "en", 2, 2, 4, "without_barrage", (), (), 0)
    config = ExecutionConfig(
        "22222222-2222-4222-8222-222222222222",
        "teacher-user",
        "student-user",
        (),
        (),
        1,
        0,
        GROUP_ID,
        None,
    )

    summary = runner.execute((spec,), config)

    assert summary["status"] == "real_failed"
    assert summary["sessions_observed"] == 0
    assert summary["stopped_reason"] == expected_code
    assert teacher.composition_requests == 1
    assert student.composition_requests == 0
    assert teacher.closed and student.closed


def test_legacy_debug_config_does_not_call_demo_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import next_wave_real_sessions as runner_module

    teacher = _CompositionTransport(VALID_COMPOSITION)
    student = _CompositionTransport(VALID_COMPOSITION)
    transports = {"teacher": teacher, "student": student}

    def factory(role: str) -> _CompositionTransport:
        return transports[role]

    monkeypatch.setattr(runner_module, "_validate_agents", lambda _transport, _config: None)

    def stop_case(
        _runner: NextWaveRealSessionRunner,
        _spec: SessionSpec,
        _config: ExecutionConfig,
        _teacher: object,
        _student: object,
        **_kwargs: object,
    ) -> dict[str, object]:
        return {"status": "failed", "error_code": "legacy_stop"}

    monkeypatch.setattr(NextWaveRealSessionRunner, "_run_case", stop_case)
    runner = NextWaveRealSessionRunner(
        SimpleNamespace(fixture_hash="legacy-fixture"),
        transport_factory=factory,
        run_id="legacy-run",
    )
    spec = SessionSpec("legacy-debug", "fresh", "en", 2, 2, 4, "without_barrage", (), (), 0)
    config = ExecutionConfig(
        "22222222-2222-4222-8222-222222222222",
        "teacher-user",
        "student-user",
        (
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
        ),
        (),
        1,
        0,
    )

    summary = runner.execute((spec,), config)

    assert summary["status"] == "real_failed"
    assert teacher.composition_requests == 0
    assert student.composition_requests == 0


class _GradeSocket:
    def __init__(
        self,
        debate_id: str,
        turn_id: str,
        support_mode: str | None,
        source_ids: list[str],
    ) -> None:
        self.debate_id = debate_id
        self.turn_id = turn_id
        self.support_mode = support_mode
        self.source_ids = source_ids
        self.messages: list[dict[str, object]] = [
            {"event_type": "snapshot", "payload": {"playback": {"control_version": 0}}}
        ]

    def send(self, data: str) -> None:
        command = json.loads(data)
        command_type = command["command_type"]
        if command_type == "playback.controller.acquire":
            self.messages.append(
                {
                    "message_type": "controller.acquired",
                    "controller_epoch": str(uuid4()),
                    "control_version": 0,
                }
            )
        elif command_type == "playback.media.prepare":
            self.messages.append(
                {
                    "message_type": "media.prepared",
                    "media_url": (
                        f"/api/v1/debates/{self.debate_id}/audio/{self.turn_id}"
                        f"?media_ticket={'T' * 43}"
                    ),
                }
            )
        elif command_type == "playback.started_ack":
            segment: dict[str, object] = {
                "text": "A paragraph",
                "source_ids": self.source_ids,
                "reply_to": None,
            }
            if self.support_mode is not None:
                segment["support_mode"] = self.support_mode
            self.messages.append(
                {
                    "event_type": "playback.started",
                    "payload": {
                        "speech": "A speech",
                        "sources": [],
                        "segment_turn": {
                            "schema_version": "segment_turn_v2",
                            "segments": [segment],
                        },
                    },
                }
            )
        elif command_type == "playback.ended_ack":
            self.messages.append(
                {
                    "event_type": "playback.completed",
                    "payload": {"control_version": 1},
                }
            )

    def recv(self, timeout: float | None = None) -> str:
        del timeout
        if not self.messages:
            raise TimeoutError("grade fake queue exhausted")
        return json.dumps(self.messages.pop(0))

    def close(self) -> None:
        pass


class _GradeTransport:
    def request(self, method: str, path: str, **kwargs: object) -> WireResponse:
        del method, path, kwargs
        return WireResponse(200, None, {}, 8)


@pytest.mark.parametrize(
    ("support_mode", "source_ids", "expected_code"),
    [
        (None, ["S1"], "segment_grade_missing"),
        ("direct", [], "segment_grade_source_mismatch"),
        ("no_match", ["S1"], "segment_grade_source_mismatch"),
        ("contextual", ["S1"], None),
    ],
)
def test_fresh_playback_grade_gate_checks_mode_and_source_shape(
    support_mode: str | None, source_ids: list[str], expected_code: str | None
) -> None:
    debate_id, turn_id = str(uuid4()), str(uuid4())
    socket = _GradeSocket(debate_id, turn_id, support_mode, source_ids)
    controller = PlaybackController(
        _GradeTransport(),
        socket,
        debate_id=debate_id,
        timeout_seconds=1,
        require_grades=True,
    )
    epoch, version = controller.acquire(0)
    if expected_code is None:
        controller.play_one(
            turn_id=turn_id,
            expected_control_version=version,
            epoch=epoch,
            action="start",
        )
    else:
        with pytest.raises(RunnerFailure) as raised:
            controller.play_one(
                turn_id=turn_id,
                expected_control_version=version,
                epoch=epoch,
                action="start",
            )
        assert raised.value.code == expected_code


def test_playback_default_keeps_legacy_ungraded_reads_compatible() -> None:
    debate_id, turn_id = str(uuid4()), str(uuid4())
    socket = _GradeSocket(debate_id, turn_id, None, ["S1"])
    controller = PlaybackController(
        _GradeTransport(), socket, debate_id=debate_id, timeout_seconds=1
    )
    epoch, version = controller.acquire(0)
    controller.play_one(
        turn_id=turn_id,
        expected_control_version=version,
        epoch=epoch,
        action="start",
    )


def test_http_transport_emits_real_multipart_body_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(variable, raising=False)

    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(201, json={"ok": True}, request=request)

    transport = HttpTransport("http://testserver")
    transport._client.close()
    transport._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://testserver",
    )
    transport._csrf_token = "C" * 32
    try:
        result = transport.request_multipart(
            "POST",
            "/api/v1/groups/" + GROUP_ID + "/knowledge-documents",
            fields={
                "target_agent_version_id": "33333333-3333-4333-8333-333333333333",
                "expected_revision": "1",
            },
            file_name="correct.md",
            file_content=CORPUS,
            content_type="text/markdown",
            idempotency_key="multipart-integration-key",
        )
    finally:
        transport.close()

    request = captured["request"]
    body = request.content
    assert result.status_code == 201
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert request.headers["x-csrf-token"] == "C" * 32
    assert request.headers["idempotency-key"] == "multipart-integration-key"
    assert b'name="target_agent_version_id"' in body
    assert b'name="expected_revision"' in body
    assert b'filename="correct.md"' in body
    assert b"Content-Type: text/markdown" in body
    assert CORPUS in body
