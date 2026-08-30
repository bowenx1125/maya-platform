"""Shared confirmed Persona fields for Debate integration fixtures.

These fixtures exercise the post-activation Debate contract.  Historical
legacy tests should construct retained Debate/turn rows directly instead of
creating a new Debate with an unconfirmed AgentVersion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.models import AgentVersion
from app.modules.agents.persona import compile_persona


def confirmed_persona_fields(
    name: str,
    confirmed_at: datetime,
    *,
    revision: int = 1,
) -> dict[str, Any]:
    """Return one canonical, confirmed Persona projection for an ORM row."""

    source = f"""# {name}

## Identity

- Role: Classroom technology ethics expert
- Historical or cultural context: A fictional cross-cultural classroom.

## Cultural lens

- Community accountability

## Core values

- Fairness
- Transparency

## Initial position

Prefer evidence-aware proportional safeguards.

## Speaking style

- Tone: Careful and respectful
- Argument pattern: State a claim, examine evidence, then qualify it
- Concession style: Acknowledge a sound point before refining it
- Question style: Ask one focused and answerable question

## Debate strategy

- Compare trade-offs without manufacturing conflict

## Boundaries

- Never invent evidence outside the assigned snapshot
"""
    compiled = compile_persona(source, expected_name=name)
    assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
    values: dict[str, Any] = {
        "agent_md": source,
        "raw_agent_md_hash": compiled.source_agent_md_hash,
        "persona_spec_json": compiled.canonical_json,
        "persona_spec_hash": compiled.persona_spec_hash,
        "persona_compiler_version": compiled.compiler_version,
        "persona_diagnostics_json": "[]",
        "persona_confirmation_revision": revision,
        "student_confirmed_at": confirmed_at,
        "persona_confirming_user_id": "fixture-student",
    }
    # The integrated P1 migration adds this server-only field.  Keeping this
    # conditional makes the fixture runnable against the pre-migration branch
    # while ensuring the field is explicit whenever the model owns it.
    if hasattr(AgentVersion, "persona_required"):
        values["persona_required"] = True
    return values


__all__ = ["confirmed_persona_fields"]
