from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.models import Agent, AgentVersion, KnowledgeChunk, KnowledgeSnapshot, SnapshotDocument
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge_sets.models import (
    AgentKnowledgeSet,
    KnowledgeAsset,
    KnowledgeAssetVersion,
)
from app.modules.knowledge_sets.schemas import NoteContent
from app.modules.workspace.chat_team_context import load_member_context
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
)
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_mayaform_team_conversations import COURSE_ID, MAYA_ID, _make_agent_version
from tests.test_mayaform_teams import _attach_personal_snapshot, _headers, _team_payload


def _add_note(db: Any, set_id: str, body: str) -> None:
    timestamp = datetime.now(UTC)
    asset_id = str(uuid4())
    content = NoteContent(kind="note", title=body, body=body).model_dump_json()
    db.add(
        KnowledgeAsset(
            id=asset_id,
            knowledge_set_id=set_id,
            kind="note",
            generation_lineage_key=None,
            current_version_seq=1,
            created_by_user_id=MAYA_ID,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    db.add(
        KnowledgeAssetVersion(
            id=str(uuid4()),
            asset_id=asset_id,
            version_seq=1,
            content_json=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            source_dependency_hash=None,
            dependency_authorization_epoch=None,
            set_authorization_epoch=0,
            origin="manual",
            created_by_user_id=MAYA_ID,
            generator_agent_version_id=None,
            generation_job_id=None,
            created_at=timestamp,
        )
    )


def test_team_runtime_context_combines_each_member_own_and_shared_evidence(
    client: TestClient, database: Any
) -> None:
    _, teacher_csrf = login(client, "maya")
    versions = [
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Context member {index}", visibility="public"
        )[1]
        for index in range(2)
    ]
    _attach_personal_snapshot(database, versions[0])
    set_ids: list[str] = []
    for label in ("own", "shared"):
        response = client.post(
            f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
            headers=_headers(teacher_csrf, f"context-{label}-{uuid4()}"),
            json={"display_name": f"Team {label} context"},
        )
        assert response.status_code == 201, response.text
        set_ids.append(response.json()["id"])
    with database.session() as db:
        first = db.get(AgentVersion, versions[0])
        assert first is not None
        db.add(
            AgentKnowledgeSet(
                agent_id=first.agent_id,
                knowledge_set_id=set_ids[0],
                order_index=0,
                created_by_user_id=MAYA_ID,
                created_at=datetime.now(UTC),
            )
        )
        for label, set_id in zip(("own-only-note", "shared-note"), set_ids, strict=True):
            _add_note(db, set_id, label)
        snapshot = db.get(KnowledgeSnapshot, first.knowledge_snapshot_id)
        assert snapshot is not None
        snapshot_document = db.scalar(
            select(SnapshotDocument).where(SnapshotDocument.snapshot_id == snapshot.id)
        )
        assert snapshot_document is not None
        db.add(
            KnowledgeChunk(
                id=str(uuid4()),
                snapshot_id=snapshot.id,
                snapshot_document_id=snapshot_document.id,
                document_id=snapshot_document.document_id,
                chunk_index=0,
                chunk_text="K3 private source fence fixture",
                start_offset=0,
                end_offset=31,
                embedding_blob=mock_embedding("K3 private source fence fixture"),
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_key=EMBEDDING_KEY,
            )
        )
    _, teacher_csrf = login(client, "maya")
    team_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"team-context-{uuid4()}"),
        json={
            **_team_payload(versions, visibility="public"),
            "shared_knowledge_set_ids": [set_ids[1]],
        },
    )
    assert team_response.status_code == 201, team_response.text
    _, student_csrf = login(client, "bowen")
    session = client.post(
        "/api/v1/conversations",
        headers=_headers(student_csrf),
        json={
            "entry": {"kind": "maya_team", "team_id": team_response.json()["id"]},
            "chat_visibility": "private",
        },
    )
    assert session.status_code == 200, session.text
    conversation_id = session.json()["id"]
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        participants = db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation_id)
            .order_by(ConversationParticipant.position)
        ).all()
        assert row is not None and len(participants) == 2
        first_context = load_member_context(db, row, participants[0], "K3 private source fence")
        second_context = load_member_context(db, row, participants[1], "K3 private source fence")
        assert "own-only-note" in first_context.knowledge_json
        assert "own-only-note" not in second_context.knowledge_json
        assert "shared-note" in first_context.knowledge_json
        assert "shared-note" in second_context.knowledge_json
        assert "K3 private source fence fixture" in first_context.knowledge_json
        assert "K3 private source fence fixture" not in second_context.knowledge_json
        assert "PRIVATE" not in json.dumps(
            json.loads(second_context.knowledge_json), ensure_ascii=False
        )


def test_team_runtime_uses_latest_safe_canonical_markdown_for_frozen_binding(
    client: TestClient, database: Any
) -> None:
    _, teacher_csrf = login(client, "maya")
    versions = [
        _make_agent_version(
            database, owner_id=MAYA_ID, name=f"Canonical member {index}", visibility="public"
        )[1]
        for index in range(2)
    ]
    _, owner_csrf = login(client, "maya")
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(owner_csrf, f"team-current-knowledge-{uuid4()}"),
        json={"display_name": "Student-safe shared Knowledge"},
    )
    assert created_set.status_code == 201, created_set.text
    set_id = created_set.json()["id"]
    assert client.get(f"/api/v1/knowledge-sets/{set_id}").status_code == 200
    with database.session() as db:
        first_version = db.get(AgentVersion, versions[0])
        assert first_version is not None
        first_agent_id = first_version.agent_id
        first_agent = db.get(Agent, first_agent_id)
        assert first_agent is not None
        first_agent_revision = first_agent.metadata_revision
    binding = client.put(
        f"/api/v1/agents/{first_agent_id}/knowledge-sets",
        headers=_headers(owner_csrf, f"team-current-knowledge-binding-{uuid4()}"),
        json={
            "expected_agent_metadata_revision": first_agent_revision,
            "set_ids": [set_id],
        },
    )
    assert binding.status_code == 200, binding.text

    markdown_v1 = (
        "# Shared study\n\n## Questions\n\n### Question 1\n\n"
        "TEAM_NOTE_VERSION_ONE\n\n#### Reference answer\n\n"
        "TEAM_REFERENCE_SECRET\n\n#### Rubric\n\n"
        "- **Understanding** (2): TEAM_RUBRIC_SECRET\nTotal: 2 points\n"
    )
    first_save = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(owner_csrf, f"team-current-knowledge-v1-{uuid4()}"),
        json={"expected_version_seq": 0, "markdown": markdown_v1},
    )
    assert first_save.status_code == 200, first_save.text

    _, teacher_csrf = login(client, "maya")
    team_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"team-current-knowledge-team-{uuid4()}"),
        json={
            **_team_payload(versions, visibility="public"),
            "shared_knowledge_set_ids": [set_id],
        },
    )
    assert team_response.status_code == 201, team_response.text
    _, student_csrf = login(client, "kaikai")
    session = client.post(
        "/api/v1/conversations",
        headers=_headers(student_csrf, f"team-current-knowledge-chat-{uuid4()}"),
        json={
            "entry": {"kind": "maya_team", "team_id": team_response.json()["id"]},
            "chat_visibility": "private",
        },
    )
    assert session.status_code == 200, session.text

    markdown_v2 = markdown_v1.replace("TEAM_NOTE_VERSION_ONE", "TEAM_NOTE_VERSION_TWO")
    _, owner_csrf = login(client, "maya")
    second_save = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(owner_csrf, f"team-current-knowledge-v2-{uuid4()}"),
        json={"expected_version_seq": 1, "markdown": markdown_v2},
    )
    assert second_save.status_code == 200, second_save.text

    with database.session() as db:
        row = db.get(Conversation, session.json()["id"])
        participants = db.scalars(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == session.json()["id"])
            .order_by(ConversationParticipant.position)
        ).all()
        assert row is not None and len(participants) == 2
        context = load_member_context(db, row, participants[0], "Use the current study note.")
        knowledge = json.loads(context.knowledge_json)
        canonical = next(
            item for item in knowledge["knowledge_sets"] if item["canonical_set_id"] == set_id
        )
        assert canonical["markdown"] is not None
        assert "TEAM_NOTE_VERSION_TWO" in canonical["markdown"]
        assert "TEAM_NOTE_VERSION_ONE" not in canonical["markdown"]
        assert "TEAM_REFERENCE_SECRET" not in context.knowledge_json
        assert "TEAM_RUBRIC_SECRET" not in context.knowledge_json
