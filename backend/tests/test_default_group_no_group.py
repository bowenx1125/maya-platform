"""Default-group migration and runtime enrolment preserve every existing row."""

import importlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.db import ALEMBIC_HEAD, Database
from app.core.group_names import DEFAULT_GROUP_NAME
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.org.classes import (
    SECOND_CLASS_GROUP_ID,
    SECOND_CLASS_ID,
    default_class_group,
    ensure_student_group,
)
from app.modules.org.names import resolve_named_group
from app.seed import COURSE_ID, GROUP_DEMO_ID, seed_demo_data, seed_uuid
from sqlalchemy import select, text

from tests.postgres_db import new_database_url


def _snapshot(db):
    return {
        model.__tablename__: {
            tuple(row)
            for row in db.execute(select(model.__table__).order_by(*model.__table__.primary_key))
        }
        for model in (Course, User, CourseMember, Group, GroupMember)
    }


@pytest.mark.parametrize("conflict_name", [None, "No Group", "no group", "NO GROUP"])
def test_migration_preserves_rows_skips_collisions_and_backfills_only_active_students(
    conflict_name, caplog
):
    database = Database(new_database_url(schema=False))
    database.initialize_schema()
    command.stamp(database._alembic_config(), "0092_repair_feedback_v2")
    third, missing = str(uuid4()), str(uuid4())
    now = datetime.now(UTC)
    course_ids = (COURSE_ID, SECOND_CLASS_ID, third, missing)
    legacy = {COURSE_ID: GROUP_DEMO_ID, SECOND_CLASS_ID: SECOND_CLASS_GROUP_ID, third: str(uuid4())}
    defaults = dict(legacy)
    defaults[missing] = seed_uuid(f"class-students-{missing}")
    student_ids = {}
    with database.session() as db:
        for index, course_id in enumerate(course_ids):
            db.add(
                Course(
                    id=course_id, code=f"class-{uuid4().hex}", name=f"Class {index}", created_at=now
                )
            )
        db.flush()
        for course_id, group_id in legacy.items():
            db.add(
                Group(
                    id=group_id,
                    course_id=course_id,
                    name="Demo Group" if course_id == COURSE_ID else "Students",
                    created_at=now,
                )
            )
            if conflict_name:
                defaults[course_id] = str(uuid4())
                db.add(
                    Group(
                        id=defaults[course_id],
                        course_id=course_id,
                        name=conflict_name,
                        created_at=now,
                    )
                )
        # Copy-like cohort sizes, including ordinary groups that must stay untouched.
        for course_id, count in ((COURSE_ID, 21), (SECOND_CLASS_ID, 11), (third, 0), (missing, 1)):
            for number in range(count):
                db.add(
                    Group(
                        id=str(uuid4()), course_id=course_id, name=f"Team {number}", created_at=now
                    )
                )
        for course_id in course_ids:
            for role, status, suffix in (
                ("student", "active", "active"),
                ("student", "inactive", "inactive"),
                ("teacher", "active", "teacher"),
                ("student", "active", "grouped"),
            ):
                user_id = str(uuid4())
                student_ids[course_id, suffix] = user_id
                db.add(
                    User(
                        id=user_id,
                        username=f"user{uuid4().hex}",
                        display_name=suffix,
                        status=status,
                        created_at=now,
                    )
                )
                db.flush()
                db.add(
                    CourseMember(course_id=course_id, user_id=user_id, role=role, created_at=now)
                )
        db.flush()
        for course_id in course_ids:
            ordinary = db.scalar(
                select(Group)
                .where(Group.course_id == course_id, Group.name.like("Team %"))
                .order_by(Group.name)
            )
            if ordinary is not None:
                db.add(
                    GroupMember(
                        group_id=ordinary.id,
                        user_id=student_ids[course_id, "grouped"],
                        role="member",
                        created_at=now,
                    )
                )
            else:
                db.add(
                    GroupMember(
                        group_id=legacy[course_id],
                        user_id=student_ids[course_id, "grouped"],
                        role="member",
                        created_at=now,
                    )
                )
        # A membership in another course must not count as membership in this one.
        db.flush()
        db.add(
            GroupMember(
                group_id=legacy[COURSE_ID],
                user_id=student_ids[missing, "active"],
                role="leader",
                created_at=now,
            )
        )
        db.flush()
        before = _snapshot(db)
    migration = importlib.import_module("migrations.versions.0093_rename_default_group_to_no_group")
    logging.getLogger().addHandler(caplog.handler)
    with database.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with database.session() as db:
        after = _snapshot(db)
        for table in ("courses", "users", "course_members", "group_members"):
            assert before[table] <= after[table]
        assert {row[0] for row in before["groups"]} <= {row[0] for row in after["groups"]}
        for course_id in course_ids:
            default = db.get(Group, defaults[course_id])
            assert default.name_key == "no group"
            assert default.name == (
                conflict_name if conflict_name and course_id != missing else DEFAULT_GROUP_NAME
            )
            assert db.get(GroupMember, (default.id, student_ids[course_id, "active"])) is not None
            assert db.get(GroupMember, (default.id, student_ids[course_id, "inactive"])) is None
            assert db.get(GroupMember, (default.id, student_ids[course_id, "teacher"])) is None
            if course_id != third or conflict_name:
                assert db.get(GroupMember, (default.id, student_ids[course_id, "grouped"])) is None
        for course_id, group_id in legacy.items():
            assert db.get(Group, group_id).name == (
                ("Demo Group" if course_id == COURSE_ID else "Students")
                if conflict_name
                else DEFAULT_GROUP_NAME
            )
        assert (
            db.get(GroupMember, (legacy[COURSE_ID], student_ids[missing, "active"])).role
            == "leader"
        )
    with database.engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
    with database.session() as db:
        assert _snapshot(db) == after
    command.upgrade(database._alembic_config(), "head")
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ALEMBIC_HEAD
    if conflict_name:
        assert "default_group_rename_conflict_skipped count=3" in caplog.text
    database.dispose()


@pytest.mark.parametrize("student_status", ["active", "inactive"])
def test_reserved_name_resolves_only_protected_default_and_repairs_missing_memberships(
    postgres_url,
    student_status,
):
    database = Database(postgres_url)
    now = datetime.now(UTC)
    course_id, student_id, teacher_id = str(uuid4()), str(uuid4()), str(uuid4())
    with database.session() as db:
        db.add(
            Course(id=course_id, code=f"class-{uuid4().hex}", name="Empty class", created_at=now)
        )
        for user_id in (student_id, teacher_id):
            db.add(
                User(
                    id=user_id,
                    username=f"u{uuid4().hex}",
                    display_name="Person",
                    status=student_status if user_id == student_id else "active",
                    created_at=now,
                )
            )
        db.flush()
        for user_id, role in ((student_id, "student"), (teacher_id, "teacher")):
            db.add(CourseMember(course_id=course_id, user_id=user_id, role=role, created_at=now))
        for spelling in ("no group", " No   Group ", "Ｎｏ Ｇｒｏｕｐ"):
            group = resolve_named_group(db, course_id, spelling)
            assert group.id == seed_uuid(f"class-students-{course_id}")
            assert group.name == DEFAULT_GROUP_NAME
        ensure_student_group(db, course_id, student_id)
        ensure_student_group(db, course_id, student_id)
        ensure_student_group(db, course_id, teacher_id)
        assert (db.get(GroupMember, (group.id, student_id)) is not None) is (
            student_status == "active"
        )
        assert db.get(GroupMember, (group.id, teacher_id)) is None
        assert db.scalars(select(Group).where(Group.course_id == course_id)).all() == [group]
    database.dispose()


def test_seed_survives_rename_collision_without_altering_legacy_cohort(postgres_url):
    database = Database(postgres_url)
    with database.session() as db:
        seed_demo_data(db)
        db.flush()
        db.get(Group, GROUP_DEMO_ID).name = "Demo Group"
        db.flush()
        other = Group(
            id=str(uuid4()), course_id=COURSE_ID, name="no group", created_at=datetime.now(UTC)
        )
        db.add(other)
        db.flush()
        seed_demo_data(db)
        assert default_class_group(db, COURSE_ID).id == other.id
        assert db.get(Group, GROUP_DEMO_ID).name == "Demo Group"
    database.dispose()
