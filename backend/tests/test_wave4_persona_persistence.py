"""Persistence/API checks for Wave 4 Persona compilation and confirmation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from app.core.db import Database
from app.core.models import Agent, AgentVersion
from app.modules.agents.persona import compile_persona, raw_agent_md_hash
from app.seed import GROUP_BOWEN_ID, seed_demo_data
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import login

BOWEN_GROUP_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"


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
        f"/api/v1/groups/{BOWEN_GROUP_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={"name": "River Keeper", "description": "Persona API fixture"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_compile_confirm_and_raw_edit_clear_persona_atomically(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent = _create_agent(client, csrf)
    version_id = agent["versions"][0]["id"]
    avatar = agent["versions"][0]["avatar_config"]
    raw = _persona_md("River Keeper")

    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": raw,
            "avatar_config": avatar,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 1
    assert updated.json()["raw_agent_md_hash"] == raw_agent_md_hash(raw)
    assert updated.json()["persona_spec"] is None

    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 1},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    assert compiled_body["compiled"] is True
    assert compiled_body["persona_spec"]["schema_version"] == "persona_spec_v1"
    assert compiled_body["persona_spec_hash"]
    assert compiled_body["diagnostics"] == []
    assert "persona_confirming_user_id" not in compiled_body

    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 1,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    assert confirmed_body["persona_confirmed"] is True
    assert confirmed_body["persona_confirmation_revision"] == 1
    assert confirmed_body["student_confirmed_at"]
    assert "persona_confirming_user_id" not in confirmed_body

    changed_raw = "# River Keeper\n\nThis no longer follows the Persona template."
    edited = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 1, "agent_md": changed_raw},
    )
    assert edited.status_code == 200, edited.text
    edited_body = edited.json()
    assert edited_body["revision"] == 2
    assert edited_body["persona_spec"] is None
    assert edited_body["persona_spec_hash"] is None
    assert edited_body["persona_confirmation_revision"] is None
    assert edited_body["student_confirmed_at"] is None
    assert edited_body["persona_confirmed"] is False

    failed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["compiled"] is False
    assert failed.json()["diagnostics"]
    reloaded = client.get(f"/api/v1/agent-versions/{version_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["persona_spec"] is None
    assert reloaded.json()["persona_confirmed"] is False


def test_compile_and_confirm_enforce_revision_and_membership(client: TestClient) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent = _create_agent(client, csrf, "persona-api-create-002")
    version_id = agent["versions"][0]["id"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": _persona_md("River Keeper"),
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200
    stale = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"

    _other, other_csrf = login(client, "student-kaikai-1")
    hidden = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(other_csrf),
        json={"expected_revision": 1},
    )
    assert hidden.status_code == 404


def test_compile_failure_does_not_keep_prior_persona_and_publish_blocks_strict_template(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent = _create_agent(client, csrf, "persona-api-create-003")
    version_id = agent["versions"][0]["id"]
    raw = _persona_md("River Keeper")
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": raw,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200
    failed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 1},
    )
    assert failed.json()["compiled"] is True
    # A strict Persona source cannot publish before confirmation, even though
    # other historical Agent drafts retain their old publication path.
    publish = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-api-publish-003"}),
        json={"expected_revision": 1},
    )
    assert publish.status_code == 422
    assert publish.json()["code"] == "persona_confirmation_required"


def test_publishing_confirmed_persona_rebinds_confirmation_to_immutable_revision(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent = _create_agent(client, csrf, "persona-api-publish-confirmed")
    version_id = agent["versions"][0]["id"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": _persona_md("River Keeper"),
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    uploaded = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-api-publish-upload"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("publish.md", b"# Publish\n\nBounded evidence.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-api-publish-confirmed"}),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["revision"] == 3
    assert body["persona_confirmation_revision"] == 3
    assert body["persona_confirmed"] is True
    assert body["raw_agent_md_hash"] == compiled_body["raw_agent_md_hash"]
    assert body["persona_spec_hash"] == compiled_body["persona_spec_hash"]


def test_document_revision_cas_preserves_confirmed_persona_without_half_update(
    client: TestClient,
) -> None:
    _user, csrf = login(client, "student-bowen-1")
    agent = _create_agent(client, csrf, "persona-api-document-revision")
    version_id = agent["versions"][0]["id"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": _persona_md("River Keeper"),
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    first = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-doc-one-123456"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={"file": ("one.md", b"# One\n\nFirst evidence.", "text/markdown")},
    )
    assert first.status_code == 201, first.text
    compiled = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/compile",
        headers=_headers(csrf),
        json={"expected_revision": 2},
    )
    assert compiled.status_code == 200, compiled.text
    compiled_body = compiled.json()
    confirmed = client.post(
        f"/api/v1/agent-versions/{version_id}/persona/confirm",
        headers=_headers(csrf),
        json={
            "expected_revision": 2,
            "raw_agent_md_hash": compiled_body["raw_agent_md_hash"],
            "persona_spec_hash": compiled_body["persona_spec_hash"],
            "compiler_version": "persona_template_v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    baseline = confirmed.json()
    first_document_id = first.json()["document"]["id"]

    second = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-doc-two-123456"}),
        data={"target_agent_version_id": version_id, "expected_revision": "2"},
        files={"file": ("two.md", b"# Two\n\nSecond evidence.", "text/markdown")},
    )
    assert second.status_code == 201, second.text
    second_version = second.json()["agent_version"]
    assert second_version["revision"] == 3
    assert second_version["persona_confirmation_revision"] == 3
    assert second_version["persona_spec_hash"] == baseline["persona_spec_hash"]
    assert second_version["student_confirmed_at"].removesuffix("Z") == baseline[
        "student_confirmed_at"
    ].removesuffix("Z")

    set_documents = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(csrf),
        json={
            "expected_revision": 3,
            "document_ids": [first_document_id, second.json()["document"]["id"]],
        },
    )
    assert set_documents.status_code == 200, set_documents.text
    set_body = set_documents.json()
    assert set_body["revision"] == 4
    assert set_body["persona_confirmation_revision"] == 4
    assert set_body["persona_spec_hash"] == baseline["persona_spec_hash"]

    stale = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": 3, "document_ids": [first_document_id]},
    )
    assert stale.status_code == 409, stale.text
    current = client.get(f"/api/v1/agent-versions/{version_id}")
    assert current.status_code == 200, current.text
    assert current.json()["revision"] == 4
    assert current.json()["persona_confirmation_revision"] == 4
    assert current.json()["persona_spec_hash"] == baseline["persona_spec_hash"]

    old_document = first.json()["document"]
    replacement = client.post(
        f"/api/v1/knowledge-documents/{first_document_id}/replace",
        headers=_headers(csrf, **{"Idempotency-Key": "persona-doc-replace-123456"}),
        data={
            "expected_content_hash": old_document["content_hash"],
            "expected_index_revision": str(old_document["index_revision"]),
        },
        files={"file": ("replacement.md", b"# Replacement\n\nNew evidence.", "text/markdown")},
    )
    assert replacement.status_code == 201, replacement.text
    replaced = client.get(f"/api/v1/agent-versions/{version_id}")
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["revision"] == 5
    assert replaced.json()["persona_confirmation_revision"] == 5
    assert replaced.json()["persona_spec_hash"] == baseline["persona_spec_hash"]


def test_0009_columns_are_nullable_for_legacy_and_constraints_are_reversible(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'persona.sqlite3'}", tmp_path)
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
    with database.engine.connect() as connection:
        trigger_names = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name LIKE 'ck_agent_versions_persona_fields_%'"
                )
            )
        }
    assert trigger_names == {
        "ck_agent_versions_persona_fields_insert",
        "ck_agent_versions_persona_fields_update",
    }


def test_0009_rejects_partial_persona_rows_and_lossy_downgrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-populated.sqlite3'}"
    database = Database(database_url, tmp_path)
    database.upgrade_schema()
    with database.session() as session:
        seed_demo_data(session)
        now = datetime.now(UTC)
        agent = Agent(
            id="persona-migration-agent",
            group_id=GROUP_BOWEN_ID,
            name="Migration Agent",
            description="",
            metadata_revision=0,
            status="active",
            current_published_version_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(agent)
        session.flush()
        agent_md = _persona_md("Migration Agent")
        session.add(
            AgentVersion(
                id="persona-migration-version",
                agent_id=agent.id,
                version_seq=0,
                state="draft",
                revision=1,
                agent_md=agent_md,
                raw_agent_md_hash=raw_agent_md_hash(agent_md),
                avatar_config_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE agent_versions SET persona_spec_json='{}' "
                    "WHERE id='persona-migration-version'"
                )
            )
    compiled = compile_persona(_persona_md("Migration Agent"), expected_name="Migration Agent")
    assert compiled.compiled and compiled.canonical_json and compiled.persona_spec_hash
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id,agent_id,version_seq,state,revision,agent_md,raw_agent_md_hash,"
                    "persona_spec_json,avatar_config_json,created_at,updated_at) "
                    "VALUES ('persona-migration-partial','persona-migration-agent',1,'published',1,"
                    ":agent_md,:raw_hash,:spec,'{}',:now,:now)"
                ),
                {
                    "agent_md": _persona_md("Migration Agent"),
                    "raw_hash": compiled.source_agent_md_hash,
                    "spec": compiled.canonical_json,
                    "now": datetime.now(UTC),
                },
            )
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE agent_versions SET persona_spec_json=:spec, persona_spec_hash=:spec_hash, "
                "persona_compiler_version='persona_template_v1' "
                "WHERE id='persona-migration-version'"
            ),
            {"spec": compiled.canonical_json, "spec_hash": compiled.persona_spec_hash},
        )
        connection.execute(
            text(
                "UPDATE agent_versions SET persona_confirmation_revision=revision, "
                "student_confirmed_at=:now, persona_confirming_user_id='student-confirming' "
                "WHERE id='persona-migration-version'"
            ),
            {"now": datetime.now(UTC)},
        )
    with database.engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "UPDATE agent_versions SET agent_md=:agent_md "
                    "WHERE id='persona-migration-version'"
                ),
                {"agent_md": _persona_md("Migration Agent", role="Changed role")},
            )
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    with pytest.raises(RuntimeError, match="Cannot downgrade 0009"):
        command.downgrade(cfg, "0008_wave4_mutual_learning_rounds")
    assert "persona_spec_json" in {
        item["name"] for item in inspect(database.engine).get_columns("agent_versions")
    }


def test_0009_does_not_backfill_existing_legacy_agent_versions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'persona-legacy.sqlite3'}"
    database = Database(database_url, tmp_path)
    cfg = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "0008_wave4_mutual_learning_rounds")
    with database.session() as session:
        seed_demo_data(session)
        now = datetime.now(UTC)
        agent = Agent(
            id="legacy-persona-agent",
            group_id=GROUP_BOWEN_ID,
            name="Legacy Agent",
            description="",
            metadata_revision=0,
            status="active",
            current_published_version_id=None,
            created_at=now,
            updated_at=now,
        )
        session.add(agent)
        session.flush()
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO agent_versions "
                "(id,agent_id,version_seq,state,revision,agent_md,avatar_config_json,"
                "voice_profile_id,knowledge_snapshot_id,published_at,created_at,updated_at) "
                "VALUES ('legacy-persona-version','legacy-persona-agent',0,'published',1,"
                "'# Legacy Agent\n\nHistorical raw source.','{}',NULL,NULL,NULL,:now,:now)"
            ),
            {"now": now},
        )
    command.upgrade(cfg, "head")
    with database.session() as session:
        row = session.get(AgentVersion, "legacy-persona-version")
        assert row is not None
        assert row.agent_md == "# Legacy Agent\n\nHistorical raw source."
        assert row.raw_agent_md_hash is None
        assert row.persona_spec_json is None
        assert row.persona_spec_hash is None
        assert row.persona_compiler_version is None
        assert row.persona_confirmation_revision is None
        assert row.student_confirmed_at is None
        assert row.persona_confirming_user_id is None
