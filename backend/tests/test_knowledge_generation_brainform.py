from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from app.core.models import Agent, KnowledgeDocument
from app.modules.knowledge_sets.generation import (
    _current_generation_authorized,
    claim_generation_run,
    enqueue_generation_for_existing_set,
)
from app.modules.knowledge_sets.materialization import (
    _render_asset_versions,
    materialize_accepted_knowledge_generation,
)
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeDocumentVersion,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.provider_runtime import _generation_input
from app.modules.knowledge_sets.schemas import QuestionContent
from app.modules.learning.recipes import current_question_version_for_asset
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import login
from tests.test_knowledge_generation import _publish, _teacher_agent_with_source
from tests.test_knowledge_generation_materialization import (
    _accept_stage,
    _create_generation_run,
    _run_claim,
)
from tests.test_knowledge_sets import _upload_source

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


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
    key: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"display_name": name}
    if group_id is not None:
        body["group_id"] = group_id
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, key or f"k3-brainform-set-{uuid4()}"),
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_agent_and_bind(
    client: TestClient,
    csrf: str,
    set_id: str,
    *,
    name: str,
    visibility: str = "private",
) -> dict[str, Any]:
    created = client.post(
        f"/api/v1/groups/{GROUP_ID}/agents",
        headers=_headers(csrf, f"k3-brainform-agent-{uuid4()}"),
        json={"name": name, "visibility": visibility},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    bound = client.put(
        f"/api/v1/agents/{agent['id']}/knowledge-sets",
        headers=_headers(csrf, f"k3-brainform-bind-{uuid4()}"),
        json={
            "expected_agent_metadata_revision": agent["metadata_revision"],
            "set_ids": [set_id],
        },
    )
    assert bound.status_code == 200, bound.text
    return agent


def _save(
    client: TestClient,
    csrf: str,
    set_id: str,
    markdown: str,
    *,
    expected_version_seq: int = 0,
    key: str | None = None,
) -> Any:
    return client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(csrf, key or f"k3-brainform-save-{uuid4()}"),
        json={"expected_version_seq": expected_version_seq, "markdown": markdown},
    )


def test_brainform_keeps_failed_first_generation_visible_and_markdown_lossless(
    client: TestClient, database: Any
) -> None:
    _agent_id, _document_id, run_id, set_id = _create_generation_run(client, database)
    pending = client.get(f"/api/v1/courses/{COURSE_ID}/brainform/knowledge")
    assert pending.status_code == 200, pending.text
    row = next(item for item in pending.json() if item["canonical_set_id"] == set_id)
    assert row["generation_state"] == "pending"
    assert row["version_seq"] is None
    assert row["can_read"] is True and row["can_edit"] is True
    assert client.get(f"/api/v1/knowledge-sets/{set_id}/markdown").status_code == 404

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        run.state = "failed"
        run.safe_error_code = "knowledge_generation_no_assets"

    failed = client.get(f"/api/v1/courses/{COURSE_ID}/brainform/knowledge")
    failed_row = next(item for item in failed.json() if item["canonical_set_id"] == set_id)
    assert failed_row["generation_state"] == "failed"
    assert failed_row["safe_error_code"] == "knowledge_generation_no_assets"
    assert client.get(f"/api/v1/knowledge-sets/{set_id}/markdown").status_code == 404

    markdown = (
        "# Raw teacher document\n\n"
        "A paragraph with **formatting**, a table, and an arbitrary HTML tag: <em>kept</em>.\n\n"
        "| left | right |\n| --- | --- |\n| original | unchanged |\n"
    )
    save_key = "k3-brainform-lossless-save-0001"
    saved = _save(client, login(client, "maya")[1], set_id, markdown, key=save_key)
    assert saved.status_code == 200, saved.text
    assert saved.json()["markdown"] == markdown
    assert saved.json()["audience"] == "full"
    assert saved.json()["version_seq"] == 1
    replay = _save(client, login(client, "maya")[1], set_id, markdown, key=save_key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["version_seq"] == 1
    assert replay.json()["markdown"] == markdown
    current = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert current.status_code == 200
    assert current.json()["markdown"] == markdown
    assert current.json()["content_hash"] == saved.json()["content_hash"]
    assert current.json()["can_edit"] is True

    peer, _peer_csrf = login(client, "bowen")
    assert peer
    assert client.get(f"/api/v1/knowledge-sets/{set_id}/markdown").status_code == 404
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/brainform/knowledge")
    assert listed.status_code == 200
    assert all(item["canonical_set_id"] != set_id for item in listed.json())


def test_student_private_knowledge_is_full_but_manual_public_markdown_fails_closed(
    client: TestClient,
) -> None:
    _student, student_csrf = login(client, "bowen")
    private_set = _create_set(client, student_csrf, "My private study guide")
    _create_agent_and_bind(
        client,
        student_csrf,
        private_set["id"],
        name="My private study agent",
    )
    private_markdown = "# Private study\n\nMy own complete notes and answers.\n"
    saved_private = _save(client, student_csrf, private_set["id"], private_markdown)
    assert saved_private.status_code == 200, saved_private.text
    assert saved_private.json()["audience"] == "full"
    assert saved_private.json()["can_edit"] is True
    assert saved_private.json()["markdown"] == private_markdown

    public_set = _create_set(
        client,
        student_csrf,
        "Group question guide",
        group_id=GROUP_ID,
    )
    share = client.patch(
        f"/api/v1/knowledge-sets/{public_set['id']}",
        headers=_headers(student_csrf, f"k3-brainform-share-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert share.status_code == 200, share.text
    first_public_agent = _create_agent_and_bind(
        client,
        student_csrf,
        public_set["id"],
        name="Public group question agent",
        visibility="public",
    )
    second_public_agent = _create_agent_and_bind(
        client,
        student_csrf,
        public_set["id"],
        name="Another Agent using the same Knowledge",
        visibility="public",
    )
    full_markdown = (
        "# Group study\n\n"
        "## Questions\n\n"
        "### Why does rain form?\n\n"
        "Explain the water cycle in your own words.\n\n"
        "#### Reference answer\n\n"
        "REFERENCE_ANSWER_SECRET\n\n"
        "#### Rubric\n\n"
        "RUBRIC_SECRET\n\n"
        "## Extra notes\n\n"
        "<script>STUDENT_HTML_CANARY</script>\n"
    )
    saved_public = _save(client, student_csrf, public_set["id"], full_markdown)
    assert saved_public.status_code == 200, saved_public.text
    assert saved_public.json()["audience"] == "full"
    assert saved_public.json()["markdown"] == full_markdown

    peer, _peer_csrf = login(client, "kaikai")
    assert peer
    listing = client.get(f"/api/v1/courses/{COURSE_ID}/brainform/knowledge")
    assert listing.status_code == 200, listing.text
    listed = [item for item in listing.json() if item["canonical_set_id"] == public_set["id"]]
    assert {item["agent_id"] for item in listed} == {
        first_public_agent["id"],
        second_public_agent["id"],
    }
    assert {item["source_agent_display_name"] for item in listed} == {
        "Public group question agent",
        "Another Agent using the same Knowledge",
    }
    assert all(item["can_read"] is True and item["can_edit"] is False for item in listed)
    assert all(item["version_seq"] == 1 for item in listed)
    projected = client.get(f"/api/v1/knowledge-sets/{public_set['id']}/markdown")
    assert projected.status_code == 200, projected.text
    assert projected.json()["audience"] == "student"
    assert projected.json()["can_edit"] is False
    assert projected.json()["projection_available"] is False
    assert projected.json()["markdown"] == ""
    assert "REFERENCE_ANSWER_SECRET" not in projected.text
    assert "RUBRIC_SECRET" not in projected.text
    assert "STUDENT_HTML_CANARY" not in projected.text
    assert projected.json()["content_hash"] == hashlib.sha256(b"").hexdigest()
    assert client.get(f"/api/v1/knowledge-sets/{private_set['id']}/markdown").status_code == 404

    changed_heading = full_markdown.replace("## Questions", "## Problem set")
    _owner, owner_csrf = login(client, "bowen")
    renamed = _save(
        client,
        owner_csrf,
        public_set["id"],
        changed_heading,
        expected_version_seq=1,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["markdown"] == changed_heading
    peer, _peer_csrf = login(client, "kaikai")
    assert peer
    fail_closed = client.get(f"/api/v1/knowledge-sets/{public_set['id']}/markdown")
    assert fail_closed.status_code == 200, fail_closed.text
    assert fail_closed.json()["version_seq"] == 2
    assert fail_closed.json()["projection_available"] is False
    assert fail_closed.json()["markdown"] == ""
    assert "REFERENCE_ANSWER_SECRET" not in fail_closed.text
    assert "RUBRIC_SECRET" not in fail_closed.text
    listed = client.get(f"/api/v1/courses/{COURSE_ID}/brainform/knowledge")
    assert listed.status_code == 200
    current_row = next(
        item for item in listed.json() if item["canonical_set_id"] == public_set["id"]
    )
    assert current_row["version_seq"] == 2
    assert current_row["content_hash"] is None


def test_brainform_student_projection_uses_trusted_typed_asset_versions(
    client: TestClient, database: Any
) -> None:
    _owner, csrf = login(client, "bowen")
    row = _create_set(client, csrf, "Typed question bank", group_id=GROUP_ID)
    shared = client.patch(
        f"/api/v1/knowledge-sets/{row['id']}",
        headers=_headers(csrf, f"k3-bf-typed-share-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert shared.status_code == 200, shared.text
    _create_agent_and_bind(
        client,
        csrf,
        row["id"],
        name="Typed question agent",
        visibility="public",
    )
    saved_asset = client.post(
        f"/api/v1/knowledge-sets/{row['id']}/assets",
        headers=_headers(csrf, f"k3-bf-typed-question-{uuid4()}"),
        json={
            "expected_content_revision": 0,
            "content": {
                "kind": "question",
                "prompt": "Explain the water cycle.",
                "reference_answer": "TYPED_REFERENCE_SECRET",
                "concept_ids": [],
                "citations": [],
                "rubric": {
                    "criteria": [
                        {
                            "label": "Evidence",
                            "guidance": "TYPED_RUBRIC_SECRET",
                            "points": 2,
                        }
                    ],
                    "total_points": 2,
                },
            },
        },
    )
    assert saved_asset.status_code == 201, saved_asset.text

    from types import SimpleNamespace

    from app.modules.knowledge_sets.service import save_knowledge_markdown_version

    with database.session() as db:
        set_row = db.get(KnowledgeSet, row["id"])
        assert set_row is not None
        asset_id = saved_asset.json()["id"]
        asset_version_id = saved_asset.json()["current_version"]["id"]
        markdown, projection, asset_version_ids = _render_asset_versions(
            db,
            set_row,
            [SimpleNamespace(asset_id=asset_id, asset_version_id=asset_version_id)],
        )
        save_knowledge_markdown_version(
            db,
            set_id=set_row.id,
            expected_version_seq=0,
            markdown=markdown,
            actor_user_id=set_row.owner_user_id,
            origin="legacy",
            asset_version_ids=asset_version_ids,
            student_projection_markdown=projection,
        )

    _peer, _peer_csrf = login(client, "kaikai")
    safe = client.get(f"/api/v1/knowledge-sets/{row['id']}/markdown")
    assert safe.status_code == 200, safe.text
    assert safe.json()["audience"] == "student"
    assert safe.json()["projection_available"] is True
    assert "Explain the water cycle." in safe.json()["markdown"]
    assert "TYPED_REFERENCE_SECRET" not in safe.text
    assert "TYPED_RUBRIC_SECRET" not in safe.text


def test_manual_markdown_question_projection_is_safe_for_public_students_and_owner_full_read(
    client: TestClient,
) -> None:
    _owner, csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        csrf,
        "Manual public assessment",
        group_id=GROUP_ID,
    )
    public = client.patch(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}",
        headers=_headers(csrf, f"k3-manual-question-public-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert public.status_code == 200, public.text
    _create_agent_and_bind(
        client,
        csrf,
        knowledge_set["id"],
        name="Manual assessment Agent",
        visibility="public",
    )
    markdown = (
        "# Manual assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "#### Rubric\n\n"
        "- **Causal model** (2): Explain evaporation and precipitation.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "MANUAL_REFERENCE_SECRET\n"
    )
    saved = _save(client, csrf, knowledge_set["id"], markdown)
    assert saved.status_code == 200, saved.text
    assert saved.json()["markdown"] == markdown

    _peer, _peer_csrf = login(client, "kaikai")
    student = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student.status_code == 200, student.text
    assert student.json()["audience"] == "student"
    assert student.json()["projection_available"] is True
    assert "Explain the water cycle." in student.json()["markdown"]
    assert "Causal model" not in student.text
    assert "evaporation and precipitation" not in student.text
    assert "MANUAL_REFERENCE_SECRET" not in student.text

    _owner, _owner_csrf = login(client, "bowen")
    owner_read = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert owner_read.status_code == 200, owner_read.text
    assert owner_read.json()["audience"] == "full"
    assert owner_read.json()["markdown"] == markdown


def test_unknown_question_headings_fail_closed_and_reference_order_is_bounded(
    client: TestClient, database: Any
) -> None:
    _owner, csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        csrf,
        "Question heading boundary",
        group_id=GROUP_ID,
    )
    public = client.patch(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}",
        headers=_headers(csrf, f"k3-question-boundary-public-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert public.status_code == 200, public.text
    _create_agent_and_bind(
        client,
        csrf,
        knowledge_set["id"],
        name="Question heading boundary Agent",
        visibility="public",
    )
    valid_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): Explain the process.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "VALID_REFERENCE_CANARY\n"
    )
    first = _save(client, csrf, knowledge_set["id"], valid_markdown)
    assert first.status_code == 200, first.text
    with database.session() as db:
        first_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 1,
            )
        )
        assert first_version is not None
        question_version_id = json.loads(first_version.asset_version_ids_json)[0]
        first_asset_version = db.get(KnowledgeAssetVersion, question_version_id)
        assert first_asset_version is not None
        stable_asset_id = first_asset_version.asset_id

    h5_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "##### Reference answer\n\n"
        "H5_REFERENCE_CANARY\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): H5_RUBRIC_CANARY\n\n"
        "Total: 2 points\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_h5 = _save(
        client,
        csrf,
        knowledge_set["id"],
        h5_markdown,
        expected_version_seq=1,
    )
    assert saved_h5.status_code == 200, saved_h5.text
    assert saved_h5.json()["markdown"] == h5_markdown
    _peer, _peer_csrf = login(client, "kaikai")
    student_h5 = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_h5.status_code == 200, student_h5.text
    assert student_h5.json()["projection_available"] is False
    assert student_h5.json()["markdown"] == ""
    assert "H5_REFERENCE_CANARY" not in student_h5.text
    assert "H5_RUBRIC_CANARY" not in student_h5.text
    with database.session() as db:
        set_row = db.get(KnowledgeSet, knowledge_set["id"])
        second_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 2,
            )
        )
        assert set_row is not None and second_version is not None
        assert json.loads(second_version.asset_version_ids_json) == []
        assert current_question_version_for_asset(db, set_row, stable_asset_id) is None
        assert db.get(KnowledgeAssetVersion, question_version_id) is not None

    ref_before_rubric = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "#### Reference answer\n\n"
        "REFERENCE_BEFORE_RUBRIC_CANARY\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): RUBRIC_AFTER_REFERENCE_CANARY\n\n"
        "Total: 2 points\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_ref_first = _save(
        client,
        csrf,
        knowledge_set["id"],
        ref_before_rubric,
        expected_version_seq=2,
    )
    assert saved_ref_first.status_code == 200, saved_ref_first.text
    assert saved_ref_first.json()["markdown"] == ref_before_rubric
    _peer, _peer_csrf = login(client, "kaikai")
    student_ref_first = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_ref_first.status_code == 200, student_ref_first.text
    assert student_ref_first.json()["projection_available"] is True
    assert "Explain the water cycle." in student_ref_first.json()["markdown"]
    assert "REFERENCE_BEFORE_RUBRIC_CANARY" not in student_ref_first.text
    assert "RUBRIC_AFTER_REFERENCE_CANARY" not in student_ref_first.text
    with database.session() as db:
        set_row = db.get(KnowledgeSet, knowledge_set["id"])
        third_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 3,
            )
        )
        assert set_row is not None and third_version is not None
        mapped_version_ids = json.loads(third_version.asset_version_ids_json)
        assert len(mapped_version_ids) == 1
        mapped_question_version = db.get(KnowledgeAssetVersion, mapped_version_ids[0])
        assert mapped_question_version is not None
        assert mapped_question_version.asset_id != stable_asset_id
        mapped_question = QuestionContent.model_validate_json(mapped_question_version.content_json)
        assert mapped_question.reference_answer == "REFERENCE_BEFORE_RUBRIC_CANARY"
        assert mapped_question.rubric.criteria[0].guidance == "RUBRIC_AFTER_REFERENCE_CANARY"
        assert current_question_version_for_asset(db, set_row, stable_asset_id) is None
        assert (
            current_question_version_for_asset(db, set_row, mapped_question_version.asset_id)
            == mapped_question_version
        )
    _owner, _owner_csrf = login(client, "bowen")
    owner = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert owner.status_code == 200, owner.text
    assert owner.json()["markdown"] == ref_before_rubric

    h1_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "# Reference answer\n\n"
        "H1_REFERENCE_CANARY\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): H1_RUBRIC_CANARY\n\n"
        "Total: 2 points\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_h1 = _save(
        client,
        csrf,
        knowledge_set["id"],
        h1_markdown,
        expected_version_seq=3,
    )
    assert saved_h1.status_code == 200, saved_h1.text
    assert saved_h1.json()["markdown"] == h1_markdown
    _peer, _peer_csrf = login(client, "kaikai")
    student_h1 = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_h1.status_code == 200, student_h1.text
    assert student_h1.json()["projection_available"] is False
    assert student_h1.json()["markdown"] == ""
    assert "H1_REFERENCE_CANARY" not in student_h1.text
    assert "H1_RUBRIC_CANARY" not in student_h1.text
    with database.session() as db:
        set_row = db.get(KnowledgeSet, knowledge_set["id"])
        fourth_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 4,
            )
        )
        assert set_row is not None and fourth_version is not None
        assert json.loads(fourth_version.asset_version_ids_json) == []
        assert current_question_version_for_asset(db, set_row, stable_asset_id) is None


def test_setext_heading_boundaries_fail_closed_and_fenced_headings_are_ignored(
    client: TestClient, database: Any
) -> None:
    _owner, csrf = login(client, "bowen")
    knowledge_set = _create_set(
        client,
        csrf,
        "Setext heading boundary",
        group_id=GROUP_ID,
    )
    public = client.patch(
        f"/api/v1/knowledge-sets/{knowledge_set['id']}",
        headers=_headers(csrf, f"k3-setext-public-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert public.status_code == 200, public.text
    _create_agent_and_bind(
        client,
        csrf,
        knowledge_set["id"],
        name="Setext heading boundary Agent",
        visibility="public",
    )

    markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): Explain the process.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "INITIAL_REFERENCE_CANARY\n"
    )
    initial = _save(client, csrf, knowledge_set["id"], markdown)
    assert initial.status_code == 200, initial.text
    with database.session() as db:
        initial_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 1,
            )
        )
        assert initial_version is not None
        initial_question_version_id = json.loads(initial_version.asset_version_ids_json)[0]
        initial_question_version = db.get(KnowledgeAssetVersion, initial_question_version_id)
        assert initial_question_version is not None
        initial_asset_id = initial_question_version.asset_id

    setext_h2_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "Reference answer\n"
        "----------------\n\n"
        "SETEXT_H2_REFERENCE_CANARY\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): Setext section must not become prompt.\n\n"
        "Total: 2 points\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_h2 = _save(
        client,
        csrf,
        knowledge_set["id"],
        setext_h2_markdown,
        expected_version_seq=1,
    )
    assert saved_h2.status_code == 200, saved_h2.text
    assert saved_h2.json()["markdown"] == setext_h2_markdown
    _peer, _peer_csrf = login(client, "kaikai")
    student_h2 = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_h2.status_code == 200, student_h2.text
    assert student_h2.json()["projection_available"] is False
    assert student_h2.json()["markdown"] == ""
    assert "SETEXT_H2_REFERENCE_CANARY" not in student_h2.text
    _owner, _owner_csrf = login(client, "bowen")
    owner_h2 = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert owner_h2.status_code == 200, owner_h2.text
    assert owner_h2.json()["markdown"] == setext_h2_markdown
    with database.session() as db:
        set_row = db.get(KnowledgeSet, knowledge_set["id"])
        second_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 2,
            )
        )
        assert set_row is not None and second_version is not None
        assert json.loads(second_version.asset_version_ids_json) == []
        assert current_question_version_for_asset(db, set_row, initial_asset_id) is None

    setext_h1_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "Private answer\n"
        "===============\n\n"
        "SETEXT_H1_REFERENCE_CANARY\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): Setext H1 is not part of the prompt.\n\n"
        "Total: 2 points\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_h1 = _save(
        client,
        csrf,
        knowledge_set["id"],
        setext_h1_markdown,
        expected_version_seq=2,
    )
    assert saved_h1.status_code == 200, saved_h1.text
    _peer, _peer_csrf = login(client, "kaikai")
    student_h1 = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_h1.status_code == 200, student_h1.text
    assert student_h1.json()["projection_available"] is False
    assert "SETEXT_H1_REFERENCE_CANARY" not in student_h1.text
    with database.session() as db:
        set_row = db.get(KnowledgeSet, knowledge_set["id"])
        third_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 3,
            )
        )
        assert set_row is not None and third_version is not None
        assert json.loads(third_version.asset_version_ids_json) == []
        assert current_question_version_for_asset(db, set_row, initial_asset_id) is None

    fenced_markdown = (
        "# Assessment\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Explain the water cycle.\n\n"
        "```markdown\n"
        "Reference answer\n"
        "----------------\n"
        "FENCED_HEADING_EXAMPLE\n"
        "```\n\n"
        "#### Rubric\n\n"
        "- **Evidence** (2): A real bounded rubric.\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "ACTUAL_REFERENCE_CANARY\n"
    )
    _owner, csrf = login(client, "bowen")
    saved_fenced = _save(
        client,
        csrf,
        knowledge_set["id"],
        fenced_markdown,
        expected_version_seq=3,
    )
    assert saved_fenced.status_code == 200, saved_fenced.text
    _peer, _peer_csrf = login(client, "kaikai")
    student_fenced = client.get(f"/api/v1/knowledge-sets/{knowledge_set['id']}/markdown")
    assert student_fenced.status_code == 200, student_fenced.text
    assert student_fenced.json()["projection_available"] is True
    assert "FENCED_HEADING_EXAMPLE" in student_fenced.json()["markdown"]
    assert "ACTUAL_REFERENCE_CANARY" not in student_fenced.text
    with database.session() as db:
        fourth_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == knowledge_set["id"],
                KnowledgeSetMarkdownVersion.version_seq == 4,
            )
        )
        assert fourth_version is not None
        question_version_id = json.loads(fourth_version.asset_version_ids_json)[0]
        question_version = db.get(KnowledgeAssetVersion, question_version_id)
        assert question_version is not None
        question = QuestionContent.model_validate_json(question_version.content_json)
        assert question_version.id != initial_question_version_id
        assert "FENCED_HEADING_EXAMPLE" in question.prompt
        assert question.reference_answer == "ACTUAL_REFERENCE_CANARY"
        assert question.rubric.criteria[0].guidance == "A real bounded rubric."


def test_owner_typed_question_survives_source_reauthorization_and_content_replace(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, document_id, _initial_run_id, set_id = _create_generation_run(client, database)
    _teacher, csrf = login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        initial_hash = document.content_hash
        initial_index_revision = document.index_revision
    primed = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-history-prime-{uuid4()}"),
        data={
            "expected_content_hash": initial_hash,
            "expected_index_revision": str(initial_index_revision),
        },
        files={
            "file": (
                "lesson-v1.md",
                b"# Existing courseware\n\nSaved before reauthorization.",
                "text/markdown",
            )
        },
    )
    assert primed.status_code == 201, primed.text
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        previous_epoch = document.authorization_epoch
        previous_visibility = document.visibility
    reauthorized = client.patch(
        f"/api/v1/knowledge-documents/{document_id}",
        headers=_headers(csrf),
        json={
            "expected_authorization_epoch": previous_epoch,
            "visibility": "public" if previous_visibility == "private" else "private",
        },
    )
    assert reauthorized.status_code == 200, reauthorized.text
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        content_revision = set_row.content_revision
    rebound = client.put(
        f"/api/v1/knowledge-sets/{set_id}/sources",
        headers=_headers(csrf, f"k3-history-rebind-{uuid4()}"),
        json={
            "expected_content_revision": content_revision,
            "source_document_ids": [document_id],
        },
    )
    assert rebound.status_code == 200, rebound.text
    with database.session() as db:
        run = db.scalar(
            select(KnowledgeGenerationRun)
            .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
            .order_by(KnowledgeGenerationRun.intent_generation.desc())
            .limit(1)
        )
        assert run is not None
        receipt = db.scalar(
            select(KnowledgeGenerationSourceReceipt).where(
                KnowledgeGenerationSourceReceipt.run_id == run.id
            )
        )
        assert receipt is not None
        run_id = run.id
        receipt_id = receipt.id
    from tests.test_mayaform_assessment_attempts import _question_content

    _accept_stage(
        database,
        run_id,
        [
            {
                "content": json.loads(
                    _question_content(
                        "Authorized at the new epoch",
                        "Internal courseware answer.",
                    )
                ),
                "source_receipt_ids": [receipt_id],
                "citation_unverified": False,
            }
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        run_id,
        _run_claim(database, run_id),
        data_root=settings.resolved_data_root,
    )
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        current = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == set_row.current_markdown_version_seq,
            )
        )
        assert current is not None
        current_ids = json.loads(current.asset_version_ids_json)
        question_version = next(
            version
            for version in db.scalars(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(current_ids))
            ).all()
            if db.get(KnowledgeAsset, version.asset_id).kind == "question"
        )
        question_asset = db.get(KnowledgeAsset, question_version.asset_id)
        assert question_asset is not None
        stable_asset_id = question_asset.id
        question_version_id = question_version.id
        reference = db.scalar(
            select(KnowledgeAssetVersionSource).where(
                KnowledgeAssetVersionSource.asset_version_id == question_version_id
            )
        )
        assert reference is not None
        old_file_id = reference.stored_file_id
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        before_hash = document.content_hash
        before_index_revision = document.index_revision
    replaced = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-history-replace-{uuid4()}"),
        data={
            "expected_content_hash": before_hash,
            "expected_index_revision": str(before_index_revision),
        },
        files={
            "file": (
                "lesson-v2.md",
                b"# New courseware\n\nCurrent retrieval content.",
                "text/markdown",
            )
        },
    )
    assert replaced.status_code == 201, replaced.text
    with database.session() as db:
        reference = db.scalar(
            select(KnowledgeAssetVersionSource).where(
                KnowledgeAssetVersionSource.asset_version_id == question_version_id
            )
        )
        history = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document_id,
                KnowledgeDocumentVersion.stored_file_id == old_file_id,
            )
        )
        assert reference is not None and history is not None
        assert history.authorization_epoch != reference.source_authorization_epoch

    source_read = client.get(f"/api/v1/knowledge-documents/{document_id}")
    canonical_read = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    typed_read = client.get(f"/api/v1/knowledge-assets/{stable_asset_id}")
    assert source_read.status_code == 200, source_read.text
    assert canonical_read.status_code == 200, canonical_read.text
    assert typed_read.status_code == 200, typed_read.text


def test_manual_markdown_question_rubric_save_is_current_and_later_ai_overwrites(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, _document_id, first_run_id, set_id = _create_generation_run(client, database)
    _accept_stage(
        database,
        first_run_id,
        [
            {
                "kind": "question",
                "prompt": "Explain why seasons change.",
                "reference_answer": "REFERENCE_ANSWER_CANARY",
                "rubric": {
                    "criteria": [
                        {
                            "label": "Causal reasoning",
                            "guidance": "RUBRIC_GUIDANCE_CANARY",
                            "points": 2,
                        }
                    ],
                    "total_points": 2,
                },
            },
            {
                "kind": "concept",
                "title": "Earth orbit",
                "description": "Earth's orbit is nearly circular.",
            },
            {
                "kind": "note",
                "title": "Study note",
                "body": "The seasons are opposite across hemispheres.",
            },
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        first_run_id,
        _run_claim(database, first_run_id),
        data_root=settings.resolved_data_root,
    )

    _teacher, csrf = login(client, "maya")
    before = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert before.status_code == 200, before.text
    initial_markdown = before.json()["markdown"]
    assert "RUBRIC_GUIDANCE_CANARY" in initial_markdown
    assert "REFERENCE_ANSWER_CANARY" in initial_markdown
    with database.session() as db:
        initial_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == 1,
            )
        )
        assert initial_version is not None
        initial_asset_version_id = json.loads(initial_version.asset_version_ids_json)[0]
        initial_asset_version = db.get(KnowledgeAssetVersion, initial_asset_version_id)
        assert initial_asset_version is not None
        stable_asset_id = initial_asset_version.asset_id

    manual_markdown = initial_markdown.replace(
        "RUBRIC_GUIDANCE_CANARY", "MANUAL_RUBRIC_GUIDANCE"
    ).replace("REFERENCE_ANSWER_CANARY", "MANUAL_REFERENCE_ANSWER")
    saved = _save(
        client,
        csrf,
        set_id,
        manual_markdown,
        expected_version_seq=1,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version_seq"] == 2
    assert saved.json()["markdown"] == manual_markdown

    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        manual_version = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == 2,
            )
        )
        assert set_row is not None and manual_version is not None
        current_version_ids = json.loads(manual_version.asset_version_ids_json)
        assert len(current_version_ids) == 3
        question_versions = []
        for version_id in current_version_ids:
            version = db.get(KnowledgeAssetVersion, version_id)
            asset = db.get(KnowledgeAsset, version.asset_id) if version is not None else None
            if asset is not None and asset.kind == "question":
                question_versions.append(version)
        assert len(question_versions) == 1
        current_asset_version = question_versions[0]
        assert current_asset_version is not None
        assert current_asset_version.asset_id == stable_asset_id
        assert current_asset_version.id != initial_asset_version_id
        assert current_asset_version.version_seq == 2
        current_question = current_question_version_for_asset(db, set_row, stable_asset_id)
        assert current_question is not None and current_question.id == current_asset_version.id
        parsed_current = json.loads(current_question.content_json)
        assert parsed_current["rubric"]["criteria"][0]["guidance"] == "MANUAL_RUBRIC_GUIDANCE"
        assert parsed_current["reference_answer"] == "MANUAL_REFERENCE_ANSWER"
        assert "Explain why seasons change." in manual_version.student_projection_markdown
        assert "Earth's orbit is nearly circular." in manual_version.student_projection_markdown
        assert (
            "The seasons are opposite across hemispheres."
            in manual_version.student_projection_markdown
        )
        assert "MANUAL_RUBRIC_GUIDANCE" not in manual_version.student_projection_markdown
        assert "MANUAL_REFERENCE_ANSWER" not in manual_version.student_projection_markdown
        assert db.get(KnowledgeAssetVersion, initial_asset_version_id) is not None

    action_id = str(uuid4())
    queued = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(csrf, f"k3-question-regenerate-{uuid4()}"),
        json={"action_id": action_id},
    )
    assert queued.status_code == 202, queued.text
    _accept_stage(
        database,
        queued.json()["run_id"],
        [
            {
                "kind": "question",
                "prompt": "Describe the water cycle.",
                "reference_answer": "NEW_REFERENCE_ANSWER_CANARY",
                "rubric": {
                    "criteria": [
                        {
                            "label": "Cycle stages",
                            "guidance": "NEW_RUBRIC_CANARY",
                            "points": 3,
                        }
                    ],
                    "total_points": 3,
                },
            }
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        queued.json()["run_id"],
        _run_claim(database, queued.json()["run_id"]),
        data_root=settings.resolved_data_root,
    )
    after = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert after.status_code == 200, after.text
    assert after.json()["version_seq"] == 3
    assert "Describe the water cycle." in after.json()["markdown"]
    assert "MANUAL_RUBRIC_GUIDANCE" not in after.json()["markdown"]
    with database.session() as db:
        markdown_versions = db.scalars(
            select(KnowledgeSetMarkdownVersion)
            .where(KnowledgeSetMarkdownVersion.knowledge_set_id == set_id)
            .order_by(KnowledgeSetMarkdownVersion.version_seq)
        ).all()
        assert [version.origin for version in markdown_versions] == ["ai", "manual", "ai"]
        assert "MANUAL_RUBRIC_GUIDANCE" in markdown_versions[1].markdown
        final_ids = json.loads(markdown_versions[-1].asset_version_ids_json)
        assert len(final_ids) == 1
        final_asset_version = db.get(KnowledgeAssetVersion, final_ids[0])
        assert final_asset_version is not None
        assert final_asset_version.id != initial_asset_version_id
        assert final_asset_version.asset_id == stable_asset_id
        assert json.loads(final_asset_version.content_json)["prompt"] == "Describe the water cycle."
        history = db.scalars(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id == stable_asset_id)
            .order_by(KnowledgeAssetVersion.version_seq)
        ).all()
        assert [version.version_seq for version in history] == [1, 2, 3]

    unsupported_markdown = after.json()["markdown"].replace("## Questions", "## Problem set")
    fail_closed = _save(
        client,
        csrf,
        set_id,
        unsupported_markdown,
        expected_version_seq=3,
    )
    assert fail_closed.status_code == 200, fail_closed.text
    assert fail_closed.json()["markdown"] == unsupported_markdown
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        current_markdown = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == 4,
            )
        )
        assert set_row is not None and current_markdown is not None
        assert json.loads(current_markdown.asset_version_ids_json) == []
        assert current_markdown.student_projection_markdown == ""
        assert current_question_version_for_asset(db, set_row, stable_asset_id) is None


def test_manual_regeneration_action_is_deduplicated_and_new_action_advances_intent(
    client: TestClient, database: Any
) -> None:
    _agent_id, _document_id, first_run_id, set_id = _create_generation_run(client, database)
    _teacher, csrf = login(client, "maya")

    def regenerate(action_id: str, key: str) -> Any:
        return client.post(
            f"/api/v1/knowledge-sets/{set_id}/regenerate",
            headers=_headers(csrf, key),
            json={"action_id": action_id},
        )

    action_one = str(uuid4())
    first = regenerate(action_one, "k3-brainform-regen-first-0001")
    assert first.status_code == 202, first.text
    duplicate = regenerate(action_one, "k3-brainform-regen-first-0002")
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json() == first.json()

    action_two = str(uuid4())
    second = regenerate(action_two, "k3-brainform-regen-second-0001")
    assert second.status_code == 202, second.text
    assert second.json()["run_id"] != first.json()["run_id"]
    assert second.json()["action_id"] == action_two
    with database.session() as db:
        set_row = db.get(KnowledgeSet, set_id)
        first_run = db.get(KnowledgeGenerationRun, first.json()["run_id"])
        second_run = db.get(KnowledgeGenerationRun, second.json()["run_id"])
        initial_run = db.get(KnowledgeGenerationRun, first_run_id)
        assert set_row is not None and set_row.generation_intent_seq == 3
        assert first_run is not None and first_run.intent_generation == 2
        assert second_run is not None and second_run.intent_generation == 3
        assert (
            initial_run is not None and initial_run.intent_generation < first_run.intent_generation
        )
        assert first_run.state == "pending" and second_run.state == "pending"
        runs = db.scalars(
            select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.knowledge_set_id == set_id)
        ).all()
        assert len(runs) == 3


def test_concurrent_same_regeneration_action_rolls_back_losing_intent_bump(
    client: TestClient, database: Any
) -> None:
    _agent_id, _document_id, initial_run_id, set_id = _create_generation_run(client, database)
    action_id = str(uuid4())
    with database.session() as db:
        initial_run = db.get(KnowledgeGenerationRun, initial_run_id)
        assert initial_run is not None
        owner_user_id = initial_run.owner_user_id

    original_scalar = Session.scalar
    interleaved = False

    def scalar_with_interleaving(
        session: Session, statement: Any, *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal interleaved
        value = original_scalar(session, statement, *args, **kwargs)
        if (
            not interleaved
            and value is None
            and "knowledge_generation_runs.action_id =" in str(statement)
        ):
            interleaved = True
            with database.session() as winner_db:
                winner = enqueue_generation_for_existing_set(
                    winner_db,
                    set_id=set_id,
                    owner_user_id=owner_user_id,
                    action_id=action_id,
                )
                assert winner.created is True
                winner_db.commit()
        return value

    with database.session() as db:
        with patch.object(Session, "scalar", scalar_with_interleaving):
            loser = enqueue_generation_for_existing_set(
                db,
                set_id=set_id,
                owner_user_id=owner_user_id,
                action_id=action_id,
            )
            db.commit()
        set_row = db.get(KnowledgeSet, set_id)
        assert set_row is not None
        assert interleaved is True
        assert loser.created is False
        assert loser.run.action_id == action_id
        assert set_row.generation_intent_seq == loser.run.intent_generation
        assert _current_generation_authorized(db, loser.run) is True
        matching = db.scalars(
            select(KnowledgeGenerationRun).where(
                KnowledgeGenerationRun.knowledge_set_id == set_id,
                KnowledgeGenerationRun.action_id == action_id,
            )
        ).all()
        assert len(matching) == 1


def test_stable_rag_edit_keeps_question_receipt_history_and_auto_enqueues_new_intent(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    _app, _database, settings = app_bundle
    agent_id, document_id, run_id, set_id = _create_generation_run(client, database)
    with database.session() as db:
        source = db.scalar(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.knowledge_set_id == set_id,
                KnowledgeSetSource.is_active.is_(True),
            )
        )
        receipt = db.scalar(
            select(KnowledgeGenerationSourceReceipt).where(
                KnowledgeGenerationSourceReceipt.run_id == run_id
            )
        )
        document = db.get(KnowledgeDocument, document_id)
        assert source is not None and receipt is not None and document is not None
        binding_id = source.id
        source_file_id = source.stored_file_id
        source_hash = source.source_content_hash
        source_sha = source.source_file_sha256
        authorization_epoch = source.source_authorization_epoch
        expected_index_revision = document.index_revision

    _accept_stage(
        database,
        run_id,
        [
            {
                "content": {
                    "kind": "question",
                    "prompt": "Explain the evidence.",
                    "reference_answer": "OWNER_ONLY_REFERENCE_ANSWER",
                    "concept_ids": [],
                    "citations": [],
                    "rubric": {
                        "criteria": [
                            {
                                "label": "Evidence",
                                "guidance": "OWNER_ONLY_RUBRIC_GUIDANCE",
                                "points": 2,
                            }
                        ],
                        "total_points": 2,
                    },
                },
                "source_receipt_ids": [receipt.id],
                "citation_unverified": False,
            }
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        run_id,
        _run_claim(database, run_id),
        data_root=settings.resolved_data_root,
    )
    with database.session() as db:
        canonical = db.scalar(
            select(KnowledgeSetMarkdownVersion).where(
                KnowledgeSetMarkdownVersion.knowledge_set_id == set_id,
                KnowledgeSetMarkdownVersion.version_seq == 1,
            )
        )
        assert canonical is not None and canonical.origin == "ai"
        asset_version_ids = canonical.asset_version_ids_json
        assert asset_version_ids
        version_source = db.scalar(select(KnowledgeAssetVersionSource))
        assert version_source is not None
        assert version_source.source_binding_id == binding_id
        assert version_source.document_id == document_id
        assert version_source.stored_file_id == source_file_id
        assert version_source.source_content_hash == source_hash

    teacher, csrf = login(client, "maya")
    assets = client.get(f"/api/v1/knowledge-sets/{set_id}/assets")
    assert assets.status_code == 200, assets.text
    assert len(assets.json()) == 1
    asset_id = assets.json()[0]["id"]
    assert assets.json()[0]["current_version"]["content"]["reference_answer"] == (
        "OWNER_ONLY_REFERENCE_ANSWER"
    )
    assert "OWNER_ONLY_RUBRIC_GUIDANCE" in assets.text

    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, set_id)
        assert document is not None
        assert set_row is not None
        expected_hash = document.content_hash
        expected_index_revision = document.index_revision
        initial_intent_seq = set_row.generation_intent_seq
        initial_generation_count = len(
            db.scalars(
                select(KnowledgeGenerationRun).where(
                    KnowledgeGenerationRun.knowledge_set_id == set_id
                )
            ).all()
        )
    renamed = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-brainform-rag-rename-{uuid4()}"),
        data={
            "expected_content_hash": expected_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={
            "file": (
                "lesson-renamed.md",
                b"# Lesson\n\nA source canary.",
                "text/markdown",
            )
        },
    )
    assert renamed.status_code == 201, renamed.text
    assert renamed.json()["id"] == document_id
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, set_id)
        runs = db.scalars(
            select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.knowledge_set_id == set_id)
        ).all()
        assert document is not None and document.source_filename == "lesson-renamed.md"
        assert document.index_revision == expected_index_revision
        assert document.content_version_seq == 1
        assert set_row is not None and set_row.generation_intent_seq == initial_intent_seq
        assert len(runs) == initial_generation_count

    replace_key = f"k3-brainform-rag-edit-{uuid4()}"
    replace_headers = _headers(csrf, replace_key)
    replacement_files = {
        "file": ("lesson-updated.md", b"# Updated source\n\nNew evidence.", "text/markdown")
    }
    replacement_data = {
        "expected_content_hash": expected_hash,
        "expected_index_revision": str(expected_index_revision),
    }
    replaced = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=replace_headers,
        data=replacement_data,
        files=replacement_files,
    )
    assert replaced.status_code == 201, replaced.text
    assert replaced.json()["id"] == document_id
    replay = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=replace_headers,
        data=replacement_data,
        files=replacement_files,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json() == replaced.json()
    with database.session() as db:
        current_source = db.get(KnowledgeSetSource, binding_id)
        current_document = db.get(KnowledgeDocument, document_id)
        history = db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_seq)
        ).all()
        run = db.get(KnowledgeGenerationRun, run_id)
        set_row = db.get(KnowledgeSet, set_id)
        runs = db.scalars(
            select(KnowledgeGenerationRun)
            .where(KnowledgeGenerationRun.knowledge_set_id == set_id)
            .order_by(KnowledgeGenerationRun.intent_generation)
        ).all()
        assert current_source is not None
        assert current_document is not None and current_document.content_version_seq == 2
        assert current_source.id == binding_id
        assert current_source.document_id == document_id
        assert current_source.stored_file_id != source_file_id
        assert current_source.source_content_hash != source_hash
        assert current_source.source_authorization_epoch == authorization_epoch
        assert [row.version_seq for row in history] == [1, 2]
        assert history[0].stored_file_id == source_file_id
        assert history[0].content_hash == source_hash
        assert history[0].file_sha256 == source_sha
        assert run is not None and run.state == "completed"
        assert set_row is not None and len(runs) == 2
        assert runs[1].intent_generation > runs[0].intent_generation
        assert runs[1].state == "pending"

    # The original question remains readable from its immutable source receipt;
    # validating it does not require its old hash to equal the new RAG head.
    current_asset = client.get(f"/api/v1/knowledge-assets/{asset_id}")
    assert current_asset.status_code == 200, current_asset.text
    assert current_asset.json()["current_version"]["content"]["reference_answer"] == (
        "OWNER_ONLY_REFERENCE_ANSWER"
    )
    assert "OWNER_ONLY_RUBRIC_GUIDANCE" in current_asset.text
    assert teacher


def test_normalization_only_rag_save_preserves_old_run_authorization(
    client: TestClient, database: Any
) -> None:
    _agent_id, document_id, run_id, set_id = _create_generation_run(client, database)
    _owner, csrf = login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, set_id)
        run = db.get(KnowledgeGenerationRun, run_id)
        assert document is not None and set_row is not None and run is not None
        expected_hash = document.content_hash
        expected_index_revision = document.index_revision
        expected_intent = set_row.generation_intent_seq
        expected_sha = document.stored_file.sha256

    crlf = b"# Lesson\r\n\r\nA source canary."
    saved = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-bf-normalized-source-{uuid4()}"),
        data={
            "expected_content_hash": expected_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={"file": ("lesson.md", crlf, "text/markdown")},
    )
    assert saved.status_code == 201, saved.text
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        set_row = db.get(KnowledgeSet, set_id)
        run = db.get(KnowledgeGenerationRun, run_id)
        versions = db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_seq)
        ).all()
        runs = db.scalars(
            select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.knowledge_set_id == set_id)
        ).all()
        assert document is not None and set_row is not None and run is not None
        assert document.content_version_seq == 2
        assert document.index_revision == expected_index_revision
        assert document.content_hash == expected_hash
        assert document.stored_file.sha256 != expected_sha
        assert set_row.generation_intent_seq == expected_intent
        assert [version.version_seq for version in versions] == [1, 2]
        assert len(runs) == 1
        assert _current_generation_authorized(db, run) is True


def test_revoked_generator_does_not_rollback_authorized_rag_source_save(
    client: TestClient, database: Any
) -> None:
    agent_id, document_id, run_id, set_id = _create_generation_run(client, database)
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        document = db.get(KnowledgeDocument, document_id)
        assert agent is not None and document is not None
        agent.deleted_at = datetime.now(UTC)
        expected_hash = document.content_hash
        expected_index_revision = document.index_revision
    _owner, csrf = login(client, "maya")
    saved = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-bf-revoked-generator-source-{uuid4()}"),
        data={
            "expected_content_hash": expected_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={
            "file": ("lesson-updated.md", b"# Updated source\n\nNew evidence.", "text/markdown")
        },
    )
    assert saved.status_code == 201, saved.text
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        runs = db.scalars(
            select(KnowledgeGenerationRun).where(KnowledgeGenerationRun.knowledge_set_id == set_id)
        ).all()
        run = db.get(KnowledgeGenerationRun, run_id)
        assert document is not None and document.content_version_seq == 2
        assert document.content_hash != expected_hash
        assert len(runs) == 1
        assert run is not None and _current_generation_authorized(db, run) is False


def test_source_owner_edit_enqueues_as_existing_generator_owner(
    client: TestClient, database: Any
) -> None:
    _student, student_csrf = login(client, "bowen")
    source = _upload_source(
        client,
        student_csrf,
        visibility="public",
        content="# Student owned public source\n\nOriginal source.",
        filename="student-source.md",
        key=f"k3-bf-cross-owner-upload-{uuid4()}",
    )
    _teacher, teacher_csrf = login(client, "maya")
    joined = client.post(
        f"/api/v1/groups/{GROUP_ID}/membership",
        headers=_headers(teacher_csrf),
    )
    assert joined.status_code == 200, joined.text
    _agent_id, version_id, revision, _own_source_id = _teacher_agent_with_source(
        client, teacher_csrf
    )
    selected = client.put(
        f"/api/v1/agent-versions/{version_id}/knowledge-documents",
        headers=_headers(teacher_csrf),
        json={"expected_revision": revision, "document_ids": [source["id"]]},
    )
    assert selected.status_code == 200, selected.text
    published = _publish(
        client,
        teacher_csrf,
        version_id,
        selected.json()["revision"],
        source["id"],
        f"k3-bf-cross-owner-publish-{uuid4()}",
    )
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    with database.session() as db:
        initial_run = db.get(KnowledgeGenerationRun, run_id)
        document = db.get(KnowledgeDocument, source["id"])
        assert initial_run is not None and document is not None
        generation_owner_id = initial_run.owner_user_id
        assert document.owner_user_id != generation_owner_id
        expected_hash = document.content_hash
        expected_index_revision = document.index_revision

    _source_owner, source_owner_csrf = login(client, "bowen")
    saved = client.post(
        f"/api/v1/knowledge-documents/{source['id']}/replace",
        headers=_headers(source_owner_csrf, f"k3-bf-cross-owner-edit-{uuid4()}"),
        data={
            "expected_content_hash": expected_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={
            "file": (
                "student-source-updated.md",
                b"# Student owned public source\n\nUpdated.",
                "text/markdown",
            )
        },
    )
    assert saved.status_code == 201, saved.text
    with database.session() as db:
        runs = db.scalars(
            select(KnowledgeGenerationRun)
            .where(KnowledgeGenerationRun.knowledge_set_id == initial_run.knowledge_set_id)
            .order_by(KnowledgeGenerationRun.intent_generation)
        ).all()
        assert len(runs) == 2
        assert all(run.owner_user_id == generation_owner_id for run in runs)
        assert runs[-1].state == "pending"


def test_hide_edited_unbound_rag_soft_hides_but_preserves_source_versions(
    client: TestClient, database: Any
) -> None:
    _owner, csrf = login(client, "bowen")
    source = _upload_source(
        client,
        csrf,
        visibility="private",
        content="# Library source\n\nBefore edit.",
        filename="library.md",
        key=f"k3-bf-hide-upload-{uuid4()}",
    )
    edited = client.post(
        f"/api/v1/knowledge-documents/{source['id']}/replace",
        headers=_headers(csrf, f"k3-bf-hide-edit-{uuid4()}"),
        data={
            "expected_content_hash": source["content_hash"],
            "expected_index_revision": str(source["index_revision"]),
        },
        files={"file": ("library.md", b"# Library source\n\nAfter edit.", "text/markdown")},
    )
    assert edited.status_code == 201, edited.text
    hidden = client.post(
        f"/api/v1/knowledge-documents/{source['id']}/hide",
        headers=_headers(csrf, f"k3-bf-hide-after-edit-{uuid4()}"),
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["id"] == source["id"]
    assert hidden.json()["workspace_state"] == "hidden"
    with database.session() as db:
        document = db.get(KnowledgeDocument, source["id"])
        versions = db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == source["id"])
            .order_by(KnowledgeDocumentVersion.version_seq)
        ).all()
        assert document is not None and document.workspace_state == "hidden"
        assert [version.version_seq for version in versions] == [1, 2]


def test_unbound_legacy_projection_stays_blocked_after_source_withdrawal(
    client: TestClient, database: Any
) -> None:
    from types import SimpleNamespace

    from app.modules.knowledge_sets.service import save_knowledge_markdown_version

    _owner, csrf = login(client, "bowen")
    source = _upload_source(
        client,
        csrf,
        visibility="public",
        content="# Revocable source\n\nWITHDRAWN_SOURCE_CANARY",
        filename="revocable.md",
        key=f"k3-bf-legacy-source-{uuid4()}",
    )
    set_row = _create_set(client, csrf, "Legacy public derived document", group_id=GROUP_ID)
    added_source = client.put(
        f"/api/v1/knowledge-sets/{set_row['id']}/sources",
        headers=_headers(csrf, f"k3-bf-legacy-bind-{uuid4()}"),
        json={"expected_content_revision": 0, "source_document_ids": [source["id"]]},
    )
    assert added_source.status_code == 200, added_source.text
    binding_id = added_source.json()["sources"][0]["id"]
    shared = client.patch(
        f"/api/v1/knowledge-sets/{set_row['id']}",
        headers=_headers(csrf, f"k3-bf-legacy-share-{uuid4()}"),
        json={"expected_metadata_revision": 0, "visibility": "public"},
    )
    assert shared.status_code == 200, shared.text
    asset = client.post(
        f"/api/v1/knowledge-sets/{set_row['id']}/assets",
        headers=_headers(csrf, f"k3-bf-legacy-asset-{uuid4()}"),
        json={
            "expected_content_revision": 1,
            "content": {
                "kind": "note",
                "title": "Derived source",
                "body": "WITHDRAWN_SOURCE_CANARY",
                "citations": [{"source_binding_id": binding_id}],
            },
        },
    )
    assert asset.status_code == 201, asset.text
    public_agent = _create_agent_and_bind(
        client,
        csrf,
        set_row["id"],
        name="Legacy derived Agent",
        visibility="public",
    )
    agent_version = public_agent["versions"][0]
    edited_agent = client.patch(
        f"/api/v1/agent-versions/{agent_version['id']}",
        headers=_headers(csrf),
        json={
            "expected_revision": agent_version["revision"],
            "agent_md": "# Public source-free Agent\n\nUse authorized Knowledge.",
        },
    )
    assert edited_agent.status_code == 200, edited_agent.text
    published_agent = client.post(
        f"/api/v1/agent-versions/{agent_version['id']}/publish",
        headers=_headers(csrf, f"k3-bf-legacy-agent-publish-{uuid4()}"),
        json={"expected_revision": edited_agent.json()["revision"]},
    )
    assert published_agent.status_code == 200, published_agent.text

    with database.session() as db:
        canonical_set = db.get(KnowledgeSet, set_row["id"])
        current_asset = db.get(KnowledgeAsset, asset.json()["id"])
        asset_version = db.scalar(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == asset.json()["id"]
            )
        )
        assert canonical_set is not None and current_asset is not None and asset_version is not None
        markdown, student_projection, asset_version_ids = _render_asset_versions(
            db,
            canonical_set,
            [
                SimpleNamespace(
                    asset_id=current_asset.id,
                    asset_version_id=asset_version.id,
                )
            ],
        )
        from app.modules.knowledge_sets.service import save_knowledge_markdown_version

        save_knowledge_markdown_version(
            db,
            set_id=canonical_set.id,
            expected_version_seq=0,
            markdown=markdown,
            actor_user_id=canonical_set.owner_user_id,
            origin="legacy",
            asset_version_ids=asset_version_ids,
            student_projection_markdown=student_projection,
        )

    _peer, _peer_csrf = login(client, "kaikai")
    visible_before = client.get(f"/api/v1/knowledge-sets/{set_row['id']}/markdown")
    assert visible_before.status_code == 200, visible_before.text
    assert visible_before.json()["projection_available"] is True
    assert "WITHDRAWN_SOURCE_CANARY" in visible_before.text

    _owner, owner_csrf = login(client, "bowen")
    withdrawn = client.patch(
        f"/api/v1/knowledge-documents/{source['id']}",
        headers=_headers(owner_csrf),
        json={"expected_authorization_epoch": 0, "visibility": "private"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    _peer, _peer_csrf = login(client, "kaikai")
    assert client.get(f"/api/v1/knowledge-sets/{set_row['id']}/markdown").status_code == 404

    _owner, owner_csrf = login(client, "bowen")
    with database.session() as db:
        current_set = db.get(KnowledgeSet, set_row["id"])
        assert current_set is not None
        expected_content_revision = current_set.content_revision
    unbound = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{set_row['id']}/sources/{binding_id}",
        headers=_headers(owner_csrf, f"k3-bf-legacy-unbind-{uuid4()}"),
        json={"expected_content_revision": expected_content_revision},
    )
    assert unbound.status_code == 200, unbound.text
    _peer, _peer_csrf = login(client, "kaikai")
    blocked_projection = client.get(f"/api/v1/knowledge-sets/{set_row['id']}/markdown")
    assert blocked_projection.status_code == 200, blocked_projection.text
    assert blocked_projection.json()["projection_available"] is False
    assert blocked_projection.json()["markdown"] == ""
    assert "WITHDRAWN_SOURCE_CANARY" not in blocked_projection.text
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-assets/{asset.json()['id']}").status_code == 404

    _owner, _owner_csrf = login(client, "bowen")
    owner_markdown = client.get(f"/api/v1/knowledge-sets/{set_row['id']}/markdown")
    assert owner_markdown.status_code == 200, owner_markdown.text
    assert owner_markdown.json()["markdown"]
    assert "WITHDRAWN_SOURCE_CANARY" in owner_markdown.text

    _teacher, _teacher_csrf = login(client, "maya")
    assert client.get(f"/api/v1/knowledge-documents/{source['id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-assets/{asset.json()['id']}").status_code == 404
    teacher_markdown = client.get(f"/api/v1/knowledge-sets/{set_row['id']}/markdown")
    assert teacher_markdown.status_code == 404, teacher_markdown.text
    assert "WITHDRAWN_SOURCE_CANARY" not in teacher_markdown.text


def test_crlf_source_save_builds_the_frozen_provider_input_from_its_receipted_version(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, document_id, run_id, _set_id = _create_generation_run(client, database)
    _teacher, csrf = login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        expected_content_hash = document.content_hash
        expected_index_revision = document.index_revision

    saved = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers=_headers(csrf, f"k3-bf-crlf-provider-input-{uuid4()}"),
        data={
            "expected_content_hash": expected_content_hash,
            "expected_index_revision": str(expected_index_revision),
        },
        files={
            "file": (
                "lesson.md",
                b"# Lesson\r\n\r\nA source canary.",
                "text/markdown",
            )
        },
    )
    assert saved.status_code == 201, saved.text

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        assert _current_generation_authorized(db, run)
        claim_token = claim_generation_run(db, run_id)
    assert claim_token is not None

    _run, _agent, _version, courseware = _generation_input(
        database.session_factory,
        run_id,
        claim_token,
        settings,
    )
    assert len(courseware) == 1
    assert courseware[0][2] == "# Lesson\n\nA source canary."
