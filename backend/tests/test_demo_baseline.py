"""Deterministic local-Demo baseline and safe composition disclosure tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.config import Settings
from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
)
from app.main import create_app
from app.modules.avatars import DEFAULT_AVATAR_CONFIG, default_config_for
from app.modules.demo_baseline.service import (
    BASELINE_AGENT_ID,
    BASELINE_CHUNK_ID,
    BASELINE_FROZEN_RELATIVE_PATH,
    BASELINE_SNAPSHOT_ID,
    BASELINE_SNAPSHOT_RELATIVE_PATH,
    BASELINE_SOURCE_RELATIVE_PATH,
    BASELINE_SPECS,
    BASELINE_VERSION_ID,
    DemoBaselineConflict,
    baseline_is_usable,
    dirty_counts,
    ensure_demo_baseline,
)
from app.seed import GROUP_DEMO_ID
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from sqlalchemy import func, select


def _seeded_database(app_factory: Any) -> tuple[Any, Any, Any]:
    app, database, settings = app_factory()
    return app, database, settings


def test_empty_runtime_baseline_is_idempotent_and_usable(
    app_factory: Any,
) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            assert baseline_is_usable(db)
            first_counts = tuple(
                int(db.scalar(select(func.count(model.id))) or 0)
                for model in (Agent, AgentVersion, KnowledgeSnapshot, KnowledgeChunk)
            )
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            second_counts = tuple(
                int(db.scalar(select(func.count(model.id))) or 0)
                for model in (Agent, AgentVersion, KnowledgeSnapshot, KnowledgeChunk)
            )
            assert second_counts == first_counts
            assert (
                db.get(Agent, BASELINE_AGENT_ID).current_published_version_id == BASELINE_VERSION_ID
            )
            assert (
                db.get(AgentVersion, BASELINE_VERSION_ID).knowledge_snapshot_id
                == BASELINE_SNAPSHOT_ID
            )
            assert db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID) is not None
            assert db.get(KnowledgeChunk, BASELINE_CHUNK_ID) is not None
        for relative_path in (
            BASELINE_SOURCE_RELATIVE_PATH,
            BASELINE_SNAPSHOT_RELATIVE_PATH,
            BASELINE_FROZEN_RELATIVE_PATH,
        ):
            path = Path(settings.resolved_data_root) / relative_path
            assert path.is_file()
            assert path.stat().st_mode & 0o777 == 0o600


def test_baselines_seed_the_requested_character_models(app_factory: Any) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            assert {
                spec.agent_name: json.loads(
                    db.get(AgentVersion, spec.version_id).avatar_config_json
                )["template_id"]
                for spec in BASELINE_SPECS
            } == {
                "Socrates": "maya-warm-scholar",
                "Plato": "maya-civic-observer",
                "Laozi": "maya-warm-scholar",
            }


def test_baseline_reconciles_only_exact_old_avatar_defaults(app_factory: Any) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            for spec in BASELINE_SPECS[:2]:
                version = db.get(AgentVersion, spec.version_id)
                assert version is not None
                version.avatar_config_json = DEFAULT_AVATAR_CONFIG.model_dump_json()
            laozi = db.get(AgentVersion, BASELINE_SPECS[2].version_id)
            assert laozi is not None
            manual_config = default_config_for("maya-civic-observer").model_dump_json()
            laozi.avatar_config_json = manual_config
            db.flush()

        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            assert (
                json.loads(db.get(AgentVersion, BASELINE_SPECS[0].version_id).avatar_config_json)[
                    "template_id"
                ]
                == "maya-warm-scholar"
            )
            assert (
                json.loads(db.get(AgentVersion, BASELINE_SPECS[1].version_id).avatar_config_json)[
                    "template_id"
                ]
                == "maya-civic-observer"
            )
            assert (
                db.get(AgentVersion, BASELINE_SPECS[2].version_id).avatar_config_json
                == manual_config
            )


def test_baseline_conflict_fails_closed_without_rewriting_reserved_rows(
    app_factory: Any,
) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
        with database.session() as db:
            agent = db.get(Agent, BASELINE_AGENT_ID)
            assert agent is not None
            agent.name = "Changed baseline"
            version = db.get(AgentVersion, BASELINE_VERSION_ID)
            assert version is not None
            version.avatar_config_json = DEFAULT_AVATAR_CONFIG.model_dump_json()
            with pytest.raises(DemoBaselineConflict):
                ensure_demo_baseline(db, settings.resolved_data_root)
            assert version.avatar_config_json == DEFAULT_AVATAR_CONFIG.model_dump_json()
            db.rollback()
        with database.session() as db:
            assert db.get(Agent, BASELINE_AGENT_ID).name == "Socrates"


def test_demo_endpoints_disclose_modes_without_provider_secrets(
    app_factory: Any,
) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app) as client:
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
        composition = client.get("/api/v1/demo/composition")
        assert composition.status_code == 200, composition.text
        body = composition.json()
        assert [(item["key"], item["mode"]) for item in body["components"]] == [
            ("embedding", "mock"),
            ("llm", "mock"),
            ("tts", "mock"),
            ("voice", "mock"),
            ("report", "mock"),
        ]
        # The boundary is the point of this assertion: a component may say
        # what it is and whether its policy was reviewed, and nothing else.
        assert all(
            set(item) <= {"key", "label", "mode", "policy_unreviewed"}
            for item in body["components"]
        )

        baseline = client.get("/api/v1/demo/baseline")
        assert baseline.status_code == 200, baseline.text
        baseline_body = baseline.json()
        assert baseline_body["system_baseline"] is True
        assert baseline_body["immutable"] is True
        assert baseline_body["usable"] is True


def test_dirty_counts_exclude_only_system_baseline_agent(
    app_factory: Any,
) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            assert dirty_counts(db) == (0, 0, 0)
            now = datetime.now(UTC)
            db.add(
                Agent(
                    id="8e3aa61e-d8cb-4b14-9e3b-75463a9b35cd",
                    group_id=GROUP_DEMO_ID,
                    name="Student Agent",
                    description="A user-owned draft.",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            assert dirty_counts(db) == (1, 0, 0)


@pytest.mark.parametrize("demo_mode", [True, False])
def test_non_test_startup_builds_the_philosophers_only_for_the_demo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    demo_mode: bool,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("MAYA_TESTING", raising=False)
    # Demo sign-in needs an identity catalog; one teacher is enough here.
    credentials = tmp_path / "demo_users.yaml"
    credentials.write_text(
        yaml.safe_dump(
            {
                "users": [
                    {
                        "user_id": "08b9de2d-bb75-5c71-a64b-231b48f9eb25",
                        "username": "maya",
                        "password_hash": PasswordHash.recommended().hash("demo-password"),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    credentials.chmod(0o600)
    settings = Settings(
        maya_env="development",
        session_secret="s" * 32,
        demo_mode=demo_mode,
        allow_legacy_demo_users=True,
        demo_users_file=credentials,
        database_url=f"sqlite:///{tmp_path / 'maya.sqlite3'}",
        data_root=tmp_path,
        demo_accounts_file=tmp_path / "missing-accounts.private.md",
        llm_provider="mock",
        embedding_provider="mock",
        tts_provider="mock",
        voice_provider="mock",
    )
    database = Database(settings.database_url, settings.data_root)
    app = create_app(settings, database)
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        with database.session() as db:
            # A classroom starts without Laozi, Plato and Socrates.
            assert baseline_is_usable(db) is demo_mode
            assert (db.get(Agent, BASELINE_AGENT_ID) is not None) is demo_mode


def test_demo_startup_revives_philosophers_a_data_reset_soft_deleted(
    app_factory: Any,
) -> None:
    app, database, settings = _seeded_database(app_factory)
    with TestClient(app):
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
        with database.session() as db:
            for spec in BASELINE_SPECS:
                agent = db.get(Agent, spec.agent_id)
                assert agent is not None
                agent.deleted_at = datetime.now(UTC)
                agent.status = "archived"
                document = db.get(KnowledgeDocument, spec.document_id)
                assert document is not None
                document.workspace_state = "hidden"
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            assert baseline_is_usable(db)
            for spec in BASELINE_SPECS:
                agent = db.get(Agent, spec.agent_id)
                assert agent is not None and agent.deleted_at is None
                assert agent.status == "active"
                document = db.get(KnowledgeDocument, spec.document_id)
                assert document is not None and document.workspace_state == "active"


DEMO_ONLY_ROUTES = (
    ("GET", "/api/v1/demo/composition"),
    ("GET", "/api/v1/demo/baseline"),
    ("GET", "/api/v1/demo/status"),
    ("POST", "/api/v1/demo/acceptance-runs"),
    ("GET", "/api/v1/demo/acceptance-runs/00000000-0000-4000-8000-000000000000"),
    ("POST", "/api/v1/demo/acceptance-runs/00000000-0000-4000-8000-000000000000/debate"),
    ("POST", "/api/v1/demo/acceptance-runs/00000000-0000-4000-8000-000000000000/report"),
    ("POST", "/api/v1/demo/acceptance-runs/00000000-0000-4000-8000-000000000000/calls"),
    ("GET", "/api/v1/demo/acceptance-runs/00000000-0000-4000-8000-000000000000/summary"),
)


def _registered_paths(app: Any) -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")} | {
        str(path) for path in app.openapi().get("paths", {})
    }


def test_demo_routes_are_not_registered_without_demo_mode(app_factory: Any) -> None:
    app, _database, _settings = app_factory(demo_mode=False)
    with TestClient(app) as client:
        for method, path in DEMO_ONLY_ROUTES:
            response = client.request(method, path, json={})
            assert response.status_code == 404, (method, path, response.text)
        # Real routes still answer, so the 404 above is not a dead app.
        assert client.get("/health/live").status_code == 200
    assert not any("/demo/" in path for path in _registered_paths(app))


def test_demo_routes_are_registered_in_demo_mode(app_factory: Any) -> None:
    app, database, settings = app_factory(demo_mode=True)
    with TestClient(app) as client:
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
        assert client.get("/api/v1/demo/composition").status_code == 200
        assert client.get("/api/v1/demo/baseline").status_code == 200
        assert client.get("/api/v1/demo/status").status_code == 200
        # Acceptance runs stay teacher-only; unauthenticated is refused, not 404.
        assert client.post("/api/v1/demo/acceptance-runs", json={}).status_code != 404
