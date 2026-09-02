"""Prove that a populated Wave 0 database upgrades safely to Wave 1A.

This probe owns its temporary SQLite database and never touches the product
``backend/data`` directory.  It deliberately seeds at the exact Wave 0
revision before upgrading to the Wave 1A head, then captures the fixed rows,
relationships and seed fingerprints for an equality check.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import ALEMBIC_HEAD, Database  # noqa: E402
from app.core.models import Course, CourseMember, Group, GroupMember, User  # noqa: E402
from app.seed import (  # noqa: E402
    COURSE_ID,
    GROUP_DEMO_ID,
    STUDENT_IDS,
    TEACHER_ID,
    row_fingerprint,
    seed_demo_data,
)

WAVE_0_REVISION = "0001_wave0_baseline"


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
    if result.returncode != 0:
        raise RuntimeError(f"Alembic upgrade to {target} failed ({result.returncode})")


def current_revision(database: Database) -> str | None:
    with database.engine.connect() as connection:
        value = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    return str(value) if value is not None else None


def fixed_rows(database: Database) -> dict[str, Any]:
    with database.session() as session:
        users = sorted(
            (row.id, row.username, row.display_name, row.status)
            for row in session.scalars(select(User)).all()
        )
        courses = sorted(
            (row.id, row.code, row.name) for row in session.scalars(select(Course)).all()
        )
        groups = sorted(
            (row.id, row.course_id, row.name) for row in session.scalars(select(Group)).all()
        )
        course_members = sorted(
            (row.course_id, row.user_id, row.role)
            for row in session.scalars(select(CourseMember)).all()
        )
        group_members = sorted(
            (row.group_id, row.user_id, row.role)
            for row in session.scalars(select(GroupMember)).all()
        )
        fingerprints = {
            **{
                f"user:{row.id}": row_fingerprint(row, ("username", "display_name", "status"))
                for row in session.scalars(select(User)).all()
            },
            **{
                f"course:{row.id}": row_fingerprint(row, ("code", "name"))
                for row in session.scalars(select(Course)).all()
            },
            **{
                f"group:{row.id}": row_fingerprint(row, ("course_id", "name"))
                for row in session.scalars(select(Group)).all()
            },
        }
    return {
        "users": users,
        "courses": courses,
        "groups": groups,
        "course_members": course_members,
        "group_members": group_members,
        "fingerprints": fingerprints,
    }


def digest(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_seed_shape(snapshot: dict[str, Any]) -> None:
    # One course, one teacher, one group of three students.
    if len(snapshot["users"]) != 4:
        raise AssertionError("Wave 0 seed user count changed")
    if snapshot["courses"] != [(COURSE_ID, "demo-course-001", "Maya Cultural Exchange Demo")]:
        raise AssertionError("Wave 0 seed course changed")
    if {row[0] for row in snapshot["groups"]} != {GROUP_DEMO_ID}:
        raise AssertionError("Wave 0 seed groups changed")
    if len(snapshot["course_members"]) != 4 or len(snapshot["group_members"]) != 3:
        raise AssertionError("Wave 0 seed relationships changed")
    if TEACHER_ID not in {row[1] for row in snapshot["course_members"]}:
        raise AssertionError("Wave 0 teacher membership is missing")
    if {row[1] for row in snapshot["group_members"]} != set(STUDENT_IDS):
        raise AssertionError("Wave 0 group membership is missing a student")


def assert_wave1_schema(database: Database) -> tuple[int, int]:
    inspector = inspect(database.engine)
    expected_tables = {
        "agents",
        "agent_versions",
        "stored_files",
        "knowledge_documents",
        "knowledge_document_chunks",
        "agent_version_documents",
        "knowledge_snapshots",
        "snapshot_documents",
        "knowledge_chunks",
        "file_references",
        "idempotency_records",
        "file_operations",
        "jobs",
    }
    missing_tables = expected_tables.difference(inspector.get_table_names())
    if missing_tables:
        raise AssertionError(f"Wave 1A tables are missing ({len(missing_tables)})")

    expected_unique_constraints = {
        "agent_versions": {"uq_agent_versions_agent_seq"},
        "knowledge_document_chunks": {"uq_knowledge_document_chunks_order"},
        "snapshot_documents": {
            "uq_snapshot_documents_source",
            "uq_snapshot_documents_order",
        },
        "knowledge_snapshots": {"uq_knowledge_snapshots_agent_version"},
        "knowledge_chunks": {"uq_knowledge_chunks_order"},
        "stored_files": {"uq_stored_files_relative_path"},
        "idempotency_records": {"uq_idempotency_actor_operation_key"},
    }
    expected_indexes = {
        "agents": {"ix_agents_group_id", "ix_agents_group_status"},
        "agent_versions": {
            "ix_agent_versions_agent_state",
            "uq_agent_versions_one_draft",
        },
        "knowledge_document_chunks": {"ix_knowledge_document_chunks_document"},
        "knowledge_documents": {"ix_knowledge_documents_group_state"},
        "agent_version_documents": {
            "ix_agent_version_documents_document",
            "uq_agent_version_documents_enabled_order",
        },
        "snapshot_documents": {
            "ix_snapshot_documents_snapshot",
            "uq_snapshot_documents_identity",
        },
        "knowledge_chunks": {"ix_knowledge_chunks_snapshot"},
        "file_references": {"ix_file_references_owner"},
        "idempotency_records": {"ix_idempotency_lease"},
        "file_operations": {"ix_file_operations_state"},
        "jobs": {"ix_jobs_document"},
    }
    expected_checks = {
        "agents": {"ck_agents_status"},
        "agent_versions": {
            "ck_agent_versions_seq_nonnegative",
            "ck_agent_versions_revision_nonnegative",
            "ck_agent_versions_state",
        },
        "knowledge_documents": {
            "ck_knowledge_documents_char_count",
            "ck_knowledge_documents_index_revision",
            "ck_knowledge_documents_index_status",
            "ck_knowledge_documents_workspace_state",
        },
        "knowledge_document_chunks": {
            "ck_knowledge_document_chunks_index",
            "ck_knowledge_document_chunks_offsets",
        },
        "agent_version_documents": {"ck_agent_version_documents_order"},
        "knowledge_snapshots": {"ck_knowledge_snapshots_total_chars"},
        "snapshot_documents": {"ck_snapshot_documents_order"},
        "knowledge_chunks": {
            "ck_knowledge_chunks_index",
            "ck_knowledge_chunks_offsets",
        },
        "stored_files": {"ck_stored_files_size", "ck_stored_files_state"},
        "file_operations": {"ck_file_operations_state"},
        "idempotency_records": {"ck_idempotency_state"},
        "jobs": {"ck_jobs_state"},
    }
    checked_constraints = 0
    for table, names in expected_unique_constraints.items():
        actual = {item["name"] for item in inspector.get_unique_constraints(table)}
        missing = names.difference(actual)
        if missing:
            raise AssertionError(f"Wave 1A unique constraints missing from {table}")
        checked_constraints += len(names)
    for table, names in expected_indexes.items():
        actual = {item["name"] for item in inspector.get_indexes(table)}
        missing = names.difference(actual)
        if missing:
            raise AssertionError(f"Wave 1A indexes missing from {table}")
        checked_constraints += len(names)
    for table, names in expected_checks.items():
        actual = {item["name"] for item in inspector.get_check_constraints(table)}
        missing = names.difference(actual)
        if missing:
            raise AssertionError(f"Wave 1A checks missing from {table}")
        checked_constraints += len(names)
    return len(expected_tables), checked_constraints


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maya-wave1-populated-migration-") as temporary:
        database_path = Path(temporary) / "populated.sqlite3"
        run_alembic(database_path, WAVE_0_REVISION)
        database = Database(database_url(database_path), Path(temporary))
        try:
            if current_revision(database) != WAVE_0_REVISION:
                raise AssertionError("database did not stop at the exact Wave 0 revision")
            with database.session() as session:
                seed_demo_data(session)
            before = fixed_rows(database)
            assert_seed_shape(before)
            before_digest = digest(before)

            run_alembic(database_path, "head")
            run_alembic(database_path, "head")
            if current_revision(database) != ALEMBIC_HEAD:
                raise AssertionError("populated database did not reach the Wave 1A head")
            after = fixed_rows(database)
            if before != after:
                raise AssertionError("Wave 0 fixed rows or relationships changed during upgrade")
            table_count, constraint_count = assert_wave1_schema(database)
            print(
                "populated migration evidence passed: "
                "Wave 0 seed preserved "
                # Counted, not asserted in prose: a hard-coded evidence line
                # kept reporting the old seed shape after it changed.
                f"({len(before['users'])} users/{len(before['courses'])} course/"
                f"{len(before['course_members'])} course members/"
                f"{len(before['groups'])} groups/"
                f"{len(before['group_members'])} group members), "
                f"fingerprint={before_digest}, head={ALEMBIC_HEAD}, "
                f"new_tables={table_count}, checked_constraints={constraint_count}"
            )
        finally:
            database.dispose()


if __name__ == "__main__":
    main()
