"""Unit checks for the isolated Next Wave Agent authoring seam."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from app.modules.agents.persona import compile_persona_v2  # noqa: E402
from next_wave_session_authoring import (  # noqa: E402
    AuthoringFailure,
    author_session_agents,
)

GROUP_ID = "11111111-1111-4111-8111-111111111111"
CORPUS = b"# Correct fixture\n\nThe spring council records a shared water rule.\n"
MANIFEST_HASH = "a" * 64
POLICY_HASH = "b" * 64


@dataclass
class Response:
    status_code: int
    data: object | None


@dataclass
class VersionState:
    agent_id: str
    version_id: str
    revision: int = 0
    document_id: str = ""
    snapshot_id: str = ""


class FakeAuthorTransport:
    """A deterministic public-route fake; it has no application/database access."""

    def __init__(
        self,
        *,
        role: str = "student",
        require_teacher_confirmation: bool = False,
        fail_path: str | None = None,
        unknown_publish: bool = False,
        nonzero_confirmation_send: bool = False,
        malformed_publish: bool = False,
        upload_revision_jump: int = 1,
    ) -> None:
        self.role = role
        self.require_teacher_confirmation = require_teacher_confirmation
        self.fail_path = fail_path
        self.unknown_publish = unknown_publish
        self.nonzero_confirmation_send = nonzero_confirmation_send
        self.malformed_publish = malformed_publish
        self.upload_revision_jump = upload_revision_jump
        self.calls: list[dict[str, Any]] = []
        self.versions: dict[str, VersionState] = {}
        self.publish_attempts: dict[str, int] = {}
        self.agent_count = 0

    def _record(self, **event: Any) -> None:
        self.calls.append(event)

    @staticmethod
    def _version(state: VersionState, *, published: bool = False) -> dict[str, object]:
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
    ) -> Response:
        del csrf, raw
        self._record(
            kind="request",
            method=method,
            path=path,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if self.role == "teacher":
            return self._teacher(method, path, payload)
        if self.fail_path and self.fail_path in path:
            return Response(503, {"code": "provider_unavailable"})
        if method == "POST" and path.endswith("/agents"):
            self.agent_count += 1
            agent_id = str(uuid4())
            version_id = str(uuid4())
            state = VersionState(agent_id, version_id)
            self.versions[version_id] = state
            return Response(
                201,
                {
                    "id": agent_id,
                    "versions": [self._version(state)],
                },
            )
        if method == "PATCH" and "/agent-versions/" in path:
            state = self.versions[path.rsplit("/", 1)[-1]]
            assert isinstance(payload, dict)
            state.revision = int(payload["expected_revision"]) + 1
            return Response(200, self._version(state))
        if method == "POST" and path.endswith("/publish"):
            version_id = path.split("/agent-versions/", 1)[1].split("/", 1)[0]
            state = self.versions[version_id]
            attempts = self.publish_attempts.get(version_id, 0) + 1
            self.publish_attempts[version_id] = attempts
            if self.unknown_publish:
                return Response(503, {"code": "acceptance_unknown"})
            if self.require_teacher_confirmation and attempts == 1:
                body: dict[str, object] = {"code": "provider_confirmation_required"}
                if self.nonzero_confirmation_send:
                    body["provider_send_count"] = 1
                return Response(409, body)
            if self.malformed_publish:
                return Response(200, {**self._version(state), "state": "draft"})
            published = self._version(state, published=True)
            return Response(200, published)
        raise AssertionError(f"unexpected student request: {method} {path}")

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
    ) -> Response:
        del csrf
        self._record(
            kind="multipart",
            method=method,
            path=path,
            fields=dict(fields),
            file_name=file_name,
            file_content=file_content,
            content_type=content_type,
            idempotency_key=idempotency_key,
        )
        if self.fail_path and self.fail_path in path:
            return Response(503, {"code": "provider_unavailable"})
        version_id = fields["target_agent_version_id"]
        state = self.versions[version_id]
        state.document_id = str(uuid4())
        state.revision = int(fields["expected_revision"]) + self.upload_revision_jump
        return Response(
            201,
            {
                "document": {
                    "id": state.document_id,
                    "index_status": "ready",
                },
                "agent_version": self._version(state),
            },
        )

    def _teacher(self, method: str, path: str, payload: object | None) -> Response:
        raise AssertionError(f"unexpected teacher request: {method} {path}")


def _mutation_keys(transport: FakeAuthorTransport) -> list[str]:
    return [
        event["idempotency_key"]
        for event in transport.calls
        if event["method"] in {"POST", "PATCH"}
    ]


def _paths(transport: FakeAuthorTransport) -> list[str]:
    return [event["path"] for event in transport.calls]


def test_authoring_creates_unique_v2_personas_and_uses_live_revisions() -> None:
    student = FakeAuthorTransport(upload_revision_jump=3)
    spec = SimpleNamespace(session_id="shape-a5-r2-en", agent_count=5)

    result = author_session_agents(
        spec,
        student=student,
        group_id=GROUP_ID,
        corpus_bytes=CORPUS,
        run_id="run-one",
    )

    assert result["status"] == "published"
    assert len(result["agent_ids"]) == len(result["version_ids"]) == 5
    assert len(result["snapshot_ids"]) == 5
    assert len(set(result["agent_ids"])) == 5
    assert len(set(result["version_ids"])) == 5
    assert len(set(result["snapshot_ids"])) == 5
    assert result["version_ids"] == [item["version_id"] for item in result["agents"]]
    assert result["snapshot_ids"] == [item["snapshot_id"] for item in result["agents"]]

    expected_suffixes = ("/agents", "/publish")
    for slot in range(5):
        events = student.calls[slot * 4 : (slot + 1) * 4]
        assert [event["kind"] for event in events] == [
            "request",
            "request",
            "multipart",
            "request",
        ]
        assert events[0]["path"].endswith(expected_suffixes[0])
        assert events[1]["method"] == "PATCH"
        assert events[2]["path"].endswith("/knowledge-documents")
        assert events[2]["fields"]["expected_revision"] == "1"
        assert events[2]["fields"]["target_agent_version_id"] in result["version_ids"]
        assert events[2]["file_content"] == CORPUS
        assert events[2]["content_type"] == "text/markdown"
        assert events[3]["path"].endswith(expected_suffixes[1])
        assert events[3]["payload"]["expected_revision"] == 4

    keys = _mutation_keys(student)
    assert len(keys) == 20
    assert all(isinstance(key, str) and len(key) >= 16 for key in keys)
    assert len(set(keys)) == len(keys)

    persona_payloads = [
        event["payload"]["agent_md"] for event in student.calls if event["method"] == "PATCH"
    ]
    compiled = [
        compile_persona_v2(markdown, expected_name=markdown.splitlines()[0][2:])
        for markdown in persona_payloads
    ]
    assert all(item.compiled for item in compiled)
    assert len({item.spec.core_values for item in compiled if item.spec}) == 5
    assert len({item.spec.speaking_style for item in compiled if item.spec}) == 5

    rendered = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "teacher_user_id",
        "student_user_id",
        "api_key",
        "endpoint",
        "policy_hash",
        "manifest_hash",
        "raw_agent_md",
    ):
        assert forbidden not in rendered
    assert all(
        set(step) <= {"stage", "status", "wall_ms", "error_code"} for step in result["steps"]
    )


def test_provider_confirmation_failure_has_no_teacher_http_fallback() -> None:
    student = FakeAuthorTransport(require_teacher_confirmation=True)
    teacher = FakeAuthorTransport(role="teacher")

    with pytest.raises(AuthoringFailure) as raised:
        author_session_agents(
            SimpleNamespace(session_id="fresh-01-2x2-en", agent_count=2),
            student,
            teacher=teacher,
            group_id=GROUP_ID,
            corpus=CORPUS,
        )

    assert raised.value.code == "provider_confirmation_required"
    assert teacher.calls == []
    assert len([path for path in _paths(student) if path.endswith("/publish")]) == 1
    assert not any("provider/data-call" in path for path in _paths(student))


@pytest.mark.parametrize(
    ("kwargs", "expected_code", "teacher_calls"),
    [
        ({"fail_path": "/knowledge-documents"}, "provider_unavailable", 0),
        ({"unknown_publish": True}, "acceptance_unknown", 0),
        (
            {"require_teacher_confirmation": True, "nonzero_confirmation_send": True},
            "provider_confirmation_required",
            0,
        ),
        ({"malformed_publish": True}, "publish_state_invalid", 0),
    ],
)
def test_failure_stops_without_downstream_or_unknown_retry(
    kwargs: dict[str, object], expected_code: str, teacher_calls: int
) -> None:
    student = FakeAuthorTransport(**kwargs)
    teacher = FakeAuthorTransport(role="teacher")

    with pytest.raises(AuthoringFailure) as raised:
        author_session_agents(
            SimpleNamespace(session_id="failure-case", agent_count=2),
            student,
            teacher=teacher,
            group_id=GROUP_ID,
            corpus=CORPUS,
        )

    assert raised.value.code == expected_code
    assert raised.value.partial_audit["error_code"] == expected_code
    assert set(raised.value.partial_audit) == {"status", "error_code", "stage", "steps"}
    assert len([event for event in teacher.calls if event["method"] == "POST"]) == teacher_calls
    paths = _paths(student)
    if expected_code == "provider_unavailable":
        assert any(path.endswith("/knowledge-documents") for path in paths)
        assert not any(path.endswith("/publish") for path in paths)
        assert not any(path.endswith("/agents") for path in paths[3:])
    elif expected_code == "acceptance_unknown":
        assert len([path for path in paths if path.endswith("/publish")]) == 1
        assert not any("provider/data-call" in path for path in paths)
    elif expected_code == "provider_confirmation_required":
        assert len([path for path in paths if path.endswith("/publish")]) == 1
        assert not any("provider/data-call" in path for path in teacher.calls)
    else:
        assert len([path for path in paths if path.endswith("/publish")]) == 1
