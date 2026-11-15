"""Database-backed, single-use entry choices for the fixed Bowen identity."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import PlatformError
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.auth.models import DemoAccountBinding, LoginIdentityChallenge
from app.modules.auth.schemas import (
    LoginIdentityChoice,
    LoginIdentityChoiceRequest,
    LoginIdentityClass,
    LoginIdentityOptions,
)
from app.modules.auth.service import lock_user_profile, new_raw_session_token, session_hash
from app.modules.org.classes import SECOND_CLASS_ID, default_class_group
from app.seed import BOWEN_ID, COURSE_ID, GROUP_DEMO_ID, TEACHER_ID

CHOICE_COURSE_IDS = (SECOND_CLASS_ID, COURSE_ID)
CHOICE_TTL_SECONDS = 300


def issue_choice(db: Session, client: str, now: datetime | None = None) -> LoginIdentityChoice:
    timestamp = now or datetime.now(UTC)
    classes = []
    for course_id in CHOICE_COURSE_IDS:
        course = db.get(Course, course_id)
        if course is None:
            raise PlatformError("identity_choice_unavailable", "Login choice is unavailable.", 503)
        classes.append(
            LoginIdentityClass(course_id=UUID(course.id), code=course.code, name=course.name)
        )
    db.execute(
        delete(LoginIdentityChallenge).where(
            LoginIdentityChallenge.expires_at < timestamp - timedelta(days=1)
        )
    )
    raw_token = new_raw_session_token()
    db.add(
        LoginIdentityChallenge(
            token_hash=session_hash(raw_token),
            user_id=BOWEN_ID,
            client_fingerprint_hash=session_hash(client),
            expires_at=timestamp + timedelta(seconds=CHOICE_TTL_SECONDS),
        )
    )
    return LoginIdentityChoice(
        choice_token=raw_token,
        expires_in_seconds=CHOICE_TTL_SECONDS,
        options=LoginIdentityOptions(classes=classes),
    )


def _student_landing_group(db: Session, course_id: str) -> Group | None:
    """Group Bowen joins when he first enters a class as a student.

    Prefer an ordinary cohort when available. The protected No Group shell
    remains the fallback, including for an existing ungrouped course member.
    """

    rows = db.scalars(
        select(Group).where(Group.course_id == course_id).order_by(Group.name, Group.id)
    ).all()
    if course_id == COURSE_ID:
        demo = next((row for row in rows if row.id == GROUP_DEMO_ID), None)
        if demo is not None:
            return demo
    protected = default_class_group(db, course_id).id
    ordinary = [row for row in rows if row.id != protected]
    return ordinary[0] if ordinary else None


def student_landing_group(db: Session, user: User, course_id: str) -> Group | None:
    """Prefer the saved choice, then a non-default existing membership.

    A binding is a preference, never a grant: revoked memberships and the
    separate bowen1 account must not supply a landing group for this user.
    """

    default_id = default_class_group(db, course_id).id
    return db.scalar(
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .outerjoin(
            DemoAccountBinding,
            (DemoAccountBinding.user_id == GroupMember.user_id)
            & DemoAccountBinding.active.is_(True),
        )
        .where(GroupMember.user_id == user.id, Group.course_id == course_id)
        .order_by(
            case((Group.id == DemoAccountBinding.selected_group_id, 0), else_=1),
            case((Group.id == default_id, 1), else_=0),
            Group.id,
        )
        .limit(1)
    )


def enter_student_class(db: Session, user: User, course_id: str, timestamp: datetime) -> None:
    """Bowen enters additively; existing grants, including revocations, stay intact."""

    membership = db.get(CourseMember, (course_id, user.id))
    if membership is not None and membership.role != "student":
        raise PlatformError("identity_choice_unavailable", "Login choice is unavailable.", 401)
    if membership is None:
        db.add(
            CourseMember(course_id=course_id, user_id=user.id, role="student", created_at=timestamp)
        )
        # A revoked or changed grant is left alone: this only runs when he
        # has no course row yet. The No Group shell is not a landing group.
        group = _student_landing_group(db, course_id)
        if group is not None and db.get(GroupMember, (group.id, user.id)) is None:
            db.add(
                GroupMember(group_id=group.id, user_id=user.id, role="member", created_at=timestamp)
            )
    db.flush()


def consume_choice(
    db: Session,
    payload: LoginIdentityChoiceRequest,
    client: str,
    now: datetime | None = None,
) -> User:
    timestamp = now or datetime.now(UTC)
    consumed = db.execute(
        update(LoginIdentityChallenge)
        .where(
            LoginIdentityChallenge.token_hash == session_hash(payload.choice_token),
            LoginIdentityChallenge.user_id == BOWEN_ID,
            LoginIdentityChallenge.client_fingerprint_hash == session_hash(client),
            LoginIdentityChallenge.consumed_at.is_(None),
            LoginIdentityChallenge.expires_at > timestamp,
        )
        .values(consumed_at=timestamp)
        .returning(LoginIdentityChallenge.token_hash)
    ).scalar_one_or_none()
    if consumed is None:
        raise PlatformError("identity_choice_invalid", "Log in again to choose an identity.", 401)
    if (payload.identity == "maya" and "course_id" in payload.model_fields_set) or (
        payload.identity == "student" and str(payload.course_id) not in CHOICE_COURSE_IDS
    ):
        raise PlatformError("identity_choice_course_invalid", "Choose an available class.", 422)

    lock_user_profile(db, BOWEN_ID)
    bowen = db.get(User, BOWEN_ID, populate_existing=True)
    user = db.get(User, TEACHER_ID) if payload.identity == "maya" else bowen
    if bowen is None or bowen.status != "active" or user is None or user.status != "active":
        raise PlatformError("identity_choice_unavailable", "Login choice is unavailable.", 401)
    if payload.identity == "student":
        course_id = str(payload.course_id)
        if db.get(Course, course_id) is None:
            raise PlatformError("identity_choice_course_invalid", "Choose an available class.", 422)
        enter_student_class(db, user, course_id, timestamp)
    return user
