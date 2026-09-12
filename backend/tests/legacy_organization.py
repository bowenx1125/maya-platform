"""Seed historical migration fixtures without querying today's ORM columns."""

from datetime import UTC, datetime

from app.seed import (
    COURSE_CODE,
    COURSE_ID,
    COURSE_NAME,
    GROUP_SPECS,
    STUDENT_IDS,
    TEACHER_ID,
    USERS,
)
from sqlalchemy import MetaData, Table
from sqlalchemy.orm import Session


def seed_legacy_organization(session: Session) -> None:
    connection = session.connection()
    metadata = MetaData()
    tables = {
        name: Table(name, metadata, autoload_with=connection)
        for name in ("users", "courses", "groups", "course_members", "group_members")
    }
    now = datetime.now(UTC)
    for user in USERS:
        session.execute(
            tables["users"]
            .insert()
            .values(
                id=user.id,
                username=user.username,
                display_name=user.display_name,
                status="active",
                created_at=now,
            )
        )
    session.execute(
        tables["courses"]
        .insert()
        .values(
            id=COURSE_ID,
            code=COURSE_CODE,
            name=COURSE_NAME,
            created_at=now,
        )
    )
    for group_id, name in GROUP_SPECS:
        session.execute(
            tables["groups"]
            .insert()
            .values(
                id=group_id,
                course_id=COURSE_ID,
                name=name,
                created_at=now,
            )
        )
    for user_id in (TEACHER_ID, *STUDENT_IDS):
        session.execute(
            tables["course_members"]
            .insert()
            .values(
                course_id=COURSE_ID,
                user_id=user_id,
                role="teacher" if user_id == TEACHER_ID else "student",
                created_at=now,
            )
        )
    for index, user_id in enumerate(STUDENT_IDS):
        session.execute(
            tables["group_members"]
            .insert()
            .values(
                group_id=GROUP_SPECS[0][0],
                user_id=user_id,
                role="leader" if index == 0 else "member",
                created_at=now,
            )
        )
