"""Persistence/API checks for Wave 4 Persona compilation and confirmation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.db import Database
from app.seed import GROUP_DEMO_ID
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from tests.postgres_db import named_url

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _persona_md(name: str, *, role: str = "Watershed steward") -> str:
    return f"""# {name}

## Identity

- Role: {role}
- Historical or cultural context: A fictional community keeper of shared water memory.

## Cultural lens

- Intergenerational responsibility

## Core values

- Reciprocity

## Initial position

Protect shared resources through careful, long-term stewardship.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
"""


def _create_agent(
    client: TestClient, csrf: str, key: str = "persona-api-create-001"
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={"name": "River Keeper", "description": "Persona API fixture"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_0009_columns_are_nullable_for_legacy_and_constraints_are_reversible(
    tmp_path: Path,
) -> None:
    database = Database(named_url(f"{tmp_path / 'persona.sqlite3'}"), tmp_path)
    database.upgrade_schema()
    inspector = inspect(database.engine)
    columns = {item["name"]: item for item in inspector.get_columns("agent_versions")}
    assert {
        "raw_agent_md_hash",
        "persona_spec_json",
        "persona_spec_hash",
        "persona_compiler_version",
        "persona_diagnostics_json",
        "persona_confirmation_revision",
        "student_confirmed_at",
        "persona_confirming_user_id",
    }.issubset(columns)
    assert all(
        columns[name]["nullable"]
        for name in columns
        if (name.startswith("persona_") and name != "persona_required")
        or name == "raw_agent_md_hash"
    )
    assert columns["persona_required"]["nullable"] is False
