from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import Agent, AgentVersion, CourseMember, Job, KnowledgeDocument
from app.modules.knowledge_sets.generation import (
    block_claimed_generation,
    claim_generation_run,
    recover_generation_runs_at_startup,
)
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeGenerationRun,
    KnowledgeSet,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _teacher_agent_with_source(
    client: TestClient,
    csrf: str,
    *,
    agent_markdown: str = "# Course Guide\n\nUse the selected courseware.",
) -> tuple[str, str, int, str]:
    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-agents",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2a-agent-{uuid4()}"}),
        json={"name": "Course Guide", "description": "Owner's source-backed Agent."},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    draft = agent["versions"][0]

    uploaded = client.post(
        f"/api/v1/courses/{COURSE_ID}/workspace-documents",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2a-source-{uuid4()}"}),
        files={"file": ("lesson.md", b"# Lesson\n\nA source canary.", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]

    selected = client.put(
        f"/api/v1/agent-versions/{draft['id']}/knowledge-documents",
        headers=_headers(csrf),
        json={"expected_revision": draft["revision"], "document_ids": [document_id]},
    )
    assert selected.status_code == 200, selected.text
    edited = client.patch(
        f"/api/v1/agent-versions/{draft['id']}",
        headers=_headers(csrf),
        json={
            "expected_revision": selected.json()["revision"],
            "agent_md": agent_markdown,
        },
    )
    assert edited.status_code == 200, edited.text
    assert [row["id"] for row in edited.json()["enabled_documents"]] == [document_id]
    return agent["id"], draft["id"], edited.json()["revision"], document_id


def _publish(
    client: TestClient,
    csrf: str,
    version_id: str,
    revision: int,
    document_id: str,
    key: str,
):
    return client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": key}),
        json={
            "expected_revision": revision,
            "generation": {"source_document_ids": [document_id]},
        },
    )


def test_done_creates_one_stable_owner_run_and_blocks_without_provider(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)

    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-initial-0001",
    )
    assert published.status_code == 200, published.text
    first = published.json()
    receipt = first["knowledge_generation"]
    assert first["state"] == "published"
    assert receipt["state"] == "pending"

    status = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "pending"

    _student, _student_csrf = login(client, "bowen")
    assert client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}").status_code == 404
    assert client.get(f"/api/v1/knowledge-sets/{receipt['knowledge_set_id']}").status_code == 404
    _teacher, csrf = login(client, "maya")

    replay = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-initial-0001",
    )
    assert replay.status_code == 200
    assert replay.json() == first

    next_version = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-next-version-00001"}),
    )
    assert next_version.status_code == 201, next_version.text
    second_publish = _publish(
        client,
        csrf,
        next_version.json()["id"],
        next_version.json()["revision"],
        document_id,
        "k2a-publish-new-key-0001",
    )
    assert second_publish.status_code == 200, second_publish.text
    assert second_publish.json()["knowledge_generation"]["run_id"] == receipt["run_id"]
    assert second_publish.json()["knowledge_generation"]["job_id"] == receipt["job_id"]

    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.operation == "knowledge_set.generate")
            )
            == 1
        )
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        assert len(run.input_key) == 64
        assert version_id not in run.input_key
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0

    block_claimed_generation(database.session_factory, receipt["run_id"])
    blocked = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "blocked"
    assert blocked.json()["safe_error_code"] == "provider_not_configured"
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "blocked"
        assert job is not None and job.state == "failed"
        assert job.attempt == 1
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0
    assert settings.llm_provider == "mock"


def test_ordinary_teacher_done_with_rag_does_not_enqueue_and_chat_still_works(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, _document_id = _teacher_agent_with_source(
        client,
        csrf,
        agent_markdown=(
            "# Course Guide\n\nDo not prepare lessons or teaching materials. "
            "Answer questions using the selected courseware."
        ),
    )

    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-ordinary-done-no-run-01"}),
        json={"expected_revision": revision},
    )
    assert published.status_code == 200, published.text
    published_body = published.json()
    assert published_body["state"] == "published"
    assert published_body["knowledge_snapshot_id"] is not None
    assert published_body["knowledge_generation"] is None

    conversation = client.post(
        "/api/v1/conversations",
        headers=_headers(csrf),
        json={"version_id": version_id},
    )
    assert conversation.status_code == 200, conversation.text
    conversation_id = conversation.json()["id"]
    sent = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
        json={
            "request_id": str(uuid4()),
            "expected_revision": 0,
            "message": "What does the courseware say?",
        },
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["turns"][-1]["state"] == "ready"

    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.operation == "knowledge_set.generate")
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0


def test_generation_source_mismatch_and_non_teacher_owner_fail_before_enqueue(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)

    mismatch = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(csrf, **{"Idempotency-Key": "k2a-source-mismatch-0001"}),
        json={"expected_revision": revision, "generation": {"source_document_ids": [str(uuid4())]}},
    )
    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["code"] == "generation_source_selection_stale"
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        assert agent is not None
        assert db.get(AgentVersion, version_id).state == "draft"
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0

    with database.session() as db:
        member = db.scalar(
            select(CourseMember).where(
                CourseMember.user_id == agent.owner_user_id,
                CourseMember.course_id == COURSE_ID,
            )
        )
        assert member is not None
        member.role = "student"
        db.commit()
    denied = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-nonteacher-owner-01",
    )
    assert denied.status_code == 404, denied.text
    with database.session() as db:
        assert db.get(AgentVersion, version_id).state == "draft"
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 0
        assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0


def test_generation_revocation_fences_worker_and_startup_reclaims_old_lease(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        "k2a-publish-revocation-01",
    )
    assert published.status_code == 200, published.text
    receipt = published.json()["knowledge_generation"]

    with database.session() as db:
        token = claim_generation_run(db, receipt["run_id"])
        assert token is not None
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "running"
        assert job is not None and job.state == "running"
        assert claim_generation_run(db, receipt["run_id"]) is None

    with database.session() as db:
        assert recover_generation_runs_at_startup(db) == 1
    with database.session() as db:
        token_after_recovery = claim_generation_run(db, receipt["run_id"])
        assert token_after_recovery is not None and token_after_recovery != token

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        db.commit()

    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        document.authorization_epoch += 1
        document.workspace_state = "hidden"
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    block_claimed_generation(database.session_factory, receipt["run_id"])
    blocked = client.get(f"/api/v1/knowledge-generation-jobs/{receipt['job_id']}")
    assert blocked.status_code == 200
    assert blocked.json()["state"] == "blocked"
    assert blocked.json()["safe_error_code"] == "authorization_revoked"

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, receipt["run_id"])
        job = db.get(Job, receipt["job_id"])
        assert run is not None and run.state == "blocked"
        assert job is not None and job.state == "failed"
        assert db.scalar(select(func.count()).select_from(KnowledgeAsset)) == 0


@pytest.mark.parametrize(
    ("fault_boundary", "committed"),
    [
        ("publish.after_final_db_prepare", False),
        ("publish.after_final_commit", True),
    ],
)
def test_done_and_generation_run_share_the_publish_commit(
    client: TestClient,
    app_bundle: Any,
    monkeypatch: pytest.MonkeyPatch,
    fault_boundary: str,
    committed: bool,
) -> None:
    from app.modules.agents import router as agents_router

    _app, database, _settings = app_bundle
    _teacher, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    original = agents_router.saga_checkpoint

    def fail_at(boundary: str) -> None:
        if boundary == fault_boundary:
            raise RuntimeError("injected publish boundary failure")
        original(boundary)

    monkeypatch.setattr(agents_router, "saga_checkpoint", fail_at)
    with pytest.raises(RuntimeError, match="injected publish boundary failure"):
        _publish(
            client,
            csrf,
            version_id,
            revision,
            document_id,
            "k2a-publish-fault-boundary-1",
        )
    monkeypatch.setattr(agents_router, "saga_checkpoint", original)

    with database.session() as db:
        version = db.get(AgentVersion, version_id)
        assert version is not None
        runs = db.scalars(select(KnowledgeGenerationRun)).all()
        generation_jobs = db.scalars(
            select(Job).where(Job.operation == "knowledge_set.generate")
        ).all()
        if committed:
            assert version.state == "published"
            assert len(runs) == len(generation_jobs) == 1
        else:
            assert version.state == "draft"
            assert runs == []
            assert generation_jobs == []
            assert db.scalar(select(func.count()).select_from(KnowledgeSet)) == 0

    if committed:
        retry = _publish(
            client,
            csrf,
            version_id,
            revision,
            document_id,
            "k2a-publish-fault-boundary-1",
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["knowledge_generation"]["run_id"] == runs[0].id
        with database.session() as db:
            assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == 1
