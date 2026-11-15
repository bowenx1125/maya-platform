"""Class provisioning on the existing course and membership tables."""

import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import case, delete, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, unprocessable
from app.core.group_names import DEFAULT_GROUP_NAME
from app.core.identity import group_name_key, normalize_group_name
from app.core.locks import xact_lock
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.core.sqlutil import begin_immediate, dialect_insert
from app.seed import COURSE_ID, COURSE_NAME, GROUP_DEMO_ID, seed_uuid

logger = logging.getLogger(__name__)

# These keys are persisted identities from the first rollout.
SECOND_CLASS_ID = seed_uuid("class-maya1002")
SECOND_CLASS_GROUP_ID = seed_uuid("class-maya1002-students")
SECOND_CLASS_NAME = "Maya1001"
CLASS_TEACHER_COURSE_IDS = {
    COURSE_NAME.casefold(): COURSE_ID,
    SECOND_CLASS_NAME.casefold(): SECOND_CLASS_ID,
}


def registration_classes(db: Session) -> list[Course]:
    # Course rows can also belong to unrelated organization scopes. Only
    # provisioned class codes with a student group are public enrolment choices.
    courses = db.scalars(
        select(Course)
        .where(select(Group.id).where(Group.course_id == Course.id).exists())
        .order_by(
            case((Course.id == COURSE_ID, 0), (Course.id == SECOND_CLASS_ID, 1), else_=2),
            Course.created_at,
            Course.code,
        )
    ).all()
    return [
        item
        for item in courses
        if item.id == COURSE_ID or re.fullmatch(r"maya\d+|class-[0-9a-f]{32}", item.code.casefold())
    ]


def create_class(db: Session, user: User, name: str) -> Course:
    classes = registration_classes(db)
    if (
        db.scalar(
            select(CourseMember.user_id)
            .where(
                CourseMember.user_id == user.id,
                CourseMember.role == "teacher",
                CourseMember.course_id.in_([item.id for item in classes]),
            )
            .limit(1)
        )
        is None
    ):
        raise forbidden()
    try:
        normalized = normalize_group_name(name)
    except ValueError as error:
        raise unprocessable("class_name_invalid", str(error)) from None
    begin_immediate(db, lock_key="maya-class-creation")
    if any(
        normalize_group_name(item.name).casefold() == normalized.casefold()
        for item in registration_classes(db)
    ):
        raise conflict("class_name_taken", "A class already uses that name.")
    now = datetime.now(UTC)
    course = Course(id=str(uuid4()), code=f"class-{uuid4().hex}", name=normalized, created_at=now)
    db.add(course)
    db.flush()
    db.add(
        Group(
            id=seed_uuid(f"class-students-{course.id}"),
            course_id=course.id,
            name=DEFAULT_GROUP_NAME,
            created_at=now,
        )
    )
    teachers = {user.id}
    teachers.update(
        db.scalars(
            select(User.id)
            .join(CourseMember, CourseMember.user_id == User.id)
            .where(
                User.username_key == "maya",
                User.status == "active",
                CourseMember.role == "teacher",
                CourseMember.course_id.in_([item.id for item in classes]),
            )
        ).all()
    )
    for teacher_id in teachers:
        db.add(
            CourseMember(course_id=course.id, user_id=teacher_id, role="teacher", created_at=now)
        )
    db.flush()
    return course


def ensure_classes(db: Session) -> None:
    # Keep the first course's identity: existing resources and registered
    # students already refer to it and must not be copied or reassigned.
    first = db.get(Course, COURSE_ID)
    if first is None:
        raise RuntimeError("Class provisioning requires the original course")
    first.name = COURSE_NAME
    now = datetime.now(UTC)
    second = db.get(Course, SECOND_CLASS_ID)
    if second is None:
        db.add(Course(id=SECOND_CLASS_ID, code="maya1002", name=SECOND_CLASS_NAME, created_at=now))
        db.flush()
    else:
        second.name = SECOND_CLASS_NAME
    default_class_group(db, SECOND_CLASS_ID)
    db.flush()


def default_class_group(db: Session, course_id: str) -> Group:
    xact_lock(db, f"course-groups:{course_id}")
    key = group_name_key(DEFAULT_GROUP_NAME)
    group = db.scalar(select(Group).where(Group.course_id == course_id, Group.name_key == key))
    if group is not None:
        return group
    preferred = (
        GROUP_DEMO_ID
        if course_id == COURSE_ID
        else SECOND_CLASS_GROUP_ID
        if course_id == SECOND_CLASS_ID
        else seed_uuid(f"class-students-{course_id}")
    )
    db.execute(
        dialect_insert(db, Group)
        .values(
            id=preferred,
            course_id=course_id,
            name=DEFAULT_GROUP_NAME,
            name_key=key,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing()
    )
    group = db.scalar(select(Group).where(Group.course_id == course_id, Group.name_key == key))
    if group is None:
        logger.error("default_group_conflict")
        raise conflict("default_group_conflict", "The class default group is unavailable.")
    return group


def ensure_student_group(db: Session, course_id: str, user_id: str) -> None:
    # Course membership alone never grants a student a usable workspace.
    db.flush()
    membership = db.get(CourseMember, (course_id, user_id))
    user = db.get(User, user_id)
    if (
        membership is None
        or membership.role != "student"
        or user is None
        or user.status != "active"
    ):
        return
    xact_lock(db, f"course-groups:{course_id}")
    grouped = db.scalar(
        select(GroupMember.group_id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.course_id == course_id, GroupMember.user_id == user_id)
        .limit(1)
    )
    if grouped is None:
        group = default_class_group(db, course_id)
        db.add(
            GroupMember(
                group_id=group.id, user_id=user_id, role="member", created_at=datetime.now(UTC)
            )
        )
        db.flush()


def change_class(db: Session, user: User, course_id: str) -> None:
    from app.modules.auth.service import lock_user_profile

    lock_user_profile(db, user.id)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    memberships = db.scalars(
        select(CourseMember).where(CourseMember.user_id == user.id).with_for_update()
    ).all()
    if not memberships or any(row.role != "student" for row in memberships):
        raise conflict("class_change_forbidden", "Only students can change their class.")
    course = next((item for item in registration_classes(db) if item.id == course_id), None)
    if course is None:
        raise unprocessable("class_not_found", "Choose an available class.")
    if len(memberships) == 1 and memberships[0].course_id == course.id:
        ensure_student_group(db, course.id, user.id)
        return
    group = default_class_group(db, course.id)
    from app.modules.auth.models import DemoAccountBinding

    binding = db.scalar(select(DemoAccountBinding).where(DemoAccountBinding.user_id == user.id))
    if binding is not None:
        binding.selected_group_id = group.id
    old_course_ids = [row.course_id for row in memberships]
    db.execute(
        delete(GroupMember).where(
            GroupMember.user_id == user.id,
            GroupMember.group_id.in_(select(Group.id).where(Group.course_id.in_(old_course_ids))),
        )
    )
    for membership in memberships:
        db.delete(membership)
    db.flush()
    now = datetime.now(UTC)
    db.add(CourseMember(course_id=course.id, user_id=user.id, role="student", created_at=now))
    db.add(GroupMember(group_id=group.id, user_id=user.id, role="member", created_at=now))
    db.flush()
