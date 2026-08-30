"""Deterministic Wave 3 migration preservation and reversibility probe."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import Database  # noqa: E402
from app.seed import COURSE_ID, TEACHER_ID, seed_demo_data  # noqa: E402

REVISION_0006 = "0006_pre_wave3_polish"
REVISION_0007 = "0007_wave3_interaction_report"
DEBATE_ID = "11111111-1111-4111-8111-111111111111"
WAVE3_TABLES = {
    "barrage_insight_assignments",
    "barrage_insight_items",
    "barrage_insight_snapshots",
    "barrage_messages",
    "civilization_report_current_success",
    "civilization_report_revisions",
    "civilization_reports",
    "classroom_interaction_windows",
    "interaction_final_barrages",
    "interaction_final_vote_counts",
    "translation_batch_items",
    "translation_batches",
    "translation_entries",
    "votes",
}


def database_url(path: Path) -> str:
    return f"sqlite:///{path}"


def alembic(path: Path, command: str, target: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url(path)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", command, target],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Alembic {command} {target} failed: {result.stderr[-2000:]}")


def seed_populated_0006(path: Path, data_root: Path) -> None:
    database = Database(database_url(path), data_root)
    now = datetime.now(UTC)
    try:
        with database.session() as session:
            seed_demo_data(session)
            session.execute(
                text(
                    "INSERT INTO debates "
                    "(id,course_id,topic,rule_set_id,rule_snapshot_json,status,revision,"
                    "last_sequence,cancellation_generation,created_by,created_at,updated_at,"
                    "total_duration_seconds,turn_duration_seconds) VALUES "
                    "(:id,:course,:topic,:rule_set,:snapshot,'draft',0,0,0,:teacher,:now,:now,"
                    "NULL,NULL)"
                ),
                {
                    "id": DEBATE_ID,
                    "course": str(COURSE_ID),
                    "topic": "Wave 3 populated migration debate",
                    "rule_set": "ordered_multi_agent_rounds_demo_v1",
                    "snapshot": "{}",
                    "teacher": str(TEACHER_ID),
                    "now": now,
                },
            )
    finally:
        database.dispose()


def historical_shape(path: Path) -> dict[str, list[str]]:
    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        return {
            table: [str(column["name"]) for column in inspector.get_columns(table)]
            for table in inspector.get_table_names()
            if table != "alembic_version"
        }
    finally:
        database.dispose()


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def historical_fingerprint(path: Path, shape: dict[str, list[str]]) -> dict[str, str]:
    database = Database(database_url(path))
    output: dict[str, str] = {}
    try:
        with database.engine.connect() as connection:
            for table, columns in sorted(shape.items()):
                rows = [
                    [_json_value(value) for value in row]
                    for row in connection.execute(
                        text(f"SELECT {', '.join(columns)} FROM {table}")
                    ).all()
                ]
                rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
                encoded = json.dumps(rows, sort_keys=True, separators=(",", ":"))
                output[table] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return output
    finally:
        database.dispose()


def assert_head_and_fks(path: Path, expected: str) -> None:
    database = Database(database_url(path))
    try:
        with database.engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != expected:
                raise AssertionError(f"expected {expected}, got {revision}")
            violations = connection.execute(text("PRAGMA foreign_key_check")).all()
            if violations:
                raise AssertionError(f"foreign-key violations: {violations}")
    finally:
        database.dispose()


def assert_wave3_schema(path: Path) -> None:
    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        tables = set(inspector.get_table_names())
        if not WAVE3_TABLES.issubset(tables):
            raise AssertionError(f"missing Wave 3 tables: {sorted(WAVE3_TABLES - tables)}")
        job_columns = {str(row["name"]) for row in inspector.get_columns("jobs")}
        expected_job_columns = {
            "insight_snapshot_id",
            "report_revision_id",
            "translation_batch_id",
        }
        if not expected_job_columns.issubset(job_columns):
            raise AssertionError("typed Wave 3 Job owners are missing")
        job_indexes = {str(row["name"]) for row in inspector.get_indexes("jobs")}
        expected_job_indexes = {
            "uq_jobs_insight_snapshot",
            "uq_jobs_report_revision",
            "uq_jobs_translation_batch",
        }
        if not expected_job_indexes.issubset(job_indexes):
            raise AssertionError("typed Wave 3 Job owner fences are missing")
        translation_indexes = {
            str(row["name"]) for row in inspector.get_indexes("translation_entries")
        }
        if not {
            "uq_translation_entries_turn_active_cache",
            "uq_translation_entries_turn_ready_cache",
            "uq_translation_entries_report_active_cache",
            "uq_translation_entries_report_ready_cache",
        }.issubset(translation_indexes):
            raise AssertionError("translation cache fences are missing")
        with database.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT id,status,token_nonce,revision FROM classroom_interaction_windows "
                    "WHERE debate_id=:debate_id"
                ),
                {"debate_id": DEBATE_ID},
            ).one()
        expected_id = str(uuid5(NAMESPACE_URL, f"maya:interaction:{DEBATE_ID}"))
        if tuple(row) != (expected_id, "closed", None, 0):
            raise AssertionError(f"invalid closed interaction backfill: {tuple(row)}")
    finally:
        database.dispose()


def assert_wave3_removed(path: Path) -> None:
    database = Database(database_url(path))
    try:
        inspector = inspect(database.engine)
        retained = WAVE3_TABLES.intersection(inspector.get_table_names())
        if retained:
            raise AssertionError(f"downgrade retained Wave 3 tables: {sorted(retained)}")
        job_columns = {str(row["name"]) for row in inspector.get_columns("jobs")}
        if job_columns.intersection(
            {"insight_snapshot_id", "report_revision_id", "translation_batch_id"}
        ):
            raise AssertionError("downgrade retained Wave 3 Job columns")
    finally:
        database.dispose()


def insert_stale_idempotency(path: Path) -> None:
    database = Database(database_url(path))
    try:
        with database.session() as session:
            now = datetime.now(UTC)
            session.execute(
                text(
                    "INSERT INTO idempotency_records "
                    "(id,actor_user_id,operation,key,request_hash,state,claim_token,"
                    "lease_expires_at,status_code,response_json,created_at,updated_at) VALUES "
                    "(:id,:actor,'report.generate',:key,:hash,'completed',:claim,:now,"
                    "202,:response,:now,:now)"
                ),
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "actor": str(TEACHER_ID),
                    "key": "wave3-migration-stale-key",
                    "hash": "a" * 64,
                    "claim": "b" * 64,
                    "now": now,
                    "response": '{"revision_id":"deleted-by-downgrade"}',
                },
            )
    finally:
        database.dispose()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave3-migration-") as temporary:
        root = Path(temporary)
        fresh = root / "fresh.sqlite3"
        alembic(fresh, "upgrade", "head")
        alembic(fresh, "upgrade", "head")
        assert_head_and_fks(fresh, REVISION_0007)

        populated = root / "populated.sqlite3"
        alembic(populated, "upgrade", REVISION_0006)
        seed_populated_0006(populated, root / "data")
        shape = historical_shape(populated)
        fingerprint = historical_fingerprint(populated, shape)

        alembic(populated, "upgrade", REVISION_0007)
        alembic(populated, "upgrade", REVISION_0007)
        assert_head_and_fks(populated, REVISION_0007)
        assert_wave3_schema(populated)
        if historical_fingerprint(populated, shape) != fingerprint:
            raise AssertionError("0007 changed pre-existing rows")

        insert_stale_idempotency(populated)
        alembic(populated, "downgrade", REVISION_0006)
        assert_head_and_fks(populated, REVISION_0006)
        assert_wave3_removed(populated)
        if historical_fingerprint(populated, shape) != fingerprint:
            raise AssertionError("0007 downgrade changed pre-existing rows")

        alembic(populated, "upgrade", REVISION_0007)
        assert_head_and_fks(populated, REVISION_0007)
        assert_wave3_schema(populated)
        if historical_fingerprint(populated, shape) != fingerprint:
            raise AssertionError("0007 re-upgrade changed pre-existing rows")

    print(
        "Wave 3 migration passed: fresh/repeat/populated 0006→0007, "
        "downgrade/re-upgrade, deterministic closed-window backfill, "
        "historical fingerprints, typed Job/cache fences and foreign_key_check=0"
    )


if __name__ == "__main__":
    main()
