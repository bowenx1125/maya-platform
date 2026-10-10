from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.core.models import Agent, AgentVersion, GroupMember, KnowledgeDocument
from app.modules.workspace.models import Conversation
from fastapi.testclient import TestClient

from tests.conftest import login
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

    directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert directory.status_code == 200, directory.text
    assert any(row["version_id"] == draft_id for row in directory.json())
    chat = client.post(
        "/api/v1/conversations", headers=_headers(csrf), json={"version_id": draft_id}
    )
    assert chat.status_code == 200, chat.text
    conversation_id = chat.json()["id"]
    sent = client.post(
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

    duplicate = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(student_csrf, **{"Idempotency-Key": "w1-private-name-dup-001"}),
        json={"name": "Hidden Name Canary", "visibility": "private"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "agent_name_conflict"

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
    assert client.get(f"/api/v1/agents/{private_id}").status_code == 404
    teacher_public = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(teacher_csrf, **{"Idempotency-Key": "w1-private-name-teacher-001"}),
        json={"name": "Hidden Name Canary", "visibility": "public"},
    )
    assert teacher_public.status_code == 201, teacher_public.text
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
    assert public_duplicate.status_code == 409
    rename = client.patch(
        f"/api/v1/agent-versions/{shared_version_id}",
        headers=_headers(teacher_csrf),
        json={
            "expected_revision": 0,
            "agent_md": "# Edit H1 Secret\n\nA public editor cannot see Bowen's private name.",
        },
    )
    assert rename.status_code == 200, rename.text
    assert rename.json()["agent_id"] == shared_agent["id"]


def test_private_history_and_private_derived_clone_stay_owner_only_until_publish(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-o6-private-history-001"}),
        json={"name": "O6 Hidden History", "visibility": "private"},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    agent_id = agent["id"]
    first_version_id = agent["versions"][0]["id"]
    secret = "O6_PRIVATE_V1_CANARY"

    first_edit = client.patch(
        f"/api/v1/agent-versions/{first_version_id}",
        headers=_headers(owner_csrf),
        json={"expected_revision": 0, "agent_md": f"# O6 Hidden History\n\n{secret}"},
    )
    assert first_edit.status_code == 200, first_edit.text
    first_publish = client.post(
        f"/api/v1/agent-versions/{first_version_id}/publish",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-o6-private-publish-001"}),
        json={"expected_revision": 1},
    )
    assert first_publish.status_code == 200, first_publish.text
    assert first_publish.json()["published_visibility"] == "private"

    made_public = client.patch(
        f"/api/v1/agents/{agent_id}",
        headers=_headers(owner_csrf),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert made_public.status_code == 200, made_public.text
    clone = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-o6-private-clone-001"}),
        json={},
    )
    assert clone.status_code == 201, clone.text
    draft_id = clone.json()["id"]
    assert secret in clone.json()["agent_md"]

    _teacher, teacher_csrf = login(client, "maya")
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 404
    assert client.get(f"/api/v1/agents/{agent_id}/versions").status_code == 404
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text

    teacher_detail = client.get(f"/api/v1/agents/{agent_id}")
    assert teacher_detail.status_code == 200, teacher_detail.text
    assert teacher_detail.json()["versions"] == []
    assert teacher_detail.json()["current_draft_version_id"] is None
    assert secret not in teacher_detail.text
    assert client.get(f"/api/v1/agents/{agent_id}/versions").json() == []
    for version_id in (first_version_id, draft_id):
        assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 404
        assert (
            client.get(f"/api/v1/agent-versions/{version_id}/agent-md/download").status_code == 404
        )

    _owner, owner_csrf = login(client, "bowen")
    owner_history = client.get(f"/api/v1/agents/{agent_id}/versions")
    assert owner_history.status_code == 200, owner_history.text
    assert [row["id"] for row in owner_history.json()] == [first_version_id, draft_id]
    assert secret in owner_history.json()[0]["agent_md"]
    assert client.get(f"/api/v1/agents/{agent_id}").json()["current_draft_version_id"] == draft_id

    second_edit = client.patch(
        f"/api/v1/agent-versions/{draft_id}",
        headers=_headers(owner_csrf),
        json={
            "expected_revision": 0,
            "agent_md": "# O6 Hidden History\n\nOwner-reviewed public V2 content.",
        },
    )
    assert second_edit.status_code == 200, second_edit.text
    second_publish = client.post(
        f"/api/v1/agent-versions/{draft_id}/publish",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-o6-public-publish-002"}),
        json={"expected_revision": 1},
    )
    assert second_publish.status_code == 200, second_publish.text
    assert second_publish.json()["published_visibility"] == "public"

    _teacher, teacher_csrf = login(client, "maya")
    public_detail = client.get(f"/api/v1/agents/{agent_id}")
    assert public_detail.status_code == 200, public_detail.text
    assert [row["id"] for row in public_detail.json()["versions"]] == [draft_id]
    assert public_detail.json()["current_draft_version_id"] is None
    assert secret not in public_detail.text
    public_history = client.get(f"/api/v1/agents/{agent_id}/versions")
    assert [row["id"] for row in public_history.json()] == [draft_id]
    assert client.get(f"/api/v1/agent-versions/{first_version_id}").status_code == 404

    left = client.delete(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert left.status_code == 204
    unentered_teacher = client.get(f"/api/v1/agents/{agent_id}")
    assert unentered_teacher.status_code == 200, unentered_teacher.text
    assert [row["id"] for row in unentered_teacher.json()["versions"]] == [draft_id]
    assert secret not in unentered_teacher.text
    assert client.get(f"/api/v1/agents/{agent_id}/versions").json()[0]["id"] == draft_id
    assert client.get(f"/api/v1/agent-versions/{first_version_id}").status_code == 404


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
    first_turn = client.post(
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

    second_turn = client.post(
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


def test_private_edit_stays_hidden_but_untouched_public_draft_can_return_to_shared(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    shared = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-draft-sharing-public-001"}),
        json={"name": "Shared Draft Control", "visibility": "public"},
    )
    assert shared.status_code == 201, shared.text
    shared_id = shared.json()["id"]
    shared_version = shared.json()["versions"][0]["id"]

    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(f"/api/v1/groups/{GROUP_ID}/membership", headers=_headers(teacher_csrf))
    assert joined.status_code == 200, joined.text
    assert client.get(f"/api/v1/agent-versions/{shared_version}").status_code == 200

    _owner, owner_csrf = login(client, "bowen")
    to_private = client.patch(
        f"/api/v1/agents/{shared_id}",
        headers=_headers(owner_csrf),
        json={"expected_metadata_revision": 0, "visibility": "private"},
    )
    assert to_private.status_code == 200, to_private.text
    private_edit = client.patch(
        f"/api/v1/agent-versions/{shared_version}",
        headers=_headers(owner_csrf),
        json={"expected_revision": 0, "agent_md": "# Shared Draft Control\n\nPrivate edit."},
    )
    assert private_edit.status_code == 200, private_edit.text
    back_to_public = client.patch(
        f"/api/v1/agents/{shared_id}",
        headers=_headers(owner_csrf),
        json={"expected_metadata_revision": 1, "visibility": "public"},
    )
    assert back_to_public.status_code == 200, back_to_public.text
    _teacher, teacher_csrf = login(client, "maya")
    visible = client.get(f"/api/v1/agents/{shared_id}")
    assert visible.status_code == 200, visible.text
    assert visible.json()["versions"] == []
    assert visible.json()["current_draft_version_id"] is None
    assert client.get(f"/api/v1/agent-versions/{shared_version}").status_code == 404

    _owner, owner_csrf = login(client, "bowen")
    untouched = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-draft-sharing-untouched-001"}),
        json={"name": "Untouched Shared Draft", "visibility": "public"},
    )
    assert untouched.status_code == 201, untouched.text
    untouched_id = untouched.json()["id"]
    untouched_version = untouched.json()["versions"][0]["id"]
    to_private = client.patch(
        f"/api/v1/agents/{untouched_id}",
        headers=_headers(owner_csrf),
        json={"expected_metadata_revision": 0, "visibility": "private"},
    )
    assert to_private.status_code == 200, to_private.text
    to_public = client.patch(
        f"/api/v1/agents/{untouched_id}",
        headers=_headers(owner_csrf),
        json={"expected_metadata_revision": 1, "visibility": "public"},
    )
    assert to_public.status_code == 200, to_public.text
    _teacher, teacher_csrf = login(client, "maya")
    returned = client.get(f"/api/v1/agents/{untouched_id}")
    assert returned.status_code == 200, returned.text
    assert [row["id"] for row in returned.json()["versions"]] == [untouched_version]
    assert returned.json()["current_draft_version_id"] == untouched_version
    assert client.get(f"/api/v1/agent-versions/{untouched_version}").status_code == 200


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
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(owner_csrf, **{"Idempotency-Key": "w1-private-source-draft-001"}),
        data={
            "target_agent_version_id": version_id,
            "expected_revision": "0",
            "visibility": "private",
        },
        files={
            "file": ("private-source.md", b"# Source\n\nPRIVATE_SOURCE_CANARY", "text/markdown")
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]

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
    peer_chat = client.post(
        "/api/v1/conversations", headers=_headers(peer_csrf), json={"version_id": version_id}
    )
    assert peer_chat.status_code == 200, peer_chat.text
    peer_conversation_id = peer_chat.json()["id"]
    sent = client.post(
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
    owner_sent = client.post(
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
    denied_continue = client.post(
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
    owner_denied = client.post(
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

    _student, student_csrf = login(client, "bowen")
    directory = client.get(f"/api/v1/courses/{COURSE_ID}/chat-agents")
    assert any(row["agent_id"] == agent_id for row in directory.json())
    assert client.get(f"/api/v1/agents/{agent_id}").status_code == 200
    assert client.get(f"/api/v1/agent-versions/{version_id}").status_code == 200
    opened = client.post(
        "/api/v1/conversations", headers=_headers(student_csrf), json={"version_id": version_id}
    )
    assert opened.status_code == 200, opened.text
    published_list = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert published_list.status_code == 200
    assert any(row["agent"]["id"] == agent_id for row in published_list.json())


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

    # Legacy pre-W1 group assets intentionally have no guessed owner. A current
    # editor may still attach an explicitly shared same-Group source.
    with database.session() as session:
        persisted = session.get(Agent, agent_id)
        assert persisted is not None
        persisted.owner_user_id = None
    linked = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={"expected_revision": 0, "document_ids": [public_source_id]},
    )
    assert linked.status_code == 200, linked.text
    assert [item["id"] for item in linked.json()["enabled_documents"]] == [public_source_id]

    # Editor ownership of a Private source does not authorize attaching it to
    # a legacy Group Agent with unknown owner.
    private_link = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={"expected_revision": 1, "document_ids": [private_source_id]},
    )
    assert private_link.status_code == 404
    current = client.get(f"/api/v1/agent-versions/{version_id}")
    assert current.status_code == 200
    assert current.json()["revision"] == 1
    assert [item["id"] for item in current.json()["enabled_documents"]] == [public_source_id]

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
            "expected_revision": 1,
            "document_ids": [other_source.json()["document"]["id"]],
        },
    )
    assert cross_group_link.status_code == 404
