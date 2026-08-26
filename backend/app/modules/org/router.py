"""Course and group read routes with server-derived scope."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Error, not_found
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.auth.dependencies import CourseScope, get_db, require_auth
from app.modules.auth.service import AuthContext
from app.modules.org.schemas import Course as CourseDTO
from app.modules.org.schemas import CourseDetail, GroupDetail, Member
from app.modules.org.schemas import Group as GroupDTO

router = APIRouter(tags=["Organization"])


def _course_dto(course: Course) -> CourseDTO:
    return CourseDTO(
        id=UUID(course.id),
        code=course.code,
        name=course.name,
        current_audio_debate_id=(
            UUID(course.current_audio_debate_id) if course.current_audio_debate_id else None
        ),
    )


def _group_dto(group: Group) -> GroupDTO:
    return GroupDTO(id=UUID(group.id), course_id=UUID(group.course_id), name=group.name)


def _members_for_course(db: Session, course_id: str) -> list[Member]:
    rows = db.execute(
        select(User.id, User.display_name, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id)
        .order_by(User.id)
    ).all()
    return [
        Member(user_id=UUID(row.id), display_name=row.display_name, role=row.role)
        for row in rows
    ]


def _members_for_group(db: Session, group_id: str) -> list[Member]:
    rows = db.execute(
        select(User.id, User.display_name, GroupMember.role)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.id)
    ).all()
    return [
        Member(user_id=UUID(row.id), display_name=row.display_name, role=row.role)
        for row in rows
    ]


def _visible_course(
    db: Session,
    context: AuthContext,
    course_id: str,
) -> tuple[Course, CourseScope]:
    # Scope and object are resolved in one query.  Do not load by global ID
    # first: an unauthorized ID must be indistinguishable from a missing one.
    row = db.execute(
        select(Course, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Course.id)
        .where(Course.id == course_id, CourseMember.user_id == context.user.id)
    ).first()
    if row is None:
        raise not_found()
    course, role = row
    return course, CourseScope(course_id, role)


def _visible_group(
    db: Session,
    context: AuthContext,
    group_id: str,
) -> tuple[Group, CourseScope]:
    # The course membership and (for students) group membership are part of
    # the same SELECT as the target object.  This is the tenant boundary, not
    # a post-load check.
    row = db.execute(
        select(Group, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .outerjoin(
            GroupMember,
            and_(
                GroupMember.group_id == Group.id,
                GroupMember.user_id == context.user.id,
            ),
        )
        .where(
            Group.id == group_id,
            CourseMember.user_id == context.user.id,
            or_(CourseMember.role == "teacher", GroupMember.user_id.is_not(None)),
        )
    ).first()
    if row is None:
        raise not_found()
    group, role = row
    return group, CourseScope(group.course_id, role)


@router.get(
    "/courses",
    response_model=list[CourseDTO],
    operation_id="listCourses",
    responses={200: {"model": list[CourseDTO], "description": "Courses visible to current user."}},
)
def list_courses(
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[CourseDTO]:
    courses = db.scalars(
        select(Course)
        .join(CourseMember, CourseMember.course_id == Course.id)
        .where(CourseMember.user_id == context.user.id)
        .order_by(Course.code)
    ).all()
    return [_course_dto(course) for course in courses]


@router.get(
    "/courses/{course_id}",
    response_model=CourseDetail,
    operation_id="getCourse",
    responses={
        200: {"model": CourseDetail, "description": "Course detail and read-only members."},
        404: {"model": Error, "description": "Course not found."},
    },
)
def get_course(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CourseDetail:
    course, _scope = _visible_course(db, context, str(course_id))
    dto = _course_dto(course)
    return CourseDetail(**dto.model_dump(), members=_members_for_course(db, course.id))


@router.get(
    "/courses/{course_id}/groups",
    response_model=list[GroupDTO],
    operation_id="listCourseGroups",
    responses={
        200: {"model": list[GroupDTO], "description": "Seeded groups visible in this course."},
        404: {"model": Error, "description": "Course not found."},
    },
)
def list_course_groups(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[GroupDTO]:
    _course, scope = _visible_course(db, context, str(course_id))
    query = select(Group).where(Group.course_id == str(course_id))
    if scope.role != "teacher":
        query = query.join(GroupMember, GroupMember.group_id == Group.id).where(
            GroupMember.user_id == context.user.id
        )
    groups = db.scalars(query.order_by(Group.name)).all()
    return [_group_dto(group) for group in groups]


@router.get(
    "/groups/{group_id}",
    response_model=GroupDetail,
    operation_id="getGroup",
    responses={
        200: {"model": GroupDetail, "description": "Group and read-only members."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def get_group(
    group_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> GroupDetail:
    group, _scope = _visible_group(db, context, str(group_id))
    dto = _group_dto(group)
    return GroupDetail(**dto.model_dump(), members=_members_for_group(db, group.id))
