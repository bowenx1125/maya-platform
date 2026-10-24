"""Remove empty Agents that a failed create left behind.

Owner decision (2026-10-24): an empty failed Agent is cleaned up globally,
not only when the owner retries the same name. The existing five-minute sweep
deletes an owner's Agent that has no published or written version, no files,
and no Team, Debate or chat reference. The hour of grace keeps a create that is
still between its two requests (row, then AGENT.md). A draft the same-name
retry already retired is removed by the same pass.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import Agent, AgentVersion, AgentVersionDocument, DemoAcceptanceRun
from app.modules.debates.models import DebateParticipant
from app.modules.knowledge_sets.models import KnowledgeGenerationRun
from app.modules.teams.models import TeamVersionMember
from app.modules.workspace.models import AgentAccountMemory, Conversation, ConversationParticipant

LOGGER = logging.getLogger(__name__)

ABANDONED_AGENT_AGE = timedelta(hours=1)


def sweep_abandoned_agents(db: Session, *, now: datetime | None = None) -> int:
    """Hard-delete empty abandoned drafts past the age threshold."""

    cutoff = (now or datetime.now(UTC)) - ABANDONED_AGENT_AGE
    candidates = list(
        db.scalars(
            select(Agent).where(
                Agent.owner_user_id.is_not(None),
                Agent.current_published_version_id.is_(None),
                Agent.updated_at < cutoff,
            )
        ).all()
    )
    removed = 0
    for agent in candidates:
        if not _is_empty_abandoned(db, agent):
            continue
        nested = db.begin_nested()
        try:
            db.delete(agent)
            db.flush()
            nested.commit()
            removed += 1
        except IntegrityError:
            nested.rollback()
            LOGGER.info("abandoned_agent_delete_blocked agent_id=%s", agent.id)
    db.commit()
    if removed:
        LOGGER.info("abandoned_agent_sweep removed=%d", removed)
    return removed


def _is_empty_abandoned(db: Session, agent: Agent) -> bool:
    versions = list(db.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent.id)).all())
    if any(version.state != "draft" or (version.agent_md or "").strip() for version in versions):
        return False
    version_ids = [version.id for version in versions]
    if version_ids and _has_documents(db, version_ids):
        return False
    if _referenced(db, agent.id, version_ids):
        return False
    return True


def _has_documents(db: Session, version_ids: list[str]) -> bool:
    return (
        db.scalar(
            select(AgentVersionDocument.document_id)
            .where(AgentVersionDocument.agent_version_id.in_(version_ids))
            .limit(1)
        )
        is not None
    )


def _referenced(db: Session, agent_id: str, version_ids: list[str]) -> bool:
    checks = [
        select(TeamVersionMember.id).where(TeamVersionMember.agent_id == agent_id),
        select(DebateParticipant.id).where(DebateParticipant.agent_id == agent_id),
        select(ConversationParticipant.id).where(ConversationParticipant.agent_id == agent_id),
        select(KnowledgeGenerationRun.id).where(KnowledgeGenerationRun.agent_id == agent_id),
        select(AgentAccountMemory.id).where(AgentAccountMemory.agent_id == agent_id),
        select(DemoAcceptanceRun.id).where(
            or_(
                DemoAcceptanceRun.baseline_agent_id == agent_id,
                DemoAcceptanceRun.target_agent_id == agent_id,
            )
        ),
    ]
    if version_ids:
        checks.append(select(Conversation.id).where(Conversation.agent_version_id.in_(version_ids)))
    return any(db.scalar(check.limit(1)) is not None for check in checks)
