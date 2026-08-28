"""Username/password and Demo-mode authentication routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, not_found, unauthenticated
from app.core.models import CourseMember, GroupMember, User
from app.modules.auth.credentials import (
    CredentialFileError,
    DemoAccountSnapshot,
    active_catalog_snapshot,
    verify_password,
)
from app.modules.auth.dependencies import (
    get_db,
    require_auth,
    require_authenticated_mutation,
    require_demo_authenticated_mutation,
    require_demo_mode,
    require_demo_quick_login,
)
from app.modules.auth.schemas import (
    AuthSession,
    CourseMembership,
    CurrentUser,
    DemoIdentity,
    DemoQuickLoginRequest,
    DemoSwitchRequest,
    GroupMembership,
    LoginRequest,
)
from app.modules.auth.service import (
    SESSION_COOKIE_NAME,
    AuthContext,
    create_rotated_session,
    revoke_cookie_session,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _set_session_cookie(
    response: Response,
    raw_token: str,
    settings: Settings,
    request: Request,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.cookie_secure(request.url.scheme),
        samesite="lax",
        max_age=12 * 60 * 60,
        path="/",
    )


def _current_user(db: Session, user: User) -> CurrentUser:
    course_rows = db.execute(
        select(CourseMember.course_id, CourseMember.role)
        .where(CourseMember.user_id == user.id)
        .order_by(CourseMember.course_id)
    ).all()
    group_rows = db.execute(
        select(GroupMember.group_id, GroupMember.role)
        .where(GroupMember.user_id == user.id)
        .order_by(GroupMember.group_id)
    ).all()
    return CurrentUser(
        id=UUID(user.id),
        username=user.username,
        display_name=user.display_name,
        courses=[
            CourseMembership(course_id=UUID(row.course_id), role=row.role) for row in course_rows
        ],
        groups=[GroupMembership(group_id=UUID(row.group_id), role=row.role) for row in group_rows],
    )


def _auth_response(db: Session, context: AuthContext, csrf: str | None = None) -> AuthSession:
    return AuthSession(
        user=_current_user(db, context.user),
        csrf_token=csrf or context.csrf_token,
        expires_at=_utc(context.session.expires_at),
    )


def _safe_demo_snapshot(settings: Settings) -> DemoAccountSnapshot:
    """Read the immutable startup catalog without exposing parser details."""

    try:
        return active_catalog_snapshot(settings)
    except CredentialFileError:
        # The catalog is validated during startup as well. This branch remains
        # generic by design: no path, account key, username, password, or raw
        # line leaks.
        raise PlatformError(
            "provider_unavailable",
            "The service is temporarily unavailable.",
            503,
        ) from None


def _public_demo_identities(db: Session, settings: Settings) -> list[DemoIdentity]:
    snapshot = _safe_demo_snapshot(settings)
    users = {
        row.id: row
        for row in db.scalars(
            select(User).where(
                User.id.in_([snapshot.user_id_for(account) for account in snapshot.accounts]),
                User.status == "active",
            )
        ).all()
    }
    output = [
        DemoIdentity(
            user_id=UUID(snapshot.user_id_for(account)),
            # The published process snapshot is the source for public
            # identity presentation too; the DB lookup only confirms that
            # the bound User remains active after startup.
            display_name=account.display_name,
            role=account.role,
        )
        for account in snapshot.accounts
        if snapshot.user_id_for(account) in users
    ]
    return sorted(output, key=lambda item: (item.display_name.casefold(), str(item.user_id)))


@router.post(
    "/login",
    response_model=AuthSession,
    operation_id="login",
    openapi_extra={"security": []},
    responses={
        200: {"model": AuthSession, "description": "Session created and CSRF token returned."},
        401: {"model": Error, "description": "Authentication failed."},
    },
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    user_id = verify_password(settings, payload.username, payload.password)
    if user_id is None:
        raise unauthenticated("The username or password is incorrect.")
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise unauthenticated("The username or password is incorrect.")
    raw_token, session_row, raw_csrf = create_rotated_session(
        db,
        user,
        settings,
        old_raw_token=request.cookies.get(SESSION_COOKIE_NAME),
    )
    _set_session_cookie(response, raw_token, settings, request)
    context = AuthContext(raw_token, session_row, user, raw_csrf)
    return _auth_response(db, context, raw_csrf)


@router.get(
    "/me",
    response_model=AuthSession,
    operation_id="getCurrentUser",
    responses={
        200: {
            "model": AuthSession,
            "description": "Current user, memberships, refreshed CSRF token and session expiry.",
        },
        401: {"model": Error, "description": "Authentication required."},
    },
)
def me(
    context: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AuthSession:
    return _auth_response(db, context)


@router.post(
    "/switch",
    response_model=AuthSession,
    operation_id="switchDemoIdentity",
    responses={
        200: {"model": AuthSession, "description": "New session."},
        403: {"model": Error, "description": "CSRF or permission failure."},
        404: {"model": Error, "description": "Demo mode or identity not found."},
    },
)
def switch_demo_identity(
    payload: DemoSwitchRequest,
    request: Request,
    response: Response,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_demo_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    require_demo_mode(settings)
    snapshot = _safe_demo_snapshot(settings)
    account = next(
        (item for item in snapshot.accounts if snapshot.user_id_for(item) == str(payload.user_id)),
        None,
    )
    user = db.get(User, str(payload.user_id)) if account is not None else None
    if user is None or user.status != "active":
        raise not_found()
    raw_token, session_row, raw_csrf = create_rotated_session(
        db,
        user,
        settings,
        old_raw_token=context.raw_session_token,
    )
    _set_session_cookie(response, raw_token, settings, request)
    return _auth_response(db, AuthContext(raw_token, session_row, user, raw_csrf), raw_csrf)


@router.get(
    "/demo-identities",
    response_model=list[DemoIdentity],
    operation_id="listDemoIdentities",
    openapi_extra={"security": []},
    responses={
        200: {"model": list[DemoIdentity], "description": "Safe identity options."},
        404: {"model": Error, "description": "Demo mode is disabled."},
    },
)
def demo_identities(
    db: Session = Depends(get_db),
    settings: Settings = Depends(require_demo_quick_login),
) -> list[DemoIdentity]:
    return _public_demo_identities(db, settings)


@router.post(
    "/quick-login",
    response_model=AuthSession,
    operation_id="quickLogin",
    openapi_extra={"security": []},
    responses={
        200: {"model": AuthSession, "description": "Passwordless Demo session created."},
        404: {"model": Error, "description": "Demo quick login is disabled or unknown."},
        503: {"model": Error, "description": "The Demo account catalog is unavailable."},
    },
)
def quick_login(
    payload: DemoQuickLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(require_demo_quick_login),
) -> AuthSession:
    """Rotate a session for one currently active catalog identity.

    This route is intentionally anonymous and has no CSRF requirement: it is
    an explicit identity selection from the server-provided public catalog.
    The old cookie, if any, is still revoked before rotation.
    """

    snapshot = _safe_demo_snapshot(settings)
    account = next(
        (item for item in snapshot.accounts if snapshot.user_id_for(item) == str(payload.user_id)),
        None,
    )
    user = db.get(User, str(payload.user_id)) if account is not None else None
    if user is None or user.status != "active":
        raise not_found()
    raw_token, session_row, raw_csrf = create_rotated_session(
        db,
        user,
        settings,
        old_raw_token=request.cookies.get(SESSION_COOKIE_NAME),
    )
    _set_session_cookie(response, raw_token, settings, request)
    return _auth_response(db, AuthContext(raw_token, session_row, user, raw_csrf), raw_csrf)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="logout",
    responses={204: {"description": "Session revoked."}},
)
def logout(
    request: Request,
    response: Response,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> None:
    revoke_cookie_session(db, context.raw_session_token)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
