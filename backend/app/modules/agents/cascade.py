"""Auto-publish the Agents that lose a RAG file or a Voice.

Owner decision (2026-10-20): deleting (or editing) a RAG file or a Voice
publishes a new version of every live Agent whose current published version
uses it. The deleted file is dropped and a deleted Voice is cleared, so the
Agent keeps working (no RAG -> plain Agent, no Voice -> silent in Immerse).
The publish runs as the Agent's owner and reuses that owner's existing
provider consent; nobody is prompted. Teams follow through the normal
``follow_published_agent`` hook inside publish. Debates keep their own
version and snapshot and are never touched.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion, AgentVersionDocument, User

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AffectedAgent:
    agent_id: str
    name: str
    owner_user_id: str | None
    version_seq: int


def _live_current_versions(db: Session) -> Any:
    return (
        select(Agent, AgentVersion)
        .join(AgentVersion, AgentVersion.id == Agent.current_published_version_id)
        .where(
            Agent.deleted_at.is_(None),
            Agent.status == "active",
            AgentVersion.state == "published",
        )
    )


def affected_agents(
    db: Session,
    *,
    document_ids: Iterable[str] = (),
    voice_profile_ids: Iterable[str] = (),
) -> list[AffectedAgent]:
    """Live Agents whose current published version uses any given file or Voice."""

    docs = [str(item) for item in document_ids]
    voices = [str(item) for item in voice_profile_ids]
    found: dict[str, AffectedAgent] = {}
    if docs:
        rows = db.execute(
            _live_current_versions(db)
            .join(
                AgentVersionDocument,
                AgentVersionDocument.agent_version_id == AgentVersion.id,
            )
            .where(AgentVersionDocument.document_id.in_(docs))
        ).all()
        for agent, version in rows:
            found[agent.id] = AffectedAgent(
                agent.id, agent.name, agent.owner_user_id, version.version_seq
            )
    if voices:
        rows = db.execute(
            _live_current_versions(db).where(AgentVersion.voice_profile_id.in_(voices))
        ).all()
        for agent, version in rows:
            found[agent.id] = AffectedAgent(
                agent.id, agent.name, agent.owner_user_id, version.version_seq
            )
    return sorted(found.values(), key=lambda item: (item.name.casefold(), item.agent_id))


def _owner_context(db: Session, agent: Agent) -> Any:
    from app.modules.auth.service import AuthContext

    owner = db.get(User, agent.owner_user_id) if agent.owner_user_id else None
    if owner is None or owner.status != "active":
        return None
    return AuthContext("", None, owner, "")  # type: ignore[arg-type]


def bump_agent(
    db: Session,
    settings: Settings,
    agent_id: str,
    *,
    drop_document_ids: Iterable[str] = (),
    drop_voice_profile_ids: Iterable[str] = (),
) -> str | None:
    """Publish the next version of one Agent without the given files/Voices.

    Returns the new published version id, or ``None`` when nothing applied.
    An owner's unpublished draft is kept: it moves one sequence number up and
    loses the same files/Voice, so their edit is not published by accident.
    """

    from app.modules.agents.persona import raw_agent_md_hash
    from app.modules.agents.router import _publish_agent_version_admitted, _time
    from app.modules.agents.schemas import PublishAgentVersionRequest

    drop_docs = {str(item) for item in drop_document_ids}
    drop_voices = {str(item) for item in drop_voice_profile_ids}
    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None or agent.status != "active":
        return None
    current = (
        db.get(AgentVersion, agent.current_published_version_id)
        if agent.current_published_version_id
        else None
    )
    if current is None or current.state != "published":
        return None
    relations = list(
        db.scalars(
            select(AgentVersionDocument)
            .where(AgentVersionDocument.agent_version_id == current.id)
            .order_by(AgentVersionDocument.order_index)
        ).all()
    )
    uses_doc = any(rel.document_id in drop_docs for rel in relations)
    uses_voice = current.voice_profile_id is not None and current.voice_profile_id in drop_voices
    if not uses_doc and not uses_voice:
        return None
    context = _owner_context(db, agent)
    if context is None:
        LOGGER.warning("Agent auto-bump skipped: owner inactive agent_id=%s", agent_id)
        return None

    max_seq = (
        db.scalar(
            select(func.max(AgentVersion.version_seq)).where(AgentVersion.agent_id == agent.id)
        )
        or current.version_seq
    )
    draft = db.scalar(
        select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.state == "draft")
    )
    timestamp = _time()
    # Only one draft may exist per Agent. Park the owner's unpublished edit,
    # publish the auto version, then restore the edit as a fresh draft (minus
    # the same files/Voice) so it is never published by accident.
    parked: dict[str, Any] | None = None
    if draft is not None:
        parked = {
            "agent_md": draft.agent_md,
            "avatar_config_json": draft.avatar_config_json,
            "voice_profile_id": (
                None if draft.voice_profile_id in drop_voices else draft.voice_profile_id
            ),
            "draft_visibility": draft.draft_visibility,
            "persona_required": draft.persona_required,
            "docs": [
                (rel.document_id, rel.enabled)
                for rel in db.scalars(
                    select(AgentVersionDocument)
                    .where(AgentVersionDocument.agent_version_id == draft.id)
                    .order_by(AgentVersionDocument.order_index)
                ).all()
                if rel.document_id not in drop_docs
            ],
        }
        for rel in db.scalars(
            select(AgentVersionDocument).where(AgentVersionDocument.agent_version_id == draft.id)
        ).all():
            db.delete(rel)
        db.delete(draft)
        db.flush()
    version = AgentVersion(
        id=str(uuid4()),
        agent_id=agent.id,
        version_seq=max_seq + 1,
        state="draft",
        revision=0,
        agent_md=current.agent_md,
        raw_agent_md_hash=raw_agent_md_hash(current.agent_md),
        persona_spec_json=current.persona_spec_json,
        persona_spec_hash=current.persona_spec_hash,
        persona_compiler_version=current.persona_compiler_version,
        persona_diagnostics_json=current.persona_diagnostics_json,
        persona_confirmation_revision=None,
        student_confirmed_at=current.student_confirmed_at,
        persona_confirming_user_id=current.persona_confirming_user_id,
        persona_required=current.persona_required,
        avatar_config_json=current.avatar_config_json,
        voice_profile_id=None if uses_voice else current.voice_profile_id,
        knowledge_snapshot_id=None,
        authorization_epoch=agent.authorization_epoch,
        draft_visibility=current.published_visibility or current.draft_visibility,
        published_visibility=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(version)
    db.flush()
    order = 0
    for rel in relations:
        if rel.document_id in drop_docs:
            continue
        db.add(
            AgentVersionDocument(
                agent_version_id=version.id,
                document_id=rel.document_id,
                enabled=rel.enabled,
                order_index=order,
            )
        )
        order += 1
    db.commit()
    version_id = version.id
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    try:
        _publish_agent_version_admitted(
            UUID(version_id),
            PublishAgentVersionRequest(expected_revision=0),
            f"auto-bump-{version_id}",
            context,
            db,
            settings,
            request,  # type: ignore[arg-type]
        )
    except PlatformError as error:
        db.rollback()
        LOGGER.warning("Agent auto-bump publish failed agent_id=%s code=%s", agent_id, error.code)
        _discard_failed_draft(db, version_id)
        _restore_parked_draft(db, agent_id, parked)
        return None
    _restore_parked_draft(db, agent_id, parked)
    return version_id


def _restore_parked_draft(db: Session, agent_id: str, parked: dict[str, Any] | None) -> None:
    if parked is None:
        return
    from app.modules.agents.persona import raw_agent_md_hash
    from app.modules.agents.router import _time

    agent = db.get(Agent, agent_id)
    if agent is None or agent.deleted_at is not None:
        return
    max_seq = (
        db.scalar(
            select(func.max(AgentVersion.version_seq)).where(AgentVersion.agent_id == agent_id)
        )
        or 0
    )
    timestamp = _time()
    restored = AgentVersion(
        id=str(uuid4()),
        agent_id=agent_id,
        version_seq=max_seq + 1,
        state="draft",
        revision=0,
        agent_md=parked["agent_md"],
        raw_agent_md_hash=raw_agent_md_hash(parked["agent_md"]),
        persona_required=parked["persona_required"],
        avatar_config_json=parked["avatar_config_json"],
        voice_profile_id=parked["voice_profile_id"],
        knowledge_snapshot_id=None,
        authorization_epoch=agent.authorization_epoch,
        draft_visibility=parked["draft_visibility"],
        published_visibility=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(restored)
    db.flush()
    for index, (document_id, enabled) in enumerate(parked["docs"]):
        db.add(
            AgentVersionDocument(
                agent_version_id=restored.id,
                document_id=document_id,
                enabled=enabled,
                order_index=index,
            )
        )
    db.commit()


def _discard_failed_draft(db: Session, version_id: str) -> None:
    leftover = db.get(AgentVersion, version_id)
    if leftover is not None and leftover.state == "draft":
        for rel in db.scalars(
            select(AgentVersionDocument).where(AgentVersionDocument.agent_version_id == version_id)
        ).all():
            db.delete(rel)
        db.delete(leftover)
        db.commit()


def cascade_removed_sources(
    database: Database,
    settings: Settings,
    *,
    agent_ids: Iterable[str],
    document_ids: Iterable[str] = (),
    voice_profile_ids: Iterable[str] = (),
) -> list[str]:
    """Background entry point: bump each Agent in its own session."""

    docs = list(document_ids)
    voices = list(voice_profile_ids)
    published: list[str] = []
    for agent_id in agent_ids:
        session = database.session_factory()
        session.info["maya_settings"] = settings
        try:
            new_id = bump_agent(
                session,
                settings,
                agent_id,
                drop_document_ids=docs,
                drop_voice_profile_ids=voices,
            )
            if new_id is not None:
                published.append(new_id)
        except Exception:  # noqa: BLE001 - one Agent must not stop the others
            session.rollback()
            LOGGER.exception("Agent auto-bump crashed agent_id=%s", agent_id)
        finally:
            session.close()
    LOGGER.info(
        "Agent auto-bump done at=%s published=%d", datetime.now(UTC).isoformat(), len(published)
    )
    return published
