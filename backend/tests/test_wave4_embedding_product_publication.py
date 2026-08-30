"""Focused product-owned real embedding publication orchestration tests."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import (
    Agent,
    AgentVersion,
    AgentVersionDocument,
    Course,
    Group,
    KnowledgeDocument,
    KnowledgeSnapshot,
    ProviderExportManifest,
    StoredFile,
)
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.knowledge.files import write_atomic
from app.modules.knowledge.markdown import normalize_markdown
from app.modules.knowledge.providers.adapters import (
    DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportResponse,
)
from app.modules.knowledge.providers.embedding import ValidatedEmbeddingBatchV1
from app.modules.knowledge.providers.packing import (
    EmbeddingBatchV1,
    EmbeddingPlanError,
    plan_embedding_batches,
)
from app.modules.knowledge.providers.product_publication import (
    ProductPublicationError,
    ensure_real_embedding_export_manifest,
    prepare_real_snapshot_build,
    require_exact_confirmation,
    run_confirmed_real_embedding_publication,
)
from app.modules.knowledge.providers.runtime import (
    AcceptedEmbeddingStageV1,
    _reservation_request,
    _response_hash,
)
from app.modules.knowledge.providers.snapshot_build import (
    REAL_EMBEDDING_DIMENSION,
    REAL_EMBEDDING_MODEL,
    REAL_EMBEDDING_POLICY_VERSION,
    REAL_EMBEDDING_PROVIDER,
    REAL_EMBEDDING_REGION,
    SnapshotBuildV1,
)
from app.modules.knowledge.providers.sql_runtime import SqlAlchemyEmbeddingControlAdapter
from app.modules.knowledge.providers.sql_stage import SqlAlchemyEmbeddingStageStore
from app.providers.control import (
    ExportConfirmationV1,
    ExportManifestV1,
    ProviderPolicySnapshotV1,
    confirm_export_manifest,
    sha256_hex,
)
from app.providers.control_repository import ProviderRepository
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, func, select, update

from tests.conftest import login
from tests.persona_fixtures import confirmed_persona_fields
from tests.test_wave1_agents_knowledge import BOWEN_GROUP_ID, _confirm_persona, _headers


@dataclass(frozen=True)
class _OwnerFixture:
    database: Database
    data_root: Path
    course_id: str
    group_id: str
    agent_version_id: str


def _policy(
    *,
    policy_id: str = "provider-policy-v1",
    endpoint: str = (
        "https://fixture.cn-beijing.maas.aliyuncs.com" + DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH
    ),
) -> ProviderPolicySnapshotV1:
    digest = sha256_hex("policy-evidence")
    return ProviderPolicySnapshotV1(
        policy_id=policy_id,
        endpoint=endpoint,
        privacy_notice_retrieved_at="2026-08-30T00:00:00Z",
        privacy_notice_sha256=digest,
        service_terms_retrieved_at="2026-08-30T00:00:00Z",
        service_terms_sha256=digest,
        faq_retrieved_at="2026-08-30T00:00:00Z",
        faq_sha256=digest,
        no_training_basis="payg-api-terms-2026-08-30",
        prompt_response_logging_disabled=True,
        inference_log_backflow_disabled=True,
        optional_content_logging_disabled=True,
        service_improvement_disabled=True,
        storage_disclosed=True,
        retention_setting="unknown",
    )


def _make_fixture(
    tmp_path: Path, *, source: bytes = b"# Lesson\n\nA bounded lesson."
) -> _OwnerFixture:
    database = Database(f"sqlite:///{tmp_path / 'product-publication.sqlite3'}", tmp_path)
    database.initialize_schema()
    course_id = str(uuid4())
    group_id = str(uuid4())
    agent_id = str(uuid4())
    version_id = str(uuid4())
    document_id = str(uuid4())
    stored_file_id = str(uuid4())
    now = datetime.now(UTC)
    persona = confirmed_persona_fields("Publication Agent", now, revision=1)
    normalized = normalize_markdown("lesson.md", source)
    relative_path = f"groups/{group_id}/knowledge/{document_id}/source.md"
    write_atomic(tmp_path, relative_path, source)
    with database.session() as session:
        session.add(
            Course(
                id=course_id,
                code=f"course-{course_id[:8]}",
                name="Product Publication Course",
                created_at=now,
            )
        )
        session.add(
            Group(id=group_id, course_id=course_id, name="Publication Group", created_at=now)
        )
        session.add(
            Agent(
                id=agent_id,
                group_id=group_id,
                name="Publication Agent",
                description="",
                metadata_revision=0,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="draft",
                revision=1,
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                created_at=now,
                updated_at=now,
                **persona,
            )
        )
        session.add(
            StoredFile(
                id=stored_file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256=hashlib.sha256(source).hexdigest(),
                size_bytes=len(source),
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            KnowledgeDocument(
                id=document_id,
                group_id=group_id,
                source_filename="lesson.md",
                stored_file_id=stored_file_id,
                char_count=normalized.char_count,
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=normalized.content_hash,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AgentVersionDocument(
                agent_version_id=version_id,
                document_id=document_id,
                enabled=True,
                order_index=0,
            )
        )
    return _OwnerFixture(database, tmp_path, course_id, group_id, version_id)


class _CountingRealProvider:
    provider = REAL_EMBEDDING_PROVIDER
    region = REAL_EMBEDDING_REGION
    model_key = REAL_EMBEDDING_MODEL
    dimension = REAL_EMBEDDING_DIMENSION
    policy_version = REAL_EMBEDDING_POLICY_VERSION

    def __init__(self) -> None:
        self.call_count = 0

    def embed_batch(self, batch: EmbeddingBatchV1) -> ValidatedEmbeddingBatchV1:
        self.call_count += 1
        vectors = tuple(tuple(0.0 for _ in range(self.dimension)) for _ in batch.items)
        return ValidatedEmbeddingBatchV1(
            build_id=batch.build_id,
            build_manifest_hash=batch.build_manifest_hash,
            batch_index=batch.batch_index,
            chunk_ids=batch.chunk_ids,
            vectors=vectors,
            model_key=self.model_key,
            dimension=self.dimension,
            embedding_provider=self.provider,
            embedding_region=self.region,
            policy_version=self.policy_version,
        )


class _CaptureTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> EmbeddingTransportResponse:
        del headers, timeout
        self.calls.append(dict(json))
        nested = json.get("input")
        assert isinstance(nested, dict)
        texts = nested.get("texts")
        assert isinstance(texts, list)
        return EmbeddingTransportResponse(
            200,
            {
                "model": REAL_EMBEDDING_MODEL,
                "data": [
                    {"index": index, "embedding": [0.0] * REAL_EMBEDDING_DIMENSION}
                    for index, _text in enumerate(texts)
                ],
            },
        )


def _build(fixture: _OwnerFixture) -> SnapshotBuildV1:
    with fixture.database.session() as session:
        return prepare_real_snapshot_build(
            session,
            fixture.data_root,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            expected_revision=1,
        )


def _confirm(
    fixture: _OwnerFixture, build: SnapshotBuildV1, policy: ProviderPolicySnapshotV1
) -> tuple[ExportManifestV1, ExportConfirmationV1]:
    ProviderRepository(fixture.database).save_policy_snapshot(
        policy,
        snapshot_id=str(uuid4()),
    )
    manifest = ensure_real_embedding_export_manifest(
        fixture.database,
        build,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
    )
    with fixture.database.engine.connect() as connection:
        row = (
            connection.execute(
                select(ProviderExportManifest.__table__).where(
                    ProviderExportManifest.__table__.c.manifest_hash == manifest.manifest_hash
                )
            )
            .mappings()
            .one()
        )
    confirmation = confirm_export_manifest(
        manifest,
        policy,
        confirmed_at="2026-08-31T00:00:00Z",
    )
    ProviderRepository(fixture.database).save_export_confirmation(str(row["id"]), confirmation)
    return manifest, confirmation


def test_real_build_is_deterministic_and_has_closed_identity(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    first = _build(fixture)
    second = _build(fixture)

    assert first == second
    assert first.knowledge_snapshot_id == second.knowledge_snapshot_id
    assert first.build_id == second.build_id
    assert first.embedding_identity.as_record() == {
        "provider": "dashscope",
        "model_key": "text-embedding-v4",
        "region": "cn-beijing",
        "dimension": 1024,
        "policy_version": "w4-embed-v1",
    }
    assert (
        first.documents[0].source_sha256
        == hashlib.sha256(b"# Lesson\n\nA bounded lesson.").hexdigest()
    )
    fixture.database.dispose()


def test_manifest_is_exact_owner_bound_and_idempotent(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    policy = _policy()
    ProviderRepository(fixture.database).save_policy_snapshot(policy, snapshot_id=str(uuid4()))
    first = ensure_real_embedding_export_manifest(
        fixture.database,
        build,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
    )
    second = ensure_real_embedding_export_manifest(
        fixture.database,
        build,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
    )

    assert first == second
    assert tuple(field.field_class for field in first.fields) == (
        "current_evidence_excerpt",
        "opaque_local_id",
    )
    assert first.fields[0].value_sha256 == _ordered_hash([chunk.text for chunk in build.chunks])
    assert first.fields[1].value_sha256 == _ordered_hash([chunk.chunk_id for chunk in build.chunks])
    with fixture.database.engine.connect() as connection:
        row = (
            connection.execute(
                select(ProviderExportManifest.__table__).where(
                    ProviderExportManifest.__table__.c.manifest_hash == first.manifest_hash
                )
            )
            .mappings()
            .one()
        )
        assert row["course_id"] == fixture.course_id
        assert row["group_id"] == fixture.group_id
        assert row["agent_version_id"] == fixture.agent_version_id
        count = connection.execute(
            select(func.count()).select_from(ProviderExportManifest)
        ).scalar_one()
        assert count == 1
    wrong_policy = _policy(policy_id="provider-policy-v2")
    wrong_policy_id = ProviderRepository(fixture.database).save_policy_snapshot(
        wrong_policy,
        snapshot_id=str(uuid4()),
    )
    manifest_table = cast(Table, ProviderExportManifest.__table__)
    with fixture.database.engine.begin() as connection:
        connection.execute(
            update(manifest_table)
            .where(manifest_table.c.manifest_hash == first.manifest_hash)
            .values(policy_snapshot_id=wrong_policy_id)
        )
    with pytest.raises(ProductPublicationError) as raised:
        ensure_real_embedding_export_manifest(
            fixture.database,
            build,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            policy=policy,
        )
    assert raised.value.code == "manifest_owner_drift"
    fixture.database.dispose()


def test_unconfirmed_publication_never_calls_injected_provider(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    policy = _policy()
    ProviderRepository(fixture.database).save_policy_snapshot(policy, snapshot_id=str(uuid4()))
    manifest = ensure_real_embedding_export_manifest(
        fixture.database,
        build,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
    )
    provider = _CountingRealProvider()

    with pytest.raises(ProductPublicationError) as raised:
        run_confirmed_real_embedding_publication(
            fixture.database,
            data_root=fixture.data_root,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            policy=policy,
            manifest=manifest,
            provider=provider,
        )
    assert raised.value.code == "provider_confirmation_required"
    assert provider.call_count == 0
    fixture.database.dispose()


def test_confirmed_sql_publication_uses_injected_provider_and_1024_snapshot(
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
    provider = _CountingRealProvider()

    result = run_confirmed_real_embedding_publication(
        fixture.database,
        data_root=fixture.data_root,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
        manifest=manifest,
        confirmation=confirmation,
        build=build,
        provider=provider,
    )
    assert result.status == "succeeded"
    assert provider.call_count == len(result.plan.batches)
    with fixture.database.session() as session:
        snapshot = session.scalar(select(KnowledgeSnapshot))
        assert snapshot is not None
        assert snapshot.embedding_provider == REAL_EMBEDDING_PROVIDER
        assert snapshot.embedding_region == REAL_EMBEDDING_REGION
        assert snapshot.embedding_key == REAL_EMBEDDING_MODEL
        assert snapshot.embedding_dimension == REAL_EMBEDDING_DIMENSION
        assert snapshot.embedding_policy_version == REAL_EMBEDDING_POLICY_VERSION
    fixture.database.dispose()


def test_complete_accepted_stages_resume_without_provider_call(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
    control = SqlAlchemyEmbeddingControlAdapter(
        fixture.database,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build.manifest_hash,
        model_key=REAL_EMBEDDING_MODEL,
    )
    stages = SqlAlchemyEmbeddingStageStore(fixture.database)
    plan = plan_embedding_batches(build)
    for batch in plan.batches:
        request = _reservation_request(
            batch,
            scope_id=build.build_id,
            attempt_no=1,
            provider_operation="embedding",
            price_cny_per_million=0.5,
        )
        operation = control.create_prepared(request)
        control.reserve(operation)
        control.mark_sending(operation.id)
        value = ValidatedEmbeddingBatchV1(
            build_id=batch.build_id,
            build_manifest_hash=batch.build_manifest_hash,
            batch_index=batch.batch_index,
            chunk_ids=batch.chunk_ids,
            vectors=tuple(tuple(0.0 for _ in range(REAL_EMBEDDING_DIMENSION)) for _ in batch.items),
            model_key=REAL_EMBEDDING_MODEL,
            dimension=REAL_EMBEDDING_DIMENSION,
            embedding_provider=REAL_EMBEDDING_PROVIDER,
            embedding_region=REAL_EMBEDDING_REGION,
            policy_version=REAL_EMBEDDING_POLICY_VERSION,
        )
        stages.stage_accepted(
            AcceptedEmbeddingStageV1.from_result(
                operation.id,
                value,
                response_hash=_response_hash(value),
            )
        )

    provider = _CountingRealProvider()
    result = run_confirmed_real_embedding_publication(
        fixture.database,
        data_root=fixture.data_root,
        course_id=fixture.course_id,
        group_id=fixture.group_id,
        agent_version_id=fixture.agent_version_id,
        policy=policy,
        manifest=manifest,
        confirmation=confirmation,
        build=build,
        provider=provider,
    )
    assert result.status == "succeeded"
    assert provider.call_count == 0
    fixture.database.dispose()


def test_partial_accepted_stages_fail_closed_without_resending(tmp_path: Path) -> None:
    source = "\n\n".join(f"# Section {index}\n\n" + "x " * 600 for index in range(11)).encode()
    fixture = _make_fixture(tmp_path, source=source)
    build = _build(fixture)
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
    control = SqlAlchemyEmbeddingControlAdapter(
        fixture.database,
        policy_hash=policy.policy_hash,
        export_manifest_hash=manifest.manifest_hash,
        build_manifest_hash=build.manifest_hash,
        model_key=REAL_EMBEDDING_MODEL,
    )
    stages = SqlAlchemyEmbeddingStageStore(fixture.database)
    plan = plan_embedding_batches(build)
    assert len(plan.batches) > 1
    batch = plan.batches[0]
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
    value = ValidatedEmbeddingBatchV1(
        build_id=batch.build_id,
        build_manifest_hash=batch.build_manifest_hash,
        batch_index=batch.batch_index,
        chunk_ids=batch.chunk_ids,
        vectors=tuple(tuple(0.0 for _ in range(REAL_EMBEDDING_DIMENSION)) for _ in batch.items),
        model_key=REAL_EMBEDDING_MODEL,
        dimension=REAL_EMBEDDING_DIMENSION,
        embedding_provider=REAL_EMBEDDING_PROVIDER,
        embedding_region=REAL_EMBEDDING_REGION,
        policy_version=REAL_EMBEDDING_POLICY_VERSION,
    )
    stages.stage_accepted(
        AcceptedEmbeddingStageV1.from_result(
            operation.id,
            value,
            response_hash=_response_hash(value),
        )
    )
    provider = _CountingRealProvider()

    with pytest.raises(ProductPublicationError) as raised:
        run_confirmed_real_embedding_publication(
            fixture.database,
            data_root=fixture.data_root,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            policy=policy,
            manifest=manifest,
            confirmation=confirmation,
            build=build,
            provider=provider,
        )
    assert raised.value.code == "partial_embedding_recovery_required"
    assert provider.call_count == 0
    fixture.database.dispose()


def test_endpoint_and_budget_preflight_fail_without_provider_call(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    unsafe_policy = _policy(endpoint="https://evil.example")
    manifest, confirmation = _confirm(fixture, build, unsafe_policy)
    provider = _CountingRealProvider()

    with pytest.raises(ProductPublicationError) as endpoint_error:
        run_confirmed_real_embedding_publication(
            fixture.database,
            data_root=fixture.data_root,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            policy=unsafe_policy,
            manifest=manifest,
            confirmation=confirmation,
            build=build,
            provider=provider,
        )
    assert endpoint_error.value.code == "provider_endpoint_invalid"
    assert provider.call_count == 0

    valid_policy = _policy(policy_id="provider-policy-v2")
    valid_manifest, valid_confirmation = _confirm(fixture, build, valid_policy)
    with pytest.raises(EmbeddingPlanError):
        run_confirmed_real_embedding_publication(
            fixture.database,
            data_root=fixture.data_root,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
            policy=valid_policy,
            manifest=valid_manifest,
            confirmation=valid_confirmation,
            build=build,
            provider=provider,
            cost_cap_cny=0,
        )
    assert provider.call_count == 0
    fixture.database.dispose()


def test_confirmation_checks_persisted_exact_pair(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    build = _build(fixture)
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
    assert (
        require_exact_confirmation(
            fixture.database,
            manifest,
            policy,
            confirmation=confirmation,
            course_id=fixture.course_id,
            group_id=fixture.group_id,
            agent_version_id=fixture.agent_version_id,
        )
        == confirmation
    )
    stale = ExportConfirmationV1(
        manifest_hash=manifest.manifest_hash,
        policy_hash=policy.policy_hash,
        confirmed_at=confirmation.confirmed_at,
        confirmation_revision=confirmation.confirmation_revision + 1,
    )
    with pytest.raises(ProductPublicationError) as raised:
        require_exact_confirmation(fixture.database, manifest, policy, confirmation=stale)
    assert raised.value.code == "provider_confirmation_stale"
    fixture.database.dispose()


def test_student_publish_route_requires_exact_teacher_confirmation_then_publishes_1024(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = cast(FastAPI, client.app)
    database = cast(Database, app.state.database)
    settings = app.state.settings
    _student, csrf = login(client, "student-bowen-1")
    created = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/agents",
        headers=_headers(csrf, **{"Idempotency-Key": "real-route-agent-create-001"}),
        json={"name": "Real Route Agent", "description": "Exact confirmation fixture"},
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    version_id = agent["versions"][0]["id"]
    raw = confirmed_persona_fields("Real Route Agent", datetime.now(UTC))["agent_md"]
    updated = client.patch(
        f"/api/v1/agent-versions/{version_id}",
        headers=_headers(csrf),
        json={
            "expected_revision": 0,
            "agent_md": raw,
            "avatar_config": agent["versions"][0]["avatar_config"],
        },
    )
    assert updated.status_code == 200, updated.text
    uploaded = client.post(
        f"/api/v1/groups/{BOWEN_GROUP_ID}/knowledge-documents",
        headers=_headers(csrf, **{"Idempotency-Key": "real-route-doc-upload-001"}),
        data={"target_agent_version_id": version_id, "expected_revision": "1"},
        files={
            "file": (
                "lesson.md",
                b"# Formal lesson\n\nEvidence-aware recommendations need accountable governance.",
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    _confirm_persona(client, csrf, version_id, expected_revision=2)

    config = DashScopeEmbeddingConfig(
        api_key="fixture-secret-never-enters-payload",
        workspace_id="fixture",
    )
    policy = _policy(endpoint=config.resolved_endpoint)
    ProviderRepository(database).save_policy_snapshot(
        policy,
        snapshot_id="real-route-policy",
    )
    settings.embedding_provider = "dashscope"
    settings.dashscope_api_key = "fixture-secret-never-enters-payload"
    settings.dashscope_workspace_id = "fixture"
    settings.dashscope_region = "cn-beijing"
    settings.provider_policy_hash = policy.policy_hash
    transport = _CaptureTransport()
    adapter = DashScopeEmbeddingAdapter(config, transport)
    agents_router_module = importlib.import_module("app.modules.agents.router")
    monkeypatch.setattr(
        agents_router_module,
        "select_embedding_provider",
        lambda _settings: adapter,
    )
    publish_headers = _headers(
        csrf,
        **{"Idempotency-Key": "real-route-publish-version-001"},
    )
    first = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=publish_headers,
        json={"expected_revision": 2},
    )
    assert first.status_code == 409, first.text
    first_body = first.json()
    assert first_body["code"] == "provider_confirmation_required"
    manifest_hash = first_body["details"]["manifest_hash"]
    assert isinstance(manifest_hash, str) and len(manifest_hash) == 64
    assert transport.calls == []

    _teacher, teacher_csrf = login(client, "teacher-demo")
    disclosure = client.get(
        "/api/v1/provider/data-call/disclosure",
        params={"manifest_hash": manifest_hash},
    )
    assert disclosure.status_code == 200, disclosure.text
    disclosed = disclosure.json()
    assert disclosed["manifest_hash"] == manifest_hash
    confirmed = client.post(
        "/api/v1/provider/data-call/disclosure/confirm",
        headers=_headers(teacher_csrf),
        json={
            "policy_hash": policy.policy_hash,
            "manifest_hash": manifest_hash,
            "expected_revision": disclosed["confirmation_revision"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    _student, retry_csrf = login(client, "student-bowen-1")
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(
            retry_csrf,
            **{"Idempotency-Key": "real-route-publish-version-001"},
        ),
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    assert len(transport.calls) == 1
    payload = transport.calls[0]
    assert payload["model"] == REAL_EMBEDDING_MODEL
    assert payload["parameters"] == {"dimension": 1024}
    assert "api_key" not in payload and "workspace_id" not in payload
    public_body = json.dumps(published.json(), ensure_ascii=False).casefold()
    assert "dashscope" not in public_body
    assert REAL_EMBEDDING_MODEL not in public_body

    with database.session() as db:
        snapshot = db.scalar(select(KnowledgeSnapshot).where(KnowledgeSnapshot.id.is_not(None)))
        assert snapshot is not None
        assert snapshot.embedding_provider == REAL_EMBEDDING_PROVIDER
        assert snapshot.embedding_key == REAL_EMBEDDING_MODEL
        assert snapshot.embedding_region == REAL_EMBEDDING_REGION
        assert snapshot.embedding_dimension == REAL_EMBEDDING_DIMENSION
        assert snapshot.embedding_policy_version == REAL_EMBEDDING_POLICY_VERSION
    operations = ProviderRepository(database).operations()
    assert operations and all(operation.state == "succeeded" for operation in operations)


def _ordered_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
