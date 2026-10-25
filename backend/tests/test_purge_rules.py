"""Hard deletes cover every foreign key, keep records, and unlink files after commit."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.core.db import Database, registered_metadata
from app.core.models import StoredFile
from app.modules import purge as purge_module
from app.modules.deferred_files import pending_unlinks, unlink_after_commit
from app.modules.purge import CLEANUP_ROOTS, RECORD_ROOTS, REFERENCE_RULES
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from tests.postgres_db import named_url

# Rows of these tables are records, grades, answers, Debate copies or provider
# ledgers. A cleanup may clear a link on them but never deletes them.
PROTECTED_PREFIXES = (
    "assessment_",
    "learning_",
    "debate",
    "provider_",
    "llm_",
    "civilization_",
    "barrage_",
    "interaction_",
    "votes",
    "turn_sources",
    "position_history",
    "playback_states",
)


def _model_foreign_keys() -> dict[str, list[tuple[str, tuple[str, ...], tuple[bool, ...]]]]:
    import app.main  # noqa: F401  (registers every router's models, card rooms included)

    incoming: dict[str, list[tuple[str, tuple[str, ...], tuple[bool, ...]]]] = {}
    for table in registered_metadata().tables.values():
        for foreign_key in table.foreign_key_constraints:
            columns = tuple(column.name for column in foreign_key.columns)
            nullable = tuple(bool(column.nullable) for column in foreign_key.columns)
            incoming.setdefault(foreign_key.referred_table.name, []).append(
                (table.name, columns, nullable)
            )
    return incoming


def _key(child: str, columns: tuple[str, ...], parent: str) -> str:
    return f"{child}.{','.join(sorted(columns))}->{parent}"


def _closure(roots: tuple[str, ...]) -> list[str]:
    incoming = _model_foreign_keys()
    seen: list[str] = []
    queue = list(roots)
    while queue:
        table = queue.pop(0)
        if table in seen:
            continue
        seen.append(table)
        for child, columns, _nullable in incoming.get(table, []):
            if REFERENCE_RULES.get(_key(child, columns, table)) == "delete":
                queue.append(child)
    return seen


def test_every_foreign_key_into_a_deleted_table_has_a_rule() -> None:
    incoming = _model_foreign_keys()
    missing = [
        _key(child, columns, table)
        for table in _closure(CLEANUP_ROOTS + RECORD_ROOTS)
        for child, columns, _nullable in incoming.get(table, [])
        if _key(child, columns, table) not in REFERENCE_RULES
    ]
    assert missing == [], "add a rule to app/modules/purge.py REFERENCE_RULES"
    existing = {
        _key(child, columns, table)
        for table, keys in incoming.items()
        for child, columns, _nullable in keys
    }
    assert sorted(set(REFERENCE_RULES) - existing) == []


def test_cleanup_never_deletes_records_grades_debates_or_ledgers() -> None:
    reached = _closure(CLEANUP_ROOTS)
    assert [table for table in reached if table.startswith(PROTECTED_PREFIXES)] == []
    incoming = _model_foreign_keys()
    for table in reached:
        for child, columns, _nullable in incoming.get(table, []):
            if child.startswith(PROTECTED_PREFIXES):
                assert REFERENCE_RULES[_key(child, columns, table)] in {"null", "protect"}


def test_a_cleared_link_is_a_column_that_can_be_null() -> None:
    incoming = _model_foreign_keys()
    for table, keys in incoming.items():
        for child, columns, nullable in keys:
            if REFERENCE_RULES.get(_key(child, columns, table)) == "null":
                assert all(nullable), _key(child, columns, table)


def _settings_root(app_bundle: tuple[FastAPI, Database, Settings]) -> tuple[Database, Path]:
    _app, database, settings = app_bundle
    return database, settings.resolved_data_root


def _stored_file(database: Database, data_root: Path) -> tuple[str, Path]:
    file_id = str(uuid4())
    relative = f"snapshots/purge-probe/{file_id}.bin"
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"probe")
    with database.session() as db:
        db.add(
            StoredFile(
                id=file_id,
                relative_path=relative,
                kind="snapshot",
                sha256="0" * 64,
                size_bytes=5,
                state="active",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
    return file_id, path


def test_a_rolled_back_delete_keeps_the_file(
    app_bundle: tuple[FastAPI, Database, Settings], client: TestClient
) -> None:
    from app.modules.real_delete import release_stored_file

    database, data_root = _settings_root(app_bundle)
    file_id, path = _stored_file(database, data_root)
    with database.session() as db:
        release_stored_file(db, data_root, file_id)
        assert db.get(StoredFile, file_id) is None
        assert path.is_file(), "nothing is unlinked before the commit"
        db.rollback()
    assert path.is_file()
    with database.session() as db:
        assert db.get(StoredFile, file_id) is not None
        assert pending_unlinks(db) == []

    with database.session() as db:
        release_stored_file(db, data_root, file_id)
        db.commit()
    assert not path.exists()


def test_a_rolled_back_savepoint_keeps_its_file_and_the_outer_commit_unlinks_the_rest(
    app_bundle: tuple[FastAPI, Database, Settings], client: TestClient
) -> None:
    database, data_root = _settings_root(app_bundle)
    kept = data_root / "snapshots" / "purge-probe" / "kept.bin"
    gone = data_root / "snapshots" / "purge-probe" / "gone.bin"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes(b"k")
    gone.write_bytes(b"g")
    with database.session() as db:
        unlink_after_commit(db, data_root, "snapshots/purge-probe/gone.bin")
        nested = db.begin_nested()
        unlink_after_commit(db, data_root, "snapshots/purge-probe/kept.bin")
        nested.rollback()
        db.commit()
    assert kept.is_file()
    assert not gone.exists()


def test_a_referenced_file_is_protected(
    app_bundle: tuple[FastAPI, Database, Settings], client: TestClient
) -> None:
    from app.core.models import VoiceProfile

    database, data_root = _settings_root(app_bundle)
    file_id, path = _stored_file(database, data_root)
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            VoiceProfile(
                id=str(uuid4()),
                scope="personal",
                group_id=None,
                display_name="Holds a sample",
                status="failed",
                provider_key="mock",
                target_model_key="qwen3-tts-flash",
                recovery_name=f"probe-{uuid4()}",
                provenance_json="{}",
                safe_error_code="voice_clone_refused",
                sample_file_id=file_id,
                created_at=now,
                updated_at=now,
            )
        )
    with database.session() as db:
        assert purge_module.purge_ids(db, "stored_files", [file_id]) == set()
        db.commit()
    assert path.is_file()


def test_deleting_knowledge_with_an_accepted_generation_run_keeps_the_provider_ledger(
    app_bundle: tuple[FastAPI, Database, Settings], client: TestClient
) -> None:
    """Production 2026-10-24: knowledge_generation_accepted_stages blocked the run delete."""

    from app.core.models import ProviderOperation
    from app.modules.knowledge_sets.models import (
        KnowledgeGenerationAcceptedStage,
        KnowledgeGenerationRun,
        KnowledgeSet,
    )
    from app.modules.real_delete import hard_delete_knowledge_set

    from tests.test_knowledge_generation_materialization import (
        _accept_stage,
        _create_generation_run,
    )

    database, data_root = _settings_root(app_bundle)
    _agent_id, _document_id, run_id, set_id = _create_generation_run(client, database)
    _accept_stage(database, run_id, [{"kind": "note", "title": "Kept", "body": "Ledger stays."}])
    with database.session() as db:
        operation_id = db.get(KnowledgeGenerationRun, run_id).provider_operation_id
        row = db.get(KnowledgeSet, set_id)
        assert row is not None
        hard_delete_knowledge_set(db, row, data_root)
        db.commit()
    with database.session() as db:
        assert db.get(KnowledgeSet, set_id) is None
        assert db.get(KnowledgeGenerationRun, run_id) is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationAcceptedStage)
                .where(KnowledgeGenerationAcceptedStage.run_id == run_id)
            )
            == 0
        )
        # The charged-call record is a ledger row, not part of the Knowledge.
        assert db.get(ProviderOperation, operation_id) is not None


def _postgres(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> tuple[Settings, Database]:
    url = os.environ.get("MAYA_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("MAYA_TEST_POSTGRES_URL is not set")
    url = named_url("pg", schema=False)
    _app, sqlite_database, base = app_factory()
    sqlite_database.dispose()
    settings = base.model_copy(update={"database_url": url})
    database = Database(url, settings.data_root)
    with database.engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    purge_module.reset_catalog_cache()
    return settings, database


def _restrict_every_foreign_key(database: Database) -> None:
    """Make every ON DELETE rule RESTRICT, so nothing relies on the database's cascade."""

    with database.engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE contype = 'f' AND confdeltype <> 'r'"
            )
        ).all()
        for table, name, definition in rows:
            stripped = re.sub(
                r" ON DELETE (CASCADE|SET NULL|SET DEFAULT|NO ACTION)", "", definition
            )
            deferrable = "DEFERRABLE" in stripped
            # A deferrable constraint cannot RESTRICT; NO ACTION still never cascades.
            rule = "ON DELETE NO ACTION" if deferrable else "ON DELETE RESTRICT"
            restricted = re.sub(r"(REFERENCES \S+\([^)]*\))", rf"\1 {rule}", stripped, count=1)
            connection.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
            connection.execute(text(f'ALTER TABLE {table} ADD CONSTRAINT "{name}" {restricted}'))
    purge_module.reset_catalog_cache()


def test_postgres_prune_with_a_restricted_export_manifest_clears_the_link(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    """Production 2026-10-24: fk_provider_export_manifests_agent_version is RESTRICT there."""

    from app.core.models import Agent, AgentVersion
    from app.main import create_app
    from app.modules.demo_baseline.service import ensure_demo_baseline
    from app.modules.real_delete import prune_agent_versions

    settings, database = _postgres(app_factory)
    app = create_app(settings, database)
    try:
        with TestClient(app):
            with database.session() as db:
                ensure_demo_baseline(db, settings.resolved_data_root)
            _restrict_every_foreign_key(database)
            with database.session() as db:
                agent = db.scalars(select(Agent).limit(1)).first()
                assert agent is not None
                current = db.get(AgentVersion, agent.current_published_version_id)
                assert current is not None
                old_ids = []
                for seq in (90, 91):
                    old = AgentVersion(
                        **{
                            column.key: getattr(current, column.key)
                            for column in AgentVersion.__table__.columns
                            if column.key not in {"id", "version_seq", "state"}
                        },
                        id=str(uuid4()),
                        version_seq=seq,
                        state="superseded",
                    )
                    old.knowledge_snapshot_id = None
                    db.add(old)
                    old_ids.append(old.id)
                db.flush()
                manifest_id = str(uuid4())
                db.execute(text("SET LOCAL session_replication_role = replica"))
                db.execute(
                    text(
                        "INSERT INTO provider_export_manifests (id, policy_snapshot_id, scope_id, "
                        "provider_operation, model_key, policy_hash, build_manifest_hash, "
                        "persona_spec_hash, fields_json, operation_revision, contains_secret, "
                        "contains_identity, contains_private_audio, contains_teacher_note, "
                        "manifest_hash, agent_version_id, max_attempts, max_total_tokens, "
                        "max_cost_cny, created_at) VALUES (:id, :policy, 'scope', 'llm_chat', "
                        "'m', :h, :h, :h, '{}', 1, false, false, false, false, :mh, :version, "
                        "1, 0, 0, now())"
                    ),
                    {
                        "id": manifest_id,
                        "policy": str(uuid4()),
                        "h": "a" * 64,
                        "mh": uuid4().hex * 2,
                        "version": old_ids[0],
                    },
                )
                db.execute(text("SET LOCAL session_replication_role = origin"))
                db.commit()
            with database.session() as db:
                assert prune_agent_versions(db, agent.id, settings.resolved_data_root) >= 1
                db.commit()
            with database.session() as db:
                assert db.get(AgentVersion, old_ids[0]) is None
                linked = db.execute(
                    text("SELECT agent_version_id FROM provider_export_manifests WHERE id = :id"),
                    {"id": manifest_id},
                ).scalar_one()
                assert linked is None
    finally:
        database.dispose()
        purge_module.reset_catalog_cache()


def test_postgres_every_foreign_key_in_the_database_has_a_rule(
    app_factory: Callable[..., tuple[FastAPI, Database, Settings]],
) -> None:
    from app.main import create_app

    settings, database = _postgres(app_factory)
    app = create_app(settings, database)
    try:
        with TestClient(app):
            catalog = purge_module._catalog(database.engine)
            deleted = set(_closure(CLEANUP_ROOTS + RECORD_ROOTS))
            missing = [
                foreign_key.key
                for table in deleted
                for foreign_key in catalog.get(table, [])
                if foreign_key.key not in REFERENCE_RULES
            ]
            assert missing == []
    finally:
        database.dispose()
        purge_module.reset_catalog_cache()
