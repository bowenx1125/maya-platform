"""Deterministic local-Demo baseline and safe composition disclosure tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.core.config import Settings
from app.core.db import Database
from app.core.models import Agent, AgentVersion, KnowledgeChunk, KnowledgeSnapshot
from app.main import create_app
from app.modules.demo_baseline.service import (
    BASELINE_AGENT_ID,
    BASELINE_CHUNK_ID,
    BASELINE_FROZEN_RELATIVE_PATH,
    BASELINE_SNAPSHOT_ID,
    BASELINE_SNAPSHOT_RELATIVE_PATH,
    BASELINE_SOURCE_RELATIVE_PATH,
    BASELINE_VERSION_ID,
    DemoBaselineConflict,
    baseline_is_usable,
    dirty_counts,
    ensure_demo_baseline,
)
from app.seed import GROUP_DEMO_ID
from fastapi.testclient import TestClient
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
            with pytest.raises(DemoBaselineConflict):
                ensure_demo_baseline(db, settings.resolved_data_root)
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


def test_non_test_startup_rebuilds_baseline_in_an_empty_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("MAYA_TESTING", raising=False)
    settings = Settings(
        maya_env="development",
        session_secret="s" * 32,
        demo_mode=False,
        database_url=f"sqlite:///{tmp_path / 'maya.sqlite3'}",
        data_root=tmp_path,
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
            assert baseline_is_usable(db)
            assert db.get(Agent, BASELINE_AGENT_ID) is not None
