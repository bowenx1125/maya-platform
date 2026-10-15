"""Course and group routes with server-derived scope.

Reads dominate this module. The one mutation is a teacher joining or
leaving a group: a teacher already sees every group in their course, and
joining is what lets them sit inside one as a participant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, status
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.core.errors import Error, forbidden, not_found
from app.core.models import Course, CourseMember, Group, GroupMember, TeacherGroupAccess, User
from app.modules.auth.dependencies import (
    CourseScope,
    get_db,
    require_auth,
    require_authenticated_mutation,
)
from app.modules.auth.service import AuthContext
from app.modules.knowledge.services import course_member_role, observes_group
from app.modules.org.overview import group_overview
from app.modules.org.roster import RosterRow, course_roster, update_member
from app.modules.org.schemas import Course as CourseDTO
from app.modules.org.schemas import (
    CourseDetail,
    CourseRoster,
    GroupDetail,
    GroupOverview,
    GroupRef,
    Member,
    RosterEntry,
    UpdateCourseMemberRequest,
)
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


# A removed account reads as deleted to everyone else in the course: its work
# is kept for a Restore, but it no longer appears as a member anywhere.
def _members_for_course(db: Session, course_id: str) -> list[Member]:
    rows = db.execute(
        select(User.id, User.display_name, User.avatar, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id, User.status == "active")
        .order_by(User.id)
    ).all()
    return [
        Member(
            user_id=UUID(row.id),
            display_name=row.display_name,
            avatar=row.avatar,
            role=row.role,
        )
        for row in rows
    ]


def _members_for_group(db: Session, group_id: str) -> list[Member]:
    rows = db.execute(
        select(User.id, User.display_name, User.avatar, GroupMember.role)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id, User.status == "active")
        .order_by(User.id)
    ).all()
    return [
        Member(
            user_id=UUID(row.id),
            display_name=row.display_name,
            avatar=row.avatar,
            role=row.role,
        )
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


@router.get(
    "/groups/{group_id}/overview",
    response_model=GroupOverview,
    operation_id="getGroupOverview",
    responses={
        200: {"model": GroupOverview, "description": "Members, test results and recent work."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def get_group_overview(
    group_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> GroupOverview:
    """What a group is doing, for a teacher of its course.

    Entering from Accounts is still what shows private Agents, Teams, RAG
    and voices. Formal attempts are included either way.
    """

    group = db.get(Group, str(group_id))
    if (
        group is None
        or context.user.status != "active"
        or course_member_role(db, context.user.id, group.course_id) != "teacher"
    ):
        raise not_found()
    return group_overview(
        db,
        context,
        group,
        include_private=observes_group(db, context.user.id, group.id),
    )


def _teacher_group(db: Session, context: AuthContext, group_id: str) -> Group:
    """Resolve a group the caller teaches, or hide it behind a 404/403."""

    row = db.execute(
        select(Group, CourseMember.role)
        .join(CourseMember, CourseMember.course_id == Group.course_id)
        .where(Group.id == group_id, CourseMember.user_id == context.user.id)
    ).first()
    if row is None:
        raise not_found()
    group, role = row
    if role != "teacher":
        # The group is visible to this student, so 403 rather than 404 is the
        # honest answer: they may read it but may not join it this way.
        raise forbidden()
    assert isinstance(group, Group)
    return group


@router.post(
    "/groups/{group_id}/membership",
    response_model=GroupDetail,
    operation_id="joinGroupAsTeacher",
    responses={
        200: {"model": GroupDetail, "description": "The group after the caller joined it."},
        403: {"model": Error, "description": "CSRF failure or the caller is not a teacher."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def join_group(
    group_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> GroupDetail:
    """Join a group in a course the caller teaches.

    Access belongs to the teacher identity and survives catalog synchronization.
    Joining is idempotent and does not add the teacher to the student roster.
    """

    group = _teacher_group(db, context, str(group_id))
    db.execute(
        insert(TeacherGroupAccess)
        .values(group_id=group.id, user_id=context.user.id, created_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["group_id", "user_id"])
    )
    dto = _group_dto(group)
    return GroupDetail(**dto.model_dump(), members=_members_for_group(db, group.id))


@router.delete(
    "/groups/{group_id}/membership",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="leaveGroupAsTeacher",
    responses={
        204: {"description": "The caller is no longer a member of this group."},
        403: {"model": Error, "description": "CSRF failure or the caller is not a teacher."},
        404: {"model": Error, "description": "Group not found."},
    },
)
def leave_group(
    group_id: UUID,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> None:
    """Leave a group the caller teaches. Leaving is idempotent."""

    group = _teacher_group(db, context, str(group_id))
    membership = db.scalar(
        select(TeacherGroupAccess).where(
            TeacherGroupAccess.group_id == group.id,
            TeacherGroupAccess.user_id == context.user.id,
        )
    )
    if membership is not None:
        db.delete(membership)


def _roster_entry(row: RosterRow) -> RosterEntry:
    return RosterEntry(
        user_id=UUID(row.user.id),
        username=row.user.username,
        display_name=row.user.display_name,
        avatar=row.user.avatar,
        role=row.role,
        status=row.user.status,
        source=row.source,
        editable=row.editable,
        groups=[GroupRef(id=UUID(group.id), name=group.name) for group in row.groups],
    )


def _teaching_scope(db: Session, context: AuthContext, course_id: str) -> CourseScope:
    """Resolve a course the caller teaches, hiding others behind a 404."""

    _course, scope = _visible_course(db, context, course_id)
    if scope.role != "teacher":
        # The course is visible to this student, so 403 is the honest answer:
        # they may read it but the roster is not theirs to see or change.
        raise forbidden()
    return scope


@router.get(
    "/courses/{course_id}/roster",
    response_model=CourseRoster,
    operation_id="getCourseRoster",
    responses={
        200: {"model": CourseRoster, "description": "Members with account source and groups."},
        403: {"model": Error, "description": "The caller does not teach this course."},
        404: {"model": Error, "description": "Course not found."},
    },
)
def get_course_roster(
    course_id: UUID,
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CourseRoster:
    """List every member of a course the caller teaches.

    This is the read behind account management, so it carries what an edit
    depends on: the username, the current status and which source provisions
    the account.
    """

    _teaching_scope(db, context, str(course_id))
    return CourseRoster(
        course_id=course_id,
        entries=[_roster_entry(row) for row in course_roster(db, str(course_id))],
    )


@router.patch(
    "/courses/{course_id}/members/{user_id}",
    response_model=RosterEntry,
    operation_id="updateCourseMember",
    responses={
        200: {"model": RosterEntry, "description": "The member after the edit."},
        403: {"model": Error, "description": "CSRF failure or the caller is not the teacher."},
        404: {"model": Error, "description": "The course or member is not visible."},
        409: {"model": Error, "description": "The account is read-only or the target is self."},
        422: {"model": Error, "description": "Invalid display name, group name or status."},
    },
)
def update_course_member(
    course_id: UUID,
    user_id: UUID,
    payload: UpdateCourseMemberRequest = Body(...),
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> RosterEntry:
    """Rename a member, move them between groups or deactivate the account.

    Only self-registered accounts are editable. Catalog identities
    are re-applied from their source on every start,
    so an edit is refused rather than accepted and lost.
    """

    _teaching_scope(db, context, str(course_id))
    row = update_member(
        db,
        course_id=str(course_id),
        actor=context.user,
        user_id=str(user_id),
        display_name=payload.display_name,
        group_name=payload.group_name,
        status=payload.status,
    )
    return _roster_entry(row)
