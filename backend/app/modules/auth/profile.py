"""Authenticated user profile and credential changes."""

from __future__ import annotations

import unicodedata
from datetime import UTC, datetime

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, conflict, unprocessable
from app.core.hash_gate import hash_slot, run_hash
from app.core.identity import group_name_key
from app.core.models import CourseMember, Group, User
from app.modules.auth.credentials import verify_password
from app.modules.auth.models import DemoAccountBinding, UserCredential
from app.modules.auth.registration import (
    DISPLAY_NAME_MAX,
    lock_password_identity,
    validate_password,
)
from app.modules.auth.service import revoke_user_sessions
from app.modules.org.roster import move_to_group

AVATAR_CHOICES = (
    "scholar-arch:violet",
    "scholar-block:terracotta",
    "scholar-round:sage",
    "scholar-pillar:gold",
    "scholar-arch:gold",
    "scholar-block:violet",
    "scholar-round:terracotta",
    "scholar-pillar:sage",
)
_AVATAR_CHOICE_SET = frozenset(AVATAR_CHOICES)


def update_avatar(user: User, avatar: str | None) -> None:
    if avatar is not None and avatar not in _AVATAR_CHOICE_SET:
        raise unprocessable("avatar_invalid", "Choose one of the available scholar avatars.")
    user.avatar = avatar


def update_display_name(db: Session, user: User, raw: str) -> None:
    """Rename yourself, with the same rules a teacher's roster edit applies."""

    # A catalog account's name is re-applied from the account file on every
    # start, so a change here would quietly revert; refuse it and say why.
    managed = db.scalar(
        select(DemoAccountBinding.user_id).where(
            DemoAccountBinding.user_id == user.id, DemoAccountBinding.active.is_(True)
        )
    )
    if managed is not None:
        raise conflict(
            "display_name_managed",
            "This account's name comes from the course's account list; ask your teacher.",
        )
    value = " ".join(unicodedata.normalize("NFKC", raw).split())
    if not value or len(value) > DISPLAY_NAME_MAX:
        raise unprocessable(
            "display_name_invalid",
            f"A name needs 1 to {DISPLAY_NAME_MAX} characters.",
        )
    user.display_name = value


def change_group(db: Session, user: User, raw: str) -> None:
    """Move a student into another of their course's existing groups.

    Only the membership moves. Agents, Teams, RAG and voices belong to the
    group they were made in and stay there, as they do when a teacher moves
    the student from Accounts.
    """

    managed = db.scalar(
        select(DemoAccountBinding.user_id).where(
            DemoAccountBinding.user_id == user.id, DemoAccountBinding.active.is_(True)
        )
    )
    if managed is not None:
        raise conflict(
            "group_managed",
            "This account's group comes from the course's account list; ask your teacher.",
        )
    course_ids = db.scalars(
        select(CourseMember.course_id).where(
            CourseMember.user_id == user.id, CourseMember.role == "student"
        )
    ).all()
    if not course_ids:
        raise conflict("group_change_forbidden", "Only students choose their own group.")
    try:
        key = group_name_key(raw)
    except ValueError:
        raise unprocessable("group_not_found", "Choose one of the course's groups.") from None
    groups = db.scalars(
        select(Group).where(Group.course_id.in_(course_ids), Group.name_key == key)
    ).all()
    # Students pick from the groups that exist; a new name never creates one.
    if len(groups) != 1:
        raise unprocessable("group_not_found", "Choose one of the course's groups.")
    group = groups[0]
    move_to_group(db, group.course_id, user, group.name)


def _password_matches(hash_value: str, password: str) -> bool:
    # Gate outside the try so a busy 503 is not reported as a wrong password.
    with hash_slot():
        try:
            return PasswordHash.recommended().verify(password, hash_value)
        except Exception:
            return False


def change_password(
    db: Session,
    settings: Settings,
    *,
    user: User,
    current_password: str,
    new_password: str,
    current_session_id_hash: str,
) -> None:
    """Change one authenticated account's password and keep this session alive."""

    credential = db.scalar(select(UserCredential).where(UserCredential.user_id == user.id))
    stored_hash = credential.password_hash if credential is not None else None
    if stored_hash is not None:
        valid_current = _password_matches(stored_hash, current_password)
    else:
        valid_current = verify_password(settings, user.username, current_password) == user.id
    if not valid_current:
        raise PlatformError(
            "password_incorrect",
            "That password does not match this account.",
            401,
        )

    password = validate_password(new_password)
    now = datetime.now(UTC)
    password_hash = run_hash(lambda: PasswordHash.recommended().hash(password), settings)
    lock_password_identity(db, user.id)
    current_hash = db.scalar(
        select(UserCredential.password_hash).where(UserCredential.user_id == user.id)
    )
    if current_hash != stored_hash:
        raise PlatformError(
            "password_incorrect",
            "That password does not match this account.",
            401,
        )
    if credential is None:
        credential = UserCredential(
            user_id=user.id,
            username=user.username,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        db.add(credential)
    else:
        credential.username = user.username
        credential.password_hash = password_hash
        credential.updated_at = now

    # Publish the credential write before looking up sessions: a concurrent
    # login holds this row until its new session can be revoked here.
    db.flush()
    revoke_user_sessions(
        db,
        user.id,
        now,
        except_session_id_hash=current_session_id_hash,
    )
    db.flush()
