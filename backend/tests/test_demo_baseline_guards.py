"""Ensure every existing student write route rejects the Demo baseline."""

from __future__ import annotations

from typing import Any

from app.core.models import Agent, AgentVersion, KnowledgeDocument, KnowledgeSnapshot
from app.modules.demo_baseline.service import (
    BASELINE_AGENT_ID,
    BASELINE_DOCUMENT_ID,
    BASELINE_SNAPSHOT_ID,
    BASELINE_VERSION_ID,
    dirty_counts,
    ensure_demo_baseline,
)
from fastapi.testclient import TestClient


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "demo-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def _headers(csrf: str, *, key: str | None = None) -> dict[str, str]:
    result = {"Origin": "http://testserver", "X-CSRF-Token": csrf}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def _assert_baseline_rejected(response: Any) -> None:
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "demo_baseline_immutable"
    assert "provider" not in response.text.lower()


def test_student_cannot_mutate_any_baseline_agent_or_source_entrypoint(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
            baseline_before = (
                db.get(Agent, BASELINE_AGENT_ID).name,
                db.get(Agent, BASELINE_AGENT_ID).description,
                db.get(Agent, BASELINE_AGENT_ID).current_published_version_id,
                db.get(AgentVersion, BASELINE_VERSION_ID).agent_md,
                db.get(AgentVersion, BASELINE_VERSION_ID).revision,
                db.get(KnowledgeDocument, BASELINE_DOCUMENT_ID).content_hash,
                db.get(KnowledgeDocument, BASELINE_DOCUMENT_ID).index_revision,
                db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID).content_hash,
            )
        csrf = _login(client, "bowen")
        version_url = f"/api/v1/agent-versions/{BASELINE_VERSION_ID}"
        agent_url = f"/api/v1/agents/{BASELINE_AGENT_ID}"
        document_url = f"/api/v1/knowledge-documents/{BASELINE_DOCUMENT_ID}"

        _assert_baseline_rejected(
            client.patch(
                agent_url,
                headers=_headers(csrf),
                json={"expected_metadata_revision": 0, "description": "tampered"},
            )
        )
        _assert_baseline_rejected(
            client.delete(
                agent_url,
                headers=_headers(csrf, key="baseline-delete-0001"),
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{agent_url}/versions",
                headers=_headers(csrf, key="baseline-version-0001"),
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{version_url}/persona/compile",
                headers=_headers(csrf),
                json={"expected_revision": 1},
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{version_url}/persona/confirm",
                headers=_headers(csrf),
                json={
                    "expected_revision": 1,
                    "raw_agent_md_hash": "sha256:" + "0" * 64,
                    "persona_spec_hash": "0" * 64,
                    "compiler_version": "persona_template_v1",
                },
            )
        )
        _assert_baseline_rejected(
            client.patch(
                version_url,
                headers=_headers(csrf),
                json={"expected_revision": 1, "agent_md": "# tampered"},
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{version_url}/agent-md/upload",
                headers=_headers(csrf),
                data={"expected_revision": "1"},
                files={"file": ("AGENT.md", b"# tampered", "text/markdown")},
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{version_url}/publish",
                headers=_headers(csrf, key="baseline-publish-0001"),
                json={"expected_revision": 1},
            )
        )
        _assert_baseline_rejected(
            client.post(
                "/api/v1/groups/7813f937-902c-5534-bfb2-ad773a43aeda/knowledge-documents",
                headers=_headers(csrf, key="baseline-upload-0001"),
                data={
                    "target_agent_version_id": BASELINE_VERSION_ID,
                    "expected_revision": "1",
                },
                files={"file": ("tampered.md", b"# tampered", "text/markdown")},
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{document_url}/replace",
                headers=_headers(csrf, key="baseline-replace-0001"),
                data={"expected_content_hash": baseline_before[5], "expected_index_revision": "1"},
                files={"file": ("replacement.md", b"# tampered", "text/markdown")},
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{document_url}/reindex",
                headers=_headers(csrf, key="baseline-reindex-0001"),
            )
        )
        _assert_baseline_rejected(
            client.post(
                f"{document_url}/hide",
                headers=_headers(csrf, key="baseline-hide-0001"),
            )
        )
        _assert_baseline_rejected(
            client.put(
                f"{version_url}/knowledge-documents",
                headers=_headers(csrf),
                json={"expected_revision": 1, "document_ids": []},
            )
        )

        with database.session() as db:
            baseline_after = (
                db.get(Agent, BASELINE_AGENT_ID).name,
                db.get(Agent, BASELINE_AGENT_ID).description,
                db.get(Agent, BASELINE_AGENT_ID).current_published_version_id,
                db.get(AgentVersion, BASELINE_VERSION_ID).agent_md,
                db.get(AgentVersion, BASELINE_VERSION_ID).revision,
                db.get(KnowledgeDocument, BASELINE_DOCUMENT_ID).content_hash,
                db.get(KnowledgeDocument, BASELINE_DOCUMENT_ID).index_revision,
                db.get(KnowledgeSnapshot, BASELINE_SNAPSHOT_ID).content_hash,
            )
            assert baseline_after == baseline_before
            assert dirty_counts(db) == (0, 0, 0)


def test_teacher_write_attempts_leave_baseline_unchanged(app_factory: Any) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        with database.session() as db:
            ensure_demo_baseline(db, settings.resolved_data_root)
        csrf = _login(client, "maya")
        response = client.patch(
            f"/api/v1/agents/{BASELINE_AGENT_ID}",
            headers=_headers(csrf),
            json={"expected_metadata_revision": 0, "description": "tampered"},
        )
        _assert_baseline_rejected(response)
        with database.session() as db:
            assert db.get(Agent, BASELINE_AGENT_ID).description == (
                "Seeded Demo Agent for the local mutual-learning session."
            )
            assert dirty_counts(db) == (0, 0, 0)
