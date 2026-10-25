"""Hard-delete Brainform rows without erasing records, grades, or Debates.

Debates keep their own AGENT.md, knowledge copy and voice copy. Chats of a
deleted Agent or Team stay open as history and refuse new messages. Deleting
a chat drops the transcript and leaves assessment answers in place.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    FileOperation,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    VoiceProfile,
)
from app.core.version_label import agent_version_label
from app.modules.debates.models import DebateParticipant
from app.modules.debates.owned_copies import _delete_snapshot_files
from app.modules.deferred_files import unlink_after_commit
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeAsset,
    KnowledgeGenerationRun,
    KnowledgeGenerationTargetSnapshot,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptQuestion,
    LearningAssessment,
    LearningAssessmentMutation,
    LearningAssessmentResourceGrant,
    LearningAssessmentRevision,
    LearningBoundary,
    LearningRecord,
)
from app.modules.purge import purge_ids
from app.modules.runtime_tools.models import RuntimeModelCallStage, RuntimeToolReceipt
from app.modules.teams.models import (
    CourseTeamPublication,
    Team,
    TeamMemberInvokeGrant,
    TeamVersion,
    TeamVersionMember,
    TeamVersionSet,
)
from app.modules.workspace.models import (
    ChatMemoryEntryAction,
    ChatProviderConsentBinding,
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamProviderConsentBinding,
    TeamProviderStandingGrant,
    TeamTurnResult,
)

LOGGER = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def release_stored_file(db: Session, data_root: Path | None, file_id: str | None) -> None:
    """Drop a file's row once nothing points at it; unlink it after commit."""

    if not file_id:
        return
    if _file_referenced(db, file_id):
        return
    stored = db.get(StoredFile, file_id)
    if stored is None:
        return
    relative = stored.relative_path
    if purge_ids(db, "stored_files", [file_id]):
        unlink_after_commit(db, data_root, relative)


def _file_referenced(db: Session, file_id: str) -> bool:
    from app.modules.debates.models import DebateVoiceClone
    from app.modules.knowledge_sets.models import (
        KnowledgeAssetVersionSource,
        KnowledgeDocumentVersion,
        KnowledgeGenerationSourceReceipt,
        KnowledgeSetSource,
    )

    checks = (
        select(KnowledgeDocument.id).where(KnowledgeDocument.stored_file_id == file_id),
        select(KnowledgeSnapshot.id).where(KnowledgeSnapshot.stored_file_id == file_id),
        select(SnapshotDocument.id).where(SnapshotDocument.stored_file_id == file_id),
        select(VoiceProfile.id).where(VoiceProfile.sample_file_id == file_id),
        select(DebateVoiceClone.id).where(DebateVoiceClone.sample_file_id == file_id),
        select(KnowledgeSetSource.id).where(KnowledgeSetSource.stored_file_id == file_id),
        select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.stored_file_id == file_id
        ),
        select(KnowledgeAssetVersionSource.id).where(
            KnowledgeAssetVersionSource.stored_file_id == file_id
        ),
        select(KnowledgeGenerationSourceReceipt.id).where(
            KnowledgeGenerationSourceReceipt.stored_file_id == file_id
        ),
    )
    return any(db.scalar(query.limit(1)) is not None for query in checks)


def _fail_pending(db: Session, conversation_ids: list[str], code: str) -> None:
    if not conversation_ids:
        return
    db.execute(
        update(ConversationTurn)
        .where(
            ConversationTurn.conversation_id.in_(conversation_ids),
            ConversationTurn.state == "pending",
        )
        .values(state="failed", safe_error_code=code)
    )


def terminate_agent_chats(db: Session, agent_id: str, *, now: datetime | None = None) -> list[str]:
    """Keep the chats, freeze the name, and stop them accepting messages."""

    moment = now or _now()
    agent = db.get(Agent, agent_id)
    versions = {
        row.id: row
        for row in db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id)).all()
    }
    if not versions:
        return []
    chats = list(
        db.scalars(
            select(Conversation).where(
                Conversation.entry_kind == "agent",
                Conversation.source_removed_at.is_(None),
                Conversation.agent_version_id.in_(list(versions)),
            )
        ).all()
    )
    for chat in chats:
        version = versions.get(chat.agent_version_id or "")
        chat.history_agent_id = agent_id
        chat.history_agent_version_id = chat.agent_version_id
        chat.history_version_label = (
            agent_version_label(version.version_seq) if version is not None else ""
        )
        chat.agent_avatar_json = version.avatar_config_json if version is not None else None
        if agent is not None and not (chat.agent_name_snapshot or "").strip():
            chat.agent_name_snapshot = agent.name
        chat.source_removed_at = moment
        chat.agent_version_id = None
        chat.snapshot_id = None
        chat.active_request_id = None
        chat.revision = int(chat.revision or 0) + 1
    db.flush()
    ids = [chat.id for chat in chats]
    _fail_pending(db, ids, "agent_deleted")
    return ids


def terminate_team_chats(db: Session, team_id: str, *, now: datetime | None = None) -> list[str]:
    moment = now or _now()
    team = db.get(Team, team_id)
    chats = list(
        db.scalars(
            select(Conversation).where(
                Conversation.team_id == team_id,
                Conversation.source_removed_at.is_(None),
            )
        ).all()
    )
    chat_ids = [chat.id for chat in chats]
    if chat_ids:
        db.execute(
            update(ConversationParticipant)
            .where(ConversationParticipant.conversation_id.in_(chat_ids))
            .values(team_version_id=None, team_member_id=None, invoke_grant_id=None)
        )
    for chat in chats:
        chat.history_team_id = chat.team_id
        chat.history_team_version_id = chat.team_version_id
        if team is not None and not (chat.team_name_snapshot or "").strip():
            chat.team_name_snapshot = team.display_name
        chat.source_removed_at = moment
        chat.team_id = None
        chat.team_version_id = None
        chat.publication_id = None
        chat.publication_epoch = None
        chat.active_request_id = None
        chat.revision = int(chat.revision or 0) + 1
    db.flush()
    _fail_pending(db, chat_ids, "team_deleted")
    return chat_ids


def abandon_team_attempts(db: Session, team_id: str, *, now: datetime | None = None) -> None:
    """In-progress work cannot continue after the Team is gone. Answers stay."""

    moment = now or _now()
    team = db.get(Team, team_id)
    name = team.display_name if team is not None else ""
    db.execute(
        update(AssessmentAttempt)
        .where(
            AssessmentAttempt.team_id == team_id,
            AssessmentAttempt.status.in_(("in_progress", "paused")),
        )
        .values(
            status="abandoned",
            abandoned_at=moment,
            abandonment_reason="source_deleted",
            team_name_snapshot=name,
            updated_at=moment,
            revision=AssessmentAttempt.revision + 1,
        )
    )
    if name:
        db.execute(
            update(AssessmentAttempt)
            .where(
                AssessmentAttempt.team_id == team_id,
                or_(
                    AssessmentAttempt.team_name_snapshot.is_(None),
                    AssessmentAttempt.team_name_snapshot == "",
                ),
            )
            .values(team_name_snapshot=name)
        )


def snapshot_team_names(db: Session, team_id: str) -> None:
    team = db.get(Team, team_id)
    if team is None:
        return
    name = team.display_name
    version_ids = list(
        db.scalars(select(TeamVersion.id).where(TeamVersion.team_id == team_id)).all()
    )
    db.execute(
        update(AssessmentActivity)
        .where(AssessmentActivity.team_id == team_id)
        .values(team_name_snapshot=name)
    )
    db.execute(
        update(LearningRecord)
        .where(LearningRecord.team_id == team_id)
        .values(team_name_snapshot=name)
    )
    db.execute(
        update(LearningAssessmentRevision)
        .where(LearningAssessmentRevision.team_id == team_id)
        .values(team_name_snapshot=name)
    )
    if version_ids:
        db.execute(
            update(AssessmentActivity)
            .where(AssessmentActivity.team_version_id.in_(version_ids))
            .values(team_name_snapshot=name)
        )


def _non_debate_snapshot_ids(db: Session, version_ids: list[str]) -> list[str]:
    if not version_ids:
        return []
    pinned = set(
        db.scalars(
            select(DebateParticipant.knowledge_snapshot_id).where(
                DebateParticipant.knowledge_snapshot_id.is_not(None)
            )
        ).all()
    )
    found: list[str] = []
    for snapshot_id in db.scalars(
        select(KnowledgeSnapshot.id).where(KnowledgeSnapshot.agent_version_id.in_(version_ids))
    ).all():
        snapshot = db.get(KnowledgeSnapshot, snapshot_id)
        if snapshot is None or snapshot.owner_debate_id or snapshot.id in pinned:
            continue
        found.append(snapshot.id)
    return found


def delete_snapshots(db: Session, snapshot_ids: list[str], data_root: Path | None) -> None:
    for snapshot_id in snapshot_ids:
        snapshot = db.get(KnowledgeSnapshot, snapshot_id)
        if snapshot is None or snapshot.owner_debate_id:
            continue
        if (
            db.scalar(
                select(DebateParticipant.id)
                .where(DebateParticipant.knowledge_snapshot_id == snapshot.id)
                .limit(1)
            )
            is not None
        ):
            continue
        if (
            db.scalar(
                select(AgentVersion.id)
                .where(AgentVersion.knowledge_snapshot_id == snapshot.id)
                .limit(1)
            )
            is not None
        ):
            continue
        _delete_snapshot_files(db, snapshot, data_root)


def _exclusive_agent_documents(db: Session, agent: Agent) -> list[KnowledgeDocument]:
    """RAG this Agent's owner uploaded that no other Agent still links."""

    own_versions = select(AgentVersion.id).where(AgentVersion.agent_id == agent.id)
    used_elsewhere = (
        select(AgentVersionDocument.document_id)
        .join(AgentVersion, AgentVersion.id == AgentVersionDocument.agent_version_id)
        .where(AgentVersion.agent_id != agent.id)
    )
    return list(
        db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id.in_(
                    select(AgentVersionDocument.document_id).where(
                        AgentVersionDocument.agent_version_id.in_(own_versions)
                    )
                ),
                KnowledgeDocument.id.not_in(used_elsewhere),
                KnowledgeDocument.owner_user_id == agent.owner_user_id,
            )
        ).all()
    )


def _exclusive_knowledge_sets(db: Session, agent_id: str) -> list[KnowledgeSet]:
    """Knowledge bound only to this Agent leaves the library with it.

    A set another Agent or a Team still uses stays. The binding row itself
    would disappear with the Agent, and Brainform would then treat the set as
    an unbound upload.
    """

    set_ids = db.scalars(
        select(AgentKnowledgeSet.knowledge_set_id).where(AgentKnowledgeSet.agent_id == agent_id)
    ).all()
    exclusive: list[KnowledgeSet] = []
    for set_id in dict.fromkeys(set_ids):
        shared = db.scalar(
            select(AgentKnowledgeSet.agent_id)
            .where(
                AgentKnowledgeSet.knowledge_set_id == set_id,
                AgentKnowledgeSet.agent_id != agent_id,
            )
            .limit(1)
        )
        if shared is not None:
            continue
        on_team = db.scalar(
            select(TeamVersionSet.knowledge_set_id)
            .where(TeamVersionSet.knowledge_set_id == set_id)
            .limit(1)
        )
        if on_team is not None:
            continue
        row = db.get(KnowledgeSet, set_id)
        if row is not None:
            exclusive.append(row)
    return exclusive


def hard_delete_agent(db: Session, agent: Agent, data_root: Path | None) -> None:
    version_ids = list(
        db.scalars(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id)).all()
    )
    terminate_agent_chats(db, agent.id)
    for document in _exclusive_agent_documents(db, agent):
        hard_delete_document(db, document, data_root)
    for knowledge_set in _exclusive_knowledge_sets(db, agent.id):
        hard_delete_knowledge_set(db, knowledge_set, data_root)
    snapshot_ids = _non_debate_snapshot_ids(db, version_ids)
    purge_ids(db, "agents", [agent.id])
    delete_snapshots(db, snapshot_ids, data_root)


def hard_delete_team(db: Session, team: Team) -> None:
    snapshot_team_names(db, team.id)
    terminate_team_chats(db, team.id)
    abandon_team_attempts(db, team.id)
    version_ids = list(
        db.scalars(select(TeamVersion.id).where(TeamVersion.team_id == team.id)).all()
    )
    grant_ids = list(
        db.scalars(
            select(TeamProviderStandingGrant.id).where(TeamProviderStandingGrant.team_id == team.id)
        ).all()
    )
    if grant_ids:
        db.execute(
            update(TeamProviderConsentBinding)
            .where(TeamProviderConsentBinding.standing_grant_id.in_(grant_ids))
            .values(standing_grant_id=None)
        )
        db.execute(
            delete(TeamProviderStandingGrant).where(TeamProviderStandingGrant.id.in_(grant_ids))
        )
    if version_ids:
        db.execute(
            delete(TeamMemberInvokeGrant).where(
                TeamMemberInvokeGrant.team_version_id.in_(version_ids)
            )
        )
        db.execute(delete(TeamVersionSet).where(TeamVersionSet.team_version_id.in_(version_ids)))
        db.execute(delete(CourseTeamPublication).where(CourseTeamPublication.team_id == team.id))
        db.execute(
            delete(TeamVersionMember).where(TeamVersionMember.team_version_id.in_(version_ids))
        )
        db.execute(delete(TeamVersion).where(TeamVersion.team_id == team.id))
    purge_ids(db, "teams", [team.id])


def detach_conversation_answers(db: Session, conversation_id: str) -> None:
    """Point record rows off the chat without removing their answer payloads."""

    pairs = (
        (LearningRecord, LearningRecord.conversation_id),
        (LearningAssessment, LearningAssessment.created_conversation_id),
        (LearningAssessmentRevision, LearningAssessmentRevision.conversation_id),
        (LearningBoundary, LearningBoundary.conversation_id),
        (AssessmentAttempt, AssessmentAttempt.source_conversation_id),
        (LearningAssessmentMutation, LearningAssessmentMutation.conversation_id),
        (LearningAssessmentResourceGrant, LearningAssessmentResourceGrant.conversation_id),
    )
    for model, column in pairs:
        db.execute(update(model).where(column == conversation_id).values({column.key: None}))


def hard_delete_conversation(
    db: Session, conversation: Conversation, data_root: Path | None
) -> None:
    conversation_id = conversation.id
    from app.modules.workspace.models import ConversationAttachment

    file_paths = list(
        db.scalars(
            select(ConversationAttachment.relative_path).where(
                ConversationAttachment.conversation_id == conversation_id
            )
        ).all()
    )
    detach_conversation_answers(db, conversation_id)
    db.execute(
        delete(RuntimeModelCallStage).where(
            RuntimeModelCallStage.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(RuntimeToolReceipt).where(RuntimeToolReceipt.conversation_id == conversation_id)
    )
    db.execute(
        delete(ChatProviderConsentBinding).where(
            ChatProviderConsentBinding.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(ChatMemoryEntryAction).where(
            ChatMemoryEntryAction.conversation_id == conversation_id
        )
    )
    result_ids = select(TeamTurnResult.id).where(TeamTurnResult.conversation_id == conversation_id)
    db.execute(
        delete(TeamProviderConsentBinding).where(
            TeamProviderConsentBinding.result_id.in_(result_ids)
        )
    )
    db.execute(delete(TeamProviderCall).where(TeamProviderCall.result_id.in_(result_ids)))
    if purge_ids(db, "agent_conversations", [conversation_id]):
        for relative in file_paths:
            unlink_after_commit(db, data_root, relative)


def hard_delete_document(db: Session, document: KnowledgeDocument, data_root: Path | None) -> None:
    file_id = document.stored_file_id
    protected = select(KnowledgeSnapshot.id).where(KnowledgeSnapshot.owner_debate_id.is_not(None))
    pinned = select(DebateParticipant.knowledge_snapshot_id).where(
        DebateParticipant.knowledge_snapshot_id.is_not(None)
    )
    db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.document_id == document.id,
            KnowledgeChunk.snapshot_id.not_in(protected),
            KnowledgeChunk.snapshot_id.not_in(pinned),
        )
    )
    from app.core.models import KnowledgeDocumentChunk
    from app.modules.knowledge_sets.models import KnowledgeDocumentVersion

    db.execute(
        delete(KnowledgeDocumentChunk).where(KnowledgeDocumentChunk.document_id == document.id)
    )
    db.execute(
        delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == document.id)
    )
    db.execute(delete(AgentVersionDocument).where(AgentVersionDocument.document_id == document.id))
    purge_ids(db, "knowledge_documents", [document.id])
    release_stored_file(db, data_root, file_id)


def hard_delete_knowledge_set(db: Session, row: KnowledgeSet, data_root: Path | None) -> None:
    del data_root
    asset_ids = list(
        db.scalars(select(KnowledgeAsset.id).where(KnowledgeAsset.knowledge_set_id == row.id)).all()
    )
    if asset_ids:
        from app.modules.knowledge_sets.models import KnowledgeAssetVersion

        version_ids = list(
            db.scalars(
                select(KnowledgeAssetVersion.id).where(
                    KnowledgeAssetVersion.asset_id.in_(asset_ids)
                )
            ).all()
        )
        if version_ids:
            db.execute(
                update(AssessmentAttemptQuestion)
                .where(AssessmentAttemptQuestion.question_version_id.in_(version_ids))
                .values(question_version_id=None)
            )
            db.execute(
                update(AssessmentActivityQuestion)
                .where(AssessmentActivityQuestion.question_version_id.in_(version_ids))
                .values(question_version_id=None)
            )
        db.execute(
            update(AssessmentActivityQuestion)
            .where(AssessmentActivityQuestion.knowledge_set_id == row.id)
            .values(knowledge_set_id=None, asset_id=None, question_version_id=None)
        )
    run_ids = list(
        db.scalars(
            select(KnowledgeGenerationRun.id).where(
                KnowledgeGenerationRun.knowledge_set_id == row.id
            )
        ).all()
    )
    if run_ids:
        db.execute(
            delete(KnowledgeGenerationTargetSnapshot).where(
                KnowledgeGenerationTargetSnapshot.run_id.in_(run_ids)
            )
        )
    db.execute(
        delete(KnowledgeSetMarkdownVersion).where(
            KnowledgeSetMarkdownVersion.knowledge_set_id == row.id
        )
    )
    db.execute(delete(AgentKnowledgeSet).where(AgentKnowledgeSet.knowledge_set_id == row.id))
    # Team version rows keep a null set id so chat selection still fails closed.
    # Generation runs go with their accepted stages, items, receipts and targets.
    purge_ids(db, "knowledge_sets", [row.id])


def hard_delete_voice(db: Session, profile: VoiceProfile, data_root: Path | None) -> None:
    file_id = profile.sample_file_id
    db.execute(
        update(AgentVersion)
        .where(AgentVersion.voice_profile_id == profile.id)
        .values(voice_profile_id=None)
    )
    purge_ids(db, "voice_profiles", [profile.id])
    release_stored_file(db, data_root, file_id)


def _versions_in_use(db: Session, version_ids: list[str]) -> set[str]:
    """Versions something live still runs on; prune leaves them whole.

    A mid-reply chat, a Team chat kept on its old Team version (an unfinished
    formal attempt, a departed member's replies), a Team that could not follow
    its member, and an unfinished assessment all keep reading the version's
    AGENT.md, files and voice. The sweep prunes them once they move on.
    """

    if not version_ids:
        return set()
    live_chat = (Conversation.source_removed_at.is_(None), Conversation.withdrawn_at.is_(None))
    queries = (
        # Any chat row that still names the version keeps it, withdrawn ones
        # included: ck_conversations_entry forbids clearing agent_version_id on
        # a single-Agent chat whose source was not removed, and the chat's own
        # record must not change. It is pruned once that chat is deleted.
        select(Conversation.agent_version_id).where(Conversation.agent_version_id.in_(version_ids)),
        select(ConversationParticipant.agent_version_id)
        .join(Conversation, Conversation.id == ConversationParticipant.conversation_id)
        .where(ConversationParticipant.agent_version_id.in_(version_ids), *live_chat),
        select(TeamVersionMember.agent_version_id)
        .join(TeamVersion, TeamVersion.id == TeamVersionMember.team_version_id)
        .join(Team, Team.id == TeamVersion.team_id)
        .where(
            TeamVersionMember.agent_version_id.in_(version_ids),
            TeamVersion.version_seq == Team.current_version_seq,
            Team.deleted_at.is_(None),
        ),
    )
    used: set[str] = set()
    for query in queries:
        used.update(value for value in db.scalars(query).all() if value)
    unfinished = select(AssessmentAttempt.activity_id).where(
        AssessmentAttempt.status.in_(("in_progress", "paused"))
    )
    for row in db.execute(
        select(
            AssessmentActivity.recipe_version_id,
            AssessmentActivity.evaluator_agent_version_id,
            AssessmentActivity.boundary_agent_version_id,
        ).where(AssessmentActivity.id.in_(unfinished))
    ).all():
        used.update(value for value in row if value in version_ids)
    return used


def _strip_version_sources(db: Session, version: AgentVersion, data_root: Path | None) -> None:
    """Older versions keep AGENT.md only. Debate copies are not these rows."""

    db.execute(
        delete(AgentVersionDocument).where(AgentVersionDocument.agent_version_id == version.id)
    )
    version.voice_profile_id = None
    snapshot_id = version.knowledge_snapshot_id
    version.knowledge_snapshot_id = None
    db.flush()
    if snapshot_id:
        delete_snapshots(db, [snapshot_id], data_root)


def prune_agent_versions(db: Session, agent_id: str, data_root: Path | None) -> int:
    """Keep the current version and, at most, the previous version's AGENT.md."""

    agent = db.get(Agent, agent_id)
    if agent is None:
        return 0
    versions = list(
        db.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_seq.desc())
        ).all()
    )
    current_id = agent.current_published_version_id
    draft_ids = {row.id for row in versions if row.state == "draft"}
    # Cascade parks the owner's open draft as superseded until publish returns.
    # That row is restored afterwards; pruning it would drop the edit.
    parked_ids = set(
        db.scalars(
            select(FileOperation.entity_id).where(
                FileOperation.operation_kind == "agent_cascade_park",
                FileOperation.state == "prepared",
            )
        ).all()
    )
    superseded = [row for row in versions if row.state == "superseded" and row.id not in parked_ids]
    keep_previous = superseded[0].id if superseded else None
    in_use = _versions_in_use(db, [row.id for row in versions])
    removed = 0
    for version in versions:
        if (
            version.state == "published"
            or version.id == current_id
            or version.id in draft_ids
            or version.id in parked_ids
            or version.id in in_use
        ):
            continue
        _strip_version_sources(db, version, data_root)
        if version.id == keep_previous:
            continue
        if (
            db.scalar(
                select(AssessmentActivity.id)
                .where(
                    or_(
                        AssessmentActivity.recipe_version_id == version.id,
                        AssessmentActivity.evaluator_agent_version_id == version.id,
                        AssessmentActivity.boundary_agent_version_id == version.id,
                    )
                )
                .limit(1)
            )
            is not None
        ):
            # A finished assessment names this version as provenance.
            continue
        removed += len(purge_ids(db, "agent_versions", [version.id]))
    db.flush()
    return removed
