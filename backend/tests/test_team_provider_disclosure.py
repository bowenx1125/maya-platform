"""Exact-hash Teacher consent for one granted Team member, without Chat disclosure."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    CourseMember,
    KnowledgeDocument,
    ProviderExportConfirmation,
    ProviderExportManifest,
    ProviderOperation,
    User,
)
from app.modules.knowledge_sets.models import AgentKnowledgeSet, KnowledgeSet
from app.modules.provider_disclosure.schemas import ProviderDataCallConfirmationRequestV1
from app.modules.provider_disclosure.service import (
    TEAM_RESULT_SCOPE_PREFIX,
    ProviderDisclosureError,
    ProviderDisclosureService,
    SqlAlchemyProviderDisclosureStore,
)
from app.modules.provider_disclosure.team_standing import (
    current_standing_grant,
    operator_standing_grant,
)
from app.modules.teams.models import CourseTeamPublication, Team, TeamMemberInvokeGrant
from app.modules.workspace.models import (
    ChatProviderStandingGrant,
    Conversation,
    ConversationParticipant,
    TeamProviderStandingGrant,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.modules.workspace.team_conversation import frozen_team_selection
from app.modules.workspace.team_runtime import claim_team_turn, result_ids
from app.providers.control import ExportFieldV1, ExportManifestV1, authorized_provider_model
from app.providers.control_repository import ProviderRepository
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.conftest import login
from tests.provider_confirm_helpers import (
    chat_standing_disclosure,
    confirm_disclosure,
    confirm_team_standing,
    preview_team_standing,
)
from tests.test_mayaform_team_conversations import (
    BOWEN_ID,
    COURSE_ID,
    MAYA_ID,
    _attach_personal_snapshot,
    _create,
    _headers,
    _make_agent_version,
)
from tests.test_mayaform_teams import _team_payload
from tests.test_wave4_provider_preflight import _digest, _policy


def _prepared(
    client: TestClient,
    database: Any,
    settings: Any,
    operation: str = "llm_agent_chat",
    *,
    custom: bool = False,
) -> tuple[str, ExportManifestV1, str, str]:
    owner_id = BOWEN_ID if custom else MAYA_ID
    _, csrf = login(client, "bowen" if custom else "maya")
    versions = [
        _make_agent_version(
            database,
            owner_id=owner_id,
            name=f"Granted {index}",
            visibility="private" if custom else "public",
        )[1]
        for index in range(2)
    ]
    document_id = _attach_personal_snapshot(database, versions[0])
    if custom:
        with database.session() as db:
            db.get(KnowledgeDocument, document_id).owner_user_id = owner_id
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(csrf, f"disclosure-set-{uuid4()}"),
        json={"display_name": "Teacher private Set"},
    )
    assert response.status_code == 201, response.text
    set_id = response.json()["id"]
    with database.session() as db:
        version = db.get(AgentVersion, versions[0])
        db.add(
            AgentKnowledgeSet(
                agent_id=version.agent_id,
                knowledge_set_id=set_id,
                order_index=0,
                created_by_user_id=owner_id,
                created_at=datetime.now(UTC),
            )
        )
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(csrf, f"disclosure-team-{uuid4()}"),
        json=_team_payload(versions, visibility="private" if custom else "public"),
    )
    assert response.status_code == 201, response.text
    _, csrf = login(client, "bowen")
    session = _create(
        client, csrf, {"kind": "team" if custom else "maya_team", "team_id": response.json()["id"]}
    )
    with database.session() as db:
        claim = claim_team_turn(
            db,
            settings,
            conversation_id=session["id"],
            actor_id=BOWEN_ID,
            request_id=str(uuid4()),
            expected_revision=session["revision"],
            message="PRIVATE_STUDENT_MESSAGE_CANARY",
            routing=TeamRouting(
                mode="selected", participant_ids=[session["team"]["members"][0]["id"]]
            ),
        )
    result_id = result_ids(database.session_factory, claim.turn_id)[0]
    policy = _policy()
    fields = (
        (
            "private_conversation_messages",
            "teacher_agent_instructions",
            "authorized_courseware_text",
        )
        if operation == "llm_agent_chat"
        else ("current_evidence_excerpt",)
    )
    manifest = ExportManifestV1(
        scope_id=TEAM_RESULT_SCOPE_PREFIX + result_id,
        provider_operation=operation,
        model_key=authorized_provider_model(operation),
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest("synthetic exact outbound bytes"),
        persona_spec_hash=_digest("synthetic member Agent.md"),
        fields=tuple(ExportFieldV1(field, _digest(field)) for field in fields),
        operation_revision=2,
    )
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=None,
        agent_version_id=versions[0],
    )
    return result_id, manifest, document_id, set_id


def _request(manifest: ExportManifestV1, **changes: Any) -> ProviderDataCallConfirmationRequestV1:
    return ProviderDataCallConfirmationRequestV1(
        **{
            "policy_hash": manifest.policy_hash,
            "manifest_hash": manifest.manifest_hash,
            "expected_revision": manifest.operation_revision,
            **changes,
        }
    )


def test_revoked_owner_tool_schema_pins_real_agno_titles() -> None:
    from copy import deepcopy

    from agno.tools.function import Function
    from app.modules.provider_disclosure.team_standing import (
        REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION,
        REVOKED_ASSESSMENT_ACTIONS,
        _revoked_assessment_tool_is_closed,
    )
    from app.modules.runtime_tools.builtin import AssessmentActionArguments

    function = Function.from_callable(lambda arguments: arguments, name="assessment_action")
    payload_schema = AssessmentActionArguments.model_json_schema()
    definitions = payload_schema.pop("$defs", None)
    function.parameters = {
        "type": "object",
        "properties": {"arguments": payload_schema},
        "required": ["arguments"],
        "additionalProperties": False,
    }
    if definitions is not None:
        function.parameters["$defs"] = definitions
    arguments = function.parameters["properties"]["arguments"]
    arguments["properties"] = {
        "classification": {"type": "string", "enum": list(REVOKED_ASSESSMENT_ACTIONS)}
    }
    arguments["required"] = ["classification"]
    arguments["additionalProperties"] = False
    function.description = REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION
    tool = {"type": "function", "function": function.to_dict()}
    assert arguments["title"] == "AssessmentActionArguments"
    assert _revoked_assessment_tool_is_closed([tool])

    arbitrary_arguments_title = deepcopy(tool)
    arbitrary_arguments_title["function"]["parameters"]["properties"]["arguments"]["title"] = (
        "Untrusted schema title"
    )
    assert not _revoked_assessment_tool_is_closed([arbitrary_arguments_title])

    arbitrary_classification_title = deepcopy(tool)
    arbitrary_classification_title["function"]["parameters"]["properties"]["arguments"][
        "properties"
    ]["classification"]["title"] = "Untrusted enum title"
    assert not _revoked_assessment_tool_is_closed([arbitrary_classification_title])


def test_teacher_cannot_disclose_private_single_query_scope(
    client: TestClient, app_bundle: Any
) -> None:
    from app.modules.provider_disclosure.service import EMBEDDING_QUERY_OPERATION
    from app.modules.workspace.models import Conversation

    from tests.test_wave3_mock_rag_delta import GROUP_DEMO_ID

    _app, database, _settings = app_bundle
    agent_id, version_id = _make_agent_version(
        database,
        owner_id=MAYA_ID,
        name="Private query scope",
        group_id=GROUP_DEMO_ID,
    )
    with database.session() as db:
        agent = db.get(Agent, agent_id)
        version = db.get(AgentVersion, version_id)
        assert agent is not None and version is not None
        conversation = Conversation(
            id=str(uuid4()),
            user_id=BOWEN_ID,
            course_id=COURSE_ID,
            agent_version_id=version.id,
            snapshot_id=version.knowledge_snapshot_id,
            agent_name_snapshot=agent.name,
            agent_authorization_epoch=agent.authorization_epoch,
            entry_kind="agent",
            chat_visibility="private",
            origin="single_agent",
            revision=0,
            active_request_id=None,
            withdrawn_at=None,
            created_at=datetime.now(UTC),
        )
        db.add(conversation)
        conversation_id = conversation.id

    policy = _policy(snapshot_revision=31)
    manifest = ExportManifestV1(
        scope_id=conversation_id,
        provider_operation=EMBEDDING_QUERY_OPERATION,
        model_key=authorized_provider_model(EMBEDDING_QUERY_OPERATION),
        policy_hash=policy.policy_hash,
        build_manifest_hash=_digest("private single query build"),
        persona_spec_hash=_digest("private single query persona"),
        fields=(ExportFieldV1("current_evidence_excerpt", _digest("private query")),),
    )
    repository = ProviderRepository(database)
    policy_id = repository.save_policy_snapshot(policy)
    repository.save_export_manifest(
        manifest,
        policy_snapshot_id=policy_id,
        course_id=COURSE_ID,
        group_id=GROUP_DEMO_ID,
        agent_version_id=version_id,
    )

    with database.session() as db:
        store = SqlAlchemyProviderDisclosureStore(db)
        assert not store.is_teacher_for_manifest(MAYA_ID, manifest.manifest_hash)
        assert not store.is_teacher_for_scope(MAYA_ID, conversation_id)
        service = ProviderDisclosureService(store)
        with pytest.raises(ProviderDisclosureError) as disclosure:
            service.disclose(MAYA_ID, manifest_ref=manifest.manifest_hash)
        assert disclosure.value.code == "forbidden"
        with pytest.raises(ProviderDisclosureError) as listing:
            service.list_embedding_query_manifests(MAYA_ID, scope_id=conversation_id)
        assert listing.value.code == "forbidden"


@pytest.mark.parametrize("operation", ["llm_agent_chat", "embedding_query"])
def test_custom_owner_confirms_own_current_resources_without_teacher_identity(
    client: TestClient, app_bundle: Any, operation: str
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, _document, _set = _prepared(
        client, database, settings, operation, custom=True
    )
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        for other in (MAYA_ID, "bc170f51-45fb-5296-a36d-a2edc8f8d315"):
            with pytest.raises(ProviderDisclosureError):
                service.confirm(_request(manifest), actor_user_id=other)
        disclosed = service.disclose(BOWEN_ID, manifest_ref=manifest.manifest_hash)
        assert "PRIVATE_STUDENT_MESSAGE_CANARY" not in disclosed.model_dump_json()
        service.confirm(
            _request(manifest), actor_user_id=BOWEN_ID, manifest_ref=manifest.manifest_hash
        )
    with database.session() as db:
        confirmation = db.scalar(select(ProviderExportConfirmation))
        assert confirmation.manifest_hash == manifest.manifest_hash
        assert db.get(TeamTurnResult, result_id).state == "pending"
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("mutation", ["owner", "role", "source", "set", "grant", "selected"])
def test_custom_confirmation_requires_actual_owner_and_all_selected_current_acl(
    client: TestClient, app_bundle: Any, mutation: str
) -> None:
    import json

    from app.modules.workspace.models import ConversationTurn

    _app, database, settings = app_bundle
    result_id, manifest, document_id, set_id = _prepared(client, database, settings, custom=True)
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        if mutation == "owner":
            conversation.user_id = MAYA_ID
        elif mutation == "role":
            db.delete(db.get(CourseMember, (COURSE_ID, BOWEN_ID)))
        elif mutation == "source":
            db.get(KnowledgeDocument, document_id).authorization_epoch += 1
        elif mutation == "set":
            db.get(KnowledgeSet, set_id).authorization_epoch += 1
        elif mutation == "grant":
            # A grant reference must never turn Custom consent into borrowed
            # Teacher consent, even if a row is tampered outside normal APIs.
            participant.invoke_grant_id = str(uuid4())
        else:
            other = db.scalar(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation.id,
                    ConversationParticipant.id != participant.id,
                )
            )
            db.get(ConversationTurn, result.turn_id).routing_json = json.dumps(
                {"mode": "selected", "participant_ids": [participant.id, other.id]}
            )
            db.get(Agent, other.agent_id).authorization_epoch += 1
        # Do not flush a deliberately invalid grant FK: authorization must
        # reject the in-memory row before any write is attempted.
        if mutation != "grant":
            db.flush()
        with db.no_autoflush:
            service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
            with pytest.raises(ProviderDisclosureError) as denied:
                service.confirm(_request(manifest), actor_user_id=BOWEN_ID)
            assert denied.value.code == "forbidden"
        db.rollback()


@pytest.mark.parametrize("operation", ["llm_agent_chat", "embedding_query"])
def test_only_exact_publisher_can_confirm_team_member_and_browser_has_no_private_context(
    client: TestClient, app_bundle: Any, operation: str
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, _document, set_id = _prepared(client, database, settings, operation)
    with database.session() as db:
        service = ProviderDisclosureService(
            SqlAlchemyProviderDisclosureStore(db), teacher_authorizer=lambda _: True
        )
        response = service.disclose(MAYA_ID, manifest_ref=manifest.manifest_hash)
        encoded = response.model_dump_json()
        for forbidden in (
            "PRIVATE_STUDENT_MESSAGE_CANARY",
            "private-source.md",
            "K3 private source fence fixture",
            result_id,
            BOWEN_ID,
            set_id,
            "invoke_grant_id",
            "model_key",
        ):
            assert forbidden not in encoded
        assert response.confirmation_revision == 2
        for actor in (BOWEN_ID, "bc170f51-45fb-5296-a36d-a2edc8f8d315"):
            with pytest.raises(ProviderDisclosureError) as denied:
                service.confirm(
                    _request(manifest), actor_user_id=actor, manifest_ref=manifest.manifest_hash
                )
            assert denied.value.code == "forbidden"
        assert (
            service.confirm(
                _request(manifest), actor_user_id=MAYA_ID, manifest_ref=manifest.manifest_hash
            )
            == response
        )
        assert (
            service.confirm(
                _request(manifest), actor_user_id=MAYA_ID, manifest_ref=manifest.manifest_hash
            )
            == response
        )
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
        result = db.get(TeamTurnResult, result_id)
        assert result.state == "pending"
        conversation_id = result.conversation_id
        with pytest.raises(ProviderDisclosureError) as listing:
            service.list_embedding_query_manifests(MAYA_ID, scope_id=manifest.scope_id)
        assert listing.value.code == "forbidden"
    _, csrf = login(client, "maya")
    assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404
    assert client.get("/api/v1/conversations").json() == []
    with database.session() as db:
        assert db.get(TeamTurnResult, result_id).state == "pending"
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("same_course", [True, False])
def test_other_teacher_cannot_confirm_published_private_member(
    client: TestClient, app_bundle: Any, same_course: bool
) -> None:
    _app, database, settings = app_bundle
    _result, manifest, _document, _set_id = _prepared(client, database, settings)
    teacher_id = "bc170f51-45fb-5296-a36d-a2edc8f8d315"
    with database.session() as db:
        member = db.get(CourseMember, (COURSE_ID, teacher_id))
        if same_course:
            member.role = "teacher"
        else:
            db.delete(member)
            course_id, now = str(uuid4()), datetime.now(UTC)
            db.add(Course(id=course_id, code="foreign-course", name="Foreign", created_at=now))
            db.flush()
            db.add(
                CourseMember(
                    course_id=course_id, user_id=teacher_id, role="teacher", created_at=now
                )
            )
    with database.session() as db:
        service = ProviderDisclosureService(
            SqlAlchemyProviderDisclosureStore(db), teacher_authorizer=lambda _: True
        )
        with pytest.raises(ProviderDisclosureError) as denied:
            service.confirm(
                _request(manifest), actor_user_id=teacher_id, manifest_ref=manifest.manifest_hash
            )
        assert denied.value.code == "forbidden"


@pytest.mark.parametrize(
    "revocation",
    [
        "publisher_role",
        "student_role",
        "actor_disabled",
        "team_epoch",
        "publication",
        "agent_epoch",
        "source_epoch",
        "set_epoch",
        "grant",
        "scope",
        "manifest_version",
        "manifest_course",
        "snapshot",
    ],
)
def test_team_confirmation_rechecks_current_target_and_does_not_inherit_owner_history(
    client: TestClient, app_bundle: Any, revocation: str
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, document_id, set_id = _prepared(client, database, settings)
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        service.confirm(
            _request(manifest), actor_user_id=MAYA_ID, manifest_ref=manifest.manifest_hash
        )
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        member = db.get(ConversationParticipant, result.participant_id)
        row = db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == manifest.manifest_hash
            )
        )
        if revocation == "publisher_role":
            db.get(CourseMember, (COURSE_ID, MAYA_ID)).role = "student"
        elif revocation == "student_role":
            db.delete(db.get(CourseMember, (COURSE_ID, BOWEN_ID)))
        elif revocation == "actor_disabled":
            db.get(User, BOWEN_ID).status = "disabled"
        elif revocation == "team_epoch":
            db.get(Team, conversation.team_id).authorization_epoch += 1
        elif revocation == "publication":
            db.get(CourseTeamPublication, conversation.publication_id).state = "revoked"
        elif revocation == "agent_epoch":
            db.get(Agent, member.agent_id).authorization_epoch += 1
        elif revocation == "source_epoch":
            db.get(KnowledgeDocument, document_id).authorization_epoch += 1
        elif revocation == "set_epoch":
            db.get(KnowledgeSet, set_id).authorization_epoch += 1
        elif revocation == "grant":
            db.get(TeamMemberInvokeGrant, member.invoke_grant_id).authorization_epoch += 1
        elif revocation == "scope":
            row.scope_id = TEAM_RESULT_SCOPE_PREFIX + str(uuid4())
        elif revocation == "manifest_version":
            other = db.scalar(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation.id,
                    ConversationParticipant.id != member.id,
                )
            )
            row.agent_version_id = other.agent_version_id
        elif revocation == "manifest_course":
            row.course_id = None
        elif revocation == "snapshot":
            member.snapshot_id = None
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        with pytest.raises(ProviderDisclosureError) as denied:
            service.confirm(
                _request(manifest), actor_user_id=MAYA_ID, manifest_ref=manifest.manifest_hash
            )
        assert denied.value.code == "forbidden"
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize(
    "changes", [{"policy_hash": "a" * 64}, {"manifest_hash": "b" * 64}, {"expected_revision": 3}]
)
def test_team_consent_retains_exact_policy_manifest_revision_cas(
    client: TestClient, app_bundle: Any, changes: dict[str, Any]
) -> None:
    _app, database, settings = app_bundle
    _result, manifest, _document, _set_id = _prepared(client, database, settings)
    with database.session() as db:
        service = ProviderDisclosureService(SqlAlchemyProviderDisclosureStore(db))
        with pytest.raises(ProviderDisclosureError) as stale:
            service.confirm(
                _request(manifest, **changes),
                actor_user_id=MAYA_ID,
                manifest_ref=manifest.manifest_hash,
            )
        assert stale.value.code == "provider_preflight_stale"
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 0


def test_publisher_can_confirm_static_team_resources_once_without_student_chat_text(
    client: TestClient, app_bundle: Any
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, _document, _set_id = _prepared(client, database, settings)
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        team_version_id = conversation.team_version_id
    payload = {
        "team_version_id": team_version_id,
        "provider_operation": manifest.provider_operation,
        "policy_hash": manifest.policy_hash,
    }
    plan = preview_team_standing(database, MAYA_ID, **payload)
    assert plan.team_version_id == team_version_id
    assert plan.policy_hash == payload["policy_hash"]
    assert "PRIVATE_STUDENT_MESSAGE_CANARY" not in plan.resource_manifest_json
    assert int(plan.safe_disclosure["member_count"]) >= 2
    assert plan.resource_hash
    grant_id = confirm_team_standing(database, MAYA_ID, plan=plan, **payload)
    assert confirm_team_standing(database, MAYA_ID, plan=plan, **payload) == grant_id
    with pytest.raises(PlatformError) as denied:
        preview_team_standing(database, BOWEN_ID, **payload)
    assert denied.value.status_code == 404


@pytest.mark.parametrize("operation", ["llm_agent_chat", "embedding_query"])
def test_operator_standing_consent_records_publisher_grant_once(
    client: TestClient, app_bundle: Any, operation: str
) -> None:
    _app, database, settings = app_bundle
    result_id, manifest, _document, _set_id = _prepared(client, database, settings, operation)
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        selection = frozen_team_selection(db, conversation)
        args = (
            db,
            BOWEN_ID,
            selection,
            {participant.team_member_id},
            manifest.policy_hash,
            manifest.provider_operation,
        )
        assert current_standing_grant(*args) is None
        grant = operator_standing_grant(*args)
        assert grant is not None
        assert grant.publisher_user_id == MAYA_ID
        assert grant.provider_operation == operation
        assert "PRIVATE_STUDENT_MESSAGE_CANARY" not in grant.resource_manifest_json
        assert current_standing_grant(*args) == grant
        again = operator_standing_grant(*args)
        assert again is not None and again.id == grant.id
        assert db.scalar(select(func.count()).select_from(TeamProviderStandingGrant)) == 1


def test_teacher_can_confirm_embedding_chat_policy_for_single_queries(
    client: TestClient, app_bundle: Any
) -> None:
    app, database, settings = app_bundle
    policy = _policy()
    app.state.settings = settings.model_copy(
        update={"embedding_provider_policy_hash": policy.policy_hash}
    )
    result_id, _team_manifest, _document_id, _set_id = _prepared(
        client, database, settings, "embedding_query"
    )
    disclosure = chat_standing_disclosure(
        database,
        MAYA_ID,
        course_id=COURSE_ID,
        policy_hash=policy.policy_hash,
        provider_operation="embedding_query",
    )
    text = json.dumps(disclosure)
    assert disclosure["policy_hash"] == policy.policy_hash
    assert disclosure["disclosure"]["outbound_field_classes"] == ["current_evidence_excerpt"]
    assert "Embed approved retrieval questions" in disclosure["disclosure"]["purpose"]
    assert "provider_operation" not in disclosure
    assert result_id not in text
    assert not any(
        forbidden in text.lower()
        for forbidden in (
            "private_student_message_canary",
            "turn_id",
            "endpoint",
            "model_key",
            "credential",
        )
    )
    with database.session() as db:
        manifest = db.scalar(
            select(ProviderExportManifest).where(
                ProviderExportManifest.manifest_hash == disclosure["manifest_hash"]
            )
        )
        assert manifest is not None
        assert manifest.scope_id == f"chat-course:{COURSE_ID}"
        assert manifest.provider_operation == "embedding_query"
        assert manifest.policy_hash == policy.policy_hash
        assert manifest.agent_version_id is None
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0

    confirm_disclosure(
        database,
        MAYA_ID,
        policy_hash=disclosure["policy_hash"],
        manifest_hash=disclosure["manifest_hash"],
        expected_revision=disclosure["confirmation_revision"],
    )
    with database.session() as db:
        course_grant = db.scalar(
            select(ChatProviderStandingGrant).where(
                ChatProviderStandingGrant.course_id == COURSE_ID,
                ChatProviderStandingGrant.provider_operation == "embedding_query",
                ChatProviderStandingGrant.policy_hash == policy.policy_hash,
            )
        )
        assert course_grant is not None
        assert course_grant.field_classes_json == '["current_evidence_excerpt"]'
        assert course_grant.field_classes_hash
        assert db.scalar(select(func.count()).select_from(ProviderExportConfirmation)) == 1
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        conversation = db.get(Conversation, result.conversation_id)
        team_version_id = conversation.team_version_id

    team_payload = {
        "team_version_id": team_version_id,
        "provider_operation": "embedding_query",
        "policy_hash": policy.policy_hash,
    }
    plan = preview_team_standing(database, MAYA_ID, **team_payload)
    assert plan.policy_hash == policy.policy_hash
    assert result_id not in plan.resource_manifest_json
    assert "PRIVATE_STUDENT_MESSAGE_CANARY" not in plan.resource_manifest_json
    grant_id = confirm_team_standing(database, MAYA_ID, plan=plan, **team_payload)
    assert confirm_team_standing(database, MAYA_ID, plan=plan, **team_payload) == grant_id
    with database.session() as db:
        grant = db.scalar(
            select(TeamProviderStandingGrant).where(
                TeamProviderStandingGrant.team_version_id == team_version_id
            )
        )
        assert grant is not None
        assert grant.provider_operation == "embedding_query"
        assert grant.policy_hash == policy.policy_hash
        assert grant.resource_hash == plan.resource_hash
        assert db.scalar(select(func.count()).select_from(ProviderOperation)) == 0


@pytest.mark.parametrize("mutation", ["none", "query_text_changed", "source_set_deleted"])
def test_team_embedding_send_rechecks_exact_query_and_current_resource_grant(
    client: TestClient, app_bundle: Any, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    import struct
    from dataclasses import replace

    from app.core.models import (
        KnowledgeChunk,
        KnowledgeSnapshot,
        ProviderOperation,
        SnapshotDocument,
    )
    from app.modules.knowledge.providers.adapters import (
        DashScopeEmbeddingAdapter,
        DashScopeEmbeddingConfig,
    )
    from app.modules.knowledge.providers.snapshot_build import (
        REAL_EMBEDDING_DIMENSION,
        REAL_EMBEDDING_MODEL,
        REAL_EMBEDDING_POLICY_VERSION,
        REAL_EMBEDDING_PROVIDER,
        REAL_EMBEDDING_REGION,
    )
    from app.modules.provider_disclosure.team_standing import (
        confirm_team_standing_grant,
        prepare_team_standing_grant,
    )
    from app.modules.workspace.chat_team_context import load_member_context
    from app.modules.workspace.models import ConversationTurn

    from tests.test_wave4_embedding_generation_query import _QueryTransport
    from tests.test_wave4_query_standing_consent import _policy as embedding_policy

    app, database, settings = app_bundle
    config = DashScopeEmbeddingConfig(api_key="fixture-query-key", workspace_id="fixture")
    policy = replace(
        embedding_policy(config.resolved_endpoint), policy_id="team-query-send-test-policy"
    )
    ProviderRepository(database).save_policy_snapshot(policy)
    settings = settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "embedding_provider": "dashscope",
            "embedding_provider_policy_hash": policy.policy_hash,
            "dashscope_api_key": "fixture-query-key",
            "dashscope_workspace_id": "fixture",
            "dashscope_region": "cn-beijing",
        }
    )
    app.state.settings = settings
    result_id, _manifest, document_id, set_id = _prepared(
        client, database, settings, "embedding_query"
    )
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        assert result is not None
        conversation = db.get(Conversation, result.conversation_id)
        turn = db.get(ConversationTurn, result.turn_id)
        participant = db.get(ConversationParticipant, result.participant_id)
        assert conversation is not None and turn is not None and participant is not None
        snapshot = db.get(KnowledgeSnapshot, participant.snapshot_id)
        assert snapshot is not None
        snapshot.embedding_provider = REAL_EMBEDDING_PROVIDER
        snapshot.embedding_model_key = REAL_EMBEDDING_MODEL
        snapshot.embedding_region = REAL_EMBEDDING_REGION
        snapshot.embedding_dimension = REAL_EMBEDDING_DIMENSION
        snapshot.embedding_policy_version = REAL_EMBEDDING_POLICY_VERSION
        snapshot_document = db.scalar(
            select(SnapshotDocument).where(SnapshotDocument.snapshot_id == snapshot.id)
        )
        assert snapshot_document is not None
        vector = struct.pack(
            f"<{REAL_EMBEDDING_DIMENSION}f",
            1.0,
            *([0.0] * (REAL_EMBEDDING_DIMENSION - 1)),
        )
        db.add(
            KnowledgeChunk(
                id=str(uuid4()),
                snapshot_id=snapshot.id,
                snapshot_document_id=snapshot_document.id,
                document_id=document_id,
                chunk_index=0,
                chunk_text="A safe retrieval record for this Team member.",
                start_offset=0,
                end_offset=44,
                embedding_blob=vector,
                embedding_dimension=REAL_EMBEDDING_DIMENSION,
                embedding_key=REAL_EMBEDDING_MODEL,
            )
        )
        selected_binding_ids = {participant.team_member_id}
        turn_id = turn.id
        claim_token = turn.claim_token
        assert claim_token is not None
        conversation_id = conversation.id
        participant_id = participant.id
        team_version_id = conversation.team_version_id
        result.state = "running"
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="embedding_query",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="embedding_query",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )

    transport = _QueryTransport()
    adapter = DashScopeEmbeddingAdapter(config, transport)
    monkeypatch.setattr(
        "app.modules.workspace.chat_team_context.embedding_provider", lambda _settings: adapter
    )
    original_transition = ProviderRepository.transition
    mutated = False

    def transition(self: ProviderRepository, operation_id: str, **kwargs: Any) -> Any:
        nonlocal mutated
        if (
            not mutated
            and kwargs.get("expected") == "reserved"
            and kwargs.get("state") == "sending"
            and mutation != "none"
        ):
            mutated = True
            with database.session() as db:
                if mutation == "query_text_changed":
                    changed_turn = db.get(ConversationTurn, turn_id)
                    assert changed_turn is not None
                    changed_turn.user_text += " changed after preparation"
                else:
                    from app.modules.knowledge_sets.models import KnowledgeSet

                    deleted_set = db.get(KnowledgeSet, set_id)
                    assert deleted_set is not None
                    deleted_set.deleted_at = datetime.now(UTC)
        return original_transition(self, operation_id, **kwargs)

    monkeypatch.setattr(ProviderRepository, "transition", transition)
    error: Exception | None = None
    try:
        with database.session() as db:
            conversation = db.get(Conversation, conversation_id)
            participant = db.get(ConversationParticipant, participant_id)
            assert conversation is not None and participant is not None
            load_member_context(
                db,
                conversation,
                participant,
                "PRIVATE_STUDENT_MESSAGE_CANARY",
                settings=settings,
                result_id=result_id,
                turn_id=turn_id,
                claim_token=claim_token,
                selected_binding_ids=selected_binding_ids,
            )
    except Exception as exc:
        error = exc

    assert len(transport.calls) == (1 if mutation == "none" else 0)
    assert (error is None) is (mutation == "none")
    with database.session() as db:
        operation = db.scalar(
            select(ProviderOperation).where(
                ProviderOperation.scope_id == f"team-result:{result_id}",
                ProviderOperation.provider_operation == "embedding_query",
            )
        )
        assert operation is not None
        if mutation == "none":
            assert operation.state == "succeeded"
            assert operation.charged_request_count == 1
        else:
            assert operation.state == "not_sent"
            assert operation.charged_request_count == 0
