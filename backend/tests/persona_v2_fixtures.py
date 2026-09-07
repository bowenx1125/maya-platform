"""Current five-section Persona fixture for offline domain tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.agents.persona import compile_persona_v2


def persona_v2_markdown(name: str = "River Keeper") -> str:
    return f"""# {name}

## Identity

- Role: Watershed steward
- Historical or cultural context: 一个虚构的社区守护者，记录共享水域的记忆。

## Cultural lens

- 代际责任
- Place-based memory

## Core values

- Reciprocity
- Patience

## Initial position

保护共享资源，通过谨慎的长期照护面对不完整的证据。

## Speaking style

- Tone: Calm and reflective
- Argument pattern: 先说明背景，再权衡后果
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects
"""


def confirmed_persona_v2_fields(
    name: str = "River Keeper",
    confirmed_at: datetime | None = None,
    *,
    revision: int = 1,
) -> dict[str, Any]:
    """Return versioned storage fields without adding removed V1 sections."""

    source = persona_v2_markdown(name)
    compiled = compile_persona_v2(source, expected_name=name)
    assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
    return {
        "agent_md": source,
        "raw_agent_md_hash": compiled.source_agent_md_hash,
        "persona_spec_json": compiled.canonical_json,
        "persona_spec_hash": compiled.persona_spec_hash,
        "persona_compiler_version": compiled.compiler_version,
        "persona_diagnostics_json": "[]",
        "persona_confirmation_revision": revision,
        "student_confirmed_at": confirmed_at or datetime.now(UTC),
        "persona_confirming_user_id": "fixture-student",
    }


__all__ = ["confirmed_persona_v2_fields", "persona_v2_markdown"]
