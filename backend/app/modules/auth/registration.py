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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.core.adaptive_admission import shared_wait_seconds
from app.core.concurrency_gate import ConcurrencyGate, GateRejected
from app.core.config import Settings
from app.core.errors import PlatformError, conflict, unprocessable
from app.core.hash_gate import hash_slot, run_hash
from app.core.identity import normalize_group_name as canonical_group_name
from app.core.identity import username_key
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.core.sqlutil import begin_immediate
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


# One registration transaction per process at a time. The transaction takes
# a global Postgres advisory lock that is held until commit; without this
# gate every concurrent registrant checked out a pooled connection just to
# block on that lock. Waiters here hold no connection.
_REGISTRATION_TURN = ConcurrencyGate()
REGISTRATION_TURN_LIMIT = 1


def reset_registration_turn_state() -> None:
    """Clear in-flight / waiter counters (tests only)."""

    _REGISTRATION_TURN.reset()


def registration_turn_in_flight() -> int:
    return _REGISTRATION_TURN.in_flight


def hash_registration_password(password: str, settings: Settings) -> str:
    """Argon2-hash a validated password under the shared hash gate."""

    validate_password(password)
    return run_hash(lambda: _hasher().hash(password), settings)


@contextmanager
def registration_turn(settings: Settings) -> Iterator[None]:
    """Hold this process's registration-writer turn until the block ends.

    The caller commits inside the block, so the advisory lock is released
    before the next waiter takes a connection. A waiter waits only for what
    is left of the request's admission deadline; past it, or when the queue
    is full, a retryable ``adaptive_admission_busy`` 503 is returned.
    """

    wait_seconds = shared_wait_seconds(float(settings.adaptive_admission_wait_seconds))
    try:
        with _REGISTRATION_TURN.hold(
            limit=REGISTRATION_TURN_LIMIT,
            queue_max=int(settings.adaptive_admission_queue_max),
            wait_seconds=wait_seconds,
        ):
            yield
    except GateRejected as rejected:
        raise PlatformError(
            "adaptive_admission_busy",
            "The server is busy. Wait a moment and try again.",
            503,
            {
                "retryable": True,
                "retry_after_seconds": max(1, int(settings.adaptive_admission_retry_seconds)),
                "reason": f"registration_{rejected.reason}",
                "operation": "register",
            },
        ) from None


def register_student(
    db: Session,
    settings: Settings,
    *,
    username: str,
    password: str,
    display_name: str | None,
    group_name: str,
    course_id: str | None = None,
    password_hash: str | None = None,
) -> tuple[User, Group]:
    """Create a self-registered student, its credential and its membership.

    ``password_hash`` is the caller's ``hash_registration_password`` result,
    computed before it took the registration turn; omitted, it is hashed here.
    """

    canonical_username = normalize_username(username)
    validate_password(password)
    canonical_group = normalize_group_name(group_name)
    canonical_display = normalize_display_name(display_name, canonical_username)

    # Hash before taking the registration advisory lock; the read/claim/group/
    # session transaction is serialized, but Argon2 work must not hold the lock.
    if password_hash is None:
        password_hash = run_hash(lambda: _hasher().hash(password), settings)
    try:
        begin_immediate(db, lock_key="maya-student-registration")
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


# Computed lazily on first unknown-username login and reused for the process
# lifetime: Argon2 parameters are frozen, so one hash is representative. It
# equalizes timing so a missing credential row costs the same CPU work as a
# real verify and does not reveal whether a name exists in the database.
_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _hasher().hash("maya-dummy-password-for-unknown-users")
    assert _DUMMY_HASH is not None
    return _DUMMY_HASH


def lock_password_identity(db: Session, user_id: str) -> None:
    # The User row also exists before a catalog account creates its first
    # database credential, so both credential sources share this fence.
    begin_immediate(db)
    db.scalar(select(User.id).where(User.id == user_id).with_for_update())


def verify_database_password(
    db: Session,
    username: str,
    password: str,
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """Return whether the database owns this name and its id when valid.

    The pooled connection is released (rollback checks it back in) before any
    Argon2 work runs, so a burst of logins never holds connections while
    burning the 64 MiB hash memory.
    """

    row = db.execute(
        select(UserCredential.user_id, UserCredential.password_hash)
        .join(User, User.id == UserCredential.user_id)
        .where(User.username_key == username_key(username))
    ).first()
    # Plain values only: no ORM attribute may be touched after the rollback
    # below expires the session's transaction state.
    credential_user_id: str | None = None
    stored_hash: str | None = None
    if row is not None:
        credential_user_id, stored_hash = row
    db.rollback()
    # The gate sits outside the try: a hash-gate busy 503 must surface as
    # "busy, retry", never be swallowed into a wrong-password answer.
    with hash_slot(settings):
        if stored_hash is None:
            # Unknown to the database: still burn one Argon2 verify so timing
            # matches the known-name path.
            try:
                _hasher().verify(password, _dummy_hash())
            except Exception:
                pass
            return False, None
        try:
            valid = _hasher().verify(password, stored_hash)
        except Exception:
            # A corrupt stored hash fails closed without surfacing the hash or the
            # backend exception at the API boundary.
            return True, None
    if not valid or credential_user_id is None:
        return True, None
    # A password reset can commit while this request waits or hashes. Keep
    # the verified credential locked through session creation: a later reset
    # must see and revoke that session, not miss an uncommitted login.
    lock_password_identity(db, credential_user_id)
    current_hash = db.scalar(
        select(UserCredential.password_hash)
        .where(UserCredential.user_id == credential_user_id)
        .with_for_update(of=UserCredential)
    )
    return True, credential_user_id if current_hash == stored_hash else None


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

    user_id = target.id
    credential_id = db.scalar(
        select(UserCredential.user_id).where(UserCredential.user_id == user_id)
    )
    if credential_id is None:
        raise unprocessable(
            "reset_not_supported",
            "This account is provisioned by the Demo catalog and has no resettable password.",
        )
    password = validate_password(new_password) if new_password else generate_reset_password()
    # Authorization and credential existence have been checked; release the
    # read connection while the bounded hash queue waits and runs.
    db.rollback()
    password_hash = run_hash(lambda: _hasher().hash(password))
    lock_password_identity(db, user_id)
    credential = db.get(UserCredential, user_id, populate_existing=True)
    if credential is None:
        raise unprocessable(
            "reset_not_supported",
            "This account is provisioned by the Demo catalog and has no resettable password.",
        )
    credential.password_hash = password_hash
    credential.updated_at = datetime.now(UTC)
    # Acquire the credential writer lock before reading sessions, so a login
    # that held it first is committed and visible to this revocation.
    db.flush()
    # Any session opened with the old password stops being usable. A reset is
    # normally requested because the student lost control of the account.
    revoke_user_sessions(db, user_id, credential.updated_at)
    db.flush()
    return password
