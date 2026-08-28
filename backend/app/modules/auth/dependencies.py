"""FastAPI dependencies shared by auth and organization routes."""

from __future__ import annotations

import hmac
from collections.abc import Generator
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import csrf_failed, forbidden, not_found, unauthenticated
from app.core.models import CourseMember, GroupMember
from app.modules.auth.service import AuthContext, get_auth_context

session_cookie = APIKeyCookie(
    name="maya_session",
    scheme_name="sessionCookie",
    auto_error=False,
)


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if not isinstance(database, Database):
        raise RuntimeError("database is not initialized")
    return database


def get_db(
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> Generator[Session, None, None]:
    # FastAPI's generator dependency closes the session after each request.
    session = database.session_factory()
    # Provider-neutral projections such as an Agent's effective platform voice
    # need the exact Settings instance injected into this app/test process.
    # Keeping it in SQLAlchemy's request-local ``Session.info`` avoids adding
    # Settings arguments to every repository projection call.
    session.info["maya_settings"] = settings
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_auth(
    request: Request,
    raw_session_token: str | None = Security(session_cookie),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    context = get_auth_context(db, settings, raw_session_token)
    if context is None:
        raise unauthenticated()
    return context


def _origin(value: str) -> tuple[str, str, int | None] | None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port
    return parsed.scheme.lower(), parsed.hostname.lower(), port


def require_same_origin(request: Request, settings: Settings) -> None:
    origin_header = request.headers.get("origin")
    if not origin_header:
        raise csrf_failed()
    origin = _origin(origin_header)
    if origin is None:
        raise csrf_failed()

    expected_values = [f"{request.url.scheme}://{request.url.netloc}"]
    if settings.classroom_public_base_url:
        expected_values.append(settings.classroom_public_base_url)
    expected = {_origin(value.rstrip("/")) for value in expected_values}
    expected.discard(None)
    if origin not in expected:
        raise csrf_failed()


def require_csrf(request: Request, context: AuthContext, settings: Settings) -> None:
    require_same_origin(request, settings)
    supplied = request.headers.get("x-csrf-token")
    if not supplied or not hmac.compare_digest(supplied, context.csrf_token):
        raise csrf_failed()


def require_authenticated_mutation(
    request: Request,
    context: AuthContext = Depends(require_auth),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    require_csrf(request, context, settings)
    return context


def require_demo_auth(
    request: Request,
    raw_session_token: str | None = Security(session_cookie),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    """Check Demo mode before looking at credentials.

    This keeps a disabled Demo endpoint consistently absent (404), including
    for anonymous requests, rather than leaking a 401 from an auth dependency.
    """

    require_demo_mode(settings)
    context = get_auth_context(db, settings, raw_session_token)
    if context is None:
        raise unauthenticated()
    return context


def require_demo_authenticated_mutation(
    request: Request,
    context: AuthContext = Depends(require_demo_auth),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    require_csrf(request, context, settings)
    return context


@dataclass(frozen=True)
class CourseScope:
    course_id: str
    role: str


def course_scope(db: Session, context: AuthContext, course_id: str) -> CourseScope | None:
    role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == course_id,
            CourseMember.user_id == context.user.id,
        )
    )
    return CourseScope(course_id, role) if role is not None else None


def group_scope(db: Session, context: AuthContext, group_id: str) -> str | None:
    return db.scalar(
        select(GroupMember.role).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == context.user.id,
        )
    )


def require_demo_mode(settings: Settings) -> None:
    if not settings.demo_mode:
        raise not_found()


def require_demo_quick_login(settings: Settings = Depends(get_settings)) -> Settings:
    """Authorize the anonymous Demo identity catalog and passwordless login."""

    if not (settings.demo_mode and settings.demo_quick_login):
        # Deliberately return 404 for either disabled flag, including an
        # anonymous request, so the feature is not discoverable when off.
        raise not_found()
    return settings


def require_teacher(scope: CourseScope | None) -> CourseScope:
    if scope is None:
        raise not_found()
    if scope.role != "teacher":
        raise forbidden()
    return scope
