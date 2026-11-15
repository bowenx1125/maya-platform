"""Class provisioning on the existing course and membership tables."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import case, delete, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, forbidden, unprocessable
from app.core.identity import normalize_group_name
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.core.sqlutil import begin_immediate
from app.seed import BOWEN_ID, COURSE_ID, COURSE_NAME, GROUP_DEMO_ID, seed_uuid

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
            name="Students",
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
    if db.get(Group, SECOND_CLASS_GROUP_ID) is None:
        db.add(
            Group(
                id=SECOND_CLASS_GROUP_ID, course_id=SECOND_CLASS_ID, name="Students", created_at=now
            )
        )
    db.flush()


def default_class_group(db: Session, course_id: str) -> Group:
    preferred = (
        GROUP_DEMO_ID
        if course_id == COURSE_ID
        else SECOND_CLASS_GROUP_ID
        if course_id == SECOND_CLASS_ID
        else seed_uuid(f"class-students-{course_id}")
    )
    group = db.scalar(select(Group).where(Group.id == preferred, Group.course_id == course_id))
    if group is None:
        group = db.scalar(select(Group).where(Group.course_id == course_id).order_by(Group.id))
    if group is None:
        raise unprocessable("registration_unavailable", "This class is not accepting students.")
    return group


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
    if user.id == BOWEN_ID:
        from app.modules.auth.identity_choice import enter_student_class

        enter_student_class(db, user, course.id, datetime.now(UTC))
        return
    if len(memberships) == 1 and memberships[0].course_id == course.id:
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
