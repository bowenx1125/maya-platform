"""Atomicity and rollback coverage for the additive Knowledge Set migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import Agent, AgentVersion, Job, ProviderOperation
from app.modules.knowledge_sets.models import (
    KnowledgeGenerationAcceptedStage,
    KnowledgeSet,
)
from sqlalchemy import MetaData, Table, event, select
from sqlalchemy.engine import Engine

from tests.legacy_organization import seed_legacy_organization

PREVIOUS_REVISION = "0035_w1_resource_ownership"
CURRENT_REVISION = "0036_knowledge_sets_assets"
NEXT_REVISION = "0037_knowledge_generation_runs"
PROVIDER_STAGE_REVISION = "0038_knowledge_generation_provider_stage"
MATERIALIZATION_REVISION = "0039_knowledge_generation_materialization"


def _database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _config(path: Path) -> Config:
    backend_root = Path(__file__).parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", _database_url(path))
    config.attributes["database_url"] = _database_url(path)
    return config


def _fingerprint(path: Path) -> str:
    """Fingerprint all SQLite schema objects and table rows, including Alembic head."""

    with sqlite3.connect(path) as connection:
        objects = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        table_rows: list[tuple[str, list[tuple[Any, ...]]]] = []
        for object_type, table_name, _owner, _sql in objects:
            if object_type != "table":
                continue
            escaped = str(table_name).replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{escaped}"').fetchall()
            table_rows.append((str(table_name), rows))
    encoded = json.dumps(
        {"objects": objects, "rows": table_rows},
        sort_keys=True,
        separators=(",", ":"),
        default=lambda value: {"bytes": value.hex()} if isinstance(value, bytes) else str(value),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _revision(path: Path) -> str:
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            return str(
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            )
    finally:
        database.dispose()


def _seed_populated_0035(path: Path) -> None:
    command.upgrade(_config(path), "0001_wave0_baseline")
    database = Database(_database_url(path))
    try:
        with database.session() as session:
            seed_legacy_organization(session)
    finally:
        database.dispose()
    command.upgrade(_config(path), PREVIOUS_REVISION)


@pytest.mark.parametrize(
    ("failure_match", "failure_label"),
    [
        ("CREATE TABLE knowledge_asset_versions", "asset-version table creation"),
        ("UPDATE alembic_version", "Alembic head update"),
    ],
)
def test_0036_failure_rolls_back_full_populated_database_and_retry_succeeds(
    tmp_path: Path,
    failure_match: str,
    failure_label: str,
) -> None:
    path = tmp_path / "populated.sqlite3"
    _seed_populated_0035(path)
    assert _revision(path) == PREVIOUS_REVISION
    before = _fingerprint(path)
    fired = False

    def inject_failure(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError(f"injected {failure_label} failure")

    event.listen(Engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected {failure_label} failure"):
            command.upgrade(_config(path), CURRENT_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", inject_failure)

    assert fired, f"the {failure_label} fault injection did not fire"
    assert _revision(path) == PREVIOUS_REVISION
    assert _fingerprint(path) == before

    command.upgrade(_config(path), CURRENT_REVISION)
    assert _revision(path) == CURRENT_REVISION
    database = Database(_database_url(path))
    try:
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    finally:
        database.dispose()


def test_fresh_database_upgrades_to_knowledge_sets_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh.sqlite3"
    command.upgrade(_config(path), CURRENT_REVISION)
    assert _revision(path) == CURRENT_REVISION
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "knowledge_sets",
            "knowledge_set_sources",
            "knowledge_assets",
            "knowledge_asset_versions",
            "knowledge_asset_version_sources",
            "agent_knowledge_sets",
        } <= tables
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_0036_downgrade_refuses_to_discard_saved_set_data(tmp_path: Path) -> None:
    path = tmp_path / "populated-knowledge-sets.sqlite3"
    _seed_populated_0035(path)
    command.upgrade(_config(path), CURRENT_REVISION)
    set_id = str(uuid4())
    with sqlite3.connect(path) as connection:
        user_id = connection.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        course_id = connection.execute("SELECT id FROM courses ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO knowledge_sets "
            "(id, owner_user_id, course_id, group_id, ownership_scope, visibility, display_name, "
            "metadata_revision, content_revision, authorization_epoch, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, 'personal', 'private', 'Retained fixture', 0, 0, 0, ?, ?)",
            (set_id, user_id, course_id, "2026-09-27T12:00:00+00:00", "2026-09-27T12:00:00+00:00"),
        )
    before = _fingerprint(path)

    with pytest.raises(RuntimeError, match="Knowledge Set data exists"):
        command.downgrade(_config(path), PREVIOUS_REVISION)

    assert _revision(path) == CURRENT_REVISION
    assert _fingerprint(path) == before


def _seed_populated_0036(path: Path) -> None:
    _seed_populated_0035(path)
    command.upgrade(_config(path), CURRENT_REVISION)
    with sqlite3.connect(path) as connection:
        user_id = connection.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        course_id = connection.execute("SELECT id FROM courses ORDER BY id LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO knowledge_sets "
            "(id, owner_user_id, course_id, group_id, ownership_scope, visibility, display_name, "
            "metadata_revision, content_revision, authorization_epoch, created_at, updated_at) "
            "VALUES (?, ?, ?, NULL, 'personal', 'private', 'Existing Knowledge', 2, 3, 1, ?, ?)",
            (
                str(uuid4()),
                user_id,
                course_id,
                "2026-09-28T12:00:00+00:00",
                "2026-09-28T12:00:00+00:00",
            ),
        )
        connection.commit()


def _table_fingerprints(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with sqlite3.connect(path) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for table in tables:
            escaped = table.replace('"', '""')
            rows = connection.execute(f'SELECT * FROM "{escaped}" ORDER BY rowid').fetchall()
            result[table] = hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str, separators=(",", ":")).encode()
            ).hexdigest()
    return result


@pytest.mark.parametrize(
    ("failure_match", "failure_label"),
    [
        ("CREATE TABLE knowledge_generation_runs", "generation table creation"),
        ("UPDATE alembic_version", "Alembic head update"),
    ],
)
def test_0037_failure_rolls_back_populated_0036_and_retry_succeeds(
    tmp_path: Path,
    failure_match: str,
    failure_label: str,
) -> None:
    path = tmp_path / "populated-0036.sqlite3"
    _seed_populated_0036(path)
    assert _revision(path) == CURRENT_REVISION
    before = _fingerprint(path)
    old_tables = _table_fingerprints(path)
    fired = False

    def inject_failure(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError(f"injected {failure_label} failure")

    event.listen(Engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected {failure_label} failure"):
            command.upgrade(_config(path), NEXT_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", inject_failure)

    assert fired
    assert _revision(path) == CURRENT_REVISION
    assert _fingerprint(path) == before

    command.upgrade(_config(path), NEXT_REVISION)
    assert _revision(path) == NEXT_REVISION
    after_tables = _table_fingerprints(path)
    retained_tables = {table for table in old_tables if table != "alembic_version"}
    assert {table: after_tables[table] for table in retained_tables} == {
        table: old_tables[table] for table in retained_tables
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT count(*) FROM knowledge_generation_runs").fetchone() == (
            0,
        )


def test_fresh_database_upgrades_to_knowledge_generation_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh-0037.sqlite3"
    command.upgrade(_config(path), NEXT_REVISION)
    assert _revision(path) == NEXT_REVISION
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA table_info(knowledge_generation_runs)").fetchall()
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(knowledge_generation_runs)")
        }
        assert {
            "ix_knowledge_generation_owner_created",
            "ix_knowledge_generation_state_lease",
            "ix_knowledge_generation_agent",
        } <= indexes
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_0037_downgrade_refuses_to_discard_generation_runs(tmp_path: Path) -> None:
    path = tmp_path / "generation-history.sqlite3"
    _seed_populated_0036(path)
    command.upgrade(_config(path), NEXT_REVISION)
    with sqlite3.connect(path) as connection:
        job_id = str(uuid4())
        connection.execute(
            "INSERT INTO jobs "
            "(id, operation, state, idempotency_key, attempt, created_at, updated_at) "
            "VALUES (?, 'knowledge_set.generate', 'pending', ?, 0, ?, ?)",
            (job_id, "b" * 64, "2026-09-28T12:00:00+00:00", "2026-09-28T12:00:00+00:00"),
        )
        connection.commit()
    before = _fingerprint(path)

    with pytest.raises(RuntimeError, match="Knowledge generation history exists"):
        command.downgrade(_config(path), CURRENT_REVISION)

    assert _revision(path) == NEXT_REVISION
    assert _fingerprint(path) == before


def _seed_populated_0037(path: Path) -> None:
    _seed_populated_0036(path)
    command.upgrade(_config(path), NEXT_REVISION)


@pytest.mark.parametrize(
    ("failure_match", "failure_label"),
    [
        ("CREATE TABLE knowledge_generation_accepted_stages", "accepted-stage table creation"),
        ("UPDATE alembic_version", "Alembic head update"),
    ],
)
def test_0038_failure_rolls_back_populated_0037_and_retry_succeeds(
    tmp_path: Path,
    failure_match: str,
    failure_label: str,
) -> None:
    path = tmp_path / "populated-0037.sqlite3"
    _seed_populated_0037(path)
    assert _revision(path) == NEXT_REVISION
    before = _fingerprint(path)
    old_tables = _table_fingerprints(path)
    fired = False

    def inject_failure(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError(f"injected {failure_label} failure")

    event.listen(Engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected {failure_label} failure"):
            command.upgrade(_config(path), PROVIDER_STAGE_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", inject_failure)

    assert fired
    assert _revision(path) == NEXT_REVISION
    assert _fingerprint(path) == before
    command.upgrade(_config(path), PROVIDER_STAGE_REVISION)
    assert _revision(path) == PROVIDER_STAGE_REVISION
    after_tables = _table_fingerprints(path)
    retained_tables = {table for table in old_tables if table != "alembic_version"}
    assert {table: after_tables[table] for table in retained_tables} == {
        table: old_tables[table] for table in retained_tables
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA table_info(knowledge_generation_accepted_stages)")
        assert connection.execute("SELECT count(*) FROM knowledge_generation_runs").fetchone() == (
            0,
        )


def test_fresh_database_upgrades_to_knowledge_provider_stage_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh-0038.sqlite3"
    command.upgrade(_config(path), PROVIDER_STAGE_REVISION)
    assert _revision(path) == PROVIDER_STAGE_REVISION
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(knowledge_generation_runs)")
        }
        assert "provider_manifest_hash" in columns
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(knowledge_generation_accepted_stages)")
        }
        assert "ix_knowledge_generation_stage_operation" in indexes
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_0038_downgrade_refuses_provider_operation_history(tmp_path: Path) -> None:
    path = tmp_path / "provider-stage-history.sqlite3"
    _seed_populated_0037(path)
    command.upgrade(_config(path), PROVIDER_STAGE_REVISION)
    now = "2026-09-28T12:00:00+00:00"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO provider_operations "
            "(id, scope_id, provider_operation, logical_item_id, attempt_no, request_hash, "
            "max_tokens, max_cost_cny, policy_hash, export_manifest_hash, build_manifest_hash, "
            "model_key, state, request_count, charged_request_count, created_at, updated_at) "
            "VALUES (?, ?, 'llm_knowledge_generate', ?, 1, ?, 0, 0, ?, ?, ?, ?, 'prepared', "
            "0, 0, ?, ?)",
            (
                str(uuid4()),
                "opaque-run-scope",
                "opaque-run-scope",
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "qwen-test-model",
                now,
                now,
            ),
        )
        connection.commit()
    before = _fingerprint(path)

    with pytest.raises(RuntimeError, match="Knowledge Provider history exists"):
        command.downgrade(_config(path), NEXT_REVISION)

    assert _revision(path) == PROVIDER_STAGE_REVISION
    assert _fingerprint(path) == before


def _seed_populated_0038(path: Path) -> None:
    _seed_populated_0037(path)
    command.upgrade(_config(path), PROVIDER_STAGE_REVISION)
    database = Database(_database_url(path))

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    stage_json = '{"assets":[]}'
    stage_hash = digest(stage_json)
    now = datetime.now(UTC)
    try:
        with database.session() as session:
            set_row = session.execute(
                select(
                    KnowledgeSet.id,
                    KnowledgeSet.owner_user_id,
                    KnowledgeSet.course_id,
                    KnowledgeSet.authorization_epoch,
                )
            ).first()
            assert set_row is not None
            agent = Agent(
                id=str(uuid4()),
                group_id=None,
                owner_user_id=set_row.owner_user_id,
                course_id=set_row.course_id,
                ownership_scope="personal",
                visibility="private",
                authorization_epoch=0,
                name="Migration fixture Agent",
                description="",
                metadata_revision=0,
                status="active",
                deleted_at=None,
                current_published_version_id=None,
                created_at=now,
                updated_at=now,
            )
            session.add(agent)
            session.flush()
            version = AgentVersion(
                id=str(uuid4()),
                agent_id=agent.id,
                version_seq=1,
                state="published",
                revision=0,
                agent_md="# Migration fixture",
                persona_required=False,
                avatar_config_json="{}",
                authorization_epoch=0,
                draft_visibility="private",
                published_visibility="private",
                published_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(version)
            session.flush()
            job_id = str(uuid4())
            run_id = str(uuid4())
            operation_id = str(uuid4())
            request_hash = digest("request")
            manifest_hash = digest("manifest")
            policy_hash = digest("policy")
            session.add(
                Job(
                    id=job_id,
                    operation="knowledge_set.generate",
                    state="pending",
                    idempotency_key=digest("input"),
                    attempt=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                ProviderOperation(
                    id=operation_id,
                    scope_id=run_id,
                    provider_operation="llm_knowledge_generate",
                    logical_item_id=run_id,
                    attempt_no=1,
                    request_hash=request_hash,
                    max_tokens=0,
                    max_cost_cny=0,
                    policy_hash=policy_hash,
                    export_manifest_hash=manifest_hash,
                    build_manifest_hash=digest("build"),
                    model_key="qwen-test-model",
                    state="accepted",
                    request_count=1,
                    charged_request_count=1,
                    staged_response_hash=stage_hash,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            # Seed the historical schema, not today's expanded ORM columns.
            runs = Table(
                "knowledge_generation_runs", MetaData(), autoload_with=session.connection()
            )
            session.execute(
                runs.insert().values(
                    id=run_id,
                    job_id=job_id,
                    input_key=digest("input"),
                    owner_user_id=set_row.owner_user_id,
                    course_id=set_row.course_id,
                    agent_id=agent.id,
                    agent_version_id=version.id,
                    knowledge_set_id=set_row.id,
                    provider_operation_id=operation_id,
                    provider_manifest_hash=manifest_hash,
                    request_hash=request_hash,
                    agent_md_hash=digest(version.agent_md),
                    agent_authorization_epoch=0,
                    set_authorization_epoch=set_row.authorization_epoch,
                    source_manifest_json="[]",
                    source_manifest_hash=digest("[]"),
                    state="pending",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                KnowledgeGenerationAcceptedStage(
                    run_id=run_id,
                    operation_id=operation_id,
                    request_hash=request_hash,
                    manifest_hash=manifest_hash,
                    policy_hash=policy_hash,
                    model_key="qwen-test-model",
                    schema_hash=digest("schema"),
                    canonical_stage_json=stage_json,
                    canonical_stage_hash=stage_hash,
                    item_count=0,
                    usage_json=None,
                    safe_error_code=None,
                    accepted_at=now,
                    created_at=now,
                )
            )
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("failure_match", "failure_label"),
    [
        ("CREATE TABLE knowledge_generation_items", "generation item table creation"),
        ("UPDATE alembic_version", "Alembic head update"),
    ],
)
def test_0039_failure_rolls_back_populated_0038_and_retry_succeeds(
    tmp_path: Path,
    failure_match: str,
    failure_label: str,
) -> None:
    path = tmp_path / "populated-0038.sqlite3"
    _seed_populated_0038(path)
    assert _revision(path) == PROVIDER_STAGE_REVISION
    before = _fingerprint(path)
    old_tables = _table_fingerprints(path)
    fired = False

    def inject_failure(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        nonlocal fired
        if failure_match in statement:
            fired = True
            raise RuntimeError(f"injected {failure_label} failure")

    event.listen(Engine, "before_cursor_execute", inject_failure)
    try:
        with pytest.raises(RuntimeError, match=f"injected {failure_label} failure"):
            command.upgrade(_config(path), MATERIALIZATION_REVISION)
    finally:
        event.remove(Engine, "before_cursor_execute", inject_failure)

    assert fired
    assert _revision(path) == PROVIDER_STAGE_REVISION
    assert _fingerprint(path) == before
    command.upgrade(_config(path), MATERIALIZATION_REVISION)
    assert _revision(path) == MATERIALIZATION_REVISION
    after_tables = _table_fingerprints(path)
    retained_tables = {table for table in old_tables if table != "alembic_version"}
    assert {table: after_tables[table] for table in retained_tables} == {
        table: old_tables[table] for table in retained_tables
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT count(*) FROM knowledge_generation_runs").fetchone() == (
            1,
        )
        assert connection.execute(
            "SELECT count(*) FROM knowledge_generation_accepted_stages"
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM knowledge_generation_items").fetchone() == (
            0,
        )


def test_fresh_database_upgrades_to_materialization_head(tmp_path: Path) -> None:
    path = tmp_path / "fresh-0039.sqlite3"
    command.upgrade(_config(path), MATERIALIZATION_REVISION)
    assert _revision(path) == MATERIALIZATION_REVISION
    with sqlite3.connect(path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "knowledge_generation_source_receipts",
            "knowledge_generation_items",
        } <= tables
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(knowledge_assets)")}
        assert "generation_lineage_key" in columns
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(knowledge_generation_items)")
        }
        assert {
            "ix_knowledge_generation_items_run_state",
            "ix_knowledge_generation_items_lineage",
        } <= indexes
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_0039_downgrade_refuses_materialization_history_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "materialization-history.sqlite3"
    _seed_populated_0038(path)
    command.upgrade(_config(path), MATERIALIZATION_REVISION)
    with sqlite3.connect(path) as connection:
        run_id = str(connection.execute("SELECT id FROM knowledge_generation_runs").fetchone()[0])
        stage_hash = str(
            connection.execute(
                "SELECT canonical_stage_hash FROM knowledge_generation_accepted_stages"
            ).fetchone()[0]
        )
        now = "2026-09-28T12:00:00+00:00"
        connection.execute(
            "INSERT INTO knowledge_generation_items "
            "(id, run_id, stage_hash, item_key, item_index, kind, lineage_key, candidate_hash, "
            "source_receipt_ids_json, citation_unverified_count, state, safe_error_code, asset_id, "
            "asset_version_id, expected_asset_version_seq, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 0, 'invalid', NULL, ?, '[]', 0, 'failed', "
            "'provider_asset_invalid', NULL, NULL, NULL, ?, ?)",
            (
                str(uuid4()),
                run_id,
                stage_hash,
                hashlib.sha256(b"item").hexdigest(),
                hashlib.sha256(b"candidate").hexdigest(),
                now,
                now,
            ),
        )
        connection.commit()
    before = _fingerprint(path)

    with pytest.raises(RuntimeError, match="Knowledge materialization history exists"):
        command.downgrade(_config(path), PROVIDER_STAGE_REVISION)

    assert _revision(path) == MATERIALIZATION_REVISION
    assert _fingerprint(path) == before
