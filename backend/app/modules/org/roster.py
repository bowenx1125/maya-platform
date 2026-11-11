"""Teacher-owned roster reads and account edits for one course.

Two account sources coexist behind a single roster.  Only one of them is
editable, and the difference is not cosmetic:

``catalog``
    The fixed Demo identities.  Their name and status are projections of
    ``accounts.private.md``, which is mounted read-only and re-applied on
    every start, so an edit here would silently disappear at the next
    restart.

``database``
    Self-registered students.  Their credential lives in ``user_credentials``
    and nothing rewrites it behind the teacher's back, so this is the only
    source an edit can durably change.

Rather than accept an edit and lose it, the service rejects the write and
names the source.  The validation mirrors ``auth.registration`` deliberately:
the rules are the same, but the failures carry a roster-specific code so a
form can tell a rejected edit from a rejected registration.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import or_, select, union_all
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found, unprocessable
from app.core.identity import normalize_group_name as canonical_group_name
from app.core.models import (
    Agent,
    CourseMember,
    Group,
    GroupMember,
    KnowledgeDocument,
    User,
)
from app.modules.auth.models import DemoAccountBinding
from app.modules.auth.service import lock_user_profile, revoke_user_sessions
from app.modules.org.access import WorkspaceMember
from app.modules.org.groups import prune_empty_groups
from app.modules.org.names import resolve_named_group

ACTIVE = "active"
INACTIVE = "inactive"
ASSIGNABLE_STATUSES = frozenset({ACTIVE, INACTIVE})

SOURCE_CATALOG = "catalog"
SOURCE_DATABASE = "database"

DISPLAY_NAME_MAX = 200
GROUP_NAME_MAX = 200


@dataclass(frozen=True)
class RosterRow:
    """One course member with the account facts a teacher acts on."""

    user: User
    role: str
    source: str
    groups: list[Group]

    @property
    def editable(self) -> bool:
        return self.source == SOURCE_DATABASE


def _invalid(message: str) -> PlatformError:
    """Return the stable domain code for a rejected roster edit."""

    return unprocessable("member_update_invalid", message)


def _collapsed(raw: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw).split())


def normalize_display_name(raw: str) -> str:
    value = _collapsed(raw)
    if not value:
        raise _invalid("A display name is required.")
    if len(value) > DISPLAY_NAME_MAX:
        raise _invalid(f"A display name may not exceed {DISPLAY_NAME_MAX} characters.")
    return value


def normalize_group_name(raw: str) -> str:
    try:
        return canonical_group_name(raw)
    except ValueError as error:
        raise _invalid(str(error)) from None


def normalize_status(raw: str) -> str:
    value = raw.strip().casefold()
    if value not in ASSIGNABLE_STATUSES:
        raise _invalid("A status must be either 'active' or 'inactive'.")
    return value


def _account_source(user: User, catalog_user_ids: frozenset[str]) -> str:
    if user.id in catalog_user_ids:
        return SOURCE_CATALOG
    return SOURCE_DATABASE


def _catalog_user_ids(db: Session) -> frozenset[str]:
    return frozenset(
        db.scalars(
            select(DemoAccountBinding.user_id).where(DemoAccountBinding.active.is_(True))
        ).all()
    )


def _groups_by_user(db: Session, course_id: str) -> dict[str, list[Group]]:
    rows = db.execute(
        select(WorkspaceMember.user_id, Group)
        .join(Group, Group.id == WorkspaceMember.group_id)
        .where(Group.course_id == course_id)
        .order_by(Group.name)
    ).all()
    grouped: dict[str, list[Group]] = {}
    for user_id, group in rows:
        grouped.setdefault(user_id, []).append(group)
    return grouped


def course_roster(db: Session, course_id: str) -> list[RosterRow]:
    """Return every member of the course with source and group attribution."""

    catalog_user_ids = _catalog_user_ids(db)
    grouped = _groups_by_user(db, course_id)
    rows = db.execute(
        select(User, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id)
        .order_by(CourseMember.role, User.display_name, User.id)
    ).all()
    return [
        RosterRow(
            user=user,
            role=role,
            source=_account_source(user, catalog_user_ids),
            groups=grouped.get(user.id, []),
        )
        for user, role in rows
    ]


def _roster_row(db: Session, course_id: str, user_id: str) -> RosterRow:
    row = db.execute(
        select(User, CourseMember.role)
        .join(CourseMember, CourseMember.user_id == User.id)
        .where(CourseMember.course_id == course_id, User.id == user_id)
    ).first()
    if row is None:
        # A member of another course must be indistinguishable from one that
        # does not exist.
        raise not_found()
    user, role = row
    return RosterRow(
        user=user,
        role=role,
        source=_account_source(user, _catalog_user_ids(db)),
        groups=_groups_by_user(db, course_id).get(user.id, []),
    )


def move_to_group(db: Session, course_id: str, user: User, group_name: str) -> None:
    """Make ``group_name`` the member's only group in this course.

    The name is the address, exactly as it is during registration: the first
    use of a name creates the group and every later use joins that row, so a
    teacher moving a student into "Team Aurora" lands them beside the
    students who typed the same name themselves.

    The student's cloned voices in a group they leave are withdrawn in the
    same transaction; the caller finishes the supplier delete after commit
    (``finish_withdrawn_voices``).
    """

    from app.modules.voices.withdrawal import withdraw_group_voices

    now = datetime.now(UTC)
    group = resolve_named_group(db, course_id, group_name)
    current = db.scalars(
        select(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .where(Group.course_id == course_id, GroupMember.user_id == user.id)
    ).all()
    left = [membership.group_id for membership in current if membership.group_id != group.id]
    for membership in current:
        if membership.group_id != group.id:
            db.delete(membership)
    withdraw_group_voices(db, user.id, left)
    if not any(membership.group_id == group.id for membership in current):
        db.add(
            GroupMember(
                group_id=group.id,
                user_id=user.id,
                role="member",
                created_at=now,
            )
        )
    db.flush()


def update_member(
    db: Session,
    *,
    course_id: str,
    actor: User,
    user_id: str,
    display_name: str | None = None,
    group_name: str | None = None,
    status: str | None = None,
) -> RosterRow:
    """Apply a teacher's edit to one member of their course."""

    if display_name is None and group_name is None and status is None:
        raise _invalid("An edit must change at least one field.")

    lock_user_profile(db, user_id)
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    row = _roster_row(db, course_id, user_id)
    if status is not None and row.user.id == actor.id:
        # Checked before the source rule so the answer names the reason that
        # holds for every teacher: losing your own session to a mis-click is
        # not recoverable from inside the product.  Today's teachers are all
        # catalog accounts, so the other order would leave this unreachable.
        raise conflict("self_status_forbidden", "You cannot change your own account status.")
    if not row.editable:
        raise conflict(
            "account_read_only",
            "This account is provisioned at startup and cannot be edited here.",
            {"source": row.source},
        )

    if display_name is not None:
        row.user.display_name = normalize_display_name(display_name)
    if status is not None:
        resolved = normalize_status(status)
        row.user.status = resolved
        if resolved == INACTIVE:
            # Deactivation has to end sessions that already exist; the auth
            # context rejects a non-active user, but the row stays until it
            # is revoked.
            revoke_user_sessions(db, row.user.id, datetime.now(UTC))
    if group_name is not None:
        previous_groups = list(
            db.scalars(
                select(GroupMember.group_id)
                .join(Group, Group.id == GroupMember.group_id)
                .where(Group.course_id == course_id, GroupMember.user_id == user_id)
            )
        )
        move_to_group(db, course_id, row.user, normalize_group_name(group_name))
        prune_empty_groups(db, course_id, previous_groups)

    db.flush()
    return _roster_row(db, course_id, user_id)


def delete_member(
    db: Session,
    *,
    course_id: str,
    actor: User,
    user_id: str,
    data_root: Path | None,
) -> list[str]:
    """Remove a student account, its public/private work and grades atomically.

    Unknown references abort the transaction. A class teacher cannot erase
    work from another class or the historical records belonging to others.
    """
    from app.core.db import registered_metadata
    from app.core.locks import xact_lock
    from app.core.models import VoiceProfile
    from app.modules.auth.registration import lock_password_identity
    from app.modules.knowledge_sets.models import KnowledgeSet
    from app.modules.learning.models import (
        AssessmentAttempt,
        AssessmentCourseReport,
        AssessmentCourseReportEvidence,
        AssessmentCourseReportRevision,
    )
    from app.modules.purge import purge_ids
    from app.modules.real_delete import (
        hard_delete_agent,
        hard_delete_conversation,
        hard_delete_document,
        hard_delete_knowledge_set,
        hard_delete_team,
    )
    from app.modules.teams.models import Team
    from app.modules.voices.withdrawal import withdraw_group_voices
    from app.modules.workspace.models import Conversation

    lock_user_profile(db, user_id)
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    row = _roster_row(db, course_id, user_id)
    if row.user.id == actor.id:
        raise conflict("self_delete_forbidden", "You cannot delete your own account.")
    if not row.editable:
        raise conflict(
            "account_read_only",
            "This account is provisioned at startup and cannot be edited here.",
            {"source": row.source},
        )
    if (
        row.role != "student"
        or db.scalar(
            select(CourseMember.user_id)
            .where(CourseMember.user_id == user_id, CourseMember.role == "teacher")
            .limit(1)
        )
        is not None
    ):
        raise conflict("teacher_delete_forbidden", "Teacher accounts cannot be deleted here.")
    lock_password_identity(db, user_id)
    previous_groups = list(
        db.scalars(
            select(GroupMember.group_id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(Group.course_id == course_id, GroupMember.user_id == user_id)
        )
    )
    taught = set(
        db.scalars(
            select(CourseMember.course_id).where(
                CourseMember.user_id == actor.id, CourseMember.role == "teacher"
            )
        )
    )
    scoped_rows = []
    for table in registered_metadata().tables.values():
        user_columns = [
            column
            for fk in table.foreign_key_constraints
            if fk.referred_table.name == "users"
            for column in fk.columns
        ]
        if not user_columns:
            continue
        owned = or_(*(column == user_id for column in user_columns))
        if "course_id" in table.c:
            scoped_rows.append(select(table.c.course_id).where(owned))
        elif "group_id" in table.c:
            scoped_rows.append(
                select(Group.course_id).join(table, table.c.group_id == Group.id).where(owned)
            )
        if "course_id" not in table.c:
            for parent_name, foreign_column in [
                ("assessment_activities", "activity_id"),
                ("knowledge_sets", "knowledge_set_id"),
                ("knowledge_documents", "document_id"),
                ("teams", "team_id"),
                ("agents", "agent_id"),
                ("learning_assessments", "assessment_id"),
                ("agent_conversations", "conversation_id"),
            ]:
                if foreign_column in table.c:
                    parent = registered_metadata().tables[parent_name]
                    scoped_rows.append(
                        select(parent.c.course_id)
                        .join(table, table.c[foreign_column] == parent.c.id)
                        .where(owned)
                    )
        if "asset_id" in table.c:
            metadata = registered_metadata()
            assets = metadata.tables["knowledge_assets"]
            sets = metadata.tables["knowledge_sets"]
            scoped_rows.append(
                select(sets.c.course_id)
                .select_from(
                    sets.join(assets, assets.c.knowledge_set_id == sets.c.id).join(
                        table, table.c.asset_id == assets.c.id
                    )
                )
                .where(owned)
            )
    report_evidence = (
        select(AssessmentCourseReportEvidence.report_revision_id)
        .join(AssessmentAttempt, AssessmentAttempt.id == AssessmentCourseReportEvidence.attempt_id)
        .where(AssessmentAttempt.actor_user_id == user_id)
    )
    related_reports = select(AssessmentCourseReportRevision.report_id).where(
        or_(
            AssessmentCourseReportRevision.report_json.contains(user_id),
            AssessmentCourseReportRevision.id.in_(report_evidence),
        )
    )
    affected = {value for value in db.scalars(union_all(*scoped_rows)) if value is not None}
    affected.update(
        db.scalars(
            select(AssessmentCourseReport.course_id).where(
                AssessmentCourseReport.id.in_(related_reports)
            )
        )
    )
    if not affected.issubset(taught):
        raise conflict(
            "account_delete_scope_forbidden",
            "A teacher who manages all this account's classes must delete it.",
        )
    for affected_course in sorted(affected):
        xact_lock(db, f"account-grade-erasure:{affected_course}")
    report_ids = list(
        db.scalars(
            select(AssessmentCourseReport.id).where(
                AssessmentCourseReport.id.in_(related_reports),
                AssessmentCourseReport.course_id.in_(affected),
            )
        )
    )
    # Cached class summaries include individual grades; invalidate those copies,
    # while leaving every other learner's source records intact.
    if set(report_ids) != purge_ids(db, "assessment_course_reports", report_ids):
        raise conflict(
            "account_delete_blocked",
            "This account still has protected references. Nothing was deleted.",
        )
    profiles = list(
        db.scalars(select(VoiceProfile).where(VoiceProfile.consent_actor_user_id == user_id))
    )
    profile_ids = [profile.id for profile in profiles]
    withdraw_group_voices(
        db, user_id, [profile.group_id for profile in profiles if profile.group_id]
    )
    for conversation in list(
        db.scalars(select(Conversation).where(Conversation.user_id == user_id))
    ):
        hard_delete_conversation(db, conversation, data_root)
    for team in list(db.scalars(select(Team).where(Team.owner_user_id == user_id))):
        hard_delete_team(db, team)
    for agent in list(db.scalars(select(Agent).where(Agent.owner_user_id == user_id))):
        hard_delete_agent(db, agent, data_root)
    for document in list(
        db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.owner_user_id == user_id))
    ):
        hard_delete_document(db, document, data_root)
    for knowledge_set in list(
        db.scalars(select(KnowledgeSet).where(KnowledgeSet.owner_user_id == user_id))
    ):
        hard_delete_knowledge_set(db, knowledge_set, data_root)
    if user_id not in purge_ids(db, "users", [user_id]):
        raise conflict(
            "account_delete_blocked",
            "This account still has protected references. Nothing was deleted.",
        )
    db.flush()
    prune_empty_groups(db, course_id, previous_groups)
    return profile_ids
