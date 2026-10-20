"""Deleting a RAG file or Voice auto-publishes the Agents that use it."""

from __future__ import annotations

from typing import Any

from app.core.models import Agent, AgentVersion, AgentVersionDocument
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _h(csrf: str, key: str | None = None) -> dict[str, str]:
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def _upload(client: TestClient, csrf: str, name: str, body: bytes, key: str) -> str:
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_h(csrf, key),
        data={"visibility": "public"},
        files={"file": (name, body, "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    return str(uploaded.json()["document"]["id"])


def _agent_with_docs(client: TestClient, csrf: str, name: str, doc_ids: list[str]) -> str:
    key = name.lower().replace(" ", "-")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_h(csrf, f"cascade-{key}-create-0001"),
        json={"name": name, "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_h(csrf),
        json={"expected_revision": 0, "agent_md": f"# {name}\n\nCascade probe."},
    )
    assert saved.status_code == 200, saved.text
    linked = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_h(csrf),
        json={"expected_revision": 1, "document_ids": doc_ids},
    )
    assert linked.status_code == 200, linked.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_h(csrf, f"cascade-{key}-publish-001"),
        json={"expected_revision": linked.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    return str(agent_id)


def _current(database: Any, agent_id: str) -> tuple[AgentVersion, list[str]]:
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None and agent.current_published_version_id
        version = db.get(AgentVersion, agent.current_published_version_id)
        assert version is not None
        docs = list(
            db.scalars(
                select(AgentVersionDocument.document_id).where(
                    AgentVersionDocument.agent_version_id == version.id
                )
            )
        )
        db.expunge(version)
        return version, docs


def test_deleting_a_rag_file_lists_and_auto_publishes_affected_agents(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _owner, csrf = login(client, "bowen")
    keep = _upload(client, csrf, "keep.md", b"# Keep\n\nKEEP_CANARY", "cascade-up-keep-0001")
    gone = _upload(client, csrf, "gone.md", b"# Gone\n\nGONE_CANARY", "cascade-up-gone-0001")
    two_docs = _agent_with_docs(client, csrf, "Cascade Two", [keep, gone])
    only_gone = _agent_with_docs(client, csrf, "Cascade Only", [gone])
    untouched = _agent_with_docs(client, csrf, "Cascade Free", [keep])
    before_two, _ = _current(database, two_docs)
    before_free, _ = _current(database, untouched)

    listed = client.get(f"/api/v1/knowledge-documents/{gone}/affected-agents")
    assert listed.status_code == 200, listed.text
    assert sorted(row["name"] for row in listed.json()) == ["Cascade Only", "Cascade Two"]

    hidden = client.post(
        f"/api/v1/knowledge-documents/{gone}/hide", headers=_h(csrf, "cascade-hide-gone-001")
    )
    assert hidden.status_code == 200, hidden.text

    after_two, docs_two = _current(database, two_docs)
    assert after_two.id != before_two.id
    assert after_two.version_seq == before_two.version_seq + 1
    assert docs_two == [keep]
    assert after_two.knowledge_snapshot_id is not None
    after_only, docs_only = _current(database, only_gone)
    assert docs_only == []
    assert after_only.knowledge_snapshot_id is None  # falls back to a no-RAG Agent
    after_free, _ = _current(database, untouched)
    assert after_free.id == before_free.id
    with database.session() as db:
        old = db.get(AgentVersion, before_two.id)
        assert old is not None and old.state == "superseded"  # Debates keep it

    # The bumped Agent can still start a chat.
    chat = client.post(
        "/api/v1/conversations", headers=_h(csrf), json={"version_id": after_only.id}
    )
    assert chat.status_code == 200, chat.text


def test_bump_clears_a_deleted_voice_and_keeps_the_agent_usable(
    client: TestClient, app_bundle: Any
) -> None:
    from app.modules.agents.cascade import affected_agents, bump_agent

    _app, database, settings = app_bundle
    _owner, csrf = login(client, "bowen")
    agent_id = _agent_with_docs(client, csrf, "Cascade Voice", [])
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        version = db.get(AgentVersion, agent.current_published_version_id)
        assert version is not None
        version.voice_profile_id = "voice-gone"
        db.commit()
        assert [a.agent_id for a in affected_agents(db, voice_profile_ids=["voice-gone"])] == [
            agent_id
        ]
        new_id = bump_agent(db, settings, agent_id, drop_voice_profile_ids=["voice-gone"])
        assert new_id is not None
    after, _ = _current(database, agent_id)
    assert after.id == new_id and after.voice_profile_id is None
    chat = client.post("/api/v1/conversations", headers=_h(csrf), json={"version_id": new_id})
    assert chat.status_code == 200, chat.text


def test_bump_keeps_an_owner_draft_unpublished(client: TestClient, app_bundle: Any) -> None:
    from app.modules.agents.cascade import bump_agent

    _app, database, settings = app_bundle
    _owner, csrf = login(client, "bowen")
    agent_id = _agent_with_docs(client, csrf, "Cascade Draft", [])
    nxt = client.post(
        f"/api/v1/agents/{agent_id}/versions", headers=_h(csrf, "cascade-draft-next-0001")
    )
    assert nxt.status_code == 201, nxt.text
    draft_id = nxt.json()["id"]
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        current = db.get(AgentVersion, agent.current_published_version_id)
        assert current is not None
        current.voice_profile_id = "voice-x"
        db.commit()
        new_id = bump_agent(db, settings, agent_id, drop_voice_profile_ids=["voice-x"])
        assert new_id is not None
        draft = db.get(AgentVersion, draft_id)  # same row, back in the draft slot
        published = db.get(AgentVersion, new_id)
        assert published is not None and published.state == "published"
        assert draft is not None and draft.version_seq == published.version_seq + 1
        assert draft.voice_profile_id is None


def test_editing_a_rag_file_publishes_a_new_version_with_the_new_content(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _owner, csrf = login(client, "bowen")
    doc = _upload(client, csrf, "edit.md", b"# Edit\n\nOLD_CANARY", "cascade-up-edit-0001")
    agent_id = _agent_with_docs(client, csrf, "Cascade Edit", [doc])
    before, _ = _current(database, agent_id)
    current = client.get(f"/api/v1/knowledge-documents/{doc}").json()
    replaced = client.post(
        f"/api/v1/knowledge-documents/{doc}/replace",
        headers=_h(csrf, "cascade-replace-edit-001"),
        data={
            "expected_content_hash": current["content_hash"],
            "expected_index_revision": str(current["index_revision"]),
        },
        files={"file": ("edit.md", b"# Edit\n\nNEW_CANARY", "text/markdown")},
    )
    assert replaced.status_code == 201, replaced.text
    after, docs = _current(database, agent_id)
    assert after.version_seq == before.version_seq + 1
    assert docs == [doc]
    assert after.knowledge_snapshot_id not in {None, before.knowledge_snapshot_id}
    from app.modules.agents.cascade import stale_agents

    with database.session() as db:
        assert stale_agents(db) == []  # nothing left for the restart sweep


def test_sweep_recovers_a_lost_auto_publish_and_is_idempotent(
    client: TestClient, app_bundle: Any
) -> None:
    from app.core.models import KnowledgeDocument
    from app.modules.agents.cascade import stale_agents, sweep_stale_agents

    _app, database, settings = app_bundle
    _owner, csrf = login(client, "bowen")
    keep = _upload(client, csrf, "sw-keep.md", b"# K\n\nKEEP", "cascade-up-swkeep-01")
    lost = _upload(client, csrf, "sw-lost.md", b"# L\n\nLOST", "cascade-up-swlost-01")
    agent_id = _agent_with_docs(client, csrf, "Cascade Sweep", [keep, lost])
    with database.session() as db:  # simulate a delete whose job died with the backend
        document = db.get(KnowledgeDocument, lost)
        assert document is not None
        document.workspace_state = "hidden"
        db.commit()
        assert [row[0] for row in stale_agents(db)] == [agent_id]
    assert sweep_stale_agents(database, settings) == 1
    _after, docs = _current(database, agent_id)
    assert docs == [keep]
    assert sweep_stale_agents(database, settings) == 0
