"""Debate-owned copies of the sources a participant was frozen from.

A Debate must not depend on live Agent, version or voice rows (2026-10-20):
those can now be hard-deleted. The knowledge snapshot (frozen combined file
and chunks) is already Debate-safe because pruning never removes a snapshot a
Debate references; this module copies the rest onto the participant row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import AgentVersion, VoiceProfile


def voice_snapshot(profile: VoiceProfile | None) -> tuple[str | None, bytes | None]:
    if profile is None:
        return None, None
    payload = {
        "voice_profile_id": profile.id,
        "display_name": profile.display_name,
        "scope": profile.scope,
        "provider_key": profile.provider_key,
        "target_model_key": profile.target_model_key,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")), profile.external_id_encrypted


def fill_owned_copies(db: Session, row: object) -> bool:
    """Fill missing copies on one ``DebateParticipant``; True when changed."""

    changed = False
    if getattr(row, "agent_md_snapshot", None) is None:
        version_id = getattr(row, "agent_version_id", None)
        version = db.get(AgentVersion, version_id) if version_id else None
        if version is not None:
            row.agent_md_snapshot = version.agent_md  # type: ignore[attr-defined]
            changed = True
    if getattr(row, "voice_snapshot_json", None) is None:
        profile_id = getattr(row, "effective_voice_profile_id", None)
        profile = db.get(VoiceProfile, profile_id) if profile_id else None
        payload, cipher = voice_snapshot(profile)
        if payload is not None:
            row.voice_snapshot_json = payload  # type: ignore[attr-defined]
            row.voice_external_id_encrypted = cipher  # type: ignore[attr-defined]
            changed = True
    return changed


@dataclass(frozen=True)
class FrozenOwner:
    course_id: str
    group_id: str | None
    version_id: str | None
    agent_md: str
    persona_spec_hash: str


def frozen_owner(db: Session, row: Any) -> FrozenOwner:
    """Everything a running Debate needs about a participant's source Agent.

    Reads only the participant row; the live version is a fallback for rows
    written before 0077 that have no AGENT.md copy yet.
    """

    agent_md = row.agent_md_snapshot
    persona_hash = getattr(row, "persona_spec_hash_snapshot", None)
    if agent_md is None or persona_hash is None:
        version = db.get(AgentVersion, row.agent_version_id) if row.agent_version_id else None
        if version is None and agent_md is None:
            raise ValueError("the frozen participant AGENT.md is unavailable")
        if version is not None:
            agent_md = version.agent_md if agent_md is None else agent_md
            persona_hash = version.persona_spec_hash if persona_hash is None else persona_hash
    return FrozenOwner(
        course_id=str(row.course_id),
        group_id=str(row.group_id) if row.group_id else None,
        version_id=str(row.agent_version_id) if row.agent_version_id else None,
        agent_md=str(agent_md or ""),
        persona_spec_hash=str(persona_hash or ""),
    )
