"""Bounded Real-Core Demo acceptance driver.

The driver keeps the product's natural call semantics: one real Snapshot
embedding, two real participant queries and four real debate-turn LLM calls.
The accepted budget is eight calls so the later Report call has a reserved
ordinal; the debate stage therefore ends at seven without treating seven as a
terminal plan. Snapshot Call1 is bound atomically by both identical publish
requests; later query/debate/report manifests are attached to the teacher-only
acceptance run before their continuations.
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
CHECKPOINT_VERSION = "real-core-demo-checkpoint-v4"
DEBATE_STAGE_CALLS = 7
EXPECTED_HAPPY_PATH_CALLS = 8
MAX_ACCEPTANCE_CALLS = 8
REPORT_READY_WORDS = range(600, 901)
REPORT_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019\-][A-Za-z0-9]+)*")
REPORT_CITATION_RE = re.compile(
    r"\[evidence:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\]"
)
REPORT_UNSAFE_RE = re.compile(
    r"\b(?:winner|winners|won|winning|vote\s+for\s+me|please\s+vote|nickname)\b",
    re.IGNORECASE,
)
BASELINE_FIELDS = {
    "agent_id",
    "version_id",
    "snapshot_id",
    "group_id",
    "system_baseline",
    "immutable",
    "usable",
}
ACCEPTANCE_RUN_FIELDS = {
    "id",
    "plan_version",
    "fixture_hash",
    "baseline_agent_id",
    "baseline_version_id",
    "baseline_snapshot_id",
    "target_agent_id",
    "target_version_id",
    "debate_id",
    "report_revision_id",
    "state",
    "starting_charged_requests",
    "call_count",
    "charged_request_count",
}
ACCEPTANCE_RUN_STATES = {"prepared", "executing", "executed", "verified"}
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
    "report_revision_id",
    "current_turn_id",
    "snapshot_calls",
    "real_query_calls",
    "llm_calls",
    "report_calls",
    "completed_turns",
    "bound_manifest_hashes",
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
        manifest["call_cap"]
        == {
            "snapshot": 1,
            "real_query": 2,
            "llm_turn": 4,
            "report": 1,
            "debate_stage": DEBATE_STAGE_CALLS,
            "expected_happy_path": EXPECTED_HAPPY_PATH_CALLS,
            "max_ceiling": MAX_ACCEPTANCE_CALLS,
            "total": EXPECTED_HAPPY_PATH_CALLS,
        },
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
        allow_list: bool = False,
    ) -> tuple[int, Any]:
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
        try:
            value = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise AcceptanceError("response_json") from exc
        require(
            isinstance(value, dict) or (allow_list and isinstance(value, list)),
            "response_shape",
        )
        if response.status_code not in expected:
            # Error envelopes are reduced to stable safe codes.  In
            # particular, a provider acceptance uncertainty is terminal for
            # this run and must never enter an automatic retry path.
            provider_code = value.get("code") if isinstance(value, dict) else None
            if isinstance(provider_code, str):
                if "acceptance_unknown" in provider_code:
                    raise AcceptanceError("acceptance_unknown")
                if provider_code in {
                    "provider_failed",
                    "provider_reservation_failed",
                    "provider_response_failed",
                    "report_provider_failed",
                } or provider_code.endswith("_provider_failed"):
                    raise AcceptanceError("provider_failed")
            raise AcceptanceError(f"http_{response.status_code}")
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

    def create_acceptance_run(
        self,
        *,
        fixture_hash: str,
        target_agent_id: str,
        target_version_id: str,
    ) -> Mapping[str, Any]:
        """Create the fresh teacher-owned run immediately before real work."""

        _status, value = self.request(
            "POST",
            "/api/v1/demo/acceptance-runs",
            expected={201},
            body={
                "fixture_hash": fixture_hash,
                "target_agent_id": target_agent_id,
                "target_version_id": target_version_id,
            },
            key="real-core-demo-create-acceptance-run",
        )
        return value

    def bind_acceptance_debate(self, run_id: str, debate_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            f"/api/v1/demo/acceptance-runs/{run_id}/debate",
            expected={200},
            body={"debate_id": debate_id},
            key=f"real-core-demo-bind-debate-{debate_id}",
        )
        return value

    def bind_acceptance_report(self, run_id: str, report_revision_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            f"/api/v1/demo/acceptance-runs/{run_id}/report",
            expected={200},
            body={"report_revision_id": report_revision_id},
            key=f"real-core-demo-bind-report-{report_revision_id}",
        )
        return value

    def acceptance_summary(self, run_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "GET", f"/api/v1/demo/acceptance-runs/{run_id}/summary", expected={200}
        )
        return value

    def attach_acceptance_call(
        self,
        run_id: str,
        *,
        manifest_hash: str,
        call_no: int,
    ) -> Mapping[str, Any]:
        """Bind one exact pending manifest to the next bounded ordinal.

        The pending DTO intentionally does not expose a Provider operation ID;
        the server resolves the unique pre-send operation by this manifest
        hash.  This call is made before disclosure confirmation and before the
        explicit preparation continuation.
        """

        _status, value = self.request(
            "POST",
            f"/api/v1/demo/acceptance-runs/{run_id}/calls",
            expected={200},
            body={"manifest_hash": manifest_hash, "call_no": call_no},
            key=f"real-core-demo-attach-call-{call_no:02d}",
        )
        return value

    def open_interaction(self, debate_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            f"/api/v1/debates/{debate_id}/interaction/open",
            expected={200},
            key=f"real-core-demo-open-interaction-{debate_id}",
        )
        return value

    def close_interaction(self, debate_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            f"/api/v1/debates/{debate_id}/interaction/close",
            expected={202},
            key=f"real-core-demo-close-interaction-{debate_id}",
        )
        return value

    def pending_report_manifests(self, debate_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "GET",
            f"/api/v1/provider/data-call/pending/reports/{debate_id}",
            expected={200},
        )
        return value

    def report_revisions(self, debate_id: str) -> list[Mapping[str, Any]]:
        _status, value = self.request(
            "GET",
            f"/api/v1/debates/{debate_id}/report/revisions",
            expected={200},
            allow_list=True,
        )
        require(isinstance(value, list), "report_revisions_shape")
        require(all(isinstance(item, dict) for item in value), "report_revision_shape")
        return value

    def continue_report(
        self,
        debate_id: str,
        revision_id: str,
        *,
        manifest_hash: str,
        call_no: int,
    ) -> Mapping[str, Any]:
        _status, value = self.request(
            "POST",
            f"/api/v1/debates/{debate_id}/report/revisions/{revision_id}/continue",
            expected={202},
            body={"manifest_hash": manifest_hash, "call_no": call_no},
            key=f"real-core-demo-report-continue-{revision_id}",
        )
        return value

    def report_revision(self, debate_id: str, revision_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "GET",
            f"/api/v1/debates/{debate_id}/report/revisions/{revision_id}",
            expected={200},
        )
        return value

    def transcript(self, debate_id: str) -> Mapping[str, Any]:
        _status, value = self.request(
            "GET", f"/api/v1/debates/{debate_id}/transcript", expected={200}
        )
        return value


def opaque(value: Any, code: str) -> str:
    require(isinstance(value, str) and UUID_RE.fullmatch(value) is not None, code)
    return value


def _validated_acceptance_run(
    value: Mapping[str, Any],
    *,
    fixture: Fixture,
    checkpoint: Mapping[str, Any],
    expected_call_count: int | None = None,
    expected_debate_id: str | None = None,
) -> Mapping[str, Any]:
    """Validate the safe run summary and its bounded counters."""

    require(set(value) == ACCEPTANCE_RUN_FIELDS, "acceptance_run_shape")
    run_id = opaque(value.get("id"), "acceptance_run_id")
    recorded_run_id = checkpoint.get("acceptance_run_id")
    if recorded_run_id is not None:
        require(recorded_run_id == run_id, "acceptance_run_mismatch")
    require(value.get("plan_version") == "real_core_demo_v2", "acceptance_run_plan")
    require(value.get("fixture_hash") == fixture.fixture_hash, "acceptance_run_fixture")
    for field in (
        "baseline_agent_id",
        "baseline_version_id",
        "baseline_snapshot_id",
        "target_agent_id",
        "target_version_id",
    ):
        opaque(value.get(field), f"acceptance_run_{field}")
    require(
        (
            value["baseline_agent_id"],
            value["baseline_version_id"],
            value["baseline_snapshot_id"],
        )
        == (
            checkpoint["baseline_agent_id"],
            checkpoint["baseline_version_id"],
            checkpoint["baseline_snapshot_id"],
        ),
        "acceptance_run_baseline",
    )
    require(
        (value["target_agent_id"], value["target_version_id"])
        == (checkpoint["real_agent_id"], checkpoint["real_version_id"]),
        "acceptance_run_target",
    )
    debate_id = value.get("debate_id")
    require(
        debate_id is None or UUID_RE.fullmatch(str(debate_id)) is not None,
        "acceptance_run_debate",
    )
    report_revision_id = value.get("report_revision_id")
    require(
        report_revision_id is None or UUID_RE.fullmatch(str(report_revision_id)) is not None,
        "acceptance_run_report",
    )
    recorded_report_revision = checkpoint.get("report_revision_id")
    if recorded_report_revision is not None:
        require(
            report_revision_id == recorded_report_revision,
            "acceptance_run_report_mismatch",
        )
    require(value.get("state") in ACCEPTANCE_RUN_STATES, "acceptance_run_state")
    require(value.get("starting_charged_requests") == 0, "acceptance_run_starting_charged")
    for field in ("call_count", "charged_request_count"):
        count = value.get(field)
        require(isinstance(count, int) and not isinstance(count, bool) and count >= 0, field)
    call_count = int(value["call_count"])
    charged_count = int(value["charged_request_count"])
    require(call_count <= MAX_ACCEPTANCE_CALLS, "acceptance_run_call_ceiling")
    require(charged_count <= call_count, "acceptance_run_charge_count")
    if expected_call_count is not None:
        require(call_count == expected_call_count, "acceptance_run_call_count")
    if expected_debate_id is not None:
        require(debate_id == expected_debate_id, "acceptance_run_debate")
    require(bool(run_id), "acceptance_run_id")
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
    require(value["version"] == CHECKPOINT_VERSION, "checkpoint_version")
    require(value["fixture_hash"] == fixture.fixture_hash, "checkpoint_fixture")
    require(value["state"] in CHECKPOINT_STATES, "checkpoint_state")
    require(
        value["acceptance_run_id"] is None
        or UUID_RE.fullmatch(str(value["acceptance_run_id"])) is not None,
        "checkpoint_acceptance_run_id",
    )
    if value["state"] != "prepared":
        require(value["acceptance_run_id"] is not None, "checkpoint_acceptance_run_id")
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
        value["report_revision_id"] is None
        or UUID_RE.fullmatch(str(value["report_revision_id"])) is not None,
        "checkpoint_report_revision_id",
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
    for field in ("snapshot_calls", "real_query_calls", "llm_calls", "report_calls"):
        require(isinstance(value[field], int) and value[field] >= 0, f"checkpoint_{field}")
    require(
        isinstance(value["completed_turns"], list)
        and all(UUID_RE.fullmatch(str(item)) is not None for item in value["completed_turns"]),
        "checkpoint_turns",
    )
    require(
        isinstance(value["bound_manifest_hashes"], list), "checkpoint_bound_manifests"
    )
    require(
        len(value["bound_manifest_hashes"]) <= MAX_ACCEPTANCE_CALLS,
        "checkpoint_bound_manifests",
    )
    bound_hashes: list[str] = []
    for item in value["bound_manifest_hashes"]:
        require(HASH_RE.fullmatch(str(item)) is not None, "checkpoint_bound_manifest")
        require(str(item) not in bound_hashes, "checkpoint_bound_manifest_duplicate")
        bound_hashes.append(str(item))
    require(
        value["snapshot_calls"]
        + value["real_query_calls"]
        + value["llm_calls"]
        + value["report_calls"]
        == len(bound_hashes),
        "checkpoint_call_counts",
    )
    require(
        value["next_call"] in {"none", "snapshot", "real_query", "llm", "report"},
        "checkpoint_next_call",
    )
    return value


def _base_checkpoint(
    fixture: Fixture,
    *,
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
        "version": CHECKPOINT_VERSION,
        "state": "prepared",
        "acceptance_run_id": None,
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
        "report_revision_id": None,
        "current_turn_id": None,
        "snapshot_calls": 0,
        "real_query_calls": 0,
        "llm_calls": 0,
        "report_calls": 0,
        "completed_turns": [],
        "bound_manifest_hashes": [],
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
    # Pending manifests deliberately do not disclose provider operation IDs.
    # A driver must use the immutable manifest hash as the server-side lookup
    # key when attaching the call to its acceptance run.
    require("operation_id" not in item, "pending_operation_id_disclosed")
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
    require(disclosure.get("manifest_hash") == manifest_hash, "manifest_hash_mismatch")
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


def _attach_pending_call(
    api: Api,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    fixture: Fixture,
    *,
    manifest: Mapping[str, Any],
    kind: str,
) -> Mapping[str, Any]:
    """Attach one pending operation before confirmation or continuation.

    ``manifest_hash`` is the only operation identity available to this
    teacher-facing driver.  The run service resolves the unique prepared
    operation and rejects a duplicate or non-sequential ordinal atomically.
    """

    run_id = checkpoint.get("acceptance_run_id")
    require(isinstance(run_id, str), "acceptance_run_missing")
    manifest_hash = manifest.get("manifest_hash")
    require(isinstance(manifest_hash, str) and HASH_RE.fullmatch(manifest_hash), "pending_manifest")
    bound_hashes = checkpoint.get("bound_manifest_hashes")
    require(isinstance(bound_hashes, list), "checkpoint_bound_manifests")
    require(manifest_hash not in bound_hashes, "acceptance_operation_duplicate")
    call_no = len(bound_hashes) + 1
    require(call_no <= MAX_ACCEPTANCE_CALLS, "acceptance_budget_exceeded")
    expected_kind = {"snapshot", "real_query", "llm", "report"}
    require(kind in expected_kind, "call_kind")
    summary = api.attach_acceptance_call(
        run_id,
        manifest_hash=manifest_hash,
        call_no=call_no,
    )
    _validated_acceptance_run(
        summary,
        fixture=fixture,
        checkpoint=checkpoint,
        expected_call_count=call_no,
    )
    require(summary["charged_request_count"] == 0, "acceptance_call_already_charged")
    bound_hashes.append(manifest_hash)
    if kind == "snapshot":
        checkpoint["snapshot_calls"] = int(checkpoint["snapshot_calls"]) + 1
    elif kind == "real_query":
        checkpoint["real_query_calls"] = int(checkpoint["real_query_calls"]) + 1
    elif kind == "llm":
        checkpoint["llm_calls"] = int(checkpoint["llm_calls"]) + 1
    elif kind == "report":
        checkpoint["report_calls"] = int(checkpoint["report_calls"]) + 1
    checkpoint["next_call"] = kind
    write_checkpoint(checkpoint_path, checkpoint)
    return summary


def _snapshot_publish_body(*, acceptance_run_id: str, expected_revision: int) -> dict[str, object]:
    """Return the exact body reused for Snapshot discovery and publish."""

    return {
        "expected_revision": expected_revision,
        "acceptance_run_id": acceptance_run_id,
        "call_no": 1,
    }


def _assert_charged_summary(
    api: Api,
    checkpoint: Mapping[str, Any],
    fixture: Fixture,
    *,
    expected_call_count: int,
) -> Mapping[str, Any]:
    """Require the run summary to reflect all successful Provider charges."""

    run_id = checkpoint.get("acceptance_run_id")
    require(isinstance(run_id, str), "acceptance_run_missing")
    summary = api.acceptance_summary(run_id)
    _validated_acceptance_run(
        summary,
        fixture=fixture,
        checkpoint=checkpoint,
        expected_call_count=expected_call_count,
    )
    require(summary["charged_request_count"] == expected_call_count, "acceptance_charge_count")
    return summary


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


def _report_failure_code(value: Mapping[str, Any]) -> str | None:
    status = value.get("status")
    if status != "failed":
        return None
    safe_error_code = value.get("safe_error_code")
    if isinstance(safe_error_code, str) and "acceptance_unknown" in safe_error_code:
        return "acceptance_unknown"
    return "provider_failed"


def _wait_report_pending(
    api: Api,
    debate_id: str,
    *,
    timeout_seconds: float = 90.0,
) -> Mapping[str, Any]:
    """Wait until Mock insight has produced one paused Real Report revision."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        revisions = api.report_revisions(debate_id)
        for revision in revisions:
            failure = _report_failure_code(revision)
            if failure is not None:
                raise AcceptanceError(failure)
        pending = api.pending_report_manifests(debate_id)
        items = pending.get("items")
        require(isinstance(items, list), "report_pending_shape")
        if len(items) > 1:
            raise AcceptanceError("report_manifest_ambiguous")
        if len(items) == 1:
            item = items[0]
            require(isinstance(item, dict), "report_pending_shape")
            require("operation_id" not in item, "report_operation_id_disclosed")
            require(set(item) == {
                "report_revision_id",
                "manifest_hash",
                "confirmation_revision",
                "confirmed",
            }, "report_pending_shape")
            revision_id = item.get("report_revision_id")
            manifest_hash = item.get("manifest_hash")
            require(
                isinstance(revision_id, str) and UUID_RE.fullmatch(revision_id) is not None,
                "report_revision_id",
            )
            require(
                isinstance(manifest_hash, str) and HASH_RE.fullmatch(manifest_hash) is not None,
                "report_manifest_hash",
            )
            require(item.get("confirmed") is False, "report_manifest_confirmed")
            matching = [
                revision
                for revision in revisions
                if revision.get("id") == revision_id and revision.get("status") == "generating"
            ]
            if len(matching) == 1:
                return item
        time.sleep(0.2)
    raise AcceptanceError("report_manifest_timeout")


def _verify_ready_report(
    value: Mapping[str, Any],
    *,
    revision_id: str,
) -> Mapping[str, Any]:
    """Validate the safe report DTO without printing its Markdown body."""

    require(value.get("id") == revision_id, "report_revision_id")
    require(value.get("status") == "ready", "report_not_ready")
    word_count = value.get("word_count")
    require(
        isinstance(word_count, int)
        and not isinstance(word_count, bool)
        and word_count in REPORT_READY_WORDS,
        "report_word_count",
    )
    markdown = value.get("english_markdown")
    require(isinstance(markdown, str) and markdown.strip(), "report_markdown_missing")
    require(CJK_RE.search(markdown) is None, "report_not_english")
    require(re.search(r"[A-Za-z]", markdown) is not None, "report_not_english")
    require(REPORT_UNSAFE_RE.search(markdown) is None, "report_unsafe_term")
    countable_markdown = REPORT_CITATION_RE.sub("", markdown)
    require(
        len(REPORT_WORD_RE.findall(countable_markdown)) == word_count,
        "report_word_count_mismatch",
    )
    return value


def _read_history_replay_views(api: Api, debate_id: str, revision_id: str) -> None:
    """Read public history/replay projections; these routes must not charge."""

    detail = _debate_detail(api, debate_id)
    require(isinstance(detail.get("playback"), dict), "replay_view_shape")
    transcript = api.transcript(debate_id)
    turns = transcript.get("turns")
    require(isinstance(turns, list) and len(turns) == 4, "history_turn_count")
    revision = api.report_revision(debate_id, revision_id)
    require(revision.get("id") == revision_id, "history_report_revision")


def _verify_report_policy_binding(
    connection: Any,
    *,
    debate_id: str,
    revision_id: str,
    report_manifest_hash: str,
    acceptance_run_id: str,
    expected_policy_hash: str,
) -> None:
    """Verify the Report manifest through its scope and bound call 8."""

    from sqlalchemy import text

    report_policy = connection.execute(
        text(
            "SELECT m.policy_hash FROM provider_export_manifests m "
            "JOIN provider_operations po ON po.export_manifest_hash=m.manifest_hash "
            "AND po.scope_id=m.scope_id "
            "WHERE m.scope_id=:debate_id "
            "AND m.manifest_hash=:manifest_hash "
            "AND m.provider_operation='llm_maya_report' "
            "AND po.provider_operation='llm_maya_report' "
            "AND po.logical_item_id=:revision_id "
            "AND po.acceptance_run_id=:run_id "
            "AND po.call_no=:call_no "
            "AND po.state='succeeded' AND po.request_count=1 "
            "AND po.charged_request_count=1 AND po.attempt_no=1"
        ),
        {
            "debate_id": debate_id,
            "manifest_hash": report_manifest_hash,
            "revision_id": revision_id,
            "run_id": acceptance_run_id,
            "call_no": EXPECTED_HAPPY_PATH_CALLS,
        },
    ).all()
    require(report_policy == [(expected_policy_hash,)], "report_policy_binding")


def report_acceptance_adapter(
    *,
    api: Api,
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    fixture: Fixture,
    report_policy_hash: str,
) -> Mapping[str, Any]:
    """Run the one-shot Real Report call as acceptance ordinal eight."""

    run_id = checkpoint.get("acceptance_run_id")
    debate_id = checkpoint.get("debate_id")
    require(isinstance(run_id, str), "acceptance_run_missing")
    require(isinstance(debate_id, str), "acceptance_debate_missing")
    require(HASH_RE.fullmatch(report_policy_hash) is not None, "report_policy_hash")
    require(checkpoint["report_calls"] == 0, "report_call_already_bound")
    require(len(checkpoint["bound_manifest_hashes"]) == DEBATE_STAGE_CALLS, "report_call_order")

    opened = api.open_interaction(debate_id)
    require(opened.get("status") == "open", "interaction_not_open")
    closed = api.close_interaction(debate_id)
    require(closed.get("status") == "finalized", "interaction_not_finalized")

    _assert_charged_summary(
        api,
        checkpoint,
        fixture,
        expected_call_count=DEBATE_STAGE_CALLS,
    )
    pending = _wait_report_pending(api, debate_id)
    revision_id = opaque(pending.get("report_revision_id"), "report_revision_id")
    checkpoint["report_revision_id"] = revision_id
    checkpoint["next_call"] = "report"
    write_checkpoint(checkpoint_path, checkpoint)
    _read_history_replay_views(api, debate_id, revision_id)
    _assert_charged_summary(
        api,
        checkpoint,
        fixture,
        expected_call_count=DEBATE_STAGE_CALLS,
    )

    # Preserve the exact disclosure CAS before associating the revision with
    # the run.  No report text or provider response is logged.
    _confirm_manifest(api, pending, expected_policy_hash=report_policy_hash)
    bound_report = api.bind_acceptance_report(run_id, revision_id)
    _validated_acceptance_run(
        bound_report,
        fixture=fixture,
        checkpoint=checkpoint,
        expected_call_count=DEBATE_STAGE_CALLS,
        expected_debate_id=debate_id,
    )
    _attach_pending_call(
        api,
        checkpoint,
        checkpoint_path,
        fixture,
        manifest=pending,
        kind="report",
    )
    continued = api.continue_report(
        debate_id,
        revision_id,
        manifest_hash=str(pending["manifest_hash"]),
        call_no=EXPECTED_HAPPY_PATH_CALLS,
    )
    failure = _report_failure_code(continued)
    if failure is not None:
        raise AcceptanceError(failure)

    deadline = time.monotonic() + 90.0
    ready: Mapping[str, Any] | None = None
    while time.monotonic() < deadline:
        current = api.report_revision(debate_id, revision_id)
        failure = _report_failure_code(current)
        if failure is not None:
            raise AcceptanceError(failure)
        if current.get("status") == "ready":
            ready = _verify_ready_report(current, revision_id=revision_id)
            break
        if current.get("status") not in {"generating"}:
            raise AcceptanceError("report_not_ready")
        time.sleep(0.2)
    require(ready is not None, "report_ready_timeout")
    _read_history_replay_views(api, debate_id, revision_id)
    _assert_charged_summary(
        api,
        checkpoint,
        fixture,
        expected_call_count=EXPECTED_HAPPY_PATH_CALLS,
    )
    return {
        "status": "REAL_CORE_DEMO_REPORT_PASS",
        "report_revision_id": revision_id,
        "report_word_count": ready["word_count"],
        "report_calls": checkpoint["report_calls"],
    }


def execute(
    base_url: str,
    checkpoint_path: Path,
    embedding_policy_hash: str,
    llm_policy_hash: str,
    report_policy_hash: str,
    student_password: str,
    teacher_password: str,
) -> Mapping[str, Any]:
    """Execute the bounded Real-Core debate stage and park before Report."""

    require(HASH_RE.fullmatch(embedding_policy_hash) is not None, "embedding_policy_hash")
    require(HASH_RE.fullmatch(llm_policy_hash) is not None, "llm_policy_hash")
    require(HASH_RE.fullmatch(report_policy_hash) is not None, "report_policy_hash")
    fixture = load_fixture()
    checkpoint = dict(read_checkpoint(checkpoint_path, fixture))
    require(checkpoint["state"] == "prepared", "checkpoint_already_consumed")
    require(
        checkpoint["snapshot_calls"] == 0
        and checkpoint["real_query_calls"] == 0
        and checkpoint["llm_calls"] == 0,
        "checkpoint_call_counts",
    )
    require(checkpoint["acceptance_run_id"] is None, "checkpoint_run_already_bound")
    require(checkpoint["bound_manifest_hashes"] == [], "checkpoint_call_counts")
    student, teacher = Api(base_url), Api(base_url)
    socket: PlaybackSocket | None = None
    try:
        student.login(
            os.environ.get("MAYA_STUDENT_USERNAME", "student-bowen-1"), student_password
        )
        teacher.login(os.environ.get("MAYA_TEACHER_USERNAME", "teacher-demo"), teacher_password)
        _assert_checkpoint_baseline(teacher, checkpoint)

        # The run is created only now, against this fresh target/version and
        # exact fixture hash.  ``prepare`` intentionally cannot fabricate or
        # persist an acceptance-run identity.
        run = teacher.create_acceptance_run(
            fixture_hash=fixture.fixture_hash,
            target_agent_id=str(checkpoint["real_agent_id"]),
            target_version_id=str(checkpoint["real_version_id"]),
        )
        _validated_acceptance_run(run, fixture=fixture, checkpoint=checkpoint, expected_call_count=0)
        acceptance_run_id = opaque(run.get("id"), "acceptance_run_id")
        checkpoint["acceptance_run_id"] = acceptance_run_id
        checkpoint["state"] = "executing"
        checkpoint["next_call"] = "snapshot"
        write_checkpoint(checkpoint_path, checkpoint)
        real_version_id = str(checkpoint["real_version_id"])
        publish_key = f"real-core-demo-real-publish-{real_version_id}"

        # Both publish requests carry the exact same body and idempotency hash.
        # The first only stages/exposes the Snapshot manifest; Call1 is bound
        # atomically only after the teacher confirms and the second request
        # reaches the real runtime.
        snapshot_publish_body = _snapshot_publish_body(
            acceptance_run_id=acceptance_run_id,
            expected_revision=int(checkpoint["real_revision"]),
        )
        _status, blocked = student.request(
            "POST",
            f"/api/v1/agent-versions/{real_version_id}/publish",
            expected={409},
            body=snapshot_publish_body,
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
        _status, published = student.request(
            "POST",
            f"/api/v1/agent-versions/{real_version_id}/publish",
            expected={200},
            body=snapshot_publish_body,
            key=publish_key,
        )
        snapshot_id = opaque(published.get("knowledge_snapshot_id"), "snapshot_id")
        checkpoint["snapshot_id"] = snapshot_id
        checkpoint["bound_manifest_hashes"] = [str(items[0]["manifest_hash"])]
        checkpoint["snapshot_calls"] = 1
        checkpoint["next_call"] = "real_query"
        write_checkpoint(checkpoint_path, checkpoint)
        _assert_charged_summary(teacher, checkpoint, fixture, expected_call_count=1)

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
        bound = teacher.bind_acceptance_debate(acceptance_run_id, debate_id)
        _validated_acceptance_run(
            bound,
            fixture=fixture,
            checkpoint=checkpoint,
            expected_call_count=1,
            expected_debate_id=debate_id,
        )
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
            # The mutual-learning order is A, B, A, B. Slot B is the sole real
            # Snapshot participant, hence two independent real queries.
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
                _attach_pending_call(
                    teacher,
                    checkpoint,
                    checkpoint_path,
                    fixture,
                    manifest=query_item,
                    kind="real_query",
                )
                _confirm_manifest(teacher, query_item, expected_policy_hash=embedding_policy_hash)
                _retry_preparation(
                    teacher,
                    debate_id,
                    turn_id,
                    key=f"real-core-demo-query-retry-{turn_index + 1:02d}",
                )
            else:
                detail = _debate_detail(teacher, debate_id)
                turn_id = opaque(detail["playback"].get("current_turn_id"), "turn_id")
                checkpoint["current_turn_id"] = turn_id
                write_checkpoint(checkpoint_path, checkpoint)

            # Every turn in this reviewed composition uses the real LLM. Its
            # exact one-shot manifest must be attached and confirmed before
            # the explicit continuation; no automatic retry is performed.
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
                if current_playback.get("status") in {"failed", "stopped"}:
                    raise AcceptanceError("provider_failed")
                if (
                    current_playback.get("status") == "ready"
                    and str(current_playback.get("current_turn_id")) == turn_id
                ):
                    break
                time.sleep(0.2)
            require(llm_item is not None, "llm_manifest_missing")
            _attach_pending_call(
                teacher,
                checkpoint,
                checkpoint_path,
                fixture,
                manifest=llm_item,
                kind="llm",
            )
            _confirm_manifest(teacher, llm_item, expected_policy_hash=llm_policy_hash)
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
            _assert_charged_summary(
                teacher,
                checkpoint,
                fixture,
                expected_call_count=len(checkpoint["bound_manifest_hashes"]),
            )

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
        transcript = teacher.transcript(debate_id)
        turns = transcript.get("turns")
        require(isinstance(turns, list) and len(turns) == 4, "turn_count")
        require(
            checkpoint["snapshot_calls"] == 1
            and checkpoint["real_query_calls"] == 2
            and checkpoint["llm_calls"] == 4
            and len(checkpoint["bound_manifest_hashes"]) == DEBATE_STAGE_CALLS,
            "debate_stage_call_counts",
        )
        _assert_charged_summary(
            teacher,
            checkpoint,
            fixture,
            expected_call_count=DEBATE_STAGE_CALLS,
        )
        report_result = report_acceptance_adapter(
            api=teacher,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            fixture=fixture,
            report_policy_hash=report_policy_hash,
        )
        checkpoint["state"] = "executed"
        checkpoint["next_call"] = "none"
        write_checkpoint(checkpoint_path, checkpoint)
        return {
            **report_result,
            "fixture_hash": fixture.fixture_hash,
            "snapshot_calls": checkpoint["snapshot_calls"],
            "real_query_calls": checkpoint["real_query_calls"],
            "llm_calls": checkpoint["llm_calls"],
            "debate_stage_calls": DEBATE_STAGE_CALLS,
            "expected_happy_path_calls": EXPECTED_HAPPY_PATH_CALLS,
            "max_acceptance_calls": MAX_ACCEPTANCE_CALLS,
            "total_calls": len(checkpoint["bound_manifest_hashes"]),
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
    report_policy_hash: str,
) -> Mapping[str, Any]:
    """Verify the complete eight-call Real-Core Demo happy path."""

    require(database_url.startswith("sqlite:"), "database_url")
    require(HASH_RE.fullmatch(embedding_policy_hash) is not None, "embedding_policy_hash")
    require(HASH_RE.fullmatch(llm_policy_hash) is not None, "llm_policy_hash")
    require(HASH_RE.fullmatch(report_policy_hash) is not None, "report_policy_hash")
    fixture = load_fixture()
    checkpoint = dict(read_checkpoint(checkpoint_path, fixture))
    require(checkpoint["state"] == "executed", "checkpoint_not_executed")
    require(
        checkpoint["snapshot_id"]
        and checkpoint["debate_id"]
        and checkpoint["report_revision_id"],
        "checkpoint_ids",
    )
    require(
        checkpoint["snapshot_id"] != checkpoint["baseline_snapshot_id"],
        "snapshot_baseline_collision",
    )
    require(checkpoint["snapshot_calls"] == 1, "checkpoint_snapshot_calls")
    require(checkpoint["real_query_calls"] == 2, "checkpoint_query_calls")
    require(checkpoint["llm_calls"] == 4, "checkpoint_llm_calls")
    require(checkpoint["report_calls"] == 1, "checkpoint_report_calls")
    require(
        len(checkpoint["bound_manifest_hashes"]) == EXPECTED_HAPPY_PATH_CALLS,
        "checkpoint_total_calls",
    )
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
            report_row = connection.execute(
                text(
                    "SELECT id,status,word_count,english_markdown "
                    "FROM civilization_report_revisions WHERE id=:revision_id "
                    "AND debate_id=:debate_id"
                ),
                {
                    "revision_id": checkpoint["report_revision_id"],
                    "debate_id": checkpoint["debate_id"],
                },
            ).mappings().one_or_none()
            require(report_row is not None, "report_revision_missing")
            _verify_ready_report(report_row, revision_id=str(checkpoint["report_revision_id"]))
            report_operation = connection.execute(
                text(
                    "SELECT state,request_count,charged_request_count,attempt_no "
                    "FROM provider_operations WHERE scope_id=:debate_id "
                    "AND provider_operation='llm_maya_report' "
                    "AND logical_item_id=:revision_id"
                ),
                {
                    "debate_id": checkpoint["debate_id"],
                    "revision_id": checkpoint["report_revision_id"],
                },
            ).all()
            require(report_operation == [("succeeded", 1, 1, 1)], "report_ledger_count")
            _verify_report_policy_binding(
                connection,
                debate_id=str(checkpoint["debate_id"]),
                revision_id=str(checkpoint["report_revision_id"]),
                report_manifest_hash=str(checkpoint["bound_manifest_hashes"][-1]),
                acceptance_run_id=str(checkpoint["acceptance_run_id"]),
                expected_policy_hash=report_policy_hash,
            )
            run_counts = connection.execute(
                text(
                    "SELECT COUNT(*),COALESCE(SUM(charged_request_count),0) "
                    "FROM provider_operations WHERE acceptance_run_id=:run_id"
                ),
                {"run_id": checkpoint["acceptance_run_id"]},
            ).one()
            require(tuple(map(int, run_counts)) == (EXPECTED_HAPPY_PATH_CALLS, EXPECTED_HAPPY_PATH_CALLS), "run_charge_count")
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
        "report_calls": 1,
        "debate_stage_calls": DEBATE_STAGE_CALLS,
        "expected_happy_path_calls": EXPECTED_HAPPY_PATH_CALLS,
        "max_acceptance_calls": MAX_ACCEPTANCE_CALLS,
        "total_calls": EXPECTED_HAPPY_PATH_CALLS,
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
    execute_parser.add_argument("--report-policy-hash", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--checkpoint", type=Path, required=True)
    verify_parser.add_argument("--database-url", required=True)
    verify_parser.add_argument("--embedding-policy-hash", required=True)
    verify_parser.add_argument("--llm-policy-hash", required=True)
    verify_parser.add_argument("--report-policy-hash", required=True)
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
                "debate_stage_calls": 0,
                "expected_happy_path_calls": EXPECTED_HAPPY_PATH_CALLS,
                "max_acceptance_calls": MAX_ACCEPTANCE_CALLS,
                "total_calls": 0,
            }
        else:
            base_url = os.environ.get("MAYA_BASE_URL", "")
            if args.command == "prepare":
                student_password = os.environ.get("MAYA_STUDENT_PASSWORD", "")
                require(bool(student_password), "student_password_missing")
                value = prepare(base_url, args.checkpoint, student_password)
            elif args.command == "execute":
                student_password = os.environ.get("MAYA_STUDENT_PASSWORD", "")
                teacher_password = os.environ.get("MAYA_TEACHER_PASSWORD", "")
                require(
                    bool(student_password)
                    and bool(teacher_password),
                    "provider_credentials_missing",
                )
                value = execute(
                    base_url,
                    args.checkpoint,
                    args.embedding_policy_hash,
                    args.llm_policy_hash,
                    args.report_policy_hash,
                    student_password,
                    teacher_password,
                )
            else:
                value = verify(
                    args.database_url,
                    args.checkpoint,
                    args.embedding_policy_hash,
                    args.llm_policy_hash,
                    args.report_policy_hash,
                )
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return 0
    except (AcceptanceError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, AcceptanceError) else "acceptance_failed"
        print(json.dumps({"status": "FAILED", "safe_error_code": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
