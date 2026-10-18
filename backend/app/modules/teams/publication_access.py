"""Who may continue an ordinary Team Chat with someone else's Team.

Shared by the Team recheck (``teams.service``) and the learning provenance
fence (``learning.service``) so the two can never disagree again.
"""

from __future__ import annotations

from app.modules.knowledge.services import course_member_role
from app.modules.teams.models import CourseTeamPublication, Team, TeamVersion
from sqlalchemy import select
from sqlalchemy.orm import Session


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
