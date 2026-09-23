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
from uuid import UUID, uuid4

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
    ProviderOperation,
    StoredFile,
)
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.demo_acceptance.schemas import DemoAcceptanceRunCreateRequest
from app.modules.demo_acceptance.service import create_acceptance_run
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge.files import write_atomic
from app.modules.knowledge.markdown import normalize_markdown
from app.modules.knowledge.providers.adapters import (
    DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH,
    DashScopeEmbeddingAdapter,
    DashScopeEmbeddingConfig,
    EmbeddingTransportResponse,
)
from app.modules.knowledge.providers.embedding import ValidatedEmbeddingBatchV1
from app.modules.knowledge.providers.outbound_guard import (
    scan_real_embedding_texts,
)
from app.modules.knowledge.providers.packing import (
    EmbeddingBatchV1,
    plan_embedding_batches,
)
from app.modules.knowledge.providers.product_publication import (
    ProductPublicationError,
    ensure_real_embedding_export_manifest,
    prepare_real_snapshot_build,
    require_exact_confirmation,
    run_confirmed_real_embedding_publication,
)
from app.modules.knowledge.providers.query_embedding import persisted_snapshot_identity
from app.modules.knowledge.providers.query_manifest import ensure_real_query_export_manifest
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
from app.seed import TEACHER_ID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Table, func, select, update

from tests.conftest import login
from tests.persona_fixtures import confirmed_persona_fields
from tests.test_wave1_agents_knowledge import GROUP_DEMO_ID, _confirm_persona, _headers


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
        "https://"
        + "fixture.cn-beijing.maas."
        + "aliyuncs.com"
        + DEFAULT_DASHSCOPE_EMBEDDING_ENDPOINT_PATH
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


def test_snapshot_publish_binding_is_closed_and_call1_only() -> None:
    from app.modules.agents.schemas import PublishAgentVersionRequest

    assert PublishAgentVersionRequest(expected_revision=2).model_dump(exclude_none=True) == {
        "expected_revision": 2
    }
    with pytest.raises(ValidationError):
        PublishAgentVersionRequest(
            expected_revision=2,
            acceptance_run_id=UUID("00000000-0000-4000-8000-000000000008"),
        )
    with pytest.raises(ValidationError):
        PublishAgentVersionRequest(
            expected_revision=2,
            acceptance_run_id=UUID("00000000-0000-4000-8000-000000000008"),
            call_no=2,
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


@pytest.mark.parametrize(
    "value",
    (
        "api_key: fixture-secret",
        "secret",
        "Authorization: Bearer fixture-token",
        "password = fixture-password",
        "student_id: 123456",
        '{"student_id": "123456"}',
        "private identity: a student",
        "student@example.invalid",
        "13800138000",
        "01234567-89ab-cdef-0123-456789abcdef",
    ),
)
def test_real_embedding_outbound_boundary_does_not_scan_authored_text(value: str) -> None:
    scan_real_embedding_texts((value,), field_name="fixture")


def test_real_embedding_outbound_guard_keeps_general_content_available() -> None:
    scan_real_embedding_texts(
        (
            "A general lesson discusses privacy, identity, account security, "
            "passwords, credentials, authorization, secret histories, and API keys "
            "without carrying private records."
        ),
        field_name="lesson",
    )


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


def test_partial_accepted_stages_continue_only_not_sent_batches(tmp_path: Path) -> None:
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
    assert len(plan.batches) == 2
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
    for missing_batch in plan.batches[1:]:
        missing = control.create_prepared(
            _reservation_request(
                missing_batch,
                scope_id=build.build_id,
                attempt_no=1,
                provider_operation="embedding",
                price_cny_per_million=0.5,
            )
        )
        control.reserve(missing)
        control.mark_sending(missing.id)
        control.mark_not_sent(missing.id)
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
    assert provider.call_count == 1
    operations = ProviderRepository(fixture.database).operations(scope_id=build.build_id)
    assert len(operations) == 3
    assert all(
        operation.state == "succeeded" for operation in operations if operation.state != "not_sent"
    )
    fixture.database.dispose()


def test_bound_snapshot_multibatch_fails_before_operation_or_provider(
    tmp_path: Path,
) -> None:
    source = "\n\n".join(f"# Section {index}\n\n" + "x " * 600 for index in range(11)).encode()
    fixture = _make_fixture(tmp_path, source=source)
    build = _build(fixture)
    policy = _policy()
    manifest, confirmation = _confirm(fixture, build, policy)
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
            acceptance_run_id="00000000-0000-4000-8000-000000000008",
            call_no=1,
            target_agent_id="00000000-0000-4000-8000-000000000009",
            target_version_id=fixture.agent_version_id,
        )
    assert raised.value.code == "acceptance_binding_multibatch"
    assert provider.call_count == 0
    assert ProviderRepository(fixture.database).operations(scope_id=build.build_id) == ()
    fixture.database.dispose()


def test_endpoint_preflight_fails_and_zero_cost_cap_still_publishes(tmp_path: Path) -> None:
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
    result = run_confirmed_real_embedding_publication(
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
    assert result.status == "succeeded"
    assert provider.call_count == len(result.plan.batches)
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
    _student, csrf = login(client, "bowen")
    created = client.post(
        f"/api/v1/groups/{GROUP_DEMO_ID}/agents",
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
        f"/api/v1/groups/{GROUP_DEMO_ID}/knowledge-documents",
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
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        acceptance = create_acceptance_run(
            db,
            actor_user_id=TEACHER_ID,
            request=DemoAcceptanceRunCreateRequest(
                fixture_hash="a" * 64,
                target_agent_id=UUID(agent["id"]),
                target_version_id=UUID(version_id),
            ),
        )
        acceptance_run_id = str(acceptance.id)
    snapshot_publish_body = {
        "expected_revision": 2,
        "acceptance_run_id": acceptance_run_id,
        "call_no": 1,
    }
    first = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=publish_headers,
        json=snapshot_publish_body,
    )
    assert first.status_code == 409, first.text
    first_body = first.json()
    assert first_body["code"] == "provider_confirmation_required"
    public_error = json.dumps(first_body, ensure_ascii=False).casefold()
    assert "manifest_hash" not in public_error
    assert "dashscope" not in public_error
    assert REAL_EMBEDDING_MODEL not in public_error
    assert "endpoint" not in public_error
    assert transport.calls == []

    _teacher, teacher_csrf = login(client, "maya")
    pending = client.get(f"/api/v1/provider/data-call/pending/agent-versions/{version_id}")
    assert pending.status_code == 200, pending.text
    pending_body = pending.json()
    assert pending_body["agent_version_id"] == version_id
    assert len(pending_body["items"]) == 1
    pending_item = pending_body["items"][0]
    assert set(pending_item) == {
        "manifest_hash",
        "confirmation_revision",
        "confirmed",
    }
    manifest_hash = pending_item["manifest_hash"]
    assert isinstance(manifest_hash, str) and len(manifest_hash) == 64
    assert pending_item["confirmed"] is False
    pending_public = json.dumps(pending_body, ensure_ascii=False).casefold()
    for forbidden in (
        "dashscope",
        "text-embedding",
        "endpoint",
        "policy_hash",
        "workspace",
    ):
        assert forbidden not in pending_public
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

    _student, retry_csrf = login(client, "bowen")
    published = client.post(
        f"/api/v1/agent-versions/{version_id}/publish",
        headers=_headers(
            retry_csrf,
            **{"Idempotency-Key": "real-route-publish-version-001"},
        ),
        json=snapshot_publish_body,
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

    with database.engine.connect() as connection:
        bound = connection.execute(
            select(
                ProviderOperation.acceptance_run_id,
                ProviderOperation.call_no,
                ProviderOperation.request_count,
                ProviderOperation.charged_request_count,
            ).where(ProviderOperation.export_manifest_hash == manifest_hash)
        ).one()
        assert bound == (acceptance_run_id, 1, 1, 1)

        with database.session() as db:
            snapshot = db.scalar(
                select(KnowledgeSnapshot).where(KnowledgeSnapshot.agent_version_id == version_id)
            )
            assert snapshot is not None
            assert snapshot.embedding_provider == REAL_EMBEDDING_PROVIDER
            assert snapshot.embedding_key == REAL_EMBEDDING_MODEL
            assert snapshot.embedding_region == REAL_EMBEDDING_REGION
            assert snapshot.embedding_dimension == REAL_EMBEDDING_DIMENSION
        assert snapshot.embedding_policy_version == REAL_EMBEDDING_POLICY_VERSION
        version = db.get(AgentVersion, version_id)
        group = db.get(Group, GROUP_DEMO_ID)
        assert version is not None and version.persona_spec_hash
        assert group is not None
        query_plan = ensure_real_query_export_manifest(
            database,
            db=db,
            scope_id="route-debate-scope",
            turn_id="route-turn-1",
            course_id=group.course_id,
            group_id=group.id,
            agent_version_id=version.id,
            snapshot_id=snapshot.id,
            identity=persisted_snapshot_identity(snapshot),
            transcript_hash="b" * 64,
            persona_spec_hash=version.persona_spec_hash,
            subqueries=(("viewpoint", "  accountable recommendation governance  "),),
            policy=policy,
        )
        assert query_plan.query_texts == ("accountable recommendation governance",)
        assert query_plan.manifest.provider_operation == "embedding_query"
        assert tuple(field.field_class for field in query_plan.manifest.fields) == (
            "current_evidence_excerpt",
        )
    operations = ProviderRepository(database).operations()
    assert operations and all(operation.state == "succeeded" for operation in operations)


def _ordered_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
