"""What keeps an Agent out of a Debate, named per Agent.

Owner decision (2026-10-24): a failed Debate create lists every problem of
every selected Agent at once, each with the Agent's id so the page can open
that Agent's editor. The same rules drive the hint bar on the Agent page.

AGENT.md has no fixed chapters. The one rule stated here, and in the
message the teacher reads, is that it has a heading line starting with ``#``
and some body text under it.

Voice None is shown to the teacher but never refuses a Debate: speech falls
back to the configured voice or to text, and text publication never waits on
a voice (AGENTS.md).

Owner decision (2026-10-24): none of these stop an Agent being saved or
published. They are hints on the Agent page and on the Debate form, read from
the Agent's current published version, and only creating a Debate refuses the
blocking ones.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import Agent, AgentVersion, KnowledgeSnapshot

ISSUE_MESSAGES = {
    "agent_archived": "Agent “{name}” was deleted or archived.",
    "agent_not_published": "Agent “{name}” has no published version.",
    "rag_missing": "Agent “{name}” needs at least one RAG file.",
    "agent_md_invalid": (
        "Agent “{name}” has a non-standard AGENT.md: it needs a heading line "
        "starting with # and some text under it."
    ),
    "avatar_missing": "Agent “{name}” has no usable Avatar.",
    "agent_not_current": (
        "Agent “{name}” changed while the Debate was being created. Check it and create again."
    ),
    "agent_not_found": "Agent “{name}” is no longer available in this course.",
    "voice_missing": (
        "Agent “{name}” has Voice set to None: it will speak with the default voice, or as text."
    ),
}
NON_BLOCKING = frozenset({"voice_missing"})

_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


def agent_md_is_standard(markdown: str) -> bool:
    if not _HEADING.search(markdown):
        return False
    body = [
        line for line in markdown.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    return bool(body)


def issue(agent: Agent, kind: str) -> dict[str, Any]:
    return named_issue(agent.id, agent.name, kind)


def named_issue(agent_id: str, agent_name: str, kind: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "agent_name": agent_name,
        "issue": kind,
        "blocking": kind not in NON_BLOCKING,
        "message": ISSUE_MESSAGES[kind].format(name=agent_name),
    }


def debate_issues(db: Session, agent: Agent, settings: Settings) -> list[dict[str, Any]]:
    """Every reason this Agent cannot join a new Debate; empty when it can."""

    del settings
    return [item for item in readiness_issues(db, agent) if item["blocking"]]


def readiness_issues(db: Session, agent: Agent) -> list[dict[str, Any]]:
    """Every hint for this Agent's current published version, Voice None included."""

    if agent.deleted_at is not None or agent.status == "archived":
        return [issue(agent, "agent_archived")]
    version = (
        db.get(AgentVersion, agent.current_published_version_id)
        if agent.current_published_version_id
        else None
    )
    if version is None or version.agent_id != agent.id or version.state != "published":
        return [issue(agent, "agent_not_published")]
    found: list[dict[str, Any]] = []
    snapshot = (
        db.get(KnowledgeSnapshot, version.knowledge_snapshot_id)
        if version.knowledge_snapshot_id
        else None
    )
    if snapshot is None or snapshot.agent_version_id != version.id:
        found.append(issue(agent, "rag_missing"))
    if not agent_md_is_standard(version.agent_md or ""):
        found.append(issue(agent, "agent_md_invalid"))
    try:
        import json

        from app.modules.avatars import validate_avatar_config

        validate_avatar_config(json.loads(version.avatar_config_json))
    except Exception:  # noqa: BLE001
        found.append(issue(agent, "avatar_missing"))
    if not version.voice_profile_id:
        found.append(issue(agent, "voice_missing"))
    return found
