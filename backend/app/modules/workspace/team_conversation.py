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
from app.modules.agents.schemas import AvatarConfig
from app.modules.auth.service import AuthContext
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
    if row.withdrawn_at is not None:
        return False
    role = db.scalar(
        select(CourseMember.role).where(
            CourseMember.course_id == row.course_id, CourseMember.user_id == actor_id
        )
    )
    if role is None:
        return False
    if row.user_id == actor_id:
        return True
    return (
        row.chat_visibility == "public"
        and role == "teacher"
        and db.get(CourseMember, (row.course_id, row.user_id)) is not None
    )


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


def create_team_conversation(
    db: Session,
    context: AuthContext,
    entry: SavedTeamChatEntry | MayaTeamChatEntry,
    chat_visibility: str,
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
    active_conversation = _active_formal_assessment_conversation(db, context, selection, entry)
    if active_conversation is not None:
        return active_conversation
    row = Conversation(
        id=str(uuid4()),
        user_id=context.user.id,
        course_id=selection.course_id,
        entry_kind=entry.kind,
        chat_visibility=chat_visibility,
        origin="published_course_team" if selection.publication_id else "custom_team",
        agent_version_id=None,
        snapshot_id=None,
        agent_name_snapshot="",
        agent_authorization_epoch=0,
        team_id=selection.team_id,
        team_version_id=selection.team_version_id,
        team_owner_user_id=selection.owner_user_id,
        team_name_snapshot=selection.display_name,
        team_authorization_epoch=selection.team_authorization_epoch,
        publication_id=selection.publication_id,
        publication_epoch=selection.publication_epoch,
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
            invoke_grant_id=member.invoke_grant_id,
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


def team_session_view(
    db: Session,
    row: Conversation,
    context: AuthContext,
    turns: list[ChatTurn],
    *,
    runtime_available: bool = False,
) -> TeamChatSession:
    from .team_runtime import _validate_members, project_team_turn

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
                )
                for participant in participants
            ],
            available=available,
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
        ],
        created_at=row.created_at,
        read_only=row.user_id != context.user.id,
        can_send=(
            runtime_available
            and row.withdrawn_at is None
            and row.user_id == context.user.id
            and row.active_request_id is None
            and any(availability.values())
        ),
    )
