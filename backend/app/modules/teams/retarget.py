"""Move open Team chats onto the Team's current version.

Owner decision (2026-10-22): a Team chat in progress follows a new Team
version the way a single-Agent chat follows a new Agent version. Turns stay
on the conversation, and a member who already spoke keeps the same
participant row, so the new version sees the full history. A chat that is
mid-reply, withdrawn, or inside an in-progress formal attempt stays put.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from uuid import uuid4

from app.core.models import Agent, AgentVersion
from app.modules.learning.models import AssessmentAttempt
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamVersion,
    TeamVersionMember,
)
from app.modules.teams.service import (
    _grant_id_for_member,
    _member_rows,
    _set_rows,
    _version_for_seq,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationParticipantSet,
    ConversationSharedSet,
    TeamTurnResult,
)
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

LOGGER = logging.getLogger(__name__)

_TEMP_POSITION = 1_000_000


@dataclass(frozen=True)
class _MemberPlan:
    member: TeamVersionMember
    agent: Agent
    version: AgentVersion
    grant_id: str | None
    own_set_ids: list[str]


class _Skip(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def teams_with_stale_chats(db: Session) -> list[str]:
    """Teams that still have an open chat on an older version."""

    return list(
        db.scalars(
            select(Team.id)
            .join(TeamVersion, TeamVersion.team_id == Team.id)
            .join(Conversation, Conversation.team_version_id == TeamVersion.id)
            .where(
                Team.deleted_at.is_(None),
                Conversation.entry_kind.in_(("team", "maya_team")),
                Conversation.withdrawn_at.is_(None),
                Conversation.active_request_id.is_(None),
                TeamVersion.version_seq != Team.current_version_seq,
            )
            .distinct()
        ).all()
    )


def retarget_team_chats(db: Session, team_id: str) -> int:
    """Point one Team's idle open chats at its current version.

    Each chat commits on its own. A chat that cannot move is left unchanged
    for a later publish or the recovery sweep.
    """

    team = db.get(Team, team_id)
    if team is None or team.deleted_at is not None:
        return 0
    version = _version_for_seq(db, team)
    members = _member_rows(db, version.id)
    conversations = list(
        db.scalars(
            select(Conversation).where(
                Conversation.team_id == team.id,
                Conversation.entry_kind.in_(("team", "maya_team")),
                Conversation.withdrawn_at.is_(None),
                Conversation.active_request_id.is_(None),
                Conversation.team_version_id != version.id,
            )
        ).all()
    )
    moved = 0
    for conversation in conversations:
        try:
            if _retarget_one(db, team, version, members, conversation):
                db.commit()
                moved += 1
            else:
                db.rollback()
        except Exception:  # noqa: BLE001
            db.rollback()
            LOGGER.exception("Team chat retarget failed team_id=%s", team.id)
    return moved


def _retarget_one(
    db: Session,
    team: Team,
    version: TeamVersion,
    members: list[TeamVersionMember],
    conversation: Conversation,
) -> bool:
    if _attempt_blocks_retarget(db, conversation.id):
        LOGGER.info(
            "team_retarget_skipped team_id=%s reason=assessment_in_progress",
            team.id,
        )
        return False
    try:
        plans = _plans_for(db, team, version, members, conversation)
    except _Skip as skipped:
        LOGGER.info("team_retarget_skipped team_id=%s reason=%s", team.id, skipped.reason)
        return False
    publication = (
        _publication_for(db, team, version) if conversation.entry_kind == "maya_team" else None
    )
    if conversation.entry_kind == "maya_team" and publication is None:
        LOGGER.info("team_retarget_skipped team_id=%s reason=maya_unpublished", team.id)
        return False
    participants = list(
        db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation.id)
            .order_by(ConversationParticipant.position)
        ).all()
    )
    by_agent = {plan.member.agent_id: plan for plan in plans}
    try:
        stayers, newcomers, leavers = _match_participants(participants, by_agent)
    except _Skip as skipped:
        LOGGER.info("team_retarget_skipped team_id=%s reason=%s", team.id, skipped.reason)
        return False
    nested = db.begin_nested()
    try:
        _refuse_leavers_with_history(db, leavers)
        for leaver in leavers:
            db.delete(leaver)
        db.flush()
        if not _shift_version(db, conversation, team, version, publication, stayers):
            raise _Skip("lost_race")
        db.expire_all()
        _insert_newcomers(db, conversation, version, newcomers)
        _replace_sets(db, conversation, version, stayers, newcomers)
        db.flush()
        nested.commit()
    except _Skip as skipped:
        nested.rollback()
        LOGGER.info("team_retarget_skipped team_id=%s reason=%s", team.id, skipped.reason)
        return False
    except IntegrityError:
        nested.rollback()
        LOGGER.info("team_retarget_skipped team_id=%s reason=constraint", team.id)
        return False
    return True


def _attempt_blocks_retarget(db: Session, conversation_id: str) -> bool:
    # An in-progress formal attempt is checked against the version it started
    # on. Moving the chat would detach that attempt from its answers.
    return (
        db.scalar(
            select(AssessmentAttempt.id).where(
                AssessmentAttempt.source_conversation_id == conversation_id,
                AssessmentAttempt.status.in_(("in_progress", "paused")),
            )
        )
        is not None
    )


def _publication_for(db: Session, team: Team, version: TeamVersion) -> CourseTeamPublication | None:
    return db.scalar(
        select(CourseTeamPublication).where(
            CourseTeamPublication.team_id == team.id,
            CourseTeamPublication.team_version_id == version.id,
            CourseTeamPublication.authorization_epoch == team.authorization_epoch,
            CourseTeamPublication.state.in_(("published", "retained")),
        )
    )


def _plans_for(
    db: Session,
    team: Team,
    version: TeamVersion,
    members: list[TeamVersionMember],
    conversation: Conversation,
) -> list[_MemberPlan]:
    publication = (
        _publication_for(db, team, version) if conversation.entry_kind == "maya_team" else None
    )
    plans: list[_MemberPlan] = []
    for member in members:
        agent = db.get(Agent, member.agent_id)
        agent_version = db.get(AgentVersion, member.agent_version_id)
        if (
            agent is None
            or agent_version is None
            or agent.deleted_at is not None
            or agent.status != "active"
            or agent_version.agent_id != agent.id
            or agent_version.state not in {"published", "superseded"}
            or agent.authorization_epoch != agent_version.authorization_epoch
        ):
            raise _Skip("member_unavailable")
        grant_id = None
        if conversation.entry_kind == "maya_team":
            grant_id = _grant_id_for_member(db, publication, team, version, member)
            if grant_id is None:
                raise _Skip("grant_missing")
        own_set_ids = _own_set_ids(member)
        if own_set_ids is None:
            raise _Skip("snapshot_json")
        plans.append(
            _MemberPlan(
                member=member,
                agent=agent,
                version=agent_version,
                grant_id=grant_id,
                own_set_ids=own_set_ids,
            )
        )
    return plans


def _own_set_ids(member: TeamVersionMember) -> list[str] | None:
    try:
        values = json.loads(member.own_knowledge_set_snapshots_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(values, list):
        return None
    ids: list[str] = []
    for item in values:
        if not isinstance(item, dict) or not item.get("id"):
            return None
        ids.append(str(item["id"]))
    return ids


def _match_participants(
    participants: list[ConversationParticipant],
    by_agent: dict[str, _MemberPlan],
) -> tuple[
    list[tuple[ConversationParticipant, _MemberPlan]],
    list[_MemberPlan],
    list[ConversationParticipant],
]:
    seen: set[str] = set()
    stayers: list[tuple[ConversationParticipant, _MemberPlan]] = []
    leavers: list[ConversationParticipant] = []
    for participant in participants:
        plan = by_agent.get(participant.agent_id)
        if plan is None:
            leavers.append(participant)
            continue
        if participant.agent_id in seen:
            raise _Skip("duplicate_member")
        seen.add(participant.agent_id)
        stayers.append((participant, plan))
    newcomers = [plan for agent_id, plan in by_agent.items() if agent_id not in seen]
    return stayers, newcomers, leavers


def _refuse_leavers_with_history(db: Session, leavers: list[ConversationParticipant]) -> None:
    if not leavers:
        return
    spoken = db.scalar(
        select(TeamTurnResult.id)
        .where(TeamTurnResult.participant_id.in_([leaver.id for leaver in leavers]))
        .limit(1)
    )
    if spoken is not None:
        # Deleting the participant would cascade their replies away.
        raise _Skip("member_departed_with_history")


def _shift_version(
    db: Session,
    conversation: Conversation,
    team: Team,
    version: TeamVersion,
    publication: CourseTeamPublication | None,
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
) -> bool:
    publication_id = publication.id if publication is not None else None
    publication_epoch = team.authorization_epoch if publication is not None else None
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return _shift_postgres(
            db, conversation, team, version, publication_id, publication_epoch, stayers
        )
    if dialect == "sqlite":
        db.execute(text("PRAGMA defer_foreign_keys=ON"))
    changed = db.execute(
        text(
            "UPDATE agent_conversations SET team_version_id = :new_version, "
            "team_name_snapshot = :name, team_authorization_epoch = :epoch, "
            "publication_id = :publication_id, publication_epoch = :publication_epoch "
            "WHERE id = :cid AND team_version_id = :old_version "
            "AND active_request_id IS NULL AND withdrawn_at IS NULL"
        ),
        {
            "new_version": version.id,
            "name": version.display_name,
            "epoch": team.authorization_epoch,
            "publication_id": publication_id,
            "publication_epoch": publication_epoch,
            "cid": conversation.id,
            "old_version": conversation.team_version_id,
        },
    )
    if int(getattr(changed, "rowcount", 0) or 0) != 1:
        return False
    _rewrite_stayers(db, conversation.id, version.id, stayers)
    return True


def _shift_postgres(
    db: Session,
    conversation: Conversation,
    team: Team,
    version: TeamVersion,
    publication_id: str | None,
    publication_epoch: int | None,
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
) -> bool:
    # Conversation and its members point at each other. PostgreSQL checks
    # those foreign keys at the end of the statement, so one command has to
    # move both. SQLite defers the same check until commit instead.
    if not stayers:
        changed = db.execute(
            text(
                "UPDATE agent_conversations SET team_version_id = :new_version, "
                "team_name_snapshot = :name, team_authorization_epoch = :epoch, "
                "publication_id = :publication_id, publication_epoch = :publication_epoch "
                "WHERE id = :cid AND team_version_id = :old_version "
                "AND active_request_id IS NULL AND withdrawn_at IS NULL"
            ),
            _conversation_params(conversation, team, version, publication_id, publication_epoch),
        )
        return int(getattr(changed, "rowcount", 0) or 0) == 1
    values_sql, params = _stayer_values(stayers)
    params.update(
        _conversation_params(conversation, team, version, publication_id, publication_epoch)
    )
    row = db.execute(
        text(
            "WITH moved AS ("
            "UPDATE agent_conversations SET team_version_id = :new_version, "
            "team_name_snapshot = :name, team_authorization_epoch = :epoch, "
            "publication_id = :publication_id, publication_epoch = :publication_epoch "
            "WHERE id = :cid AND team_version_id = :old_version "
            "AND active_request_id IS NULL AND withdrawn_at IS NULL "
            "RETURNING id), "
            "shifted AS ("
            "UPDATE conversation_participants AS p SET "
            "team_version_id = :new_version, "
            "team_member_id = v.member_id, "
            "agent_version_id = v.agent_version_id, "
            "snapshot_id = v.snapshot_id, "
            "agent_authorization_epoch = v.epoch, "
            "position = v.temp_position, "
            "is_leader = false, "
            "display_name = v.display_name, "
            "avatar_config_json = v.avatar_json, "
            "invoke_grant_id = v.grant_id "
            f"FROM moved, (VALUES {values_sql}) AS v("
            "participant_id, member_id, agent_version_id, snapshot_id, epoch, "
            "temp_position, display_name, avatar_json, grant_id) "
            "WHERE p.conversation_id = moved.id AND p.id = v.participant_id "
            "RETURNING p.id) "
            "SELECT (SELECT count(*) FROM moved), (SELECT count(*) FROM shifted)"
        ),
        params,
    ).one()
    if int(row[0]) != 1 or int(row[1]) != len(stayers):
        return False
    _assign_final_places(db, conversation.id, stayers)
    return True


def _conversation_params(
    conversation: Conversation,
    team: Team,
    version: TeamVersion,
    publication_id: str | None,
    publication_epoch: int | None,
) -> dict[str, object]:
    return {
        "new_version": version.id,
        "name": version.display_name,
        "epoch": team.authorization_epoch,
        "publication_id": publication_id,
        "publication_epoch": publication_epoch,
        "cid": conversation.id,
        "old_version": conversation.team_version_id,
    }


def _stayer_values(
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
) -> tuple[str, dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}
    for index, (participant, plan) in enumerate(stayers):
        clauses.append(
            f"(CAST(:pid_{index} AS VARCHAR), CAST(:mid_{index} AS VARCHAR), "
            f"CAST(:avid_{index} AS VARCHAR), CAST(:snap_{index} AS VARCHAR), "
            f"CAST(:epoch_{index} AS INTEGER), CAST(:temp_{index} AS INTEGER), "
            f"CAST(:name_{index} AS VARCHAR), CAST(:avatar_{index} AS VARCHAR), "
            f"CAST(:grant_{index} AS VARCHAR))"
        )
        params.update(
            {
                f"pid_{index}": participant.id,
                f"mid_{index}": plan.member.id,
                f"avid_{index}": plan.version.id,
                f"snap_{index}": plan.version.knowledge_snapshot_id,
                f"epoch_{index}": plan.agent.authorization_epoch,
                f"temp_{index}": _TEMP_POSITION + plan.member.position,
                f"name_{index}": plan.member.display_name,
                f"avatar_{index}": plan.member.avatar_config_json,
                f"grant_{index}": plan.grant_id,
            }
        )
    return ", ".join(clauses), params


def _rewrite_stayers(
    db: Session,
    conversation_id: str,
    new_version_id: str,
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
) -> None:
    if not stayers:
        return
    params: dict[str, object] = {
        "new_version": new_version_id,
        "cid": conversation_id,
    }
    for index, (participant, plan) in enumerate(stayers):
        params[f"pid_{index}"] = participant.id
        params[f"mid_{index}"] = plan.member.id
        params[f"avid_{index}"] = plan.version.id
        params[f"snap_{index}"] = plan.version.knowledge_snapshot_id
        params[f"epoch_{index}"] = plan.agent.authorization_epoch
        params[f"temp_{index}"] = _TEMP_POSITION + plan.member.position
        params[f"name_{index}"] = plan.member.display_name
        params[f"avatar_{index}"] = plan.member.avatar_config_json
        params[f"grant_{index}"] = plan.grant_id
    id_list = ", ".join(f":pid_{index}" for index in range(len(stayers)))

    def case(column_index: str) -> str:
        parts = " ".join(
            f"WHEN :pid_{index} THEN :{column_index}_{index}" for index in range(len(stayers))
        )
        return f"CASE id {parts} END"

    db.execute(
        text(
            "UPDATE conversation_participants SET "
            "team_version_id = :new_version, "
            f"team_member_id = {case('mid')}, "
            f"agent_version_id = {case('avid')}, "
            f"snapshot_id = {case('snap')}, "
            f"agent_authorization_epoch = {case('epoch')}, "
            f"position = {case('temp')}, "
            "is_leader = 0, "
            f"display_name = {case('name')}, "
            f"avatar_config_json = {case('avatar')}, "
            f"invoke_grant_id = {case('grant')} "
            f"WHERE conversation_id = :cid AND id IN ({id_list})"
        ),
        params,
    )
    _assign_final_places(db, conversation_id, stayers)


def _assign_final_places(
    db: Session,
    conversation_id: str,
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
) -> None:
    # Temporary positions avoid the per-row unique check while members swap.
    for participant, plan in stayers:
        db.execute(
            text(
                "UPDATE conversation_participants SET position = :position, is_leader = :leader "
                "WHERE id = :pid AND conversation_id = :cid"
            ),
            {
                "position": plan.member.position,
                "leader": plan.member.is_leader,
                "pid": participant.id,
                "cid": conversation_id,
            },
        )


def _insert_newcomers(
    db: Session,
    conversation: Conversation,
    version: TeamVersion,
    newcomers: list[_MemberPlan],
) -> None:
    for plan in newcomers:
        participant = ConversationParticipant(
            id=str(uuid4()),
            conversation_id=conversation.id,
            team_version_id=version.id,
            team_member_id=plan.member.id,
            agent_id=plan.member.agent_id,
            agent_version_id=plan.version.id,
            snapshot_id=plan.version.knowledge_snapshot_id,
            agent_authorization_epoch=plan.agent.authorization_epoch,
            position=plan.member.position,
            is_leader=plan.member.is_leader,
            display_name=plan.member.display_name,
            avatar_config_json=plan.member.avatar_config_json,
            invoke_grant_id=plan.grant_id,
        )
        db.add(participant)
        db.flush()
        for position, set_id in enumerate(plan.own_set_ids):
            db.add(
                ConversationParticipantSet(
                    participant_id=participant.id,
                    knowledge_set_id=set_id,
                    position=position,
                )
            )


def _replace_sets(
    db: Session,
    conversation: Conversation,
    version: TeamVersion,
    stayers: list[tuple[ConversationParticipant, _MemberPlan]],
    newcomers: list[_MemberPlan],
) -> None:
    del newcomers
    for participant, plan in stayers:
        db.execute(
            delete(ConversationParticipantSet).where(
                ConversationParticipantSet.participant_id == participant.id
            )
        )
        for position, set_id in enumerate(plan.own_set_ids):
            db.add(
                ConversationParticipantSet(
                    participant_id=participant.id,
                    knowledge_set_id=set_id,
                    position=position,
                )
            )
    db.execute(
        delete(ConversationSharedSet).where(
            ConversationSharedSet.conversation_id == conversation.id
        )
    )
    for position, binding in enumerate(_set_rows(db, version.id)):
        db.add(
            ConversationSharedSet(
                conversation_id=conversation.id,
                knowledge_set_id=binding.knowledge_set_id,
                position=position,
            )
        )
