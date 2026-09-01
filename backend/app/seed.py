"""Deterministic, transactional Wave 0 organization seed."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Database
from app.core.models import Course, CourseMember, Group, GroupMember, User

SEED_NAMESPACE = "a7cea9e2-390f-5b48-b129-4f388b0362e3"
SEED_NAMESPACE_UUID = UUID(SEED_NAMESPACE)


def seed_uuid(seed_key: str) -> str:
    """Return the frozen UUIDv5 value for a demo seed key."""

    return str(uuid5(SEED_NAMESPACE_UUID, seed_key))


SEED_IDS = {
    "demo-course-001": "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b",
    "group-demo": "7813f937-902c-5534-bfb2-ad773a43aeda",
    "maya": "08b9de2d-bb75-5c71-a64b-231b48f9eb25",
    "bowen": "60541c78-30f1-55c5-b2aa-207b6a766883",
    "kaikai": "bc170f51-45fb-5296-a36d-a2edc8f8d315",
    "jade": "89857c76-2d84-5ecf-b680-990815b98680",
}

# Fail fast during module import if a future edit accidentally drifts one of
# the exact UUIDv5 values frozen by C02.5.
if any(seed_uuid(key) != value for key, value in SEED_IDS.items()):
    raise RuntimeError("frozen Wave 0 seed UUIDs are inconsistent")

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
BOWEN_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"
KAIKAI_ID = "bc170f51-45fb-5296-a36d-a2edc8f8d315"
JADE_ID = "89857c76-2d84-5ecf-b680-990815b98680"
STUDENT_IDS = (BOWEN_ID, KAIKAI_ID, JADE_ID)


class SeedConflict(RuntimeError):
    """Raised when a fixed seed row exists with a different fingerprint."""

    code = "seed_conflict"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def row_fingerprint(instance: object, fields: Iterable[str]) -> str:
    """Compute the fixed-row fingerprint used by seed conflict checks."""

    values = {field: getattr(instance, field) for field in fields}
    return _fingerprint(values)


@dataclass(frozen=True)
class UserSeed:
    id: str
    username: str
    display_name: str


USERS = (
    UserSeed(TEACHER_ID, "maya", "Maya"),
    UserSeed(BOWEN_ID, "bowen", "Bowen"),
    UserSeed(KAIKAI_ID, "kaikai", "Kaikai"),
    UserSeed(JADE_ID, "jade", "Jade"),
)

COURSE_CODE = "demo-course-001"
COURSE_NAME = "Maya Cultural Exchange Demo"
GROUP_SPECS = ((GROUP_DEMO_ID, "Demo Group"),)


def _existing_by_id(session: Session, model: Any, object_id: str) -> Any:
    return session.get(model, object_id)


def _ensure_user(session: Session, seed: UserSeed, now: datetime) -> User:
    existing = _existing_by_id(session, User, seed.id)
    if existing is not None:
        assert isinstance(existing, User)
        expected = _fingerprint(
            {"username": seed.username, "display_name": seed.display_name, "status": "active"}
        )
        actual = row_fingerprint(existing, ("username", "display_name", "status"))
        if actual != expected:
            raise SeedConflict(f"fixed user row conflicts: {seed.id}")
        return existing
    duplicate = session.scalar(select(User).where(User.username == seed.username))
    if duplicate is not None:
        raise SeedConflict(f"fixed user username conflicts: {seed.username}")
    user = User(
        id=seed.id,
        username=seed.username,
        display_name=seed.display_name,
        status="active",
        created_at=now,
    )
    session.add(user)
    return user


def _ensure_course(session: Session, now: datetime) -> Course:
    existing = session.get(Course, COURSE_ID)
    if existing is not None:
        expected = _fingerprint({"code": COURSE_CODE, "name": COURSE_NAME})
        actual = row_fingerprint(existing, ("code", "name"))
        if actual != expected:
            raise SeedConflict(f"fixed course row conflicts: {COURSE_ID}")
        return existing
    duplicate = session.scalar(select(Course).where(Course.code == COURSE_CODE))
    if duplicate is not None:
        raise SeedConflict(f"fixed course code conflicts: {COURSE_CODE}")
    course = Course(
        id=COURSE_ID,
        code=COURSE_CODE,
        name=COURSE_NAME,
        current_audio_debate_id=None,
        created_at=now,
    )
    session.add(course)
    return course


def _ensure_group(session: Session, group_id: str, name: str, now: datetime) -> Group:
    existing = session.get(Group, group_id)
    if existing is not None:
        expected = _fingerprint({"course_id": COURSE_ID, "name": name})
        actual = row_fingerprint(existing, ("course_id", "name"))
        if actual != expected:
            raise SeedConflict(f"fixed group row conflicts: {group_id}")
        return existing
    duplicate = session.scalar(
        select(Group).where(Group.course_id == COURSE_ID, Group.name == name)
    )
    if duplicate is not None:
        raise SeedConflict(f"fixed group name conflicts: {name}")
    group = Group(id=group_id, course_id=COURSE_ID, name=name, created_at=now)
    session.add(group)
    return group


def _ensure_course_member(session: Session, user_id: str, role: str, now: datetime) -> None:
    existing = session.get(CourseMember, {"course_id": COURSE_ID, "user_id": user_id})
    if existing is not None:
        assert isinstance(existing, CourseMember)
        if existing.role != role:
            raise SeedConflict(f"fixed course membership conflicts: {user_id}")
        return
    session.add(CourseMember(course_id=COURSE_ID, user_id=user_id, role=role, created_at=now))


def _ensure_group_member(
    session: Session,
    group_id: str,
    user_id: str,
    role: str,
    now: datetime,
) -> None:
    existing = session.get(GroupMember, {"group_id": group_id, "user_id": user_id})
    if existing is not None:
        assert isinstance(existing, GroupMember)
        if existing.role != role:
            raise SeedConflict(f"fixed group membership conflicts: {group_id}/{user_id}")
        return
    session.add(GroupMember(group_id=group_id, user_id=user_id, role=role, created_at=now))


def seed_demo_data(session: Session) -> None:
    """Create or verify all fixed Wave 0 organization rows atomically.

    The caller's transaction is intentionally used unchanged: if any fixed
    row conflicts, ``SeedConflict`` escapes and the database context rolls the
    entire transaction back, including rows created earlier in this function.
    """

    now = utc_now()
    for user in USERS:
        _ensure_user(session, user, now)
    _ensure_course(session, now)
    for group_id, name in GROUP_SPECS:
        _ensure_group(session, group_id, name, now)

    _ensure_course_member(session, TEACHER_ID, "teacher", now)
    for student_id in STUDENT_IDS:
        _ensure_course_member(session, student_id, "student", now)

    expected_group_for_user = {student_id: GROUP_DEMO_ID for student_id in STUDENT_IDS}
    for student_id, expected_group_id in expected_group_for_user.items():
        existing_groups = session.scalars(
            select(GroupMember.group_id).where(GroupMember.user_id == student_id)
        ).all()
        if any(group_id != expected_group_id for group_id in existing_groups):
            raise SeedConflict(f"fixed student group relationship conflicts: {student_id}")
    if session.scalar(select(GroupMember.group_id).where(GroupMember.user_id == TEACHER_ID)):
        raise SeedConflict("fixed teacher group relationship conflicts")

    for index, student_id in enumerate(STUDENT_IDS):
        _ensure_group_member(
            session,
            GROUP_DEMO_ID,
            student_id,
            "leader" if index == 0 else "member",
            now,
        )

    # Flush inside the transaction so a uniqueness/foreign-key error is
    # observed before the caller can accidentally commit a partial seed.
    try:
        session.flush()
    except IntegrityError as exc:
        raise SeedConflict("fixed seed rows conflict with existing database data") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Maya demo organization data")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    settings = get_settings()
    database_url = args.database_url or settings.database_url
    database = Database(database_url, settings.resolved_data_root)
    database.upgrade_schema()
    if not database.check_ready():
        raise RuntimeError("database is not ready after Alembic upgrade")
    with database.session() as session:
        seed_demo_data(session)
    database.dispose()


if __name__ == "__main__":
    main()
