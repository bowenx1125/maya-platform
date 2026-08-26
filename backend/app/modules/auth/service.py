"""Session and CSRF primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import SessionRecord, User

SESSION_COOKIE_NAME = "maya_session"
SESSION_TTL = timedelta(hours=12)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _urlsafe_digest(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def new_raw_session_token() -> str:
    # token_urlsafe(32) encodes exactly 32 random bytes and never stores the
    # raw value in the database.
    return secrets.token_urlsafe(32)


def session_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def csrf_token(raw_token: str, settings: Settings) -> str:
    digest = hmac.new(settings.secret_bytes, raw_token.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_digest(digest)


def csrf_hash(raw_csrf: str) -> str:
    return hashlib.sha256(raw_csrf.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthContext:
    raw_session_token: str
    session: SessionRecord
    user: User
    csrf_token: str


def revoke_cookie_session(db: Session, raw_token: str | None, now: datetime | None = None) -> None:
    if not raw_token:
        return
    row = db.get(SessionRecord, session_hash(raw_token))
    if row is not None and row.revoked_at is None:
        row.revoked_at = now or utc_now()


def create_rotated_session(
    db: Session,
    user: User,
    settings: Settings,
    old_raw_token: str | None = None,
    now: datetime | None = None,
) -> tuple[str, SessionRecord, str]:
    timestamp = now or utc_now()
    revoke_cookie_session(db, old_raw_token, timestamp)
    raw_token = new_raw_session_token()
    raw_csrf = csrf_token(raw_token, settings)
    row = SessionRecord(
        id_hash=session_hash(raw_token),
        user_id=user.id,
        csrf_hash=csrf_hash(raw_csrf),
        expires_at=timestamp + SESSION_TTL,
        created_at=timestamp,
        revoked_at=None,
    )
    db.add(row)
    db.flush()
    return raw_token, row, raw_csrf


def get_auth_context(
    db: Session,
    settings: Settings,
    raw_token: str | None,
    now: datetime | None = None,
) -> AuthContext | None:
    if not raw_token:
        return None
    row = db.get(SessionRecord, session_hash(raw_token))
    if row is None or row.revoked_at is not None:
        return None
    timestamp = now or utc_now()
    if _normalise_datetime(row.expires_at) <= timestamp:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return None
    raw_csrf = csrf_token(raw_token, settings)
    if not hmac.compare_digest(row.csrf_hash, csrf_hash(raw_csrf)):
        # A database row with an altered CSRF hash is invalid; never mint a
        # new value or reveal why it failed.
        return None
    return AuthContext(raw_token, row, user, raw_csrf)
