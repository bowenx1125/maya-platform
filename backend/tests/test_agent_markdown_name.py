"""Renaming an Agent is its own action; AGENT.md never renames it."""

from uuid import uuid4

from app.core.models import Agent, AgentVersion
from app.modules.debates.models import DebateParticipant
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login
from tests.test_mayaform_teams import BOWEN_ID
from tests.test_wave1_agents_knowledge import _make_agent
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent


def test_agent_md_heading_is_only_content_now(client):
    """Owner 2026-11-08: renaming happens on the Name card; AGENT.md's first
    heading no longer renames the Agent, on save or upload."""
    _, csrf = login(client, "bowen")
    agent, version_id = _make_agent(client, csrf)
    url = f"/api/v1/agent-versions/{version_id}"
    saved = client.patch(
        url, headers=_headers(csrf), json={"expected_revision": 0, "agent_md": "# 新名字\nBody"}
    )
    assert saved.status_code == 200, saved.text
    detail = client.get(f"/api/v1/agents/{agent['id']}").json()
    assert detail["name"] == agent["name"]
    assert detail["metadata_revision"] == agent["metadata_revision"]
    uploaded = client.post(
        f"{url}/agent-md/upload",
        headers=_headers(csrf),
        data={"expected_revision": "1"},
        files={"file": ("AGENT.md", b"# Uploaded name\nBody", "text/markdown")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.get(f"/api/v1/agents/{agent['id']}").json()["name"] == agent["name"]


def test_renaming_next_draft_keeps_published_source_and_debate_participant_name(app_factory):
    app, database, _ = app_factory()
    try:
        with TestClient(app) as client:
            agents = [
                _insert_published_agent(
                    database,
                    group_id=GROUP_DEMO_ID,
                    name=f"Original {index}",
                    evidence="Shared classroom evidence.",
                )
                for index in range(2)
            ]
            # Only the publishing account edits an Agent; bowen renames below.
            with database.session() as db:
                edited = db.get(Agent, agents[0])
                assert edited is not None
                edited.owner_user_id = BOWEN_ID
            _, csrf = login(client)
            created = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
                json={
                    "topic": "How should communities share resources?",
                    "participants": [
                        {"agent_id": agent_id, "stance_mode": "open"} for agent_id in agents
                    ],
                    "round_count": 4,
                    "round_unit_caps": [200, 200, 200, 200],
                },
            )
            assert created.status_code == 201, created.text
            with database.session() as db:
                participant = db.scalar(
                    select(DebateParticipant).where(
                        DebateParticipant.debate_id == created.json()["id"],
                        DebateParticipant.agent_id == agents[0],
                    )
                )
                participant_id = participant.id
                published_id = participant.agent_version_id
                published_source = db.get(AgentVersion, published_id).agent_md
            _, csrf = login(client, "bowen")
            draft = client.post(
                f"/api/v1/agents/{agents[0]}/versions",
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
            )
            assert draft.status_code == 201, draft.text
            metadata = client.get(f"/api/v1/agents/{agents[0]}").json()["metadata_revision"]
            renamed = client.patch(
                f"/api/v1/agents/{agents[0]}",
                headers=_headers(csrf),
                json={"expected_metadata_revision": metadata, "name": "Current name"},
            )
            assert renamed.status_code == 200, renamed.text
            assert client.get(f"/api/v1/agents/{agents[0]}").json()["name"] == "Current name"
            with database.session() as db:
                assert db.get(DebateParticipant, participant_id).agent_name == "Original 0"
                assert db.get(AgentVersion, published_id).agent_md == published_source
    finally:
        database.dispose()
