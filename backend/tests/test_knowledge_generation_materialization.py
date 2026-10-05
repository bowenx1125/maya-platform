from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import CourseMember, Job, KnowledgeDocument, ProviderOperation
from app.modules.knowledge_sets.generation import claim_generation_run
from app.modules.knowledge_sets.materialization import materialize_accepted_knowledge_generation
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeGenerationAcceptedStage,
    KnowledgeGenerationItem,
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetMarkdownVersion,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_knowledge_generation import (
    _headers,
    _publish,
    _teacher_agent_with_source,
)


def _digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _accept_stage(database: Any, run_id: str, assets: list[object]) -> str:
    with database.session() as db:
        token = claim_generation_run(db, run_id)
    assert token is not None

    canonical_stage_json = _canonical({"assets": assets})
    stage_hash = _digest(canonical_stage_json)
    manifest_hash = _digest(f"manifest:{run_id}")
    request_hash = _digest(f"request:{run_id}:{stage_hash}")
    policy_hash = _digest("policy")
    schema_hash = _digest("schema")
    operation_id = str(uuid4())
    now = datetime.now(UTC)

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None and run.claim_token == token
        job = db.get(Job, run.job_id)
        assert job is not None and job.claim_token == token
        run.provider_operation_id = operation_id
        run.provider_manifest_hash = manifest_hash
        run.request_hash = request_hash
        db.add(
            ProviderOperation(
                id=operation_id,
                scope_id=run_id,
                provider_operation="llm_knowledge_generate",
                logical_item_id=run_id,
                attempt_no=1,
                request_hash=request_hash,
                max_tokens=0,
                max_cost_cny=0,
                policy_hash=policy_hash,
                export_manifest_hash=manifest_hash,
                build_manifest_hash=_digest("build"),
                model_key="qwen3.5-plus",
                state="accepted",
                request_count=1,
                charged_request_count=1,
                staged_response_hash=stage_hash,
                safe_error_code=None,
                acceptance_run_id=None,
                call_no=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            KnowledgeGenerationAcceptedStage(
                run_id=run_id,
                operation_id=operation_id,
                request_hash=request_hash,
                manifest_hash=manifest_hash,
                policy_hash=policy_hash,
                model_key="qwen3.5-plus",
                schema_hash=schema_hash,
                canonical_stage_json=canonical_stage_json,
                canonical_stage_hash=stage_hash,
                item_count=len(assets),
                usage_json=None,
                safe_error_code=None,
                accepted_at=now,
                created_at=now,
            )
        )
        db.commit()
    return token


def _create_generation_run(client: TestClient, database: Any) -> tuple[str, str, str, str]:
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    published = _publish(
        client,
        csrf,
        version_id,
        revision,
        document_id,
        f"k2b2-materialization-{uuid4()}",
    )
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        set_id = run.knowledge_set_id
    return agent_id, document_id, run_id, set_id


def test_manual_markdown_edit_is_overwritten_by_later_successful_generation(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    agent_id, document_id, first_run_id, set_id = _create_generation_run(client, database)
    first_stage = [
        {
            "kind": "note",
            "title": "Generated first draft",
            "body": "The first generated note is immediately available.",
        }
    ]
    _accept_stage(database, first_run_id, first_stage)
    materialize_accepted_knowledge_generation(
        database.session_factory,
        first_run_id,
        _run_claim(database, first_run_id),
        data_root=settings.resolved_data_root,
    )

    _teacher, csrf = login(client, "maya")
    detail = client.get(f"/api/v1/knowledge-sets/{set_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["generated_by_agent_id"] == agent_id
    current = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert current.status_code == 200, current.text
    assert current.json()["version_seq"] == 1
    manual = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2b2-manual-{uuid4()}"}),
        json={
            "expected_version_seq": 1,
            "markdown": "# Teacher's edit\n\nA human saved this newer version.",
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["version_seq"] == 2

    next_draft = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2b2-next-{uuid4()}"}),
    )
    assert next_draft.status_code == 201, next_draft.text
    changed = client.patch(
        f"/api/v1/agent-versions/{next_draft.json()['id']}",
        headers=_headers(csrf),
        json={
            "expected_revision": next_draft.json()["revision"],
            "agent_md": "# Updated Course Guide\n\nUse the same source with a new instruction.",
        },
    )
    assert changed.status_code == 200, changed.text
    published = _publish(
        client,
        csrf,
        changed.json()["id"],
        changed.json()["revision"],
        document_id,
        f"k2b2-update-{uuid4()}",
    )
    assert published.status_code == 200, published.text
    second_run_id = published.json()["knowledge_generation"]["run_id"]
    assert published.json()["knowledge_generation"]["knowledge_set_id"] == set_id
    owner_detail = client.get(f"/api/v1/knowledge-sets/{set_id}")
    assert owner_detail.status_code == 200
    assert owner_detail.json()["generated_by_agent_id"] == agent_id

    _accept_stage(
        database,
        second_run_id,
        [
            {
                "kind": "note",
                "title": "New generated candidate",
                "body": "A successful newer generation replaces the manual head.",
            }
        ],
    )
    second_token = _run_claim(database, second_run_id)
    materialize_accepted_knowledge_generation(
        database.session_factory,
        second_run_id,
        second_token,
        data_root=settings.resolved_data_root,
    )

    current = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert current.status_code == 200, current.text
    assert current.json()["version_seq"] == 3
    assert "New generated candidate" in current.json()["markdown"]
    assert "Teacher's edit" not in current.json()["markdown"]
    with database.session() as db:
        item = db.scalar(
            select(KnowledgeGenerationItem).where(KnowledgeGenerationItem.run_id == second_run_id)
        )
        assert item is not None and item.state == "applied"
        markdown_versions = db.scalars(
            select(KnowledgeSetMarkdownVersion)
            .where(KnowledgeSetMarkdownVersion.knowledge_set_id == set_id)
            .order_by(KnowledgeSetMarkdownVersion.version_seq)
        ).all()
        assert [version.origin for version in markdown_versions] == ["ai", "manual", "ai"]
        assert (
            db.scalar(
                select(KnowledgeAssetVersion.origin).where(
                    KnowledgeAssetVersion.id == item.asset_version_id,
                )
            )
            == "ai"
        )


def test_partial_refresh_keeps_previous_complete_markdown_version(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, _document_id, initial_run_id, set_id = _create_generation_run(client, database)
    _accept_stage(
        database,
        initial_run_id,
        [
            {
                "kind": "note",
                "title": "Complete current guide",
                "body": "This is the last complete generated document.",
            }
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        initial_run_id,
        _run_claim(database, initial_run_id),
        data_root=settings.resolved_data_root,
    )
    _teacher, csrf = login(client, "maya")
    before = client.get(f"/api/v1/knowledge-sets/{set_id}/markdown")
    assert before.status_code == 200, before.text
    before_document = before.json()

    action_id = str(uuid4())
    queued = client.post(
        f"/api/v1/knowledge-sets/{set_id}/regenerate",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2b2-partial-refresh-{uuid4()}"}),
        json={"action_id": action_id},
    )
    assert queued.status_code == 202, queued.text
    _accept_stage(
        database,
        queued.json()["run_id"],
        [
            {
                "kind": "note",
                "title": "Incomplete candidate",
                "body": "One valid item does not make the whole refresh complete.",
            },
            {"_item_error": "provider_asset_invalid"},
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
    assert after.json()["version_seq"] == before_document["version_seq"]
    assert after.json()["content_hash"] == before_document["content_hash"]
    assert after.json()["markdown"] == before_document["markdown"]
    assert "Incomplete candidate" not in after.json()["markdown"]
    with database.session() as db:
        failed_run = db.get(KnowledgeGenerationRun, queued.json()["run_id"])
        versions = db.scalars(
            select(KnowledgeSetMarkdownVersion)
            .where(KnowledgeSetMarkdownVersion.knowledge_set_id == set_id)
            .order_by(KnowledgeSetMarkdownVersion.version_seq)
        ).all()
        assert failed_run is not None
        assert failed_run.state == "failed"
        assert failed_run.safe_error_code == "knowledge_generation_partial_failure"
        assert [version.version_seq for version in versions] == [1]


def test_newer_intent_fences_older_run_before_provider_acceptance(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    agent_id, document_id, older_run_id, set_id = _create_generation_run(client, database)
    _teacher, csrf = login(client, "maya")
    next_draft = client.post(
        f"/api/v1/agents/{agent_id}/versions",
        headers=_headers(csrf, **{"Idempotency-Key": f"k2b2-race-next-{uuid4()}"}),
    )
    assert next_draft.status_code == 201, next_draft.text
    changed = client.patch(
        f"/api/v1/agent-versions/{next_draft.json()['id']}",
        headers=_headers(csrf),
        json={
            "expected_revision": next_draft.json()["revision"],
            "agent_md": "# Newer Guide\n\nThis explicit update is newer.",
        },
    )
    assert changed.status_code == 200, changed.text
    newer = _publish(
        client,
        csrf,
        changed.json()["id"],
        changed.json()["revision"],
        document_id,
        f"k2b2-race-publish-{uuid4()}",
    )
    assert newer.status_code == 200, newer.text
    newer_run_id = newer.json()["knowledge_generation"]["run_id"]
    assert newer.json()["knowledge_generation"]["knowledge_set_id"] == set_id

    with database.session() as db:
        assert claim_generation_run(db, older_run_id) is None
        older_run = db.get(KnowledgeGenerationRun, older_run_id)
        assert older_run is not None
        assert older_run.state == "blocked"
        assert older_run.safe_error_code == "authorization_revoked"
    newer_token = _accept_stage(
        database,
        newer_run_id,
        [{"kind": "note", "title": "Newer head", "body": "This is the latest intent."}],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        newer_run_id,
        newer_token,
        data_root=settings.resolved_data_root,
    )
    assets = client.get(f"/api/v1/knowledge-sets/{set_id}/assets")
    assert assets.status_code == 200, assets.text
    notes = {asset["current_version"]["content"]["title"]: asset for asset in assets.json()}
    assert "Newer head" in notes
    assert set(notes) == {"Newer head"}
    with database.session() as db:
        old_items = db.scalars(
            select(KnowledgeGenerationItem)
            .where(KnowledgeGenerationItem.run_id == older_run_id)
            .order_by(KnowledgeGenerationItem.item_index)
        ).all()
        assert old_items == []
        assert (
            db.scalar(
                select(KnowledgeAssetVersion.origin).where(
                    KnowledgeAssetVersion.asset_id == notes["Newer head"]["id"],
                    KnowledgeAssetVersion.version_seq == 1,
                )
            )
            == "ai"
        )


def _run_claim(database: Any, run_id: str) -> str:
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None and run.state == "running" and run.claim_token is not None
        return run.claim_token


@pytest.mark.parametrize("revocation", ["source", "teacher", "set"])
def test_revocation_after_first_item_keeps_saved_item_and_blocks_later_items(
    client: TestClient, app_bundle: Any, monkeypatch: Any, revocation: str
) -> None:
    _app, database, settings = app_bundle
    _agent_id, document_id, run_id, set_id = _create_generation_run(client, database)
    token = _accept_stage(
        database,
        run_id,
        [
            {"kind": "note", "title": "Saved before revocation", "body": "Keep this."},
            {"kind": "note", "title": "Blocked after revocation", "body": "Do not save."},
        ],
    )

    from app.modules.knowledge_sets import materialization

    original = materialization._materialize_one
    calls = 0

    def revoke_after_first(*args: Any, **kwargs: Any) -> str:
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1 and result == "applied":
            with database.session() as db:
                run = db.get(KnowledgeGenerationRun, run_id)
                assert run is not None
                if revocation == "source":
                    document = db.get(KnowledgeDocument, document_id)
                    assert document is not None
                    document.authorization_epoch += 1
                    document.workspace_state = "hidden"
                elif revocation == "teacher":
                    member = db.scalar(
                        select(CourseMember).where(
                            CourseMember.user_id == run.owner_user_id,
                            CourseMember.course_id == run.course_id,
                        )
                    )
                    assert member is not None
                    member.role = "student"
                else:
                    set_row = db.get(KnowledgeSet, set_id)
                    assert set_row is not None
                    set_row.deleted_at = datetime.now(UTC)
                    set_row.authorization_epoch += 1
                db.commit()
        return result

    monkeypatch.setattr(materialization, "_materialize_one", revoke_after_first)
    materialize_accepted_knowledge_generation(
        database.session_factory, run_id, token, data_root=settings.resolved_data_root
    )

    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.get(Job, run.job_id) if run is not None else None
        assert run is not None and run.state == "blocked"
        assert run.safe_error_code == "authorization_revoked"
        assert job is not None and job.state == "failed"
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.knowledge_set_id == set_id)
            )
            == 1
        )


def test_accepted_stage_restarts_into_local_materialization_without_transport(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, _document_id, run_id, set_id = _create_generation_run(client, database)
    token = _accept_stage(
        database,
        run_id,
        [{"kind": "note", "title": "Recovered locally", "body": "No second call."}],
    )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None and run.state == "running" and run.claim_token == token
        assert run.provider_operation_id is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.knowledge_set_id == set_id)
            )
            == 0
        )
        from app.modules.knowledge_sets.generation import recover_generation_runs_at_startup

        assert recover_generation_runs_at_startup(db) == 1

    from app.modules.knowledge_sets.provider_runtime import run_claimed_knowledge_generation

    class NoTransport:
        def post_bytes(self, **_kwargs: object) -> object:
            raise AssertionError("an accepted stage must recover without another request")

    run_claimed_knowledge_generation(
        database.session_factory,
        run_id,
        settings,
        transport=NoTransport(),  # type: ignore[arg-type]
    )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        job = db.get(Job, run.job_id) if run is not None else None
        assert run is not None and run.state == "completed"
        assert job is not None and job.state == "completed"
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.knowledge_set_id == set_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationItem)
                .where(KnowledgeGenerationItem.run_id == run_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationItem)
                .where(
                    KnowledgeGenerationItem.run_id == run_id,
                    KnowledgeGenerationItem.state == "applied",
                )
            )
            == 1
        )


def test_late_materializer_claim_cannot_write_after_lease_changes(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    _agent_id, _document_id, run_id, set_id = _create_generation_run(client, database)
    token = _accept_stage(
        database,
        run_id,
        [{"kind": "note", "title": "Must stay staged", "body": "Late worker."}],
    )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        job = db.get(Job, run.job_id)
        assert job is not None
        run.claim_token = "f" * 64
        job.claim_token = "f" * 64
        db.commit()

    materialize_accepted_knowledge_generation(
        database.session_factory, run_id, token, data_root=settings.resolved_data_root
    )

    with database.session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.knowledge_set_id == set_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeGenerationItem)
                .where(KnowledgeGenerationItem.run_id == run_id)
            )
            == 0
        )
