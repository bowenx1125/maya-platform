"""Authenticated user profile and credential changes."""

from __future__ import annotations

from datetime import UTC, datetime

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import PlatformError, unprocessable
from app.core.models import User
from app.modules.auth.credentials import verify_password
from app.modules.auth.models import UserCredential
from app.modules.auth.registration import validate_password
from app.modules.auth.service import revoke_user_sessions

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


def _password_matches(hash_value: str, password: str) -> bool:
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
    if credential is not None:
        valid_current = _password_matches(credential.password_hash, current_password)
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
    password_hash = PasswordHash.recommended().hash(password)
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

    revoke_user_sessions(
        db,
        user.id,
        now,
        except_session_id_hash=current_session_id_hash,
    )
    db.flush()
