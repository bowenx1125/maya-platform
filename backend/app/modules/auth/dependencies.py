"""FastAPI dependencies shared by auth and organization routes."""

from __future__ import annotations

import hmac
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.core.errors import csrf_failed, not_found, unauthenticated
from app.core.origin import origin_allowed, origin_tuple
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



def get_auth_clock() -> datetime | None:
    """Internal auth clock for TTL checks.

    Default ``None`` keeps the service-layer ``utc_now()`` path. Tests may
    override this dependency with a fixed timezone-aware UTC datetime; clients
    cannot supply a clock value.
    """

    return None


def require_auth(
    request: Request,
    raw_session_token: str | None = Security(session_cookie),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime | None = Depends(get_auth_clock),
) -> AuthContext:
    context = get_auth_context(db, settings, raw_session_token, now=now)
    if context is None:
        raise unauthenticated()
    return context


def _origin(value: str) -> tuple[str, str, int | None] | None:
    return origin_tuple(value)


def require_same_origin(request: Request, settings: Settings) -> None:
    origin_header = request.headers.get("origin")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if not origin_allowed(origin_header, settings, request_origin=request_origin):
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
    now: datetime | None = Depends(get_auth_clock),
) -> AuthContext:
    """Check Demo mode before looking at credentials.

    This keeps a disabled Demo endpoint consistently absent (404), including
    for anonymous requests, rather than leaking a 401 from an auth dependency.
    """

    require_demo_mode(settings)
    context = get_auth_context(db, settings, raw_session_token, now=now)
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
