"""Database-backed, single-use entry choices for the fixed Bowen identity."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.core.errors import PlatformError
from app.core.models import Course, CourseMember, GroupMember, User
from app.modules.auth.models import LoginIdentityChallenge
from app.modules.auth.schemas import (
    LoginIdentityChoice,
    LoginIdentityChoiceRequest,
    LoginIdentityClass,
    LoginIdentityOptions,
)
from app.modules.auth.service import lock_user_profile, new_raw_session_token, session_hash
from app.modules.org.classes import SECOND_CLASS_ID, default_class_group
from app.seed import BOWEN_ID, COURSE_ID, TEACHER_ID

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
        membership = db.get(CourseMember, (course_id, BOWEN_ID))
        if membership is not None and membership.role != "student":
            raise PlatformError("identity_choice_unavailable", "Login choice is unavailable.", 401)
        group = default_class_group(db, course_id)
        if membership is None:
            db.add(
                CourseMember(
                    course_id=course_id, user_id=BOWEN_ID, role="student", created_at=timestamp
                )
            )
        if db.get(GroupMember, (group.id, BOWEN_ID)) is None:
            db.add(
                GroupMember(
                    group_id=group.id, user_id=BOWEN_ID, role="member", created_at=timestamp
                )
            )
        db.flush()
    return user
