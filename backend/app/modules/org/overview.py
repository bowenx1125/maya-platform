"""A group's members, test results and recent work, for a course teacher.

Formal attempts are readable without entering the group. Private Agents,
Teams, RAG and voices stay behind that visit. The read changes nothing.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import (
    Agent,
    AgentVersion,
    Group,
    GroupMember,
    KnowledgeDocument,
    User,
    VoiceProfile,
)
from app.modules.auth.service import AuthContext
from app.modules.learning.reports import read_group_results
from app.modules.org.schemas import (
    GroupOverview,
    OverviewEvent,
    OverviewMember,
    OverviewResult,
    OverviewWork,
)
from app.modules.teams.models import Team

RECENT_EVENTS = 20


def group_overview(
    db: Session,
    context: AuthContext,
    group: Group,
    *,
    include_private: bool,
) -> GroupOverview:
    students = db.execute(
        select(User.id, User.display_name, User.avatar)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group.id, User.status == "active")
        .order_by(User.display_name, User.id)
    ).all()
    names = {row.id: row.display_name for row in students}
    events: list[OverviewEvent] = []

    def event(kind: str, at: datetime | None, user_id: str | None, title: str) -> None:
        if at is None or user_id not in names:
            return
        events.append(
            OverviewEvent.model_validate(
                {
                    "kind": kind,
                    "at": at,
                    "user_id": UUID(user_id),
                    "display_name": names[user_id],
                    "title": title,
                }
            )
        )

    agents: dict[str, list[OverviewWork]] = defaultdict(list)
    for agent in db.scalars(
        select(Agent)
        .where(
            Agent.group_id == group.id,
            Agent.ownership_scope == "group",
            Agent.deleted_at.is_(None),
        )
        .order_by(Agent.created_at, Agent.id)
    ).all():
        if agent.owner_user_id is None:
            continue
        if not include_private and agent.visibility != "public":
            continue
        agents[agent.owner_user_id].append(
            OverviewWork(id=UUID(agent.id), name=agent.name, visibility=agent.visibility)
        )
        event("agent_created", agent.created_at, agent.owner_user_id, agent.name)
        for version in db.scalars(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.state.in_(("published", "superseded")),
            )
        ).all():
            event(
                "agent_published",
                version.published_at,
                agent.owner_user_id,
                f"{agent.name} V1.{version.version_seq}",
            )

    teams: dict[str, list[OverviewWork]] = defaultdict(list)
    for team in db.scalars(
        select(Team)
        .where(Team.group_id == group.id, Team.deleted_at.is_(None))
        .order_by(Team.created_at, Team.id)
    ).all():
        if not include_private and team.visibility != "public":
            continue
        teams[team.owner_user_id].append(
            OverviewWork(id=UUID(team.id), name=team.display_name, visibility=team.visibility)
        )
        event("team_created", team.created_at, team.owner_user_id, team.display_name)

    rag_counts: dict[str, int] = defaultdict(int)
    for document in db.scalars(
        select(KnowledgeDocument).where(
            KnowledgeDocument.group_id == group.id,
            KnowledgeDocument.workspace_state == "active",
        )
    ).all():
        if document.owner_user_id is None:
            continue
        if not include_private and document.visibility != "public":
            continue
        rag_counts[document.owner_user_id] += 1
        event("rag_added", document.created_at, document.owner_user_id, document.source_filename)

    voice_counts: dict[str, int] = defaultdict(int)
    # A voice name is the student's own recording. It stays on the visit.
    if include_private:
        for voice in db.scalars(
            select(VoiceProfile).where(
                VoiceProfile.group_id == group.id,
                VoiceProfile.status.notin_(("deleting", "deleted", "failed")),
            )
        ).all():
            if voice.consent_actor_user_id is None:
                continue
            voice_counts[voice.consent_actor_user_id] += 1
            event("voice_added", voice.created_at, voice.consent_actor_user_id, voice.display_name)

    results = [
        OverviewResult.model_validate(row)
        for row in read_group_results(
            db,
            context,
            course_id=group.course_id,
            user_ids=set(names),
            group_id=group.id,
            group_name=group.name,
        )
    ]
    for result in results:
        event("test_completed", result.ended_at, str(result.user_id), result.team_name)

    events.sort(key=lambda item: item.at, reverse=True)
    return GroupOverview(
        group_id=UUID(group.id),
        members=[
            OverviewMember(
                user_id=UUID(row.id),
                display_name=row.display_name,
                avatar=row.avatar,
                agents=agents.get(row.id, []),
                teams=teams.get(row.id, []),
                rag_count=rag_counts.get(row.id, 0),
                voice_count=voice_counts.get(row.id, 0),
            )
            for row in students
        ],
        results=results,
        activity=events[:RECENT_EVENTS],
    )
