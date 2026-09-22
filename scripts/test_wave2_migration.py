"""Deterministic fresh/repeat/populated checks for Wave 2 migrations 0004/0005.

The probe creates all SQLite databases below a temporary directory.  The
populated case stops at each prior revision, fingerprints every pre-existing
row (including the voice operation ledger), installs update/delete sentinels
on the three voice tables, then upgrades to 0004 and 0005 and checks exact
composite foreign-key behaviour plus an empty ``foreign_key_check``.  The
manual-advance step also proves that SQLite rebuilds only ``playback_states``
and does not persist the derived ``next_turn_ready`` field.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import Database
from app.core.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    SnapshotDocument,
    StoredFile,
    VoicePreview,
    VoiceProfile,
    VoiceProviderOperation,
)
from tests.legacy_organization import seed_legacy_organization

WAVE_0_REVISION = "0001_wave0_baseline"
WAVE_1_REVISION = "0002_wave1_agents_rag"
WAVE_1B_REVISION = "0003_wave1b_avatar_voice"
WAVE_2_REVISION = "0004_wave2_debate_playback"
WAVE_2_MANUAL_ADVANCE_REVISION = "0005_wave2_manual_advance"
PRE_WAVE_3_POLISH_REVISION = "0006_pre_wave3_polish"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def run_alembic(path: Path, target: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Alembic upgrade to {target} failed: {result.stderr[-1000:]}")


def downgrade_alembic(path: Path, target: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", target],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Alembic downgrade to {target} failed: {result.stderr[-1000:]}")


def revision(path: Path) -> str | None:
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    finally:
        database.dispose()


def canonical(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    return value


def table_columns(path: Path) -> dict[str, list[str]]:
    """Return the exact column order used for pre-migration fingerprints."""

    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        return {
            table: [item["name"] for item in inspector.get_columns(table)]
            for table in inspector.get_table_names()
        }
    finally:
        database.dispose()


def table_fingerprints(
    path: Path,
    *,
    columns_by_table: dict[str, list[str]] | None = None,
) -> dict[str, str]:
    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        result: dict[str, str] = {}
        with database.engine.connect() as connection:
            for table in sorted(inspector.get_table_names()):
                configured_columns = (
                    columns_by_table.get(table) if columns_by_table is not None else None
                )
                columns = (
                    configured_columns
                    if configured_columns is not None
                    else [item["name"] for item in inspector.get_columns(table)]
                )
                available = {item["name"] for item in inspector.get_columns(table)}
                if not set(columns).issubset(available):
                    raise AssertionError(
                        f"Fingerprint columns disappeared from {table}: "
                        f"{sorted(set(columns) - available)}"
                    )
                selected = ", ".join(columns)
                rows = connection.execute(text(f"SELECT {selected} FROM {table}"))
                values = [
                    {column: canonical(value) for column, value in zip(columns, row, strict=True)}
                    for row in rows
                ]
                encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
                result[table] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return result
    finally:
        database.dispose()


def insert_wave1_rows_and_voice_ledger(database: Database) -> None:
    now = datetime.now(UTC)
    agent_id, version_id = str(uuid4()), str(uuid4())
    source_file_id, document_id = str(uuid4()), str(uuid4())
    snapshot_id, snapshot_document_id, chunk_id = (str(uuid4()) for _ in range(3))
    system_voice_id, preview_file_id, preview_id, operation_id = (str(uuid4()) for _ in range(4))
    idempotency_id, job_id, file_operation_id = (str(uuid4()) for _ in range(3))
    with database.session() as session:
        session.add(
            StoredFile(
                id=source_file_id,
                kind="markdown",
                relative_path=f"groups/{GROUP_ID}/knowledge/{document_id}/source.md",
                sha256="1" * 64,
                size_bytes=9,
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        # The probe intentionally inserts at the historical 0003 schema.
        # Use a column-explicit Core insert so later ORM-only columns (for
        # example 0006 ``metadata_revision``) do not leak backward into the
        # frozen Wave 1 fixture.
        session.execute(
            text(
                "INSERT INTO agents "
                "(id, group_id, name, description, status, "
                "current_published_version_id, created_at, updated_at) "
                "VALUES (:id, :group_id, :name, :description, :status, "
                ":current_published_version_id, :created_at, :updated_at)"
            ),
            {
                "id": agent_id,
                "group_id": GROUP_ID,
                "name": "Migration Agent",
                "description": "Wave 1 preservation row",
                "status": "active",
                "current_published_version_id": version_id,
                "created_at": now,
                "updated_at": now,
            },
        )
        session.add(
            KnowledgeDocument(
                id=document_id,
                group_id=GROUP_ID,
                source_filename="migration.md",
                stored_file_id=source_file_id,
                char_count=9,
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash="2" * 64,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        # AgentVersion gained nullable Persona columns in 0009. Keep this
        # historical 0003 fixture column-explicit just like Agent above so an
        # old-revision probe never asks SQLite to insert future ORM fields.
        session.execute(
            text(
                "INSERT INTO agent_versions "
                "(id, agent_id, version_seq, state, revision, agent_md, "
                "avatar_config_json, voice_profile_id, knowledge_snapshot_id, "
                "published_at, created_at, updated_at) "
                "VALUES (:id, :agent_id, :version_seq, :state, :revision, :agent_md, "
                ":avatar_config_json, :voice_profile_id, :knowledge_snapshot_id, "
                ":published_at, :created_at, :updated_at)"
            ),
            {
                "id": version_id,
                "agent_id": agent_id,
                "version_seq": 0,
                "state": "published",
                "revision": 1,
                "agent_md": "# Migration Agent",
                "avatar_config_json": (
                    '{"template_id":"wave1-default-head","material_theme":"demo",'
                    '"default_expression":"neutral","expression_strength":"medium",'
                    '"motion_style":"calm"}'
                ),
                "voice_profile_id": None,
                "knowledge_snapshot_id": snapshot_id,
                "published_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        # Keep the historical 0003 Snapshot insert independent of the latest
        # ORM too. Migration 0013 adds the closed five-field embedding
        # identity, which must not be emitted before those columns exist.
        session.execute(
            text(
                "INSERT INTO knowledge_snapshots "
                "(id, agent_version_id, combined_file_id, content_hash, "
                "total_char_count, embedding_model_key, chunking_config_json, created_at) "
                "VALUES (:id, :agent_version_id, :combined_file_id, :content_hash, "
                ":total_char_count, :embedding_model_key, :chunking_config_json, :created_at)"
            ),
            {
                "id": snapshot_id,
                "agent_version_id": version_id,
                "combined_file_id": source_file_id,
                "content_hash": "3" * 64,
                "total_char_count": 9,
                "embedding_model_key": "mock",
                "chunking_config_json": "{}",
                "created_at": now,
            },
        )
        session.add(
            SnapshotDocument(
                id=snapshot_document_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                stored_file_id=source_file_id,
                source_filename="migration.md",
                char_count=9,
                order_index=0,
            )
        )
        session.flush()
        session.add(
            KnowledgeChunk(
                id=chunk_id,
                snapshot_id=snapshot_id,
                snapshot_document_id=snapshot_document_id,
                document_id=document_id,
                chunk_index=0,
                chunk_text="Migration",
                start_offset=0,
                end_offset=9,
                embedding_blob=b"\x00" * 4,
                embedding_dimension=1,
                embedding_key="mock",
            )
        )
        session.add(
            VoiceProfile(
                id=system_voice_id,
                scope="system",
                group_id=None,
                display_name="System fallback ledger fixture",
                status="preview_ready",
                provider_key="mock",
                target_model_key="mock-tts",
                external_id_encrypted=b"encrypted-synthetic-id",
                recovery_name="migration-system-fallback",
                provenance_json='{"fixture":true}',
                source_filename=None,
                source_sha256=None,
                consent_copy_version=None,
                consent_actor_user_id=None,
                consent_accepted_at=None,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            VoiceProviderOperation(
                id=operation_id,
                profile_id=system_voice_id,
                operation_type="tts_preview",
                profile_scope="system",
                state="failed",
                attempt=1,
                claim_token="migration-claim-token",
                request_hash="4" * 64,
                provider_deadline=now + timedelta(minutes=1),
                request_count=1,
                charged_request_count=0,
                input_bytes=12,
                output_bytes=0,
                safe_request_id="migration-safe-request",
                safe_error_code="provider_unavailable",
                idempotency_record_id=None,
                dispatched_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            StoredFile(
                id=preview_file_id,
                kind="voice_preview",
                relative_path=f"tmp/voice-preview/{preview_id}.wav",
                sha256="5" * 64,
                size_bytes=12,
                state="staged",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            VoicePreview(
                id=preview_id,
                profile_id=system_voice_id,
                group_id=None,
                stored_file_id=preview_file_id,
                relative_path=f"tmp/voice-preview/{preview_id}.wav",
                state="active",
                expires_at=now + timedelta(minutes=5),
                created_at=now,
                confirmed_at=None,
            )
        )
        # These rows intentionally exercise the two Wave 1 tables that 0004
        # recreates with new nullable debate columns.  Use SQL text here: the
        # current ORM includes those Wave 2 columns, while this fixture is
        # still running at the Wave 1B schema.
        session.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, actor_user_id, operation, key, request_hash, state, claim_token, "
                "lease_expires_at, status_code, response_json, created_at, updated_at) "
                "VALUES (:id, :actor_user_id, :operation, :key, :request_hash, :state, "
                ":claim_token, :lease_expires_at, :status_code, :response_json, "
                ":created_at, :updated_at)"
            ),
            {
                "id": idempotency_id,
                "actor_user_id": TEACHER_ID,
                "operation": "documentUpload",
                "key": "migration-populated-file-operation-001",
                "request_hash": "6" * 64,
                "state": "completed",
                "claim_token": "migration-idempotency-claim",
                "lease_expires_at": now + timedelta(minutes=1),
                "status_code": 201,
                "response_json": '{"fixture":true}',
                "created_at": now,
                "updated_at": now,
            },
        )
        session.execute(
            text(
                "INSERT INTO jobs "
                "(id, document_id, operation, state, safe_error_code, attempt, "
                "created_at, updated_at) VALUES (:id, :document_id, :operation, "
                ":state, :safe_error_code, :attempt, :created_at, :updated_at)"
            ),
            {
                "id": job_id,
                "document_id": document_id,
                "operation": "index",
                "state": "completed",
                "safe_error_code": None,
                "attempt": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        session.execute(
            text(
                "INSERT INTO file_operations "
                "(id, idempotency_record_id, operation_type, entity_id, request_id, "
                "source_relative_path, target_relative_path, expected_sha256, state, "
                "safe_error_code, created_at, updated_at) VALUES (:id, :idempotency_id, "
                ":operation_type, :entity_id, :request_id, :source_path, :target_path, "
                ":expected_sha256, :state, :safe_error_code, :created_at, :updated_at)"
            ),
            {
                "id": file_operation_id,
                "idempotency_id": idempotency_id,
                "operation_type": "document_upload",
                "entity_id": document_id,
                "request_id": str(uuid4()),
                "source_path": f"tmp/staging/{document_id}.md",
                "target_path": f"groups/{GROUP_ID}/knowledge/{document_id}/source.md",
                "expected_sha256": "2" * 64,
                "state": "promoted",
                "safe_error_code": None,
                "created_at": now,
                "updated_at": now,
            },
        )


def insert_legacy_playback_fixture(path: Path) -> dict[str, str]:
    """Insert a fully valid 0004 Debate/Turn/Playback row.

    This is intentionally done after 0004 is applied.  It proves that 0005
    rebuilds an existing child row rather than only accepting an empty table.
    The fixture uses the synthetic Wave 1 Agent/Version/Snapshot rows above so
    every composite foreign key is exercised with real parent keys.
    """

    database = Database(database_url(path))
    debate_id, participant_id, turn_id, playback_id = (str(uuid4()) for _ in range(4))
    now = datetime.now(UTC)
    try:
        with database.engine.begin() as connection:
            parent = connection.execute(
                text(
                    "SELECT a.id, a.group_id, av.id, av.knowledge_snapshot_id "
                    "FROM agents AS a JOIN agent_versions AS av "
                    "ON av.id=a.current_published_version_id "
                    "WHERE a.name='Migration Agent' LIMIT 1"
                )
            ).first()
            if parent is None:
                raise AssertionError("populated migration fixture Agent is missing")
            agent_id, group_id, version_id, snapshot_id = (str(value) for value in parent)
            connection.execute(
                text(
                    "INSERT INTO debates "
                    "(id, course_id, topic, rule_set_id, rule_snapshot_json, status, "
                    "revision, last_sequence, cancellation_generation, created_by, "
                    "created_at, updated_at, started_at, finished_at, total_duration_seconds, "
                    "turn_duration_seconds) VALUES (:id, :course_id, :topic, :rule_set_id, "
                    ":rule_snapshot_json, 'running', 0, 0, 0, :created_by, :created_at, "
                    ":updated_at, :started_at, NULL, NULL, NULL)"
                ),
                {
                    "id": debate_id,
                    "course_id": COURSE_ID,
                    "topic": "manual advance migration fixture",
                    "rule_set_id": "ordered_multi_agent_rounds_demo_v1",
                    "rule_snapshot_json": "{}",
                    "created_by": TEACHER_ID,
                    "created_at": now,
                    "updated_at": now,
                    "started_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO debate_participants "
                    "(id, debate_id, course_id, group_id, agent_id, agent_version_id, "
                    "knowledge_snapshot_id, slot, order_index, agent_name, version_label, "
                    "avatar_config_json, requested_voice_profile_id, effective_voice_kind, "
                    "effective_voice_profile_id, voice_fallback_active, stance_mode, "
                    "initial_stance, current_stance, teacher_note, initial_position_summary, "
                    "current_position_summary, created_at, updated_at) VALUES "
                    "(:id, :debate_id, :course_id, :group_id, :agent_id, :version_id, "
                    ":snapshot_id, 'A', 0, 'Migration Agent', 'V1.0', :avatar_config, NULL, "
                    "'mock_sentinel', NULL, 1, 'open', NULL, NULL, '', '', '', :created_at, "
                    ":updated_at)"
                ),
                {
                    "id": participant_id,
                    "debate_id": debate_id,
                    "course_id": COURSE_ID,
                    "group_id": group_id,
                    "agent_id": agent_id,
                    "version_id": version_id,
                    "snapshot_id": snapshot_id,
                    "avatar_config": (
                        '{"template_id":"wave1-default-head",'
                        '"material_theme":"demo","default_expression":"neutral",'
                        '"expression_strength":"medium","motion_style":"calm"}'
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO debate_turns "
                    "(id, debate_id, participant_id, knowledge_snapshot_id, round_no, "
                    "turn_index, generation_status, publication_status, preparation_stage, "
                    "speech, structured_json, predecessor_turn_ids_json, transcript_hash, "
                    "cutoff_turn_index, retrieval_status, grounding_mode, "
                    "retrieval_receipts_json, word_count, attempt, audio_file_id, "
                    "audio_duration_ms, actual_tts_voice_kind, actual_tts_voice_profile_id, "
                    "safe_error_code, created_at, updated_at, public_at) VALUES "
                    "(:id, :debate_id, :participant_id, :snapshot_id, 1, 0, 'pending', "
                    "'unpublished', 'generation', NULL, NULL, '[]', NULL, NULL, NULL, NULL, "
                    "'[]', NULL, 1, NULL, NULL, NULL, NULL, NULL, :created_at, :updated_at, "
                    "NULL)"
                ),
                {
                    "id": turn_id,
                    "debate_id": debate_id,
                    "participant_id": participant_id,
                    "snapshot_id": snapshot_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO playback_states "
                    "(id, debate_id, status, mode, current_turn_id, cursor_ms, "
                    "playback_rate, control_version, controller_epoch, "
                    "controller_owner_connection, server_started_at, replay_scope, "
                    "replay_index, created_at, updated_at) VALUES "
                    "(:id, :debate_id, 'preparing', 'live', :turn_id, 0, 1.0, 0, NULL, "
                    "NULL, NULL, NULL, NULL, :created_at, :updated_at)"
                ),
                {
                    "id": playback_id,
                    "debate_id": debate_id,
                    "turn_id": turn_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
    finally:
        database.dispose()
    return {
        "debate_id": debate_id,
        "participant_id": participant_id,
        "turn_id": turn_id,
        "playback_id": playback_id,
    }


def row_fingerprint(path: Path, table: str, row_id: str, columns: list[str]) -> str:
    """Fingerprint one row using the same canonical encoding as table checks."""

    database = Database(database_url(path))
    try:
        selected = ", ".join(columns)
        with database.engine.connect() as connection:
            row = connection.execute(
                text(f"SELECT {selected} FROM {table} WHERE id=:id"), {"id": row_id}
            ).first()
            if row is None:
                raise AssertionError(f"{table} row {row_id} disappeared")
            values = {column: canonical(value) for column, value in zip(columns, row, strict=True)}
            encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
            return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    finally:
        database.dispose()


def assert_legacy_playback_row_preserved(
    path: Path,
    fixture: dict[str, str],
    before_fingerprint: str,
) -> None:
    """Verify 0005 copied the legacy row and kept its exact relationships."""

    database = Database(database_url(path))
    try:
        columns = [item["name"] for item in inspect(database.engine).get_columns("playback_states")]
        after_fingerprint = row_fingerprint(
            path,
            "playback_states",
            fixture["playback_id"],
            columns,
        )
        if after_fingerprint != before_fingerprint:
            raise AssertionError("0005 changed an existing playback_states row")
        with database.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT debate_id, status, mode, current_turn_id, replay_scope, "
                    "replay_index FROM playback_states WHERE id=:id"
                ),
                {"id": fixture["playback_id"]},
            ).first()
            if row is None:
                raise AssertionError("legacy playback_states row disappeared after 0005")
            (
                debate_id,
                playback_status,
                mode,
                current_turn_id,
                replay_scope,
                replay_index,
            ) = (str(value) if value is not None else None for value in row)
            if (debate_id, playback_status, mode, current_turn_id) != (
                fixture["debate_id"],
                "preparing",
                "live",
                fixture["turn_id"],
            ):
                raise AssertionError("0005 changed legacy playback state or current turn")
            if replay_scope is not None or replay_index is not None:
                raise AssertionError("legacy live playback unexpectedly gained replay scope")
            related = connection.execute(
                text(
                    "SELECT d.id, dt.id, dt.participant_id, dp.id "
                    "FROM playback_states AS ps "
                    "JOIN debates AS d ON d.id=ps.debate_id "
                    "JOIN debate_turns AS dt "
                    "ON dt.id=ps.current_turn_id AND dt.debate_id=ps.debate_id "
                    "JOIN debate_participants AS dp "
                    "ON dp.id=dt.participant_id AND dp.debate_id=dt.debate_id "
                    "WHERE ps.id=:id"
                ),
                {"id": fixture["playback_id"]},
            ).first()
            if related != (
                fixture["debate_id"],
                fixture["turn_id"],
                fixture["participant_id"],
                fixture["participant_id"],
            ):
                raise AssertionError("legacy playback foreign-key relationships changed")
            if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
                raise AssertionError("foreign_key_check is not empty after preserving playback row")
    finally:
        database.dispose()


def install_voice_mutation_sentinels(path: Path) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE voice_mutation_sentinel (table_name TEXT NOT NULL)")
            )
            for table in (
                "voice_profiles",
                "voice_provider_operations",
                "voice_previews",
            ):
                connection.execute(
                    text(
                        f"CREATE TRIGGER sentinel_{table}_update AFTER UPDATE ON {table} "
                        "BEGIN INSERT INTO voice_mutation_sentinel(table_name) VALUES "
                        f"('{table}:update'); END"
                    )
                )
                connection.execute(
                    text(
                        f"CREATE TRIGGER sentinel_{table}_delete AFTER DELETE ON {table} "
                        "BEGIN INSERT INTO voice_mutation_sentinel(table_name) VALUES "
                        f"('{table}:delete'); END"
                    )
                )
    finally:
        database.dispose()


def assert_schema(path: Path, *, manual_advance: bool = False) -> None:
    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        expected_tables = {
            "debates",
            "debate_participants",
            "debate_turns",
            "turn_sources",
            "position_history",
            "playback_states",
            "debate_events",
        }
        missing = expected_tables.difference(inspector.get_table_names())
        if missing:
            raise AssertionError(f"Wave 2 tables missing: {sorted(missing)}")
        expected_indexes = {
            "debates": {"uq_debates_one_running_per_course"},
            "jobs": {
                "ix_jobs_debate",
                "ix_jobs_turn",
                "uq_jobs_operation_idempotency_key",
            },
            "playback_states": {"ix_playback_states_debate_status"},
        }
        for table, names in expected_indexes.items():
            actual = {item["name"] for item in inspector.get_indexes(table)}
            missing = names.difference(actual)
            if missing:
                raise AssertionError(f"Wave 2 indexes missing from {table}: {sorted(missing)}")
        expected_unique_constraints = {
            "playback_states": {"uq_playback_states_debate"},
        }
        for table, names in expected_unique_constraints.items():
            actual = {item["name"] for item in inspector.get_unique_constraints(table)}
            missing = names.difference(actual)
            if missing:
                raise AssertionError(
                    f"Wave 2 unique constraints missing from {table}: {sorted(missing)}"
                )
        expected_checks = {
            "debates": {"ck_debates_status", "ck_debates_revision_nonnegative"},
            "debate_participants": {
                "ck_debate_participants_slot",
                "ck_debate_participants_slot_order",
                "ck_debate_participants_stance_shape",
                "ck_debate_participants_voice_shape",
            },
            "debate_turns": {
                "ck_debate_turns_round",
                "ck_debate_turns_word_count",
                "ck_debate_turns_final_ready_shape",
                "ck_debate_turns_attempt",
            },
        }
        if manual_advance:
            expected_checks["playback_states"] = {
                "ck_playback_states_status",
                "ck_playback_states_waiting_next_live",
            }
        for table, names in expected_checks.items():
            actual = {item["name"] for item in inspector.get_check_constraints(table)}
            missing = names.difference(actual)
            if missing:
                raise AssertionError(f"Wave 2 checks missing from {table}: {sorted(missing)}")
        fks = {
            item["name"]: (
                item["constrained_columns"],
                item["referred_table"],
                item["referred_columns"],
            )
            for item in inspector.get_foreign_keys("position_history")
        }
        if fks.get("fk_position_history_turn_participant") != (
            ["turn_id", "participant_id"],
            "debate_turns",
            ["id", "participant_id"],
        ):
            raise AssertionError("position history must bind the exact participant turn")
        playback_fks = {
            item["name"]: item for item in inspector.get_foreign_keys("playback_states")
        }
        current_fk = playback_fks.get("fk_playback_states_current_turn_debate")
        if current_fk is None or current_fk["constrained_columns"] != [
            "current_turn_id",
            "debate_id",
        ]:
            raise AssertionError("Playback current turn must be scoped to its Debate")
    finally:
        database.dispose()


def _playback_row(
    row_id: str,
    *,
    debate_id: str,
    status: str,
    mode: str,
    current_turn_id: str | None,
    replay_scope: str | None = None,
    replay_index: int | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": row_id,
        "debate_id": debate_id,
        "status": status,
        "mode": mode,
        "current_turn_id": current_turn_id,
        "cursor_ms": 0,
        "playback_rate": 1.0,
        "control_version": 0,
        "controller_epoch": None,
        "controller_owner_connection": None,
        "server_started_at": None,
        "replay_scope": replay_scope,
        "replay_index": replay_index,
        "created_at": now,
        "updated_at": now,
    }


def _insert_playback_row(connection: Any, row: dict[str, Any]) -> None:
    connection.execute(
        text(
            "INSERT INTO playback_states "
            "(id, debate_id, status, mode, current_turn_id, cursor_ms, playback_rate, "
            "control_version, controller_epoch, controller_owner_connection, "
            "server_started_at, replay_scope, replay_index, created_at, updated_at) "
            "VALUES (:id, :debate_id, :status, :mode, :current_turn_id, :cursor_ms, "
            ":playback_rate, :control_version, :controller_epoch, "
            ":controller_owner_connection, :server_started_at, :replay_scope, "
            ":replay_index, :created_at, :updated_at)"
        ),
        row,
    )


def assert_manual_advance_constraints(path: Path) -> None:
    """Check the new named checks and their SQLite behaviour.

    Synthetic UUIDs are inserted with foreign-key enforcement disabled only
    for this isolated constraint probe.  The rows are deleted before the
    connection closes; the normal database connection still has foreign keys
    enabled and the final migration check proves no orphan remains.
    """

    database = Database(database_url(path))
    row_ids = [str(uuid4()) for _ in range(5)]
    debate_id = str(uuid4())
    turn_id = str(uuid4())
    try:
        inspector = inspect(database.engine)
        columns = {item["name"] for item in inspector.get_columns("playback_states")}
        if "next_turn_ready" in columns:
            raise AssertionError("next_turn_ready must remain a derived response field")
        checks = {
            item["name"]: " ".join(item["sqltext"].split())
            for item in inspector.get_check_constraints("playback_states")
        }
        if "ck_playback_states_waiting_next_live" not in checks:
            raise AssertionError("waiting_next live-only check is missing")
        expected_waiting_check = (
            "status != 'waiting_next' OR (mode = 'live' AND current_turn_id IS NOT NULL "
            "AND replay_scope IS NULL AND replay_index IS NULL)"
        )
        if checks["ck_playback_states_waiting_next_live"] != expected_waiting_check:
            raise AssertionError(
                "waiting_next check expression drifted: "
                f"{checks['ck_playback_states_waiting_next_live']}"
            )
        if "waiting_next" not in checks["ck_playback_states_status"]:
            raise AssertionError("playback status check does not include waiting_next")

        # This probe uses an autocommit connection so SQLite permits toggling
        # foreign_keys before each synthetic insert; CHECK constraints remain
        # active and are the only behaviour under test here.
        with database.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            _insert_playback_row(
                connection,
                _playback_row(
                    row_ids[0],
                    debate_id=debate_id,
                    status="waiting_next",
                    mode="live",
                    current_turn_id=turn_id,
                ),
            )
            for row in (
                _playback_row(
                    row_ids[1],
                    debate_id=debate_id,
                    status="waiting_next",
                    mode="live",
                    current_turn_id=None,
                ),
                _playback_row(
                    row_ids[2],
                    debate_id=debate_id,
                    status="waiting_next",
                    mode="replay",
                    current_turn_id=turn_id,
                ),
                _playback_row(
                    row_ids[3],
                    debate_id=debate_id,
                    status="waiting_next",
                    mode="live",
                    current_turn_id=turn_id,
                    replay_scope="all",
                ),
                _playback_row(
                    row_ids[4],
                    debate_id=debate_id,
                    status="waiting_next",
                    mode="live",
                    current_turn_id=turn_id,
                    replay_index=0,
                ),
            ):
                try:
                    _insert_playback_row(connection, row)
                except IntegrityError:
                    continue
                raise AssertionError(
                    f"invalid waiting_next playback shape was accepted: {row['id']}"
                )
            connection.execute(
                text("DELETE FROM playback_states WHERE id IN (:one, :two, :three, :four, :five)"),
                {
                    "one": row_ids[0],
                    "two": row_ids[1],
                    "three": row_ids[2],
                    "four": row_ids[3],
                    "five": row_ids[4],
                },
            )
    finally:
        database.dispose()


def assert_legacy_status_rejects_waiting_next(path: Path) -> None:
    """The downgraded 0004 status check must reject the new state."""

    database = Database(database_url(path))
    row_id = str(uuid4())
    try:
        with database.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            try:
                _insert_playback_row(
                    connection,
                    _playback_row(
                        row_id,
                        debate_id=str(uuid4()),
                        status="waiting_next",
                        mode="live",
                        current_turn_id=str(uuid4()),
                    ),
                )
            except IntegrityError:
                return
            raise AssertionError("downgraded 0004 accepted waiting_next status")
    finally:
        with database.engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.execute(text("DELETE FROM playback_states WHERE id=:id"), {"id": row_id})
        database.dispose()


def _row_values(path: Path, table: str, row_id: str) -> dict[str, Any]:
    database = Database(database_url(path))
    try:
        columns = [item["name"] for item in inspect(database.engine).get_columns(table)]
        selected = ", ".join(columns)
        with database.engine.connect() as connection:
            row = (
                connection.execute(
                    text(f"SELECT {selected} FROM {table} WHERE id=:id"), {"id": row_id}
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AssertionError(f"{table} row {row_id} disappeared")
            return dict(row)
    finally:
        database.dispose()


def assert_waiting_next_downgrade_preserves_row(path: Path, fixture: dict[str, str]) -> None:
    """Map a real 0005 waiting row to conservative 0004 ``paused``.

    The row remains attached to its Debate/Turn and all durable identity,
    cursor, controller, replay and timestamp fields survive both the downgrade
    and the subsequent upgrade.  Only the 0005-only status is intentionally
    irreversible; no row is deleted and no turn is published.
    """

    database = Database(database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE playback_states SET status='waiting_next', cursor_ms=321, "
                    "control_version=7, controller_epoch='epoch-downgrade', "
                    "controller_owner_connection='owner-downgrade', "
                    "replay_scope=NULL, replay_index=NULL WHERE id=:id"
                ),
                {"id": fixture["playback_id"]},
            )
    finally:
        database.dispose()

    before = _row_values(path, "playback_states", fixture["playback_id"])
    if before.get("status") != "waiting_next":
        raise AssertionError("test fixture did not enter waiting_next before downgrade")
    if before.get("current_turn_id") != fixture["turn_id"]:
        raise AssertionError("waiting fixture lost its current turn before downgrade")
    if before.get("replay_scope") is not None or before.get("replay_index") is not None:
        raise AssertionError("waiting fixture has a replay field despite the 0005 gate")

    downgrade_alembic(path, WAVE_2_REVISION)
    if revision(path) != WAVE_2_REVISION:
        raise AssertionError("waiting-row downgrade did not return to 0004")
    assert_schema(path)
    after_downgrade = _row_values(path, "playback_states", fixture["playback_id"])
    if after_downgrade.get("status") != "paused":
        raise AssertionError("0005 waiting_next row was not conservatively mapped to paused")
    for column, value in before.items():
        if column != "status" and after_downgrade.get(column) != value:
            raise AssertionError(f"downgrade changed playback_states.{column}")
    if after_downgrade.get("current_turn_id") != fixture["turn_id"]:
        raise AssertionError("downgrade changed the waiting row current turn")
    if (
        after_downgrade.get("replay_scope") is not None
        or after_downgrade.get("replay_index") is not None
    ):
        raise AssertionError("downgrade introduced replay authority")
    with database.engine.connect() as connection:
        if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
            raise AssertionError("foreign_key_check failed after waiting-row downgrade")

    run_alembic(path, WAVE_2_MANUAL_ADVANCE_REVISION)
    if revision(path) != WAVE_2_MANUAL_ADVANCE_REVISION:
        raise AssertionError("waiting-row re-upgrade did not return to 0005")
    assert_schema(path, manual_advance=True)
    after_upgrade = _row_values(path, "playback_states", fixture["playback_id"])
    if after_upgrade.get("status") != "paused":
        raise AssertionError("0005 re-upgrade unexpectedly restored waiting_next semantics")
    for column, value in before.items():
        if column != "status" and after_upgrade.get(column) != value:
            raise AssertionError(f"re-upgrade changed playback_states.{column}")
    with database.engine.connect() as connection:
        if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
            raise AssertionError("foreign_key_check failed after waiting-row re-upgrade")


def assert_voice_untouched(path: Path) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            touched = connection.execute(
                text("SELECT table_name FROM voice_mutation_sentinel")
            ).fetchall()
            if touched:
                raise AssertionError(f"0005 touched immutable voice ledger rows: {touched}")
            if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
                raise AssertionError("foreign_key_check is not empty after 0005")
    finally:
        database.dispose()


def assert_final_ready_shape_rejects(path: Path) -> None:
    """Prove the final-ready invariant rejects a missing word count.

    Reflection confirms the named check exists, but a direct insert protects
    against a check that is accidentally present in metadata yet ineffective
    on SQLite.  The fixture rows are removed after the negative insert.
    """

    database = Database(database_url(path))
    debate_id, participant_id, turn_id = (str(uuid4()) for _ in range(3))
    try:
        with database.engine.connect() as connection:
            parent = connection.execute(
                text(
                    "SELECT a.id, a.group_id, av.id, av.knowledge_snapshot_id "
                    "FROM agents AS a JOIN agent_versions AS av "
                    "ON av.id=a.current_published_version_id "
                    "WHERE a.name='Migration Agent' LIMIT 1"
                )
            ).first()
            if parent is None:
                raise AssertionError("populated migration fixture Agent is missing")
            agent_id, group_id, version_id, snapshot_id = (str(value) for value in parent)
        now = datetime.now(UTC)
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO debates "
                    "(id, course_id, topic, rule_set_id, rule_snapshot_json, status, revision, "
                    "last_sequence, cancellation_generation, created_by, created_at, updated_at, "
                    "total_duration_seconds, turn_duration_seconds) VALUES "
                    "(:id, :course_id, :topic, :rule_set_id, :rule_snapshot_json, :status, "
                    ":revision, :last_sequence, :cancellation_generation, :created_by, "
                    ":created_at, :updated_at, NULL, NULL)"
                ),
                {
                    "id": debate_id,
                    "course_id": COURSE_ID,
                    "topic": "schema counterexample",
                    "rule_set_id": "ordered_multi_agent_rounds_demo_v1",
                    "rule_snapshot_json": "{}",
                    "status": "draft",
                    "revision": 0,
                    "last_sequence": 0,
                    "cancellation_generation": 0,
                    "created_by": TEACHER_ID,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO debate_participants "
                    "(id, debate_id, course_id, group_id, agent_id, agent_version_id, "
                    "knowledge_snapshot_id, slot, order_index, agent_name, version_label, "
                    "avatar_config_json, requested_voice_profile_id, effective_voice_kind, "
                    "effective_voice_profile_id, voice_fallback_active, stance_mode, "
                    "initial_stance, current_stance, teacher_note, initial_position_summary, "
                    "current_position_summary, created_at, updated_at) VALUES "
                    "(:id, :debate_id, :course_id, :group_id, :agent_id, :version_id, "
                    ":snapshot_id, 'A', 0, 'Migration Agent', 'V1.0', '{}', NULL, "
                    "'mock_sentinel', NULL, 1, 'open', NULL, NULL, '', '', '', :created_at, "
                    ":updated_at)"
                ),
                {
                    "id": participant_id,
                    "debate_id": debate_id,
                    "course_id": COURSE_ID,
                    "group_id": group_id,
                    "agent_id": agent_id,
                    "version_id": version_id,
                    "snapshot_id": snapshot_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        rejected = False
        try:
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO debate_turns "
                        "(id, debate_id, participant_id, knowledge_snapshot_id, round_no, "
                        "turn_index, generation_status, publication_status, preparation_stage, "
                        "speech, structured_json, predecessor_turn_ids_json, transcript_hash, "
                        "cutoff_turn_index, retrieval_status, grounding_mode, "
                        "retrieval_receipts_json, word_count, attempt, audio_file_id, "
                        "audio_duration_ms, actual_tts_voice_kind, actual_tts_voice_profile_id, "
                        "safe_error_code, created_at, updated_at, public_at) VALUES "
                        "(:id, :debate_id, :participant_id, :snapshot_id, 1, 0, "
                        "'final_ready', 'unpublished', 'ready', 'short', '{}', '[]', :hash, "
                        "-1, 'no_match', 'general_reasoning', '[]', NULL, 1, NULL, NULL, "
                        "'mock_sentinel', NULL, NULL, :created_at, :updated_at, NULL)"
                    ),
                    {
                        "id": turn_id,
                        "debate_id": debate_id,
                        "participant_id": participant_id,
                        "snapshot_id": snapshot_id,
                        "hash": "7" * 64,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        except IntegrityError:
            rejected = True
        if not rejected:
            raise AssertionError(
                "final_ready turn with NULL word_count bypassed the named shape check"
            )
    finally:
        with database.engine.begin() as connection:
            connection.execute(text("DELETE FROM debate_turns WHERE id=:id"), {"id": turn_id})
            connection.execute(
                text("DELETE FROM debate_participants WHERE id=:id"),
                {"id": participant_id},
            )
            connection.execute(text("DELETE FROM debates WHERE id=:id"), {"id": debate_id})
        database.dispose()


def assert_pre_wave3_polish_migration(
    path: Path,
    fixture: dict[str, str],
) -> None:
    """Prove 0006 is reversible without deleting frozen Agent history."""

    historical_tables = (
        "agent_versions",
        "knowledge_snapshots",
        "snapshot_documents",
        "knowledge_chunks",
        "debates",
        "debate_participants",
        "debate_turns",
    )
    columns_0005 = table_columns(path)
    before = table_fingerprints(path, columns_by_table=columns_0005)

    run_alembic(path, PRE_WAVE_3_POLISH_REVISION)
    run_alembic(path, PRE_WAVE_3_POLISH_REVISION)
    if revision(path) != PRE_WAVE_3_POLISH_REVISION:
        raise AssertionError("populated database did not reach 0006")

    after_upgrade = table_fingerprints(path, columns_by_table=columns_0005)
    for table, fingerprint in before.items():
        if table in {"alembic_version", "voice_mutation_sentinel"}:
            continue
        if after_upgrade.get(table) != fingerprint:
            raise AssertionError(f"pre-existing table changed during 0006: {table}")

    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        agent_columns = {item["name"] for item in inspector.get_columns("agents")}
        playback_columns = {item["name"] for item in inspector.get_columns("playback_states")}
        if "metadata_revision" not in agent_columns:
            raise AssertionError("0006 metadata_revision column is missing")
        expected_playback_columns = {
            "replay_turn_ids_json",
            "pending_action",
            "pending_ticket_hash",
            "pending_media_command_id",
            "audio_duration_ms",
        }
        if not expected_playback_columns.issubset(playback_columns):
            raise AssertionError(
                "0006 playback columns are missing: "
                f"{sorted(expected_playback_columns - playback_columns)}"
            )
        playback_checks = {
            item["name"] for item in inspector.get_check_constraints("playback_states")
        }
        if not {
            "ck_playback_states_waiting_next_mode",
            "ck_playback_states_pending_action",
            "ck_playback_states_audio_duration",
        }.issubset(playback_checks):
            raise AssertionError("0006 playback safety checks are missing")
        if not {"demo_account_bindings", "audit_logs"}.issubset(set(inspector.get_table_names())):
            raise AssertionError("0006 server-only auth/audit tables are missing")
        with database.engine.connect() as connection:
            trigger_count = connection.execute(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'ck_agents_metadata_revision_nonnegative_%'"
                )
            ).scalar_one()
        if trigger_count != 2:
            raise AssertionError("0006 metadata revision guards are missing")

        with database.engine.begin() as connection:
            agent_id = connection.execute(
                text("SELECT id FROM agents WHERE name='Migration Agent'")
            ).scalar_one()
            rejected = False
            try:
                connection.execute(
                    text("UPDATE agents SET metadata_revision=-1 WHERE id=:id"),
                    {"id": agent_id},
                )
            except IntegrityError:
                rejected = True
            if not rejected:
                raise AssertionError("0006 accepted a negative metadata revision")
        for statement, message in (
            (
                "UPDATE playback_states SET audio_duration_ms=-1 WHERE id=:id",
                "0006 accepted a negative audio duration",
            ),
            (
                "UPDATE playback_states SET pending_action='invalid' WHERE id=:id",
                "0006 accepted an invalid pending action",
            ),
        ):
            with database.engine.begin() as connection:
                rejected = False
                try:
                    connection.execute(text(statement), {"id": fixture["playback_id"]})
                except IntegrityError:
                    rejected = True
                if not rejected:
                    raise AssertionError(message)
    finally:
        database.dispose()

    database = Database(database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE playback_states SET status='waiting_next', "
                    "mode='replay', current_turn_id=:turn_id, replay_scope='all', "
                    "replay_index=0, replay_turn_ids_json=:queue, "
                    "controller_epoch='migration-epoch', "
                    "controller_owner_connection='migration-owner', cursor_ms=123 "
                    "WHERE id=:playback_id"
                ),
                {
                    "turn_id": fixture["turn_id"],
                    "queue": json.dumps([fixture["turn_id"]]),
                    "playback_id": fixture["playback_id"],
                },
            )
    finally:
        database.dispose()

    pre_downgrade = table_fingerprints(path)
    downgrade_alembic(path, WAVE_2_MANUAL_ADVANCE_REVISION)
    if revision(path) != WAVE_2_MANUAL_ADVANCE_REVISION:
        raise AssertionError("0006 downgrade did not return to 0005")

    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        if "metadata_revision" in {item["name"] for item in inspector.get_columns("agents")}:
            raise AssertionError("0006 downgrade retained metadata_revision")
        downgraded_playback_columns = {
            item["name"] for item in inspector.get_columns("playback_states")
        }
        if expected_playback_columns & downgraded_playback_columns:
            raise AssertionError("0006 downgrade retained new playback columns")
        if {"demo_account_bindings", "audit_logs"} & set(inspector.get_table_names()):
            raise AssertionError("0006 downgrade retained server-only tables")
        with database.engine.connect() as connection:
            trigger_count = connection.execute(
                text(
                    "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'ck_agents_metadata_revision_nonnegative_%'"
                )
            ).scalar_one()
            if trigger_count:
                raise AssertionError("0006 downgrade retained metadata guards")
            playback = (
                connection.execute(
                    text(
                        "SELECT status, mode, current_turn_id, cursor_ms, "
                        "controller_epoch, controller_owner_connection, replay_scope, "
                        "replay_index FROM playback_states WHERE id=:id"
                    ),
                    {"id": fixture["playback_id"]},
                )
                .mappings()
                .one()
            )
            expected = {
                "status": "completed",
                "mode": "live",
                "current_turn_id": None,
                "cursor_ms": 0,
                "controller_epoch": None,
                "controller_owner_connection": None,
                "replay_scope": None,
                "replay_index": None,
            }
            if dict(playback) != expected:
                raise AssertionError(f"0006 downgrade replay mapping drifted: {playback}")
            if connection.execute(text("PRAGMA foreign_key_check")).all():
                raise AssertionError("0006 downgrade left foreign-key violations")
    finally:
        database.dispose()

    after_downgrade = table_fingerprints(path)
    for table in historical_tables:
        if after_downgrade.get(table) != pre_downgrade.get(table):
            raise AssertionError(f"0006 downgrade changed or deleted frozen history: {table}")

    run_alembic(path, PRE_WAVE_3_POLISH_REVISION)
    if revision(path) != PRE_WAVE_3_POLISH_REVISION:
        raise AssertionError("0006 re-upgrade did not restore head")
    after_reupgrade = table_fingerprints(path)
    for table in historical_tables:
        if after_reupgrade.get(table) != pre_downgrade.get(table):
            raise AssertionError(f"0006 re-upgrade changed or deleted frozen history: {table}")
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            if connection.execute(text("PRAGMA foreign_key_check")).all():
                raise AssertionError("0006 re-upgrade left foreign-key violations")
    finally:
        database.dispose()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave2-migration-") as directory:
        root = Path(directory)
        fresh = root / "fresh.sqlite3"
        run_alembic(fresh, WAVE_2_REVISION)
        if revision(fresh) != WAVE_2_REVISION:
            raise AssertionError("fresh database did not reach 0004 before manual-advance delta")
        run_alembic(fresh, WAVE_2_REVISION)
        assert_schema(fresh)
        run_alembic(fresh, WAVE_2_MANUAL_ADVANCE_REVISION)
        if revision(fresh) != WAVE_2_MANUAL_ADVANCE_REVISION:
            raise AssertionError("fresh database did not reach 0005")
        run_alembic(fresh, WAVE_2_MANUAL_ADVANCE_REVISION)
        assert_schema(fresh, manual_advance=True)
        assert_manual_advance_constraints(fresh)
        downgrade_alembic(fresh, WAVE_2_REVISION)
        if revision(fresh) != WAVE_2_REVISION:
            raise AssertionError("0005 downgrade did not return to 0004")
        assert_legacy_status_rejects_waiting_next(fresh)
        run_alembic(fresh, WAVE_2_MANUAL_ADVANCE_REVISION)
        assert_manual_advance_constraints(fresh)

        populated = root / "populated.sqlite3"
        run_alembic(populated, WAVE_0_REVISION)
        wave0 = Database(database_url(populated), root)
        with wave0.session() as session:
            seed_legacy_organization(session)
        wave0.dispose()
        run_alembic(populated, WAVE_1B_REVISION)
        database = Database(database_url(populated), root)
        insert_wave1_rows_and_voice_ledger(database)
        database.dispose()
        pre_migration_columns = table_columns(populated)
        before = table_fingerprints(
            populated,
            columns_by_table=pre_migration_columns,
        )
        for table in ("jobs", "file_operations"):
            if not pre_migration_columns.get(table):
                raise AssertionError(f"Populated fixture is missing {table} before 0004")
            if before.get(table) is None:
                raise AssertionError(f"Populated fixture did not fingerprint {table}")
        install_voice_mutation_sentinels(populated)
        run_alembic(populated, WAVE_2_REVISION)
        if revision(populated) != WAVE_2_REVISION:
            raise AssertionError("populated database did not reach 0004")
        after_wave2 = table_fingerprints(
            populated,
            columns_by_table=pre_migration_columns,
        )
        for table, fingerprint in before.items():
            if table in {"alembic_version", "voice_mutation_sentinel"}:
                continue
            if after_wave2.get(table) != fingerprint:
                raise AssertionError(f"pre-existing table changed during 0004: {table}")
        legacy_fixture = insert_legacy_playback_fixture(populated)
        pre_manual_columns = table_columns(populated)
        legacy_playback_before = row_fingerprint(
            populated,
            "playback_states",
            legacy_fixture["playback_id"],
            pre_manual_columns["playback_states"],
        )
        before_manual = table_fingerprints(
            populated,
            columns_by_table=pre_manual_columns,
        )
        run_alembic(populated, WAVE_2_MANUAL_ADVANCE_REVISION)
        run_alembic(populated, WAVE_2_MANUAL_ADVANCE_REVISION)
        after = table_fingerprints(
            populated,
            columns_by_table=pre_manual_columns,
        )
        for table, fingerprint in before_manual.items():
            if table in {"alembic_version", "voice_mutation_sentinel"}:
                continue
            if after.get(table) != fingerprint:
                raise AssertionError(f"pre-existing table changed during 0005: {table}")
        if revision(populated) != WAVE_2_MANUAL_ADVANCE_REVISION:
            raise AssertionError("populated database did not reach 0005")
        assert_schema(populated, manual_advance=True)
        assert_legacy_playback_row_preserved(
            populated,
            legacy_fixture,
            legacy_playback_before,
        )
        assert_manual_advance_constraints(populated)
        assert_waiting_next_downgrade_preserves_row(populated, legacy_fixture)
        assert_final_ready_shape_rejects(populated)
        assert_voice_untouched(populated)
        assert_pre_wave3_polish_migration(populated, legacy_fixture)
    print(
        "Wave 2/pre-Wave3 migration passed: fresh/repeat/populated "
        "0001→0004→0005→0006, 0005/0006 downgrade/re-upgrade, "
        "Wave 0/1/voice/frozen-debate fingerprints preserved, "
        "named schema/check constraints passed, derived next_turn_ready stayed "
        "out of SQLite, voice ledger untouched, and foreign_key_check empty."
    )


if __name__ == "__main__":
    main()
