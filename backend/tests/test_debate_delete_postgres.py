"""Delete All must remove LLM recovery inputs on PostgreSQL (production).

Production (2026-10-18) rejected Delete All for every Debate that had produced
speech: ``llm_recovery_inputs`` rows were only deleted on the SQLite path that
lifts the immutability trigger, so on PostgreSQL ``DELETE FROM
provider_operations`` hit ``fk_llm_recovery_inputs_operation`` and the request
failed with a 500.  Rebirth/Remake read ``sqlite_master`` unconditionally for
the same rows.

The static checks run everywhere.  Set ``MAYA_TEST_POSTGRES_URL`` (a scratch
database; its ``public`` schema is dropped) to also execute them there.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from app.modules.debates import cleanup
from app.modules.debates import models as _debate_models
from sqlalchemy import text

from tests.test_cleanup_debate_runtime import _seed_runtime_graph

del _debate_models

_APP = Path(__file__).resolve().parents[1] / "app"
_POSTGRES_URL = os.environ.get("MAYA_TEST_POSTGRES_URL")


def test_delete_graph_removes_recovery_inputs_without_sqlite_trigger_capture():
    source = (_APP / "modules/debates/cleanup.py").read_text(encoding="utf-8")
    body = source.split("def _delete_graph(", 1)[1].split("\ndef ", 1)[0]
    before_operations = body.split('remove("provider_operations"', 1)[0]
    # Recovery inputs restrict provider_operations; their delete may not be
    # conditional on the SQLite-only trigger capture.
    assert 'remove("llm_recovery_inputs", "operation_id"' in before_operations
    assert "if captured_triggers is not None:\n        if graph" not in before_operations


def test_rebirth_does_not_read_sqlite_master_for_recovery_inputs():
    source = (_APP / "modules/debates/rebirth.py").read_text(encoding="utf-8")
    assert "_capture_recovery_triggers" not in source
    assert source.count("_delete_recovery_inputs(") == 2


@pytest.fixture
def postgres_database(tmp_path):
    if not _POSTGRES_URL:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    from app.core.db import Database

    database = Database(_POSTGRES_URL, tmp_path)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    database.initialize_schema()
    ids = _seed_runtime_graph(database, tmp_path)
    try:
        yield database, ids, tmp_path
    finally:
        database.engine.dispose()


def _count(database, sql: str, **params: str) -> int:
    with database.session() as session:
        return int(session.execute(text(sql), params).scalar_one())


def test_delete_all_removes_debate_with_recovery_inputs_on_postgres(postgres_database):
    database, ids, data_root = postgres_database
    assert _count(database, "SELECT count(*) FROM llm_recovery_inputs") == 1
    with database.session() as session:
        result = asyncio.run(
            cleanup.delete_all(
                session,
                actor_user_id=ids["teacher"],
                debate_id=ids["debate"],
                expected_revision=1,
                expected_control_version=1,
                data_root=data_root,
                idempotency_key="pg-delete-all-recovery-001",
            )
        )
    assert result.debate_id == ids["debate"]
    assert result.deleted_rows.get("llm_recovery_inputs") == 1
    assert _count(database, "SELECT count(*) FROM debates WHERE id=:id", id=ids["debate"]) == 0
    assert _count(database, "SELECT count(*) FROM llm_recovery_inputs") == 0
    assert (
        _count(
            database, "SELECT count(*) FROM provider_operations WHERE id=:id", id=ids["operation"]
        )
        == 0
    )
    # Authored rows stay.
    assert _count(database, "SELECT count(*) FROM courses WHERE id=:id", id=ids["course"]) == 1
    assert _count(database, "SELECT count(*) FROM agents WHERE id=:id", id=ids["agent"]) == 1


def test_scoped_recovery_input_delete_runs_on_postgres(postgres_database):
    database, ids, _data_root = postgres_database
    with database.session() as session:
        assert cleanup._delete_recovery_inputs(session, "turn_id", set()) == 0
        assert cleanup._delete_recovery_inputs(session, "turn_id", {ids["turn"]}) == 1
        session.commit()
    assert _count(database, "SELECT count(*) FROM llm_recovery_inputs") == 0
