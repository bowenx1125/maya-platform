"""Avatar-only writes preserve the published persona, Voice and indexed evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.errors import conflict, invalid_state, stale_revision, validation_failure
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    Base,
    KnowledgeChunk,
    KnowledgeSnapshot,
    SnapshotDocument,
)
from app.modules.agents.schemas import DrawingMouth, SaveAvatarRequest
from app.modules.avatars import AvatarConfigValidationError, validate_avatar_config


def _copy[Row: Base](row: Row, **changes: Any) -> Row:
    values = {attr.key: getattr(row, attr.key) for attr in inspect(type(row)).column_attrs}
    return type(row)(**(values | changes))


def save_avatar(
    db: Session, agent: Agent, version: AgentVersion, payload: SaveAvatarRequest
) -> AgentVersion:
    if agent.status != "active" or agent.deleted_at is not None:
        raise invalid_state("The Agent is unavailable.")
    expected = (
        str(payload.expected_published_version_id)
        if payload.expected_published_version_id
        else None
    )
    if agent.current_published_version_id != expected:
        raise conflict(
            "stale_base_version", "Someone else published a newer version of this Agent."
        )
    if version.revision != payload.expected_revision:
        raise stale_revision(version.revision)
    if version.state == "superseded":
        raise conflict(
            "stale_base_version", "Someone else published a newer version of this Agent."
        )
    try:
        config = validate_avatar_config(payload.avatar_config)
        previous = validate_avatar_config(json.loads(version.avatar_config_json))
    except (AvatarConfigValidationError, ValueError) as exc:
        raise validation_failure(
            "The avatar configuration is invalid.", code="avatar_missing"
        ) from exc
    if (
        config.drawing is not None
        and not config.drawing.strokes
        and config.drawing.mouth == DrawingMouth()
    ):
        config = config.model_copy(update={"drawing": None})
    if (
        previous.drawing is not None
        and not previous.drawing.strokes
        and previous.drawing.mouth == DrawingMouth()
    ):
        previous = previous.model_copy(update={"drawing": None})
    if config == previous:
        return version
    timestamp = datetime.now(UTC)
    if version.state == "draft" and agent.current_published_version_id:
        raise invalid_state("An Agent can have only one draft version.")
    if version.state == "draft":
        # The draft's revision fences all writers; changing only Avatar does
        # not change the already-confirmed persona's source or meaning.
        version.avatar_config_json = config.model_dump_json()
        version.revision += 1
        if version.persona_confirmation_revision is not None:
            version.persona_confirmation_revision = version.revision
        version.updated_at = timestamp
        return version
    if agent.current_published_version_id != version.id:
        raise conflict(
            "stale_base_version", "Someone else published a newer version of this Agent."
        )
    # A separate open draft cannot be safely rebased without its editor's
    # source selection. Keep it intact and require that editor to finish first.
    if db.scalar(
        select(AgentVersion.id).where(
            AgentVersion.agent_id == agent.id, AgentVersion.state == "draft"
        )
    ):
        raise invalid_state("An Agent can have only one draft version.")
    next_seq = db.scalar(
        select(func.max(AgentVersion.version_seq)).where(AgentVersion.agent_id == agent.id)
    )
    published = _copy(
        version,
        id=str(uuid4()),
        version_seq=(next_seq or 0) + 1,
        revision=0,
        avatar_config_json=config.model_dump_json(),
        knowledge_snapshot_id=None,
        persona_confirmation_revision=0
        if version.persona_confirmation_revision is not None
        else None,
        created_at=timestamp,
        updated_at=timestamp,
        published_at=timestamp,
    )
    db.add(published)
    db.flush()
    for relation in db.scalars(
        select(AgentVersionDocument).where(AgentVersionDocument.agent_version_id == version.id)
    ):
        db.add(_copy(relation, agent_version_id=published.id))
    if version.knowledge_snapshot_id:
        source = db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
        if source is None or source.agent_version_id != version.id or source.owner_debate_id:
            raise invalid_state("The published knowledge is unavailable.")
        snapshot = _copy(
            source, id=str(uuid4()), agent_version_id=published.id, created_at=timestamp
        )
        db.add(snapshot)
        db.flush()
        document_ids = {}
        for document in db.scalars(
            select(SnapshotDocument).where(SnapshotDocument.snapshot_id == source.id)
        ):
            copied = _copy(document, id=str(uuid4()), snapshot_id=snapshot.id)
            document_ids[document.id] = copied.id
            db.add(copied)
        db.flush()
        for chunk in db.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.snapshot_id == source.id)
        ):
            db.add(
                _copy(
                    chunk,
                    id=str(uuid4()),
                    snapshot_id=snapshot.id,
                    snapshot_document_id=document_ids[chunk.snapshot_document_id],
                )
            )
        published.knowledge_snapshot_id = snapshot.id
    version.state = "superseded"
    version.updated_at = timestamp
    agent.current_published_version_id = published.id
    agent.updated_at = timestamp
    return published
