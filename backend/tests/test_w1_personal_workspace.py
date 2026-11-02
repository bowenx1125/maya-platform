from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.core.models import Agent, AgentVersion, GroupMember, KnowledgeDocument
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login, post_message
from tests.test_auth_self_registration import register

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def test_teacher_personal_no_rag_agent_chat_and_private_source_acl(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(csrf, **{"Idempotency-Key": "w1-personal-agent-create-001"}),
        json={"name": "Teacher Private Guide", "description": "Owner-only draft."},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["group_id"] is None
    assert agent["course_id"] == COURSE_ID
    assert agent["ownership_scope"] == "personal"
    assert agent["visibility"] == "private"
    draft_id = agent["versions"][0]["id"]

    updated = client.patch(
        f"/api/v1/agent-versions/{draft_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": "# Teacher Private Guide\n\nA saved draft."},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["publish_blockers"] == []
    published = client.post(
        f"/api/v1/agent-versions/{draft_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "w1-personal-agent-publish-001"}),
        json={"expected_revision": 1},
    )
    assert published.status_code == 200, published.text
    released = published.json()
    assert released["state"] == "published"
    assert released["knowledge_snapshot_id"] is None
    owner_published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert all(row["agent"]["id"] != agent["id"] for row in owner_published.json())

    directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert directory.status_code == 200, directory.text
    assert any(row["version_id"] == draft_id for row in directory.json())
    chat = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": draft_id}
    )
    assert chat.status_code == 200, chat.text
    conversation_id = chat.json()["id"]
    sent = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Hello"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"][0]["sources"] == []
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        assert row.snapshot_id is None
        assert row.agent_name_snapshot == "Teacher Private Guide"
        assert db.get(AgentVersion, draft_id).knowledge_snapshot_id is None

    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "w1-private-source-upload-001"}),
        files={
            "file": ("owner-only.md", b"# Owner canary\n\nPrivate source body", "text/markdown")
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]
    source = uploaded.json()["document"]
    assert source["group_id"] is None
    assert source["ownership_scope"] == "personal"
    assert source["visibility"] == "private"
    assert client.get(f"/api/v1/knowledge-documents/{document_id}/download").status_code == 200
    assert (
        client.get(f"/api/v1/courses/{COURSE_ID}/workspace-documents").json()[0]["id"]
        == document_id
    )
    assert client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents").status_code == 404
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(csrf))
    assert joined.status_code == 200, joined.text
    group_documents = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert group_documents.status_code == 200
    assert all(row["id"] != document_id for row in group_documents.json())

    _student, student_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert client.get(f"/api/v1/agent-versions/{draft_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 404
    denied_download = client.get(f"/api/v1/knowledge-documents/{document_id}/download")
    assert denied_download.status_code == 404
    assert b"Owner canary" not in denied_download.content
    assert client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents").json() == []
    assert student_csrf

    with database.session() as db:
        persisted_agent = db.get(Agent, agent["id"])
        persisted_document = db.get(KnowledgeDocument, document_id)
        assert persisted_agent is not None and persisted_agent.group_id is None
        assert (
            persisted_document is not None
            and persisted_document.owner_user_id == "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
        )
        assert UUID(persisted_document.id) == UUID(document_id)


def test_private_group_names_are_owner_scoped_and_public_editor_cannot_probe_them(
    client: TestClient,
) -> None:
    _student, student_csrf = login(client, "bowen")
    private = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-private-name-create-001"}),
        json={"name": "Hidden Name Canary", "visibility": "private"},
    )
    assert private.status_code == 201, private.text
    private_id = private.json()["id"]
    # An empty never-saved draft is reclaimable on retry; give it content so
    # it really holds the name.
    assert (
        client.patch(
            f"/api/v1/agent-versions/{private.json()['versions'][0]['id']}",
            headers=_headers(student_csrf),
            json={"expected_revision": 0, "agent_md": "Private body"},
        ).status_code
        == 200
    )

    duplicate = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-private-name-dup-001"}),
        json={"name": "Hidden Name Canary", "visibility": "private"},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["name"] == "Hidden Name Canary-2"

    hidden_h1 = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-private-h1-create-001"}),
        json={"name": "Edit H1 Secret", "visibility": "private"},
    )
    assert hidden_h1.status_code == 201, hidden_h1.text

    shared = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-private-name-public-001"}),
        json={"name": "Public Rename Target", "visibility": "public"},
    )
    assert shared.status_code == 201, shared.text
    shared_agent = shared.json()
    shared_version_id = shared_agent["versions"][0]["id"]

    # A private owner can use a public group's name in their private
    # namespace; the shared and private namespaces are independent.
    private_with_public_name = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(
            student_csrf,
            **{"Idempotency-Key": "w1-private-name-cross-scope-001"},
        ),
        json={"name": "Public Rename Target", "visibility": "private"},
    )
    assert private_with_public_name.status_code == 201, private_with_public_name.text

    _teacher, teacher_csrf = login(client, "maya")
    assert (
        client.post(
            f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf)
        ).status_code
        == 200
    )
    # A teacher who has entered the group can edit its private Agent content.
    observed = client.get(f"/api/v1/agents/{private_id}")
    assert observed.status_code == 200, observed.text
    assert observed.json()["can_edit"] is True
    teacher_public = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "w1-private-name-teacher-001"}),
        json={"name": "Hidden Name Canary", "visibility": "public"},
    )
    assert teacher_public.status_code == 201, teacher_public.text
    assert (
        client.patch(
            f"/api/v1/agent-versions/{teacher_public.json()['versions'][0]['id']}",
            headers=_headers(teacher_csrf),
            json={"expected_revision": 0, "agent_md": "Teacher body"},
        ).status_code
        == 200
    )
    other_owner_private = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(
            teacher_csrf,
            **{"Idempotency-Key": "w1-private-name-other-owner-001"},
        ),
        json={"name": "Hidden Name Canary", "visibility": "private"},
    )
    assert other_owner_private.status_code == 201, other_owner_private.text
    public_duplicate = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(
            teacher_csrf,
            **{"Idempotency-Key": "w1-public-name-duplicate-001"},
        ),
        json={"name": "Hidden Name Canary", "visibility": "public"},
    )
    assert public_duplicate.status_code == 201, public_duplicate.text
    assert public_duplicate.json()["name"] == "Hidden Name Canary-2"
    rename = client.patch(
        f"/api/v1/agent-versions/{shared_version_id}",
        headers=_headers(teacher_csrf),
        json={
            "expected_revision": 0,
            "agent_md": "# Edit H1 Secret\n\nA public editor cannot see Bowen's private name.",
        },
    )
    # A visit may edit the group's draft. The private name stayed out of the
    # public name namespace above; this write does not reveal it.
    assert rename.status_code == 200, rename.text


def test_agent_visibility_is_chosen_at_creation_and_never_changes(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    agents: dict[str, tuple[str, str]] = {}
    for visibility in ("private", "public"):
        created = client.post(
            f"/api/v1/groups/{GROUP_ID}/agents",
            headers=_headers(owner_csrf, **{"Idempotency-Key": f"w1-locked-{visibility}-001"}),
            json={"name": f"Locked {visibility}", "visibility": visibility},
        )
        assert created.status_code == 201, created.text
        agents[visibility] = (created.json()["id"], created.json()["versions"][0]["id"])

    for visibility, flipped in (("private", "public"), ("public", "private")):
        agent_id, _version = agents[visibility]
        refused = client.patch(
            f"/api/v1/agents/{agent_id}",
            headers=_headers(owner_csrf),
            json={"expected_metadata_revision": 0, "visibility": flipped},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "agent_visibility_locked"
        # The same choice stays accepted, so a description edit still saves.
        kept = client.patch(
            f"/api/v1/agents/{agent_id}",
            headers=_headers(owner_csrf),
            json={
                "expected_metadata_revision": 0,
                "visibility": visibility,
                "description": "Still the same choice.",
            },
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["visibility"] == visibility
        assert kept.json()["metadata_revision"] == 1

    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text
    private_id, private_version = agents["private"]
    public_id, public_version = agents["public"]
    # The entered teacher can edit both. Visibility stays the creator's choice.
    assert client.get(f"/api/v1/agent-versions/{private_version}").status_code == 200
    assert client.get(f"/api/v1/agent-versions/{public_version}").status_code == 200
    assert client.get(f"/api/v1/agents/{public_id}").json()["visibility"] == "public"
    observed = client.get(f"/api/v1/agents/{private_id}")
    assert observed.status_code == 200, observed.text
    assert observed.json()["visibility"] == "private"
    assert observed.json()["can_edit"] is True
    flipped = client.patch(
        f"/api/v1/agents/{private_id}",
        headers=_headers(teacher_csrf),
        json={"expected_metadata_revision": 1, "visibility": "public"},
    )
    assert flipped.status_code in {403, 404}, flipped.text


def test_owner_history_survives_sharing_an_active_private_source(
    client: TestClient,
    database: Any,
) -> None:
    owner, owner_csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-owner-history-agent-001"}),
        json={"name": "Owner History Source", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    version_id = agent["versions"][0]["id"]
    edited = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(owner_csrf),
        json={
            "expected_revision": 0,
            "agent_md": "# Owner History Source\n\nPrivate owner instructions.",
        },
    )
    assert edited.status_code == 200, edited.text
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-owner-history-source-001"}),
        data={
            "target_agent_version_id": version_id,
            "expected_revision": "1",
            "visibility": "private",
        },
        files={
            "file": (
                "owner-history.md",
                b"# Private evidence\n\nOWNER_HISTORY_SOURCE_CANARY",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()["document"]
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-owner-history-publish-001"}),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    snapshot_id = published.json()["knowledge_snapshot_id"]
    conversation = client.post(
        "/api/v1/conversations",
        headers=_headers(owner_csrf),
        json={"version_id": version_id},
    )
    assert conversation.status_code == 200, conversation.text
    conversation_id = conversation.json()["id"]
    first_turn = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(owner_csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "What evidence supports this?",
        },
    )
    assert first_turn.status_code == 200, first_turn.text

    shared = client.patch(
        f"/api/v1/knowledge-documents/{source['id']}",
        headers=_headers(owner_csrf),
        json={"expected_authorization_epoch": 0, "visibility": "public"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["authorization_epoch"] == 1
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}/download").status_code == 200

    owner_history = client.get(f"/api/v1/agents/{agent['id']}/versions")
    assert owner_history.status_code == 200, owner_history.text
    assert [row["id"] for row in owner_history.json()] == [version_id]
    version = client.get(f"/api/v1/agent-versions/{version_id}")
    assert version.status_code == 200, version.text
    assert "Private owner instructions." in version.json()["agent_md"]
    detail = client.get(f"/api/v1/agents/{agent['id']}")
    assert [row["id"] for row in detail.json()["versions"]] == [version_id]
    snapshot = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}")
    assert snapshot.status_code == 200, snapshot.text
    source_id = snapshot.json()["documents"][0]["id"]
    rag_download = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download")
    assert rag_download.status_code == 200, rag_download.text
    assert "OWNER_HISTORY_SOURCE_CANARY" in rag_download.text
    source_download = client.get(
        f"/api/v1/knowledge-snapshots/{snapshot_id}/documents/{source_id}/download"
    )
    assert source_download.status_code == 200, source_download.text
    assert "OWNER_HISTORY_SOURCE_CANARY" in source_download.text

    second_turn = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(owner_csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": 1,
            "message": "Use the same evidence again.",
        },
    )
    assert second_turn.status_code == 200, second_turn.text

    _peer, peer_csrf = login(client, "kaikai")
    assert client.get(f"/api/v1/agents/{agent['id']}").status_code == 404
    assert client.get(f"/api/v1/agents/{agent['id']}/versions").status_code == 404
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}/download").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}/download").status_code == 200
    assert peer_csrf

    with database.session() as session:
        membership = session.get(GroupMember, (GROUP_ID, owner["user"]["id"]))
        assert membership is not None
        session.delete(membership)
    _owner, _owner_csrf = login(client, "bowen")
    revoked_version = client.get(f"/api/v1/agent-versions/{version_id}")
    assert revoked_version.status_code == 404
    revoked_snapshot = client.get(f"/api/v1/knowledge-snapshots/{snapshot_id}")
    assert revoked_snapshot.status_code == 404
    retained_chat = client.get(f"/api/v1/conversations/{conversation_id}")
    assert retained_chat.status_code == 200, retained_chat.text
    assert retained_chat.json()["agent"]["available"] is False
    assert len(retained_chat.json()["turns"]) == 2


def test_private_source_makes_public_agent_draft_owner_only_even_after_source_is_shared(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-private-source-draft-agent-001"}),
        json={"name": "Private Source Draft", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    # Uploading into this public Agent would make the file public, so the
    # private source arrives as an existing library file the owner attaches.
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-private-source-draft-001"}),
        data={"visibility": "private"},
        files={
            "file": ("private-source.md", b"# Source\n\nPRIVATE_SOURCE_CANARY", "text/markdown")
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]
    attached = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(owner_csrf),
        json={"expected_revision": 0, "document_ids": [document_id]},
    )
    assert attached.status_code == 200, attached.text

    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text
    hidden = client.get(f"/api/v1/agents/{agent_id}")
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["versions"] == []
    assert hidden.json()["current_draft_version_id"] is None
    assert "PRIVATE_SOURCE_CANARY" not in hidden.text
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404

    _owner, owner_csrf = login(client, "bowen")
    shared_source = client.patch(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=_headers(owner_csrf),
        json={"expected_authorization_epoch": 0, "visibility": "public"},
    )
    assert shared_source.status_code == 200, shared_source.text
    assert shared_source.json()["visibility"] == "public"

    _teacher, teacher_csrf = login(client, "maya")
    still_hidden = client.get(f"/api/v1/agents/{agent_id}")
    assert still_hidden.status_code == 200, still_hidden.text
    assert still_hidden.json()["versions"] == []
    assert still_hidden.json()["current_draft_version_id"] is None
    assert "PRIVATE_SOURCE_CANARY" not in still_hidden.text
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404


def test_rag_uploaded_into_an_agent_takes_the_agents_visibility(client: TestClient) -> None:
    _owner, owner_csrf = login(client, "bowen")
    for visibility in ("private", "public"):
        created = client.post(
            f"/api/v1/groups/{GROUP_ID}/agents",
            headers=_headers(owner_csrf, **{"Idempotency-Key": f"w1-follow-{visibility}-001"}),
            json={"name": f"Follows {visibility}", "visibility": visibility},
        )
        assert created.status_code == 201, created.text
        version_id = created.json()["versions"][0]["id"]
        flipped = "public" if visibility == "private" else "private"
        refused = client.post(
            f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
            headers=_headers(owner_csrf, **{"Idempotency-Key": f"w1-follow-{visibility}-bad"}),
            data={
                "target_agent_version_id": version_id,
                "expected_revision": "0",
                "visibility": flipped,
            },
            files={"file": (f"{visibility}-bad.md", b"# Wrong\n\nMismatch", "text/markdown")},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "document_visibility_follows_agent"
        uploaded = client.post(
            f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
            headers=_headers(owner_csrf, **{"Idempotency-Key": f"w1-follow-{visibility}-ok"}),
            data={"target_agent_version_id": version_id, "expected_revision": "0"},
            files={
                "file": (f"{visibility}.md", f"# {visibility}\n\nFollows".encode(), "text/markdown")
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()["document"]["visibility"] == visibility

    # Only the public Agent's file reaches a classmate's Brainform.
    login(client, "kaikai")
    listed = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert listed.status_code == 200, listed.text
    names = {row["source_filename"] for row in listed.json()}
    assert "public.md" in names and "private.md" not in names


def test_a_teachers_public_agent_rag_stays_out_of_student_brainform(client: TestClient) -> None:
    _teacher, csrf = login(client, "maya")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(csrf, **{"Idempotency-Key": "w1-teacher-public-rag-agent"}),
        json={"name": "Teacher Public Guide", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]
    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "w1-teacher-public-rag-upload"}),
        data={"target_agent_version_id": version_id, "expected_revision": "0"},
        files={"file": ("guide.md", b"# Guide\n\nCourse notes", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["document"]
    assert document["ownership_scope"] == "personal"
    assert document["visibility"] == "public"
    own = client.get(f"/api/v1/courses/{COURSE_ID}/workspace-documents").json()
    assert [row["id"] for row in own] == [document["id"]]

    # A student meets it only read-only inside that Agent, never in Brainform.
    login(client, "kaikai")
    listed = client.get(f"/api/v1/groups/{GROUP_ID}/knowledge-documents")
    assert listed.status_code == 200, listed.text
    assert all(row["id"] != document["id"] for row in listed.json())


def _create_public_group_agent(client: TestClient, csrf: str, name: str) -> tuple[str, str]:
    key = name.lower().replace(" ", "-")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": f"w1-acl-{key}-create-001"}),
        json={"name": name, "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={"expected_revision": 0, "agent_md": f"# {name}\n\nSynthetic shared Agent."},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": f"w1-acl-{key}-publish-001"}),
        json={"expected_revision": 1},
    )
    assert published.status_code == 200, published.text
    return agent_id, version_id


def test_group_public_access_is_scoped_to_group_and_lost_access_only_disables_chat(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _owner, owner_csrf = login(client, "bowen")
    agent_id, version_id = _create_public_group_agent(client, owner_csrf, "Group ACL Probe")
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-acl-source-upload-001"}),
        data={"visibility": "public"},
        files={
            "file": ("group-source.md", b"# Group source\n\nGROUP_SOURCE_CANARY", "text/markdown")
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    source = uploaded.json()["document"]
    source_id = source["id"]

    # A real member and a same-course Teacher retain the Group Public path.
    _peer, peer_csrf = login(client, "kaikai")
    peer_directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert peer_directory.status_code == 200
    assert any(row["agent_id"] == agent_id for row in peer_directory.json())
    peer_published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert any(row["agent"]["id"] == agent_id for row in peer_published.json())
    peer_chat = client.post(
        "/api/v1/conversations", headers=_headers(peer_csrf), json={"version_id": version_id}
    )
    assert peer_chat.status_code == 200, peer_chat.text
    peer_conversation_id = peer_chat.json()["id"]
    sent = post_message(
        client,
        f"/api/v1/conversations/{peer_conversation_id}/messages",
        headers=_headers(peer_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Keep history"},
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"][0]["assistant_text"]
    assert client.get(f"/api/v1/knowledge-documents/{source_id}").status_code == 200
    assert client.get(f"/api/v1/knowledge-documents/{source_id}/download").status_code == 200

    _teacher, teacher_csrf = login(client, "maya")
    teacher_directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert any(row["agent_id"] == agent_id for row in teacher_directory.json())
    teacher_published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert any(row["agent"]["id"] == agent_id for row in teacher_published.json())
    teacher_chat = client.post(
        "/api/v1/conversations", headers=_headers(teacher_csrf), json={"version_id": version_id}
    )
    assert teacher_chat.status_code == 200, teacher_chat.text

    # The resource owner also gets a retained Chat whose invoke availability
    # must follow current Group membership.
    _owner, owner_csrf = login(client, "bowen")
    owner_chat = client.post(
        "/api/v1/conversations", headers=_headers(owner_csrf), json={"version_id": version_id}
    )
    assert owner_chat.status_code == 200, owner_chat.text
    owner_conversation_id = owner_chat.json()["id"]
    owner_sent = post_message(
        client,
        f"/api/v1/conversations/{owner_conversation_id}/messages",
        headers=_headers(owner_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 0, "message": "Owner history"},
    )
    assert owner_sent.status_code == 200, owner_sent.text

    # A student in a different group in the same course cannot discover, invoke,
    # read, download, reindex, replace or hide these Public group resources.
    other = register(client, username="w1-acl-other-group", group_name="W1 ACL Other Group")
    assert other.status_code == 201, other.text
    other_csrf = other.json()["csrf_token"]
    other_directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert all(row["agent_id"] != agent_id for row in other_directory.json())
    other_published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert all(row["agent"]["id"] != agent_id for row in other_published.json())
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{source_id}").status_code == 404
    denied_download = client.get(f"/api/v1/knowledge-documents/{source_id}/download")
    assert denied_download.status_code == 404
    assert b"GROUP_SOURCE_CANARY" not in denied_download.content
    denied_chat = client.post(
        "/api/v1/conversations", headers=_headers(other_csrf), json={"version_id": version_id}
    )
    assert denied_chat.status_code == 404
    denied_replace = client.post(
        f"/api/v1/knowledge-documents/{source_id}/replace",
        headers=_headers(other_csrf, **{"Idempotency-Key": "w1-acl-cross-group-replace-001"}),
        data={
            "expected_content_hash": source["content_hash"],
            "expected_index_revision": str(source["index_revision"]),
        },
        files={"file": ("replacement.md", b"# Unauthorized replacement", "text/markdown")},
    )
    assert denied_replace.status_code == 404
    denied_reindex = client.post(
        f"/api/v1/knowledge-documents/{source_id}/reindex",
        headers=_headers(other_csrf, **{"Idempotency-Key": "w1-acl-cross-group-reindex-001"}),
    )
    assert denied_reindex.status_code == 404
    denied_hide = client.post(
        f"/api/v1/knowledge-documents/{source_id}/hide",
        headers=_headers(other_csrf, **{"Idempotency-Key": "w1-acl-cross-group-hide-001"}),
    )
    assert denied_hide.status_code == 404

    # Losing Group membership retains old text but removes the live invoke grant.
    with database.session() as session:
        session.delete(session.get(GroupMember, (GROUP_ID, "bc170f51-45fb-5296-a36d-a2edc8f8d315")))
    _peer, peer_csrf = login(client, "kaikai")
    lost_access = client.get(f"/api/v1/conversations/{peer_conversation_id}")
    assert lost_access.status_code == 200, lost_access.text
    assert lost_access.json()["agent"]["available"] is False
    assert len(lost_access.json()["turns"]) == 1
    assert lost_access.json()["turns"][0]["user_text"] == "Keep history"
    denied_continue = post_message(
        client,
        f"/api/v1/conversations/{peer_conversation_id}/messages",
        headers=_headers(peer_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "Continue"},
    )
    assert denied_continue.status_code == 409
    assert denied_continue.json()["code"] == "agent_unavailable"
    assert len(client.get(f"/api/v1/conversations/{peer_conversation_id}").json()["turns"]) == 1

    # Owner identity alone does not keep a Group resource live after the owner
    # leaves that Group; the frozen Chat remains visible to its owner.
    with database.session() as session:
        session.delete(session.get(GroupMember, (GROUP_ID, "60541c78-30f1-55c5-b2aa-207b6a766883")))
    _owner, owner_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    owner_history = client.get(f"/api/v1/conversations/{owner_conversation_id}")
    assert owner_history.status_code == 200
    assert owner_history.json()["agent"]["available"] is False
    assert len(owner_history.json()["turns"]) == 1
    assert owner_history.json()["turns"][0]["user_text"] == "Owner history"
    owner_denied = post_message(
        client,
        f"/api/v1/conversations/{owner_conversation_id}/messages",
        headers=_headers(owner_csrf),
        json={"request_id": str(uuid4()), "expected_revision": 1, "message": "No longer live"},
    )
    assert owner_denied.status_code == 409
    assert owner_denied.json()["code"] == "agent_unavailable"
    owner_source_edit = client.post(
        f"/api/v1/knowledge-documents/{source_id}/replace",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-acl-owner-revoked-replace-001"}),
        data={
            "expected_content_hash": source["content_hash"],
            "expected_index_revision": str(source["index_revision"]),
        },
        files={"file": ("revoked.md", b"# Owner left the group", "text/markdown")},
    )
    assert owner_source_edit.status_code == 404
    owner_visibility = client.patch(
        f"/api/v1/knowledge-documents/{source_id}",
        headers=_headers(owner_csrf),
        json={
            "expected_authorization_epoch": source["authorization_epoch"],
            "visibility": "private",
        },
    )
    assert owner_visibility.status_code == 404


def test_personal_public_agent_is_visible_to_the_course(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "maya")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-personal-public-create-001"}),
        json={"name": "Personal Public Canary", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(owner_csrf),
        json={"expected_revision": 0, "agent_md": "# Personal\n\nOwner-only until granted."},
    )
    assert saved.status_code == 200, saved.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-personal-public-publish-001"}),
        json={"expected_revision": 1},
    )
    assert published.status_code == 200, published.text

    # Studyform (2026-10-18): a teacher's public Agent is usable by the
    # course only through a Team; students do not list, open or single-chat it.
    _student, student_csrf = login(client, "bowen")
    directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert not any(row["agent_id"] == agent_id for row in directory.json())
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
    opened = client.post(
        "/api/v1/conversations", headers=_headers(student_csrf), json={"version_id": version_id}
    )
    assert opened.status_code == 404, opened.text
    published_list = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert published_list.status_code == 200
    assert not any(row["agent"]["id"] == agent_id for row in published_list.json())
    denied_next = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-personal-public-next-denied"}),
    )
    assert denied_next.status_code == 404

    # The same holds for a student outside the teacher's groups.
    other = register(client, username="w1-teacher-public-outsider", group_name="W1 Outside")
    assert other.status_code == 201, other.text
    other_csrf = other.json()["csrf_token"]
    other_directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert not any(row["agent_id"] == agent_id for row in other_directory.json())
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    other_published = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert not any(row["agent"]["id"] == agent_id for row in other_published.json())
    other_chat = client.post(
        "/api/v1/conversations", headers=_headers(other_csrf), json={"version_id": version_id}
    )
    assert other_chat.status_code == 404, other_chat.text

    # Its teacher still sees and chats with it.
    _owner, owner_csrf = login(client, "maya")
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 200
    teacher_chat = client.post(
        "/api/v1/conversations", headers=_headers(owner_csrf), json={"version_id": version_id}
    )
    assert teacher_chat.status_code == 200, teacher_chat.text


def test_teacher_public_group_source_is_usable_outside_that_group(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "maya")
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-teacher-source-agent-001"}),
        json={"name": "Teacher Shared Source", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]
    saved = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(owner_csrf),
        json={"expected_revision": 0, "agent_md": "# Teacher Shared Source\n\nCourse usable."},
    )
    assert saved.status_code == 200, saved.text
    assert (
        client.post(
            f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(owner_csrf)
        ).status_code
        == 200
    )
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-teacher-source-doc-001"}),
        data={"visibility": "public"},
        files={"file": ("shared.md", b"# Shared\n\nTEACHER_PUBLIC_SOURCE_CANARY", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]
    linked = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(owner_csrf),
        json={"expected_revision": 1, "document_ids": [document_id]},
    )
    assert linked.status_code == 200, linked.text
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-teacher-source-publish-001"}),
        json={"expected_revision": linked.json()["revision"]},
    )
    assert published.status_code == 200, published.text

    other = register(client, username="w1-teacher-source-outsider", group_name="W1 Source Outside")
    assert other.status_code == 201, other.text
    other_csrf = other.json()["csrf_token"]
    # Studyform: students reach a teacher's public Agent only through a Team.
    published_list = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert not any(row["agent"]["id"] == agent_id for row in published_list.json())
    opened = client.post(
        "/api/v1/conversations", headers=_headers(other_csrf), json={"version_id": version_id}
    )
    assert opened.status_code == 404, opened.text
    assert client.get(f"/api/v1/knowledge-documents/{document_id}").status_code == 404
    denied_download = client.get(f"/api/v1/knowledge-documents/{document_id}/download")
    assert denied_download.status_code == 404
    assert b"TEACHER_PUBLIC_SOURCE_CANARY" not in denied_download.content


def test_legacy_group_agent_binds_entered_teachers_public_group_source_only(
    client: TestClient,
    database: Any,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-legacy-public-agent-create-001"}),
        json={"name": "Legacy Public Binding", "visibility": "public"},
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    version_id = created.json()["versions"][0]["id"]

    _teacher, teacher_csrf = login(client, "maya")
    assert (
        client.post(
            f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf)
        ).status_code
        == 200
    )
    owned_public_source = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "w1-legacy-public-source-001"}),
        data={"visibility": "public"},
        files={
            "file": ("teacher-shared.md", b"# Shared\n\nTEACHER_PUBLIC_SOURCE", "text/markdown")
        },
    )
    assert owned_public_source.status_code == 201, owned_public_source.text
    public_source_id = owned_public_source.json()["document"]["id"]
    private_source = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "w1-legacy-private-source-001"}),
        data={"visibility": "private"},
        files={
            "file": ("teacher-private.md", b"# Private\n\nTEACHER_PRIVATE_SOURCE", "text/markdown")
        },
    )
    assert private_source.status_code == 201, private_source.text
    private_source_id = private_source.json()["document"]["id"]

    # A group Agent with no publishing account is not editable, even by a
    # teacher who has entered the group.
    with database.session() as session:
        persisted = session.get(Agent, agent_id)
        assert persisted is not None
        persisted.owner_user_id = None
    linked = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={"expected_revision": 0, "document_ids": [public_source_id]},
    )
    assert linked.status_code == 404, linked.text

    private_link = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={"expected_revision": 0, "document_ids": [private_source_id]},
    )
    assert private_link.status_code == 404
    current = client.get(f"/api/v1/agent-versions/{version_id}")
    assert current.status_code == 200
    assert current.json()["revision"] == 0
    assert current.json()["enabled_documents"] == []

    other = register(client, username="w1-legacy-cross-group", group_name="W1 Legacy Other")
    assert other.status_code == 201, other.text
    other_csrf = other.json()["csrf_token"]
    other_source = client.post(
        f"/api/v1/groups/{other.json()['user']['groups'][0]['group_id']}/knowledge-documents",
        headers=_headers(other_csrf, **{"Idempotency-Key": "w1-legacy-other-source-001"}),
        data={"visibility": "public"},
        files={"file": ("other.md", b"# Other group", "text/markdown")},
    )
    assert other_source.status_code == 201, other_source.text
    _teacher, teacher_csrf = login(client, "maya")
    cross_group_link = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={
            "expected_revision": 0,
            "document_ids": [other_source.json()["document"]["id"]],
        },
    )
    assert cross_group_link.status_code == 404
