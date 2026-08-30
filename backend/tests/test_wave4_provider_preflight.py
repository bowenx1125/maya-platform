"""Teacher disclosure and confirmation tests for ProviderDataCallV1."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
from app.core.db import Database
from app.core.errors import PlatformError, error_body, unauthenticated
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
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


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
        "https://dashscope.aliyuncs.com",
        "workspace-id",
        "api_key",
        "student-name",
        "absolute/path",
        "payload_json",
        "provider_operations",
        "teacher_note",
    ):
        assert forbidden.casefold() not in encoded
    assert response.policy_hash == policy.policy_hash
    assert response.manifest_hash == manifest.manifest_hash


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
    unsafe_policy = _policy(no_training_basis="api_key=secret-value")
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
