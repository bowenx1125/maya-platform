"""Frozen Team identities and read authorization for the Chat creation slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found
from app.core.models import Agent, AgentVersion, CourseMember
from app.core.read_memo import memoized
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.service import AuthContext
from app.modules.teams.models import Team
from app.modules.teams.service import (
    FrozenTeamMember,
    FrozenTeamSelection,
    resolve_chat_entry,
)

from .models import (
    Conversation,
    ConversationParticipant,
    ConversationParticipantSet,
    ConversationSharedSet,
    ConversationTurn,
)
from .schemas import (
    ChatTeam,
    ChatTurn,
    MayaTeamChatEntry,
    SavedTeamChatEntry,
    TeamChatParticipant,
    TeamChatSession,
)


def can_read_conversation(db: Session, actor_id: str, row: Conversation) -> bool:
    # Every Chat is its owner's alone. A stored legacy "public" value no longer
    # opens it to a Teacher; formal assessment reaches reports as records instead.
    if row.withdrawn_at is not None or row.user_id != actor_id:
        return False
    return db.get(CourseMember, (row.course_id, actor_id)) is not None


def require_single_runtime(row: Conversation) -> None:
    if row.entry_kind != "agent":
        raise conflict("team_chat_runtime_unavailable", "Team messaging is not available yet.")


def _active_formal_assessment_conversation(
    db: Session,
    context: AuthContext,
    selection: FrozenTeamSelection,
    entry: SavedTeamChatEntry | MayaTeamChatEntry,
) -> Conversation | None:
    if entry.kind != "maya_team":
        return None
    membership = db.get(CourseMember, (selection.course_id, context.user.id))
    if membership is None or membership.role != "student":
        return None
    leader = next(member for member in selection.members if member.is_leader)
    leader_version = db.get(AgentVersion, leader.agent_version_id)
    if leader_version is None:
        raise not_found()
    from app.modules.learning.attempts import find_active_assessment_conversation
    from app.modules.learning.recipes import declared_recipe

    try:
        recipe_id = declared_recipe(leader_version.agent_md)
    except PlatformError:
        return None
    if recipe_id is None:
        return None
    return find_active_assessment_conversation(
        db,
        actor_user_id=context.user.id,
        course_id=selection.course_id,
        team_id=selection.team_id,
        recipe_id=recipe_id,
    )


def _published_recipe_is_complete(db: Session, selection: FrozenTeamSelection) -> bool:
    """Score only a teacher-published Team whose recipe, roles and questions are complete."""

    if selection.publication_id is None:
        return False
    from app.modules.learning.recipes import (
        _selected_questions,
        declared_recipe,
    )
    from app.modules.workspace.formal_assessment import resolve_formal_assessment

    leader = next((member for member in selection.members if member.is_leader), None)
    if leader is None:
        return False
    leader_version = db.get(AgentVersion, leader.agent_version_id)
    if leader_version is None:
        return False
    try:
        if declared_recipe(leader_version.agent_md) is None:
            return False
        # Speakers come from ## Formal assessment, not MAYA-ASSESSMENT-ROLE.
        if (
            resolve_formal_assessment(
                leader_version.agent_md,
                [(member.binding_id, member.display_name) for member in selection.members],
            )
            is None
        ):
            return False
        set_ids = tuple(
            dict.fromkeys(
                tuple(
                    set_id
                    for member in selection.members
                    for set_id in member.own_knowledge_set_ids
                )
                + selection.shared_knowledge_set_ids
            )
        )
        if not set_ids:
            return False
        return bool(_selected_questions(db, set_ids))
    except PlatformError:
        return False


def create_team_conversation(
    db: Session,
    context: AuthContext,
    entry: SavedTeamChatEntry | MayaTeamChatEntry,
) -> Conversation:
    selection = resolve_chat_entry(
        db,
        context,
        str(entry.team_id),
        str(entry.team_version_id)
        if isinstance(entry, SavedTeamChatEntry) and entry.team_version_id is not None
        else None,
        require_publication=entry.kind == "maya_team",
    )
    if (
        len(selection.members) < 2
        or sum(member.is_leader for member in selection.members) != 1
        or {member.binding_id for member in selection.members}
        != set(selection.invokable_binding_ids)
        or selection.leader_binding_id
        != next(member.binding_id for member in selection.members if member.is_leader)
    ):
        raise not_found()
    # Published course chats use maya_team. A Teams-list chat without a
    # complete recipe stays an ordinary Team and does not store that publication.
    recipe_ready = _published_recipe_is_complete(db, selection)
    entry_kind: Literal["team", "maya_team"] = (
        "maya_team" if entry.kind == "maya_team" or recipe_ready else "team"
    )
    stored_publication = selection.publication_id if entry_kind == "maya_team" else None
    assessable = (
        MayaTeamChatEntry(kind="maya_team", team_id=entry.team_id)
        if entry_kind == "maya_team"
        else SavedTeamChatEntry(kind="team", team_id=entry.team_id)
    )
    active_conversation = _active_formal_assessment_conversation(db, context, selection, assessable)
    if active_conversation is not None:
        return active_conversation
    row = Conversation(
        id=str(uuid4()),
        user_id=context.user.id,
        course_id=selection.course_id,
        entry_kind=entry_kind,
        chat_visibility="private",
        origin="published_course_team" if stored_publication else "custom_team",
        agent_version_id=None,
        snapshot_id=None,
        agent_name_snapshot="",
        agent_authorization_epoch=0,
        team_id=selection.team_id,
        team_version_id=selection.team_version_id,
        team_owner_user_id=selection.owner_user_id,
        team_name_snapshot=selection.display_name,
        team_authorization_epoch=selection.team_authorization_epoch,
        publication_id=stored_publication,
        publication_epoch=selection.publication_epoch if stored_publication else None,
        revision=0,
        active_request_id=None,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    for member in selection.members:
        version = db.get(AgentVersion, member.agent_version_id)
        agent = db.get(Agent, member.agent_id)
        if version is None or agent is None or version.agent_id != agent.id:
            raise not_found()
        participant = ConversationParticipant(
            id=str(uuid4()),
            conversation_id=row.id,
            team_version_id=selection.team_version_id,
            team_member_id=member.binding_id,
            agent_id=member.agent_id,
            agent_version_id=member.agent_version_id,
            snapshot_id=version.knowledge_snapshot_id,
            agent_authorization_epoch=agent.authorization_epoch,
            position=member.position,
            is_leader=member.is_leader,
            display_name=member.display_name,
            avatar_config_json=json.dumps(member.avatar_config, ensure_ascii=False),
            invoke_grant_id=member.invoke_grant_id if entry_kind == "maya_team" else None,
        )
        db.add(participant)
        db.flush()
        for position, set_id in enumerate(member.own_knowledge_set_ids):
            db.add(
                ConversationParticipantSet(
                    participant_id=participant.id, knowledge_set_id=set_id, position=position
                )
            )
    for position, set_id in enumerate(selection.shared_knowledge_set_ids):
        db.add(
            ConversationSharedSet(
                conversation_id=row.id, knowledge_set_id=set_id, position=position
            )
        )
    # A new Team chat stays quiet until the student sends a message. Formal
    # Guide lines are spoken only after that message starts an attempt.
    db.flush()
    return row


def _participants(db: Session, conversation_id: str) -> list[ConversationParticipant]:
    return list(
        db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation_id)
            .order_by(ConversationParticipant.position)
        ).all()
    )


def frozen_team_selection(db: Session, row: Conversation) -> FrozenTeamSelection:
    return memoized(
        db,
        ("frozen_team_selection", row.id),
        lambda: _read_frozen_team_selection(db, row),
        across_sessions=True,
    )


def _read_frozen_team_selection(db: Session, row: Conversation) -> FrozenTeamSelection:
    if (
        row.entry_kind == "agent"
        or row.team_id is None
        or row.team_version_id is None
        or row.team_owner_user_id is None
        or row.team_name_snapshot is None
        or row.team_authorization_epoch is None
    ):
        raise not_found()
    members: list[FrozenTeamMember] = []
    for participant in _participants(db, row.id):
        own_ids = tuple(
            db.scalars(
                select(ConversationParticipantSet.knowledge_set_id)
                .where(ConversationParticipantSet.participant_id == participant.id)
                .order_by(ConversationParticipantSet.position)
            ).all()
        )
        members.append(
            FrozenTeamMember(
                binding_id=participant.team_member_id,
                agent_id=participant.agent_id,
                agent_version_id=participant.agent_version_id,
                position=participant.position,
                is_leader=participant.is_leader,
                display_name=participant.display_name,
                avatar_config=json.loads(participant.avatar_config_json),
                invoke_grant_id=participant.invoke_grant_id,
                own_knowledge_set_ids=own_ids,
            )
        )
    leaders = [member.binding_id for member in members if member.is_leader]
    if len(members) < 2 or len(leaders) != 1:
        raise not_found()
    shared_ids = tuple(
        db.scalars(
            select(ConversationSharedSet.knowledge_set_id)
            .where(ConversationSharedSet.conversation_id == row.id)
            .order_by(ConversationSharedSet.position)
        ).all()
    )
    return FrozenTeamSelection(
        team_id=row.team_id,
        team_version_id=row.team_version_id,
        course_id=row.course_id,
        owner_user_id=row.team_owner_user_id,
        display_name=row.team_name_snapshot,
        publication_id=row.publication_id,
        publication_epoch=row.publication_epoch,
        team_authorization_epoch=row.team_authorization_epoch,
        require_publication=row.entry_kind == "maya_team",
        members=tuple(members),
        leader_binding_id=leaders[0],
        shared_knowledge_set_ids=shared_ids,
        invokable_binding_ids=tuple(member.binding_id for member in members),
    )


def _finishing_stalled(db: Session, row: Conversation) -> bool:
    """The last turn is a failed server-run executor turn and nothing runs now."""

    if row.active_request_id is not None:
        return False
    latest = db.execute(
        select(ConversationTurn.user_text, ConversationTurn.state)
        .where(ConversationTurn.conversation_id == row.id)
        .order_by(ConversationTurn.position.desc())
        .limit(1)
    ).first()
    return latest is not None and latest.user_text == "" and latest.state == "failed"


def _assessment_stage(
    db: Session, row: Conversation
) -> Literal["preparing", "scoring", "summarizing", "completed"] | None:
    from app.modules.learning.finalizer import _next_purpose
    from app.modules.learning.models import AssessmentAttempt

    attempt = db.scalar(
        select(AssessmentAttempt)
        .where(
            AssessmentAttempt.source_conversation_id == row.id,
            AssessmentAttempt.actor_user_id == row.user_id,
        )
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
        .limit(1)
    )
    if attempt is None:
        return None
    if attempt.status == "in_progress":
        purpose = _next_purpose(db, attempt)
        if purpose is not None and _finishing_stalled(db, row):
            # Bug (2026-10-17, #121): a failed scoring/summary left the bar and
            # the disabled Send up until a restart. While nothing runs, the
            # chat stops waiting; the server retries, and so does a new message.
            return None
        if purpose == "assessment_evaluate":
            from app.modules.learning.attempts import awaits_follow_up_round

            # The scoring that picks follow-ups keeps the Chat checking but
            # shows no bar: the test is not over yet.
            return "preparing" if awaits_follow_up_round(db, attempt.id) else "scoring"
        return "summarizing" if purpose == "boundary_summarize" else None
    if attempt.status != "completed" or attempt.completed_at is None:
        return None
    # The finished bar stays until the student writes again.
    later_message = db.scalar(
        select(ConversationTurn.id)
        .where(
            ConversationTurn.conversation_id == row.id,
            ConversationTurn.user_text != "",
            ConversationTurn.created_at > attempt.completed_at,
        )
        .limit(1)
    )
    return None if later_message is not None else "completed"


def team_session_view(
    db: Session,
    row: Conversation,
    context: AuthContext,
    turns: list[ChatTurn],
    *,
    runtime_available: bool = False,
) -> TeamChatSession:
    from .team_runtime import _student_hides_turn, _validate_members, project_team_turn

    selection = frozen_team_selection(db, row)
    participants = _participants(db, row.id)
    availability: dict[str, bool] = {}
    for participant in participants:
        try:
            _validate_members(db, row, [participant])
            availability[participant.id] = True
        except PlatformError:
            availability[participant.id] = False
    available = bool(availability) and all(availability.values())
    deleted_agents = {
        participant.id
        for participant in participants
        if (agent := db.get(Agent, participant.agent_id)) is not None
        and agent.deleted_at is not None
    }
    team = db.get(Team, selection.team_id)
    return TeamChatSession(
        id=UUID(row.id),
        entry_kind=cast("Literal['team', 'maya_team']", row.entry_kind),
        chat_visibility=cast("Literal['private', 'public']", row.chat_visibility),
        origin=cast("Literal['custom_team', 'published_course_team']", row.origin),
        team=ChatTeam(
            id=UUID(selection.team_id),
            version_id=UUID(selection.team_version_id),
            course_id=UUID(row.course_id),
            name=selection.display_name,
            members=[
                TeamChatParticipant(
                    id=UUID(participant.id),
                    name=participant.display_name,
                    avatar_config=AvatarConfig.model_validate_json(participant.avatar_config_json),
                    position=participant.position,
                    is_leader=participant.is_leader,
                    available=availability[participant.id],
                    deleted=participant.id in deleted_agents,
                )
                for participant in participants
            ],
            available=available,
            deleted=team is None or team.deleted_at is not None,
        ),
        revision=row.revision,
        turns=[
            project_team_turn(db, turn, read_only=row.user_id != context.user.id)
            for turn in db.scalars(
                select(ConversationTurn)
                .where(
                    ConversationTurn.conversation_id == row.id,
                )
                .order_by(ConversationTurn.position, ConversationTurn.id)
            )
            if not _student_hides_turn(db, turn)
        ],
        created_at=row.created_at,
        title=row.title,
        pinned_at=row.pinned_at,
        assessment_stage=_assessment_stage(db, row),
        read_only=row.user_id != context.user.id,
        can_send=(
            runtime_available
            and row.withdrawn_at is None
            and row.user_id == context.user.id
            and row.active_request_id is None
            and any(availability.values())
        ),
    )
