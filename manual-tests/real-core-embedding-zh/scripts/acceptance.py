"""Offline fixture check and two-phase REAL-EMBED product acceptance driver."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
PACKET = ROOT / "manual-tests" / "real-core-embedding-zh"
BACKEND = ROOT / "backend"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]+|"
    r"password\s*[:=]|secret\s*[:=]|sk-[A-Za-z0-9])"
)
CHECKPOINT_FIELDS = {
    "version",
    "fixture_hash",
    "course_id",
    "group_id",
    "target_agent_id",
    "target_version_id",
    "target_revision",
    "control_agent_id",
}


class AcceptanceError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise AcceptanceError(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Fixture:
    manifest: Mapping[str, Any]
    knowledge: bytes
    persona: str
    topic: str
    fixture_hash: str
    persona_hash: str
    query_text: str


def load_fixture() -> Fixture:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.modules.agents.persona import compile_persona
    from app.modules.debates.generation import GenerationContext, MutualLearningPolicy
    from app.modules.debates.generation.retrieval import build_turn_subqueries
    from app.modules.debates.generation.types import ParticipantContext
    from app.modules.knowledge.markdown import (
        TOKEN_RE,
        build_chunks,
        normalize_markdown,
    )

    manifest = json.loads((PACKET / "fixture-manifest.json").read_text(encoding="utf-8"))
    require(isinstance(manifest, dict), "manifest_invalid")
    required = {
        "manifest_version",
        "language",
        "knowledge_path",
        "persona_path",
        "topic_path",
        "expected_terms_path",
        "chunking_version",
        "expected_chunk_count",
        "call_cap",
        "snapshot_document_filename",
    }
    require(set(manifest) == required, "manifest_fields_invalid")
    require(manifest["manifest_version"] == "real-embed-zh-v1", "manifest_version")
    require(manifest["language"] == "zh-CN", "manifest_language")
    require(manifest["expected_chunk_count"] == 1, "manifest_chunk_count")
    require(manifest["call_cap"] == {"snapshot": 1, "query": 1, "total": 2}, "call_cap")

    hashes: dict[str, str] = {}
    for line in (PACKET / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        require(HASH_RE.fullmatch(digest) is not None, "hash_manifest_invalid")
        require(relative not in hashes and "/" not in relative and ".." not in relative, "hash_path")
        hashes[relative] = digest
    expected = {
        "fixture-manifest.json",
        str(manifest["knowledge_path"]),
        str(manifest["persona_path"]),
        str(manifest["topic_path"]),
        str(manifest["expected_terms_path"]),
    }
    require(set(hashes) == expected, "hash_paths_invalid")
    for relative, digest in hashes.items():
        require(sha(PACKET / relative) == digest, "fixture_hash_changed")

    knowledge = (PACKET / str(manifest["knowledge_path"])).read_bytes()
    persona = (PACKET / str(manifest["persona_path"])).read_text(encoding="utf-8")
    topic = (PACKET / str(manifest["topic_path"])).read_text(encoding="utf-8").strip()
    terms = tuple(
        item.strip()
        for item in (PACKET / str(manifest["expected_terms_path"]))
        .read_text(encoding="utf-8")
        .splitlines()
        if item.strip()
    )
    for value in (knowledge.decode("utf-8"), persona, topic, "\n".join(terms)):
        require(SECRET_RE.search(value) is None, "fixture_secret_like")
        require("@" not in value and UUID_RE.search(value) is None, "fixture_identity_like")
    require(any("\u4e00" <= char <= "\u9fff" for char in topic), "topic_not_chinese")
    require(all(term in knowledge.decode("utf-8") for term in terms), "term_missing")

    normalized = normalize_markdown(str(manifest["snapshot_document_filename"]), knowledge).normalized
    require(len(list(TOKEN_RE.finditer(normalized))) < 600, "fixture_too_large")
    chunks = tuple(build_chunks(normalized))
    require(len(chunks) == 1, "fixture_not_one_chunk")
    compiled = compile_persona(persona, expected_name="河流与种子守护者")
    require(compiled.compiled and compiled.persona_spec_hash is not None, "persona_compile")

    participants = (
        ParticipantContext("p1", "a1", "Agent 1", "A", 0, "s1"),
        ParticipantContext("p2", "a2", "Agent 2", "B", 1, "s2"),
    )
    turn = MutualLearningPolicy().plan(participants, round_count=2)[0]
    query = build_turn_subqueries(
        GenerationContext("fixture-debate", topic, turn, participants[0], participants)
    )[0].text
    require(any(term in query for term in terms), "opening_query_not_chinese")
    fixture_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Fixture(manifest, knowledge, persona, topic, fixture_hash, compiled.persona_spec_hash, query)


@dataclass
class TwoCallGate:
    snapshot_confirmed: bool = False
    snapshot_calls: int = 0
    query_confirmed: bool = False
    query_calls: int = 0

    def confirm_snapshot(self) -> None:
        self.snapshot_confirmed = True

    def call_snapshot(self) -> None:
        require(self.snapshot_confirmed and self.snapshot_calls == 0, "snapshot_call_forbidden")
        self.snapshot_calls = 1

    def confirm_query(self) -> None:
        require(self.snapshot_calls == 1, "query_confirmation_too_early")
        self.query_confirmed = True

    def call_query(self) -> None:
        require(self.query_confirmed and self.query_calls == 0, "query_call_forbidden")
        self.query_calls = 1

    def result(self) -> dict[str, int]:
        require(self.snapshot_calls == 1 and self.query_calls == 1, "call_count_incomplete")
        return {"snapshot_calls": 1, "query_calls": 1, "total_calls": 2}


class Api:
    def __init__(self, base_url: str) -> None:
        require(base_url.startswith("http://127.0.0.1:") or base_url == "http://localhost:8080", "base_url")
        self.client = httpx.Client(base_url=base_url, timeout=20, follow_redirects=False)
        self.csrf = ""

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: set[int],
        body: Mapping[str, Any] | None = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        key: str | None = None,
        params: Mapping[str, str] | None = None,
    ) -> tuple[int, Mapping[str, Any]]:
        headers: dict[str, str] = {}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        if key:
            headers["Idempotency-Key"] = key
        try:
            response = self.client.request(
                method, path, json=body, data=data, files=files, headers=headers, params=params
            )
        except httpx.HTTPError as exc:
            raise AcceptanceError("http_transport") from exc
        require(response.status_code in expected, f"http_{response.status_code}")
        value = response.json()
        require(isinstance(value, dict), "response_shape")
        return response.status_code, value

    def login(self, username: str, password: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST", "/api/v1/auth/login", expected={200}, body={"username": username, "password": password}
        )
        require(isinstance(value.get("csrf_token"), str), "csrf_missing")
        self.csrf = str(value["csrf_token"])
        user = value.get("user")
        require(isinstance(user, dict), "user_missing")
        return user


def opaque(value: Any, code: str) -> str:
    require(isinstance(value, str) and UUID_RE.fullmatch(value) is not None, code)
    return value


def setup_agent(api: Api, group_id: str, name: str, persona: str, knowledge: bytes) -> tuple[str, str, int]:
    _status, created = api.request(
        "POST",
        f"/api/v1/groups/{group_id}/agents",
        expected={201},
        body={"name": name, "description": "Real-Core fixed fixture"},
        key=f"real-core-create-{hashlib.sha256(name.encode()).hexdigest()[:20]}",
    )
    agent_id = opaque(created.get("id"), "agent_id")
    versions = created.get("versions")
    require(isinstance(versions, list) and len(versions) == 1, "version_missing")
    version = versions[0]
    require(isinstance(version, dict), "version_shape")
    version_id = opaque(version.get("id"), "version_id")
    _status, updated = api.request(
        "PATCH",
        f"/api/v1/agent-versions/{version_id}",
        expected={200},
        body={"expected_revision": 0, "agent_md": persona, "avatar_config": version.get("avatar_config")},
    )
    require(updated.get("revision") == 1, "draft_revision")
    _status, uploaded = api.request(
        "POST",
        f"/api/v1/groups/{group_id}/knowledge-documents",
        expected={201},
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("maya-cultural-knowledge-zh.md", knowledge, "text/markdown")},
        key=f"real-core-doc-{version_id}",
    )
    version_after = uploaded.get("agent_version")
    require(isinstance(version_after, dict) and version_after.get("revision") == 2, "document_revision")
    _status, compiled = api.request(
        "POST", f"/api/v1/agent-versions/{version_id}/persona/compile", expected={200}, body={"expected_revision": 2}
    )
    confirm_body = {
        "expected_revision": 2,
        "raw_agent_md_hash": compiled.get("raw_agent_md_hash"),
        "persona_spec_hash": compiled.get("persona_spec_hash"),
        "compiler_version": compiled.get("compiler_version"),
    }
    _status, confirmed = api.request(
        "POST", f"/api/v1/agent-versions/{version_id}/persona/confirm", expected={200}, body=confirm_body
    )
    require(confirmed.get("persona_confirmed") is True, "persona_unconfirmed")
    return agent_id, version_id, int(confirmed.get("revision", -1))


def write_checkpoint(path: Path, value: Mapping[str, Any]) -> None:
    require(set(value) == CHECKPOINT_FIELDS, "checkpoint_fields")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def read_checkpoint(path: Path, fixture: Fixture) -> Mapping[str, Any]:
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "checkpoint_mode")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict) and set(value) == CHECKPOINT_FIELDS, "checkpoint_invalid")
    require(value["version"] == "real-embed-checkpoint-v1", "checkpoint_version")
    require(value["fixture_hash"] == fixture.fixture_hash, "checkpoint_fixture")
    for field in CHECKPOINT_FIELDS - {"version", "fixture_hash", "target_revision"}:
        opaque(value[field], f"checkpoint_{field}")
    require(isinstance(value["target_revision"], int), "checkpoint_revision")
    return value


def prepare(base_url: str, checkpoint_path: Path, student_password: str) -> Mapping[str, Any]:
    fixture = load_fixture()
    api = Api(base_url)
    try:
        user = api.login(os.environ.get("MAYA_STUDENT_USERNAME", "student-bowen-1"), student_password)
        courses, groups = user.get("courses"), user.get("groups")
        require(isinstance(courses, list) and courses and isinstance(groups, list) and groups, "scope_missing")
        course_id = opaque(courses[0].get("course_id"), "course_id")
        group_id = opaque(groups[0].get("group_id"), "group_id")
        control_persona = fixture.persona.replace("# 河流与种子守护者", "# 课堂流程观察者", 1)
        control_agent, control_version, control_revision = setup_agent(
            api, group_id, "课堂流程观察者", control_persona, fixture.knowledge
        )
        _status, published = api.request(
            "POST",
            f"/api/v1/agent-versions/{control_version}/publish",
            expected={200},
            body={"expected_revision": control_revision},
            key=f"real-core-publish-{control_version}",
        )
        require(published.get("state") == "published", "control_publish")
        target_agent, target_version, target_revision = setup_agent(
            api, group_id, "河流与种子守护者", fixture.persona, fixture.knowledge
        )
        checkpoint = {
            "version": "real-embed-checkpoint-v1",
            "fixture_hash": fixture.fixture_hash,
            "course_id": course_id,
            "group_id": group_id,
            "target_agent_id": target_agent,
            "target_version_id": target_version,
            "target_revision": target_revision,
            "control_agent_id": control_agent,
        }
        write_checkpoint(checkpoint_path, checkpoint)
        return checkpoint
    finally:
        api.close()


def execute(
    base_url: str,
    checkpoint_path: Path,
    policy_hash: str,
    student_password: str,
    teacher_password: str,
) -> Mapping[str, Any]:
    require(HASH_RE.fullmatch(policy_hash) is not None, "policy_hash")
    fixture = load_fixture()
    checkpoint = read_checkpoint(checkpoint_path, fixture)
    student, teacher = Api(base_url), Api(base_url)
    gate = TwoCallGate()
    try:
        student.login(os.environ.get("MAYA_STUDENT_USERNAME", "student-bowen-1"), student_password)
        teacher.login(os.environ.get("MAYA_TEACHER_USERNAME", "teacher-demo"), teacher_password)
        version_id = str(checkpoint["target_version_id"])
        publish_key = f"real-core-publish-{version_id}"
        status, blocked = student.request(
            "POST",
            f"/api/v1/agent-versions/{version_id}/publish",
            expected={409},
            body={"expected_revision": int(checkpoint["target_revision"])},
            key=publish_key,
        )
        require(status == 409 and blocked.get("code") == "provider_confirmation_required", "snapshot_not_blocked")
        _status, pending = teacher.request(
            "GET", f"/api/v1/provider/data-call/pending/agent-versions/{version_id}", expected={200}
        )
        items = pending.get("items")
        require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict), "snapshot_manifest")
        item = items[0]
        manifest_hash = str(item.get("manifest_hash", ""))
        _status, disclosure = teacher.request(
            "GET",
            "/api/v1/provider/data-call/disclosure",
            expected={200},
            params={"manifest_hash": manifest_hash},
        )
        require(disclosure.get("policy_hash") == policy_hash, "snapshot_policy")
        teacher.request(
            "POST",
            "/api/v1/provider/data-call/disclosure/confirm",
            expected={200},
            body={
                "policy_hash": policy_hash,
                "manifest_hash": manifest_hash,
                "expected_revision": disclosure.get("confirmation_revision"),
            },
        )
        gate.confirm_snapshot()
        _status, published = student.request(
            "POST",
            f"/api/v1/agent-versions/{version_id}/publish",
            expected={200},
            body={"expected_revision": int(checkpoint["target_revision"])},
            key=publish_key,
        )
        gate.call_snapshot()
        snapshot_id = opaque(published.get("knowledge_snapshot_id"), "snapshot_id")

        _status, debate = teacher.request(
            "POST",
            f"/api/v1/courses/{checkpoint['course_id']}/debates",
            expected={201},
            body={
                "topic": fixture.topic,
                "participants": [
                    {"agent_id": checkpoint["target_agent_id"], "stance_mode": "open"},
                    {"agent_id": checkpoint["control_agent_id"], "stance_mode": "open"},
                ],
                "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
                "round_count": 2,
            },
            key="real-core-create-debate-0001",
        )
        debate_id = opaque(debate.get("id"), "debate_id")
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/start",
            expected={200},
            body={
                "expected_revision": debate.get("revision"),
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
            key="real-core-start-debate-0001",
        )
        query_item: Mapping[str, Any] | None = None
        for _ in range(30):
            _status, pending_query = teacher.request(
                "GET",
                "/api/v1/provider/data-call/pending",
                expected={200},
                params={"scope_id": debate_id},
            )
            query_items = pending_query.get("items")
            if isinstance(query_items, list) and query_items and isinstance(query_items[0], dict):
                query_item = query_items[0]
                break
            time.sleep(0.2)
        require(query_item is not None, "query_manifest")
        query_hash = str(query_item.get("manifest_hash", ""))
        turn_id = opaque(query_item.get("turn_id"), "turn_id")
        _status, query_disclosure = teacher.request(
            "GET",
            "/api/v1/provider/data-call/disclosure",
            expected={200},
            params={"manifest_hash": query_hash},
        )
        require(query_disclosure.get("policy_hash") == policy_hash, "query_policy")
        teacher.request(
            "POST",
            "/api/v1/provider/data-call/disclosure/confirm",
            expected={200},
            body={
                "policy_hash": policy_hash,
                "manifest_hash": query_hash,
                "expected_revision": query_disclosure.get("confirmation_revision"),
            },
        )
        gate.confirm_query()
        _status, current = teacher.request("GET", f"/api/v1/debates/{debate_id}", expected={200})
        playback = current.get("playback")
        require(isinstance(playback, dict), "playback_missing")
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/preparation/retry",
            expected={200},
            body={"turn_id": turn_id, "expected_control_version": playback.get("control_version")},
            key="real-core-query-retry-0001",
        )
        gate.call_query()
        accepted_turn: Mapping[str, Any] | None = None
        for _ in range(50):
            _status, current = teacher.request("GET", f"/api/v1/debates/{debate_id}", expected={200})
            turns = current.get("public_turns")
            if isinstance(turns, list) and turns and isinstance(turns[0], dict):
                candidate = turns[0]
                if candidate.get("retrieval_status") == "matched" and candidate.get("sources"):
                    accepted_turn = candidate
                    break
            time.sleep(0.2)
        require(accepted_turn is not None, "matched_turn_missing")
        participants = current.get("participants")
        require(isinstance(participants, list) and participants[0].get("knowledge_snapshot_id") == snapshot_id, "snapshot_binding")
        sources = accepted_turn.get("sources")
        require(isinstance(sources, list) and sources[0].get("source_filename") == "maya-cultural-knowledge-zh.md", "source_binding")
        require(bool(accepted_turn.get("evidence_trace")), "evidence_trace_missing")
        return {
            "status": "REAL_EMBED_E2E_PASS",
            "fixture_hash": fixture.fixture_hash,
            "snapshot_id": snapshot_id,
            "debate_id": debate_id,
            **gate.result(),
        }
    finally:
        student.close()
        teacher.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    for name in ("prepare", "execute"):
        command = sub.add_parser(name)
        command.add_argument("--checkpoint", type=Path, required=True)
    execute_parser = sub.choices["execute"]
    execute_parser.add_argument("--policy-hash", required=True)
    execute_parser.add_argument("--confirm-two-call-cap", action="store_true", required=True)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        fixture = load_fixture()
        if args.command == "check":
            value: Mapping[str, Any] = {
                "status": "FIXTURE_OK",
                "fixture_hash": fixture.fixture_hash,
                "chunk_count": 1,
                "real_calls": 0,
            }
        else:
            base_url = os.environ.get("MAYA_BASE_URL", "")
            student_password = os.environ.get("MAYA_STUDENT_PASSWORD", "")
            require(bool(student_password), "student_password_missing")
            if args.command == "prepare":
                value = prepare(base_url, args.checkpoint, student_password)
            else:
                teacher_password = os.environ.get("MAYA_TEACHER_PASSWORD", "")
                require(args.confirm_two_call_cap and bool(teacher_password), "real_confirmation_missing")
                value = execute(
                    base_url,
                    args.checkpoint,
                    args.policy_hash,
                    student_password,
                    teacher_password,
                )
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0
    except (AcceptanceError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, AcceptanceError) else "acceptance_failed"
        print(json.dumps({"status": "FAILED", "safe_error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
