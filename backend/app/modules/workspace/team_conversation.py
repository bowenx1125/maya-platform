"""Frozen Team identities and read authorization for the Chat creation slice."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PlatformError, conflict, not_found
from app.core.models import Agent, AgentVersion, CourseMember
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
    TeamTurnResult,
)
from .schemas import (
    ChatTeam,
    ChatTurn,
    MayaTeamChatEntry,
    SavedTeamChatEntry,
    TeamChatParticipant,
    TeamChatSession,
)

MAYA_TEAM_OPENING = (
    "我是 Leader。直接发消息，由我来带。要叫某一位成员，输入 @ 再选。要正式测评，直接说你要测评。"
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
        declared_assessment_role,
        declared_recipe,
    )

    leader = next((member for member in selection.members if member.is_leader), None)
    if leader is None:
        return False
    leader_version = db.get(AgentVersion, leader.agent_version_id)
    if leader_version is None:
        return False
    try:
        if declared_recipe(leader_version.agent_md) is None:
            return False
        # Same role rule as ensure_assessment_activity: the Leader may itself
        # be one of the two executors.
        roles: list[str] = []
        for member in selection.members:
            version = db.get(AgentVersion, member.agent_version_id)
            if version is None:
                return False
            role = declared_assessment_role(version.agent_md)
            if role is not None:
                roles.append(role)
        if roles.count("evaluator") != 1 or roles.count("boundary_summarizer") != 1:
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
    leader_participant: ConversationParticipant | None = None
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
        if participant.is_leader:
            leader_participant = participant
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
    # The opening is a fixed rule of a complete published recipe, whoever opens
    # the chat; without that recipe the Team waits for the first message.
    if recipe_ready:
        if leader_participant is None:
            raise not_found()
        _persist_maya_team_opening(db, row, leader_participant)
    db.flush()
    return row


def _persist_maya_team_opening(
    db: Session, row: Conversation, leader: ConversationParticipant
) -> None:
    """The Leader's first message is stored with the Chat, before any model call."""

    now = datetime.now(UTC)
    turn_id = str(uuid5(UUID(row.id), "maya-team-opening"))
    routing = {"mode": "selected", "participant_ids": [leader.id]}
    request_hash = hashlib.sha256(
        json.dumps(
            {"conversation_id": row.id, "message": MAYA_TEAM_OPENING},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    turn = ConversationTurn(
        id=turn_id,
        conversation_id=row.id,
        position=1,
        user_text="",
        assistant_text=None,
        sources_json="[]",
        mode="mock",
        state="ready",
        safe_error_code=None,
        routing_json=json.dumps(routing, ensure_ascii=False, separators=(",", ":")),
        request_hash=request_hash,
        claim_token=str(uuid5(UUID(turn_id), "maya-team-opening")),
        created_at=now,
    )
    db.add(turn)
    db.flush()
    db.add(
        TeamTurnResult(
            id=str(uuid5(UUID(turn_id), leader.id)),
            turn_id=turn_id,
            conversation_id=row.id,
            participant_id=leader.id,
            ordinal=0,
            state="ready",
            assistant_text=MAYA_TEAM_OPENING,
            sources_json="[]",
            safe_error_code=None,
            created_at=now,
            completed_at=now,
        )
    )
    row.revision = 1


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
