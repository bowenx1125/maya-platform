from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.core.db import ALEMBIC_HEAD, Database
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.seed import (
    COURSE_ID,
    GROUP_DEMO_ID,
    STUDENT_IDS,
    TEACHER_ID,
    SeedConflict,
    row_fingerprint,
    seed_demo_data,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def _snapshot(session: Session) -> dict[str, Any]:
    return {
        "users": [
            (row.id, row.username, row.display_name) for row in session.scalars(select(User)).all()
        ],
        "courses": [(row.id, row.code, row.name) for row in session.scalars(select(Course)).all()],
        "groups": [
            (row.id, row.course_id, row.name) for row in session.scalars(select(Group)).all()
        ],
        "course_members": sorted(
            (row.course_id, row.user_id, row.role)
            for row in session.scalars(select(CourseMember)).all()
        ),
        "group_members": sorted(
            (row.group_id, row.user_id, row.role)
            for row in session.scalars(select(GroupMember)).all()
        ),
        "fingerprints": {
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
        },
    }


def test_seed_is_exact_and_idempotent(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'seed.sqlite3'}")
    db.upgrade_schema()
    with db.session() as session:
        seed_demo_data(session)
    with db.session() as session:
        before = _snapshot(session)
        seed_demo_data(session)
        after = _snapshot(session)
    assert before == after
    assert {row[0] for row in before["users"]} == {
        TEACHER_ID,
        *STUDENT_IDS,
        *STUDENT_IDS,
    }
    assert before["courses"] == [(COURSE_ID, "demo-course-001", "Maya Cultural Exchange Demo")]
    assert {row[0] for row in before["groups"]} == {GROUP_DEMO_ID, GROUP_DEMO_ID}


def test_seed_conflict_rolls_back_everything(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'conflict.sqlite3'}")
    db.upgrade_schema()
    with db.session() as session:
        session.add(
            Course(
                id=COURSE_ID,
                code="demo-course-001",
                name="conflicting course",
                created_at=datetime.now(UTC),
            )
        )
    with pytest.raises(SeedConflict):
        with db.session() as session:
            seed_demo_data(session)
    with db.session() as session:
        assert session.scalar(select(User)) is None
        course = session.get(Course, COURSE_ID)
        assert course is not None
        assert course.name == "conflicting course"


def test_seed_cli_uses_alembic_and_is_repeatable(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cli.sqlite3'}"
    command = [sys.executable, "-m", "app.seed", "--database-url", database_url]
    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command, check=False, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    db = Database(database_url)
    with db.session() as session:
        assert session.scalar(select(User)) is not None
    with db.engine.connect() as connection:
        assert ALEMBIC_HEAD == "0075_real_delete_history_links"
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == ALEMBIC_HEAD
        )
