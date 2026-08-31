"""Teacher disclosure and confirmation tests for ProviderDataCallV1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError, error_body, unauthenticated
from app.core.models import Agent, AgentVersion, Course, CourseMember, ProviderOperation, User
from app.modules.auth.dependencies import require_auth, require_authenticated_mutation
from app.modules.provider_disclosure import (
    InMemoryProviderDisclosureStore,
    ProviderDataCallConfirmationRequestV1,
    ProviderDisclosureError,
    ProviderDisclosureService,
    SqlAlchemyProviderDisclosureStore,
    router,
)
from app.providers.control import (
    FIXED_MODELS,
    ExportFieldV1,
    ExportManifestV1,
    PolicyValidationError,
    ProviderPolicySnapshotV1,
)
from app.providers.control_repository import ProviderRepository
from app.seed import COURSE_ID, GROUP_BOWEN_ID, TEACHER_ID
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import login


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _policy(**changes: object) -> ProviderPolicySnapshotV1:
    values: dict[str, object] = {
        "privacy_notice_retrieved_at": "2026-08-30T00:00:00Z",
        "privacy_notice_sha256": _digest("privacy"),
        "service_terms_retrieved_at": "2026-08-30T00:00:00Z",
        "service_terms_sha256": _digest("terms"),
        "faq_retrieved_at": "2026-08-30T00:00:00Z",
        "faq_sha256": _digest("faq"),
        "no_training_basis": "payg-api-terms-2026-08-30",
        "prompt_response_logging_disabled": True,
        "inference_log_backflow_disabled": True,
        "optional_content_logging_disabled": True,
        "service_improvement_disabled": True,
        "storage_disclosed": True,
        "retention_setting": "unknown",
    }
    values.update(changes)
    return ProviderPolicySnapshotV1(**values)


def _manifest(
    policy: ProviderPolicySnapshotV1,
    *,
    scope_id: str = "debate-scope",
    operation_revision: int = 1,
) -> ExportManifestV1:
    return ExportManifestV1(
        scope_id=scope_id,
        provider_operation="llm_debate",
        model_key=FIXED_MODELS["llm_debate"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest("build"),
        persona_spec_hash=_digest("persona"),
        fields=(
            ExportFieldV1("topic_and_platform_rules", _digest("rules")),
            ExportFieldV1("current_evidence_excerpt", _digest("evidence")),
        ),
        operation_revision=operation_revision,
    )


def _query_manifest(
    policy: ProviderPolicySnapshotV1,
    *,
    scope_id: str = "debate-query-scope",
    operation_revision: int = 1,
) -> ExportManifestV1:
    return ExportManifestV1(
        scope_id=scope_id,
        provider_operation="embedding_query",
        model_key=FIXED_MODELS["embedding_query"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest(scope_id + "-build"),
        persona_spec_hash=_digest(scope_id + "-persona"),
        fields=(ExportFieldV1("current_evidence_excerpt", _digest(scope_id + "-query")),),
        operation_revision=operation_revision,
    )


def _embedding_manifest(
    policy: ProviderPolicySnapshotV1,
    *,
    scope_id: str = "publication-build-scope",
    operation_revision: int = 1,
) -> ExportManifestV1:
    return ExportManifestV1(
        scope_id=scope_id,
        provider_operation="embedding",
        model_key=FIXED_MODELS["embedding"],
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest(scope_id + "-build"),
        persona_spec_hash=_digest(scope_id + "-persona"),
        fields=(ExportFieldV1("current_evidence_excerpt", _digest(scope_id + "-text")),),
        operation_revision=operation_revision,
    )


def _service(
    *, policy: ProviderPolicySnapshotV1 | None = None
) -> tuple[
    ProviderDisclosureService,
    InMemoryProviderDisclosureStore,
    ProviderPolicySnapshotV1,
    ExportManifestV1,
]:
    selected_policy = policy or _policy()
    manifest = _manifest(selected_policy)
    store = InMemoryProviderDisclosureStore(selected_policy, manifest)
    return ProviderDisclosureService(store), store, selected_policy, manifest


def test_disclosure_has_exact_teacher_allowlist_and_no_provider_secrets() -> None:
    service, _store, policy, manifest = _service()

    response = service.disclose("teacher")
    public = response.disclosure.model_dump(mode="json")

    assert set(public) == {
        "supplier_display_name",
        "region",
        "purpose",
        "outbound_field_classes",
        "storage_fact",
        "no_training_basis",
        "retention_setting",
    }
    assert public["supplier_display_name"] == "Alibaba Cloud Model Studio"
    assert public["region"] == "cn-beijing"
    assert public["outbound_field_classes"] == [
        "topic_and_platform_rules",
        "current_evidence_excerpt",
    ]
    encoded = json.dumps(public, sort_keys=True).casefold()
    for forbidden in (
        FIXED_MODELS["llm_debate"],
        "https://" + "dashscope." + "aliyuncs.com",
        "workspace-id",
        "_".join(("api", "key")),
        "student-name",
        "absolute/path",
        "payload_json",
        "provider_operations",
        "teacher_note",
    ):
        assert forbidden.casefold() not in encoded
    assert response.policy_hash == policy.policy_hash
    assert response.manifest_hash == manifest.manifest_hash


def test_query_embedding_disclosure_is_exact_and_provider_neutral() -> None:
    policy = _policy()
    manifest = _query_manifest(policy)
    response = ProviderDisclosureService(
        InMemoryProviderDisclosureStore(policy, manifest)
    ).disclose("teacher")

    assert response.manifest_hash == manifest.manifest_hash
    assert response.disclosure.outbound_field_classes == ("current_evidence_excerpt",)
    assert "retrieval questions" in response.disclosure.purpose
    assert FIXED_MODELS["embedding_query"] not in json.dumps(response.model_dump(mode="json"))


def test_query_manifest_discovery_is_exact_and_teacher_course_bound() -> None:
    policy = _policy()
    manifest = _query_manifest(policy, operation_revision=3)
    store = InMemoryProviderDisclosureStore(policy, manifest)
    service = ProviderDisclosureService(store)

    pending = service.list_embedding_query_manifests("teacher", scope_id=manifest.scope_id)
    assert pending.model_dump(mode="json") == {
        "scope_id": manifest.scope_id,
        "items": [
            {
                "manifest_hash": manifest.manifest_hash,
                "turn_id": None,
                "confirmation_revision": 3,
                "confirmed": False,
            }
        ],
    }
    encoded = json.dumps(pending.model_dump(mode="json"), sort_keys=True).casefold()
    for forbidden in (
        FIXED_MODELS["embedding_query"],
        "endpoint",
        "workspace",
        "policy_hash",
        "build_manifest_hash",
        "persona_spec_hash",
        "fields_json",
        "course_id",
        "agent_version_id",
    ):
        assert forbidden.casefold() not in encoded

    service.confirm(
        ProviderDataCallConfirmationRequestV1(
            policy_hash=policy.policy_hash,
            manifest_hash=manifest.manifest_hash,
            expected_revision=3,
        ),
        actor_user_id="teacher",
        manifest_ref=manifest.manifest_hash,
    )
    confirmed = service.list_embedding_query_manifests("teacher", scope_id=manifest.scope_id)
    assert confirmed.items[0].confirmed is True
    assert confirmed.items[0].confirmation_revision == 3

    with pytest.raises(ProviderDisclosureError) as forbidden_result:
        service.list_embedding_query_manifests("student", scope_id=manifest.scope_id)
    assert forbidden_result.value.code == "forbidden"
    with pytest.raises(ProviderDisclosureError) as missing:
        service.list_embedding_query_manifests("teacher", scope_id="other-scope")
    assert missing.value.code == "forbidden"


def test_publication_manifest_discovery_does_not_require_provider_operation() -> None:
    policy = _policy()
    agent_version_id = "agent-version-publication-1"
    publication = _embedding_manifest(policy, operation_revision=4)
    store = InMemoryProviderDisclosureStore(
        policy,
        _manifest(policy),
        agent_version_id=agent_version_id,
        publication_manifests=(publication,),
    )
    service = ProviderDisclosureService(store)

    pending = service.list_embedding_manifests_for_agent_version(
        "teacher",
        agent_version_id=agent_version_id,
    )
    assert pending.model_dump(mode="json") == {
        "agent_version_id": agent_version_id,
        "items": [
            {
                "manifest_hash": publication.manifest_hash,
                "confirmation_revision": 4,
                "confirmed": False,
            }
        ],
    }
    # The compact publication DTO must not accidentally grow the query-turn
    # field or any server-side policy/provider/ledger fields.
    assert set(pending.items[0].model_dump(mode="json")) == {
        "manifest_hash",
        "confirmation_revision",
        "confirmed",
    }
    assert not hasattr(pending.items[0], "turn_id")
    encoded = json.dumps(pending.model_dump(mode="json"), sort_keys=True).casefold()
    for forbidden in (
        FIXED_MODELS["embedding"],
        "endpoint",
        "policy_hash",
        "provider_operation",
        "provider_operations",
        "course_id",
        "agent_version_id",
    ):
        if forbidden == "agent_version_id":
            # The response envelope intentionally carries the requested opaque
            # version id; no internal owner field is nested in each item.
            continue
        assert forbidden.casefold() not in encoded

    # Confirmation is optional at discovery time and does not change the
    # manifest's immutable revision.
    service.confirm(
        ProviderDataCallConfirmationRequestV1(
            policy_hash=policy.policy_hash,
            manifest_hash=publication.manifest_hash,
            expected_revision=4,
        ),
        actor_user_id="teacher",
        manifest_ref=publication.manifest_hash,
    )
    confirmed = service.list_embedding_manifests_for_agent_version(
        "teacher",
        agent_version_id=agent_version_id,
    )
    assert confirmed.items[0].confirmed is True
    assert confirmed.items[0].confirmation_revision == 4

    with pytest.raises(ProviderDisclosureError) as student:
        service.list_embedding_manifests_for_agent_version(
            "student",
            agent_version_id=agent_version_id,
        )
    assert student.value.code == "forbidden"
    with pytest.raises(ProviderDisclosureError) as missing:
        service.list_embedding_manifests_for_agent_version(
            "teacher",
            agent_version_id="missing-agent-version",
        )
    assert missing.value.code == "not_found"


@pytest.mark.parametrize(
    "changes",
    (
        {"account_product": "token_plan_personal"},
        {"account_product": "coding_plan"},
        {"prompt_response_logging_disabled": None},
        {"inference_log_backflow_disabled": False},
        {"optional_content_logging_disabled": None},
        {"service_improvement_disabled": False},
    ),
)
def test_unknown_personal_coding_or_privacy_control_is_rejected_before_disclosure(
    changes: dict[str, object],
) -> None:
    with pytest.raises(PolicyValidationError):
        _policy(**changes)


def test_teacher_only_confirmation_is_revision_and_hash_cas_bound() -> None:
    service, store, policy, manifest = _service()
    request = ProviderDataCallConfirmationRequestV1(
        policy_hash=policy.policy_hash,
        manifest_hash=manifest.manifest_hash,
        expected_revision=manifest.operation_revision,
    )

    confirmed = service.confirm(request, actor_user_id="teacher")
    assert confirmed.confirmation_revision == 1
    assert confirmed.revision == 1
    assert service.disclose("teacher").confirmation_revision == 1

    with pytest.raises(ProviderDisclosureError) as stale:
        service.confirm(
            request.model_copy(update={"expected_revision": 2}),
            actor_user_id="teacher",
        )
    assert stale.value.code == "provider_preflight_stale"
    with pytest.raises(ProviderDisclosureError) as forbidden:
        service.confirm(request, actor_user_id="student")
    assert forbidden.value.code == "forbidden"

    changed_policy = _policy(snapshot_revision=2)
    changed_manifest = _manifest(changed_policy)
    store.replace_current(changed_policy, changed_manifest)
    changed = service.disclose("teacher")
    assert changed.policy_hash == changed_policy.policy_hash
    assert changed.manifest_hash == changed_manifest.manifest_hash
    with pytest.raises(ProviderDisclosureError) as drifted_preflight:
        service.preflight(
            actor_user_id="teacher",
            provider_operation="llm_debate",
            model_key=FIXED_MODELS["llm_debate"],
            scope_id=changed_manifest.scope_id,
        )
    assert drifted_preflight.value.code == "provider_confirmation_required"


def test_confirmation_is_durably_visible_to_a_new_service_instance() -> None:
    service, store, policy, manifest = _service()
    request = ProviderDataCallConfirmationRequestV1(
        policy_hash=policy.policy_hash,
        manifest_hash=manifest.manifest_hash,
        expected_revision=1,
    )
    service.confirm(request, actor_user_id="teacher")

    reloaded = ProviderDisclosureService(store)
    assert (
        reloaded.preflight(
            actor_user_id="teacher",
            provider_operation="llm_debate",
            model_key=FIXED_MODELS["llm_debate"],
            scope_id=manifest.scope_id,
        ).export_manifest_hash
        == manifest.manifest_hash
    )


def test_missing_manifest_is_not_found_and_preflight_never_calls_transport() -> None:
    service, _store, _policy_value, _manifest_value = _service()
    missing = ProviderDisclosureService(service.store, manifest_ref="missing-manifest")
    with pytest.raises(ProviderDisclosureError) as not_found:
        missing.disclose("teacher")
    assert not_found.value.code == "not_found"

    calls: list[str] = []
    with pytest.raises(ProviderDisclosureError) as required:
        service.preflight(
            actor_user_id="teacher",
            provider_operation="llm_debate",
            model_key=FIXED_MODELS["llm_debate"],
            scope_id="debate-scope",
            payload={"speech": "safe"},
        )
    assert required.value.code == "provider_confirmation_required"
    assert calls == []


def test_confirmed_fake_preflight_blocks_secret_payload_without_transport() -> None:
    service, _store, policy, manifest = _service()
    request = ProviderDataCallConfirmationRequestV1(
        policy_hash=policy.policy_hash,
        manifest_hash=manifest.manifest_hash,
        expected_revision=1,
    )
    service.confirm(request, actor_user_id="teacher")
    result = service.preflight(
        actor_user_id="teacher",
        provider_operation="llm_debate",
        model_key=FIXED_MODELS["llm_debate"],
        scope_id=manifest.scope_id,
        payload={"speech": "safe"},
    )
    assert result.policy_hash == policy.policy_hash
    with pytest.raises(ProviderDisclosureError) as blocked:
        service.preflight(
            actor_user_id="teacher",
            provider_operation="llm_debate",
            model_key=FIXED_MODELS["llm_debate"],
            scope_id=manifest.scope_id,
            payload={"student_id": "private"},
        )
    assert blocked.value.code == "provider_preflight_blocked"


def test_public_disclosure_text_red_team_is_rejected_before_rendering() -> None:
    unsafe_policy = _policy(no_training_basis="_".join(("api", "key")) + "=redacted-fixture")
    unsafe_manifest = _manifest(unsafe_policy)
    service = ProviderDisclosureService(
        InMemoryProviderDisclosureStore(unsafe_policy, unsafe_manifest)
    )
    with pytest.raises(ProviderDisclosureError) as blocked:
        service.disclose("teacher")
    assert blocked.value.code == "provider_preflight_blocked"


def test_manifest_model_drift_is_a_zero_call_blocker() -> None:
    policy = _policy()
    manifest = _manifest(policy)
    object.__setattr__(manifest, "model_key", "latest")
    service = ProviderDisclosureService(InMemoryProviderDisclosureStore(policy, manifest))
    with pytest.raises(ProviderDisclosureError) as blocked:
        service.disclose("teacher")
    assert blocked.value.code == "provider_model_invalid"


def test_sql_store_reads_and_writes_confirmation_durably(tmp_path: Any) -> None:
    database = Database(f"sqlite:///{tmp_path / 'provider-preflight.sqlite3'}")
    database.initialize_schema()
    control = ProviderRepository(database)
    policy = _policy()
    policy_id = control.save_policy_snapshot(policy, snapshot_id="policy-1")
    manifest = _manifest(policy)
    control.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        manifest_id="manifest-1",
    )
    session = database.session_factory()
    try:
        store = SqlAlchemyProviderDisclosureStore(session)
        service = ProviderDisclosureService(
            store,
            teacher_authorizer=lambda user_id: user_id == "teacher",
        )
        before = service.disclose("teacher")
        assert before.confirmation_revision == 1
        service.confirm(
            ProviderDataCallConfirmationRequestV1(
                policy_hash=policy.policy_hash,
                manifest_hash=manifest.manifest_hash,
                expected_revision=1,
            ),
            actor_user_id="teacher",
        )
        session.commit()
    finally:
        session.close()
    reloaded_session = database.session_factory()
    try:
        reloaded = ProviderDisclosureService(
            SqlAlchemyProviderDisclosureStore(reloaded_session),
            teacher_authorizer=lambda user_id: user_id == "teacher",
        )
        assert (
            reloaded.preflight(
                actor_user_id="teacher",
                provider_operation="llm_debate",
                model_key=FIXED_MODELS["llm_debate"],
                scope_id=manifest.scope_id,
            ).export_manifest_hash
            == manifest.manifest_hash
        )
    finally:
        reloaded_session.close()
        database.dispose()


def test_sql_manifest_authorization_is_bound_to_exact_owner_course(
    client: TestClient,
) -> None:
    app = client.app
    database = app.state.database
    _student, csrf = login(client, "student-bowen-1")
    created = client.post(
        f"/api/v1/groups/{GROUP_BOWEN_ID}/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "provider-owner-agent-0001",
        },
        json={"name": "Owner-bound Agent", "description": ""},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]

    policy = _policy(snapshot_revision=7)
    manifest = _manifest(policy, scope_id="owned-build")
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_BOWEN_ID,
        agent_version_id=version_id,
    )

    other_teacher_id = "6655f62c-1a95-4ed8-a344-12e3f34e3c71"
    other_course_id = "4a74392f-a2e5-45ec-b222-9475ce08bfd2"
    with database.session() as db:
        now = datetime.now(UTC)
        db.add(
            User(
                id=other_teacher_id,
                username="other-course-teacher",
                display_name="Other Course Teacher",
                status="active",
                created_at=now,
            )
        )
        db.add(
            Course(
                id=other_course_id,
                code="other-course",
                name="Other Course",
                current_audio_debate_id=None,
                created_at=now,
            )
        )
        db.flush()
        db.add(
            CourseMember(
                course_id=other_course_id,
                user_id=other_teacher_id,
                role="teacher",
                created_at=now,
            )
        )

    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        assert service.disclose(TEACHER_ID, manifest_ref=manifest.manifest_hash).manifest_hash == (
            manifest.manifest_hash
        )
        with pytest.raises(ProviderDisclosureError) as wrong_course:
            service.disclose(other_teacher_id, manifest_ref=manifest.manifest_hash)
        assert wrong_course.value.code == "forbidden"
        with pytest.raises(ProviderDisclosureError) as student:
            service.disclose(str(_student["user"]["id"]), manifest_ref=manifest.manifest_hash)
        assert student.value.code == "forbidden"


def test_sql_query_manifest_listing_is_owner_bound_and_returns_safe_summary(
    client: TestClient,
) -> None:
    app = client.app
    database = app.state.database
    _student, csrf = login(client, "student-bowen-1")
    created = client.post(
        f"/api/v1/groups/{GROUP_BOWEN_ID}/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "provider-query-list-agent-0001",
        },
        json={"name": "Query list Agent", "description": ""},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]

    with database.session() as db:
        assert (
            db.scalar(
                select(AgentVersion.id)
                .join(Agent, Agent.id == AgentVersion.agent_id)
                .where(Agent.group_id == GROUP_BOWEN_ID, AgentVersion.id == version_id)
            )
            == version_id
        )

    policy = _policy(snapshot_revision=11)
    manifest = _query_manifest(policy, scope_id="sql-query-list")
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_BOWEN_ID,
        agent_version_id=version_id,
    )
    with database.session() as db:
        now = datetime.now(UTC)
        db.add(
            ProviderOperation(
                id=str(uuid4()),
                scope_id=manifest.scope_id,
                provider_operation="embedding_query",
                logical_item_id="turn:query-turn-1",
                attempt_no=1,
                request_hash=_digest("query-request"),
                max_tokens=1,
                max_cost_cny=0,
                policy_hash=policy.policy_hash,
                export_manifest_hash=manifest.manifest_hash,
                build_manifest_hash=manifest.build_manifest_hash,
                model_key=manifest.model_key,
                state="prepared",
                request_count=0,
                charged_request_count=0,
                staged_response_hash=None,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )

    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        pending = service.list_embedding_query_manifests(
            TEACHER_ID,
            scope_id=manifest.scope_id,
        )
        assert pending.scope_id == manifest.scope_id
        assert pending.items[0].manifest_hash == manifest.manifest_hash
        assert pending.items[0].turn_id == "query-turn-1"
        assert pending.items[0].confirmation_revision == 1
        assert pending.items[0].confirmed is False

        with pytest.raises(ProviderDisclosureError) as student:
            service.list_embedding_query_manifests(
                str(_student["user"]["id"]),
                scope_id=manifest.scope_id,
            )
        assert student.value.code == "forbidden"


def test_sql_publication_manifest_listing_is_version_and_course_bound_without_operation(
    client: TestClient,
) -> None:
    app = client.app
    database = app.state.database
    _student, csrf = login(client, "student-bowen-1")
    created = client.post(
        f"/api/v1/groups/{GROUP_BOWEN_ID}/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "provider-publication-list-agent-0001",
        },
        json={"name": "Publication list Agent", "description": ""},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]

    second = client.post(
        f"/api/v1/groups/{GROUP_BOWEN_ID}/agents",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "provider-publication-list-agent-0002",
        },
        json={"name": "Publication list Agent 2", "description": ""},
    )
    assert second.status_code == 201, second.text
    other_version_id = second.json()["versions"][0]["id"]

    policy = _policy(snapshot_revision=12)
    first_manifest = _embedding_manifest(
        policy,
        scope_id="publication-list-first",
        operation_revision=7,
    )
    other_manifest = _embedding_manifest(
        policy,
        scope_id="publication-list-other",
        operation_revision=8,
    )
    query_manifest = _query_manifest(policy, scope_id="publication-list-query")
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        first_manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_BOWEN_ID,
        agent_version_id=version_id,
    )
    repository.save_export_manifest(
        other_manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_BOWEN_ID,
        agent_version_id=other_version_id,
    )
    # A query manifest for the same version must stay on the existing
    # scope-based query route and must not appear in this publication list.
    repository.save_export_manifest(
        query_manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_BOWEN_ID,
        agent_version_id=version_id,
    )

    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        pending = service.list_embedding_manifests_for_agent_version(
            TEACHER_ID,
            agent_version_id=version_id,
        )
        assert pending.model_dump(mode="json") == {
            "agent_version_id": version_id,
            "items": [
                {
                    "manifest_hash": first_manifest.manifest_hash,
                    "confirmation_revision": 7,
                    "confirmed": False,
                }
            ],
        }

        # No ProviderOperation row has been inserted; discovery is driven by
        # the durable publication manifest itself.
        assert (
            db.scalar(
                select(ProviderOperation.id).where(
                    ProviderOperation.export_manifest_hash == first_manifest.manifest_hash
                )
            )
            is None
        )

        with pytest.raises(ProviderDisclosureError) as student:
            service.list_embedding_manifests_for_agent_version(
                str(_student["user"]["id"]),
                agent_version_id=version_id,
            )
        assert student.value.code == "forbidden"

        with pytest.raises(ProviderDisclosureError) as missing:
            service.list_embedding_manifests_for_agent_version(
                TEACHER_ID,
                agent_version_id="00000000-0000-4000-8000-000000000404",
            )
        assert missing.value.code == "not_found"


def _route_app(service: ProviderDisclosureService) -> FastAPI:
    app = FastAPI()
    app.state.provider_disclosure_service = service
    app.include_router(router)

    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError) -> Any:
        return JSONResponse(status_code=exc.status_code, content=error_body(request, exc))

    return app


def test_router_enforces_auth_and_teacher_boundary() -> None:
    service, _store, policy, manifest = _service()
    app = _route_app(service)

    def missing_auth() -> Any:
        raise unauthenticated()

    app.dependency_overrides[require_auth] = missing_auth
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/provider/data-call/disclosure",
            params={"manifest_hash": manifest.manifest_hash},
        )
    assert response.status_code == 401

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="student")
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/provider/data-call/disclosure",
            params={"manifest_hash": manifest.manifest_hash},
        )
    assert response.status_code == 403

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="teacher")
    )
    app.dependency_overrides[require_authenticated_mutation] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="teacher")
    )
    with TestClient(app) as client:
        disclosed = client.get(
            "/provider/data-call/disclosure",
            params={"manifest_hash": manifest.manifest_hash},
        )
        assert disclosed.status_code == 200
        assert disclosed.json()["disclosure"]["supplier_display_name"] == (
            "Alibaba Cloud Model Studio"
        )
        confirmed = client.post(
            "/provider/data-call/disclosure/confirm",
            json={
                "policy_hash": policy.policy_hash,
                "manifest_hash": manifest.manifest_hash,
                "expected_revision": 1,
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["confirmation_revision"] == 1


def test_router_lists_only_teacher_visible_query_manifests() -> None:
    policy = _policy()
    manifest = _query_manifest(policy, scope_id="router-query-scope")
    app = _route_app(ProviderDisclosureService(InMemoryProviderDisclosureStore(policy, manifest)))

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="student")
    )
    with TestClient(app) as client:
        forbidden = client.get(
            "/provider/data-call/pending",
            params={"scope_id": manifest.scope_id},
        )
    assert forbidden.status_code == 403

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="teacher")
    )
    with TestClient(app) as client:
        response = client.get(
            "/provider/data-call/pending",
            params={"scope_id": manifest.scope_id},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "scope_id": manifest.scope_id,
        "items": [
            {
                "manifest_hash": manifest.manifest_hash,
                "turn_id": None,
                "confirmation_revision": 1,
                "confirmed": False,
            }
        ],
    }


def test_router_lists_publication_manifests_by_agent_version() -> None:
    policy = _policy()
    agent_version_id = "agent-version-router-publication"
    publication = _embedding_manifest(policy, operation_revision=2)
    service = ProviderDisclosureService(
        InMemoryProviderDisclosureStore(
            policy,
            _manifest(policy),
            agent_version_id=agent_version_id,
            publication_manifests=(publication,),
        )
    )
    app = _route_app(service)

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="student")
    )
    with TestClient(app) as client:
        forbidden = client.get(f"/provider/data-call/pending/agent-versions/{agent_version_id}")
    assert forbidden.status_code == 403

    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(
        user=SimpleNamespace(id="teacher")
    )
    with TestClient(app) as client:
        response = client.get(f"/provider/data-call/pending/agent-versions/{agent_version_id}")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "agent_version_id": agent_version_id,
            "items": [
                {
                    "manifest_hash": publication.manifest_hash,
                    "confirmation_revision": 2,
                    "confirmed": False,
                }
            ],
        }

        missing = client.get("/provider/data-call/pending/agent-versions/agent-version-missing")
    assert missing.status_code == 404
