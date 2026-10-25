"""SQL statements per request on the course pages, at a fixed data size.

Production 2026-10-26 (b5e140e9, maya.request_timing): published-agents ran
554 statements per request, chat-agents 343, agents/{id} 249 — one or more
queries per Agent or version. These pages now read in batches; this test
pins each one under a ceiling with 20 published Agents, so a new per-row
query fails here instead of in production.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_mayaform_team_conversations import _make_agent_version
from tests.test_mayaform_teams import (
    BOWEN_ID,
    COURSE_ID,
    GROUP_ID,
    MAYA_ID,
    _attach_personal_snapshot,
)

AGENTS = 20
VERSIONS = 3
DOCUMENTS = 40


def _rich_group_agent(database: Any) -> tuple[str, str]:
    """A student's public group Agent: VERSIONS versions, each with a snapshot
    of the same DOCUMENTS public group documents, all enabled."""

    from app.core.models import (
        Agent,
        AgentVersion,
        AgentVersionDocument,
        KnowledgeDocument,
        KnowledgeSnapshot,
        SnapshotDocument,
        StoredFile,
    )

    now = datetime.now(UTC)
    agent_id, first_version = _make_agent_version(
        database, owner_id=BOWEN_ID, name="Rich agent", visibility="public", group_id=GROUP_ID
    )
    with database.session() as db:
        documents = []
        for index in range(DOCUMENTS):
            file_id = str(uuid4())
            db.add(
                StoredFile(
                    id=file_id,
                    kind="markdown",
                    relative_path=f"groups/{GROUP_ID}/knowledge/{file_id}.md",
                    sha256="a" * 64,
                    size_bytes=10,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            document = KnowledgeDocument(
                id=str(uuid4()),
                group_id=GROUP_ID,
                owner_user_id=BOWEN_ID,
                course_id=COURSE_ID,
                ownership_scope="group",
                visibility="public",
                authorization_epoch=0,
                source_filename=f"source-{index}.md",
                stored_file_id=file_id,
                char_count=10,
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash="a" * 64,
                created_at=now,
                updated_at=now,
            )
            db.add(document)
            documents.append(document)
        db.flush()
        current = db.get(AgentVersion, first_version)
        version_ids = [first_version]
        for seq in range(2, VERSIONS + 1):
            version = AgentVersion(
                **{
                    column.key: getattr(current, column.key)
                    for column in AgentVersion.__table__.columns
                    if column.key not in {"id", "version_seq", "state"}
                },
                id=str(uuid4()),
                version_seq=seq,
                state="published",
            )
            db.add(version)
            version_ids.append(version.id)
        db.flush()
        for version_id in version_ids[:-1]:
            db.get(AgentVersion, version_id).state = "superseded"
        db.get(Agent, agent_id).current_published_version_id = version_ids[-1]
        for version_id in version_ids:
            snapshot_file = str(uuid4())
            db.add(
                StoredFile(
                    id=snapshot_file,
                    kind="snapshot_rag",
                    relative_path=f"snapshots/{snapshot_file}/rag.md",
                    sha256="b" * 64,
                    size_bytes=10,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            snapshot = KnowledgeSnapshot(
                id=str(uuid4()),
                agent_version_id=version_id,
                stored_file_id=snapshot_file,
                content_hash="b" * 64,
                total_char_count=10 * DOCUMENTS,
                embedding_key="mock-sha256-v1",
                chunking_json="{}",
                created_at=now,
            )
            db.add(snapshot)
            db.flush()
            for order, document in enumerate(documents):
                db.add(
                    AgentVersionDocument(
                        agent_version_id=version_id,
                        document_id=document.id,
                        enabled=True,
                        order_index=order,
                    )
                )
                db.add(
                    SnapshotDocument(
                        id=str(uuid4()),
                        snapshot_id=snapshot.id,
                        document_id=document.id,
                        stored_file_id=document.stored_file_id,
                        source_filename=document.source_filename,
                        char_count=10,
                        order_index=order,
                        source_authorization_epoch=0,
                    )
                )
            db.get(AgentVersion, version_id).knowledge_snapshot_id = snapshot.id
        db.commit()
        snapshot_id = db.get(AgentVersion, version_ids[-1]).knowledge_snapshot_id
    return agent_id, snapshot_id


def _timed(client: TestClient, caplog: pytest.LogCaptureFixture, url: str) -> dict[str, Any]:
    client.get(url)  # warm: the first call of a route pays one-off import costs
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="maya.request_timing"):
        response = client.get(url)
    assert response.status_code == 200, response.text
    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "maya.request_timing"
    ]
    return lines[-1] | {"body": response.json()}


@pytest.fixture
def course(client: TestClient) -> dict[str, Any]:
    database = client.app.state.database
    teacher_agents: list[tuple[str, str]] = []
    for index in range(AGENTS // 2):
        agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Teacher agent {index}", visibility="public"
        )
        _attach_personal_snapshot(database, version_id)
        teacher_agents.append((agent_id, version_id))
    for index in range(AGENTS - AGENTS // 2):
        _make_agent_version(
            database,
            owner_id=BOWEN_ID,
            name=f"Student agent {index}",
            visibility="public",
            group_id=GROUP_ID,
        )
    agent_id, snapshot_id = _rich_group_agent(database)
    return {"agent_id": agent_id, "snapshot_id": snapshot_id}


CEILINGS = {
    "published_agents": 15,
    "chat_agents": 15,
    "agent": 20,
    "agent_versions": 20,
    "snapshot": 20,
    "brainform_knowledge": 10,
    "assessment_attempts": 10,
}


def test_course_pages_stay_under_their_query_ceilings(
    client: TestClient, course: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    login(client, "maya")
    urls = {
        "published_agents": f"/api/v1/courses/{COURSE_ID}/published-agents",
        "chat_agents": f"/api/v1/courses/{COURSE_ID}/chat-agents",
        "agent": f"/api/v1/agents/{course['agent_id']}",
        "agent_versions": f"/api/v1/agents/{course['agent_id']}/versions",
        "snapshot": f"/api/v1/knowledge-snapshots/{course['snapshot_id']}",
        "brainform_knowledge": f"/api/v1/courses/{COURSE_ID}/brainform/knowledge",
        "assessment_attempts": f"/api/v1/learning/courses/{COURSE_ID}/assessment-attempts",
    }
    measured = {name: _timed(client, caplog, url) for name, url in urls.items()}
    report = {
        name: {"db_queries": line["db_queries"], "ms": line["ms"], "db_ms": line["db_ms"]}
        for name, line in measured.items()
    }
    out = os.environ.get("MAYA_QUERY_COUNT_REPORT")
    if out:
        with open(out, "w") as handle:
            json.dump(report, handle, indent=1)
    assert len(measured["published_agents"]["body"]) >= AGENTS
    for name, ceiling in CEILINGS.items():
        assert report[name]["db_queries"] <= ceiling, (name, report[name])
