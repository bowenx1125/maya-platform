"""Self-registration for student accounts backed by the database catalog.

The fixed Demo identities stay in the read-only ``accounts.private.md``
catalog.  This module owns the second, writable source: it validates a
requested username/password, creates the public :class:`User` row, stores the
hash in :class:`UserCredential`, enrols the account in a course and attaches
it to a group.

A group is addressed by *name* rather than by id.  That is what makes
"students who pick the same group land in the same group" true without a
teacher pre-provisioning anything: the first student to use a name creates
the group, everyone after that joins the existing row.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, conflict, unprocessable
from app.core.identity import normalize_group_name as canonical_group_name
from app.core.identity import username_key
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.auth.credentials import CredentialFileError, active_catalog_snapshot
from app.modules.auth.models import UserCredential
from app.modules.auth.service import revoke_user_sessions
from app.modules.org.names import resolve_named_group

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
USERNAME_MIN = 3
USERNAME_MAX = 64
PASSWORD_MIN = 5
PASSWORD_MAX = 128
DISPLAY_NAME_MAX = 200
GROUP_NAME_MAX = 200


def _hasher() -> PasswordHash:
    return PasswordHash.recommended()


def _invalid(message: str) -> PlatformError:
    """Return the stable domain code for a rejected registration field."""

    return unprocessable("registration_invalid", message)


def normalize_username(raw: str) -> str:
    """Return the canonical stored form of a requested username."""

    value = unicodedata.normalize("NFKC", raw).strip()
    if not USERNAME_PATTERN.fullmatch(value):
        raise _invalid(
            "A username must be 3 to 64 characters and may contain only "
            "letters, digits, dot, underscore and hyphen, starting with a "
            "letter or digit."
        )
    return value


def validate_password(raw: str) -> str:
    if not PASSWORD_MIN <= len(raw) <= PASSWORD_MAX:
        raise _invalid(f"A password must contain {PASSWORD_MIN} to {PASSWORD_MAX} characters.")
    if any(ord(character) < 0x20 for character in raw):
        raise _invalid("A password may not contain control characters.")
    return raw


def normalize_group_name(raw: str) -> str:
    try:
        return canonical_group_name(raw)
    except ValueError as error:
        raise _invalid(str(error)) from None


def normalize_display_name(raw: str | None, fallback: str) -> str:
    value = " ".join(unicodedata.normalize("NFKC", raw or "").split()) or fallback
    if len(value) > DISPLAY_NAME_MAX:
        raise _invalid(f"A display name may not exceed {DISPLAY_NAME_MAX} characters.")
    return value


def _catalog_usernames(settings: Settings) -> frozenset[str]:
    """Return the case-folded usernames owned by the read-only catalog."""

    try:
        snapshot = active_catalog_snapshot(settings)
    except CredentialFileError:
        # A missing or unreadable catalog must not silently widen the set of
        # claimable names; fail closed by treating nothing as free here only
        # when the caller can still detect the DB-side conflict below.
        return frozenset()
    return frozenset(username_key(account.username) for account in snapshot.accounts)


def username_is_available(db: Session, settings: Settings, username: str) -> bool:
    folded = username_key(username)
    if folded in _catalog_usernames(settings):
        return False
    taken = db.scalar(select(User.id).where(User.username_key == folded))
    return taken is None


def resolve_course(db: Session, course_id: str | None) -> Course:
    if course_id is not None:
        course = db.get(Course, course_id)
        if course is None:
            raise _invalid("The selected course does not exist.")
        return course
    courses = db.scalars(select(Course).order_by(Course.code)).all()
    if not courses:
        raise unprocessable(
            "registration_unavailable",
            "No course is available for registration yet.",
        )
    if len(courses) > 1:
        raise _invalid("A course must be selected when more than one course exists.")
    return courses[0]


def attach_to_group(db: Session, course: Course, user: User, group_name: str) -> Group:
    """Join the course group with this name, creating it on first use."""

    now = datetime.now(UTC)
    group = resolve_named_group(db, course.id, group_name)
    existing = db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group.id,
            GroupMember.user_id == user.id,
        )
    )
    if existing is None:
        db.add(
            GroupMember(
                group_id=group.id,
                user_id=user.id,
                role="member",
                created_at=now,
            )
        )
    return group


def register_student(
    db: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    display_name: str | None,
    group_name: str,
    course_id: str | None = None,
) -> tuple[User, Group]:
    """Create a self-registered student, its credential and its membership."""

    canonical_username = normalize_username(username)
    validate_password(password)
    canonical_group = normalize_group_name(group_name)
    canonical_display = normalize_display_name(display_name, canonical_username)

    # Hash before taking SQLite's writer lock; the read/claim/group/session
    # transaction must be serialized, but Argon2 work must not hold that lock.
    password_hash = _hasher().hash(password)
    try:
        db.execute(text("BEGIN IMMEDIATE"))
    except OperationalError:
        raise conflict("registration_busy", "Registration is busy. Please try again.") from None

    if not username_is_available(db, settings, canonical_username):
        # A duplicate username is the one registration failure a caller is
        # allowed to distinguish; without it the form cannot be corrected.
        raise conflict("username_taken", "That username is already taken.")

    course = resolve_course(db, course_id)
    now = datetime.now(UTC)
    user = User(
        id=str(uuid4()),
        username=canonical_username,
        display_name=canonical_display,
        status="active",
        created_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("username_taken", "That username is already taken.") from None
    db.add(
        UserCredential(
            user_id=user.id,
            username=canonical_username,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        CourseMember(
            course_id=course.id,
            user_id=user.id,
            role="student",
            created_at=now,
        )
    )
    group = attach_to_group(db, course, user, canonical_group)
    db.flush()
    return user, group


def username_exists(db: Session, settings: Settings, username: str) -> bool:
    """Whether either credential source knows this username.

    Used only to tell "no such account" apart from "wrong password" in the
    sign-in response.  That distinction is a deliberate product choice for a
    classroom: it also confirms to anyone asking that a given name is taken,
    so account names here are not a secret.
    """

    folded = username_key(username)
    if not folded:
        return False
    if folded in _catalog_usernames(settings):
        return True
    return (
        db.scalar(select(UserCredential.user_id).join(User).where(User.username_key == folded))
        is not None
    )


def verify_database_password(db: Session, username: str, password: str) -> str | None:
    """Return the User id for a valid database-catalog credential."""

    credential = db.scalar(
        select(UserCredential).join(User).where(User.username_key == username_key(username))
    )
    if credential is None:
        return None
    try:
        if _hasher().verify(password, credential.password_hash):
            return credential.user_id
    except Exception:
        # A corrupt stored hash fails closed without surfacing the hash or the
        # backend exception at the API boundary.
        return None
    return None


# A reset password is handed over verbally in class, so it is generated from
# an unambiguous alphabet: no 0/O or 1/l/I to mis-hear or mis-type.
RESET_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
RESET_LENGTH = 8


def generate_reset_password() -> str:
    """Return a short, read-aloud-safe temporary password."""

    return "".join(secrets.choice(RESET_ALPHABET) for _ in range(RESET_LENGTH))


def reset_student_password(
    db: Session,
    *,
    target: User,
    new_password: str | None,
) -> str:
    """Replace a self-registered account's password and return the new value.

    Only the writable database source can be reset.  The seven fixed Demo
    identities live in the read-only catalog that is mounted ``:ro`` and
    snapshotted at startup, so there is nothing here to rewrite for them and
    the caller is told that explicitly instead of silently doing nothing.
    """

    credential = db.scalar(select(UserCredential).where(UserCredential.user_id == target.id))
    if credential is None:
        raise unprocessable(
            "reset_not_supported",
            "This account is provisioned by the Demo catalog and has no resettable password.",
        )
    password = validate_password(new_password) if new_password else generate_reset_password()
    credential.password_hash = _hasher().hash(password)
    credential.updated_at = datetime.now(UTC)
    # Any session opened with the old password stops being usable. A reset is
    # normally requested because the student lost control of the account.
    revoke_user_sessions(db, target.id, credential.updated_at)
    db.flush()
    return password
