from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import Course, KnowledgeDocument, TeacherGroupAccess
from app.modules.knowledge_sets.models import (
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeSet,
    KnowledgeSetSource,
)
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
MAYA_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
BOWEN_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"


def _headers(csrf: str, key: str | None = None) -> dict[str, str]:
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _create_set(
    client: TestClient,
    csrf: str,
    name: str,
    *,
    group_id: str | None = None,
    key: str = "k1-create-set-default-01",
) -> dict[str, Any]:
    body: dict[str, Any] = {"display_name": name}
    if group_id is not None:
        body["group_id"] = group_id
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, key),
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_source(
    client: TestClient,
    csrf: str,
    *,
    visibility: str,
    content: str,
    filename: str = "lesson.md",
    key: str = "k1-upload-source-default-01",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, key),
        data={"visibility": visibility},
        files={"file": (filename, content.encode("utf-8"), "text/markdown")},
    )
    assert response.status_code == 201, response.text
    return response.json()["document"]


def _question(
    prompt: str,
    rubric_label: str,
    rubric_guidance: str,
    *,
    reference_answer: str | None = None,
) -> dict[str, Any]:
    content = {
        "kind": "question",
        "prompt": prompt,
        "concept_ids": [],
        "citations": [],
        "rubric": {
            "criteria": [{"label": rubric_label, "guidance": rubric_guidance, "points": 2}],
            "total_points": 2,
        },
    }
    if reference_answer is not None:
        content["reference_answer"] = reference_answer
    return content


def test_set_create_agent_binding_and_asset_save_are_cas_and_idempotent(
    client: TestClient, database: Any
) -> None:
    _teacher, csrf = login(client, "maya")
    create_key = "k1-personal-set-create-0001"
    body = {"display_name": "Private teaching notes"}
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, create_key),
        json=body,
    )
    assert created.status_code == 201, created.text
    set_row = created.json()
    replayed_create = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, create_key),
        json=body,
    )
    assert replayed_create.status_code == 201, replayed_create.text
    assert replayed_create.json()["id"] == set_row["id"]

    changed_body = {"display_name": "A different Set"}
    reused_key = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, create_key),
        json=changed_body,
    )
    assert reused_key.status_code == 409
    assert reused_key.json()["code"] == "idempotency_conflict"

    created_agent = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(csrf, "k1-personal-agent-create-01"),
        json={"name": "Teacher Resource Agent"},
    )
    assert created_agent.status_code == 201, created_agent.text
    agent = created_agent.json()
    binding_body = {
        "expected_agent_metadata_revision": agent["metadata_revision"],
        "set_ids": [set_row["id"]],
    }
    bound = client.put(
        f"/api/v1/agents/{agent['id']}/knowledge-sets",
        headers=_headers(csrf, "k1-private-agent-set-bind-01"),
        json=binding_body,
    )
    assert bound.status_code == 200, bound.text
    assert [row["id"] for row in bound.json()["sets"]] == [set_row["id"]]
    bound_replay = client.put(
        f"/api/v1/agents/{agent['id']}/knowledge-sets",
        headers=_headers(csrf, "k1-private-agent-set-bind-01"),
        json=binding_body,
    )
    assert bound_replay.status_code == 200, bound_replay.text
    assert bound_replay.json()["sets"][0]["id"] == set_row["id"]

    set_id = set_row["id"]
    create_asset_body = {
        "expected_content_revision": 0,
        "content": _question(
            "What changes when water cools?", "Reasoning", "Owner rubric canary one"
        ),
    }
    create_asset_key = "k1-question-create-idempotent-01"
    created_asset = client.post(
        f"/api/v1/knowledge-sets/{set_id}/assets",
        headers=_headers(csrf, create_asset_key),
        json=create_asset_body,
    )
    assert created_asset.status_code == 201, created_asset.text
    asset_v1 = created_asset.json()
    assert asset_v1["current_version_seq"] == 1

    update_body = {
        "expected_content_revision": 1,
        "expected_asset_version_seq": 1,
        "content": _question(
            "What changes when water cools?", "Reasoning", "Owner rubric canary two"
        ),
    }
    updated_asset = client.patch(
        f"/api/v1/knowledge-assets/{asset_v1['id']}",
        headers=_headers(csrf, "k1-question-version-two-0001"),
        json=update_body,
    )
    assert updated_asset.status_code == 200, updated_asset.text
    assert updated_asset.json()["current_version_seq"] == 2

    # A delayed response retry returns its original immutable version rather
    # than the now-current V2, and never writes a third version.
    replayed_v1 = client.post(
        f"/api/v1/knowledge-sets/{set_id}/assets",
        headers=_headers(csrf, create_asset_key),
        json=create_asset_body,
    )
    assert replayed_v1.status_code == 201, replayed_v1.text
    assert replayed_v1.json() == asset_v1
    assert replayed_v1.json()["id"] == asset_v1["id"]
    assert replayed_v1.json()["current_version_seq"] == 1
    assert (
        replayed_v1.json()["current_version"]["content"]["rubric"]["criteria"][0]["guidance"]
        == "Owner rubric canary one"
    )

    replayed_v2 = client.patch(
        f"/api/v1/knowledge-assets/{asset_v1['id']}",
        headers=_headers(csrf, "k1-question-version-two-0001"),
        json=update_body,
    )
    assert replayed_v2.status_code == 200, replayed_v2.text
    assert replayed_v2.json() == updated_asset.json()
    assert replayed_v2.json()["current_version_seq"] == 2

    deleted_set = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_id}",
        headers=_headers(csrf, "k1-delete-set-after-asset-replays"),
        json={"expected_metadata_revision": 0, "expected_content_revision": 2},
    )
    assert deleted_set.status_code == 200, deleted_set.text
    assert (
        client.post(
            f"/api/v1/knowledge-sets/{set_id}/assets",
            headers=_headers(csrf, create_asset_key),
            json=create_asset_body,
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/knowledge-assets/{asset_v1['id']}",
            headers=_headers(csrf, "k1-question-version-two-0001"),
            json=update_body,
        ).status_code
        == 404
    )

    _student, _student_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/knowledge-sets/{set_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-assets/{asset_v1['id']}").status_code == 404
    with database.session_factory() as db:
        assert (
            db.query(KnowledgeAssetVersion)
            .filter(KnowledgeAssetVersion.asset_id == asset_v1["id"])
            .count()
            == 2
        )
        current_set = db.get(KnowledgeSet, set_id)
        assert current_set is not None
        assert current_set.content_revision == 3


def test_group_public_student_projection_omits_rubric_and_its_fingerprint(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        owner_csrf,
        "Shared question bank",
        group_id=GROUP_ID,
        key="k1-public-set-create-0001",
    )
    set_id = knowledge_set["id"]
    shared = client.patch(
        f"/api/v1/knowledge-sets/{set_id}",
        headers=_headers(owner_csrf, "k1-public-set-share-0001"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["authorization_epoch"] == 1

    v1 = client.post(
        f"/api/v1/knowledge-sets/{set_id}/assets",
        headers=_headers(owner_csrf, "k1-public-question-create-01"),
        json={
            "expected_content_revision": 0,
            "content": _question(
                "Explain evaporation.",
                "Evidence",
                "private rubric canary alpha",
                reference_answer="private answer canary one",
            ),
        },
    )
    assert v1.status_code == 201, v1.text
    asset_id = v1.json()["id"]
    full_hash_v1 = v1.json()["current_version"]["content_hash"]

    v2 = client.patch(
        f"/api/v1/knowledge-assets/{asset_id}",
        headers=_headers(owner_csrf, "k1-public-question-update-01"),
        json={
            "expected_content_revision": 1,
            "expected_asset_version_seq": 1,
            "content": _question(
                "Explain evaporation.",
                "Evidence",
                "private rubric canary beta",
                reference_answer="private answer canary two",
            ),
        },
    )
    assert v2.status_code == 200, v2.text
    full_hash_v2 = v2.json()["current_version"]["content_hash"]
    assert full_hash_v1 != full_hash_v2

    _peer, _peer_csrf = login(client, "kaikai")
    assets = client.get(f"/api/v1/knowledge-sets/{set_id}/assets")
    assert assets.status_code == 200, assets.text
    student_asset = next(row for row in assets.json() if row["id"] == asset_id)
    assert student_asset["audience"] == "student"
    assert "rubric" not in student_asset["current_version"]["content"]
    assert "reference_answer" not in student_asset["current_version"]["content"]
    assert student_asset["current_version"]["content_hash"] != full_hash_v2

    history = client.get(f"/api/v1/knowledge-assets/{asset_id}/versions")
    assert history.status_code == 200, history.text
    assert history.json()["audience"] == "student"
    assert len(history.json()["versions"]) == 2
    assert all("rubric" not in version["content"] for version in history.json()["versions"])
    assert all(
        "reference_answer" not in version["content"] for version in history.json()["versions"]
    )
    # Rubric-only edits cannot be fingerprinted through ordinary student DTOs.
    assert (
        history.json()["versions"][0]["content_hash"]
        == history.json()["versions"][1]["content_hash"]
    )
    assert "private rubric canary" not in history.text
    assert "private answer canary" not in history.text

    _owner, _owner_csrf = login(client, "bowen")
    owner_asset = client.get(f"/api/v1/knowledge-assets/{asset_id}")
    assert owner_asset.status_code == 200, owner_asset.text
    assert (
        owner_asset.json()["current_version"]["content"]["rubric"]["criteria"][0]["guidance"]
        == "private rubric canary beta"
    )
    assert (
        owner_asset.json()["current_version"]["content"]["reference_answer"]
        == "private answer canary two"
    )
    assert owner_asset.json()["current_version"]["content_hash"] == full_hash_v2


def test_private_asset_requires_owner_save_after_public_set_before_group_can_read(
    client: TestClient, database: Any
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        owner_csrf,
        "Private-first question bank",
        group_id=GROUP_ID,
        key="k1-private-first-set-create-01",
    )
    set_id = knowledge_set["id"]
    source = _upload_source(
        client,
        owner_csrf,
        visibility="public",
        content="Water freezes at zero degrees.",
        filename="water-cycle.md",
        key="k1-private-first-source-upload-01",
    )
    bound = client.put(
        f"/api/v1/knowledge-sets/{set_id}/sources",
        headers=_headers(owner_csrf, "k1-private-first-source-bind-01"),
        json={"expected_content_revision": 0, "source_document_ids": [source["id"]]},
    )
    assert bound.status_code == 200, bound.text
    binding_id = bound.json()["sources"][0]["id"]
    with database.session() as db:
        document = db.get(KnowledgeDocument, source["id"])
        binding_row = db.get(KnowledgeSetSource, binding_id)
        assert document is not None and binding_row is not None
        # A nonzero current source epoch can encode earlier privacy changes.
        document.authorization_epoch = 4
        binding_row.source_authorization_epoch = 4
        db.commit()
    owner_source_projection = client.get(f"/api/v1/knowledge-sets/{set_id}")
    assert owner_source_projection.status_code == 200, owner_source_projection.text
    assert owner_source_projection.json()["sources"][0]["authorization_epoch"] == 4

    private_content = _question(
        "Private prompt canary",
        "Reasoning",
        "Private rubric canary",
        reference_answer="Private answer canary",
    )
    private_content["citations"] = [
        {
            "source_binding_id": binding_id,
            "location": {"start_offset": 0, "end_offset": 13},
        }
    ]
    v1 = client.post(
        f"/api/v1/knowledge-sets/{set_id}/assets",
        headers=_headers(owner_csrf, "k1-private-first-v1-save-0001"),
        json={"expected_content_revision": 1, "content": private_content},
    )
    assert v1.status_code == 201, v1.text
    asset_id = v1.json()["id"]
    private_created_at = v1.json()["created_at"]

    made_public = client.patch(
        f"/api/v1/knowledge-sets/{set_id}",
        headers=_headers(owner_csrf, "k1-private-first-share-0001"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert made_public.status_code == 200, made_public.text
    assert made_public.json()["asset_count"] == 1

    _peer, _peer_csrf = login(client, "kaikai")
    peer_detail = client.get(f"/api/v1/knowledge-sets/{set_id}")
    assert peer_detail.status_code == 200, peer_detail.text
    assert peer_detail.json()["asset_count"] == 0
    assert peer_detail.json()["metadata_revision"] is None
    assert peer_detail.json()["content_revision"] is None
    assert peer_detail.json()["authorization_epoch"] is None
    assert peer_detail.json()["owner_user_id"] is None
    assert peer_detail.json()["created_at"] is None
    assert peer_detail.json()["updated_at"] is None
    assert peer_detail.json()["sources"][0]["available"] is True
    assert peer_detail.json()["sources"][0]["source_filename"] == "water-cycle.md"
    assert peer_detail.json()["sources"][0]["authorization_epoch"] is None
    peer_assets = client.get(f"/api/v1/knowledge-sets/{set_id}/assets")
    assert peer_assets.status_code == 200, peer_assets.text
    assert peer_assets.json() == []
    assert client.get(f"/api/v1/knowledge-assets/{asset_id}").status_code == 404
    assert client.get(f"/api/v1/knowledge-assets/{asset_id}/versions").status_code == 404

    _owner, owner_csrf = login(client, "bowen")
    owner_history = client.get(f"/api/v1/knowledge-assets/{asset_id}/versions")
    assert owner_history.status_code == 200, owner_history.text
    assert [row["version_seq"] for row in owner_history.json()["versions"]] == [1]

    public_content = _question(
        "Public prompt after explicit save",
        "Reasoning",
        "Owner rubric remains private",
        reference_answer="Owner reference answer remains private",
    )
    public_content["citations"] = private_content["citations"]
    v2 = client.patch(
        f"/api/v1/knowledge-assets/{asset_id}",
        headers=_headers(owner_csrf, "k1-private-first-v2-save-0001"),
        json={
            "expected_content_revision": 2,
            "expected_asset_version_seq": 1,
            "content": public_content,
        },
    )
    assert v2.status_code == 200, v2.text
    assert v2.json()["current_version_seq"] == 2
    assert v2.json()["current_version"]["version_seq"] == 2
    owner_asset = client.get(f"/api/v1/knowledge-assets/{asset_id}")
    assert owner_asset.status_code == 200, owner_asset.text
    assert owner_asset.json()["created_at"].removesuffix("Z") == private_created_at.removesuffix(
        "Z"
    )

    _peer, _peer_csrf = login(client, "kaikai")
    shared_detail = client.get(f"/api/v1/knowledge-sets/{set_id}")
    assert shared_detail.status_code == 200, shared_detail.text
    assert shared_detail.json()["asset_count"] == 1
    assert shared_detail.json()["content_revision"] is None
    shared_asset = client.get(f"/api/v1/knowledge-assets/{asset_id}")
    assert shared_asset.status_code == 200, shared_asset.text
    projected = shared_asset.json()
    assert projected["audience"] == "student"
    assert projected["current_version_seq"] is None
    assert projected["current_version"]["version_seq"] is None
    assert projected["created_at"] is None
    assert projected["updated_at"] == projected["current_version"]["created_at"]
    assert projected["current_version"]["content"]["prompt"] == public_content["prompt"]
    assert "reference_answer" not in projected["current_version"]["content"]
    assert "rubric" not in projected["current_version"]["content"]
    visible_history = client.get(f"/api/v1/knowledge-assets/{asset_id}/versions")
    assert visible_history.status_code == 200, visible_history.text
    assert visible_history.json()["audience"] == "student"
    assert len(visible_history.json()["versions"]) == 1
    assert visible_history.json()["versions"][0]["version_seq"] is None
    assert "Private prompt canary" not in visible_history.text
    assert "Private rubric canary" not in visible_history.text
    assert "Private answer canary" not in visible_history.text


def test_public_set_and_source_disappear_for_peer_when_source_access_is_revoked(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        owner_csrf,
        "Revocable source Set",
        group_id=GROUP_ID,
        key="k1-revoked-source-set-create-01",
    )
    source = _upload_source(
        client,
        owner_csrf,
        visibility="public",
        content="A source that can later be withdrawn.",
        key="k1-revoked-source-upload-001",
    )
    bound = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(owner_csrf, "k1-revoked-source-bind-0001"),
        json={"expected_content_revision": 0, "source_document_ids": [source["id"]]},
    )
    assert bound.status_code == 200, bound.text
    binding_id = bound.json()["sources"][0]["id"]
    shared = client.patch(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}",
        headers=_headers(owner_csrf, "k1-revoked-source-share-0001"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert shared.status_code == 200, shared.text

    _peer, _peer_csrf = login(client, "kaikai")
    peer_sets = client.get(f"/api/v1/courses/{COURSE_ID}/knowledge-sets")
    assert peer_sets.status_code == 200, peer_sets.text
    assert peer_sets.json()[0]["source_count"] == 1
    assert client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}").status_code == 200

    _owner, owner_csrf = login(client, "bowen")
    withdrawn = client.patch(
        f"/api/v1/knowledge-documents/{source['id']}",
        headers=_headers(owner_csrf, "k1-revoked-source-withdraw-01"),
        json={"expected_authorization_epoch": 0, "visibility": "private"},
    )
    assert withdrawn.status_code == 200, withdrawn.text

    _peer, _peer_csrf = login(client, "kaikai")
    peer_sets = client.get(f"/api/v1/courses/{COURSE_ID}/knowledge-sets")
    assert peer_sets.status_code == 200, peer_sets.text
    assert peer_sets.json() == []
    assert client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}/download").status_code == 404

    _owner, owner_csrf = login(client, "bowen")
    owner_detail = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}")
    assert owner_detail.status_code == 200, owner_detail.text
    assert owner_detail.json()["source_count"] == 1
    unavailable_source = owner_detail.json()["sources"][0]
    assert unavailable_source["id"] == binding_id
    assert unavailable_source["available"] is False
    assert unavailable_source["source_filename"] is None
    assert unavailable_source["content_hash"] is None

    removed = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources/{binding_id}",
        headers=_headers(owner_csrf, "k1-revoked-source-unbind-001"),
        json={"expected_content_revision": 1},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["source_count"] == 0

    _peer, _peer_csrf = login(client, "kaikai")
    peer_sets = client.get(f"/api/v1/courses/{COURSE_ID}/knowledge-sets")
    assert peer_sets.status_code == 200, peer_sets.text
    assert peer_sets.json()[0]["source_count"] == 0


def test_private_set_and_source_link_to_owner_public_agent_never_leak_to_peer(
    client: TestClient,
) -> None:
    _owner, owner_csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        owner_csrf,
        "Owner only Set",
        group_id=GROUP_ID,
        key="k1-private-set-create-0001",
    )
    uploaded = _upload_source(
        client,
        owner_csrf,
        visibility="private",
        content="# Private lesson\n\nsource body canary",
        filename="private-lesson.md",
        key="k1-private-source-upload-001",
    )
    source_update = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(owner_csrf, "k1-private-source-bind-0001"),
        json={
            "expected_content_revision": 0,
            "source_document_ids": [uploaded["id"]],
        },
    )
    assert source_update.status_code == 200, source_update.text
    source_binding_id = source_update.json()["sources"][0]["id"]
    question = client.post(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/assets",
        headers=_headers(owner_csrf, "k1-private-question-create-01"),
        json={
            "expected_content_revision": 1,
            "content": {
                "kind": "question",
                "prompt": "Owner private question",
                "concept_ids": [],
                "citations": [
                    {
                        "source_binding_id": source_binding_id,
                        "location": {"start_offset": 0, "end_offset": 8},
                    }
                ],
                "rubric": {
                    "criteria": [
                        {
                            "label": "Private grading",
                            "guidance": "private rubric canary",
                            "points": 1,
                        }
                    ],
                    "total_points": 1,
                },
            },
        },
    )
    assert question.status_code == 201, question.text

    agent_response = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(owner_csrf, "k1-owner-public-agent-create-01"),
        json={"name": "Owner public Agent", "visibility": "public"},
    )
    assert agent_response.status_code == 201, agent_response.text
    agent_id = agent_response.json()["id"]
    linked = client.put(
        f"/api/v1/agents/{agent_id}/knowledge-sets",
        headers=_headers(owner_csrf, "k1-owner-private-set-link-01"),
        json={
            "expected_agent_metadata_revision": agent_response.json()["metadata_revision"],
            "set_ids": [knowledge_set["id"]],
        },
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["sets"][0]["id"] == knowledge_set["id"]

    _peer, _peer_csrf = login(client, "kaikai")
    visible_agent_sets = client.get(f"/api/v1/agents/{agent_id}/knowledge-sets")
    assert visible_agent_sets.status_code == 200, visible_agent_sets.text
    assert visible_agent_sets.json()["sets"] == []
    assert "private-lesson.md" not in visible_agent_sets.text
    assert "private rubric canary" not in visible_agent_sets.text
    assert client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-assets/{question.json()['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-documents/{uploaded['id']}/download").status_code == 404


def test_personal_set_redacts_revoked_group_source_and_allows_owner_unbind(
    client: TestClient,
    database: Any,
) -> None:
    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(
        f"/api/v1/groups/{GROUP_ID}/membership",
        headers=_headers(teacher_csrf),
    )
    assert joined.status_code == 200, joined.text

    _student, student_csrf = login(client, "bowen")
    uploaded = _upload_source(
        client,
        student_csrf,
        visibility="public",
        content="# Public lesson\n\npublic body for citation",
        filename="shared-lesson.md",
        key="k1-shared-source-upload-01",
    )

    _teacher, teacher_csrf = login(client, "maya")
    knowledge_set = _create_set(
        client,
        teacher_csrf,
        "Teacher personal Set",
        key="k1-personal-derived-set-01",
    )
    bound = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(teacher_csrf, "k1-personal-group-source-bind-01"),
        json={"expected_content_revision": 0, "source_document_ids": [uploaded["id"]]},
    )
    assert bound.status_code == 200, bound.text
    source_binding_id = bound.json()["sources"][0]["id"]
    assert bound.json()["sources"][0]["available"] is True
    note = client.post(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/assets",
        headers=_headers(teacher_csrf, "k1-derived-note-create-0001"),
        json={
            "expected_content_revision": 1,
            "content": {
                "kind": "note",
                "title": "Derived note",
                "body": "Only usable while source access remains.",
                "citations": [
                    {
                        "source_binding_id": source_binding_id,
                        "location": {"start_offset": 0, "end_offset": 8},
                    }
                ],
            },
        },
    )
    assert note.status_code == 201, note.text
    asset_id = note.json()["id"]

    # A Teacher who leaves the Group retains the personal Set but loses the
    # binding authorization even though the raw source is still Public.
    with database.session() as db:
        row = db.get(TeacherGroupAccess, {"group_id": GROUP_ID, "user_id": MAYA_ID})
        assert row is not None
        db.delete(row)
        db.commit()

    _teacher, teacher_csrf = login(client, "maya")
    detail = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}")
    assert detail.status_code == 200, detail.text
    redacted = detail.json()["sources"][0]
    assert redacted["id"] == source_binding_id
    assert redacted["available"] is False
    assert redacted["document_id"] is None
    assert redacted["source_filename"] is None
    assert redacted["content_hash"] is None
    assert client.get(f"/api/v1/knowledge-assets/{asset_id}").status_code == 404

    stale_save = client.patch(
        f"/api/v1/knowledge-assets/{asset_id}",
        headers=_headers(teacher_csrf, "k1-derived-note-stale-save-01"),
        json={
            "expected_content_revision": 2,
            "expected_asset_version_seq": 1,
            "content": {
                "kind": "note",
                "title": "Derived note",
                "body": "Updated after permission change.",
                "citations": [
                    {
                        "source_binding_id": source_binding_id,
                        "location": {"start_offset": 0, "end_offset": 8},
                    }
                ],
            },
        },
    )
    assert stale_save.status_code == 422, stale_save.text
    assert stale_save.json()["code"] == "knowledge_source_access_changed"

    removed = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources/{source_binding_id}",
        headers=_headers(teacher_csrf, "k1-stale-source-unbind-01"),
        json={"expected_content_revision": 2},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["sources"] == []


def test_excerpt_hash_matches_frozen_source_and_unverified_locations_are_rejected(
    client: TestClient,
) -> None:
    _owner, csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        csrf,
        "Verified citation Set",
        group_id=GROUP_ID,
        key="k1-excerpt-set-create-001",
    )
    source = _upload_source(
        client,
        csrf,
        visibility="private",
        content="Water freezes at zero degrees.\n",
        key="k1-excerpt-source-upload-001",
    )
    bound = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(csrf, "k1-excerpt-source-bind-0001"),
        json={"expected_content_revision": 0, "source_document_ids": [source["id"]]},
    )
    assert bound.status_code == 200, bound.text
    binding_id = bound.json()["sources"][0]["id"]

    def save_note(key: str, location: dict[str, Any]):
        return client.post(
            f"/api/v1/knowledge-sets/{knowledge_set['id']}/assets",
            headers=_headers(csrf, key),
            json={
                "expected_content_revision": 1,
                "content": {
                    "kind": "note",
                    "title": "Water fact",
                    "body": "Water freezes.",
                    "citations": [{"source_binding_id": binding_id, "location": location}],
                },
            },
        )

    location = {
        "start_offset": 0,
        "end_offset": 13,
        "excerpt_hash": hashlib.sha256(b"Water freezes").hexdigest(),
    }
    fake_path = save_note(
        "k1-excerpt-fake-path-0001",
        {**location, "excerpt_hash": None, "section_path": ["Never existed"]},
    )
    assert fake_path.status_code == 422, fake_path.text
    assert fake_path.json()["code"] == "knowledge_source_location_unverified"
    fake_paragraph = save_note(
        "k1-excerpt-fake-para-0001",
        {**location, "excerpt_hash": None, "paragraph_index": 12345},
    )
    assert fake_paragraph.status_code == 422, fake_paragraph.text
    assert fake_paragraph.json()["code"] == "knowledge_source_location_unverified"
    fake_excerpt = save_note(
        "k1-excerpt-fake-hash-0001",
        {**location, "excerpt_hash": "0" * 64},
    )
    assert fake_excerpt.status_code == 422, fake_excerpt.text
    assert fake_excerpt.json()["code"] == "knowledge_source_excerpt_mismatch"

    verified = save_note("k1-excerpt-valid-save-0001", location)
    assert verified.status_code == 201, verified.text


def test_source_epoch_refresh_keeps_old_asset_version_and_rejects_bad_start_offset(
    client: TestClient,
    database: Any,
) -> None:
    _owner, csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        csrf,
        "Source refresh Set",
        group_id=GROUP_ID,
        key="k1-source-refresh-set-001",
    )
    source = _upload_source(
        client,
        csrf,
        visibility="private",
        content="# Segment\n\nSmall source body.",
        filename="segment.md",
        key="k1-source-refresh-upload-001",
    )
    bound = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(csrf, "k1-source-refresh-bind-0001"),
        json={"expected_content_revision": 0, "source_document_ids": [source["id"]]},
    )
    assert bound.status_code == 200, bound.text
    old_binding_id = bound.json()["sources"][0]["id"]
    note = client.post(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/assets",
        headers=_headers(csrf, "k1-source-refresh-note-create-01"),
        json={
            "expected_content_revision": 1,
            "content": {
                "kind": "note",
                "title": "Referenced note",
                "body": "Immutable note body.",
                "citations": [
                    {
                        "source_binding_id": old_binding_id,
                        "location": {"start_offset": 0, "end_offset": 9},
                    }
                ],
            },
        },
    )
    assert note.status_code == 201, note.text
    version_before = note.json()["current_version"]

    with database.session() as db:
        document = db.get(KnowledgeDocument, source["id"])
        assert document is not None
        document.authorization_epoch += 1
        db.commit()

    refreshed = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/sources",
        headers=_headers(csrf, "k1-source-refresh-same-doc-01"),
        json={"expected_content_revision": 2, "source_document_ids": [source["id"]]},
    )
    assert refreshed.status_code == 200, refreshed.text
    new_binding_id = refreshed.json()["sources"][0]["id"]
    assert new_binding_id != old_binding_id
    with database.session() as db:
        bindings = (
            db.query(KnowledgeSetSource)
            .filter(KnowledgeSetSource.knowledge_set_id == knowledge_set["id"])
            .all()
        )
        assert len(bindings) == 2
        assert {row.id: row.is_active for row in bindings} == {
            old_binding_id: False,
            new_binding_id: True,
        }
        version_source = (
            db.query(KnowledgeAssetVersionSource)
            .filter(KnowledgeAssetVersionSource.asset_version_id == version_before["id"])
            .one()
        )
        assert version_source.source_binding_id == old_binding_id
        immutable_version = db.get(KnowledgeAssetVersion, version_before["id"])
        assert immutable_version is not None
        assert immutable_version.content_hash == version_before["content_hash"]

    bad_location = client.post(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}/assets",
        headers=_headers(csrf, "k1-invalid-source-location-01"),
        json={
            "expected_content_revision": 3,
            "content": {
                "kind": "note",
                "title": "Bad location",
                "body": "Unbounded prose is allowed.",
                "citations": [
                    {
                        "source_binding_id": new_binding_id,
                        "location": {"start_offset": source["char_count"] + 1},
                    }
                ],
            },
        },
    )
    assert bad_location.status_code == 422, bad_location.text
    assert bad_location.json()["code"] == "knowledge_source_location_invalid"
    with database.session() as db:
        assert db.get(KnowledgeSet, knowledge_set["id"]).content_revision == 3


def test_knowledge_set_group_course_composite_foreign_key_and_personal_null_group(
    client: TestClient,
    database: Any,
) -> None:
    del client
    wrong_course_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Course(id=wrong_course_id, code=f"k1-{uuid4()}", name="Other Course", created_at=now)
        )
        db.flush()
        invalid = KnowledgeSet(
            id=str(uuid4()),
            owner_user_id=BOWEN_ID,
            course_id=wrong_course_id,
            group_id=GROUP_ID,
            ownership_scope="group",
            visibility="private",
            display_name="Mismatched scope",
            metadata_revision=0,
            content_revision=0,
            authorization_epoch=0,
            created_at=now,
            updated_at=now,
        )
        db.add(invalid)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    with database.session() as db:
        valid_personal = KnowledgeSet(
            id=str(uuid4()),
            owner_user_id=MAYA_ID,
            course_id=COURSE_ID,
            group_id=None,
            ownership_scope="personal",
            visibility="private",
            display_name="Personal null group",
            metadata_revision=0,
            content_revision=0,
            authorization_epoch=0,
            created_at=now,
            updated_at=now,
        )
        db.add(valid_personal)
        db.flush()
        assert db.get(KnowledgeSet, valid_personal.id) is not None


def test_set_revocation_is_soft_cas_idempotent_and_blocks_late_writes(
    client: TestClient, database: Any
) -> None:
    _teacher, csrf = login(client, "maya")
    create_key = "k1-revoke-create-set-0001"
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, create_key),
        json={"display_name": "Retained course notes"},
    )
    assert created.status_code == 201, created.text
    set_row = created.json()
    asset = client.post(
        f"/api/v1/knowledge-sets/{set_row['id']}/assets",
        headers=_headers(csrf, "k1-revoke-retained-asset-01"),
        json={
            "expected_content_revision": 0,
            "content": {
                "kind": "note",
                "title": "Historical note",
                "body": "This remains immutable after revocation.",
                "citations": [],
            },
        },
    )
    assert asset.status_code == 201, asset.text
    deletion_body = {
        "expected_metadata_revision": 0,
        "expected_content_revision": 1,
    }
    deleted = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_row['id']}",
        headers=_headers(csrf, "k1-revoke-set-idempotency-01"),
        json=deletion_body,
    )
    assert deleted.status_code == 200, deleted.text
    receipt = deleted.json()
    assert receipt["deleted"] is True
    assert receipt["metadata_revision"] == 1
    assert receipt["content_revision"] == 2
    assert receipt["authorization_epoch"] == 1

    replayed = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_row['id']}",
        headers=_headers(csrf, "k1-revoke-set-idempotency-01"),
        json=deletion_body,
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == receipt
    assert client.get(f"/api/v1/knowledge-sets/{set_row['id']}").status_code == 404
    assert (
        client.post(
            f"/api/v1/knowledge-sets/{set_row['id']}/assets",
            headers=_headers(csrf, "k1-revoke-late-write-0001"),
            json={
                "expected_content_revision": 2,
                "content": {
                    "kind": "note",
                    "title": "Late",
                    "body": "",
                    "citations": [],
                },
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
            headers=_headers(csrf, create_key),
            json={"display_name": "Retained course notes"},
        ).status_code
        == 404
    )

    with database.session() as db:
        assert db.get(KnowledgeSet, set_row["id"]) is not None
        assert db.query(KnowledgeAssetVersion).filter_by(asset_id=asset.json()["id"]).count() == 1

    _peer, peer_csrf = login(client, "bowen")
    peer_delete = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_row['id']}",
        headers=_headers(peer_csrf, "k1-revoke-guessed-private-01"),
        json=deletion_body,
    )
    assert peer_delete.status_code == 404


def test_student_owned_agent_can_use_same_owner_personal_knowledge_set(
    client: TestClient,
) -> None:
    _student, csrf = login(client, "bowen")
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, "k1-student-set-create-0001"),
        json={"display_name": "Student study notes"},
    )
    assert created_set.status_code == 201, created_set.text
    student_set = created_set.json()

    created_agent = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf, "k1-student-agent-create-0001"),
        json={"name": "Student Study Agent", "visibility": "private"},
    )
    assert created_agent.status_code == 201, created_agent.text
    agent = created_agent.json()

    linked = client.put(
        f"/api/v1/agents/{agent['id']}/knowledge-sets",
        headers=_headers(csrf, "k1-student-agent-set-bind-01"),
        json={
            "expected_agent_metadata_revision": agent["metadata_revision"],
            "set_ids": [student_set["id"]],
        },
    )
    assert linked.status_code == 200, linked.text
    assert [row["id"] for row in linked.json()["sets"]] == [student_set["id"]]

    read_back = client.get(f"/api/v1/agents/{agent['id']}/knowledge-sets")
    assert read_back.status_code == 200, read_back.text
    assert [row["id"] for row in read_back.json()["sets"]] == [student_set["id"]]
