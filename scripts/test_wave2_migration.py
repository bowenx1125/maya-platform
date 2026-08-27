"""Deterministic fresh/repeat/populated checks for Wave 2 migration 0004.

The probe creates all SQLite databases below a temporary directory.  The
populated case stops at each prior revision, fingerprints every pre-existing
row (including the voice operation ledger), installs update/delete sentinels
on the three voice tables, then upgrades to 0004 and checks exact composite
foreign-key behaviour plus an empty ``foreign_key_check``.
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

from app.core.db import Database  # noqa: E402
from app.core.models import (  # noqa: E402
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    VoicePreview,
    VoiceProfile,
    VoiceProviderOperation,
)
from app.seed import seed_demo_data  # noqa: E402

WAVE_0_REVISION = "0001_wave0_baseline"
WAVE_1_REVISION = "0002_wave1_agents_rag"
WAVE_1B_REVISION = "0003_wave1b_avatar_voice"
WAVE_2_REVISION = "0004_wave2_debate_playback"
TEACHER_ID = "98644172-6bbb-5383-8198-3b78dcd5b9ab"
COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"


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
        session.add(
            Agent(
                id=agent_id,
                group_id=GROUP_ID,
                name="Migration Agent",
                description="Wave 1 preservation row",
                status="active",
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
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
        session.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="published",
                revision=1,
                agent_md="# Migration Agent",
                avatar_config_json=(
                    '{"template_id":"wave1-default-head","material_theme":"demo",'
                    '"default_expression":"neutral","expression_strength":"medium",'
                    '"motion_style":"calm"}'
                ),
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=source_file_id,
                content_hash="3" * 64,
                total_char_count=9,
                embedding_key="mock",
                chunking_json="{}",
                created_at=now,
            )
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


def install_voice_mutation_sentinels(path: Path) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE voice_mutation_sentinel (table_name TEXT NOT NULL)")
            )
            for table in ("voice_profiles", "voice_provider_operations", "voice_previews"):
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


def assert_schema(path: Path) -> None:
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
            "jobs": {"ix_jobs_debate", "ix_jobs_turn", "uq_jobs_operation_idempotency_key"},
        }
        for table, names in expected_indexes.items():
            actual = {item["name"] for item in inspector.get_indexes(table)}
            missing = names.difference(actual)
            if missing:
                raise AssertionError(f"Wave 2 indexes missing from {table}: {sorted(missing)}")
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


def assert_voice_untouched(path: Path) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            touched = connection.execute(
                text("SELECT table_name FROM voice_mutation_sentinel")
            ).fetchall()
            if touched:
                raise AssertionError(f"0004 touched immutable voice ledger rows: {touched}")
            if connection.execute(text("PRAGMA foreign_key_check")).fetchall():
                raise AssertionError("foreign_key_check is not empty after 0004")
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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave2-migration-") as directory:
        root = Path(directory)
        fresh = root / "fresh.sqlite3"
        run_alembic(fresh, "head")
        if revision(fresh) != WAVE_2_REVISION:
            raise AssertionError("fresh database did not reach 0004")
        run_alembic(fresh, "head")
        assert_schema(fresh)

        populated = root / "populated.sqlite3"
        run_alembic(populated, WAVE_0_REVISION)
        wave0 = Database(database_url(populated), root)
        with wave0.session() as session:
            seed_demo_data(session)
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
        run_alembic(populated, "head")
        run_alembic(populated, "head")
        after = table_fingerprints(
            populated,
            columns_by_table=pre_migration_columns,
        )
        for table, fingerprint in before.items():
            if table in {"alembic_version", "voice_mutation_sentinel"}:
                continue
            if after.get(table) != fingerprint:
                raise AssertionError(f"pre-existing table changed during 0004: {table}")
        if revision(populated) != WAVE_2_REVISION:
            raise AssertionError("populated database did not reach 0004")
        assert_schema(populated)
        assert_final_ready_shape_rejects(populated)
        assert_voice_untouched(populated)
    print(
        "Wave 2 migration passed: fresh/repeat/populated 0001→0004, "
        "Wave 0/1/voice fingerprints preserved, named schema checks passed, "
        "voice ledger untouched, and foreign_key_check empty."
    )


if __name__ == "__main__":
    main()
