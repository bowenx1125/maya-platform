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
SevenCallGate = acceptance.SevenCallGate
load_fixture = acceptance.load_fixture
main = acceptance.main
read_checkpoint = acceptance.read_checkpoint
write_checkpoint = acceptance.write_checkpoint


def checkpoint(fixture_hash: str) -> dict[str, object]:
    values: dict[str, object] = {
        "version": "real-core-demo-checkpoint-v1",
        "state": "prepared",
        "fixture_hash": fixture_hash,
        "real_revision": 3,
        "snapshot_id": None,
        "debate_id": None,
        "current_turn_id": None,
        "snapshot_calls": 0,
        "real_query_calls": 0,
        "llm_calls": 0,
        "completed_turns": [],
        "next_call": "none",
    }
    for index, name in enumerate(
        sorted(
            CHECKPOINT_FIELDS
            - {
                "version",
                "state",
                "fixture_hash",
                "real_revision",
                "snapshot_id",
                "debate_id",
                "current_turn_id",
                "snapshot_calls",
                "real_query_calls",
                "llm_calls",
                "completed_turns",
                "next_call",
            }
        ),
        start=1,
    ):
        values[name] = f"00000000-0000-4000-8000-{index:012d}"
    return values


def test_fixture_is_one_chunk_and_query_is_chinese() -> None:
    fixture = load_fixture()
    assert fixture.real_persona_hash
    assert "文化知识" in fixture.query_text
    assert "上下文" in fixture.query_text
    assert fixture.topic.startswith("How should")


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


def test_seven_call_gate_requires_confirmations_and_forbids_excess() -> None:
    gate = SevenCallGate()
    with pytest.raises(AcceptanceError, match="snapshot_call_forbidden"):
        gate.call_snapshot()
    gate.confirm_snapshot()
    gate.call_snapshot()
    with pytest.raises(AcceptanceError, match="snapshot_call_forbidden"):
        gate.call_snapshot()
    gate.confirm_query()
    gate.call_query()
    gate.call_query()
    with pytest.raises(AcceptanceError, match="query_call_forbidden"):
        gate.call_query()
    gate.confirm_llm()
    for _ in range(4):
        gate.call_llm()
    with pytest.raises(AcceptanceError, match="llm_call_forbidden"):
        gate.call_llm()
    assert gate.result() == {
        "snapshot_calls": 1,
        "real_query_calls": 2,
        "llm_calls": 4,
        "total_calls": 7,
    }


def test_seven_call_gate_rejects_attempt_two_without_provider_call() -> None:
    gate = SevenCallGate()
    gate.confirm_snapshot()
    gate.call_snapshot()
    gate.confirm_query()
    gate.call_query()
    gate.confirm_llm()
    for _ in range(4):
        gate.call_llm()
    with pytest.raises(AcceptanceError, match="llm_call_forbidden"):
        gate.call_llm()
    assert gate.llm_calls == 4


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


def test_execute_requires_explicit_cap_before_password_or_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_fixture()
    path = tmp_path / "checkpoint.json"
    write_checkpoint(path, checkpoint(fixture.fixture_hash))
    monkeypatch.setenv("MAYA_STUDENT_PASSWORD", "fixture-password")
    monkeypatch.setenv("MAYA_TEACHER_PASSWORD", "fixture-password")
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "execute",
                "--checkpoint",
                str(path),
                "--embedding-policy-hash",
                "a" * 64,
                "--llm-policy-hash",
                "b" * 64,
            ]
        )
    assert raised.value.code == 2
