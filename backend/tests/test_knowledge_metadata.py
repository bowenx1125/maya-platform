"""RAG names are metadata; renaming cannot reindex or grant source access."""

from typing import Any
from uuid import uuid4

from app.core.models import Job, KnowledgeDocument, KnowledgeSnapshot, ProviderOperation
from app.modules.knowledge.providers.packing import plan_embedding_batches
from app.modules.knowledge.providers.product_publication import (
    prepare_real_snapshot_build,
    run_confirmed_real_embedding_publication,
)
from app.modules.knowledge.providers.runtime import (
    AcceptedEmbeddingStageV1,
    _reservation_request,
    _response_hash,
)
from app.modules.knowledge.providers.snapshot_build import REAL_EMBEDDING_MODEL
from app.modules.knowledge.providers.sql_runtime import SqlAlchemyEmbeddingControlAdapter
from app.modules.knowledge.providers.sql_stage import SqlAlchemyEmbeddingStageStore
from app.modules.knowledge_sets.generation import claim_generation_run
from app.modules.knowledge_sets.models import KnowledgeDocumentVersion, KnowledgeGenerationRun
from app.modules.knowledge_sets.provider_runtime import _generation_input
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_knowledge_generation import COURSE_ID, _teacher_agent_with_source
from tests.test_knowledge_generation_materialization import _create_generation_run
from tests.test_wave4_embedding_product_publication import (
    _confirm,
    _CountingRealProvider,
    _OwnerFixture,
    _policy,
)

GROUP_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"


def test_owned_rename_is_cas_idempotent_without_content_or_generation_change(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, _settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    _, csrf = login(client, "bowen")
    uploaded = client.post(
        f"/api/v1/groups/{GROUP_ID}/knowledge-documents",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
        files={"file": ("before.md", b"# Original source\n", "text/markdown")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["document"]["id"]

    def content_fingerprint() -> tuple[Any, ...]:
        with database.session() as db:
            document = db.get(KnowledgeDocument, document_id)
            assert document is not None
            return (
                document.stored_file_id,
                document.content_hash,
                document.content_version_seq,
                document.index_revision,
                document.authorization_epoch,
                db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)),
                db.scalar(select(func.count()).select_from(Job)),
            )

    before = content_fingerprint()
    url = f"/api/v1/knowledge-documents/{document_id}:rename"
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}
    body = {"expected_filename": "before.md", "filename": "after.md"}
    renamed = client.post(url, headers=headers, json=body)
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["id"] == document_id
    assert renamed.json()["source_filename"] == "after.md"
    replay = client.post(url, headers=headers, json=body)
    assert replay.status_code == 200 and replay.json() == renamed.json()
    stale = client.post(url, headers={**headers, "Idempotency-Key": str(uuid4())}, json=body)
    assert stale.status_code == 409
    assert content_fingerprint() == before
    with database.session() as db:
        retained = db.scalars(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        ).all()
        assert [(version.version_seq, version.source_filename) for version in retained] == [
            (1, "before.md")
        ]
    assert (
        client.get(f"/api/v1/knowledge-documents/{document_id}/download").content
        == b"# Original source\n"
    )

    _, teacher_csrf = login(client, "maya")
    denied = client.post(
        url,
        headers={"X-CSRF-Token": teacher_csrf, "Idempotency-Key": str(uuid4())},
        json={"expected_filename": "after.md", "filename": "taken.md"},
    )
    assert denied.status_code == 404
    assert content_fingerprint() == before


def test_rename_keeps_running_generation_authorized_and_exact_input_unchanged(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    _agent_id, document_id, run_id, _set_id = _create_generation_run(client, database)
    _, csrf = login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        original_name = document.source_filename
        claim_token = claim_generation_run(db, run_id)
        count_before = db.scalar(select(func.count()).select_from(KnowledgeGenerationRun))
    assert claim_token is not None
    before = _generation_input(database.session_factory, run_id, claim_token, settings)[3]
    response = client.post(
        f"/api/v1/knowledge-documents/{document_id}:rename",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
        json={"expected_filename": original_name, "filename": "Renamed lesson.md"},
    )
    assert response.status_code == 200, response.text
    after = _generation_input(database.session_factory, run_id, claim_token, settings)[3]
    assert after == before
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(KnowledgeGenerationRun)) == count_before


def test_http_rename_preserves_accepted_embedding_manifest_and_publishes_without_resending(
    app_bundle: Any, client: TestClient
) -> None:
    _app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    _, csrf = login(client, "maya")
    _agent_id, version_id, revision, document_id = _teacher_agent_with_source(client, csrf)
    fixture = _OwnerFixture(database, settings.resolved_data_root, COURSE_ID, None, version_id)

    def current_build() -> Any:
        return prepare_real_snapshot_build(
            database,
            settings.resolved_data_root,
            course_id=COURSE_ID,
            group_id=None,
            agent_version_id=version_id,
            expected_revision=revision,
        )

    build = current_build()
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
    control = SqlAlchemyEmbeddingControlAdapter(
        database,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build.manifest_hash,
        model_key=REAL_EMBEDDING_MODEL,
    )
    stages = SqlAlchemyEmbeddingStageStore(database)
    accepted_provider = _CountingRealProvider()
    for batch in plan_embedding_batches(build).batches:
        operation = control.create_prepared(
            _reservation_request(
                batch,
                scope_id=build.build_id,
                attempt_no=1,
                provider_operation="embedding",
                price_cny_per_million=0.5,
            )
        )
        control.reserve(operation)
        control.mark_sending(operation.id)
        value = accepted_provider.embed_batch(batch)
        stages.stage_accepted(
            AcceptedEmbeddingStageV1.from_result(
                operation.id, value, response_hash=_response_hash(value)
            )
        )

    response = client.post(
        f"/api/v1/knowledge-documents/{document_id}:rename",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())},
        json={"expected_filename": "lesson.md", "filename": "Renamed lesson.md"},
    )
    assert response.status_code == 200, response.text
    fresh = current_build()
    assert fresh.manifest_hash == build.manifest_hash
    provider = _CountingRealProvider()
    result = run_confirmed_real_embedding_publication(
        database,
        data_root=settings.resolved_data_root,
        course_id=COURSE_ID,
        group_id=None,
        agent_version_id=version_id,
        expected_revision=revision,
        policy=policy,
        manifest=manifest,
        confirmation=confirmation,
        build=fresh,
        provider=provider,
    )
    assert result.status == "succeeded"
    assert provider.call_count == 0
    with database.session() as db:
        assert db.get(KnowledgeSnapshot, build.knowledge_snapshot_id) is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(ProviderOperation)
                .where(ProviderOperation.scope_id == build.build_id)
            )
            == accepted_provider.call_count
        )
        assert db.get(KnowledgeDocument, document_id).source_filename == "Renamed lesson.md"
