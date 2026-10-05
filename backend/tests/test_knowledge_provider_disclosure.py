"""Synthetic owner/current-permission checks for Knowledge provider consent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.models import (
    Agent,
    Course,
    CourseMember,
    KnowledgeDocument,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    StoredFile,
    TeacherGroupAccess,
    User,
)
from app.modules.knowledge_sets.generation import _canonical_json, _input_payload, _sha256
from app.modules.knowledge_sets.models import (
    KnowledgeGenerationRun,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.provider_disclosure.schemas import ProviderDataCallConfirmationRequestV1
from app.modules.provider_disclosure.service import (
    ProviderDisclosureError,
    ProviderDisclosureService,
    SqlAlchemyProviderDisclosureStore,
)
from app.providers.control import ExportFieldV1, ExportManifestV1, authorized_provider_model
from app.providers.control_repository import ProviderRepository
from app.seed import BOWEN_ID, COURSE_ID, GROUP_DEMO_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.test_knowledge_generation import _publish, _teacher_agent_with_source
from tests.test_wave4_provider_preflight import _policy


def _prepare(
    client: TestClient,
    database: Database,
    *,
    group_agent: bool = False,
    group_set: bool = False,
    group_source: bool = False,
) -> tuple[str, ExportManifestV1]:
    _teacher, csrf = login(client, "maya")
    agent_id, version_id, revision, document_id = _teacher_agent_with_source(
        client, csrf, agent_markdown="# Teacher instruction sentinel\n\nNever export this in a DTO."
    )
    published = _publish(client, csrf, version_id, revision, document_id, f"disclosure-{uuid4()}")
    assert published.status_code == 200, published.text
    run_id = published.json()["knowledge_generation"]["run_id"]
    policy = _policy()
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        agent = db.get(Agent, agent_id)
        document = db.get(KnowledgeDocument, document_id)
        assert run is not None and agent is not None and document is not None
        set_row = db.get(KnowledgeSet, run.knowledge_set_id)
        assert set_row is not None
        if group_agent or group_set or group_source:
            db.add(
                TeacherGroupAccess(
                    group_id=GROUP_DEMO_ID, user_id=TEACHER_ID, created_at=datetime.now(UTC)
                )
            )
        for row, grouped in ((agent, group_agent), (set_row, group_set), (document, group_source)):
            if grouped:
                row.group_id = GROUP_DEMO_ID
                row.ownership_scope = "group"
        run.input_key = _sha256(
            _canonical_json(
                _input_payload(
                    agent=agent,
                    set_row=set_row,
                    agent_md_hash=run.agent_md_hash,
                    source_manifest=json.loads(run.source_manifest_json),
                    action_id=run.action_id,
                    intent_generation=run.intent_generation,
                )
            )
        )
        manifest = ExportManifestV1(
            scope_id=run.id,
            provider_operation="llm_knowledge_generate",
            model_key=authorized_provider_model("llm_knowledge_generate"),
            policy_hash=policy.policy_hash,
            build_manifest_hash=_sha256("synthetic exact body"),
            persona_spec_hash=run.agent_md_hash,
            fields=tuple(
                ExportFieldV1(name, _sha256(name))
                for name in (
                    "teacher_agent_instructions",
                    "authorized_courseware_text",
                    "topic_and_platform_rules",
                    "opaque_local_id",
                )
            ),
            operation_revision=3,
        )
        run.provider_manifest_hash = manifest.manifest_hash
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_DEMO_ID if group_agent else None,
        agent_version_id=version_id,
    )
    return run_id, manifest


def _confirmation(
    manifest: ExportManifestV1, **changes: Any
) -> ProviderDataCallConfirmationRequestV1:
    return ProviderDataCallConfirmationRequestV1(
        **{
            "manifest_hash": manifest.manifest_hash,
            "policy_hash": manifest.policy_hash,
            "expected_revision": manifest.operation_revision,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "group_agent,group_set,group_source",
    [(False, False, False), (True, False, True), (True, True, True), (False, True, False)],
)
def test_knowledge_owner_can_disclose_and_confirm_exact_manifest(
    client: TestClient, app_bundle: Any, group_agent: bool, group_set: bool, group_source: bool
) -> None:
    _app, database, _settings = app_bundle
    _run_id, manifest = _prepare(
        client, database, group_agent=group_agent, group_set=group_set, group_source=group_source
    )
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        response = service.disclose(TEACHER_ID, manifest_ref=manifest.manifest_hash)
        assert response.disclosure.outbound_field_classes == tuple(
            field.field_class for field in manifest.fields
        )
        assert "questions with rubrics" in response.disclosure.purpose
        encoded = response.model_dump_json()
        for forbidden in (
            "Teacher instruction sentinel",
            "A source canary",
            "lesson.md",
            "Never export",
            manifest.model_key,
            TEACHER_ID,
            COURSE_ID,
            "endpoint",
            "api_key",
            "source_manifest_json",
        ):
            assert forbidden not in encoded
        request = _confirmation(manifest)
        assert (
            service.confirm(request, actor_user_id=TEACHER_ID, manifest_ref=manifest.manifest_hash)
            == response
        )
        assert (
            service.confirm(request, actor_user_id=TEACHER_ID, manifest_ref=manifest.manifest_hash)
            == response
        )
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("same_course", [True, False])
def test_knowledge_other_teacher_cannot_disclose_or_confirm(
    client: TestClient, app_bundle: Any, same_course: bool
) -> None:
    _app, database, _settings = app_bundle
    _run_id, manifest = _prepare(client, database)
    other_id = str(uuid4())
    with database.session() as db:
        now = datetime.now(UTC)
        other_course = COURSE_ID if same_course else str(uuid4())
        db.add(
            User(
                id=other_id,
                username="disclosure-other",
                display_name="Other",
                status="active",
                created_at=now,
            )
        )
        if not same_course:
            db.add(Course(id=other_course, code="other", name="Other", created_at=now))
        db.flush()
        db.add(
            CourseMember(course_id=other_course, user_id=other_id, role="teacher", created_at=now)
        )
    with database.session() as db:
        # The legacy testing override must not bypass Knowledge's exact owner.
        service = ProviderDisclosureService(
            SqlAlchemyProviderDisclosureStore(db), teacher_authorizer=lambda _: True
        )
        for actor in (other_id, BOWEN_ID):
            with pytest.raises(ProviderDisclosureError, match="teacher") as denied:
                service.disclose(actor, manifest_ref=manifest.manifest_hash)
            assert denied.value.code == "forbidden"
            with pytest.raises(ProviderDisclosureError) as denied:
                service.confirm(
                    _confirmation(manifest),
                    actor_user_id=actor,
                    manifest_ref=manifest.manifest_hash,
                )
            assert denied.value.code == "forbidden"
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 0


@pytest.mark.parametrize(
    "revocation",
    [
        "course_role",
        "course_removed",
        "agent_owner",
        "agent_epoch",
        "agent_deleted",
        "set_owner",
        "set_epoch",
        "set_deleted",
        "source_owner",
        "source_epoch",
        "source_hidden",
        "source_hash",
        "source_binding",
        "file_deleted",
        "agent_group_access",
        "set_group_access",
        "source_group_access",
        "manifest_scope",
        "manifest_course",
        "manifest_group",
        "run_manifest",
    ],
)
def test_knowledge_current_permissions_required_even_after_confirmation(
    client: TestClient, app_bundle: Any, revocation: str
) -> None:
    _app, database, _settings = app_bundle
    run_id, manifest = _prepare(
        client,
        database,
        group_agent=revocation == "agent_group_access",
        group_set=revocation == "set_group_access",
        group_source=revocation == "source_group_access",
    )
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        service.confirm(
            _confirmation(manifest), actor_user_id=TEACHER_ID, manifest_ref=manifest.manifest_hash
        )
    with database.session() as db:
        run = db.get(KnowledgeGenerationRun, run_id)
        assert run is not None
        agent = db.get(Agent, run.agent_id)
        set_row = db.get(KnowledgeSet, run.knowledge_set_id)
        binding = db.scalar(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.knowledge_set_id == run.knowledge_set_id
            )
        )
        assert agent is not None and set_row is not None and binding is not None
        source = db.get(KnowledgeDocument, binding.document_id)
        file = db.get(StoredFile, binding.stored_file_id)
        member = db.get(CourseMember, (COURSE_ID, TEACHER_ID))
        row = db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest.manifest_hash
            )
        )
        assert source is not None and file is not None and member is not None and row is not None
        if revocation == "course_role":
            member.role = "student"
        elif revocation == "course_removed":
            db.delete(member)
        elif revocation.endswith("group_access"):
            access = db.get(TeacherGroupAccess, (GROUP_DEMO_ID, TEACHER_ID))
            assert access is not None
            db.delete(access)
        elif revocation == "agent_owner":
            agent.owner_user_id = BOWEN_ID
        elif revocation == "agent_epoch":
            agent.authorization_epoch += 1
        elif revocation == "agent_deleted":
            agent.deleted_at = datetime.now(UTC)
        elif revocation == "set_owner":
            set_row.owner_user_id = BOWEN_ID
        elif revocation == "set_epoch":
            set_row.authorization_epoch += 1
        elif revocation == "set_deleted":
            set_row.deleted_at = datetime.now(UTC)
        elif revocation == "source_owner":
            source.owner_user_id = BOWEN_ID
        elif revocation == "source_epoch":
            source.authorization_epoch += 1
        elif revocation == "source_hidden":
            source.workspace_state = "hidden"
        elif revocation == "source_hash":
            source.content_hash = _sha256("changed courseware")
        elif revocation == "source_binding":
            binding.is_active = False
        elif revocation == "file_deleted":
            file.state = "deleted"
        elif revocation == "manifest_scope":
            row.scope_id = str(uuid4())
        elif revocation == "manifest_course":
            row.course_id = None
        elif revocation == "manifest_group":
            row.group_id = GROUP_DEMO_ID
        elif revocation == "run_manifest":
            run.provider_manifest_hash = None
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        with pytest.raises(ProviderDisclosureError) as denied:
            service.disclose(TEACHER_ID, manifest_ref=manifest.manifest_hash)
        assert denied.value.code == "forbidden"
        with pytest.raises(ProviderDisclosureError) as denied:
            service.confirm(
                _confirmation(manifest),
                actor_user_id=TEACHER_ID,
                manifest_ref=manifest.manifest_hash,
            )
        assert denied.value.code == "forbidden"
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize(
    "changes", [{"policy_hash": "a" * 64}, {"manifest_hash": "b" * 64}, {"expected_revision": 4}]
)
def test_knowledge_confirmation_retains_exact_hash_revision_cas(
    client: TestClient, app_bundle: Any, changes: dict[str, Any]
) -> None:
    _app, database, _settings = app_bundle
    _run_id, manifest = _prepare(client, database)
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        with pytest.raises(ProviderDisclosureError) as stale:
            service.confirm(
                _confirmation(manifest, **changes),
                actor_user_id=TEACHER_ID,
                manifest_ref=manifest.manifest_hash,
            )
        assert stale.value.code == "provider_preflight_stale"
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 0
