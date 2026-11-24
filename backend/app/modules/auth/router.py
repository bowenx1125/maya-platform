"""Username/password and Demo-mode authentication routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.adaptive_admission import adaptive_slot
from app.core.config import Settings, get_settings
from app.core.errors import Error, PlatformError, forbidden, not_found
from app.core.models import Course, CourseMember, Group, GroupMember, User
from app.modules.auth.abuse import AuthAbuseLimiter, client_key
from app.modules.auth.admission import (
    login_database_overloaded,
)
from app.modules.auth.credentials import (
    CredentialFileError,
    DemoAccountSnapshot,
    active_catalog_snapshot,
    verify_password,
)
from app.modules.auth.dependencies import (
    get_auth_clock,
    get_db,
    require_auth,
    require_authenticated_mutation,
    require_demo_authenticated_mutation,
    require_demo_mode,
    require_demo_quick_login,
    require_same_origin,
)
from app.modules.auth.identity_choice import consume_choice, issue_choice, student_landing_group
from app.modules.auth.models import UserCredential
from app.modules.auth.profile import (
    change_group,
    change_password,
    update_avatar,
    update_display_name,
)
from app.modules.auth.registration import (
    hash_registration_password,
    lock_password_identity,
    normalize_display_name,
    normalize_group_name,
    normalize_username,
    register_student,
    registration_turn,
    reset_student_password,
    resolve_course,
    username_exists,
    verify_database_password,
)
from app.modules.auth.research_consent import apply_login_research_consent
from app.modules.auth.schemas import (
    AuthSession,
    CourseMembership,
    CurrentUser,
    DemoIdentity,
    DemoQuickLoginRequest,
    DemoSwitchRequest,
    GroupMembership,
    LoginIdentityChoice,
    LoginIdentityChoiceRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    PasswordResetResult,
    RegisterRequest,
    RegistrationClass,
    RegistrationGroup,
    RegistrationOptions,
    UpdateCurrentUserRequest,
)
from app.modules.auth.service import (
    SESSION_COOKIE_NAME,
    AuthContext,
    create_rotated_session,
    lock_user_profile,
    revoke_cookie_session,
)
from app.modules.org.access import WorkspaceMember
from app.modules.org.classes import SECOND_CLASS_ID
from app.modules.voices.withdrawal import finish_withdrawn_voices
from app.seed import BOWEN_ID, COURSE_ID

router = APIRouter(prefix="/auth", tags=["Auth"])


def _limiter(request: Request) -> AuthAbuseLimiter:
    limiter = getattr(request.app.state, "auth_abuse_limiter", None)
    if not isinstance(limiter, AuthAbuseLimiter):
        raise RuntimeError("authentication abuse limiter is not initialized")
    return limiter


def _require_production_auth_origin(request: Request, settings: Settings) -> None:
    if settings.is_production:
        require_same_origin(request, settings)


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
        max_age=int(settings.session_ttl.total_seconds()),
        path="/",
    )


def _current_user(db: Session, user: User, active_course_id: str | None = None) -> CurrentUser:
    course_rows = db.execute(
        select(CourseMember.course_id, CourseMember.role)
        .join(Course, Course.id == CourseMember.course_id)
        .where(CourseMember.user_id == user.id)
        .order_by(
            case((Course.id == active_course_id, 0), else_=1),
            case((Course.id == COURSE_ID, 0), (Course.id == SECOND_CLASS_ID, 1), else_=2),
            Course.created_at,
            Course.code,
        )
    ).all()
    group_rows = db.execute(
        select(WorkspaceMember.group_id, WorkspaceMember.role)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.group_id)
    ).all()
    if user.id == BOWEN_ID and course_rows:
        landing = student_landing_group(db, user, active_course_id or course_rows[0].course_id)
        if landing is not None:
            group_rows = sorted(group_rows, key=lambda row: row.group_id != landing.id)
    return CurrentUser(
        id=UUID(user.id),
        username=user.username,
        display_name=user.display_name,
        avatar=user.avatar,
        courses=[
            CourseMembership(course_id=UUID(row.course_id), role=row.role) for row in course_rows
        ],
        groups=[GroupMembership(group_id=UUID(row.group_id), role=row.role) for row in group_rows],
    )


def _auth_response(db: Session, context: AuthContext, csrf: str | None = None) -> AuthSession:
    return AuthSession(
        user=_current_user(db, context.user, context.session.active_course_id),
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
        202: {"model": LoginIdentityChoice, "description": "Choose the login identity."},
        401: {"model": Error, "description": "Authentication failed."},
        403: {"model": Error, "description": "The configured public origin is required."},
        413: {"description": "The production gateway rejects oversized login bodies."},
        429: {"model": Error, "description": "Authentication attempts are temporarily limited."},
    },
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime | None = Depends(get_auth_clock),
) -> AuthSession | JSONResponse:
    _require_production_auth_origin(request, settings)
    # Join the unified pressure queue before the abuse limiter and password
    # check: under host pressure sign-in waits (not fails) and does not spend
    # the failed-login allowance. Only timeout / full queue returns a 503.
    with adaptive_slot("login", settings):
        return _login_admitted(payload, request, response, db, settings, now=now)


def _login_admitted(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session,
    settings: Settings,
    now: datetime | None = None,
) -> AuthSession | JSONResponse:
    limiter = _limiter(request) if settings.is_production else None
    reservation = None
    failed = False
    succeeded = False
    try:
        if limiter is not None:
            reservation = limiter.reserve_login(
                client_key(request, settings), payload.username, settings
            )
        # The read-only catalog stays authoritative for provisioned identities;
        # self-registered accounts resolve from the database source after a miss.
        database_owned, user_id = verify_database_password(
            db, payload.username, payload.password, settings
        )
        if not database_owned:
            user_id = verify_password(settings, payload.username, payload.password)
            if user_id is not None:
                lock_password_identity(db, user_id)
                # A catalog password stops working as soon as the account
                # saves its own credential, including during this verify.
                if db.get(UserCredential, user_id) is not None:
                    user_id = None
        if user_id is None:
            failed = True
            # Which half was wrong is reported on purpose. A student who has
            # mistyped their name should not spend the lesson guessing at their
            # password instead. The cost is that a name can be probed for
            # existence, which is accepted here: these are classroom accounts,
            # created by the students themselves, and the roster is visible to
            # everyone in the course anyway.
            if username_exists(db, settings, payload.username):
                raise PlatformError(
                    "password_incorrect", "That password does not match this account.", 401
                )
            raise PlatformError("account_not_found", "No account uses that username yet.", 401)
        user = db.get(User, user_id)
        if user is None or user.status != "active":
            failed = True
            # A deactivated account is a teacher decision, not a typo, and saying
            # so is what stops the student from trying the password again.
            raise PlatformError(
                "account_inactive", "This account has been deactivated by a teacher.", 401
            )
        # Consent is recorded only after a successful password verify. It never
        # blocks the session; untick on a later login revokes a prior true row.
        apply_login_research_consent(
            db,
            user_id=user.id,
            consented=bool(payload.research_consent),
            now=now,
        )
        if user.id == BOWEN_ID:
            challenge = issue_choice(db, client_key(request, settings), now)
            succeeded = True
            return JSONResponse(status_code=202, content=challenge.model_dump(mode="json"))
        raw_token, session_row, raw_csrf = create_rotated_session(
            db,
            user,
            settings,
            old_raw_token=request.cookies.get(SESSION_COOKIE_NAME),
            now=now,
        )
        _set_session_cookie(response, raw_token, settings, request)
        context = AuthContext(raw_token, session_row, user, raw_csrf)
        succeeded = True
        return _auth_response(db, context, raw_csrf)
    except OperationalError as exc:
        if not login_database_overloaded(exc):
            raise
        raise _login_queue_overload(settings) from None
    finally:
        if limiter is not None and reservation is not None:
            limiter.finish_login(reservation, failed=failed)
        # Commit the new session; a failed sign-in rolls its own writes back.
        if succeeded:
            db.commit()
        elif db.in_transaction():
            db.rollback()


@router.post(
    "/identity-choice",
    response_model=AuthSession,
    operation_id="chooseLoginIdentity",
    openapi_extra={"security": []},
    responses={
        200: {"model": AuthSession, "description": "Session created for the chosen identity."},
        401: {"model": Error, "description": "Login choice is invalid or unavailable."},
        403: {"model": Error, "description": "The configured public origin is required."},
        422: {"model": Error, "description": "Choose an available class for the student identity."},
        429: {"model": Error, "description": "Authentication attempts are temporarily limited."},
    },
)
def choose_login_identity(
    payload: LoginIdentityChoiceRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime | None = Depends(get_auth_clock),
) -> AuthSession:
    _require_production_auth_origin(request, settings)
    with adaptive_slot("login", settings):
        limiter = _limiter(request)
        key = client_key(request, settings)
        reservation = limiter.reserve_login(key, "identity-choice", settings)
        failed = False
        succeeded = False
        try:
            user = consume_choice(db, payload, key, now)
            raw_token, row, raw_csrf = create_rotated_session(
                db,
                user,
                settings,
                old_raw_token=request.cookies.get(SESSION_COOKIE_NAME),
                now=now,
            )
            row.entered_via_user_id = BOWEN_ID
            if payload.identity == "student":
                row.active_course_id = str(payload.course_id)
            result = _auth_response(db, AuthContext(raw_token, row, user, raw_csrf))
            db.commit()
            succeeded = True
            _set_session_cookie(response, raw_token, settings, request)
            return result
        except PlatformError:
            failed = True
            raise
        except OperationalError as exc:
            if not login_database_overloaded(exc):
                raise
            raise _login_queue_overload(settings) from None
        finally:
            limiter.finish_login(reservation, failed=failed)
            if not succeeded and db.in_transaction():
                db.rollback()


def _login_queue_overload(settings: Settings) -> PlatformError:
    return PlatformError(
        "auth_login_queued",
        "Waiting to enter. Stay on this page; your place in line is kept.",
        429,
        {"position": 0, "retry_after_seconds": settings.auth_login_queue_retry_seconds},
    )


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


@router.patch(
    "/me",
    response_model=AuthSession,
    operation_id="updateCurrentUser",
    responses={
        200: {"model": AuthSession, "description": "Updated profile and current session."},
        401: {"model": Error, "description": "Authentication required."},
        403: {"model": Error, "description": "CSRF failure."},
        409: {"model": Error, "description": "Name or group is managed elsewhere."},
        422: {"model": Error, "description": "Avatar choice, name or group is invalid."},
    },
)
def update_current_user(
    payload: UpdateCurrentUserRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    lock_user_profile(db, context.user.id)
    if "avatar" in payload.model_fields_set:
        update_avatar(context.user, payload.avatar)
    if payload.display_name is not None:
        update_display_name(db, context.user, payload.display_name)
    if payload.course_id is not None:
        from app.modules.org.classes import change_class

        if payload.group_name is not None:
            raise PlatformError("registration_invalid", "Change class and group separately.", 422)
        change_class(db, context.user, str(payload.course_id))
        context.session.active_course_id = str(payload.course_id)
    if payload.group_name is not None:
        change_group(
            db,
            context.user,
            payload.group_name,
            course_id=context.session.active_course_id,
        )
        # The move withdraws this student's old-group voices; commit it, then
        # finish their supplier delete (best effort).
        db.commit()
        finish_withdrawn_voices(db, settings, context.user.id)
    db.flush()
    return _auth_response(db, context)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="changeCurrentPassword",
    responses={
        204: {"description": "Password changed; other sessions revoked."},
        401: {"model": Error, "description": "Authentication or current password failed."},
        403: {"model": Error, "description": "CSRF failure."},
        422: {"model": Error, "description": "New password is invalid."},
    },
)
def change_current_password(
    payload: PasswordChangeRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    change_password(
        db,
        settings,
        user=context.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_session_id_hash=context.session.id_hash,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    now: datetime | None = Depends(get_auth_clock),
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
        now=now,
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
    now: datetime | None = Depends(get_auth_clock),
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
        now=now,
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


@router.get(
    "/registration-options",
    response_model=RegistrationOptions,
    operation_id="getRegistrationOptions",
    openapi_extra={"security": []},
    responses={
        200: {
            "model": RegistrationOptions,
            "description": "Course and existing group names a new student may join.",
        },
        422: {"model": Error, "description": "Registration is not available yet."},
    },
)
def registration_options(db: Session = Depends(get_db)) -> RegistrationOptions:
    """Publish the joinable group names for the registration form.

    Only the group name and a member count are exposed. Member identities
    stay behind authentication: a student picking a group must be able to
    recognise it, not enumerate who is already in it.
    """

    from app.modules.org.classes import default_class_group, registration_classes

    courses = registration_classes(db)
    course = courses[0] if courses else resolve_course(db, None)
    rows = db.execute(
        select(Group.course_id, Group.name, func.count(GroupMember.user_id))
        .outerjoin(GroupMember, GroupMember.group_id == Group.id)
        .where(Group.course_id.in_([item.id for item in courses]))
        .group_by(Group.id, Group.course_id, Group.name)
        .order_by(Group.name)
    ).all()
    return RegistrationOptions(
        course_id=UUID(course.id),
        course_name=course.name,
        groups=[
            RegistrationGroup(name=row[1], member_count=row[2])
            for row in rows
            if row[0] == course.id
        ],
        classes=[
            RegistrationClass(
                course_id=UUID(item.id),
                course_name=item.name,
                group_name=default_class_group(db, item.id).name,
                groups=[
                    RegistrationGroup(name=row[1], member_count=row[2])
                    for row in rows
                    if row[0] == item.id
                ],
            )
            for item in courses
        ],
    )


@router.post(
    "/register",
    response_model=AuthSession,
    status_code=status.HTTP_201_CREATED,
    operation_id="registerStudent",
    openapi_extra={"security": []},
    responses={
        201: {"model": AuthSession, "description": "Account created and session started."},
        403: {"model": Error, "description": "The configured public origin is required."},
        409: {"model": Error, "description": "The username is already taken."},
        413: {"description": "The production gateway rejects oversized registration bodies."},
        429: {"model": Error, "description": "Registration attempts are temporarily limited."},
        422: {"model": Error, "description": "A submitted field is not acceptable."},
    },
)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    now: datetime | None = Depends(get_auth_clock),
) -> AuthSession:
    """Create a student account, attach it to a group and start its session.

    The new account signs in immediately: requiring a second manual login
    right after a successful registration adds a failure step without adding
    any security, because the caller just proved knowledge of the password.
    """

    _require_production_auth_origin(request, settings)
    # Cheap checks first: a bad field is refused before the hash, the queue
    # or the limiter, and a client over its registration limit gets its 429
    # without taking a place in the shared pressure queue.
    username = normalize_username(payload.username)
    normalize_group_name(payload.group_name)
    normalize_display_name(payload.display_name, username)
    limiter = _limiter(request) if settings.is_production else None
    limiter_key = client_key(request, settings) if limiter is not None else ""
    attempt = limiter.consume_registration(limiter_key, settings) if limiter is not None else None
    try:
        result, raw_token = _register_admitted(payload, request, db, settings, now=now)
    except PlatformError as exc:
        # A retryable refusal (queue full, wait timeout, busy turn) did no
        # work; it must not spend the client's registration allowance.
        if limiter is not None and attempt is not None and exc.status_code == 503:
            limiter.refund_registration(limiter_key, attempt)
        raise
    _set_session_cookie(response, raw_token, settings, request)
    return result


def _register_admitted(
    payload: RegisterRequest,
    request: Request,
    db: Session,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[AuthSession, str]:
    # Same unified pressure queue as sign-in (Argon2 + a short write): under
    # host pressure a registration waits instead of piling on.
    with adaptive_slot("login", settings):
        # Hash outside the registration turn so only the short DB write is
        # serialized; nothing has touched the request Session yet, so neither
        # wait below holds a pooled connection.
        password_hash = hash_registration_password(payload.password, settings)
        with registration_turn(settings):
            user, _group = register_student(
                db,
                settings,
                username=payload.username,
                password=payload.password,
                display_name=payload.display_name,
                group_name=payload.group_name,
                course_id=str(payload.course_id) if payload.course_id else None,
                password_hash=password_hash,
            )
            raw_token, session_row, raw_csrf = create_rotated_session(
                db,
                user,
                settings,
                old_raw_token=request.cookies.get(SESSION_COOKIE_NAME),
                now=now,
            )
            result = _auth_response(
                db, AuthContext(raw_token, session_row, user, raw_csrf), raw_csrf
            )
            # Commit inside the turn: the advisory lock ends with this
            # transaction, before the next registrant takes a connection.
            db.commit()
    return result, raw_token


@router.post(
    "/password-resets",
    response_model=PasswordResetResult,
    operation_id="resetStudentPassword",
    responses={
        200: {
            "model": PasswordResetResult,
            "description": "The new password, returned exactly once.",
        },
        403: {"model": Error, "description": "CSRF failure or the caller is not the teacher."},
        404: {"model": Error, "description": "The course or member is not visible."},
        422: {"model": Error, "description": "This account has no resettable password."},
    },
)
def reset_password(
    payload: PasswordResetRequest,
    _csrf_header: str = Header(..., alias="X-CSRF-Token", min_length=32),
    context: AuthContext = Depends(require_authenticated_mutation),
    db: Session = Depends(get_db),
) -> PasswordResetResult:
    """Reset one student's password and return the value to read out in class.

    Self-registered accounts have no email, so there is no self-service
    recovery path; the teacher of the course is the recovery mechanism. The
    scope is checked twice: the caller must teach this course, and the target
    must be a member of that same course.
    """

    caller_role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == str(payload.course_id),
            CourseMember.user_id == context.user.id,
        )
    )
    if caller_role is None:
        # An unauthorized course id stays indistinguishable from a missing one.
        raise not_found()
    if caller_role != "teacher":
        raise forbidden()
    target_role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == str(payload.course_id),
            CourseMember.user_id == str(payload.user_id),
        )
    )
    if target_role is None:
        raise not_found()
    target = db.get(User, str(payload.user_id))
    if target is None or target.status != "active":
        raise not_found()
    password = reset_student_password(db, target=target, new_password=payload.new_password)
    return PasswordResetResult(
        user_id=UUID(target.id),
        username=target.username,
        display_name=target.display_name,
        password=password,
    )
