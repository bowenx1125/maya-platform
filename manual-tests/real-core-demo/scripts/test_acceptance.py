from __future__ import annotations

import importlib
import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

acceptance = importlib.import_module("acceptance")
AcceptanceError = acceptance.AcceptanceError
Api = acceptance.Api
CHECKPOINT_FIELDS = acceptance.CHECKPOINT_FIELDS
BASELINE_FIELDS = acceptance.BASELINE_FIELDS
verify_turn_evidence = acceptance._verify_turn_evidence
validated_baseline = acceptance._validated_baseline
load_fixture = acceptance.load_fixture
main = acceptance.main
read_checkpoint = acceptance.read_checkpoint
write_checkpoint = acceptance.write_checkpoint


def checkpoint(fixture_hash: str) -> dict[str, object]:
    values: dict[str, object] = {
        "version": acceptance.CHECKPOINT_VERSION,
        "state": "prepared",
        "acceptance_run_id": None,
        "fixture_hash": fixture_hash,
        "dirty_agents": 1,
        "dirty_debates": 0,
        "dirty_interactions": 0,
        "real_revision": 3,
        "baseline_agent_id": "00000000-0000-4000-8000-000000000001",
        "baseline_version_id": "00000000-0000-4000-8000-000000000002",
        "baseline_snapshot_id": "00000000-0000-4000-8000-000000000003",
        "snapshot_id": None,
        "debate_id": None,
        "current_turn_id": None,
        "snapshot_calls": 0,
        "real_query_calls": 0,
        "llm_calls": 0,
        "completed_turns": [],
        "bound_manifest_hashes": [],
        "next_call": "none",
    }
    for index, name in enumerate(
        sorted(
            CHECKPOINT_FIELDS
            - {
                "version",
                "state",
                "acceptance_run_id",
                "fixture_hash",
                "dirty_agents",
                "dirty_debates",
                "dirty_interactions",
                "real_revision",
                "baseline_agent_id",
                "baseline_version_id",
                "baseline_snapshot_id",
                "snapshot_id",
                "debate_id",
                "current_turn_id",
                "snapshot_calls",
                "real_query_calls",
                "llm_calls",
                "completed_turns",
                "bound_manifest_hashes",
                "next_call",
            }
        ),
        start=1,
    ):
        values[name] = f"00000000-0000-4000-8000-{index:012d}"
    return values


def test_fixture_is_one_chunk_and_query_is_chinese() -> None:
    fixture = load_fixture()
    assert "mock_persona_path" not in fixture.manifest
    assert fixture.manifest["real_participant_slot"] == "B"
    assert fixture.real_persona_hash
    assert "文化知识" in fixture.query_text
    assert "上下文" in fixture.query_text
    assert fixture.topic.startswith("How should")
    assert "课堂" in fixture.topic
    assert fixture.manifest["call_cap"] == {
        "snapshot": 1,
        "real_query": 2,
        "llm_turn": 4,
        "report": 1,
        "debate_stage": 7,
        "expected_happy_path": 8,
        "max_ceiling": 8,
        "total": 8,
    }


def run_summary(checkpoint_value: dict[str, object], *, call_count: int = 0) -> dict[str, object]:
    return {
        "id": "00000000-0000-4000-8000-000000000008",
        "plan_version": "real_core_demo_v2",
        "fixture_hash": checkpoint_value["fixture_hash"],
        "baseline_agent_id": checkpoint_value["baseline_agent_id"],
        "baseline_version_id": checkpoint_value["baseline_version_id"],
        "baseline_snapshot_id": checkpoint_value["baseline_snapshot_id"],
        "target_agent_id": checkpoint_value["real_agent_id"],
        "target_version_id": checkpoint_value["real_version_id"],
        "debate_id": checkpoint_value["debate_id"],
        "report_revision_id": None,
        "state": "executing",
        "starting_charged_requests": 0,
        "call_count": call_count,
        "charged_request_count": 0,
    }


def test_checkpoint_is_closed_and_private(tmp_path: Path) -> None:
    fixture = load_fixture()
    path = tmp_path / "checkpoint.json"
    value = checkpoint(fixture.fixture_hash)
    write_checkpoint(path, value)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_checkpoint(path, fixture) == value

    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["fixture_hash"] = "0" * 64
    path.write_text(json.dumps(changed), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(AcceptanceError, match="checkpoint_fixture"):
        read_checkpoint(path, fixture)


def test_default_check_is_provider_free(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FIXTURE_OK"
    assert output["total_calls"] == 0


@pytest.mark.parametrize(
    ("base_url", "origin"),
    [
        ("http://127.0.0.1:18080", "http://127.0.0.1:18080"),
        ("http://127.0.0.1:18080/", "http://127.0.0.1:18080"),
        ("http://localhost:8080", "http://localhost:8080"),
    ],
)
def test_api_uses_exact_same_origin(
    base_url: str,
    origin: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, str]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {}

    class CapturingClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def request(self, _method: str, _path: str, **kwargs: object) -> Response:
            headers = kwargs.get("headers")
            assert isinstance(headers, dict)
            observed.append(dict(headers))
            return Response()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr("acceptance.httpx.Client", CapturingClient)
    api = Api(base_url)
    try:
        api.request("GET", "/health", expected={200})
        api.csrf = "csrf-token"
        api.request("POST", "/api/v1/auth/logout", expected={200})
    finally:
        api.close()
    assert [headers["Origin"] for headers in observed] == [origin, origin]
    assert observed[1]["X-CSRF-Token"] == "csrf-token"


def test_api_attach_uses_manifest_hash_and_ordinal(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[dict[str, object]] = []

    class Response:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return {"call_count": 1, "charged_request_count": 0}

    class CapturingClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def request(self, _method: str, _path: str, **kwargs: object) -> Response:
            observed.append(kwargs)
            return Response()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr("acceptance.httpx.Client", CapturingClient)
    api = Api("http://127.0.0.1:18080")
    try:
        api.attach_acceptance_call(
            "00000000-0000-4000-8000-000000000008",
            manifest_hash="a" * 64,
            call_no=1,
        )
    finally:
        api.close()
    assert observed[0]["json"] == {"manifest_hash": "a" * 64, "call_no": 1}
    assert "operation_id" not in observed[0]["json"]


def test_api_stops_on_acceptance_unknown_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 409

        @staticmethod
        def json() -> dict[str, object]:
            return {"code": "llm_acceptance_unknown", "message": "safe"}

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        @staticmethod
        def request(*_args: object, **_kwargs: object) -> Response:
            return Response()

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr("acceptance.httpx.Client", Client)
    api = Api("http://127.0.0.1:18080")
    try:
        with pytest.raises(AcceptanceError, match="acceptance_unknown"):
            api.request("POST", "/continuation", expected={200})
    finally:
        api.close()


def test_demo_baseline_requires_stable_usable_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    baseline = {
        "agent_id": "00000000-0000-4000-8000-000000000001",
        "version_id": "00000000-0000-4000-8000-000000000002",
        "snapshot_id": "00000000-0000-4000-8000-000000000003",
        "group_id": "00000000-0000-4000-8000-000000000004",
        "system_baseline": True,
        "immutable": True,
        "usable": True,
    }
    status = {
        "baseline": baseline,
        "composition": {"components": []},
        "dirty_agents": 1,
        "dirty_debates": 0,
        "dirty_interactions": 0,
    }

    class Response:
        status_code = 200

        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def json(self) -> dict[str, object]:
            return self.payload

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            self.responses = iter((baseline, baseline, status))

        def request(self, *_args: object, **_kwargs: object) -> Response:
            return Response(next(self.responses))

        @staticmethod
        def close() -> None:
            pass

    monkeypatch.setattr("acceptance.httpx.Client", Client)
    api = Api("http://127.0.0.1:18080")
    try:
        first = api.demo_baseline()
        assert set(first) == BASELINE_FIELDS
        assert first == api.demo_baseline()
        assert api.demo_status()["dirty_agents"] == 1
    finally:
        api.close()


def test_demo_baseline_rejects_unusable_or_incomplete_response() -> None:
    baseline = {
        "agent_id": "00000000-0000-4000-8000-000000000001",
        "version_id": "00000000-0000-4000-8000-000000000002",
        "snapshot_id": "00000000-0000-4000-8000-000000000003",
        "group_id": "00000000-0000-4000-8000-000000000004",
        "system_baseline": True,
        "immutable": True,
        "usable": False,
    }
    with pytest.raises(AcceptanceError, match="baseline_not_usable"):
        validated_baseline(baseline)
    del baseline["snapshot_id"]
    with pytest.raises(AcceptanceError, match="baseline_shape"):
        validated_baseline(baseline)


def test_prepare_reuses_server_baseline_and_creates_only_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = {
        "agent_id": "00000000-0000-4000-8000-000000000001",
        "version_id": "00000000-0000-4000-8000-000000000002",
        "snapshot_id": "00000000-0000-4000-8000-000000000003",
        "group_id": "00000000-0000-4000-8000-000000000004",
        "system_baseline": True,
        "immutable": True,
        "usable": True,
    }
    created: list[str] = []

    class FakeApi:
        def __init__(self, _base_url: str) -> None:
            self.status_calls = 0

        def login(self, _username: str, _password: str) -> dict[str, object]:
            return {
                "courses": [{"course_id": "00000000-0000-4000-8000-000000000005"}],
                "groups": [{"group_id": baseline["group_id"]}],
            }

        @staticmethod
        def demo_baseline() -> dict[str, object]:
            return baseline

        def demo_status(self) -> dict[str, object]:
            self.status_calls += 1
            counts = (0, 0, 0) if self.status_calls == 1 else (1, 0, 0)
            return {
                "baseline": baseline,
                "composition": {"components": [{"mode": "mock"}]},
                "dirty_agents": counts[0],
                "dirty_debates": counts[1],
                "dirty_interactions": counts[2],
            }

        @staticmethod
        def close() -> None:
            pass

    def fake_setup(
        _api: object,
        _group_id: str,
        name: str,
        _persona: str,
        _knowledge: bytes,
        *,
        key_prefix: str,
    ) -> tuple[str, str, int]:
        created.append(f"{name}:{key_prefix}")
        return (
            "00000000-0000-4000-8000-000000000006",
            "00000000-0000-4000-8000-000000000007",
            3,
        )

    monkeypatch.setattr("acceptance.Api", FakeApi)
    monkeypatch.setattr("acceptance.setup_agent", fake_setup)
    checkpoint_path = tmp_path / "checkpoint.json"
    result = acceptance.prepare("http://127.0.0.1:18080", checkpoint_path, "fixture-password")

    assert created == ["河流与种子守护者:real"]
    assert result["baseline_agent_id"] == baseline["agent_id"]
    assert result["baseline_version_id"] == baseline["version_id"]
    assert result["baseline_snapshot_id"] == baseline["snapshot_id"]
    assert result["acceptance_run_id"] is None
    assert result["bound_manifest_hashes"] == []
    assert result["snapshot_calls"] == result["real_query_calls"] == result["llm_calls"] == 0
    assert result["dirty_agents"] == 1
    assert result["dirty_debates"] == result["dirty_interactions"] == 0


def test_attach_pending_call_binds_once_and_advances_bounded_summary(
    tmp_path: Path,
) -> None:
    fixture = load_fixture()
    value = checkpoint(fixture.fixture_hash)
    value["state"] = "executing"
    value["acceptance_run_id"] = "00000000-0000-4000-8000-000000000008"
    manifest_hash = "a" * 64
    captured: list[dict[str, object]] = []

    class FakeApi:
        def attach_acceptance_call(
            self,
            run_id: str,
            *,
            manifest_hash: str,
            call_no: int,
        ) -> dict[str, object]:
            captured.append(
                {"run_id": run_id, "manifest_hash": manifest_hash, "call_no": call_no}
            )
            result = run_summary(value, call_count=call_no)
            result["charged_request_count"] = 0
            return result

    path = tmp_path / "checkpoint.json"
    acceptance._attach_pending_call(
        FakeApi(),
        value,
        path,
        fixture,
        manifest={"manifest_hash": manifest_hash, "confirmed": False},
        kind="snapshot",
    )
    assert captured == [
        {
            "run_id": "00000000-0000-4000-8000-000000000008",
            "manifest_hash": manifest_hash,
            "call_no": 1,
        }
    ]
    assert value["bound_manifest_hashes"] == [manifest_hash]
    assert value["snapshot_calls"] == 1
    with pytest.raises(AcceptanceError, match="acceptance_operation_duplicate"):
        acceptance._attach_pending_call(
            FakeApi(),
            value,
            path,
            fixture,
            manifest={"manifest_hash": manifest_hash, "confirmed": False},
            kind="snapshot",
        )


def test_acceptance_run_creation_requires_fresh_zero_summary() -> None:
    fixture = load_fixture()
    value = checkpoint(fixture.fixture_hash)
    value["state"] = "executing"
    value["acceptance_run_id"] = None
    summary = run_summary(value)
    with pytest.raises(AcceptanceError, match="acceptance_run_starting_charged"):
        acceptance._validated_acceptance_run(
            {**summary, "starting_charged_requests": 1},
            fixture=fixture,
            checkpoint=value,
            expected_call_count=0,
        )
    with pytest.raises(AcceptanceError, match="acceptance_run_call_count"):
        acceptance._validated_acceptance_run(
            {**summary, "call_count": 1},
            fixture=fixture,
            checkpoint=value,
            expected_call_count=0,
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://127.0.0.1:18080/path",
        "http://127.0.0.2:18080",
        "http://localhost:18080",
        "http://LOCALHOST:8080",
        "https://127.0.0.1:18080",
    ],
)
def test_api_rejects_base_url_outside_loopback_allowlist(base_url: str) -> None:
    with pytest.raises(AcceptanceError, match="base_url"):
        Api(base_url)


def test_turn_evidence_rejects_mismatched_source_lineage() -> None:
    class Result:
        def mappings(self) -> Result:
            return self

        def all(self) -> list[dict[str, str]]:
            return [
                {
                    "evidence_id": "evidence-1",
                    "chunk_id": "wrong-chunk",
                    "snapshot_id": "snapshot-1",
                    "source_filename": "lesson.md",
                }
            ]

    class Connection:
        def execute(self, *_args: object, **_kwargs: object) -> Result:
            return Result()

    row = {
        "id": "turn-1",
        "knowledge_snapshot_id": "snapshot-1",
        "speech": "This is an English-safe sentence.",
        "retrieval_receipts_json": json.dumps(
            [
                {
                    "evidence_id": "evidence-1",
                    "chunk_id": "chunk-1",
                    "snapshot_id": "snapshot-1",
                    "source_filename": "lesson.md",
                }
            ]
        ),
        "evidence_trace_json": json.dumps(
            [
                {
                    "evidence_id": "evidence-1",
                    "chunk_id": "chunk-1",
                    "source_filename": "lesson.md",
                    "support_mode": "direct",
                }
            ]
        ),
    }
    with pytest.raises(AcceptanceError, match="source_receipt_mismatch"):
        verify_turn_evidence(Connection(), row)
