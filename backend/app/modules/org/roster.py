"""Teacher-owned roster reads and account edits for one course.

Three account sources coexist behind a single roster.  Only one of them is
editable, and the difference is not cosmetic:

``catalog``
    The fixed Demo identities.  Their name and status are projections of
    ``accounts.private.md``, which is mounted read-only and re-applied on
    every start, so an edit here would silently disappear at the next
    restart.

``database``
    Self-registered students.  Their credential lives in ``user_credentials``
    and nothing rewrites it behind the teacher's back, so this is the only
    source an edit can durably change.

Rather than accept an edit and lose it, the service rejects the write and
names the source.  The validation mirrors ``auth.registration`` deliberately:
the rules are the same, but the failures carry a roster-specific code so a
form can tell a rejected edit from a rejected registration.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found, unprocessable
from app.core.models import CourseMember, Group, GroupMember, User
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.service import revoke_user_sessions

ACTIVE = "active"
INACTIVE = "inactive"
ASSIGNABLE_STATUSES = frozenset({ACTIVE, INACTIVE})

SOURCE_CATALOG = "catalog"
SOURCE_DATABASE = "database"

DISPLAY_NAME_MAX = 200
GROUP_NAME_MAX = 200


@dataclass(frozen=True)
class RosterRow:
    """One course member with the account facts a teacher acts on."""

    user: User
    role: str
    source: str
    groups: list[Group]

    @property
    def editable(self) -> bool:
        return self.source == SOURCE_DATABASE


def _invalid(message: str) -> PlatformError:
    """Return the stable domain code for a rejected roster edit."""

    return unprocessable("member_update_invalid", message)


def _collapsed(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw).split())


def normalize_display_name(raw: str) -> str:
    value = _collapsed(raw)
    if not value:
        raise _invalid("A display name is required.")
    if len(value) > DISPLAY_NAME_MAX:
        raise _invalid(f"A display name may not exceed {DISPLAY_NAME_MAX} characters.")
    return value


def normalize_group_name(raw: str) -> str:
    value = _collapsed(raw)
    if not value:
        raise _invalid("A group name is required.")
    if len(value) > GROUP_NAME_MAX:
        raise _invalid(f"A group name may not exceed {GROUP_NAME_MAX} characters.")
    if any(ord(character) < 0x20 for character in value):
        raise _invalid("A group name may not contain control characters.")
    return value


def normalize_status(raw: str) -> str:
    value = raw.strip().casefold()
    if value not in ASSIGNABLE_STATUSES:
        raise _invalid("A status must be either 'active' or 'inactive'.")
    return value


def _account_source(user: User, catalog_user_ids: frozenset[str]) -> str:
    if user.id in catalog_user_ids:
        return SOURCE_CATALOG
    return SOURCE_DATABASE


def _catalog_user_ids(db: Session) -> frozenset[str]:
    return frozenset(
        db.scalars(
            select(DemoAccountBinding.user_id).where(DemoAccountBinding.active.is_(True))
        ).all()
    )


def _groups_by_user(db: Session, course_id: str) -> dict[str, list[Group]]:
    rows = db.execute(
        select(GroupMember.user_id, Group)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.course_id == course_id)
        .order_by(Group.name)
    ).all()
    grouped: dict[str, list[Group]] = {}
    for user_id, group in rows:
        grouped.setdefault(user_id, []).append(group)
    return grouped


def course_roster(db: Session, course_id: str) -> list[RosterRow]:
    """Return every member of the course with source and group attribution."""

    catalog_user_ids = _catalog_user_ids(db)
    grouped = _groups_by_user(db, course_id)
    rows = db.execute(
        select(User, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id)
        .order_by(CourseMember.role, User.display_name, User.id)
    ).all()
    return [
        RosterRow(
            user=user,
            role=role,
            source=_account_source(user, catalog_user_ids),
            groups=grouped.get(user.id, []),
        )
        for user, role in rows
    ]


def _roster_row(db: Session, course_id: str, user_id: str) -> RosterRow:
    row = db.execute(
        select(User, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id, User.id == user_id)
    ).first()
    if row is None:
        # A member of another course must be indistinguishable from one that
        # does not exist.
        raise not_found()
    user, role = row
    return RosterRow(
        user=user,
        role=role,
        source=_account_source(user, _catalog_user_ids(db)),
        groups=_groups_by_user(db, course_id).get(user.id, []),
    )


def _move_to_group(db: Session, course_id: str, user: User, group_name: str) -> None:
    """Make ``group_name`` the member's only group in this course.

    The name is the address, exactly as it is during registration: the first
    use of a name creates the group and every later use joins that row, so a
    teacher moving a student into "Team Aurora" lands them beside the
    students who typed the same name themselves.
    """

    now = datetime.now(UTC)
    group = db.scalar(
        select(Group).where(
            Group.course_id == course_id,
            func.lower(Group.name) == group_name.casefold(),
        )
    )
    if group is None:
        group = Group(id=str(uuid4()), course_id=course_id, name=group_name, created_at=now)
        db.add(group)
        db.flush()
    current = db.scalars(
        select(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.course_id == course_id, GroupMember.user_id == user.id)
    ).all()
    for membership in current:
        if membership.group_id != group.id:
            db.delete(membership)
    if not any(membership.group_id == group.id for membership in current):
        db.add(
            GroupMember(
                group_id=group.id,
                user_id=user.id,
                role="member",
                created_at=now,
            )
        )
    db.flush()


def update_member(
    db: Session,
    *,
    course_id: str,
    actor: User,
    user_id: str,
    display_name: str | None = None,
    group_name: str | None = None,
    status: str | None = None,
) -> RosterRow:
    """Apply a teacher's edit to one member of their course."""

    if display_name is None and group_name is None and status is None:
        raise _invalid("An edit must change at least one field.")

    row = _roster_row(db, course_id, user_id)
    if status is not None and row.user.id == actor.id:
        # Checked before the source rule so the answer names the reason that
        # holds for every teacher: losing your own session to a mis-click is
        # not recoverable from inside the product.  Today's teachers are all
        # catalog accounts, so the other order would leave this unreachable.
        raise conflict("self_status_forbidden", "You cannot change your own account status.")
    if not row.editable:
        raise conflict(
            "account_read_only",
            "This account is provisioned at startup and cannot be edited here.",
            {"source": row.source},
        )

    if display_name is not None:
        row.user.display_name = normalize_display_name(display_name)
    if status is not None:
        resolved = normalize_status(status)
        row.user.status = resolved
        if resolved == INACTIVE:
            # Deactivation has to end sessions that already exist; the auth
            # context rejects a non-active user, but the row stays until it
            # is revoked.
            revoke_user_sessions(db, row.user.id, datetime.now(UTC))
    if group_name is not None:
        _move_to_group(db, course_id, row.user, normalize_group_name(group_name))

    db.flush()
    return _roster_row(db, course_id, user_id)
