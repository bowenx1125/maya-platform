"""Session, CSRF and private Demo-account synchronization primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.identity import username_key
from app.core.locks import xact_lock
from app.core.models import Course, CourseMember, Group, GroupMember, SessionRecord, User
from app.core.sqlutil import begin_immediate
from app.modules.auth.credentials import (
    CredentialFileError,
    DemoAccount,
    DesiredAccountGraph,
    account_id,
    catalog_graph_for_sync,
    discard_pending_catalog,
    publish_catalog_snapshot,
)
from app.modules.auth.models import DemoAccountBinding
from app.modules.org.groups import prune_empty_groups
from app.seed import BOWEN_ID, GROUP_DEMO_ID

SESSION_COOKIE_NAME = "maya_session"


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


class AccountSyncError(RuntimeError):
    """Raised when a complete private account graph cannot be applied."""


@dataclass(frozen=True)
class AccountSyncResult:
    """Non-sensitive startup synchronization counters."""

    active_count: int
    created_count: int
    changed_count: int
    disabled_count: int


# The single seeded Demo group ID is stable and is used only to resolve the
# human-readable private-file group key. No group key is emitted to the API.
_GROUP_KEY_ALIASES = {
    "group-demo": GROUP_DEMO_ID,
    "demo": GROUP_DEMO_ID,
    "demo-group": GROUP_DEMO_ID,
    "group_demo": GROUP_DEMO_ID,
}

# These are the fixed identities from the Wave 0 seed. They are eligible for
# first binding by their canonical account key (or by a new key that explicitly
# names the same unbound seeded username), but an arbitrary existing user is
# never silently claimed by a catalog row.
_SEED_ACCOUNT_KEYS = (
    "maya",
    "bowen",
    "kaikai",
    "jade",
)
_SEED_USER_IDS = frozenset(account_id(key) for key in _SEED_ACCOUNT_KEYS)


@dataclass(frozen=True)
class _SyncOutcome:
    result: AccountSyncResult
    resolved_user_ids: dict[str, str]


def _account_fingerprint(account: DemoAccount, settings: Settings) -> str:
    """Hash credential/authorization material without display metadata.

    The keyed digest is stable across process restarts that share the session
    secret, while preventing a database reader from directly comparing a
    stored fingerprint to common Demo passwords. ``account_key`` is the
    durable binding key, not mutable material; ``display_name`` is expressly
    excluded so a presentation-only rename does not revoke sessions.
    """

    password_material = account.password_hash or account.password
    canonical = json.dumps(
        (account.username, account.role, account.group_key or "", password_material),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(settings.secret_bytes, canonical, hashlib.sha256).hexdigest()


def _normalise_group_label(value: str) -> str:
    return value.strip().casefold().replace(" ", "-")


def _resolve_group(
    account: DemoAccount,
    groups: dict[str, Group],
    groups_by_name: dict[str, Group],
    course_id: str,
) -> str:
    if account.role == "teacher":
        if account.group_key is not None:
            raise AccountSyncError("demo account catalog contains an invalid group")
        return ""
    if not account.group_key:
        raise AccountSyncError("demo account catalog contains an invalid group")
    label = _normalise_group_label(account.group_key)
    candidate_id = _GROUP_KEY_ALIASES.get(label, account.group_key)
    candidate = groups.get(candidate_id)
    if candidate is None:
        candidate = groups_by_name.get(label)
    if candidate is None or candidate.course_id != course_id:
        raise AccountSyncError("demo account catalog contains an invalid group")
    return candidate.id


def lock_user_profile(db: Session, user_id: str) -> None:
    """Serialize explicit membership choices with startup projection and erasure."""
    xact_lock(db, f"user-profile:{user_id}")


def revoke_user_sessions(
    session: Session,
    user_id: str,
    timestamp: datetime,
    *,
    except_session_id_hash: str | None = None,
) -> None:
    """Revoke live sessions for a user, optionally preserving one session.

    Deactivating an account has to take effect on sessions that already
    exist, not only on the next login, so the roster edit path calls this
    alongside the catalog sync that first needed it.
    """

    rows = session.scalars(select(SessionRecord).where(SessionRecord.user_id == user_id)).all()
    for row in rows:
        if row.revoked_at is None and row.id_hash != except_session_id_hash:
            row.revoked_at = timestamp


def _resolve_catalog_users(
    graph: DesiredAccountGraph,
    users: Sequence[User],
    bindings: Sequence[DemoAccountBinding],
) -> dict[str, User | None]:
    """Resolve every row before mutating anything in the writer transaction."""

    users_by_id = {row.id: row for row in users}
    users_by_username: dict[str, list[User]] = {}
    for row in users:
        users_by_username.setdefault(username_key(row.username), []).append(row)

    bindings_by_key: dict[str, DemoAccountBinding] = {}
    bindings_by_user: dict[str, DemoAccountBinding] = {}
    for existing_binding in bindings:
        if (
            existing_binding.account_key in bindings_by_key
            or existing_binding.user_id in bindings_by_user
        ):
            raise AccountSyncError("demo account catalog bindings are inconsistent")
        bindings_by_key[existing_binding.account_key] = existing_binding
        bindings_by_user[existing_binding.user_id] = existing_binding

    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    seen_users: set[str] = set()
    resolved: dict[str, User | None] = {}
    for account in graph.accounts:
        name_key = username_key(account.username)
        if account.account_key in seen_keys or name_key in seen_names:
            raise AccountSyncError("demo account catalog contains duplicate identities")
        seen_keys.add(account.account_key)
        seen_names.add(name_key)

        account_binding = bindings_by_key.get(account.account_key)
        resolved_user: User | None
        if account_binding is not None:
            resolved_user = users_by_id.get(account_binding.user_id)
            if resolved_user is None:
                raise AccountSyncError("demo account catalog binding is inconsistent")
        else:
            deterministic = users_by_id.get(account.user_id)
            candidates = users_by_username.get(name_key, [])
            if len(candidates) > 1:
                raise AccountSyncError("demo account catalog conflicts with an existing user")
            named = candidates[0] if candidates else None
            if named is not None:
                owner = bindings_by_user.get(named.id)
                if owner is not None and owner.account_key != account.account_key:
                    raise AccountSyncError("demo account catalog conflicts with an existing user")
                if named.id not in _SEED_USER_IDS and named.id != account.user_id:
                    raise AccountSyncError("demo account catalog conflicts with an existing user")
                if deterministic is not None and deterministic.id != named.id:
                    raise AccountSyncError("demo account catalog conflicts with an existing user")
                resolved_user = named
            elif deterministic is not None:
                owner = bindings_by_user.get(deterministic.id)
                if owner is not None:
                    raise AccountSyncError("demo account catalog conflicts with an existing user")
                # A deterministic row that has drifted away from its username
                # is not safe to claim. It may be a non-Demo application user.
                if username_key(deterministic.username) != name_key:
                    raise AccountSyncError("demo account catalog conflicts with an existing user")
                resolved_user = deterministic
            else:
                resolved_user = None

        if resolved_user is not None:
            conflicting = users_by_username.get(name_key, [])
            if any(other.id != resolved_user.id for other in conflicting):
                raise AccountSyncError("demo account catalog conflicts with an existing user")
            if resolved_user.id in seen_users:
                raise AccountSyncError("demo account catalog contains duplicate identities")
            seen_users.add(resolved_user.id)
        elif account.user_id in seen_users:
            raise AccountSyncError("demo account catalog contains duplicate identities")
        else:
            seen_users.add(account.user_id)
        resolved[account.account_key] = resolved_user
    return resolved


def _sync_graph_in_session(
    session: Session,
    settings: Settings,
    graph: DesiredAccountGraph,
    *,
    transaction_started: bool = False,
) -> _SyncOutcome:
    """Apply the complete desired graph in one transaction.

    Startup runs this under the database's startup advisory lock, so only one
    replica synchronizes the catalog at a time.

    The returned mapping is only published by the Database wrapper after its
    commit succeeds. A failed commit therefore cannot advance auth reads.
    """

    if transaction_started:
        if not session.in_transaction():
            raise AccountSyncError("account sync requires an active transaction")
    elif session.in_transaction():
        raise AccountSyncError("account sync requires a fresh transaction")

    try:
        if not transaction_started:
            # Opens the transaction; serialization comes from the startup lock.
            begin_immediate(session)

        course = session.scalar(select(Course).where(Course.code == "demo-course-001"))
        if course is None:
            course = session.scalar(select(Course).order_by(Course.id))
        if course is None:
            raise AccountSyncError("demo account catalog requires a seeded course")

        profile_ids = set(session.scalars(select(DemoAccountBinding.user_id)))
        profile_ids.update(account.user_id for account in graph.accounts)
        for user_id in sorted(profile_ids):
            lock_user_profile(session, user_id)

        group_rows = session.scalars(select(Group)).all()
        groups = {row.id: row for row in group_rows}
        groups_by_name = {
            _normalise_group_label(row.name): row
            for row in group_rows
            if row.course_id == course.id
        }
        default_course = course
        from app.modules.org.classes import (
            CLASS_TEACHER_COURSE_IDS,
            default_class_group,
            registration_classes,
        )

        classes = registration_classes(session)
        courses_by_code = {row.code.casefold(): row for row in classes}
        class_ids = {row.id for row in classes}
        teacher_classes = {row.id: row for row in classes}

        users = session.scalars(select(User).order_by(User.id)).all()
        bindings = session.scalars(
            select(DemoAccountBinding).order_by(DemoAccountBinding.account_key)
        ).all()
        resolved_users = _resolve_catalog_users(graph, users, bindings)
        users_by_id = {row.id: row for row in users}

        course_members = session.scalars(select(CourseMember)).all()
        group_members = session.scalars(select(GroupMember)).all()
        course_members_by_user: dict[str, list[CourseMember]] = {}
        group_members_by_user: dict[str, list[GroupMember]] = {}
        for course_row in course_members:
            course_members_by_user.setdefault(course_row.user_id, []).append(course_row)
        for group_row in group_members:
            group_members_by_user.setdefault(group_row.user_id, []).append(group_row)

        bindings_by_key = {row.account_key: row for row in bindings}
        timestamp = utc_now()
        created_count = 0
        changed_count = 0
        resolved_user_ids: dict[str, str] = {}
        desired_keys = {account.account_key for account in graph.accounts}

        for account in graph.accounts:
            user = resolved_users[account.account_key]
            binding = bindings_by_key.get(account.account_key)
            is_new = user is None
            if user is None:
                user = User(
                    id=account.user_id,
                    username=account.username,
                    display_name=account.display_name,
                    status="active",
                    created_at=timestamp,
                )
                session.add(user)
                users_by_id[user.id] = user
                created_count += 1

            resolved_user_ids[account.account_key] = user.id
            fingerprint = _account_fingerprint(account, settings)
            material_changed = (
                is_new
                or binding is None
                or not binding.active
                or binding.material_fingerprint != fingerprint
                or user.status != "active"
            )

            # Username/display name are current projections of the catalog;
            # only username participates in the material fingerprint.
            user.username = account.username
            user.display_name = account.display_name
            user.status = "active"

            existing_courses = course_members_by_user.get(user.id, [])
            existing_groups = group_members_by_user.get(user.id, [])
            course = default_course
            if account.role == "teacher":
                key = username_key(account.username)
                if key in CLASS_TEACHER_COURSE_IDS:
                    course = teacher_classes[CLASS_TEACHER_COURSE_IDS[key]]
                else:
                    course = courses_by_code.get(key, default_course)
            elif (
                account.role == "student"
                and not material_changed
                and len(existing_courses) == 1
                and existing_courses[0].role == "student"
                and existing_courses[0].course_id in class_ids
            ):
                course = session.get(Course, existing_courses[0].course_id) or default_course
            if account.role == "teacher":
                desired_group_id = ""
            elif course.id != default_course.id:
                desired_group_id = default_class_group(session, course.id).id
            else:
                desired_group_id = _resolve_group(account, groups, groups_by_name, course.id)
            if binding is not None and binding.selected_group_id is not None:
                selected_group = groups.get(binding.selected_group_id)
                if (
                    not material_changed
                    and account.role == "student"
                    and selected_group is not None
                    and selected_group.course_id == course.id
                ):
                    desired_group_id = selected_group.id
                else:
                    binding.selected_group_id = None
            # The chooser enrolls Bowen additively; a replica restart must not
            # project those memberships away or revoke his existing sessions.
            preserve_bowen_memberships = (
                user.id == BOWEN_ID and account.role == "student" and not material_changed
            )
            desired_courses = {course.id}
            if preserve_bowen_memberships:
                desired_courses.update(row.course_id for row in existing_courses)
            if account.role == "teacher":
                created_class_ids = {
                    item.id for item in courses_by_code.values() if item.code.startswith("class-")
                }
                desired_courses.update(
                    row.course_id
                    for row in existing_courses
                    if row.role == "teacher" and row.course_id in created_class_ids
                )
            if account.role == "teacher" and username_key(account.username) == "maya":
                desired_courses = {item.id for item in courses_by_code.values()}
            kept_course = next(
                (
                    row
                    for row in existing_courses
                    if row.course_id == course.id and row.role == account.role
                ),
                None,
            )
            prior_group = next(
                (row for row in existing_groups if row.group_id == desired_group_id),
                None,
            )
            if {
                row.course_id for row in existing_courses if row.role == account.role
            } != desired_courses or any(row.role != account.role for row in existing_courses):
                material_changed = True
            if account.role == "teacher":
                if existing_groups:
                    material_changed = True
            elif not preserve_bowen_memberships and (
                len(existing_groups) != 1 or prior_group is None
            ):
                material_changed = True

            # Enforce the complete desired course/group graph. Existing seed
            # leader membership is preserved when the desired group remains.
            for course_row in existing_courses:
                if course_row.course_id not in desired_courses or course_row.role != account.role:
                    session.delete(course_row)
            if kept_course is None:
                session.add(
                    CourseMember(
                        course_id=course.id,
                        user_id=user.id,
                        role=account.role,
                        created_at=timestamp,
                    )
                )

            for extra_course_id in desired_courses - {course.id}:
                if not any(
                    row.course_id == extra_course_id and row.role == account.role
                    for row in existing_courses
                ):
                    session.add(
                        CourseMember(
                            course_id=extra_course_id,
                            user_id=user.id,
                            role=account.role,
                            created_at=timestamp,
                        )
                    )

            for group_row in existing_groups:
                if not preserve_bowen_memberships and (
                    not desired_group_id or group_row is not prior_group
                ):
                    session.delete(group_row)
            if desired_group_id and prior_group is None:
                session.add(
                    GroupMember(
                        group_id=desired_group_id,
                        user_id=user.id,
                        role="member",
                        created_at=timestamp,
                    )
                )

            if binding is None:
                session.add(
                    DemoAccountBinding(
                        account_key=account.account_key,
                        user_id=user.id,
                        material_fingerprint=fingerprint,
                        active=True,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
            elif (
                binding.user_id != user.id
                or binding.material_fingerprint != fingerprint
                or not binding.active
            ):
                binding.user_id = user.id
                binding.material_fingerprint = fingerprint
                binding.active = True
                binding.updated_at = timestamp

            if material_changed and not is_new:
                revoke_user_sessions(session, user.id, timestamp)
                changed_count += 1

        # Only users owned by a durable catalog binding can be disabled. A
        # seeded/non-Demo application user is intentionally left untouched.
        disabled_count = 0
        groups_to_prune: dict[str, set[str]] = {}
        for binding in bindings:
            if binding.account_key in desired_keys:
                continue
            user = users_by_id.get(binding.user_id)
            if user is None:
                raise AccountSyncError("demo account catalog binding is inconsistent")
            had_live_state = binding.active or user.status != "inactive"
            if had_live_state:
                disabled_count += 1
            binding.active = False
            binding.updated_at = timestamp
            user.status = "inactive"
            revoke_user_sessions(session, user.id, timestamp)
            for course_row in course_members_by_user.get(user.id, []):
                session.delete(course_row)
            for group_row in group_members_by_user.get(user.id, []):
                groups_to_prune.setdefault(groups[group_row.group_id].course_id, set()).add(
                    group_row.group_id
                )
                session.delete(group_row)

        session.flush()
        for course_id in sorted(groups_to_prune):
            prune_empty_groups(session, course_id, groups_to_prune[course_id])
        return _SyncOutcome(
            result=AccountSyncResult(
                active_count=len(graph.accounts),
                created_count=created_count,
                changed_count=changed_count,
                disabled_count=disabled_count,
            ),
            resolved_user_ids=resolved_user_ids,
        )
    except AccountSyncError:
        session.rollback()
        raise
    except (IntegrityError, SQLAlchemyError):
        session.rollback()
        raise AccountSyncError("demo account catalog could not be synchronized") from None
    except Exception:
        session.rollback()
        raise AccountSyncError("demo account catalog could not be synchronized") from None


def _catalog_for_sync(settings: Settings, graph: DesiredAccountGraph | None) -> DesiredAccountGraph:
    if graph is not None:
        return graph
    try:
        return catalog_graph_for_sync(settings)
    except CredentialFileError:
        raise AccountSyncError("demo account catalog could not be parsed") from None


def sync_demo_accounts(
    target: Session | Database,
    settings: Settings,
    graph: DesiredAccountGraph | None = None,
) -> AccountSyncResult:
    """Synchronize one prepared graph and publish it only after commit."""

    desired = _catalog_for_sync(settings, graph)
    if isinstance(target, Database):
        try:
            with target.session() as session:
                outcome = _sync_graph_in_session(session, settings, desired)
        except Exception:
            # Keep an already-published snapshot untouched. A first-startup
            # pending graph is discarded so a failed process cannot expose it.
            discard_pending_catalog(settings)
            raise AccountSyncError("demo account catalog could not be synchronized") from None
        publish_catalog_snapshot(settings, desired, outcome.resolved_user_ids)
        return outcome.result
    outcome = _sync_graph_in_session(target, settings, desired)
    # The caller owns this Session's commit. Do not publish before that commit
    # succeeds; startup should use ``bootstrap_demo_accounts`` for a complete
    # seed+sync boundary.
    return outcome.result


def bootstrap_demo_accounts(
    target: Database,
    settings: Settings,
    seed_callback: Callable[[Session], None],
    graph: DesiredAccountGraph | None = None,
) -> AccountSyncResult:
    """Seed and synchronize in one transaction (under the startup lock).

    The callback is injected so the auth module does not own the Wave 0 seed
    implementation. A caller can wire this helper from the composition root
    without changing public contracts.
    """

    desired = _catalog_for_sync(settings, graph)
    try:
        with target.session() as session:
            begin_immediate(session)
            seed_callback(session)
            outcome = _sync_graph_in_session(
                session,
                settings,
                desired,
                transaction_started=True,
            )
    except AccountSyncError:
        discard_pending_catalog(settings)
        raise
    except Exception:
        discard_pending_catalog(settings)
        raise AccountSyncError("demo account bootstrap failed") from None
    publish_catalog_snapshot(settings, desired, outcome.resolved_user_ids)
    return outcome.result


# Explicit aliases make the startup seam discoverable without exposing any
# private catalog field through a route or DTO.
synchronize_demo_accounts = sync_demo_accounts
sync_demo_account_catalog = sync_demo_accounts


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
        expires_at=timestamp + settings.session_ttl,
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
