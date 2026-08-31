from __future__ import annotations

import json
import sqlite3
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
    verify,
    write_checkpoint,
)


def checkpoint(fixture_hash: str) -> dict[str, object]:
    values: dict[str, object] = {
        "version": "real-embed-checkpoint-v1",
        "state": "prepared",
        "fixture_hash": fixture_hash,
        "target_revision": 2,
        "snapshot_id": None,
        "debate_id": None,
        "turn_id": None,
    }
    for index, name in enumerate(
        sorted(
            CHECKPOINT_FIELDS
            - {
                "version",
                "state",
                "fixture_hash",
                "target_revision",
                "snapshot_id",
                "debate_id",
                "turn_id",
            }
        ),
        start=1,
    ):
        values[name] = f"00000000-0000-4000-8000-{index:012d}"
    return values


def test_fixture_is_one_chunk_and_opening_query_contains_chinese_position() -> None:
    fixture = load_fixture()
    assert fixture.persona_hash
    assert "文化知识" in fixture.query_text
    assert "共同责任" in fixture.query_text
    assert fixture.topic.startswith("How should")


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


def test_offline_verify_requires_exact_sql_ledger_and_evidence(tmp_path: Path) -> None:
    fixture = load_fixture()
    path = tmp_path / "checkpoint.json"
    value = checkpoint(fixture.fixture_hash)
    value.update(
        {
            "state": "executed",
            "snapshot_id": "10000000-0000-4000-8000-000000000001",
            "debate_id": "10000000-0000-4000-8000-000000000002",
            "turn_id": "10000000-0000-4000-8000-000000000003",
        }
    )
    write_checkpoint(path, value)
    database_path = tmp_path / "verify.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE knowledge_snapshots (
              id TEXT, agent_version_id TEXT, embedding_provider TEXT,
              embedding_model_key TEXT, embedding_region TEXT,
              embedding_dimension INTEGER, embedding_policy_version TEXT);
            CREATE TABLE provider_export_manifests (
              scope_id TEXT, agent_version_id TEXT, provider_operation TEXT);
            CREATE TABLE provider_operations (
              scope_id TEXT, provider_operation TEXT, state TEXT,
              request_count INTEGER, charged_request_count INTEGER);
            CREATE TABLE debate_turns (
              id TEXT, debate_id TEXT, generation_status TEXT, retrieval_status TEXT,
              evidence_trace_json TEXT, retrieval_receipts_json TEXT);
            CREATE TABLE turn_sources (
              turn_id TEXT, snapshot_id TEXT, source_filename TEXT, rank INTEGER);
            """
        )
        connection.execute(
            "INSERT INTO knowledge_snapshots VALUES (?,?,?,?,?,?,?)",
            (
                value["snapshot_id"],
                value["target_version_id"],
                "dashscope",
                "text-embedding-v4",
                "cn-beijing",
                1024,
                "w4-embed-v1",
            ),
        )
        connection.execute(
            "INSERT INTO provider_export_manifests VALUES (?,?,?)",
            ("build-1", value["target_version_id"], "embedding"),
        )
        connection.executemany(
            "INSERT INTO provider_operations VALUES (?,?,?,?,?)",
            (
                ("build-1", "embedding_snapshot", "succeeded", 1, 1),
                (value["debate_id"], "embedding_query", "succeeded", 1, 1),
            ),
        )
        connection.execute(
            "INSERT INTO debate_turns VALUES (?,?,?,?,?,?)",
            (
                value["turn_id"],
                value["debate_id"],
                "final_ready",
                "matched",
                '[{"evidence_id":"e1"}]',
                '[{"chunk_id":"c1"}]',
            ),
        )
        connection.execute(
            "INSERT INTO turn_sources VALUES (?,?,?,?)",
            (
                value["turn_id"],
                value["snapshot_id"],
                "maya-cultural-knowledge-zh.md",
                1,
            ),
        )
        connection.commit()
    finally:
        connection.close()
    result = verify(f"sqlite:///{database_path}", path)
    assert result["status"] == "REAL_EMBED_E2E_PASS"
    assert result["total_calls"] == 2
    assert read_checkpoint(path, fixture)["state"] == "verified"
