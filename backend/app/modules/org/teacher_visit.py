"""Temporary membership a course teacher holds while inside one group.

The row is the teacher themselves, not a second account and not a student
roster member. It expires, and a repeat enter refreshes the same row instead
of inserting another. Content edits consult ``teacher_may_edit_group_content``;
the SQL view used for reads excludes an expired or inactive row even before
the sweeper deletes it.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from app.core.models import (
    TEACHER_GROUP_VISIT_TTL,
    CourseMember,
    Group,
    TeacherGroupAccess,
    User,
)
from app.core.sqlutil import dialect_insert


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def purge_expired_teacher_visits(db: Session, *, now: datetime | None = None) -> int:
    """Delete visits whose window has closed. Returns how many rows went."""

    moment = now or datetime.now(UTC)
    # A statement, not ORM deletes: those wait for the commit flush, which
    # runs after grant_teacher_visit's upsert has already renewed the same
    # row, and so deleted the visit a re-entering teacher had just been given.
    result = db.execute(
        delete(TeacherGroupAccess).where(TeacherGroupAccess.expires_at <= moment)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def grant_teacher_visit(
    db: Session,
    *,
    group_id: str,
    user_id: str,
    now: datetime | None = None,
) -> None:
    """Insert the teacher's visit, or refresh the one row they already hold."""

    moment = now or datetime.now(UTC)
    expires_at = moment + TEACHER_GROUP_VISIT_TTL
    db.execute(
        dialect_insert(db, TeacherGroupAccess)
        .values(
            group_id=group_id,
            user_id=user_id,
            created_at=moment,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=["group_id", "user_id"],
            set_={"expires_at": expires_at},
        )
    )


def prefetch_teacher_visit_edits(db: Session, *, user_id: str, group_ids: Collection[str]) -> None:
    """One IN query covering ``teacher_may_edit_group_content`` for ``group_ids``.

    List routes call this before per-Agent helpers so visit ACL does not add
    one SELECT per row. Every requested key is stored (False when absent).
    """

    from app.core.prefetch import store

    if not group_ids:
        return
    flags: dict[tuple[str, str], bool] = dict.fromkeys(
        ((user_id, group_id) for group_id in group_ids), False
    )
    now = datetime.now(UTC)
    for group_id, expires_at in db.execute(
        select(TeacherGroupAccess.group_id, TeacherGroupAccess.expires_at)
        .join(Group, Group.id == TeacherGroupAccess.group_id)
        .join(
            CourseMember,
            and_(
                CourseMember.course_id == Group.course_id,
                CourseMember.user_id == TeacherGroupAccess.user_id,
            ),
        )
        .join(User, User.id == TeacherGroupAccess.user_id)
        .where(
            TeacherGroupAccess.group_id.in_(group_ids),
            TeacherGroupAccess.user_id == user_id,
            CourseMember.role == "teacher",
            User.status == "active",
        )
    ).all():
        flags[(user_id, group_id)] = expires_at is not None and _as_utc(expires_at) > now
    store(db, "teacher_may_edit_group", flags)


def teacher_may_edit_group_content(db: Session, user_id: str, group_id: str) -> bool:
    """True only for an active teacher of this group's course, during a live visit.

    An expired row, a teacher of another course, a student, or a deactivated
    account is not a grant. The check does not extend the window.
    """

    from app.core.prefetch import prefetched

    return prefetched(
        db,
        "teacher_may_edit_group",
        (user_id, group_id),
        lambda: _teacher_may_edit_group_content_uncached(db, user_id, group_id),
    )


def _teacher_may_edit_group_content_uncached(db: Session, user_id: str, group_id: str) -> bool:
    expires_at = db.scalar(
        select(TeacherGroupAccess.expires_at)
        .join(Group, Group.id == TeacherGroupAccess.group_id)
        .join(
            CourseMember,
            and_(
                CourseMember.course_id == Group.course_id,
                CourseMember.user_id == TeacherGroupAccess.user_id,
            ),
        )
        .join(User, User.id == TeacherGroupAccess.user_id)
        .where(
            TeacherGroupAccess.group_id == group_id,
            TeacherGroupAccess.user_id == user_id,
            CourseMember.role == "teacher",
            User.status == "active",
        )
    )
    if expires_at is None:
        return False
    return _as_utc(expires_at) > datetime.now(UTC)
