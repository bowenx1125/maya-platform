from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from acceptance import (
    CHECKPOINT_FIELDS,
    AcceptanceError,
    TwoCallGate,
    load_fixture,
    main,
    read_checkpoint,
    write_checkpoint,
)


def checkpoint(fixture_hash: str) -> dict[str, object]:
    values: dict[str, object] = {
        "version": "real-embed-checkpoint-v1",
        "fixture_hash": fixture_hash,
        "target_revision": 2,
    }
    for index, name in enumerate(
        sorted(CHECKPOINT_FIELDS - {"version", "fixture_hash", "target_revision"}), start=1
    ):
        values[name] = f"00000000-0000-4000-8000-{index:012d}"
    return values


def test_fixture_is_one_chunk_and_opening_query_is_chinese() -> None:
    fixture = load_fixture()
    assert fixture.persona_hash
    assert "玛雅" in fixture.query_text
    assert any("\u4e00" <= char <= "\u9fff" for char in fixture.topic)


def test_checkpoint_is_closed_hash_bound_and_private(tmp_path: Path) -> None:
    fixture = load_fixture()
    path = tmp_path / "checkpoint.json"
    value = checkpoint(fixture.fixture_hash)
    write_checkpoint(path, value)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_checkpoint(path, fixture) == value

    changed = json.loads(path.read_text())
    changed["fixture_hash"] = "0" * 64
    path.write_text(json.dumps(changed), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(AcceptanceError, match="checkpoint_fixture"):
        read_checkpoint(path, fixture)


def test_two_call_gate_requires_confirmation_and_never_allows_retry() -> None:
    gate = TwoCallGate()
    with pytest.raises(AcceptanceError, match="snapshot_call_forbidden"):
        gate.call_snapshot()
    gate.confirm_snapshot()
    gate.call_snapshot()
    with pytest.raises(AcceptanceError, match="snapshot_call_forbidden"):
        gate.call_snapshot()
    gate.confirm_query()
    gate.call_query()
    assert gate.result() == {"snapshot_calls": 1, "query_calls": 1, "total_calls": 2}
    with pytest.raises(AcceptanceError, match="query_call_forbidden"):
        gate.call_query()


def test_default_check_is_provider_free(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FIXTURE_OK"
    assert output["real_calls"] == 0


def test_execute_requires_explicit_cap_before_any_password_or_http(
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
                "--policy-hash",
                "a" * 64,
            ]
        )
    assert raised.value.code == 2
