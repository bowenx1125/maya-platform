"""Provisioning for the shared MAYAMAYA teaching account.

The Demo catalog already ships a teacher called ``maya``; this is a separate,
environment-provisioned account and its name has to stay distinct from that
one.  MAYAMAYA is an ordinary account: a username, a password and the teacher role.
Two things about it are deliberate.

First, the password comes from ``MAYA_PASSWORD`` rather than from Git or a
literal in this file. It is a shared classroom credential, so a fixed value
is the point; keeping it out of the repository is what stops "fixed" from
also meaning "public". With the variable unset the account is not created at
all and signing in as MAYAMAYA fails closed.

Second, MAYAMAYA is re-provisioned on every start. That makes the environment
the single source of truth: changing the password and restarting is the
whole rotation procedure, and no stale hash survives it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid5

from pwdlib import PasswordHash
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import Course, CourseMember, User
from app.modules.auth.credentials import ACCOUNT_NAMESPACE
from app.modules.auth.models import UserCredential
from app.modules.auth.service import revoke_user_sessions

OBSERVER_USERNAME = "MAYAMAYA"
OBSERVER_DISPLAY_NAME = "MAYAMAYA"
# A deterministic id keeps the account stable across restarts and rebuilds,
# so its group memberships and any audit trail survive re-provisioning.
OBSERVER_USER_ID = str(uuid5(ACCOUNT_NAMESPACE, "maya-observer"))


def observer_enabled(settings: Settings) -> bool:
    return bool(settings.maya_password and settings.maya_password.strip())


def is_observer(user: User) -> bool:
    return user.id == OBSERVER_USER_ID


def provision_observer_account(session: Session, settings: Settings) -> bool:
    """Create or refresh MAYAMAYA and enrol it as a teacher in every course.

    Returns whether the account is present after the call.
    """

    password = (settings.maya_password or "").strip()
    now = datetime.now(UTC)
    if not password:
        # No configured password: revoke any account left over from a start
        # that did have one, so removing the variable actually turns MAYAMAYA off.
        existing = session.get(User, OBSERVER_USER_ID)
        if existing is not None and existing.status == "active":
            existing.status = "disabled"
            revoke_user_sessions(session, OBSERVER_USER_ID, now)
        return False

    user = session.get(User, OBSERVER_USER_ID)
    if user is None:
        # A human-registered account may already hold the name; the reserved
        # list prevents that, but a database restored from before this
        # feature could still contain one. Leave it alone rather than
        # silently taking over someone's login.
        clash = session.scalar(
            select(User).where(func.lower(User.username) == OBSERVER_USERNAME.casefold())
        )
        if clash is not None:
            return False
        user = User(
            id=OBSERVER_USER_ID,
            username=OBSERVER_USERNAME,
            display_name=OBSERVER_DISPLAY_NAME,
            status="active",
            created_at=now,
        )
        session.add(user)
        session.flush()
    else:
        user.status = "active"
        user.username = OBSERVER_USERNAME
        user.display_name = OBSERVER_DISPLAY_NAME

    password_hash = PasswordHash.recommended().hash(password)
    credential = session.get(UserCredential, OBSERVER_USER_ID)
    if credential is None:
        session.add(
            UserCredential(
                user_id=OBSERVER_USER_ID,
                username=OBSERVER_USERNAME,
                password_hash=password_hash,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        credential.username = OBSERVER_USERNAME
        credential.password_hash = password_hash
        credential.updated_at = now

    # MAYAMAYA teaches every course, so it reaches the teacher surface through
    # the same scope checks every other teacher uses. No route special-cases
    # this account.
    course_ids = list(session.scalars(select(Course.id)).all())
    enrolled = set(
        session.scalars(
            select(CourseMember.course_id).where(CourseMember.user_id == OBSERVER_USER_ID)
        ).all()
    )
    for course_id in course_ids:
        if course_id in enrolled:
            continue
        session.add(
            CourseMember(
                course_id=course_id,
                user_id=OBSERVER_USER_ID,
                role="teacher",
                created_at=now,
            )
        )
    session.flush()
    return True
