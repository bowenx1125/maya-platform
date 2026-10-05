from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import Agent, AgentVersion, KnowledgeDocument, ProviderOperation, User
from app.modules.auth.service import AuthContext, create_rotated_session
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.materialization import materialize_accepted_knowledge_generation
from app.modules.knowledge_sets.models import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
    KnowledgeAssetVersionSource,
    KnowledgeDocumentVersion,
    KnowledgeGenerationRun,
    KnowledgeGenerationSourceReceipt,
    KnowledgeSet,
    KnowledgeSetSource,
)
from app.modules.knowledge_sets.schemas import QuestionContent
from app.modules.learning.attempts import (
    apply_assessment_decision,
    apply_attempt_lifecycle_action,
    get_assessment_runtime_context,
    mark_attempt_question_presented,
    read_attempt_answers,
    start_or_resume_attempt,
    withdraw_conversation_attempts,
)
from app.modules.learning.execution import (
    attempt_has_final_evidence,
    get_assessment_executor_context,
    read_own_formal_attempt,
    write_formal_assessment,
    write_formal_boundary,
)
from app.modules.learning.models import (
    AssessmentActivity,
    AssessmentActivityQuestion,
    AssessmentAttempt,
    AssessmentAttemptEvent,
    AssessmentAttemptQuestion,
    LearningAssessment,
    LearningAssessmentResourceGrant,
    LearningAssessmentRevision,
    LearningBoundary,
    LearningBoundaryRevision,
    LearningRecord,
)
from app.modules.learning.recipes import (
    COMPLETION_DECLARATION,
    QUESTION_SCOPE_DECLARATION,
    SUPPORTED_RECIPE_ID,
    current_question_version_for_asset,
    question_sources_readable,
    refresh_assessment_activity_questions,
)
from app.modules.learning.reports import (
    create_assessment_course_report,
    download_assessment_course_report,
    read_assessment_activity_aggregate,
)
from app.modules.learning.schemas import AssessmentRuntimeDecision, CreateAssessmentRequest
from app.modules.learning.service import create_assessment, read_assessment
from app.modules.runtime_tools.learning import learning_tools
from app.modules.runtime_tools.models import RuntimeModelCallStage, RuntimeToolReceipt
from app.modules.runtime_tools.registry import ToolCallIdentity, execute_tool
from app.modules.teams.models import (
    TeamMemberInvokeGrant,
    TeamVersionMember,
    TeamVersionSet,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from app.seed import COURSE_ID, TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_knowledge_generation_materialization import (
    _accept_stage as _accept_knowledge_stage,
)
from tests.test_knowledge_generation_materialization import (
    _create_generation_run,
    _run_claim,
)
from tests.test_mayaform_learning_evidence import (
    OTHER_STUDENT_ID,
    STUDENT_ID,
    _context,
    _login,
    _start_chat,
    _team_conversation,
)
from tests.test_team_provider_stage import _dispatch


@pytest.fixture
def attempt_env(app_bundle: Any, client: TestClient) -> tuple[Any, Any, Any, TestClient]:
    app, database, settings = app_bundle
    client.headers["Origin"] = "http://testserver"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
    return app, database, settings, client


def _question_content(prompt: str, reference_answer: str) -> str:
    return QuestionContent(
        kind="question",
        prompt=prompt,
        reference_answer=reference_answer,
        rubric={"criteria": [{"label": "Reasoning", "guidance": "Internal only", "points": 2}]},
    ).model_dump_json()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _service_actor(db: Any, settings: Any, user_id: str) -> AuthContext:
    user = db.get(User, user_id)
    assert user is not None
    raw_token, session, csrf = create_rotated_session(db, user, settings)
    return AuthContext(raw_token, session, user, csrf)


def _accepted_tool_identity(
    db: Any,
    *,
    template_stage_id: str,
    conversation_id: str,
    participant_id: str,
    position: int,
    tool_name: str,
    execution: tuple[str, str] | None = None,
    tool_arguments: dict[str, Any] | None = None,
) -> ToolCallIdentity:
    template_stage = db.get(TeamProviderCall, template_stage_id)
    assert template_stage is not None
    template_operation = db.get(ProviderOperation, template_stage.operation_id)
    assert template_operation is not None
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None
    now = datetime.now(UTC)
    if execution is None:
        pending_turns = db.scalars(
            select(ConversationTurn).where(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.state == "pending",
            )
        ).all()
        for pending_turn in pending_turns:
            pending_turn.state = "ready"
            pending_turn.assistant_text = "Saved assessment result."
        pending_results = db.scalars(
            select(TeamTurnResult)
            .join(ConversationTurn, ConversationTurn.id == TeamTurnResult.turn_id)
            .where(
                TeamTurnResult.conversation_id == conversation_id,
                TeamTurnResult.state == "running",
            )
        ).all()
        for pending_result in pending_results:
            pending_result.state = "ready"
            pending_result.assistant_text = "Saved assessment result."
            pending_result.completed_at = now

        turn_id = str(uuid4())
        turn = ConversationTurn(
            id=turn_id,
            conversation_id=conversation_id,
            position=position,
            user_text="Please save the current formal result.",
            assistant_text=None,
            sources_json="[]",
            mode="real",
            state="pending",
            safe_error_code=None,
            routing_json=None,
            request_hash=None,
            claim_token=None,
            created_at=now,
        )
        db.add(turn)
        conversation.active_request_id = turn_id
        conversation.revision = position
        result = TeamTurnResult(
            id=str(uuid4()),
            turn_id=turn_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            ordinal=0,
            state="running",
            assistant_text=None,
            sources_json="[]",
            safe_error_code=None,
            created_at=now,
            completed_at=None,
        )
        db.add(result)
    else:
        turn_id, result_id = execution
        turn = db.get(ConversationTurn, turn_id)
        result = db.get(TeamTurnResult, result_id)
        assert turn is not None and result is not None
        assert turn.conversation_id == conversation_id and turn.state == "pending"
        assert conversation.active_request_id == turn_id
        assert result.turn_id == turn_id and result.participant_id == participant_id
        assert result.state == "running"

    call_id = f"call-{tool_name}-{position}"
    arguments = tool_arguments or {"content": {"saved": True}}
    request_json = json.dumps(
        {
            "messages": [{"role": "user", "content": turn.user_text}],
            "tools": [{"type": "function", "function": {"name": tool_name}}],
        }
    )
    response_json = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps({"arguments": arguments}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    request_hash = _hash(request_json)
    operation_id = str(uuid4())
    db.add(
        ProviderOperation(
            id=operation_id,
            scope_id=f"assessment-test:{turn_id}",
            provider_operation=template_operation.provider_operation,
            logical_item_id=turn_id,
            attempt_no=1,
            request_hash=request_hash,
            max_tokens=template_operation.max_tokens,
            max_cost_cny=template_operation.max_cost_cny,
            policy_hash=template_operation.policy_hash,
            export_manifest_hash=template_operation.export_manifest_hash,
            build_manifest_hash=template_operation.build_manifest_hash,
            model_key=template_operation.model_key,
            state="accepted",
            request_count=1,
            charged_request_count=1,
            staged_response_hash=_hash(response_json),
            safe_error_code=None,
            acceptance_run_id=None,
            call_no=None,
            created_at=now,
            updated_at=now,
        )
    )
    stage_id = str(uuid4())
    db.add(
        TeamProviderCall(
            id=stage_id,
            result_id=result.id,
            ordinal=0,
            operation_id=operation_id,
            request_hash=request_hash,
            manifest_hash=template_stage.manifest_hash,
            request_json=request_json,
            accepted_response_json=response_json,
            accepted_response_hash=_hash(response_json),
            created_at=now,
            accepted_at=now,
        )
    )
    db.flush()
    return ToolCallIdentity(conversation_id, turn_id, participant_id, stage_id, call_id)


def _begin_pending_executor_turn(
    db: Any,
    *,
    conversation_id: str,
    participant_id: str,
    position: int,
) -> tuple[str, str]:
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None and conversation.active_request_id is None
    now = datetime.now(UTC)
    turn_id, result_id = str(uuid4()), str(uuid4())
    db.add(
        ConversationTurn(
            id=turn_id,
            conversation_id=conversation_id,
            position=position,
            user_text="Please finish this assessment task.",
            assistant_text=None,
            sources_json="[]",
            mode="real",
            state="pending",
            safe_error_code=None,
            routing_json=None,
            request_hash=None,
            claim_token=None,
            created_at=now,
        )
    )
    db.flush()
    db.add(
        TeamTurnResult(
            id=result_id,
            turn_id=turn_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            ordinal=0,
            state="running",
            assistant_text=None,
            sources_json="[]",
            safe_error_code=None,
            created_at=now,
            completed_at=None,
        )
    )
    conversation.active_request_id = turn_id
    conversation.revision = position
    db.flush()
    return turn_id, result_id


def _finish_executor_turn(db: Any, execution: tuple[str, str]) -> None:
    turn_id, result_id = execution
    turn = db.get(ConversationTurn, turn_id)
    result = db.get(TeamTurnResult, result_id)
    assert turn is not None and result is not None
    turn.state = "ready"
    turn.assistant_text = "Saved assessment result."
    result.state = "ready"
    result.assistant_text = "Saved assessment result."
    result.completed_at = datetime.now(UTC)
    conversation = db.get(Conversation, turn.conversation_id)
    assert conversation is not None
    if conversation.active_request_id == turn.id:
        conversation.active_request_id = None


def _accepted_single_tool_identity(
    db: Any,
    *,
    template_stage_id: str,
    conversation_id: str,
    agent_version_id: str,
    position: int,
    tool_name: str,
    tool_arguments: dict[str, Any],
) -> ToolCallIdentity:
    template_stage = db.get(TeamProviderCall, template_stage_id)
    assert template_stage is not None
    template_operation = db.get(ProviderOperation, template_stage.operation_id)
    assert template_operation is not None
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None and conversation.entry_kind == "agent"
    now = datetime.now(UTC)
    turn_id, call_id, operation_id = str(uuid4()), f"call-{tool_name}-{position}", str(uuid4())
    turn = ConversationTurn(
        id=turn_id,
        conversation_id=conversation_id,
        position=position,
        user_text="Please save this practice assessment revision.",
        assistant_text=None,
        sources_json="[]",
        mode="real",
        state="pending",
        safe_error_code=None,
        routing_json=None,
        request_hash=None,
        claim_token=None,
        created_at=now,
    )
    db.add(turn)
    conversation.active_request_id = turn_id
    conversation.revision = position
    db.flush()
    request_json = json.dumps(
        {
            "messages": [{"role": "user", "content": turn.user_text}],
            "tools": [{"type": "function", "function": {"name": tool_name}}],
        }
    )
    response_json = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps({"arguments": tool_arguments}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )
    request_hash, response_hash = _hash(request_json), _hash(response_json)
    db.add(
        ProviderOperation(
            id=operation_id,
            scope_id=f"assessment-single-test:{turn_id}",
            provider_operation=template_operation.provider_operation,
            logical_item_id=turn_id,
            attempt_no=1,
            request_hash=request_hash,
            max_tokens=template_operation.max_tokens,
            max_cost_cny=template_operation.max_cost_cny,
            policy_hash=template_operation.policy_hash,
            export_manifest_hash=template_operation.export_manifest_hash,
            build_manifest_hash=template_operation.build_manifest_hash,
            model_key=template_operation.model_key,
            state="accepted",
            request_count=1,
            charged_request_count=1,
            staged_response_hash=response_hash,
            safe_error_code=None,
            acceptance_run_id=None,
            call_no=None,
            created_at=now,
            updated_at=now,
        )
    )
    db.flush()
    db.add(
        RuntimeModelCallStage(
            operation_id=operation_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            executor_agent_version_id=agent_version_id,
            ordinal=0,
            dispatch_ordinal=0,
            request_hash=request_hash,
            request_json=request_json,
            accepted_response_json=response_json,
            accepted_response_hash=response_hash,
            created_at=now,
            accepted_at=now,
        )
    )
    db.flush()
    return ToolCallIdentity(conversation_id, turn_id, agent_version_id, operation_id, call_id)


def _finish_single_tool_turn(db: Any, identity: ToolCallIdentity) -> None:
    turn = db.get(ConversationTurn, identity.turn_id)
    conversation = db.get(Conversation, identity.conversation_id)
    assert turn is not None and conversation is not None
    turn.state = "ready"
    turn.assistant_text = "Saved read result."
    if conversation.active_request_id == turn.id:
        conversation.active_request_id = None


def _create_question(
    db: Any,
    *,
    set_id: str,
    asset_id: str,
    version_id: str,
    ordinal: int,
    prompt: str,
    reference_answer: str,
    now: datetime,
) -> None:
    content_json = _question_content(prompt, reference_answer)
    db.add(
        KnowledgeAsset(
            id=asset_id,
            knowledge_set_id=set_id,
            kind="question",
            generation_lineage_key=None,
            current_version_seq=1,
            created_by_user_id=TEACHER_ID,
            created_at=now + timedelta(seconds=ordinal),
            updated_at=now + timedelta(seconds=ordinal),
        )
    )
    db.add(
        KnowledgeAssetVersion(
            id=version_id,
            asset_id=asset_id,
            version_seq=1,
            content_json=content_json,
            content_hash=_hash(content_json),
            source_dependency_hash=None,
            dependency_authorization_epoch=None,
            set_authorization_epoch=0,
            origin="manual",
            created_by_user_id=TEACHER_ID,
            generator_agent_version_id=None,
            generation_job_id=None,
            created_at=now + timedelta(seconds=ordinal),
        )
    )


def _create_question_version(
    db: Any,
    *,
    asset_id: str,
    version_id: str,
    version_seq: int,
    prompt: str,
    reference_answer: str,
) -> None:
    content_json = _question_content(prompt, reference_answer)
    db.add(
        KnowledgeAssetVersion(
            id=version_id,
            asset_id=asset_id,
            version_seq=version_seq,
            content_json=content_json,
            content_hash=_hash(content_json),
            source_dependency_hash=None,
            dependency_authorization_epoch=None,
            set_authorization_epoch=0,
            origin="manual",
            created_by_user_id=TEACHER_ID,
            generator_agent_version_id=None,
            generation_job_id=None,
            created_at=datetime.now(UTC),
        )
    )


def _create_formal_conversation(
    db: Any,
    *,
    actor_user_id: str = STUDENT_ID,
    visibility: str = "public",
) -> tuple[str, str, str, str, str, list[tuple[str, str]]]:
    conversation_id, team_id, team_version_id = _team_conversation(
        db,
        actor_user_id=actor_user_id,
        team_owner_id=TEACHER_ID,
        origin="published_course_team",
        visibility=visibility,
    )
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None and conversation.publication_id is not None
    members = db.scalars(
        select(TeamVersionMember)
        .where(TeamVersionMember.team_version_id == team_version_id)
        .order_by(TeamVersionMember.position)
    ).all()
    leader = next(member for member in members if member.is_leader)
    participants: dict[str, ConversationParticipant] = {}
    for member in members:
        agent = db.get(Agent, member.agent_id)
        member_version = db.get(AgentVersion, member.agent_version_id)
        assert agent is not None and member_version is not None
        participant = ConversationParticipant(
            id=str(uuid4()),
            conversation_id=conversation_id,
            team_version_id=team_version_id,
            team_member_id=member.id,
            agent_id=member.agent_id,
            agent_version_id=member.agent_version_id,
            snapshot_id=member_version.knowledge_snapshot_id,
            agent_authorization_epoch=agent.authorization_epoch,
            position=member.position,
            is_leader=member.is_leader,
            display_name=member.display_name,
            avatar_config_json=member.avatar_config_json,
            invoke_grant_id=None,
        )
        participants[member.id] = participant
        db.add(participant)
    db.flush()
    leader_version = db.get(AgentVersion, leader.agent_version_id)
    assert leader_version is not None
    leader_version.agent_md = (
        f"{leader_version.agent_md}\n\nMAYA-ASSESSMENT-RECIPE: {SUPPORTED_RECIPE_ID}\n"
        f"{QUESTION_SCOPE_DECLARATION}\n{COMPLETION_DECLARATION}\n"
        "MAYA-ASSESSMENT-ROLE: boundary_summarizer\n"
    )
    for member in members:
        if not member.is_leader:
            executor_version = db.get(AgentVersion, member.agent_version_id)
            assert executor_version is not None
            executor_version.agent_md = (
                f"{executor_version.agent_md}\n\nMAYA-ASSESSMENT-ROLE: evaluator\n"
            )
        grant = TeamMemberInvokeGrant(
            id=str(uuid4()),
            publication_id=conversation.publication_id,
            team_version_id=team_version_id,
            team_member_id=member.id,
            agent_id=member.agent_id,
            agent_version_id=member.agent_version_id,
            authorization_epoch=0,
            created_at=datetime.now(UTC),
        )
        db.add(grant)
        participants[member.id].invoke_grant_id = grant.id

    now = datetime.now(UTC)
    set_id = str(uuid4())
    db.add(
        KnowledgeSet(
            id=set_id,
            owner_user_id=TEACHER_ID,
            course_id=COURSE_ID,
            group_id=None,
            ownership_scope="personal",
            visibility="private",
            display_name="Formal diagnostic questions",
            metadata_revision=0,
            content_revision=0,
            authorization_epoch=0,
            deleted_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        TeamVersionSet(
            id=str(uuid4()),
            team_version_id=team_version_id,
            knowledge_set_id=set_id,
            authorization_epoch=0,
            position=0,
            created_at=now,
        )
    )
    db.flush()
    questions: list[tuple[str, str]] = []
    for ordinal, prompt in enumerate(("Question one", "Question two")):
        asset_id, version_id = str(uuid4()), str(uuid4())
        _create_question(
            db,
            set_id=set_id,
            asset_id=asset_id,
            version_id=version_id,
            ordinal=ordinal,
            prompt=prompt,
            reference_answer=f"Internal answer {ordinal + 1}",
            now=now,
        )
        questions.append((asset_id, version_id))
    db.flush()
    return conversation_id, team_id, team_version_id, conversation.publication_id, set_id, questions


def _custom_conversation_with_participants(db: Any, actor_user_id: str) -> str:
    conversation_id, _team_id, team_version_id = _team_conversation(
        db,
        actor_user_id=actor_user_id,
        team_owner_id=actor_user_id,
        origin="custom_team",
        visibility="public",
    )
    members = db.scalars(
        select(TeamVersionMember)
        .where(TeamVersionMember.team_version_id == team_version_id)
        .order_by(TeamVersionMember.position)
    ).all()
    for member in members:
        agent = db.get(Agent, member.agent_id)
        version = db.get(AgentVersion, member.agent_version_id)
        assert agent is not None and version is not None
        db.add(
            ConversationParticipant(
                id=str(uuid4()),
                conversation_id=conversation_id,
                team_version_id=team_version_id,
                team_member_id=member.id,
                agent_id=member.agent_id,
                agent_version_id=member.agent_version_id,
                snapshot_id=version.knowledge_snapshot_id,
                agent_authorization_epoch=agent.authorization_epoch,
                position=member.position,
                is_leader=member.is_leader,
                display_name=member.display_name,
                avatar_config_json=member.avatar_config_json,
                invoke_grant_id=None,
            )
        )
    db.flush()
    return conversation_id


def _copy_conversation(
    db: Any,
    source_id: str,
    *,
    actor_user_id: str,
    visibility: str,
) -> str:
    source = db.get(Conversation, source_id)
    assert source is not None
    row = Conversation(
        id=str(uuid4()),
        user_id=actor_user_id,
        course_id=source.course_id,
        agent_version_id=None,
        snapshot_id=None,
        agent_name_snapshot="",
        agent_authorization_epoch=0,
        entry_kind="maya_team",
        chat_visibility=visibility,
        origin="published_course_team",
        team_id=source.team_id,
        team_version_id=source.team_version_id,
        team_owner_user_id=source.team_owner_user_id,
        team_name_snapshot=source.team_name_snapshot,
        team_authorization_epoch=source.team_authorization_epoch,
        publication_id=source.publication_id,
        publication_epoch=source.publication_epoch,
        revision=0,
        active_request_id=None,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    return row.id


def _answer_decision(
    event_id: UUID,
    question_version_id: UUID,
    answer: str,
    *,
    mixed: bool = False,
) -> AssessmentRuntimeDecision:
    return AssessmentRuntimeDecision(
        client_event_id=event_id,
        classification="answer_with_restricted_request" if mixed else "answer_only",
        answer_span=answer,
        question_version_id=question_version_id,
    )


def test_private_attempt_reentry_from_public_entry_keeps_original_visibility(
    attempt_env: Any,
) -> None:
    _app, database, settings, _client = attempt_env
    token, _csrf = _login(_client, "bowen")
    with database.session() as db:
        private_id, *_ = _create_formal_conversation(db, visibility="private")
        actor = _context(db, settings, token)
        original = start_or_resume_attempt(db, actor, private_id, client_event_id=uuid4())
        assert original is not None
        assert original.attempt.chat_visibility == "private"
        assert original.canonical_conversation_id == UUID(private_id)

        public_id = _copy_conversation(
            db,
            private_id,
            actor_user_id=STUDENT_ID,
            visibility="public",
        )
        reentry = get_assessment_runtime_context(db, actor, public_id)
        assert reentry is not None
        assert reentry.redirect_to_original_conversation is True
        assert reentry.canonical_conversation_id == UUID(private_id)
        assert reentry.attempt.id == original.attempt.id
        assert reentry.attempt.chat_visibility == "private"
        resumed = start_or_resume_attempt(db, actor, public_id, client_event_id=uuid4())
        assert resumed is not None and resumed.attempt.id == original.attempt.id
        assert db.get(Conversation, private_id).chat_visibility == "private"
        assert db.get(Conversation, public_id).chat_visibility == "public"


def test_teacher_chat_does_not_activate_a_student_assessment_attempt(attempt_env: Any) -> None:
    _app, database, settings, _client = attempt_env
    with database.session() as db:
        teacher = _service_actor(db, settings, TEACHER_ID)
        conversation_id, team_id, *_ = _create_formal_conversation(
            db, actor_user_id=TEACHER_ID, visibility="public"
        )
        assert get_assessment_runtime_context(db, teacher, conversation_id) is None
        assert (
            start_or_resume_attempt(db, teacher, conversation_id, client_event_id=uuid4()) is None
        )
        assert (
            db.scalar(
                select(func.count(AssessmentAttempt.id)).where(
                    AssessmentAttempt.team_id == team_id,
                    AssessmentAttempt.actor_user_id == TEACHER_ID,
                )
            )
            == 0
        )


def test_teacher_public_read_denies_private_assessment_and_boundary(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    _teacher_token, teacher_csrf = _login(client, "maya")
    teacher_conversation_id = _start_chat(client, teacher_csrf)
    with database.session() as template_db:
        template_stage = template_db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        template_stage_id = template_stage.id
    with database.session() as db:
        teacher = _service_actor(db, settings, TEACHER_ID)
        private_conversation_id, _team_id, _version_id, _publication_id, _set_id, _questions = (
            _create_formal_conversation(db, visibility="private")
        )
        student = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(
            db,
            student,
            private_conversation_id,
            client_event_id=uuid4(),
        )
        assert started is not None
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        conversation = db.get(Conversation, private_conversation_id)
        assert activity is not None and conversation is not None
        assessment = LearningAssessment(
            id=str(uuid4()),
            owner_user_id=STUDENT_ID,
            course_id=COURSE_ID,
            created_conversation_id=private_conversation_id,
            attempt_id=str(started.attempt.id),
            current_revision_seq=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        boundary = LearningBoundary(
            id=str(uuid4()),
            attempt_id=str(started.attempt.id),
            activity_id=activity.id,
            owner_user_id=STUDENT_ID,
            course_id=COURSE_ID,
            conversation_id=private_conversation_id,
            current_revision_seq=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add_all([assessment, boundary])
        db.flush()
        teacher_conversation = db.get(Conversation, teacher_conversation_id)
        assert teacher_conversation is not None and teacher_conversation.agent_version_id
        assessment_args = {"assessment_id": assessment.id}
        assessment_identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=teacher_conversation_id,
            agent_version_id=teacher_conversation.agent_version_id,
            position=0,
            tool_name="read_assessment",
            tool_arguments=assessment_args,
        )
        denied_assessment = execute_tool(
            db,
            teacher,
            assessment_identity,
            "read_assessment",
            assessment_args,
            learning_tools(),
        )
        assert not denied_assessment["ok"] and denied_assessment["code"] == "not_found"
        _finish_single_tool_turn(db, assessment_identity)

        boundary_args = {"boundary_id": boundary.id}
        boundary_identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=teacher_conversation_id,
            agent_version_id=teacher_conversation.agent_version_id,
            position=1,
            tool_name="read_learning_boundary",
            tool_arguments=boundary_args,
        )
        denied_boundary = execute_tool(
            db,
            teacher,
            boundary_identity,
            "read_learning_boundary",
            boundary_args,
            learning_tools(),
        )
        assert not denied_boundary["ok"] and denied_boundary["code"] == "not_found"


def test_presented_question_version_stays_frozen_and_all_raw_answers_are_readable(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    _teacher_token, teacher_csrf = _login(client, "maya")
    teacher_conversation_id = _start_chat(client, teacher_csrf)
    token, _csrf = _login(client, "bowen")
    with database.session() as template_db:
        template_stage = template_db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        template_stage_id = template_stage.id
    with database.session() as db:
        conversation_id, team_id, _team_version_id, publication_id, _set_id, source_questions = (
            _create_formal_conversation(db, visibility="public")
        )
        actor = _context(db, settings, token)
        teacher = _service_actor(db, settings, TEACHER_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert activity is not None
        evaluator = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.evaluator_team_member_id,
            )
        )
        boundary_writer = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.boundary_team_member_id,
            )
        )
        assert evaluator is not None and boundary_writer is not None
        incomplete_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=50,
        )
        with pytest.raises(PlatformError) as incomplete_evaluation:
            get_assessment_executor_context(
                db,
                actor,
                conversation_id,
                turn_id=incomplete_execution[0],
                participant_id=evaluator.id,
                result_id=incomplete_execution[1],
                purpose="assessment_evaluate",
            )
        assert incomplete_evaluation.value.code == "assessment_answers_incomplete"
        _finish_executor_turn(db, incomplete_execution)

        first_asset_id, first_version_id = source_questions[0]
        assert str(started.current_question.question_version_id) == first_version_id
        pinned_first = mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=first_version_id,
        )
        assert pinned_first.current_question is not None
        assert pinned_first.current_question.prompt == "Question one"

        # A normal content revision changes the next unread question; the
        # first question already presented remains byte-for-byte pinned.
        first_asset = db.get(KnowledgeAsset, first_asset_id)
        assert first_asset is not None
        first_asset.current_version_seq = 2
        _create_question_version(
            db,
            asset_id=first_asset_id,
            version_id=str(uuid4()),
            version_seq=2,
            prompt="Question one changed after presentation",
            reference_answer="Updated internal answer",
        )

        second_asset_id, _old_second_version = source_questions[1]
        second_asset = db.get(KnowledgeAsset, second_asset_id)
        assert second_asset is not None
        second_asset.current_version_seq = 2
        second_version_id = str(uuid4())
        _create_question_version(
            db,
            asset_id=second_asset_id,
            version_id=second_version_id,
            version_seq=2,
            prompt="Question two updated before presentation",
            reference_answer="Internal answer two v2",
        )
        db.flush()

        # The attempt still presents the original first question version.
        context_after_edit = get_assessment_runtime_context(db, actor, conversation_id)
        assert context_after_edit is not None and context_after_edit.current_question is not None
        assert str(context_after_edit.current_question.question_version_id) == first_version_id
        assert context_after_edit.current_question.prompt == "Question one"

        first_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="My exact answer is seven, and please give me a hint.",
            decision=_answer_decision(uuid4(), UUID(first_version_id), "seven", mixed=True),
        )
        assert first_answer is not None
        assert first_answer.response_key == "assessment.answer_recorded_restricted_request"
        assert first_answer.context.current_question is not None
        assert (
            first_answer.context.current_question.prompt
            == "Question two updated before presentation"
        )
        assert "Internal answer" not in first_answer.model_dump_json()
        assert "Rubric" not in first_answer.model_dump_json()

        second_presented = mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=second_version_id,
        )
        assert second_presented.current_question is not None
        assert (
            second_presented.current_question.prompt == "Question two updated before presentation"
        )
        first_second_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="Second answer: two.",
            decision=_answer_decision(uuid4(), UUID(second_version_id), "two"),
        )
        assert first_second_answer is not None
        second_second_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="Correction for question two: three.",
            decision=_answer_decision(uuid4(), UUID(second_version_id), "three"),
        )
        assert second_second_answer is not None
        assert second_second_answer.context.progress.answered_count == 2
        assert second_second_answer.context.progress.resolved_count == 2

        answers = read_attempt_answers(db, actor, conversation_id)
        assert [answer.answer_text for answer in answers] == ["seven", "two", "three"]
        assert [answer.question_ordinal for answer in answers] == [0, 1, 1]
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.attempt_id == str(started.attempt.id)
                )
            )
            == 3
        )

        missing_assessment_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=boundary_writer.id,
            position=51,
        )
        with pytest.raises(PlatformError) as missing_assessment:
            get_assessment_executor_context(
                db,
                actor,
                conversation_id,
                turn_id=missing_assessment_execution[0],
                participant_id=boundary_writer.id,
                result_id=missing_assessment_execution[1],
                purpose="boundary_summarize",
            )
        assert missing_assessment.value.code == "assessment_evaluation_missing"
        _finish_executor_turn(db, missing_assessment_execution)

        evaluator_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
        )
        evaluator_context = get_assessment_executor_context(
            db,
            actor,
            conversation_id,
            turn_id=evaluator_execution[0],
            participant_id=evaluator.id,
            result_id=evaluator_execution[1],
            purpose="assessment_evaluate",
        )
        assert evaluator_context is not None
        evaluation_input = json.loads(evaluator_context.task_payload_json)
        assert [item["question_ordinal"] for item in evaluation_input["questions"]] == [0, 1]
        assert [item["answer_text"] for item in evaluation_input["questions"]] == [
            "seven",
            "three",
        ]
        assert evaluation_input["questions"][0]["rubric"]["criteria"][0]["points"] == 2
        assert "attempt_id" not in evaluation_input
        with pytest.raises(PlatformError, match="cannot edit this result"):
            get_assessment_executor_context(
                db,
                actor,
                conversation_id,
                turn_id=evaluator_execution[0],
                participant_id=evaluator.id,
                result_id=evaluator_execution[1],
                purpose="boundary_summarize",
            )
        evaluator_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
            tool_name="edit_assessment",
            execution=evaluator_execution,
        )
        evaluation_saved = write_formal_assessment(
            db,
            actor,
            evaluator_identity,
            {
                "overall_feedback": "Clear reasoning across the two questions.",
                "questions": [
                    {
                        "question_ordinal": 0,
                        "feedback": "Explained the key idea.",
                        "points_awarded": 1,
                    },
                    {
                        "question_ordinal": 1,
                        "feedback": "Improved the reasoning in the correction.",
                        "points_awarded": 2,
                    },
                ],
                "strengths": ["Persistence"],
                "next_steps": ["Explain the evidence used."],
            },
        )
        assert evaluation_saved == {"saved": True}
        _finish_executor_turn(db, evaluator_execution)
        formal_assessment = db.scalar(
            select(LearningAssessment).where(
                LearningAssessment.attempt_id == str(started.attempt.id)
            )
        )
        assert formal_assessment is not None
        public_revision_before = formal_assessment.current_revision_seq
        public_assessment_arguments = {"assessment_id": formal_assessment.id}
        public_assessment_identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=teacher_conversation_id,
            agent_version_id=str(db.get(Conversation, teacher_conversation_id).agent_version_id),
            position=0,
            tool_name="read_assessment",
            tool_arguments=public_assessment_arguments,
        )
        public_assessment_result = execute_tool(
            db,
            teacher,
            public_assessment_identity,
            "read_assessment",
            public_assessment_arguments,
            learning_tools(),
        )
        assert public_assessment_result["ok"] is True
        public_assessment = public_assessment_result["result"]
        assert public_assessment["status"] == "in_progress"
        assert public_assessment["assessment"]["overall_feedback"].startswith("Clear reasoning")
        assert "assessment_id" not in public_assessment
        assert formal_assessment.current_revision_seq == public_revision_before
        _finish_single_tool_turn(db, public_assessment_identity)

        teacher_edit_arguments = {
            "assessment_id": formal_assessment.id,
            "content": {
                "overall_feedback": "Teacher read permission does not allow edits.",
                "questions": [
                    {"question_ordinal": 0, "feedback": "Unauthorized edit."},
                    {"question_ordinal": 1, "feedback": "Unauthorized edit."},
                ],
            },
        }
        teacher_edit_identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=teacher_conversation_id,
            agent_version_id=str(db.get(Conversation, teacher_conversation_id).agent_version_id),
            position=1,
            tool_name="edit_assessment",
            tool_arguments=teacher_edit_arguments,
        )
        teacher_edit_result = execute_tool(
            db,
            teacher,
            teacher_edit_identity,
            "edit_assessment",
            teacher_edit_arguments,
            learning_tools(),
        )
        assert not teacher_edit_result["ok"]
        assert teacher_edit_result["code"] == "assessment_attempt_not_active"
        assert formal_assessment.current_revision_seq == public_revision_before
        _finish_single_tool_turn(db, teacher_edit_identity)

        active_view = read_own_formal_attempt(
            db,
            actor,
            conversation_id,
            attempt_id=str(started.attempt.id),
        )
        assert active_view["assessment"] is None and active_view["boundary"] is None
        assert [answer["answer_text"] for answer in active_view["answers"]] == [
            "seven",
            "two",
            "three",
        ]

        custom_conversation_id = _custom_conversation_with_participants(db, STUDENT_ID)
        custom_participant = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == custom_conversation_id,
                ConversationParticipant.agent_version_id == activity.evaluator_agent_version_id,
            )
        )
        assert custom_participant is not None
        custom_execution = _begin_pending_executor_turn(
            db,
            conversation_id=custom_conversation_id,
            participant_id=custom_participant.id,
            position=0,
        )
        denied_formal_content = {
            "overall_feedback": "A custom Team cannot revise this formal result.",
            "questions": [
                {"question_ordinal": 0, "feedback": "Must be denied."},
                {"question_ordinal": 1, "feedback": "Must be denied."},
            ],
        }
        custom_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=custom_conversation_id,
            participant_id=custom_participant.id,
            position=0,
            tool_name="edit_assessment",
            execution=custom_execution,
            tool_arguments={
                "assessment_id": formal_assessment.id,
                "content": denied_formal_content,
            },
        )
        denied_formal = execute_tool(
            db,
            actor,
            custom_identity,
            "edit_assessment",
            {
                "assessment_id": formal_assessment.id,
                "content": denied_formal_content,
            },
            learning_tools(),
        )
        assert not denied_formal["ok"]
        assert denied_formal["code"] == "assessment_attempt_not_active"

        boundary_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=boundary_writer.id,
            position=1,
        )
        boundary_context = get_assessment_executor_context(
            db,
            actor,
            conversation_id,
            turn_id=boundary_execution[0],
            participant_id=boundary_writer.id,
            result_id=boundary_execution[1],
            purpose="boundary_summarize",
        )
        assert boundary_context is not None
        boundary_input = json.loads(boundary_context.task_payload_json)
        assert [item["answer_text"] for item in boundary_input["responses"]] == [
            "seven",
            "three",
        ]
        assert boundary_input["assessment"]["overall_feedback"].startswith("Clear reasoning")
        assert all("rubric" not in item for item in boundary_input["responses"])
        boundary_arguments = {
            "content": {
                "summary": "The learner revised an explanation after feedback.",
                "strengths": ["Persistence", "Revisiting evidence"],
                "areas_to_explore": ["Show intermediate reasoning."],
                "next_step": "Compare two explanations with evidence.",
            }
        }
        boundary_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=boundary_writer.id,
            position=1,
            tool_name="update_learning_boundary",
            execution=boundary_execution,
            tool_arguments=boundary_arguments,
        )
        boundary_saved = execute_tool(
            db,
            actor,
            boundary_identity,
            "update_learning_boundary",
            boundary_arguments,
            learning_tools(),
        )
        assert boundary_saved == {"ok": True, "result": {"saved": True}}
        saved_attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert saved_attempt is not None and saved_attempt.status == "completed"
        assert attempt_has_final_evidence(db, saved_attempt)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AssessmentAttemptEvent)
                .where(
                    AssessmentAttemptEvent.attempt_id == saved_attempt.id,
                    AssessmentAttemptEvent.event_kind == "complete",
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(RuntimeToolReceipt)
                .where(
                    RuntimeToolReceipt.tool_name == "update_learning_boundary",
                    RuntimeToolReceipt.turn_id == boundary_identity.turn_id,
                )
            )
            == 1
        )
        assert (
            execute_tool(
                db,
                actor,
                boundary_identity,
                "update_learning_boundary",
                boundary_arguments,
                learning_tools(),
            )
            == boundary_saved
        )
        assert (
            db.scalar(
                select(func.count(LearningBoundaryRevision.id)).where(
                    LearningBoundaryRevision.attempt_id == saved_attempt.id
                )
            )
            == 1
        )
        boundary_row = db.scalar(
            select(LearningBoundary).where(LearningBoundary.attempt_id == saved_attempt.id)
        )
        assert boundary_row is not None
        public_boundary_arguments = {"boundary_id": boundary_row.id}
        public_boundary_identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=teacher_conversation_id,
            agent_version_id=str(db.get(Conversation, teacher_conversation_id).agent_version_id),
            position=1,
            tool_name="read_learning_boundary",
            tool_arguments=public_boundary_arguments,
        )
        public_boundary_result = execute_tool(
            db,
            teacher,
            public_boundary_identity,
            "read_learning_boundary",
            public_boundary_arguments,
            learning_tools(),
        )
        assert public_boundary_result["ok"] is True
        public_boundary = public_boundary_result["result"]
        assert public_boundary["boundary"]["summary"].startswith("The learner revised")
        saved_attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert saved_attempt is not None and saved_attempt.status == "completed"
        old_attempt_id = saved_attempt.id
        terminal_view = read_own_formal_attempt(
            db,
            actor,
            conversation_id,
            attempt_id=old_attempt_id,
        )
        assert terminal_view["assessment"]["overall_feedback"].startswith("Clear reasoning")
        assert terminal_view["boundary"]["summary"].startswith("The learner revised")

        teacher_activity = db.scalar(
            select(AssessmentActivity).where(
                AssessmentActivity.publication_id == publication_id,
                AssessmentActivity.team_id == team_id,
            )
        )
        assert teacher_activity is not None
        report_event_id = uuid4()
        receipt = create_assessment_course_report(
            db,
            teacher,
            course_id=COURSE_ID,
            activity_id=teacher_activity.id,
            client_event_id=report_event_id,
        )
        report = receipt.report
        assert report.content.student_count == 1
        assert report.content.attempt_count == 1
        assert report.content.completed_count == 1
        assert report.content.effective_answer_count == 2
        assert report.content.raw_answer_count == 3
        duplicate = create_assessment_course_report(
            db,
            teacher,
            course_id=COURSE_ID,
            activity_id=teacher_activity.id,
            client_event_id=report_event_id,
        )
        assert duplicate.report.revision_id == report.revision_id
        downloaded = download_assessment_course_report(
            db,
            teacher,
            report_id=str(report.id),
            revision_id=str(report.revision_id),
        )
        assert downloaded.filename.endswith(".md")
        assert "Raw answer records | 3" in downloaded.content
        assert "seven" not in downloaded.content
        with pytest.raises(PlatformError) as student_denied:
            read_assessment_activity_aggregate(
                db,
                actor,
                course_id=COURSE_ID,
                activity_id=teacher_activity.id,
            )
        assert student_denied.value.code == "not_found"

        new_attempt = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert new_attempt is not None and str(new_attempt.attempt.id) != old_attempt_id
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.attempt_id == old_attempt_id
                )
            )
            == 3
        )


def test_plain_abandon_redo_and_withdraw_keep_raw_answer_history(attempt_env: Any) -> None:
    _app, database, settings, client = attempt_env
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, _team_id, _team_version_id, _publication_id, _set_id, _source_questions = (
            _create_formal_conversation(db, visibility="public")
        )
        actor = _context(db, settings, token)
        first = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert first is not None and first.current_question is not None
        qversion = first.current_question.question_version_id
        mark_attempt_question_presented(db, actor, conversation_id, question_version_id=qversion)
        saved = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="Answer one is retained.",
            decision=_answer_decision(uuid4(), qversion, "one"),
        )
        assert saved is not None

        abandoned = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="I abandon this attempt.",
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(), classification="abandon_request"
            ),
        )
        assert abandoned is not None and abandoned.response_key == "assessment.abandoned"
        assert abandoned.context.attempt.status == "abandoned"
        assert (
            db.get(AssessmentAttempt, str(first.attempt.id)).abandonment_reason == "user_abandoned"
        )
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.attempt_id == str(first.attempt.id)
                )
            )
            == 1
        )
        assert get_assessment_runtime_context(db, actor, conversation_id) is None
        restarted = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert restarted is not None and restarted.attempt.id != first.attempt.id

        redo_event_id = uuid4()
        redo_decision = AssessmentRuntimeDecision(
            client_event_id=redo_event_id, classification="redo_request"
        )
        redo_message = "Abandon this attempt and redo it."
        redo = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=redo_message,
            decision=redo_decision,
        )
        assert redo is not None and redo.response_key == "assessment.abandoned_and_restarted"
        replacement_id = str(redo.context.attempt.id)
        assert replacement_id != str(restarted.attempt.id)
        assert (
            db.get(AssessmentAttempt, str(restarted.attempt.id)).abandonment_reason == "user_redo"
        )
        replayed_redo = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=redo_message,
            decision=redo_decision,
        )
        assert replayed_redo is not None
        assert replayed_redo.response_key == "assessment.abandoned_and_restarted"
        assert str(replayed_redo.context.attempt.id) == replacement_id
        with pytest.raises(PlatformError) as redo_conflict:
            apply_assessment_decision(
                db,
                actor,
                conversation_id,
                user_message="A different redo request with the same event key.",
                decision=redo_decision,
            )
        assert redo_conflict.value.code == "idempotency_conflict"
        assert (
            db.scalar(
                select(func.count(AssessmentAttempt.id)).where(
                    AssessmentAttempt.team_id == _team_id,
                    AssessmentAttempt.actor_user_id == STUDENT_ID,
                )
            )
            == 3
        )

        withdrawn_conversation = _copy_conversation(
            db,
            conversation_id,
            actor_user_id=OTHER_STUDENT_ID,
            visibility="public",
        )
        # The helper authenticates the current student, so use the other learner's
        # session for an independent actor provenance.
        other_actor = _service_actor(db, settings, OTHER_STUDENT_ID)
        other_started = start_or_resume_attempt(
            db, other_actor, withdrawn_conversation, client_event_id=uuid4()
        )
        assert other_started is not None
        assert withdraw_conversation_attempts(db, withdrawn_conversation) == 1
        withdrawn_attempt = db.get(AssessmentAttempt, str(other_started.attempt.id))
        assert withdrawn_attempt is not None
        assert withdrawn_attempt.status == "abandoned"
        assert withdrawn_attempt.abandonment_reason == "chat_withdrawn"
        assert (
            db.scalar(
                select(func.count(AssessmentAttemptEvent.id)).where(
                    AssessmentAttemptEvent.attempt_id == withdrawn_attempt.id,
                    AssessmentAttemptEvent.event_kind == "withdraw",
                )
            )
            == 1
        )


def test_original_actor_can_abandon_after_question_source_revocation(attempt_env: Any) -> None:
    _app, database, settings, client = attempt_env
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            set_id,
            _source_questions,
        ) = _create_formal_conversation(db, visibility="private")
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        question_version_id = started.current_question.question_version_id
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=question_version_id,
        )
        answered = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="My recorded answer is seven.",
            decision=_answer_decision(uuid4(), question_version_id, "seven"),
        )
        assert answered is not None
        attempt_id = str(started.attempt.id)
        activity_id = str(started.attempt.activity_id)

        # Match a real Knowledge Set revoke: authorization epochs are monotone,
        # so old pinned Question content cannot be read through the new ACL.
        knowledge_set = db.get(KnowledgeSet, set_id)
        assert knowledge_set is not None
        original_epoch = knowledge_set.authorization_epoch
        knowledge_set.authorization_epoch += 1
        db.flush()
        with pytest.raises(PlatformError) as source_denied:
            get_assessment_runtime_context(db, actor, conversation_id)
        assert source_denied.value.code == "assessment_question_source_stale"

        abandon_event = uuid4()
        abandon_decision = AssessmentRuntimeDecision(
            client_event_id=abandon_event,
            classification="abandon_request",
        )
        abandon_message = "I explicitly abandon this assessment."
        abandoned = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=abandon_message,
            decision=abandon_decision,
        )
        assert abandoned is not None and abandoned.response_key == "assessment.abandoned"
        assert abandoned.context.attempt.id == started.attempt.id
        assert abandoned.context.attempt.status == "abandoned"
        assert abandoned.context.current_question is None
        assert "Question one" not in abandoned.model_dump_json()
        assert knowledge_set.authorization_epoch == original_epoch + 1

        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None
        assert attempt.abandonment_reason == "user_abandoned"
        assert attempt.status == "abandoned"
        saved_answer = db.scalar(
            select(LearningRecord).where(
                LearningRecord.attempt_id == attempt_id,
                LearningRecord.record_kind == "answer",
            )
        )
        assert saved_answer is not None
        assert json.loads(saved_answer.payload_json)["answer_text"] == "seven"

        # The original student can replay the exact decision without reopening
        # the revoked source, while a reused event id with a different message
        # remains a conflict.
        replayed = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=abandon_message,
            decision=abandon_decision,
        )
        assert replayed is not None and replayed.response_key == "assessment.abandoned"
        assert replayed.context.attempt.id == started.attempt.id
        assert replayed.context.current_question is None
        with pytest.raises(PlatformError) as changed_payload:
            apply_assessment_decision(
                db,
                actor,
                conversation_id,
                user_message="A different action using the same event id.",
                decision=abandon_decision,
            )
        assert changed_payload.value.code == "idempotency_conflict"

        other_actor = _service_actor(db, settings, OTHER_STUDENT_ID)
        with pytest.raises(PlatformError) as unauthorized_actor:
            apply_assessment_decision(
                db,
                other_actor,
                conversation_id,
                user_message=abandon_message,
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="abandon_request",
                ),
            )
        assert unauthorized_actor.value.code == "not_found"
        assert (
            db.scalar(
                select(func.count(AssessmentAttempt.id)).where(
                    AssessmentAttempt.activity_id == activity_id,
                    AssessmentAttempt.actor_user_id == STUDENT_ID,
                )
            )
            == 1
        )


def test_explicit_attempt_action_route_abandons_revoked_source_and_replays(
    attempt_env: Any,
) -> None:
    _app, database, settings, client = attempt_env
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, _team_id, _version_id, _publication_id, set_id, _questions = (
            _create_formal_conversation(db, visibility="private")
        )
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        knowledge_set = db.get(KnowledgeSet, set_id)
        assert knowledge_set is not None
        knowledge_set.authorization_epoch += 1
        db.flush()
        with pytest.raises(PlatformError):
            get_assessment_runtime_context(db, actor, conversation_id)
        attempt_id = str(started.attempt.id)

    event_id = uuid4()
    payload = {"client_event_id": str(event_id), "action": "abandon"}
    response = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_key"] == "assessment.abandoned"
    assert body["context"]["attempt"]["status"] == "abandoned"
    assert body["context"]["current_question"] is None

    replay = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["context"]["attempt"]["id"] == body["context"]["attempt"]["id"]

    changed_payload = {"client_event_id": str(event_id), "action": "redo"}
    conflict_response = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=changed_payload,
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "idempotency_conflict"

    _other_token, other_csrf = _login(client, "kaikai")
    unauthorized = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": other_csrf},
        json={"client_event_id": str(uuid4()), "action": "abandon"},
    )
    assert unauthorized.status_code == 404


def test_successful_noop_lifecycle_actions_are_durable_and_idempotent(attempt_env: Any) -> None:
    _app, database, settings, client = attempt_env
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, *_ = _create_formal_conversation(db, visibility="private")
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt_id = str(started.attempt.id)

    resume_event_id = uuid4()
    resume_payload = {"client_event_id": str(resume_event_id), "action": "resume"}
    first_resume = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=resume_payload,
    )
    assert first_resume.status_code == 200, first_resume.text
    assert first_resume.json()["context"]["attempt"]["status"] == "in_progress"
    with database.session() as db:
        first_event = db.scalar(
            select(AssessmentAttemptEvent).where(
                AssessmentAttemptEvent.attempt_id == attempt_id,
                AssessmentAttemptEvent.client_event_id == str(resume_event_id),
            )
        )
        assert first_event is not None
        assert first_event.event_kind == "resume"
        assert first_event.classification == "resume_request"
        assert len(first_event.request_hash) == 64

    pause = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"client_event_id": str(uuid4()), "action": "pause"},
    )
    assert pause.status_code == 200, pause.text
    assert pause.json()["context"]["attempt"]["status"] == "paused"

    resumed_replay = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=resume_payload,
    )
    assert resumed_replay.status_code == 200, resumed_replay.text
    assert resumed_replay.json()["response_key"] == "assessment.resumed"
    assert resumed_replay.json()["context"]["attempt"]["status"] == "paused"
    changed_action = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"client_event_id": str(resume_event_id), "action": "abandon"},
    )
    assert changed_action.status_code == 409
    assert changed_action.json()["code"] == "idempotency_conflict"
    with database.session() as db:
        assert db.get(AssessmentAttempt, attempt_id).status == "paused"
        assert (
            db.scalar(
                select(func.count(AssessmentAttemptEvent.id)).where(
                    AssessmentAttemptEvent.attempt_id == attempt_id
                )
            )
            == 3
        )

    pause_event_id = uuid4()
    pause_payload = {"client_event_id": str(pause_event_id), "action": "pause"}
    repeated_pause = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=pause_payload,
    )
    assert repeated_pause.status_code == 200, repeated_pause.text
    assert repeated_pause.json()["context"]["attempt"]["status"] == "paused"
    with database.session() as db:
        assert (
            db.scalar(
                select(AssessmentAttemptEvent.id).where(
                    AssessmentAttemptEvent.attempt_id == attempt_id,
                    AssessmentAttemptEvent.client_event_id == str(pause_event_id),
                )
            )
            is not None
        )

    resume_again = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json={"client_event_id": str(uuid4()), "action": "resume"},
    )
    assert resume_again.status_code == 200, resume_again.text
    assert resume_again.json()["context"]["attempt"]["status"] == "in_progress"
    pause_replay = client.post(
        f"/api/v1/learning/attempts/{attempt_id}/actions",
        headers={"X-CSRF-Token": csrf},
        json=pause_payload,
    )
    assert pause_replay.status_code == 200, pause_replay.text
    assert pause_replay.json()["response_key"] == "assessment.paused"
    assert pause_replay.json()["context"]["attempt"]["status"] == "in_progress"

    with database.session() as db:
        actor = _context(db, settings, token)
        tool_resume = AssessmentRuntimeDecision(
            client_event_id=uuid4(), classification="resume_request"
        )
        tool_resume_message = "Resume the assessment."
        first_tool_resume = apply_assessment_decision(
            db,
            actor,
            str(started.attempt.conversation_id),
            user_message=tool_resume_message,
            decision=tool_resume,
        )
        assert first_tool_resume is not None
        assert first_tool_resume.context.attempt.status == "in_progress"
        tool_pause = apply_assessment_decision(
            db,
            actor,
            str(started.attempt.conversation_id),
            user_message="Pause the assessment.",
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(), classification="pause_request"
            ),
        )
        assert tool_pause is not None and tool_pause.context.attempt.status == "paused"
        replayed_tool_resume = apply_assessment_decision(
            db,
            actor,
            str(started.attempt.conversation_id),
            user_message=tool_resume_message,
            decision=tool_resume,
        )
        assert replayed_tool_resume is not None
        assert replayed_tool_resume.context.attempt.status == "paused"
        with pytest.raises(PlatformError) as tool_event_conflict:
            apply_assessment_decision(
                db,
                actor,
                str(started.attempt.conversation_id),
                user_message=tool_resume_message,
                decision=AssessmentRuntimeDecision(
                    client_event_id=tool_resume.client_event_id,
                    classification="abandon_request",
                ),
            )
        assert tool_event_conflict.value.code == "idempotency_conflict"


def test_paused_attempt_cannot_resume_after_source_revocation_but_can_abandon(
    attempt_env: Any,
) -> None:
    _app, database, settings, client = attempt_env
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        (
            conversation_id,
            _team_id,
            _version_id,
            _publication_id,
            set_id,
            _questions,
        ) = _create_formal_conversation(db, visibility="private")
        actor = _context(db, settings, token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        paused = apply_attempt_lifecycle_action(
            db,
            actor,
            str(started.attempt.id),
            client_event_id=uuid4(),
            action="pause",
        )
        assert paused is not None and paused.response_key == "assessment.paused"
        assert paused.context.attempt.status == "paused"
        assert paused.context.current_question is None

        knowledge_set = db.get(KnowledgeSet, set_id)
        assert knowledge_set is not None
        knowledge_set.authorization_epoch += 1
        db.flush()
        with pytest.raises(PlatformError) as resume_denied:
            apply_attempt_lifecycle_action(
                db,
                actor,
                str(started.attempt.id),
                client_event_id=uuid4(),
                action="resume",
            )
        assert resume_denied.value.code == "assessment_question_source_stale"
        saved_attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert saved_attempt is not None and saved_attempt.status == "paused"

        abandoned = apply_attempt_lifecycle_action(
            db,
            actor,
            str(started.attempt.id),
            client_event_id=uuid4(),
            action="abandon",
        )
        assert abandoned is not None and abandoned.response_key == "assessment.abandoned"
        assert abandoned.context.attempt.status == "abandoned"


def test_presented_question_survives_real_rag_source_replacement(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    _agent_id, document_id, initial_run_id, knowledge_set_id = _create_generation_run(
        client, database
    )
    _teacher_token, teacher_csrf = _login(client, "maya")

    def candidate(
        prompt: str,
        reference: str,
        rubric_guidance: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        content = json.loads(_question_content(prompt, reference))
        content["rubric"]["criteria"][0]["guidance"] = rubric_guidance
        return {
            "content": content,
            "source_receipt_ids": [receipt_id],
            "citation_unverified": False,
        }

    with database.session() as db:
        initial_receipt = db.scalar(
            select(KnowledgeGenerationSourceReceipt).where(
                KnowledgeGenerationSourceReceipt.run_id == initial_run_id
            )
        )
        document = db.get(KnowledgeDocument, document_id)
        assert initial_receipt is not None and document is not None
        first_file_id = document.stored_file_id
        original_hash = document.content_hash
        original_index_revision = document.index_revision

    first_stage = [
        candidate(
            "Original first question",
            "Old answer one",
            "RAG_RUBRIC_V1_FIRST",
            initial_receipt.id,
        ),
        candidate(
            "Original second question",
            "Old answer two",
            "RAG_RUBRIC_V1_SECOND",
            initial_receipt.id,
        ),
    ]
    _accept_knowledge_stage(database, initial_run_id, first_stage)
    materialize_accepted_knowledge_generation(
        database.session_factory,
        initial_run_id,
        _run_claim(database, initial_run_id),
        data_root=settings.resolved_data_root,
    )

    with database.session() as db:
        (
            conversation_id,
            _team_id,
            team_version_id,
            _publication_id,
            fixture_set_id,
            _fixture_questions,
        ) = _create_formal_conversation(db, visibility="private")
        team_set = db.scalar(
            select(TeamVersionSet).where(
                TeamVersionSet.team_version_id == team_version_id,
                TeamVersionSet.knowledge_set_id == fixture_set_id,
            )
        )
        source_set = db.get(KnowledgeSet, knowledge_set_id)
        assert team_set is not None and source_set is not None
        team_set.knowledge_set_id = knowledge_set_id
        team_set.authorization_epoch = source_set.authorization_epoch
        db.flush()

        initial_question_versions = db.scalars(
            select(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetVersion.asset_id)
            .where(KnowledgeAsset.knowledge_set_id == knowledge_set_id)
        ).all()
        initial_question_prompts = {
            QuestionContent.model_validate_json(version.content_json).prompt
            for version in initial_question_versions
        }
        assert initial_question_prompts == {
            "Original first question",
            "Original second question",
        }

        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        first_question_version_id = started.current_question.question_version_id
        assert started.current_question.prompt == "Original first question"
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=first_question_version_id,
        )

    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        original_hash = document.content_hash
        original_index_revision = document.index_revision
    replacement = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-rag-replace-{uuid4()}",
        },
        data={
            "expected_content_hash": original_hash,
            "expected_index_revision": str(original_index_revision),
        },
        files={
            "file": (
                "lesson-updated.md",
                b"# Updated lesson\n\nThe current RAG source has new content.\n",
                "text/markdown",
            )
        },
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["id"] == document_id

    with database.session() as db:
        source_set = db.get(KnowledgeSet, knowledge_set_id)
        current_binding = db.scalar(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.knowledge_set_id == knowledge_set_id,
                KnowledgeSetSource.is_active.is_(True),
            )
        )
        assert source_set is not None and current_binding is not None
        binding_id = current_binding.id
        assert current_binding.stored_file_id != first_file_id
        replacement_run = db.scalar(
            select(KnowledgeGenerationRun)
            .where(KnowledgeGenerationRun.knowledge_set_id == knowledge_set_id)
            .order_by(KnowledgeGenerationRun.intent_generation.desc())
        )
        assert replacement_run is not None and replacement_run.id != initial_run_id
        replacement_receipt = db.scalar(
            select(KnowledgeGenerationSourceReceipt).where(
                KnowledgeGenerationSourceReceipt.run_id == replacement_run.id
            )
        )
        assert replacement_receipt is not None
        assert replacement_receipt.stored_file_id == current_binding.stored_file_id

        second_stage = [
            candidate(
                "Updated first question",
                "New answer one",
                "RAG_RUBRIC_V2_FIRST",
                replacement_receipt.id,
            ),
            candidate(
                "Updated second question",
                "New answer two",
                "RAG_RUBRIC_V2_SECOND",
                replacement_receipt.id,
            ),
            candidate(
                "New canonical third question",
                "New answer three",
                "RAG_RUBRIC_V2_THIRD",
                replacement_receipt.id,
            ),
        ]
    _accept_knowledge_stage(database, replacement_run.id, second_stage)
    materialize_accepted_knowledge_generation(
        database.session_factory,
        replacement_run.id,
        _run_claim(database, replacement_run.id),
        data_root=settings.resolved_data_root,
    )

    with database.session() as db:
        actor = _service_actor(db, settings, STUDENT_ID)
        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert activity is not None
        generated_catalog = refresh_assessment_activity_questions(
            db, actor, conversation_id, activity
        )
        assert activity.question_selection_revision == 2
        assert len(generated_catalog) == 3
        second_question_asset_id = generated_catalog[1].asset_id
        generated_second_question_version_id = generated_catalog[1].question_version_id

    with database.session() as db:
        actor = _service_actor(db, settings, STUDENT_ID)
        refreshed = get_assessment_runtime_context(db, actor, conversation_id)
        assert refreshed is not None and refreshed.current_question is not None
        assert refreshed.current_question.question_version_id == first_question_version_id
        assert refreshed.current_question.prompt == "Original first question"
        pinned_content = QuestionContent.model_validate_json(
            db.get(KnowledgeAssetVersion, str(first_question_version_id)).content_json
        )
        assert pinned_content.rubric.criteria[0].guidance == "RAG_RUBRIC_V1_FIRST"

        first_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="The first answer is seven.",
            decision=_answer_decision(uuid4(), first_question_version_id, "seven"),
        )
        assert first_answer is not None and first_answer.context.current_question is not None
        generated_unpresented_question_version_id = (
            first_answer.context.current_question.question_version_id
        )
        assert first_answer.context.current_question.prompt == "Updated second question"
        assert generated_unpresented_question_version_id == UUID(
            generated_second_question_version_id
        )
        generated_unpresented_content = QuestionContent.model_validate_json(
            db.get(
                KnowledgeAssetVersion, str(generated_unpresented_question_version_id)
            ).content_json
        )
        assert generated_unpresented_content.rubric.criteria[0].guidance == "RAG_RUBRIC_V2_SECOND"

    current_markdown = client.get(f"/api/v1/knowledge-sets/{knowledge_set_id}/markdown")
    assert current_markdown.status_code == 200, current_markdown.text
    assert "### Question 3" in current_markdown.json()["markdown"]
    title = current_markdown.json()["markdown"].splitlines()[0]
    manual_markdown = (
        f"{title}\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "Updated first question\n\n"
        "#### Rubric\n\n"
        "- **Reasoning** (2): MANUAL_RUBRIC_FIRST\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "Manual reference answer one\n\n"
        "### Question 2\n\n"
        "Updated second question\n\n"
        "#### Rubric\n\n"
        "- **Reasoning** (2): MANUAL_RUBRIC_SECOND\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        "Manual reference answer two\n"
    )
    manual_save = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set_id}/markdown",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-manual-question-edit-{uuid4()}",
        },
        json={
            "expected_version_seq": current_markdown.json()["version_seq"],
            "markdown": manual_markdown,
        },
    )
    assert manual_save.status_code == 200, manual_save.text
    assert manual_save.json()["markdown"] == manual_markdown

    with database.session() as db:
        actor = _service_actor(db, settings, STUDENT_ID)
        source_set = db.get(KnowledgeSet, knowledge_set_id)
        assert source_set is not None
        manual_second_question_version = current_question_version_for_asset(
            db, source_set, second_question_asset_id
        )
        assert manual_second_question_version is not None
        assert manual_second_question_version.id != generated_second_question_version_id
        manual_second_question = QuestionContent.model_validate_json(
            manual_second_question_version.content_json
        )
        assert manual_second_question.rubric.criteria[0].guidance == "MANUAL_RUBRIC_SECOND"
        manual_second_question_version_id = manual_second_question_version.id

        refreshed = get_assessment_runtime_context(db, actor, conversation_id)
        assert refreshed is not None and refreshed.current_question is not None
        assert refreshed.current_question.prompt == "Updated second question"
        second_question_version_id = refreshed.current_question.question_version_id
        assert second_question_version_id == UUID(manual_second_question_version_id)
        assert second_question_version_id != generated_unpresented_question_version_id
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=second_question_version_id,
        )
        second_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="The second answer is two.",
            decision=_answer_decision(uuid4(), second_question_version_id, "two"),
        )
        assert second_answer is not None

        activity = db.get(AssessmentActivity, str(started.attempt.activity_id))
        assert activity is not None
        evaluator = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.evaluator_team_member_id,
            )
        )
        boundary_writer = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.boundary_team_member_id,
            )
        )
        assert evaluator is not None and boundary_writer is not None
        evaluator_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
        )
        evaluator_context = get_assessment_executor_context(
            db,
            actor,
            conversation_id,
            turn_id=evaluator_execution[0],
            participant_id=evaluator.id,
            result_id=evaluator_execution[1],
            purpose="assessment_evaluate",
        )
        assert evaluator_context is not None
        evaluation_questions = json.loads(evaluator_context.task_payload_json)["questions"]
        assert [question["prompt"] for question in evaluation_questions] == [
            "Original first question",
            "Updated second question",
        ]
        assert [
            question["rubric"]["criteria"][0]["guidance"] for question in evaluation_questions
        ] == [
            "RAG_RUBRIC_V1_FIRST",
            "MANUAL_RUBRIC_SECOND",
        ]
        evaluator_identity = _accepted_tool_identity(
            db,
            template_stage_id=str(
                db.scalar(
                    select(TeamProviderCall.id).where(
                        TeamProviderCall.operation_id == template_operation_id
                    )
                )
            ),
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
            tool_name="edit_assessment",
            execution=evaluator_execution,
        )
        assert write_formal_assessment(
            db,
            actor,
            evaluator_identity,
            {
                "overall_feedback": "The original and updated questions were both answered.",
                "questions": [
                    {"question_ordinal": 0, "feedback": "Used the original rubric."},
                    {"question_ordinal": 1, "feedback": "Used the updated rubric."},
                ],
            },
        ) == {"saved": True}
        _finish_executor_turn(db, evaluator_execution)

        boundary_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=boundary_writer.id,
            position=1,
        )
        boundary_context = get_assessment_executor_context(
            db,
            actor,
            conversation_id,
            turn_id=boundary_execution[0],
            participant_id=boundary_writer.id,
            result_id=boundary_execution[1],
            purpose="boundary_summarize",
        )
        assert boundary_context is not None
        boundary_identity = _accepted_tool_identity(
            db,
            template_stage_id=str(
                db.scalar(
                    select(TeamProviderCall.id).where(
                        TeamProviderCall.operation_id == template_operation_id
                    )
                )
            ),
            conversation_id=conversation_id,
            participant_id=boundary_writer.id,
            position=1,
            tool_name="update_learning_boundary",
            execution=boundary_execution,
        )
        assert write_formal_boundary(
            db,
            actor,
            boundary_identity,
            {
                "summary": "The learner moved from the original source revision to its update.",
                "strengths": ["Persistence"],
                "areas_to_explore": [],
                "next_step": "Compare explanations from later sources.",
            },
        ) == {"saved": True}
        _finish_executor_turn(db, boundary_execution)
        saved_attempt = db.get(AssessmentAttempt, str(started.attempt.id))
        assert saved_attempt is not None and saved_attempt.status == "completed"
        assert attempt_has_final_evidence(db, saved_attempt)

        # A subsequent attempt still rejects an actual Knowledge Set unbind.
        next_attempt = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert next_attempt is not None and next_attempt.current_question is not None
        assert next_attempt.progress.question_count == 2
        assert next_attempt.current_question.prompt == "Updated first question"
        current_activity = db.get(AssessmentActivity, str(next_attempt.attempt.activity_id))
        assert current_activity is not None
        assert current_activity.question_selection_revision == 3
        original_attempt_questions = db.scalars(
            select(AssessmentAttemptQuestion).where(
                AssessmentAttemptQuestion.attempt_id == str(started.attempt.id)
            )
        ).all()
        assert len(original_attempt_questions) == 2
        assert all(
            db.get(AssessmentActivityQuestion, question.activity_question_id).selection_revision
            == 1
            for question in original_attempt_questions
        )
        next_attempt_questions = db.scalars(
            select(AssessmentAttemptQuestion)
            .where(AssessmentAttemptQuestion.attempt_id == str(next_attempt.attempt.id))
            .order_by(AssessmentAttemptQuestion.ordinal)
        ).all()
        assert len(next_attempt_questions) == 2
        assert all(
            db.get(AssessmentActivityQuestion, question.activity_question_id).selection_revision
            == 3
            for question in next_attempt_questions
        )
        generated_revision_questions = db.scalars(
            select(AssessmentActivityQuestion).where(
                AssessmentActivityQuestion.activity_id == current_activity.id,
                AssessmentActivityQuestion.selection_revision == 2,
            )
        ).all()
        assert len(generated_revision_questions) == 3
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=next_attempt.current_question.question_version_id,
        )
        next_answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="The updated first answer is eight.",
            decision=_answer_decision(
                uuid4(), next_attempt.current_question.question_version_id, "eight"
            ),
        )
        assert next_answer is not None and next_answer.context.current_question is not None
        assert next_answer.context.current_question.prompt == "Updated second question"
        assert next_answer.context.progress.resolved_count == 1
        assert next_answer.context.progress.question_count == 2
        source_set = db.get(KnowledgeSet, knowledge_set_id)
        assert source_set is not None
        set_content_revision = source_set.content_revision

    unbound = client.request(
        "DELETE",
        f"/api/v1/knowledge-sets/{knowledge_set_id}/sources/{binding_id}",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-rag-unbind-{uuid4()}",
        },
        json={"expected_content_revision": set_content_revision},
    )
    assert unbound.status_code == 200, unbound.text
    with database.session() as db:
        actor = _service_actor(db, settings, STUDENT_ID)
        with pytest.raises(PlatformError) as unbound_denied:
            get_assessment_runtime_context(db, actor, conversation_id)
        assert unbound_denied.value.code == "assessment_question_source_stale"
        # Reactivate only inside this isolated fixture to exercise the separate
        # library-hide fence; production rebind creates a new source binding.
        old_binding = db.get(KnowledgeSetSource, binding_id)
        assert old_binding is not None and not old_binding.is_active
        old_binding.is_active = True
        db.flush()
        assert get_assessment_runtime_context(db, actor, conversation_id) is not None

    hidden = client.post(
        f"/api/v1/knowledge-documents/{document_id}/hide",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-rag-hide-{uuid4()}",
        },
    )
    assert hidden.status_code == 200, hidden.text
    with database.session() as db:
        actor = _service_actor(db, settings, STUDENT_ID)
        with pytest.raises(PlatformError) as hidden_denied:
            get_assessment_runtime_context(db, actor, conversation_id)
        assert hidden_denied.value.code == "assessment_question_source_stale"
        abandoned = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="I explicitly abandon after the source is hidden.",
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(),
                classification="abandon_request",
            ),
        )
        assert abandoned is not None and abandoned.response_key == "assessment.abandoned"


def test_presented_question_history_survives_source_reauthorization_and_replace(
    attempt_env: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _agent_id, document_id, _initial_run_id, knowledge_set_id = _create_generation_run(
        client, database
    )
    _teacher_token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        assert document is not None
        initial_hash = document.content_hash
        initial_index_revision = document.index_revision

    primed = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-history-prime-{uuid4()}",
        },
        data={
            "expected_content_hash": initial_hash,
            "expected_index_revision": str(initial_index_revision),
        },
        files={
            "file": (
                "lesson-v1.md",
                b"# Existing content head\n\nThis source version predates reauthorization.",
                "text/markdown",
            )
        },
    )
    assert primed.status_code == 201, primed.text
    with database.session() as db:
        document = db.get(KnowledgeDocument, document_id)
        knowledge_set = db.get(KnowledgeSet, knowledge_set_id)
        assert document is not None and knowledge_set is not None
        old_document_epoch = document.authorization_epoch
        old_visibility = document.visibility
        reauthorized_file_id = document.stored_file_id
        revision = knowledge_set.content_revision

    changed = client.patch(
        f"/api/v1/knowledge-documents/{document_id}",
        headers={"X-CSRF-Token": teacher_csrf},
        json={
            "expected_authorization_epoch": old_document_epoch,
            "visibility": "public" if old_visibility == "private" else "private",
        },
    )
    assert changed.status_code == 200, changed.text
    rebound = client.put(
        f"/api/v1/knowledge-sets/{knowledge_set_id}/sources",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-history-rebind-{uuid4()}",
        },
        json={
            "expected_content_revision": revision,
            "source_document_ids": [document_id],
        },
    )
    assert rebound.status_code == 200, rebound.text

    with database.session() as db:
        current_run = db.scalar(
            select(KnowledgeGenerationRun)
            .where(KnowledgeGenerationRun.knowledge_set_id == knowledge_set_id)
            .order_by(KnowledgeGenerationRun.intent_generation.desc())
        )
        assert current_run is not None
        current_run_id = current_run.id
        receipt = db.scalar(
            select(KnowledgeGenerationSourceReceipt).where(
                KnowledgeGenerationSourceReceipt.run_id == current_run_id
            )
        )
        assert receipt is not None
        assert receipt.stored_file_id == reauthorized_file_id
        source_receipt_id = receipt.id

    _accept_knowledge_stage(
        database,
        current_run_id,
        [
            {
                "content": json.loads(
                    _question_content(
                        "Reauthorized source question", "Use the current lesson evidence."
                    )
                ),
                "source_receipt_ids": [source_receipt_id],
                "citation_unverified": False,
            }
        ],
    )
    materialize_accepted_knowledge_generation(
        database.session_factory,
        current_run_id,
        _run_claim(database, current_run_id),
        data_root=settings.resolved_data_root,
    )

    student_token, _student_csrf = _login(client, "bowen")
    with database.session() as db:
        (
            conversation_id,
            _team_id,
            team_version_id,
            _publication_id,
            fixture_set_id,
            _fixture_questions,
        ) = _create_formal_conversation(db, visibility="private")
        team_set = db.scalar(
            select(TeamVersionSet).where(
                TeamVersionSet.team_version_id == team_version_id,
                TeamVersionSet.knowledge_set_id == fixture_set_id,
            )
        )
        knowledge_set = db.get(KnowledgeSet, knowledge_set_id)
        assert team_set is not None and knowledge_set is not None
        team_set.knowledge_set_id = knowledge_set_id
        team_set.authorization_epoch = knowledge_set.authorization_epoch
        db.flush()

        actor = _context(db, settings, student_token)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None and started.current_question is not None
        question_version_id = str(started.current_question.question_version_id)
        assert started.current_question.prompt == "Reauthorized source question"
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=question_version_id,
        )
        question_version = db.get(KnowledgeAssetVersion, question_version_id)
        reference = db.scalar(
            select(KnowledgeAssetVersionSource).where(
                KnowledgeAssetVersionSource.asset_version_id == question_version_id
            )
        )
        current_binding = db.scalar(
            select(KnowledgeSetSource).where(
                KnowledgeSetSource.knowledge_set_id == knowledge_set_id,
                KnowledgeSetSource.is_active.is_(True),
            )
        )
        document = db.get(KnowledgeDocument, document_id)
        assert question_version is not None
        assert reference is not None
        assert reference.stored_file_id == reauthorized_file_id
        assert reference.source_authorization_epoch == 1
        assert current_binding is not None and current_binding.source_authorization_epoch == 1
        assert document is not None and document.authorization_epoch == 1
        assert question_sources_readable(db, knowledge_set, question_version)
        binding_id = current_binding.id
        current_hash = document.content_hash
        current_index_revision = document.index_revision

    _teacher_token, teacher_csrf = _login(client, "maya")
    replaced = client.post(
        f"/api/v1/knowledge-documents/{document_id}/replace",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": teacher_csrf,
            "Idempotency-Key": f"maya-history-replace-after-rebind-{uuid4()}",
        },
        data={
            "expected_content_hash": current_hash,
            "expected_index_revision": str(current_index_revision),
        },
        files={
            "file": (
                "lesson-v2.md",
                b"# New content head\n\nThis source content changed after reauthorization.",
                "text/markdown",
            )
        },
    )
    assert replaced.status_code == 201, replaced.text

    student_token, _student_csrf = _login(client, "bowen")
    with database.session() as db:
        knowledge_set = db.get(KnowledgeSet, knowledge_set_id)
        document = db.get(KnowledgeDocument, document_id)
        binding = db.get(KnowledgeSetSource, binding_id)
        version = db.get(KnowledgeAssetVersion, question_version_id)
        reference = db.scalar(
            select(KnowledgeAssetVersionSource).where(
                KnowledgeAssetVersionSource.asset_version_id == question_version_id
            )
        )
        assert reference is not None
        historic_content = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document_id,
                KnowledgeDocumentVersion.stored_file_id == reauthorized_file_id,
                KnowledgeDocumentVersion.content_hash == reference.source_content_hash,
                KnowledgeDocumentVersion.file_sha256 == reference.source_file_sha256,
            )
        )
        assert knowledge_set is not None and document is not None and binding is not None
        assert version is not None and historic_content is not None
        assert historic_content.authorization_epoch == 0
        assert reference.source_authorization_epoch == 1
        assert historic_content.content_hash == reference.source_content_hash
        assert historic_content.file_sha256 == reference.source_file_sha256
        assert binding.source_authorization_epoch == document.authorization_epoch == 1
        assert question_sources_readable(db, knowledge_set, version)

        actor = _context(db, settings, student_token)
        resumed = get_assessment_runtime_context(db, actor, conversation_id)
        assert resumed is not None and resumed.current_question is not None
        assert resumed.current_question.question_version_id == UUID(question_version_id)
        assert resumed.current_question.prompt == "Reauthorized source question"


def test_unpresented_question_cannot_be_answered_or_complete(attempt_env: Any) -> None:
    _app, database, settings, client = attempt_env
    token, _csrf = _login(client, "bowen")
    with database.session() as db:
        conversation_id, _team_id, _version_id, _publication_id, _set_id, _questions = (
            _create_formal_conversation(db)
        )
        actor = _context(db, settings, token)
        context = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert context is not None and context.current_question is not None
        answer = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="I know the answer is two.",
            decision=_answer_decision(uuid4(), context.current_question.question_version_id, "two"),
        )
        assert answer is not None and answer.response_key == "assessment.redirect"
        assert answer.context.progress.resolved_count == 0
        complete = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message="Complete this attempt.",
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(), classification="complete_request"
            ),
        )
        assert complete is not None and complete.context.attempt.status == "in_progress"
        assert (
            db.scalar(
                select(func.count(LearningRecord.id)).where(
                    LearningRecord.conversation_id == conversation_id
                )
            )
            == 0
        )


def test_explicit_resource_grant_allows_custom_team_edit_and_denies_without_grant(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    token, _csrf = _login(client, "bowen")
    with database.session() as template_db:
        template_stage = template_db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        template_stage_id = template_stage.id

    with database.session() as db:
        actor = _context(db, settings, token)
        conversation_id = _custom_conversation_with_participants(db, STUDENT_ID)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.entry_kind == "team"
        participant = db.scalar(
            select(ConversationParticipant)
            .where(ConversationParticipant.conversation_id == conversation_id)
            .order_by(ConversationParticipant.position)
        )
        assert participant is not None
        created = create_assessment(
            db,
            actor,
            conversation_id,
            CreateAssessmentRequest(
                client_event_id=uuid4(),
                content={"summary": "Student-authored practice record"},
            ),
        )
        assessment_id = str(created.assessment_id)
        grant = LearningAssessmentResourceGrant(
            id=str(uuid4()),
            assessment_id=assessment_id,
            owner_user_id=STUDENT_ID,
            course_id=COURSE_ID,
            conversation_id=conversation_id,
            participant_id=participant.id,
            team_member_id=participant.team_member_id,
            agent_version_id=participant.agent_version_id,
            agent_authorization_epoch=participant.agent_authorization_epoch,
            operation="edit",
            created_at=datetime.now(UTC),
            revoked_at=None,
        )
        db.add(grant)
        db.flush()

        execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=0,
        )
        content = {
            "overall_feedback": "This is an authorized practice revision.",
            "questions": [{"question_ordinal": 0, "feedback": "Try another example."}],
        }
        arguments = {"assessment_id": assessment_id, "content": content}
        identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=0,
            tool_name="edit_assessment",
            execution=execution,
            tool_arguments=arguments,
        )
        tool_result = execute_tool(
            db, actor, identity, "edit_assessment", arguments, learning_tools()
        )
        assert tool_result == {"ok": True, "result": {"saved": True}}
        head = db.get(LearningAssessment, assessment_id)
        assert head is not None and head.current_revision_seq == 2
        history = db.scalars(
            select(LearningAssessmentRevision)
            .where(LearningAssessmentRevision.assessment_id == assessment_id)
            .order_by(LearningAssessmentRevision.revision_seq)
        ).all()
        assert [revision.revision_source for revision in history] == [
            "user_authored",
            "practice_agent_edit",
        ]
        assert history[1].actor_user_id == STUDENT_ID
        assert history[1].editor_team_member_id == participant.team_member_id
        assert history[1].editor_agent_version_id == participant.agent_version_id
        assert history[1].evaluator_team_member_id is None
        assert history[1].source_model_call_id == identity.model_call_id
        assert history[1].source_tool_call_id == identity.tool_call_id
        projected = read_assessment(db, actor, conversation_id, assessment_id)
        assert [revision.revision_source for revision in projected.revisions] == [
            "user_authored",
            "practice_agent_edit",
        ]
        assert execute_tool(
            db, actor, identity, "edit_assessment", arguments, learning_tools()
        ) == {"ok": True, "result": {"saved": True}}
        assert head.current_revision_seq == 2
        _finish_executor_turn(db, execution)

        denied = create_assessment(
            db,
            actor,
            conversation_id,
            CreateAssessmentRequest(
                client_event_id=uuid4(),
                content={"summary": "A separate practice record"},
            ),
        )
        denied_id = str(denied.assessment_id)
        denied_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=1,
        )
        denied_content = {
            "overall_feedback": "This target has no grant.",
            "questions": [{"question_ordinal": 0, "feedback": "No edit permission."}],
        }
        denied_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            participant_id=participant.id,
            position=1,
            tool_name="edit_assessment",
            execution=denied_execution,
            tool_arguments={"assessment_id": denied_id, "content": denied_content},
        )
        no_grant = execute_tool(
            db,
            actor,
            denied_identity,
            "edit_assessment",
            {"assessment_id": denied_id, "content": denied_content},
            learning_tools(),
        )
        assert not no_grant["ok"] and no_grant["code"] == "assessment_edit_not_authorized"
        denied_head = db.get(LearningAssessment, denied_id)
        assert denied_head is not None and denied_head.current_revision_seq == 1


def test_explicit_single_agent_resource_grant_uses_the_same_edit_tool(
    attempt_env: Any,
    app_bundle: Any,
) -> None:
    _app, database, settings, client = attempt_env
    _template_database, _repository, template_operation_id = _dispatch(client, app_bundle)
    token, csrf = _login(client, "bowen")
    conversation_id = _start_chat(client, csrf)
    with database.session() as template_db:
        template_stage = template_db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        template_stage_id = template_stage.id

    with database.session() as db:
        actor = _context(db, settings, token)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.entry_kind == "agent"
        version = db.get(AgentVersion, conversation.agent_version_id)
        assert version is not None
        agent = db.get(Agent, version.agent_id)
        assert agent is not None
        created = create_assessment(
            db,
            actor,
            conversation_id,
            CreateAssessmentRequest(
                client_event_id=uuid4(), content={"summary": "Single Agent practice record"}
            ),
        )
        assessment_id = str(created.assessment_id)
        db.add(
            LearningAssessmentResourceGrant(
                id=str(uuid4()),
                assessment_id=assessment_id,
                owner_user_id=STUDENT_ID,
                course_id=COURSE_ID,
                conversation_id=conversation_id,
                participant_id=None,
                team_member_id=None,
                agent_version_id=version.id,
                agent_authorization_epoch=agent.authorization_epoch,
                operation="edit",
                created_at=datetime.now(UTC),
                revoked_at=None,
            )
        )
        db.flush()
        content = {
            "overall_feedback": "This authorized Single Agent practice revision is saved.",
            "questions": [{"question_ordinal": 0, "feedback": "Continue with evidence."}],
        }
        arguments = {"assessment_id": assessment_id, "content": content}
        identity = _accepted_single_tool_identity(
            db,
            template_stage_id=template_stage_id,
            conversation_id=conversation_id,
            agent_version_id=version.id,
            position=0,
            tool_name="edit_assessment",
            tool_arguments=arguments,
        )
        result = execute_tool(db, actor, identity, "edit_assessment", arguments, learning_tools())
        assert result == {"ok": True, "result": {"saved": True}}
        revisions = db.scalars(
            select(LearningAssessmentRevision)
            .where(LearningAssessmentRevision.assessment_id == assessment_id)
            .order_by(LearningAssessmentRevision.revision_seq)
        ).all()
        assert [revision.revision_source for revision in revisions] == [
            "user_authored",
            "practice_agent_edit",
        ]
        assert revisions[1].editor_team_member_id is None
        assert revisions[1].editor_agent_version_id == version.id
