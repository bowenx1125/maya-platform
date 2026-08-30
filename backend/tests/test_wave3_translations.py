"""Focused M15 manifest, Mock provider and read-model boundary checks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.core.db import Database
from app.core.models import Base
from app.modules.debates import models as debate_models  # noqa: F401
from app.modules.reports import models as report_models  # noqa: F401
from app.modules.translations.manifest import (
    ManifestTurn,
    TranslationInputManifestV1,
    canonical_json_bytes,
    manifest_hash,
    source_text_hash,
)
from app.modules.translations.models import TranslationBatch, TranslationEntry
from app.modules.translations.policy import (
    MOCK_PREFIX,
    MOCK_TRANSLATION_POLICY,
    MOCK_TRANSLATION_QUALITY,
    MockTranslationProvider,
    TranslationInput,
)
from app.modules.translations.service import (
    OPERATION_INTERRUPTED,
    TranslationService,
    attach_translated_report,
    attach_translated_text,
)
from sqlalchemy import Table, create_engine, text
from sqlalchemy.exc import IntegrityError

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
TEACHER_ID = "98644172-6bbb-5383-8198-3b78dcd5b9ab"


def test_manifest_is_utf8_canonical_and_source_hash_is_exact() -> None:
    turn_id = uuid4()
    source = "Café\r\nA choice — 保留 exact bytes"
    manifest = TranslationInputManifestV1(
        debate_id=uuid4(),
        turns=[
            ManifestTurn(
                turn_id=turn_id,
                turn_index=2,
                source_text_hash=source_text_hash(source),
            )
        ],
        report=None,
        target_language="zh-Hans",
        policy_key=MOCK_TRANSLATION_POLICY,
        quality_key=MOCK_TRANSLATION_QUALITY,
    )
    encoded = manifest.canonical_bytes()
    assert encoded.decode("utf-8") == json.dumps(
        manifest.canonical_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert encoded == canonical_json_bytes(manifest.canonical_dict())
    assert b"\\u4fdd" not in encoded
    assert source_text_hash(source) == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert manifest_hash(manifest) == hashlib.sha256(encoded).hexdigest()


def test_mock_translation_is_fixed_visible_test_representation() -> None:
    provider = MockTranslationProvider()
    source = "  Do not trim this source.\n"
    output = provider.translate_batch(
        [
            TranslationInput(
                content_type="turn",
                content_id=str(uuid4()),
                source_text=source,
                source_text_hash=source_text_hash(source),
            )
        ]
    )[0]
    assert output.translated_text == MOCK_PREFIX + source
    assert output.safe_error_code is None
    assert provider.call_count == 1


def test_mock_translation_failure_is_per_item_and_safe() -> None:
    provider = MockTranslationProvider(failures=["provider timeout", None])
    inputs = [
        TranslationInput("turn", str(uuid4()), "one", source_text_hash("one")),
        TranslationInput("turn", str(uuid4()), "two", source_text_hash("two")),
    ]
    outputs = provider.translate_batch(inputs)
    assert outputs[0].translated_text is None
    assert outputs[0].safe_error_code == "provider_timeout"
    assert outputs[1].translated_text == MOCK_PREFIX + "two"


def test_models_are_not_allowed_to_normalize_or_feed_translations_back() -> None:
    # This is a source-level contract test for the read projection: callers
    # receive detached copies and the authoritative speech remains unchanged.
    original = {"id": str(uuid4()), "speech": "Exact source", "sources": []}
    db = Database("sqlite:///:memory:")
    projected = attach_translated_text(
        db.session_factory(),
        debate_id=str(uuid4()),
        turns=[original],
    )
    assert projected[0]["speech"] == original["speech"]
    assert projected[0]["translated_text"] is None
    assert "translated_text" not in original


def _make_baseline(db: Database) -> str:
    now = datetime.now(UTC)
    debate_id = str(uuid4())
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE debates (id VARCHAR(36) PRIMARY KEY, course_id VARCHAR(36), "
            "status VARCHAR(24))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE course_members (course_id VARCHAR(36), user_id VARCHAR(36), "
            "role VARCHAR(16))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE debate_turns (id VARCHAR(36) PRIMARY KEY, debate_id VARCHAR(36), "
            "participant_id VARCHAR(36), knowledge_snapshot_id VARCHAR(36), round_no INTEGER, "
            "turn_index INTEGER, generation_status VARCHAR(32), publication_status VARCHAR(16), "
            "preparation_stage VARCHAR(16), speech TEXT, predecessor_turn_ids_json TEXT, "
            "retrieval_receipts_json TEXT, attempt INTEGER, created_at DATETIME, "
            "updated_at DATETIME)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE jobs (id VARCHAR(36) PRIMARY KEY, debate_id VARCHAR(36), "
            "turn_id VARCHAR(36), "
            "operation VARCHAR(40), state VARCHAR(16), safe_error_code VARCHAR(64), "
            "attempt INTEGER, created_at DATETIME, updated_at DATETIME)"
        )
        connection.exec_driver_sql(
            "INSERT INTO debates VALUES (?,?,?)", (debate_id, COURSE_ID, "debate_finished")
        )
        connection.exec_driver_sql(
            "INSERT INTO course_members VALUES (?,?,?)", (COURSE_ID, TEACHER_ID, "teacher")
        )
    del now
    return debate_id


def _install_wave3_tables(db: Database) -> None:
    """Install only the focused-test tables without changing product migrations."""

    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE translation_batches (
                id VARCHAR(36) PRIMARY KEY,
                debate_id VARCHAR(36) NOT NULL,
                course_id VARCHAR(36) NOT NULL,
                requested_by VARCHAR(36) NOT NULL,
                target_language VARCHAR(16) NOT NULL,
                policy_key VARCHAR(80) NOT NULL,
                quality_key VARCHAR(80) NOT NULL,
                status VARCHAR(16) NOT NULL,
                manifest_json TEXT NOT NULL,
                input_hash VARCHAR(64) NOT NULL,
                total_items INTEGER NOT NULL,
                succeeded_items INTEGER NOT NULL,
                failed_items INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE translation_entries (
                id VARCHAR(36) PRIMARY KEY,
                debate_id VARCHAR(36) NOT NULL,
                content_type VARCHAR(24) NOT NULL,
                turn_id VARCHAR(36),
                report_revision_id VARCHAR(36),
                source_text_hash VARCHAR(64) NOT NULL,
                target_language VARCHAR(16) NOT NULL,
                policy_key VARCHAR(80) NOT NULL,
                quality_key VARCHAR(80) NOT NULL,
                status VARCHAR(16) NOT NULL,
                translated_text TEXT,
                safe_error_code VARCHAR(64),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE translation_batch_items (
                batch_id VARCHAR(36) NOT NULL,
                entry_id VARCHAR(36) NOT NULL,
                debate_id VARCHAR(36) NOT NULL,
                order_index INTEGER NOT NULL,
                reused BOOLEAN NOT NULL,
                status VARCHAR(16) NOT NULL,
                safe_error_code VARCHAR(64),
                PRIMARY KEY (batch_id, order_index)
            )
            """
        )
        connection.exec_driver_sql(
            """
            ALTER TABLE jobs ADD COLUMN translation_batch_id VARCHAR(36)
            """
        )


def test_translation_service_all_cache_hit_has_no_job_and_attaches_exact_entry(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'translation.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    now = datetime.now(UTC)
    turn_id = str(uuid4())
    source = "Exact cached English text"
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO debate_turns "
            "(id, debate_id, participant_id, knowledge_snapshot_id, round_no, turn_index, "
            "generation_status, publication_status, preparation_stage, speech, "
            "predecessor_turn_ids_json, retrieval_receipts_json, attempt, created_at, updated_at) "
            "VALUES (?,?,?, ?,1,0,'final_ready','public','ready',?,'[]','[]',1,?,?)",
            (turn_id, debate_id, str(uuid4()), str(uuid4()), source, now, now),
        )
    _install_wave3_tables(db)
    # Populate a ready entry and its batch to exercise exact cache lookup/read.
    service = TranslationService(db.session_factory)
    digest = source_text_hash(source)
    manifest = TranslationInputManifestV1(
        debate_id=UUID(debate_id),
        turns=[ManifestTurn(turn_id=UUID(turn_id), turn_index=0, source_text_hash=digest)],
    )
    batch_id = str(uuid4())
    entry_id = str(uuid4())
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                debate_id,
                COURSE_ID,
                TEACHER_ID,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "completed",
                manifest.canonical_bytes().decode(),
                manifest.input_hash,
                1,
                1,
                0,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                debate_id,
                "turn",
                turn_id,
                None,
                digest,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "ready",
                MOCK_PREFIX + source,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (batch_id, entry_id, debate_id, 0, 0, "ready", None),
        )
    with db.session() as session:
        result = service.get_batch(session, batch_id=batch_id)
        assert result.status == "completed"
        assert result.items[0].reused is False
        projected = attach_translated_text(
            session,
            debate_id=debate_id,
            turns=[{"id": turn_id, "speech": source}],
        )
    assert projected[0]["translated_text"] == MOCK_PREFIX + source
    with db.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one() == 0


def test_restart_recovery_marks_running_items_interrupted_and_preserves_ready(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'recovery.sqlite3'}", tmp_path)
    _make_baseline(db)
    _install_wave3_tables(db)
    batch_id = str(uuid4())
    entry_id = str(uuid4())
    now = datetime.now(UTC)
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                str(uuid4()),
                COURSE_ID,
                TEACHER_ID,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "running",
                "{}",
                "a" * 64,
                2,
                1,
                0,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                str(uuid4()),
                "turn",
                str(uuid4()),
                None,
                "b" * 64,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "ready",
                MOCK_PREFIX + "ready",
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (batch_id, entry_id, str(uuid4()), 0, 1, "ready", None),
        )
        pending_entry = str(uuid4())
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pending_entry,
                str(uuid4()),
                "turn",
                str(uuid4()),
                None,
                "c" * 64,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "running",
                None,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (batch_id, pending_entry, str(uuid4()), 1, 0, "running", None),
        )
        connection.exec_driver_sql(
            "INSERT INTO jobs (id,debate_id,turn_id,operation,state,safe_error_code,attempt,"
            "created_at,updated_at,translation_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                str(uuid4()),
                None,
                "translation.generate",
                "running",
                None,
                1,
                now,
                now,
                batch_id,
            ),
        )
    service = TranslationService(db.session_factory)
    with db.session() as session:
        pending = service.recover_startup(session)
        assert pending == ()
    with db.engine.connect() as connection:
        item_state = connection.execute(
            text(
                "SELECT status,safe_error_code FROM translation_batch_items "
                "WHERE batch_id=:id ORDER BY order_index"
            ),
            {"id": batch_id},
        ).all()
        assert item_state[0][0] == "ready"
        assert item_state[1][0] == "failed"
        assert item_state[1][1] == OPERATION_INTERRUPTED


def test_restart_recovery_does_not_fail_entry_reused_by_another_running_batch(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'shared-entry-recovery.sqlite3'}", tmp_path)
    _make_baseline(db)
    _install_wave3_tables(db)
    owner_batch = str(uuid4())
    recovering_batch = str(uuid4())
    shared_entry = str(uuid4())
    now = datetime.now(UTC)
    with db.engine.begin() as connection:
        for batch_id in (owner_batch, recovering_batch):
            connection.exec_driver_sql(
                "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    str(uuid4()),
                    COURSE_ID,
                    TEACHER_ID,
                    "zh-Hans",
                    MOCK_TRANSLATION_POLICY,
                    MOCK_TRANSLATION_QUALITY,
                    "running",
                    "{}",
                    "a" * 64,
                    1,
                    0,
                    0,
                    now,
                    now,
                ),
            )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                shared_entry,
                str(uuid4()),
                "turn",
                str(uuid4()),
                None,
                "b" * 64,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "running",
                None,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (owner_batch, shared_entry, str(uuid4()), 0, 0, "running", None),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (recovering_batch, shared_entry, str(uuid4()), 0, 1, "running", None),
        )
        connection.exec_driver_sql(
            "INSERT INTO jobs (id,debate_id,turn_id,operation,state,safe_error_code,attempt,"
            "created_at,updated_at,translation_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                str(uuid4()),
                None,
                "translation.generate",
                "running",
                None,
                1,
                now,
                now,
                recovering_batch,
            ),
        )

    service = TranslationService(db.session_factory)
    with db.session() as session:
        assert service.recover_startup(session) == ()
    with db.engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT status FROM translation_entries WHERE id=:id"),
                {"id": shared_entry},
            ).scalar_one()
            == "running"
        )
        assert connection.execute(
            text("SELECT status,safe_error_code FROM translation_batch_items WHERE batch_id=:id"),
            {"id": recovering_batch},
        ).one() == ("failed", OPERATION_INTERRUPTED)


def test_real_orm_create_all_enforces_split_identity_indexes_and_terminal_shape() -> None:
    engine = create_engine("sqlite:///:memory:")
    entry_table = cast(Table, TranslationEntry.__table__)
    batch_table = cast(Table, TranslationBatch.__table__)
    Base.metadata.create_all(engine, tables=[batch_table, entry_table])
    now = datetime.now(UTC)
    common = {
        "debate_id": str(uuid4()),
        "content_type": "turn",
        "turn_id": str(uuid4()),
        "report_revision_id": None,
        "source_text_hash": "a" * 64,
        "target_language": "zh-Hans",
        "policy_key": MOCK_TRANSLATION_POLICY,
        "quality_key": MOCK_TRANSLATION_QUALITY,
        "status": "ready",
        "translated_text": "ready",
        "safe_error_code": None,
        "created_at": now,
        "updated_at": now,
    }
    with engine.begin() as connection:
        connection.execute(entry_table.insert(), {"id": str(uuid4()), **common})
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(entry_table.insert(), {"id": str(uuid4()), **common})
    poisoned = {**common, "turn_id": str(uuid4()), "status": "failed", "translated_text": None}
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(entry_table.insert(), {"id": str(uuid4()), **poisoned})
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                batch_table.insert(),
                {
                    "id": str(uuid4()),
                    "debate_id": str(uuid4()),
                    "course_id": COURSE_ID,
                    "requested_by": TEACHER_ID,
                    "target_language": "zh-Hans",
                    "policy_key": MOCK_TRANSLATION_POLICY,
                    "quality_key": MOCK_TRANSLATION_QUALITY,
                    "status": "failed",
                    "manifest_json": "{}",
                    "input_hash": "a" * 64,
                    "total_items": 1,
                    "succeeded_items": 1,
                    "failed_items": 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )


def _insert_pending_contract(
    db: Database,
    *,
    debate_id: str,
    turn_id: str,
    source: str,
    manifest_json: str | None = None,
    add_job: bool = True,
) -> str:
    now = datetime.now(UTC)
    digest = source_text_hash(source)
    manifest = TranslationInputManifestV1(
        debate_id=UUID(debate_id),
        turns=[ManifestTurn(turn_id=UUID(turn_id), turn_index=0, source_text_hash=digest)],
    )
    batch_id, entry_id = str(uuid4()), str(uuid4())
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                debate_id,
                COURSE_ID,
                TEACHER_ID,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "pending",
                manifest_json or manifest.canonical_bytes().decode(),
                manifest.input_hash,
                1,
                0,
                0,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                debate_id,
                "turn",
                turn_id,
                None,
                digest,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "pending",
                None,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (batch_id, entry_id, debate_id, 0, 0, "pending", None),
        )
        if add_job:
            connection.exec_driver_sql(
                "INSERT INTO jobs (id,debate_id,turn_id,operation,state,safe_error_code,attempt,"
                "created_at,updated_at,translation_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    debate_id,
                    None,
                    "translation.generate",
                    "pending",
                    None,
                    0,
                    now,
                    now,
                    batch_id,
                ),
            )
    return batch_id


@pytest.mark.parametrize("with_job,tampered", [(False, False), (True, True)])
def test_job_or_manifest_contract_failure_is_before_provider(
    tmp_path: Path, with_job: bool, tampered: bool
) -> None:
    db = Database(f"sqlite:///{tmp_path / f'fail-{with_job}-{tampered}.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    _install_wave3_tables(db)
    turn_id, source = str(uuid4()), "Provider must never see invalid ownership"
    now = datetime.now(UTC)
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO debate_turns (id,debate_id,participant_id,knowledge_snapshot_id,round_no,"
            "turn_index,generation_status,publication_status,preparation_stage,speech,"
            "predecessor_turn_ids_json,retrieval_receipts_json,attempt,created_at,updated_at) "
            "VALUES (?,?,?,?,1,0,'final_ready','public','ready',?,'[]','[]',1,?,?)",
            (turn_id, debate_id, str(uuid4()), str(uuid4()), source, now, now),
        )
    batch_id = _insert_pending_contract(
        db,
        debate_id=debate_id,
        turn_id=turn_id,
        source=source,
        manifest_json="{}" if tampered else None,
        add_job=with_job,
    )
    provider = MockTranslationProvider()
    service = TranslationService(db.session_factory, provider=provider)
    service.run_batch(batch_id)
    assert provider.call_count == 0


def test_active_entry_reuse_is_exact_and_poisoned_report_translation_is_ignored(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'identity.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    _install_wave3_tables(db)
    source, turn_id, now = "Exact active", str(uuid4()), datetime.now(UTC)
    digest = source_text_hash(source)
    entry_id = str(uuid4())
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                debate_id,
                "turn",
                turn_id,
                None,
                digest,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "pending",
                None,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                debate_id,
                "report_revision",
                None,
                str(uuid4()),
                "f" * 64,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "ready",
                "poisoned derived text",
                None,
                now,
                now,
            ),
        )
    service = TranslationService(db.session_factory)
    from app.modules.translations.manifest import ManifestSource

    with db.session() as session:
        found = service._cache_entry(
            session,
            debate_id=debate_id,
            source=ManifestSource("turn", turn_id, 0, source, digest),
            policy_key=MOCK_TRANSLATION_POLICY,
            quality_key=MOCK_TRANSLATION_QUALITY,
        )
        wrong = service._cache_entry(
            session,
            debate_id=debate_id,
            source=ManifestSource("turn", turn_id, 0, source + "!", source_text_hash(source + "!")),
            policy_key=MOCK_TRANSLATION_POLICY,
            quality_key=MOCK_TRANSLATION_QUALITY,
        )
    assert found == (entry_id, "pending")
    assert wrong is None
    with db.session() as session:
        report = attach_translated_report(
            session,
            debate_id=debate_id,
            report={"revision_id": str(uuid4()), "english_markdown": "authoritative report"},
        )
    assert report["translated_markdown"] is None


def test_recovery_all_ready_is_completed_with_exclusive_counts(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'all-ready.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    _install_wave3_tables(db)
    now, batch_id, entry_id, turn_id = datetime.now(UTC), str(uuid4()), str(uuid4()), str(uuid4())
    source = "already durable"
    manifest = TranslationInputManifestV1(
        debate_id=UUID(debate_id),
        turns=[
            ManifestTurn(
                turn_id=UUID(turn_id), turn_index=0, source_text_hash=source_text_hash(source)
            )
        ],
    )
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                batch_id,
                debate_id,
                COURSE_ID,
                TEACHER_ID,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "running",
                manifest.canonical_bytes().decode(),
                manifest.input_hash,
                1,
                0,
                0,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                debate_id,
                "turn",
                turn_id,
                None,
                source_text_hash(source),
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "ready",
                MOCK_PREFIX + source,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (batch_id, entry_id, debate_id, 0, 1, "ready", None),
        )
        connection.exec_driver_sql(
            "INSERT INTO jobs (id,debate_id,turn_id,operation,state,safe_error_code,attempt,"
            "created_at,updated_at,translation_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                debate_id,
                None,
                "translation.generate",
                "running",
                None,
                1,
                now,
                now,
                batch_id,
            ),
        )
    service = TranslationService(db.session_factory)
    with db.session() as session:
        assert service.recover_startup(session) == ()
    with db.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status,total_items,succeeded_items,failed_items FROM translation_batches "
                "WHERE id=:id"
            ),
            {"id": batch_id},
        ).one()
    assert tuple(row) == ("completed", 1, 1, 0)


def test_shared_running_entry_waits_for_owner_and_never_calls_second_provider(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'shared-owner.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    _install_wave3_tables(db)
    now, turn_id, entry_id = datetime.now(UTC), str(uuid4()), str(uuid4())
    source, digest = "shared exact source", source_text_hash("shared exact source")
    manifest = TranslationInputManifestV1(
        debate_id=UUID(debate_id),
        turns=[ManifestTurn(turn_id=UUID(turn_id), turn_index=0, source_text_hash=digest)],
    )
    owner_batch, follower_batch = str(uuid4()), str(uuid4())
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO debate_turns (id,debate_id,participant_id,knowledge_snapshot_id,round_no,"
            "turn_index,generation_status,publication_status,preparation_stage,speech,"
            "predecessor_turn_ids_json,retrieval_receipts_json,attempt,created_at,updated_at) "
            "VALUES (?,?,?,?,1,0,'final_ready','public','ready',?,'[]','[]',1,?,?)",
            (turn_id, debate_id, str(uuid4()), str(uuid4()), source, now, now),
        )
        for batch_id, status in ((owner_batch, "running"), (follower_batch, "pending")):
            connection.exec_driver_sql(
                "INSERT INTO translation_batches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    batch_id,
                    debate_id,
                    COURSE_ID,
                    TEACHER_ID,
                    "zh-Hans",
                    MOCK_TRANSLATION_POLICY,
                    MOCK_TRANSLATION_QUALITY,
                    status,
                    manifest.canonical_bytes().decode(),
                    manifest.input_hash,
                    1,
                    0,
                    0,
                    now,
                    now,
                ),
            )
        connection.exec_driver_sql(
            "INSERT INTO translation_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entry_id,
                debate_id,
                "turn",
                turn_id,
                None,
                digest,
                "zh-Hans",
                MOCK_TRANSLATION_POLICY,
                MOCK_TRANSLATION_QUALITY,
                "running",
                None,
                None,
                now,
                now,
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (owner_batch, entry_id, debate_id, 0, 0, "running", None),
        )
        connection.exec_driver_sql(
            "INSERT INTO translation_batch_items VALUES (?,?,?,?,?,?,?)",
            (follower_batch, entry_id, debate_id, 0, 1, "pending", None),
        )
        for batch_id, state in ((owner_batch, "running"), (follower_batch, "pending")):
            connection.exec_driver_sql(
                "INSERT INTO jobs (id,debate_id,turn_id,operation,state,safe_error_code,attempt,"
                "created_at,updated_at,translation_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    debate_id,
                    None,
                    "translation.generate",
                    state,
                    None,
                    1,
                    now,
                    now,
                    batch_id,
                ),
            )
    provider = MockTranslationProvider()
    events: list[tuple[str, str, object]] = []
    service = TranslationService(
        db.session_factory,
        provider=provider,
        event_publisher=lambda debate, event, payload: events.append((debate, event, payload)),
    )
    waiting = service.run_batch(follower_batch)
    assert waiting is not None and waiting.status == "pending"
    assert provider.call_count == 0
    assert events == []
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE translation_entries SET status='ready',translated_text=:text WHERE id=:id"
            ),
            {"id": entry_id, "text": MOCK_PREFIX + source},
        )
    completed = service.run_batch(follower_batch)
    assert completed is not None and completed.status == "completed"
    assert provider.call_count == 0
    assert [event[1] for event in events] == ["translation.batch_completed"]


def test_started_event_is_once_immediately_before_owned_provider(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'started.sqlite3'}", tmp_path)
    debate_id = _make_baseline(db)
    _install_wave3_tables(db)
    turn_id, source, now = str(uuid4()), "owned source", datetime.now(UTC)
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO debate_turns (id,debate_id,participant_id,knowledge_snapshot_id,round_no,"
            "turn_index,generation_status,publication_status,preparation_stage,speech,"
            "predecessor_turn_ids_json,retrieval_receipts_json,attempt,created_at,updated_at) "
            "VALUES (?,?,?,?,1,0,'final_ready','public','ready',?,'[]','[]',1,?,?)",
            (turn_id, debate_id, str(uuid4()), str(uuid4()), source, now, now),
        )
    batch_id = _insert_pending_contract(db, debate_id=debate_id, turn_id=turn_id, source=source)
    events: list[str] = []
    service = TranslationService(
        db.session_factory,
        provider=MockTranslationProvider(),
        event_publisher=lambda _debate, event, _payload: events.append(event),
    )
    result = service.run_batch(batch_id)
    assert result is not None and result.status == "completed"
    assert events == ["translation.batch_started", "translation.batch_completed"]
