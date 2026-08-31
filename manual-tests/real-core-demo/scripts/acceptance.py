"""Bounded Real-Core Demo acceptance driver.

The active command is the provider-free full-Mock preparation boundary.  The
superseded seven-call execute/verify implementation remains gated until the
replacement Real plan is frozen, so this process currently makes no Provider
request and records only opaque checkpoint metadata.
"""

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
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[3]
PACKET = ROOT / "manual-tests" / "real-core-demo"
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
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
BASE_URL_RE = re.compile(r"http://(?P<host>127\.0\.0\.1|localhost):(?P<port>[0-9]{1,5})/?")
REAL_PLAN_FROZEN = False
BASELINE_FIELDS = {
    "agent_id",
    "version_id",
    "snapshot_id",
    "group_id",
    "system_baseline",
    "immutable",
    "usable",
}
CHECKPOINT_FIELDS = {
    "version",
    "state",
    "acceptance_run_id",
    "fixture_hash",
    "course_id",
    "group_id",
    "real_agent_id",
    "real_version_id",
    "baseline_agent_id",
    "baseline_version_id",
    "baseline_snapshot_id",
    "real_revision",
    "dirty_agents",
    "dirty_debates",
    "dirty_interactions",
    "snapshot_id",
    "debate_id",
    "current_turn_id",
    "snapshot_calls",
    "real_query_calls",
    "llm_calls",
    "completed_turns",
    "next_call",
}
CHECKPOINT_STATES = {"prepared", "executing", "executed", "verified"}


class AcceptanceError(RuntimeError):
    """Safe, value-free driver failure."""


def require(value: bool, code: str) -> None:
    if not value:
        raise AcceptanceError(code)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validated_baseline(value: Mapping[str, Any]) -> Mapping[str, Any]:
    require(set(value) == BASELINE_FIELDS, "baseline_shape")
    identifiers = tuple(opaque(value[field], f"baseline_{field}") for field in (
        "agent_id", "version_id", "snapshot_id", "group_id"
    ))
    require(len(set(identifiers)) == len(identifiers), "baseline_identity")
    require(value["system_baseline"] is True, "baseline_not_system")
    require(value["immutable"] is True, "baseline_not_immutable")
    require(value["usable"] is True, "baseline_not_usable")
    return value


@dataclass(frozen=True)
class Fixture:
    manifest: Mapping[str, Any]
    knowledge: bytes
    real_persona: str
    topic: str
    fixture_hash: str
    real_persona_hash: str
    query_text: str


def load_fixture() -> Fixture:
    """Validate the fixed identity-free fixture and derive its first query."""

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.modules.agents.persona import compile_persona, provider_view
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
        "real_persona_path",
        "topic_path",
        "expected_terms_path",
        "chunking_version",
        "expected_chunk_count",
        "call_cap",
        "snapshot_document_filename",
        "real_participant_slot",
    }
    require(set(manifest) == required, "manifest_fields_invalid")
    require(manifest["manifest_version"] == "real-core-demo-v1", "manifest_version")
    require(manifest["language"] == "zh-CN", "manifest_language")
    require(manifest["expected_chunk_count"] == 1, "manifest_chunk_count")
    require(
        manifest["call_cap"] == {"snapshot": 1, "real_query": 2, "llm_turn": 4, "total": 7},
        "call_cap",
    )
    require(manifest["real_participant_slot"] == "B", "real_slot")

    hashes: dict[str, str] = {}
    for line in (PACKET / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        require(len(parts) == 2, "hash_manifest_invalid")
        digest, relative = parts
        require(HASH_RE.fullmatch(digest) is not None, "hash_manifest_invalid")
        require(
            relative not in hashes and "/" not in relative and ".." not in relative,
            "hash_path",
        )
        hashes[relative] = digest
    expected = {
        "fixture-manifest.json",
        str(manifest["real_persona_path"]),
        str(manifest["knowledge_path"]),
        str(manifest["topic_path"]),
        str(manifest["expected_terms_path"]),
    }
    require(set(hashes) == expected, "hash_paths_invalid")
    for relative, digest in hashes.items():
        require(sha(PACKET / relative) == digest, "fixture_hash_changed")

    knowledge = (PACKET / str(manifest["knowledge_path"])).read_bytes()
    real_persona = (PACKET / str(manifest["real_persona_path"])).read_text(encoding="utf-8")
    topic = (PACKET / str(manifest["topic_path"])).read_text(encoding="utf-8").strip()
    require(CJK_RE.search(topic) is not None, "topic_not_chinese")
    terms = tuple(
        item.strip()
        for item in (PACKET / str(manifest["expected_terms_path"]))
        .read_text(encoding="utf-8")
        .splitlines()
        if item.strip()
    )
    for value in (knowledge.decode("utf-8"), real_persona, topic, "\n".join(terms)):
        require(SECRET_RE.search(value) is None, "fixture_secret_like")
        require("@" not in value and UUID_RE.search(value) is None, "fixture_identity_like")
    knowledge_text = knowledge.decode("utf-8")
    require(all(term in knowledge_text for term in terms), "term_missing")
    normalized = normalize_markdown(
        str(manifest["snapshot_document_filename"]), knowledge
    ).normalized
    require(len(list(TOKEN_RE.finditer(normalized))) < 600, "fixture_too_large")
    require(len(tuple(build_chunks(normalized))) == 1, "fixture_not_one_chunk")

    real_compiled = compile_persona(real_persona, expected_name="河流与种子守护者")
    require(
        real_compiled.compiled
        and real_compiled.spec is not None
        and real_compiled.persona_spec_hash is not None,
        "real_persona_compile",
    )
    participants = (
        ParticipantContext(
            "fixture-baseline",
            "fixture-baseline-agent",
            "baseline",
            "A",
            0,
            "fixture-baseline-snapshot",
        ),
        ParticipantContext(
            "fixture-real",
            "fixture-real-agent",
            "河流与种子守护者",
            "B",
            1,
            "fixture-real-snapshot",
            persona=provider_view(real_compiled.spec),
            persona_spec_hash=real_compiled.persona_spec_hash,
        ),
    )
    turn = MutualLearningPolicy().plan(participants, round_count=2)[1]
    query = build_turn_subqueries(
        GenerationContext("fixture-debate", topic, turn, participants[1], participants)
    )[0].text
    require(any(term in query for term in terms), "opening_query_not_chinese")
    fixture_hash = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return Fixture(
        manifest,
        knowledge,
        real_persona,
        topic,
        fixture_hash,
        real_compiled.persona_spec_hash,
        query,
    )


@dataclass
class SevenCallGate:
    """Local fence for exactly one Snapshot, two queries and four LLM turns."""

    snapshot_confirmed: bool = False
    snapshot_calls: int = 0
    query_confirmed: bool = False
    real_query_calls: int = 0
    llm_confirmed: bool = False
    llm_calls: int = 0

    def confirm_snapshot(self) -> None:
        self.snapshot_confirmed = True

    def call_snapshot(self) -> None:
        require(self.snapshot_confirmed and self.snapshot_calls == 0, "snapshot_call_forbidden")
        self.snapshot_calls = 1

    def confirm_query(self) -> None:
        require(self.snapshot_calls == 1, "query_confirmation_too_early")
        self.query_confirmed = True

    def call_query(self) -> None:
        require(self.query_confirmed and self.real_query_calls < 2, "query_call_forbidden")
        self.real_query_calls += 1

    def confirm_llm(self) -> None:
        require(self.snapshot_calls == 1, "llm_confirmation_too_early")
        self.llm_confirmed = True

    def call_llm(self) -> None:
        require(self.llm_confirmed and self.llm_calls < 4, "llm_call_forbidden")
        self.llm_calls += 1

    def result(self) -> dict[str, int]:
        require(
            self.snapshot_calls == 1 and self.real_query_calls == 2 and self.llm_calls == 4,
            "call_count_incomplete",
        )
        return {
            "snapshot_calls": self.snapshot_calls,
            "real_query_calls": self.real_query_calls,
            "llm_calls": self.llm_calls,
            "total_calls": self.snapshot_calls + self.real_query_calls + self.llm_calls,
        }


def _validated_origin(base_url: str) -> str:
    require(isinstance(base_url, str), "base_url")
    match = BASE_URL_RE.fullmatch(base_url)
    require(match is not None, "base_url")
    host = str(match.group("host"))
    port = int(str(match.group("port")))
    require(1 <= port <= 65535, "base_url")
    require(host != "localhost" or port == 8080, "base_url")
    return f"http://{host}:{port}"


class Api:
    """Small no-retry API client that keeps error output value-free."""

    def __init__(self, base_url: str) -> None:
        self.origin = _validated_origin(base_url)
        self.client = httpx.Client(
            base_url=self.origin,
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        )
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
        headers: dict[str, str] = {"Origin": self.origin}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        if key:
            headers["Idempotency-Key"] = key
        try:
            response = self.client.request(
                method,
                path,
                json=body,
                data=data,
                files=files,
                headers=headers,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise AcceptanceError("http_transport") from exc
        require(response.status_code in expected, f"http_{response.status_code}")
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AcceptanceError("response_json") from exc
        require(isinstance(value, dict), "response_shape")
        return response.status_code, value

    def login(self, username: str, password: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            "/api/v1/auth/login",
            expected={200},
            body={"username": username, "password": password},
        )
        require(isinstance(value.get("csrf_token"), str), "csrf_missing")
        self.csrf = str(value["csrf_token"])
        user = value.get("user")
        require(isinstance(user, dict), "user_missing")
        return user

    def demo_baseline(self) -> Mapping[str, Any]:
        _status, value = self.request("GET", "/api/v1/demo/baseline", expected={200})
        return _validated_baseline(value)

    def demo_status(self) -> Mapping[str, Any]:
        _status, value = self.request("GET", "/api/v1/demo/status", expected={200})
        require(set(value) == {
            "baseline", "composition", "dirty_agents", "dirty_debates", "dirty_interactions"
        }, "status_shape")
        baseline = value.get("baseline")
        require(isinstance(baseline, dict), "status_baseline")
        _validated_baseline(baseline)
        require(isinstance(value["composition"], dict), "status_composition")
        for field in ("dirty_agents", "dirty_debates", "dirty_interactions"):
            count = value[field]
            require(isinstance(count, int) and not isinstance(count, bool) and count >= 0,
                    f"status_{field}")
        return value


def opaque(value: Any, code: str) -> str:
    require(isinstance(value, str) and UUID_RE.fullmatch(value) is not None, code)
    return value


def _safe_json(value: object, code: str) -> Mapping[str, Any]:
    require(isinstance(value, dict), code)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
    require(SECRET_RE.search(encoded) is None, f"{code}_secret")
    return value


def setup_agent(
    api: Api,
    group_id: str,
    name: str,
    persona: str,
    knowledge: bytes,
    *,
    key_prefix: str,
) -> tuple[str, str, int]:
    """Create and confirm one fixed Agent while the runtime is Mock-only."""

    _status, created = api.request(
        "POST",
        f"/api/v1/groups/{group_id}/agents",
        expected={201},
        body={"name": name, "description": "Real-Core fixed fixture"},
        key=f"real-core-demo-{key_prefix}-create",
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
        body={
            "expected_revision": 0,
            "agent_md": persona,
            "avatar_config": version.get("avatar_config"),
        },
    )
    require(updated.get("revision") == 1, "draft_revision")
    _status, uploaded = api.request(
        "POST",
        f"/api/v1/groups/{group_id}/knowledge-documents",
        expected={201},
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("maya-real-core-demo.md", knowledge, "text/markdown")},
        key=f"real-core-demo-{key_prefix}-document",
    )
    uploaded_version = uploaded.get("agent_version")
    require(
        isinstance(uploaded_version, dict) and uploaded_version.get("revision") == 2,
        "document_revision",
    )
    _status, compiled = api.request(
        "POST",
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        expected={200},
        body={"expected_revision": 2},
    )
    _status, confirmed = api.request(
        "POST",
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        expected={200},
        body={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled.get("raw_agent_md_hash"),
            "persona_spec_hash": compiled.get("persona_spec_hash"),
            "compiler_version": compiled.get("compiler_version"),
        },
    )
    require(confirmed.get("persona_confirmed") is True, "persona_unconfirmed")
    return agent_id, version_id, int(confirmed.get("revision", -1))


def _checkpoint_atomic(path: Path, value: Mapping[str, Any]) -> None:
    """Write one private checkpoint without exposing a partial JSON file."""

    require(set(value) == CHECKPOINT_FIELDS, "checkpoint_fields")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def write_checkpoint(path: Path, value: Mapping[str, Any]) -> None:
    _checkpoint_atomic(path, value)


def read_checkpoint(path: Path, fixture: Fixture) -> Mapping[str, Any]:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceError("checkpoint_invalid") from exc
    require(mode == 0o600, "checkpoint_mode")
    require(isinstance(value, dict) and set(value) == CHECKPOINT_FIELDS, "checkpoint_invalid")
    require(value["version"] == "real-core-demo-checkpoint-v3", "checkpoint_version")
    require(value["fixture_hash"] == fixture.fixture_hash, "checkpoint_fixture")
    require(value["state"] in CHECKPOINT_STATES, "checkpoint_state")
    opaque(value["acceptance_run_id"], "checkpoint_acceptance_run_id")
    for field in (
        "course_id",
        "group_id",
        "real_agent_id",
        "real_version_id",
        "baseline_agent_id",
        "baseline_version_id",
        "baseline_snapshot_id",
    ):
        opaque(value[field], f"checkpoint_{field}")
    require(
        len({value["real_agent_id"], value["baseline_agent_id"]}) == 2,
        "checkpoint_agent_identity",
    )
    require(
        len({value["real_version_id"], value["baseline_version_id"]}) == 2,
        "checkpoint_version_identity",
    )
    for field in ("snapshot_id", "debate_id", "current_turn_id"):
        require(
            value[field] is None or UUID_RE.fullmatch(str(value[field])) is not None,
            f"checkpoint_{field}",
        )
    require(
        isinstance(value["real_revision"], int) and value["real_revision"] >= 0,
        "checkpoint_revision",
    )
    for field in ("dirty_agents", "dirty_debates", "dirty_interactions"):
        require(
            isinstance(value[field], int)
            and not isinstance(value[field], bool)
            and value[field] >= 0,
            f"checkpoint_{field}",
        )
    require(
        (value["dirty_agents"], value["dirty_debates"], value["dirty_interactions"])
        == (1, 0, 0),
        "checkpoint_dirty_counts",
    )
    for field in ("snapshot_calls", "real_query_calls", "llm_calls"):
        require(isinstance(value[field], int) and value[field] >= 0, f"checkpoint_{field}")
    require(
        isinstance(value["completed_turns"], list)
        and all(UUID_RE.fullmatch(str(item)) is not None for item in value["completed_turns"]),
        "checkpoint_turns",
    )
    require(value["next_call"] in {"none", "snapshot", "real_query", "llm"}, "checkpoint_next_call")
    return value


def _base_checkpoint(
    fixture: Fixture,
    *,
    acceptance_run_id: str,
    course_id: str,
    group_id: str,
    real_agent_id: str,
    real_version_id: str,
    baseline_agent_id: str,
    baseline_version_id: str,
    baseline_snapshot_id: str,
    real_revision: int,
) -> dict[str, Any]:
    return {
        "version": "real-core-demo-checkpoint-v3",
        "state": "prepared",
        "acceptance_run_id": acceptance_run_id,
        "fixture_hash": fixture.fixture_hash,
        "course_id": course_id,
        "group_id": group_id,
        "real_agent_id": real_agent_id,
        "real_version_id": real_version_id,
        "baseline_agent_id": baseline_agent_id,
        "baseline_version_id": baseline_version_id,
        "baseline_snapshot_id": baseline_snapshot_id,
        "real_revision": real_revision,
        "dirty_agents": 1,
        "dirty_debates": 0,
        "dirty_interactions": 0,
        "snapshot_id": None,
        "debate_id": None,
        "current_turn_id": None,
        "snapshot_calls": 0,
        "real_query_calls": 0,
        "llm_calls": 0,
        "completed_turns": [],
        "next_call": "none",
    }


def prepare(base_url: str, checkpoint_path: Path, student_password: str) -> Mapping[str, Any]:
    """Create only target Agent B and reuse the immutable server baseline as A."""

    fixture = load_fixture()
    require(not checkpoint_path.exists(), "checkpoint_exists")
    api = Api(base_url)
    try:
        user = api.login(
            os.environ.get("MAYA_STUDENT_USERNAME", "student-bowen-1"),
            student_password,
        )
        courses, groups = user.get("courses"), user.get("groups")
        require(isinstance(courses, list) and courses, "scope_missing")
        require(isinstance(groups, list) and groups, "scope_missing")
        baseline = api.demo_baseline()
        require(baseline == api.demo_baseline(), "baseline_not_stable")
        initial_status = api.demo_status()
        require(initial_status["baseline"] == baseline, "baseline_changed")
        require(
            (
                initial_status["dirty_agents"],
                initial_status["dirty_debates"],
                initial_status["dirty_interactions"],
            )
            == (0, 0, 0),
            "dirty_runtime",
        )
        components = initial_status["composition"].get("components")
        require(
            isinstance(components, list)
            and components
            and all(isinstance(item, dict) and item.get("mode") == "mock" for item in components),
            "prepare_not_mock",
        )
        course_id = opaque(courses[0].get("course_id"), "course_id")
        group_id = opaque(baseline["group_id"], "group_id")
        require(
            any(isinstance(item, dict) and item.get("group_id") == group_id for item in groups),
            "baseline_group",
        )
        real_agent, real_version, real_revision = setup_agent(
            api,
            group_id,
            "河流与种子守护者",
            fixture.real_persona,
            fixture.knowledge,
            key_prefix="real",
        )
        checkpoint = _base_checkpoint(
            fixture,
            acceptance_run_id=str(uuid4()),
            course_id=course_id,
            group_id=group_id,
            real_agent_id=real_agent,
            real_version_id=real_version,
            baseline_agent_id=str(baseline["agent_id"]),
            baseline_version_id=str(baseline["version_id"]),
            baseline_snapshot_id=str(baseline["snapshot_id"]),
            real_revision=real_revision,
        )
        status = api.demo_status()
        require(status["baseline"] == baseline, "baseline_changed")
        require(
            (status["dirty_agents"], status["dirty_debates"], status["dirty_interactions"])
            == (1, 0, 0),
            "dirty_counts",
        )
        checkpoint["dirty_agents"] = status["dirty_agents"]
        checkpoint["dirty_debates"] = status["dirty_debates"]
        checkpoint["dirty_interactions"] = status["dirty_interactions"]
        write_checkpoint(checkpoint_path, checkpoint)
        return checkpoint
    finally:
        api.close()


def _pending_item(
    api: Api,
    *,
    path: str,
    current_turn_id: str | None = None,
) -> Mapping[str, Any] | None:
    _status, pending = api.request("GET", path, expected={200})
    items = pending.get("items")
    if not isinstance(items, list):
        raise AcceptanceError("pending_shape")
    candidates = [item for item in items if isinstance(item, dict) and not item.get("confirmed")]
    if current_turn_id is not None:
        matching = [item for item in candidates if str(item.get("turn_id")) == current_turn_id]
        if matching:
            candidates = matching
    if not candidates:
        return None
    item = candidates[0]
    require(isinstance(item.get("manifest_hash"), str), "pending_manifest")
    require(HASH_RE.fullmatch(str(item["manifest_hash"])) is not None, "pending_manifest")
    return item


def _confirm_manifest(
    api: Api,
    item: Mapping[str, Any],
    *,
    expected_policy_hash: str,
) -> None:
    manifest_hash = str(item.get("manifest_hash", ""))
    _status, disclosure = api.request(
        "GET",
        "/api/v1/provider/data-call/disclosure",
        expected={200},
        params={"manifest_hash": manifest_hash},
    )
    require(disclosure.get("policy_hash") == expected_policy_hash, "policy_hash_mismatch")
    _safe_json(disclosure, "disclosure")
    expected_revision = disclosure.get("confirmation_revision")
    require(isinstance(expected_revision, int) and expected_revision >= 1, "disclosure_revision")
    api.request(
        "POST",
        "/api/v1/provider/data-call/disclosure/confirm",
        expected={200},
        body={
            "policy_hash": expected_policy_hash,
            "manifest_hash": manifest_hash,
            "expected_revision": expected_revision,
        },
    )


def _assert_checkpoint_baseline(api: Api, checkpoint: Mapping[str, Any]) -> None:
    baseline = api.demo_baseline()
    require(
        (
            baseline["agent_id"],
            baseline["version_id"],
            baseline["snapshot_id"],
            baseline["group_id"],
        )
        == (
            checkpoint["baseline_agent_id"],
            checkpoint["baseline_version_id"],
            checkpoint["baseline_snapshot_id"],
            checkpoint["group_id"],
        ),
        "baseline_changed",
    )


def _wait_pending(
    api: Api,
    path: str,
    *,
    current_turn_id: str,
    timeout_seconds: float = 30.0,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        item = _pending_item(api, path=path, current_turn_id=current_turn_id)
        if item is not None:
            return item
        time.sleep(0.2)
    raise AcceptanceError("provider_manifest_timeout")


def _debate_detail(api: Api, debate_id: str) -> Mapping[str, Any]:
    _status, detail = api.request("GET", f"/api/v1/debates/{debate_id}", expected={200})
    playback = detail.get("playback")
    require(isinstance(playback, dict), "playback_missing")
    return detail


def _retry_preparation(api: Api, debate_id: str, turn_id: str, *, key: str) -> None:
    detail = _debate_detail(api, debate_id)
    playback = detail["playback"]
    if playback.get("status") == "ready" and str(playback.get("current_turn_id")) == turn_id:
        return
    expected_version = playback.get("control_version")
    require(isinstance(expected_version, int), "control_version")
    api.request(
        "POST",
        f"/api/v1/debates/{debate_id}/preparation/retry",
        expected={200},
        body={"turn_id": turn_id, "expected_control_version": expected_version},
        key=key,
    )


def _wait_turn_ready(
    api: Api,
    debate_id: str,
    *,
    timeout_seconds: float = 60.0,
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        detail = _debate_detail(api, debate_id)
        playback = detail["playback"]
        if detail.get("status") in {"failed", "stopped"}:
            raise AcceptanceError("debate_failed")
        if playback.get("status") == "ready" and playback.get("current_turn_id"):
            return detail
        time.sleep(0.2)
    raise AcceptanceError("turn_ready_timeout")


class PlaybackSocket:
    """Minimal teacher controller for retained media and live turn acks."""

    def __init__(self, api: Api, debate_id: str) -> None:
        try:
            from websockets.sync.client import connect
        except ImportError as exc:  # pragma: no cover - bundled backend dependency
            raise AcceptanceError("websocket_client_missing") from exc
        cookie = api.client.cookies.get("maya_session")
        require(isinstance(cookie, str) and cookie, "session_cookie_missing")
        self._socket = connect(
            f"ws://{api.origin.removeprefix('http://')}/api/v1/debates/{debate_id}/events",
            origin=api.origin,
            additional_headers={"Cookie": f"maya_session={cookie}"},
            proxy=None,
            open_timeout=20,
        )
        self.debate_id = debate_id

    def close(self) -> None:
        self._socket.close()

    def _receive(self, timeout: float = 2.0) -> Mapping[str, Any]:
        try:
            raw = self._socket.recv(timeout=timeout)
        except TimeoutError as exc:
            raise AcceptanceError("websocket_timeout") from exc
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        require(isinstance(raw, str), "websocket_message")
        try:
            value = json.loads(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AcceptanceError("websocket_message") from exc
        return _safe_json(value, "websocket_message")

    def _wait(
        self,
        *,
        event_type: str | None = None,
        message_type: str | None = None,
        turn_id: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            event = self._receive(timeout=min(2.0, max(0.1, deadline - time.monotonic())))
            if event_type is not None and event.get("event_type") != event_type:
                continue
            if message_type is not None and event.get("message_type") != message_type:
                continue
            payload = event.get("payload")
            if turn_id is not None:
                turn_value = (
                    payload.get("turn_id")
                    if isinstance(payload, dict)
                    else event.get("turn_id")
                )
                if str(turn_value) != turn_id:
                    continue
            return event
        raise AcceptanceError("websocket_event_timeout")

    def _send(self, value: Mapping[str, Any]) -> None:
        self._socket.send(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    def acquire(self, expected_control_version: int) -> str:
        command_id = str(uuid4())
        self._send(
            {
                "command_id": command_id,
                "command_type": "playback.controller.acquire",
                "command_version": 1,
                "debate_id": self.debate_id,
                "expected_control_version": expected_control_version,
            }
        )
        result = self._wait(message_type="controller.acquired")
        epoch = result.get("controller_epoch")
        require(isinstance(epoch, str) and UUID_RE.fullmatch(epoch) is not None, "controller_epoch")
        return epoch

    def prepare(
        self,
        *,
        epoch: str,
        expected_control_version: int,
        turn_id: str,
        action: str,
    ) -> str:
        command_id = str(uuid4())
        self._send(
            {
                "command_id": command_id,
                "command_type": "playback.media.prepare",
                "command_version": 1,
                "debate_id": self.debate_id,
                "expected_control_version": expected_control_version,
                "controller_epoch": epoch,
                "turn_id": turn_id,
                "playback_action": action,
            }
        )
        result = self._wait(message_type="media.prepared", turn_id=turn_id)
        media_url = result.get("media_url")
        require(
            isinstance(media_url, str)
            and media_url.startswith(f"/api/v1/debates/{self.debate_id}/audio/"),
            "media_url",
        )
        return media_url

    def started(self, *, epoch: str, expected_control_version: int, turn_id: str) -> None:
        self._send(
            {
                "command_id": str(uuid4()),
                "command_type": "playback.started_ack",
                "command_version": 1,
                "debate_id": self.debate_id,
                "expected_control_version": expected_control_version,
                "controller_epoch": epoch,
                "turn_id": turn_id,
                "playback_action": "start" if not hasattr(self, "_started_once") else "next",
            }
        )
        self._started_once = True
        self._wait(event_type="playback.started", turn_id=turn_id)

    def ended(self, *, epoch: str, expected_control_version: int, turn_id: str) -> None:
        self._send(
            {
                "command_id": str(uuid4()),
                "command_type": "playback.ended_ack",
                "command_version": 1,
                "debate_id": self.debate_id,
                "expected_control_version": expected_control_version,
                "controller_epoch": epoch,
                "turn_id": turn_id,
            }
        )
        self._wait(event_type="playback.waiting_next")


def _fetch_audio(api: Api, media_url: str) -> None:
    """Exercise the retained media boundary without printing the ticket."""

    try:
        response = api.client.get(
            media_url,
            headers={"Origin": api.origin, "X-CSRF-Token": api.csrf},
        )
    except httpx.HTTPError as exc:
        raise AcceptanceError("audio_transport") from exc
    require(response.status_code == 200, "audio_not_retained")
    require(response.headers.get("content-type", "").startswith("audio/wav"), "audio_type")
    require(bool(response.content), "audio_empty")


def _verify_turn_evidence(connection: Any, row: Any) -> None:
    """Reconcile one turn's receipts, trace rows and persisted sources."""

    from sqlalchemy import text

    turn_id = str(row["id"])
    snapshot_id = str(row["knowledge_snapshot_id"])
    speech = row["speech"]
    require(isinstance(speech, str) and speech.strip(), "speech_missing")
    require(CJK_RE.search(speech) is None, "speech_not_english_safe")
    try:
        receipts = json.loads(str(row["retrieval_receipts_json"]))
        traces = json.loads(str(row["evidence_trace_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceError("evidence_json_invalid") from exc
    require(isinstance(receipts, list) and isinstance(traces, list), "evidence_json_shape")
    receipt_by_id: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        require(isinstance(receipt, dict), "receipt_shape")
        evidence_id = receipt.get("evidence_id")
        require(isinstance(evidence_id, str) and evidence_id, "receipt_evidence_id")
        require(evidence_id not in receipt_by_id, "receipt_duplicate")
        require(receipt.get("snapshot_id") == snapshot_id, "receipt_snapshot")
        require(isinstance(receipt.get("chunk_id"), str), "receipt_chunk")
        require(isinstance(receipt.get("source_filename"), str), "receipt_filename")
        receipt_by_id[evidence_id] = receipt
    sources = connection.execute(
        text(
            "SELECT evidence_id,chunk_id,snapshot_id,source_filename FROM turn_sources "
            "WHERE turn_id=:turn_id ORDER BY rank,evidence_id"
        ),
        {"turn_id": turn_id},
    ).mappings().all()
    source_by_id: dict[str, Mapping[str, Any]] = {}
    for source in sources:
        evidence_id = str(source["evidence_id"])
        require(evidence_id not in source_by_id, "source_duplicate")
        source_by_id[evidence_id] = source
        receipt = receipt_by_id.get(evidence_id)
        require(receipt is not None, "source_receipt_missing")
        require(
            (str(source["chunk_id"]), str(source["snapshot_id"]), str(source["source_filename"]))
            == (
                str(receipt["chunk_id"]),
                snapshot_id,
                str(receipt["source_filename"]),
            ),
            "source_receipt_mismatch",
        )
    require(set(source_by_id) == set(receipt_by_id), "source_receipt_set_mismatch")
    traced_source_ids: set[str] = set()
    for trace in traces:
        require(isinstance(trace, dict), "trace_shape")
        support_mode = trace.get("support_mode")
        require(
            support_mode in {"direct", "contextual", "general_reasoning", "no_match"},
            "trace_support_mode",
        )
        evidence_id = trace.get("evidence_id")
        source_fields = ("evidence_id", "chunk_id", "source_filename")
        if support_mode in {"direct", "contextual"}:
            require(isinstance(evidence_id, str) and evidence_id, "trace_evidence_id")
            receipt = receipt_by_id.get(evidence_id)
            source = source_by_id.get(evidence_id)
            require(receipt is not None and source is not None, "trace_source_missing")
            require(
                (trace.get("chunk_id"), trace.get("source_filename"))
                == (receipt["chunk_id"], receipt["source_filename"]),
                "trace_receipt_mismatch",
            )
            require(
                str(source["snapshot_id"]) == snapshot_id
                and str(source["chunk_id"]) == str(trace["chunk_id"])
                and str(source["source_filename"]) == str(trace["source_filename"]),
                "trace_source_mismatch",
            )
            traced_source_ids.add(evidence_id)
        else:
            require(
                all(trace.get(field) is None for field in source_fields),
                "trace_unsourced_fields",
            )
    require(traced_source_ids == set(source_by_id), "source_trace_set_mismatch")


def _mark_provider_call(
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    gate: SevenCallGate,
    kind: str,
) -> None:
    """Advance the local count only after the product request has returned."""

    if kind == "snapshot":
        gate.call_snapshot()
        checkpoint["snapshot_calls"] = gate.snapshot_calls
    elif kind == "real_query":
        gate.call_query()
        checkpoint["real_query_calls"] = gate.real_query_calls
    elif kind == "llm":
        gate.call_llm()
        checkpoint["llm_calls"] = gate.llm_calls
    else:  # pragma: no cover - closed driver call kinds
        raise AcceptanceError("call_kind")
    checkpoint["next_call"] = "none"
    write_checkpoint(checkpoint_path, checkpoint)


def execute(
    base_url: str,
    checkpoint_path: Path,
    embedding_policy_hash: str,
    llm_policy_hash: str,
    student_password: str,
    teacher_password: str,
) -> Mapping[str, Any]:
    """Reject the superseded seven-call path until the Real plan is frozen."""

    require(REAL_PLAN_FROZEN, "real_plan_not_frozen")

    require(HASH_RE.fullmatch(embedding_policy_hash) is not None, "embedding_policy_hash")
    require(HASH_RE.fullmatch(llm_policy_hash) is not None, "llm_policy_hash")
    fixture = load_fixture()
    checkpoint = dict(read_checkpoint(checkpoint_path, fixture))
    require(checkpoint["state"] == "prepared", "checkpoint_already_consumed")
    require(
        checkpoint["snapshot_calls"] == 0
        and checkpoint["real_query_calls"] == 0
        and checkpoint["llm_calls"] == 0,
        "checkpoint_call_counts",
    )
    checkpoint["state"] = "executing"
    checkpoint["next_call"] = "snapshot"
    write_checkpoint(checkpoint_path, checkpoint)
    student, teacher = Api(base_url), Api(base_url)
    gate = SevenCallGate()
    socket: PlaybackSocket | None = None
    try:
        student.login(
            os.environ.get("MAYA_STUDENT_USERNAME", "student-bowen-1"), student_password
        )
        teacher.login(os.environ.get("MAYA_TEACHER_USERNAME", "teacher-demo"), teacher_password)
        _assert_checkpoint_baseline(teacher, checkpoint)
        real_version_id = str(checkpoint["real_version_id"])
        publish_key = f"real-core-demo-real-publish-{real_version_id}"

        # The first publish request only stages and exposes the exact Snapshot
        # manifest. It must not call the Provider until the teacher confirms.
        _status, blocked = student.request(
            "POST",
            f"/api/v1/agent-versions/{real_version_id}/publish",
            expected={409},
            body={"expected_revision": int(checkpoint["real_revision"])},
            key=publish_key,
        )
        require(blocked.get("code") == "provider_confirmation_required", "snapshot_not_blocked")
        _status, pending = teacher.request(
            "GET",
            f"/api/v1/provider/data-call/pending/agent-versions/{real_version_id}",
            expected={200},
        )
        items = pending.get("items")
        require(
            isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict),
            "snapshot_manifest",
        )
        _confirm_manifest(teacher, items[0], expected_policy_hash=embedding_policy_hash)
        gate.confirm_snapshot()
        checkpoint["next_call"] = "snapshot"
        write_checkpoint(checkpoint_path, checkpoint)
        _status, published = student.request(
            "POST",
            f"/api/v1/agent-versions/{real_version_id}/publish",
            expected={200},
            body={"expected_revision": int(checkpoint["real_revision"])},
            key=publish_key,
        )
        _mark_provider_call(checkpoint, checkpoint_path, gate, "snapshot")
        snapshot_id = opaque(published.get("knowledge_snapshot_id"), "snapshot_id")
        checkpoint["snapshot_id"] = snapshot_id
        write_checkpoint(checkpoint_path, checkpoint)

        # The server-owned baseline is Mock and immutable; only target B's
        # published real Snapshot can consume real query calls.
        _status, debate = teacher.request(
            "POST",
            f"/api/v1/courses/{checkpoint['course_id']}/debates",
            expected={201},
            body={
                "topic": fixture.topic,
                "participants": [
                    {"agent_id": checkpoint["baseline_agent_id"], "stance_mode": "open"},
                    {"agent_id": checkpoint["real_agent_id"], "stance_mode": "open"},
                ],
                "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
                "round_count": 2,
            },
            key="real-core-demo-create-debate-0001",
        )
        debate_id = opaque(debate.get("id"), "debate_id")
        checkpoint["debate_id"] = debate_id
        write_checkpoint(checkpoint_path, checkpoint)
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/start",
            expected={200},
            body={
                "expected_revision": debate.get("revision"),
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
            key="real-core-demo-start-debate-0001",
        )
        socket = PlaybackSocket(teacher, debate_id)
        detail = _debate_detail(teacher, debate_id)
        playback = detail["playback"]
        expected_control_version = playback.get("control_version")
        require(isinstance(expected_control_version, int), "control_version")
        epoch = socket.acquire(expected_control_version)

        for turn_index in range(4):
            # The frozen mutual-learning order is A, B, A, B. Slot B is the
            # sole real Snapshot participant, hence exactly two real queries.
            if turn_index in {1, 3}:
                detail = _debate_detail(teacher, debate_id)
                turn_id = opaque(detail["playback"].get("current_turn_id"), "turn_id")
                checkpoint["current_turn_id"] = turn_id
                checkpoint["next_call"] = "real_query"
                write_checkpoint(checkpoint_path, checkpoint)
                query_item = _wait_pending(
                    teacher,
                    f"/api/v1/provider/data-call/pending?scope_id={debate_id}",
                    current_turn_id=turn_id,
                )
                _confirm_manifest(teacher, query_item, expected_policy_hash=embedding_policy_hash)
                gate.confirm_query()
                _retry_preparation(
                    teacher,
                    debate_id,
                    turn_id,
                    key=f"real-core-demo-query-retry-{turn_index + 1:02d}",
                )
                _mark_provider_call(checkpoint, checkpoint_path, gate, "real_query")
            else:
                detail = _debate_detail(teacher, debate_id)
                turn_id = opaque(detail["playback"].get("current_turn_id"), "turn_id")
                checkpoint["current_turn_id"] = turn_id
                write_checkpoint(checkpoint_path, checkpoint)

            # Query success (or a Mock Snapshot) exposes the exact one-shot
            # LLM manifest. Confirm it before retrying generation.
            llm_item: Mapping[str, Any] | None = None
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                llm_item = _pending_item(
                    teacher,
                    path=f"/api/v1/provider/data-call/pending/debates/{debate_id}",
                    current_turn_id=turn_id,
                )
                if llm_item is not None:
                    break
                detail = _debate_detail(teacher, debate_id)
                current_playback = detail["playback"]
                if (
                    current_playback.get("status") == "ready"
                    and str(current_playback.get("current_turn_id")) == turn_id
                ):
                    break
                time.sleep(0.2)
            if llm_item is not None:
                _confirm_manifest(teacher, llm_item, expected_policy_hash=llm_policy_hash)
                gate.confirm_llm()
                checkpoint["next_call"] = "llm"
                write_checkpoint(checkpoint_path, checkpoint)
                _retry_preparation(
                    teacher,
                    debate_id,
                    turn_id,
                    key=f"real-core-demo-llm-retry-{turn_index + 1:02d}",
                )
            ready = _wait_turn_ready(teacher, debate_id)
            ready_playback = ready["playback"]
            ready_turn_id = opaque(ready_playback.get("current_turn_id"), "turn_id")
            require(ready_turn_id == turn_id, "turn_order")
            _mark_provider_call(checkpoint, checkpoint_path, gate, "llm")

            media_url = socket.prepare(
                epoch=epoch,
                expected_control_version=int(ready_playback["control_version"]),
                turn_id=turn_id,
                action="start" if turn_index == 0 else "next",
            )
            _fetch_audio(teacher, media_url)
            socket.started(
                epoch=epoch,
                expected_control_version=int(ready_playback["control_version"]),
                turn_id=turn_id,
            )
            socket.ended(
                epoch=epoch,
                expected_control_version=int(ready_playback["control_version"]),
                turn_id=turn_id,
            )
            checkpoint["completed_turns"] = [
                *list(checkpoint["completed_turns"]),
                turn_id,
            ]
            checkpoint["current_turn_id"] = turn_id
            write_checkpoint(checkpoint_path, checkpoint)

            if turn_index < 3:
                after_end = _debate_detail(teacher, debate_id)
                after_playback = after_end["playback"]
                require(after_playback.get("status") == "waiting_next", "waiting_next")
                next_version = after_playback.get("control_version")
                require(isinstance(next_version, int), "control_version")
                _status, advanced = teacher.request(
                    "POST",
                    f"/api/v1/debates/{debate_id}/next",
                    expected={200},
                    body={
                        "expected_control_version": next_version,
                        "expected_current_turn_id": turn_id,
                    },
                )
                require(advanced.get("status") in {"ready", "preparing"}, "next_state")

        finished = _debate_detail(teacher, debate_id)
        finished_playback = finished["playback"]
        finish_version = finished_playback.get("control_version")
        require(isinstance(finish_version, int), "control_version")
        teacher.request(
            "POST",
            f"/api/v1/debates/{debate_id}/finish",
            expected={200},
            body={
                "expected_control_version": finish_version,
                "expected_current_turn_id": finished_playback.get("current_turn_id"),
            },
            key="real-core-demo-finish-0001",
        )
        _status, transcript = teacher.request(
            "GET",
            f"/api/v1/debates/{debate_id}/transcript",
            expected={200},
        )
        turns = transcript.get("turns")
        require(isinstance(turns, list) and len(turns) == 4, "turn_count")
        checkpoint["state"] = "executed"
        checkpoint["next_call"] = "none"
        write_checkpoint(checkpoint_path, checkpoint)
        return {
            "status": "REAL_CORE_DEMO_EXECUTED_PENDING_OFFLINE_VERIFY",
            "fixture_hash": fixture.fixture_hash,
            **gate.result(),
        }
    finally:
        if socket is not None:
            socket.close()
        student.close()
        teacher.close()


def verify(
    database_url: str,
    checkpoint_path: Path,
    embedding_policy_hash: str,
    llm_policy_hash: str,
) -> Mapping[str, Any]:
    """Reject verification until the replacement Real plan is frozen."""

    require(REAL_PLAN_FROZEN, "real_plan_not_frozen")

    require(database_url.startswith("sqlite:"), "database_url")
    require(HASH_RE.fullmatch(embedding_policy_hash) is not None, "embedding_policy_hash")
    require(HASH_RE.fullmatch(llm_policy_hash) is not None, "llm_policy_hash")
    fixture = load_fixture()
    checkpoint = dict(read_checkpoint(checkpoint_path, fixture))
    require(checkpoint["state"] == "executed", "checkpoint_not_executed")
    require(checkpoint["snapshot_id"] and checkpoint["debate_id"], "checkpoint_ids")
    require(
        checkpoint["snapshot_id"] != checkpoint["baseline_snapshot_id"],
        "snapshot_baseline_collision",
    )
    require(checkpoint["snapshot_calls"] == 1, "checkpoint_snapshot_calls")
    require(checkpoint["real_query_calls"] == 2, "checkpoint_query_calls")
    require(checkpoint["llm_calls"] == 4, "checkpoint_llm_calls")
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from app.core.db import Database
    from sqlalchemy import text

    database = Database(database_url)
    try:
        with database.engine.connect() as connection:
            snapshot = connection.execute(
                text(
                    "SELECT embedding_provider,embedding_model_key,embedding_region,"
                    "embedding_dimension,embedding_policy_version FROM knowledge_snapshots "
                    "WHERE id=:snapshot_id AND agent_version_id=:version_id"
                ),
                {
                    "snapshot_id": checkpoint["snapshot_id"],
                    "version_id": checkpoint["real_version_id"],
                },
            ).one_or_none()
            require(
                snapshot
                == ("dashscope", "text-embedding-v4", "cn-beijing", 1024, "w4-embed-v1"),
                "snapshot_identity",
            )
            baseline_row = connection.execute(
                text(
                    "SELECT a.current_published_version_id,av.state,av.knowledge_snapshot_id "
                    "FROM agents a JOIN agent_versions av ON av.id=a.current_published_version_id "
                    "WHERE a.id=:agent_id"
                ),
                {"agent_id": checkpoint["baseline_agent_id"]},
            ).one_or_none()
            require(
                baseline_row
                == (
                    checkpoint["baseline_version_id"],
                    "published",
                    checkpoint["baseline_snapshot_id"],
                ),
                "baseline_binding",
            )
            participants = connection.execute(
                text(
                    "SELECT agent_id,agent_version_id,knowledge_snapshot_id,slot,order_index "
                    "FROM debate_participants WHERE debate_id=:debate_id ORDER BY order_index"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(
                participants
                == [
                    (
                        checkpoint["baseline_agent_id"],
                        checkpoint["baseline_version_id"],
                        checkpoint["baseline_snapshot_id"],
                        "A",
                        0,
                    ),
                    (
                        checkpoint["real_agent_id"],
                        checkpoint["real_version_id"],
                        checkpoint["snapshot_id"],
                        "B",
                        1,
                    ),
                ],
                "participant_bindings",
            )
            dirty_counts = (
                connection.execute(
                    text("SELECT COUNT(*) FROM agents WHERE id != :agent_id"),
                    {"agent_id": checkpoint["baseline_agent_id"]},
                ).scalar_one(),
                connection.execute(text("SELECT COUNT(*) FROM debates")).scalar_one(),
                connection.execute(
                    text("SELECT COUNT(*) FROM classroom_interaction_windows")
                ).scalar_one(),
            )
            require(tuple(map(int, dirty_counts)) == (1, 1, 1), "dirty_counts")
            snapshot_ops = connection.execute(
                text(
                    "SELECT po.state,po.request_count,po.charged_request_count,po.attempt_no "
                    "FROM provider_operations po JOIN provider_export_manifests m "
                    "ON m.scope_id=po.scope_id WHERE m.agent_version_id=:version_id "
                    "AND m.provider_operation='embedding' "
                    "AND po.provider_operation IN ('embedding','embedding_snapshot')"
                ),
                {"version_id": checkpoint["real_version_id"]},
            ).all()
            require(snapshot_ops == [("succeeded", 1, 1, 1)], "snapshot_ledger_count")

            query_ops = connection.execute(
                text(
                    "SELECT po.state,po.request_count,po.charged_request_count,po.attempt_no,"
                    "dt.turn_index FROM provider_operations po "
                    "JOIN debate_turns dt ON po.logical_item_id='turn:' || dt.id "
                    "WHERE po.scope_id=:debate_id AND po.provider_operation='embedding_query' "
                    "ORDER BY dt.turn_index"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(
                query_ops == [
                    ("succeeded", 1, 1, 1, 0),
                    ("succeeded", 1, 1, 1, 2),
                ],
                "query_ledger_count",
            )
            query_policies = connection.execute(
                text(
                    "SELECT DISTINCT policy_hash FROM provider_export_manifests "
                    "WHERE scope_id=:debate_id AND provider_operation='embedding_query'"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(query_policies == [(embedding_policy_hash,)], "query_policy_binding")

            llm_ops = connection.execute(
                text(
                    "SELECT state,request_count,charged_request_count,attempt_no "
                    "FROM provider_operations WHERE scope_id=:debate_id "
                    "AND provider_operation='llm_debate_turn' ORDER BY logical_item_id"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(
                llm_ops == [("succeeded", 1, 1, 1)] * 4,
                "llm_ledger_count",
            )
            llm_manifests = connection.execute(
                text(
                    "SELECT policy_hash,max_attempts,repair_policy_version,repair_policy_hash "
                    "FROM provider_export_manifests WHERE debate_id=:debate_id "
                    "AND provider_operation='llm_debate_turn' ORDER BY turn_id"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(
                llm_manifests == [(llm_policy_hash, 1, None, None)] * 4,
                "llm_manifest_policy",
            )

            turns = connection.execute(
                text(
                    "SELECT id,turn_index,participant_id,knowledge_snapshot_id,speech,"
                    "generation_status,retrieval_status,"
                    "retrieval_receipts_json,evidence_trace_json FROM debate_turns "
                    "WHERE debate_id=:debate_id ORDER BY turn_index"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).mappings().all()
            require(len(turns) == 4, "turn_count")
            require(
                all(
                    row["generation_status"] == "final_ready"
                    and row["retrieval_status"] == "matched"
                    for row in turns
                ),
                "turn_status",
            )
            for row in turns:
                _verify_turn_evidence(connection, row)
            require(
                [int(row["turn_index"]) for row in turns] == [0, 1, 2, 3],
                "turn_order",
            )
            real_participant_ids = connection.execute(
                text(
                    "SELECT participant_id FROM debate_turns WHERE debate_id=:debate_id "
                    "AND turn_index IN (1,3) ORDER BY turn_index"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            query_participant_ids = connection.execute(
                text(
                    "SELECT dt.participant_id FROM provider_operations po "
                    "JOIN debate_turns dt ON po.logical_item_id='turn:' || dt.id "
                    "WHERE po.scope_id=:debate_id AND po.provider_operation='embedding_query' "
                    "ORDER BY dt.turn_index"
                ),
                {"debate_id": checkpoint["debate_id"]},
            ).all()
            require(query_participant_ids == real_participant_ids, "query_real_participant_only")
            source = connection.execute(
                text(
                    "SELECT COUNT(*) FROM turn_sources ts JOIN debate_turns dt ON dt.id=ts.turn_id "
                    "WHERE dt.debate_id=:debate_id AND ts.source_filename=:filename"
                ),
                {
                    "debate_id": checkpoint["debate_id"],
                    "filename": fixture.manifest["snapshot_document_filename"],
                },
            ).scalar_one()
            require(int(source) >= 2, "turn_source_binding")
    finally:
        database.dispose()
    checkpoint["state"] = "verified"
    checkpoint["next_call"] = "none"
    write_checkpoint(checkpoint_path, checkpoint)
    return {
        "status": "REAL_CORE_DEMO_E2E_PASS",
        "fixture_hash": fixture.fixture_hash,
        "snapshot_calls": 1,
        "real_query_calls": 2,
        "llm_calls": 4,
        "total_calls": 7,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--checkpoint", type=Path, required=True)
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("--checkpoint", type=Path, required=True)
    execute_parser.add_argument("--embedding-policy-hash", required=True)
    execute_parser.add_argument("--llm-policy-hash", required=True)
    execute_parser.add_argument("--confirm-seven-call-cap", action="store_true", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--checkpoint", type=Path, required=True)
    verify_parser.add_argument("--database-url", required=True)
    verify_parser.add_argument("--embedding-policy-hash", required=True)
    verify_parser.add_argument("--llm-policy-hash", required=True)
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
                "snapshot_calls": 0,
                "real_query_calls": 0,
                "llm_calls": 0,
                "total_calls": 0,
            }
        else:
            base_url = os.environ.get("MAYA_BASE_URL", "")
            if args.command == "prepare":
                student_password = os.environ.get("MAYA_STUDENT_PASSWORD", "")
                require(bool(student_password), "student_password_missing")
                value = prepare(base_url, args.checkpoint, student_password)
            elif args.command == "execute":
                require(REAL_PLAN_FROZEN, "real_plan_not_frozen")
                student_password = os.environ.get("MAYA_STUDENT_PASSWORD", "")
                teacher_password = os.environ.get("MAYA_TEACHER_PASSWORD", "")
                require(
                    args.confirm_seven_call_cap
                    and bool(student_password)
                    and bool(teacher_password),
                    "real_confirmation_missing",
                )
                value = execute(
                    base_url,
                    args.checkpoint,
                    args.embedding_policy_hash,
                    args.llm_policy_hash,
                    student_password,
                    teacher_password,
                )
            else:
                require(REAL_PLAN_FROZEN, "real_plan_not_frozen")
                value = verify(
                    args.database_url,
                    args.checkpoint,
                    args.embedding_policy_hash,
                    args.llm_policy_hash,
                )
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0
    except (AcceptanceError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, AcceptanceError) else "acceptance_failed"
        print(json.dumps({"status": "FAILED", "safe_error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
