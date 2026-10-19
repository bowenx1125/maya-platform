"""Who may continue an ordinary Team Chat with someone else's Team.

Shared by the Team recheck (``teams.service``), the learning provenance fence
(``learning.service``) and the Provider dispatch checks so they can never
disagree again. Two non-owners qualify: a course member using a teacher's
published public Team, and a course teacher using a student's public Team.
"""

from __future__ import annotations

import logging

from app.modules.knowledge.services import course_member_role
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion
from sqlalchemy import select
from sqlalchemy.orm import Session

LOGGER = logging.getLogger("maya.teams")


def log_team_chat_refused(team: Team, user_id: str, reason: str, *, check: str) -> None:
    """Say why a Team Chat was refused before it is answered as not found.

    Bug (2026-10-19): a teacher's sends to a student's public Team 404ed with
    nothing in the logs to say which check refused them.
    """

    LOGGER.warning(
        "Team chat refused check=%s team_id=%s user_id=%s owner_user_id=%s "
        "ownership_scope=%s visibility=%s reason=%s",
        check,
        team.id,
        user_id,
        team.owner_user_id,
        team.ownership_scope,
        team.visibility,
        reason,
    )


def live_teacher_publication(
    db: Session, team: Team, version: TeamVersion
) -> CourseTeamPublication | None:
    """The live publication that makes this personal Team a teacher's public
    Team for this exact version, as the Maya Team recheck reads it."""

    if (
        team.ownership_scope != "personal"
        or team.visibility != "public"
        or team.group_id is not None
        or team.owner_user_id is None
        or course_member_role(db, team.owner_user_id, team.course_id) != "teacher"
    ):
        return None
    return db.scalar(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team.id,
            CourseTeamPublication.team_version_id == version.id,
            CourseTeamPublication.course_id == team.course_id,
            CourseTeamPublication.publisher_user_id == team.owner_user_id,
            CourseTeamPublication.authorization_epoch == team.authorization_epoch,
            # Saving a new version keeps the old one's publication as
            # "retained", as for Maya Team Chats; a revoke ends both.
            CourseTeamPublication.state.in_(("published", "retained")),
        )
    )


def teacher_uses_student_public_team(db: Session, user_id: str, team: Team) -> bool:
    """A course teacher chatting with a student's public Team.

    Bug (2026-10-19): ``can_read_team`` listed a student's public Team to the
    course's teachers and the Chat opened, but the send recheck required the
    owner or a student inside the group, so the teacher's first message got
    not found. The teacher uses it as themselves: every member, RAG source
    and Knowledge Set is still checked against what the teacher may read, so
    a student's private Knowledge is refused, never borrowed. Editing stays
    with the owner.
    """

    if (
        team.deleted_at is not None
        or team.visibility != "public"
        or team.owner_user_id is None
        or team.owner_user_id == user_id
    ):
        return False
    if course_member_role(db, user_id, team.course_id) != "teacher":
        return False
    return course_member_role(db, team.owner_user_id, team.course_id) == "student"


def chat_team_open_to_non_owner(
    db: Session,
    *,
    actor_user_id: str,
    team_id: str | None,
    team_version_id: str | None,
    team_authorization_epoch: int | None,
) -> bool:
    """True when someone other than the Team owner may send in an ordinary
    Team Chat with this frozen Team version: a teacher's live public Team, or
    a student's public Team used by a course teacher."""

    if chat_team_is_live_teacher_public(
        db,
        team_id=team_id,
        team_version_id=team_version_id,
        team_authorization_epoch=team_authorization_epoch,
    ):
        return True
    if team_id is None or team_version_id is None or team_authorization_epoch is None:
        return False
    team = db.get(Team, team_id)
    version = db.get(TeamVersion, team_version_id)
    return (
        team is not None
        and version is not None
        and version.team_id == team.id
        and team.authorization_epoch == team_authorization_epoch
        and version.authorization_epoch == team_authorization_epoch
        and teacher_uses_student_public_team(db, actor_user_id, team)
    )


def chat_team_is_live_teacher_public(
    db: Session,
    *,
    team_id: str | None,
    team_version_id: str | None,
    team_authorization_epoch: int | None,
) -> bool:
    """True when an ordinary Team Chat's frozen Team version is still a
    teacher's live public Team, so a student who is not the owner may send.

    Bug (2026-10-19): #186 let the recheck and the send through, but the
    Provider dispatch checks still required the Team owner, so every member
    of a student's Chat failed with team_context_changed before any model call.
    """

    if team_id is None or team_version_id is None or team_authorization_epoch is None:
        return False
    team = db.get(Team, team_id)
    version = db.get(TeamVersion, team_version_id)
    if (
        team is None
        or version is None
        or team.deleted_at is not None
        or version.team_id != team.id
        or team.authorization_epoch != team_authorization_epoch
        or version.authorization_epoch != team_authorization_epoch
    ):
        return False
    return live_teacher_publication(db, team, version) is not None
