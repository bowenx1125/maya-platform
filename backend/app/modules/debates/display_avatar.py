"""Live Agent avatar for Debate display (Immerse / Live).

Debate create still freezes card, RAG and voice. Avatar is not part of that
semantic snapshot: stage and Live read the Agent's current published avatar,
or the catalog default when the Agent is gone or has no usable config.
Stored ``avatar_config_json`` on the participant stays for NOT NULL /
compatibility and is ignored for display.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import Agent, AgentVersion
from app.modules.avatars import (
    DEFAULT_AVATAR_CONFIG,
    AvatarConfigValidationError,
    validate_avatar_config,
)
from app.modules.debates.models import DebateParticipant


def participant_display_avatar(
    db: Session | None, participant: DebateParticipant
) -> dict[str, Any]:
    """Avatar the stage should show for this participant right now."""

    agent_id = getattr(participant, "agent_id", None)
    if agent_id and db is not None:
        agent = db.get(Agent, agent_id)
        if (
            agent is not None
            and agent.deleted_at is None
            and agent.status == "active"
            and agent.current_published_version_id
        ):
            version = db.get(AgentVersion, agent.current_published_version_id)
            if (
                version is not None
                and version.agent_id == agent.id
                and version.state == "published"
            ):
                try:
                    return validate_avatar_config(
                        json.loads(version.avatar_config_json)
                    ).model_dump(mode="json")
                except (
                    ValueError,
                    TypeError,
                    json.JSONDecodeError,
                    AvatarConfigValidationError,
                ):
                    pass
    return DEFAULT_AVATAR_CONFIG.model_dump(mode="json")
