from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from agno.models.response import ModelResponse
from app.core.errors import PlatformError
from app.core.models import AgentVersion, SessionRecord
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.models import KnowledgeSet
from app.modules.learning.attempts import (
    apply_assessment_decision,
    get_assessment_runtime_context,
    mark_attempt_question_presented,
    start_or_resume_attempt,
)
from app.modules.learning.execution import attempt_has_final_evidence, write_formal_assessment
from app.modules.learning.models import AssessmentActivity, AssessmentAttempt, LearningRecord
from app.modules.learning.recipes import (
    COMPLETION_DECLARATION,
    QUESTION_SCOPE_DECLARATION,
    SUPPORTED_RECIPE_ID,
)
from app.modules.learning.schemas import AssessmentRuntimeDecision
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    current_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.assessment_protocol import (
    ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL,
)
from app.modules.workspace.chat_team_provider import (
    TeamProviderDispatch,
)
from app.modules.workspace.chat_team_provider import (
    dispatch_team_model as real_dispatch_team_model,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationSharedSet,
    ConversationTurn,
    TeamProviderCall,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tests.conftest import post_message
from tests.test_mayaform_assessment_attempts import (
    _accepted_tool_identity,
    _begin_pending_executor_turn,
    _create_formal_conversation,
    _finish_executor_turn,
    _login,
)
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_team_provider_stage import _dispatch
from tests.test_wave4_provider_preflight import _digest, _policy


def test_active_assessment_never_persists_free_form_member_output(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    _app, _database, settings = app_bundle
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        _recipe_conversation_id, team_id, *_rest = _create_formal_conversation(
            db, visibility="private"
        )
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team_id})
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, settings, token)
        assert actor is not None
        attempt = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert attempt is not None and attempt.attempt.status == "in_progress"
        db.commit()
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        participants = runtime._targets(db, conversation, TeamRouting())[1]
        leader = next(participant for participant in participants if participant.is_leader)
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="Please explain the answer to this question.",
            routing=TeamRouting(mode="selected", participant_ids=[leader.id]),
            actor_context=actor,
        )
    result_ids = runtime.result_ids(database.session_factory, claim.turn_id)
    request = runtime._start_member(
        database.session_factory,
        claim.turn_id,
        claim.token,
        result_ids[0],
        settings=settings,
        actor_context=actor,
    )
    assert request is not None
    assert request.assessment_active is True
    assert request.assessment_purpose is None
    assert "<active_assessment_action_protocol>" in request.system_message
    assert "assessment_action" in request.system_message
    assert "assessment_active is a server ledger flag" in request.system_message
    assert "Internal answer" not in request.system_message
    assert request.knowledge_json == "{}"
    assert request.sources == ()
    for result_id in result_ids[1:]:
        runtime._start_member(
            database.session_factory,
            claim.turn_id,
            claim.token,
            result_id,
            settings=settings,
            actor_context=actor,
        )
    for result_id in result_ids:
        runtime.settle_member(
            database.session_factory,
            claim.turn_id,
            claim.token,
            result_id,
            reply=runtime.MemberReply("This free-form answer must never reach the student."),
            actor_context=actor,
        )
    with database.session() as db:
        results = db.scalars(
            select(TeamTurnResult).where(TeamTurnResult.turn_id == claim.turn_id)
        ).all()
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None and results
        assert all("free-form answer" not in (result.assistant_text or "") for result in results)
        assert all("已记录" not in (result.assistant_text or "") for result in results)
        assert results[0].state == "ready"
        assert (results[0].assistant_text or "").startswith("收到，第一题是")
        assert turn.state == "ready"


def test_real_sdk_dispatch_scopes_private_assessment_payload_to_assigned_executor(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    app, _database, settings = app_bundle
    _template_db, _template_repository, template_operation_id = _dispatch(client, app_bundle)
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        _recipe_conversation_id, team_id, *_rest = _create_formal_conversation(
            db, visibility="private"
        )
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team_id})
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, settings, token)
        assert actor is not None
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        context = started
        answer_number = 0
        while context.current_question is not None:
            question = context.current_question
            mark_attempt_question_presented(
                db,
                actor,
                conversation_id,
                question_version_id=question.question_version_id,
            )
            answer = f"saved answer {answer_number}"
            recorded = apply_assessment_decision(
                db,
                actor,
                conversation_id,
                user_message=answer,
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="answer_only",
                    answer_span=answer,
                    question_version_id=question.question_version_id,
                ),
            )
            assert recorded is not None
            context = recorded.context
            answer_number += 1
        assert answer_number >= 1
        activity = db.scalar(
            select(AssessmentActivity).where(AssessmentActivity.team_id == team_id)
        )
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
        template_stage = db.scalar(
            select(TeamProviderCall).where(TeamProviderCall.operation_id == template_operation_id)
        )
        assert template_stage is not None
        assessment_content = {
            "overall_feedback": "A private evaluation based on the saved responses.",
            "questions": [
                {
                    "question_ordinal": ordinal,
                    "feedback": "Evidence was recorded for this question.",
                    "points_awarded": 1,
                }
                for ordinal in range(answer_number)
            ],
            "strengths": ["Persistence"],
            "next_steps": ["Explain the evidence used."],
        }
        evaluator_execution = _begin_pending_executor_turn(
            db,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
        )
        evaluator_identity = _accepted_tool_identity(
            db,
            template_stage_id=template_stage.id,
            conversation_id=conversation_id,
            participant_id=evaluator.id,
            position=0,
            tool_name="edit_assessment",
            execution=evaluator_execution,
            tool_arguments={"content": assessment_content},
        )
        assert write_formal_assessment(db, actor, evaluator_identity, assessment_content) == {
            "saved": True
        }
        _finish_executor_turn(db, evaluator_execution)
        db.commit()

    app_settings = app.state.settings.model_copy(update={"llm_provider": "dashscope"})
    app.state.settings = app_settings
    calls: list[tuple[str, list[Any], list[dict[str, Any]] | None]] = []
    requests: list[runtime.MemberRequest] = []
    choices: list[Any] = []

    def dispatch_provider(
        _db: Any,
        _settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        tool_choice: Any,
        **_kwargs: Any,
    ) -> TeamProviderDispatch:
        requests.append(request)
        calls.append((request.participant_id, messages, tools))
        choices.append(tool_choice)
        return TeamProviderDispatch(
            response=ModelResponse(role="assistant", content="synthetic internal output"),
            call_id=f"synthetic-{request.participant_id}",
        )

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", dispatch_provider
    )

    for participant, expected_purpose in (
        (evaluator, "assessment_evaluate"),
        (boundary_writer, "boundary_summarize"),
    ):
        with database.session() as db:
            row = db.get(Conversation, conversation_id)
            assert row is not None
            claim = runtime.claim_assessment_executor_turn(
                db,
                app_settings,
                conversation_id=conversation_id,
                participant_id=participant.id,
                actor_context=actor,
            )
            assert claim is not None
        result_id = runtime.result_ids(database.session_factory, claim.turn_id)[0]
        runtime.execute_real_member(database.session_factory, claim, result_id)
        assert requests[-1].knowledge_json == "{}"
        assert requests[-1].sources == ()
        participant_id, messages, tools = calls[-1]
        assert participant_id == participant.id
        # Without its action the turn is rejected, so the model is not left
        # free to answer in prose.
        assert choices[-1] == {
            "type": "function",
            "function": {
                "name": "edit_assessment"
                if expected_purpose == "assessment_evaluate"
                else "update_learning_boundary"
            },
        }
        assert messages and messages[0].role == "system"
        system = messages[0].content
        assert isinstance(system, str)
        tool_names = {
            function.get("name")
            for tool in (tools or [])
            if isinstance(tool, dict) and isinstance((function := tool.get("function")), dict)
        }
        if expected_purpose == "assessment_evaluate":
            assert 'purpose="assessment_evaluate"' in system
            assert "<assessment_executor_private_context>" in system
            payload = system.split("<assessment_executor_private_context>\n", 1)[1].split(
                "\n</assessment_executor_private_context>", 1
            )[0]
            task = json.loads(payload)
            assert task["questions"]
            assert all("rubric" in question for question in task["questions"])
            assert all(question["answer_text"] for question in task["questions"])
            assert "edit_assessment" in tool_names
            assert "assessment_action" not in tool_names
            assert "Internal answer" in system
        else:
            assert 'purpose="boundary_summarize"' in system
            assert "<assessment_executor_private_context>" in system
            payload = system.split("<assessment_executor_private_context>\n", 1)[1].split(
                "\n</assessment_executor_private_context>", 1
            )[0]
            task = json.loads(payload)
            assert task["responses"]
            assert task["assessment"]["overall_feedback"] == assessment_content["overall_feedback"]
            assert all("rubric" not in response for response in task["responses"])
            assert "update_learning_boundary" in tool_names
            assert "edit_assessment" not in tool_names
            assert "assessment_action" not in tool_names
            assert "Internal answer" not in system


# Bug (2026-10-13): with a follow-up for a wrong answer, the scorer's closing
# model call rechecked the test after the follow-up was added, found it
# unanswered and failed as "This Team member could not reply".
#
# Prod (2026-10-18): the Scorer's assessment_action failed with
# assessment_action_required when it carried an argument the Tool does not
# take (reply_language='zh') or arrived as truncated JSON ("'{' was never
# closed"). An unknown argument is now ignored and logged; truncated JSON gets
# one forced retry through admission; a second failure asks for the answer again.
@pytest.mark.parametrize(
    ("follow_up", "scorer_wire"),
    [
        (False, "clean"),
        (True, "clean"),
        (False, "unknown_argument"),
        (False, "argument_beside"),
        (False, "truncated_once"),
        (False, "truncated_twice"),
    ],
)
def test_open_test_runs_the_leader_alone_and_the_server_scores_without_leaks(
    client: TestClient,
    database: Any,
    app_bundle: Any,
    monkeypatch: Any,
    follow_up: bool,
    scorer_wire: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app, _database, base_settings = app_bundle
    teacher_token, teacher_csrf = _login(client, "maya")
    del teacher_token

    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
        (
            _source_conversation_id,
            _source_team_id,
            _source_version_id,
            _publication_id,
            set_id,
            _questions,
        ) = _create_formal_conversation(
            db,
            visibility="private",
            prompts=("Question one", "Question two", "Why question one?")
            if follow_up
            else ("Question one", "Question two"),
            labels={"Why question one?": "Follow-up for Question 1; at most 1"},
        )

    from app.modules.workspace.formal_assessment import formal_ruleset_markdown

    names = ("Bowen", "Jade", "Kaikai", "Maya")
    version_ids: list[str] = []
    for name in names:
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="public"
        )
        version_ids.append(version_id)
        instructions = [f"# {name}"]
        if name == "Bowen":
            instructions.extend(
                (
                    f"MAYA-ASSESSMENT-RECIPE: {SUPPORTED_RECIPE_ID}",
                    QUESTION_SCOPE_DECLARATION,
                    COMPLETION_DECLARATION,
                    "",
                    formal_ruleset_markdown(
                        answer_recorder="Jade",
                        question_guide="Bowen",
                        scorer="Jade",
                        summarizer="Kaikai",
                        student_round_order=("Jade", "Bowen"),
                    ),
                )
            )
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            assert version is not None
            version.agent_md = "\n".join(instructions)
            version.avatar_config_json = json.dumps(
                {
                    "template_id": "synthetic",
                    "material_theme": "default",
                    "default_expression": "neutral",
                    "expression_strength": "low",
                    "motion_style": "calm",
                }
            )

    team_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"assessment-coordinate-{uuid4()}"),
        json={
            "display_name": "Synthetic assessment coordination",
            "visibility": "public",
            "members": [
                {"agent_version_id": version_id, "is_leader": index == 0, "position": index}
                for index, version_id in enumerate(version_ids)
            ],
            "shared_knowledge_set_ids": [set_id],
        },
    )
    assert team_response.status_code == 201, team_response.text
    student_token, student_csrf = _login(client, "bowen")
    session = _create(
        client,
        student_csrf,
        {"kind": "maya_team", "team_id": team_response.json()["id"]},
    )
    conversation_id = session["id"]

    with database.session() as db:
        actor = get_auth_context(db, base_settings, student_token)
        assert actor is not None
        context = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert context is not None
        while context.progress.resolved_count < context.progress.question_count - 1:
            question = context.current_question
            assert question is not None
            mark_attempt_question_presented(
                db,
                actor,
                conversation_id,
                question_version_id=question.question_version_id,
            )
            answer = f"Earlier saved answer {context.progress.resolved_count}"
            recorded = apply_assessment_decision(
                db,
                actor,
                conversation_id,
                user_message=answer,
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="answer_only",
                    answer_span=answer,
                    question_version_id=question.question_version_id,
                ),
            )
            assert recorded is not None
            context = recorded.context
        final_question = context.current_question
        assert final_question is not None
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=final_question.question_version_id,
        )
        db.commit()

    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="assessment-coordinate-synthetic",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("assessment-coordinate-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)

    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.team_version_id is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=conversation.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        participants = list(
            db.scalars(
                select(ConversationParticipant)
                .where(ConversationParticipant.conversation_id == conversation_id)
                .order_by(ConversationParticipant.position)
            )
        )
        by_name = {participant.display_name: participant for participant in participants}
        leader, evaluator, boundary = by_name["Bowen"], by_name["Jade"], by_name["Kaikai"]
        assert leader.is_leader and not evaluator.is_leader and not boundary.is_leader
        from app.modules.workspace.team_conversation import frozen_team_selection

        frozen = frozen_team_selection(db, conversation)
        assert (
            current_standing_grant(
                db,
                actor.user.id,
                frozen,
                {participant.team_member_id for participant in participants},
                policy.policy_hash,
                "llm_agent_chat",
            )
            is not None
        )
        question_count = context.progress.question_count
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="My final answer is FINAL_ANSWER_CANARY.",
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )
    assessment_content = {
        "overall_feedback": "Saved evaluation of the submitted responses.",
        "questions": [
            {
                "question_ordinal": ordinal,
                "feedback": "Evidence was recorded for this response.",
                "points_awarded": 1,
            }
            for ordinal in range(question_count)
        ],
        "strengths": ["Persistence"],
        "next_steps": ["Explain the evidence used."],
    }

    def tool_body(call_id: str, name: str, arguments: dict[str, Any]) -> bytes:
        wire_arguments = (
            arguments if name == "delegate_task_to_member" else {"arguments": arguments}
        )
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(wire_arguments),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ).encode()

    def raw_tool_body(call_id: str, name: str, raw_arguments: str) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": name, "arguments": raw_arguments},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ).encode()

    def text_body(content: str) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()

    class SyntheticResponse:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class SyntheticTransport:
        def __init__(self, response: bytes) -> None:
            self.response = response
            self.wires: list[bytes] = []

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            self.wires.append(content)
            return SyntheticResponse(self.response)

    wires: dict[str, list[bytes]] = defaultdict(list)
    call_counts: dict[str, int] = defaultdict(int)
    from app.modules.runtime_tools import sdk as runtime_sdk

    tool_results: list[tuple[str, dict[str, Any]]] = []
    actual_execute_tool = runtime_sdk.execute_tool
    actual_bind_one = runtime_sdk._bind_one
    function_flags: dict[str, list[tuple[str, bool]]] = defaultdict(list)

    def record_bound_function(*args: Any, **kwargs: Any) -> Any:
        function = actual_bind_one(*args, **kwargs)
        function_flags[args[3]].append((function.name, function.stop_after_tool_call))
        return function

    def record_tool_result(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = actual_execute_tool(*args, **kwargs)
        tool_results.append((args[3], result))
        return result

    monkeypatch.setattr(runtime_sdk, "execute_tool", record_tool_result)
    monkeypatch.setattr(runtime_sdk, "_bind_one", record_bound_function)

    def response_for(request: runtime.MemberRequest, ordinal: int) -> bytes:
        # The student turn dispatches only the scorer. Executor turns keep
        # their purpose and are not chosen by MAYA-ASSESSMENT-ROLE.
        if request.assessment_purpose == "assessment_evaluate":
            if ordinal == 0:
                return tool_body(
                    f"edit-assessment-{request.turn_id}",
                    "edit_assessment",
                    {"content": assessment_content},
                )
            return text_body("EVALUATOR_RAW_CANARY includes private rubric and internal task JSON.")
        if request.assessment_purpose == "boundary_summarize":
            if ordinal == 0:
                return tool_body(
                    f"edit-boundary-{request.turn_id}",
                    "update_learning_boundary",
                    {
                        "content": {
                            "summary": "The saved responses show a need for clearer evidence.",
                            "strengths": ["Persistence"],
                            "areas_to_explore": ["Evidence"],
                            "next_step": "Explain one example.",
                        }
                    },
                )
            return text_body("BOUNDARY_RAW_CANARY includes private assessment task JSON.")
        if request.participant_id == evaluator.id and request.message.startswith("My final answer"):
            answer = {
                "classification": "answer_only",
                "relevant": True,
                "answer_span": "FINAL_ANSWER_CANARY",
            }
            truncated = '{"arguments": {"classification": "answer_only", "relevant": true'
            if scorer_wire == "truncated_once" and ordinal == 0:
                return raw_tool_body(f"broken-{request.turn_id}", "assessment_action", truncated)
            if scorer_wire == "truncated_twice" and ordinal <= 1:
                return raw_tool_body(
                    f"broken-{request.turn_id}-{ordinal}", "assessment_action", truncated
                )
            retried = scorer_wire == "truncated_once" and ordinal == 1
            if ordinal == 0 or retried:
                call_id = f"answer-{request.turn_id}"
                if scorer_wire == "unknown_argument":
                    return tool_body(call_id, "assessment_action", {**answer, "mood": "calm"})
                if scorer_wire == "argument_beside":
                    return raw_tool_body(
                        call_id,
                        "assessment_action",
                        json.dumps({"arguments": answer, "reply_language": "en"}),
                    )
                return tool_body(call_id, "assessment_action", answer)
            return text_body("Untrusted coordinator prose after formal work.")
        raise AssertionError(
            f"Unexpected dispatch participant={request.participant_id} "
            f"purpose={request.assessment_purpose}"
        )

    def synthetic_dispatch(
        db: Any,
        _call_settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        choice: Any,
        **kwargs: Any,
    ) -> TeamProviderDispatch:
        ordinal = call_counts[request.result_id]
        call_counts[request.result_id] += 1
        transport = SyntheticTransport(response_for(request, ordinal))
        dispatch = real_dispatch_team_model(
            db,
            settings,
            request,
            messages,
            tools,
            choice,
            transport=transport,
            **kwargs,
        )
        assert len(transport.wires) == 1
        wires[request.participant_id].append(transport.wires[0])
        return dispatch

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    from app.modules.workspace import chat_team_provider

    admitted: list[str] = []
    real_slot = chat_team_provider.llm_admission_slot

    def counted_slot(*args: Any, **kwargs: Any) -> Any:
        admitted.append("llm")
        return real_slot(*args, **kwargs)

    monkeypatch.setattr(chat_team_provider, "llm_admission_slot", counted_slot)
    write_commits: list[int] = []
    wrote: set[int] = set()
    selects: list[int] = []

    def note_write(conn, _cursor, statement, *_args):  # type: ignore[no-untyped-def]
        if not statement.lstrip()[:6].upper().startswith("SELECT"):
            wrote.add(id(conn))
        else:
            selects.append(1)

    def note_commit(conn):  # type: ignore[no-untyped-def]
        if id(conn) in wrote:
            wrote.discard(id(conn))
            write_commits.append(1)

    event.listen(database.engine, "after_cursor_execute", note_write)
    event.listen(database.engine, "commit", note_commit)
    try:
        runtime.execute_team_turn(database.session_factory, claim)
    finally:
        event.remove(database.engine, "after_cursor_execute", note_write)
        event.remove(database.engine, "commit", note_commit)
    scorer_wires = [json.loads(wire) for wire in wires[evaluator.id]]
    forced = {"type": "function", "function": {"name": "assessment_action"}}
    if scorer_wire.startswith("truncated"):
        # One retry, sent through the same dispatch (and admission) as the
        # first call, with the Tool still required; never a third call.
        assert len(scorer_wires) == 2
        assert [wire.get("tool_choice") for wire in scorer_wires] == [forced, forced]
        # Every model call on this turn (the retry included) took an LLM slot.
        assert len(admitted) == len(scorer_wires)
    if scorer_wire == "unknown_argument":
        assert "ignored unknown arguments tool=assessment_action arguments=mood" in caplog.text
    if scorer_wire == "truncated_twice":
        from app.modules.workspace.formal_assessment import (
            SILENT_MEMBER_LINE,
            UNSAVED_RETRY_LINE,
        )

        with database.session() as db:
            turn = db.get(ConversationTurn, claim.turn_id)
            assert turn is not None and turn.state == "ready"
            results = {
                row.participant_id: row
                for row in db.scalars(
                    select(TeamTurnResult).where(TeamTurnResult.turn_id == claim.turn_id)
                )
            }
            # The Scorer asks for the answer again; the Guide adds nothing.
            assert results[evaluator.id].state == "ready"
            assert results[evaluator.id].assistant_text == UNSAVED_RETRY_LINE["en"]
            assert results[leader.id].state == "ready"
            assert results[leader.id].assistant_text == SILENT_MEMBER_LINE
            assert all(row.safe_error_code is None for row in results.values())
            # Answers saved earlier stay; the broken one is not invented.
            waiting = get_assessment_runtime_context(db, actor, conversation_id)
            assert waiting is not None and waiting.current_question is not None
            assert waiting.progress.resolved_count == question_count - 1
            saved = db.scalars(
                select(LearningRecord.payload_json).where(
                    LearningRecord.conversation_id == conversation_id
                )
            ).all()
            assert sum("Earlier saved answer" in text for text in saved) == question_count - 1
            assert not any("FINAL_ANSWER_CANARY" in text for text in saved)
        return
    # 2026-10-18: one answer turn with one model call committed 14 write
    # transactions; the ledger steps between network points now share one (10).
    # The retried model call adds its own five provider ledger steps.
    assert len(write_commits) <= (15 if scorer_wire == "truncated_once" else 10), len(write_commits)
    # 2026-10-18: the same turn ran 812 SELECTs (112 distinct); the assessment
    # context and Team member checks now run once per request phase (448).
    # A retried Scorer call is one more model-call phase of checks (593).
    select_cap = 650 if scorer_wire.startswith("truncated") else 500
    assert len(selects) <= select_cap, len(selects)
    # The student turn dispatches the scorer. The Guide and Summarizer are
    # server text, so they have no model wire on this turn.
    assert wires[leader.id] == [] and wires[boundary.id] == []
    assert len(wires[evaluator.id]) >= 1
    with database.session() as db:
        from app.modules.workspace.formal_assessment import ALL_DONE_GUIDE, SUMMARIZER_LINE
        from app.modules.workspace.team_conversation import _assessment_stage

        shown_now = db.scalars(
            select(TeamTurnResult.assistant_text).where(TeamTurnResult.turn_id == claim.turn_id)
        ).all()
        stage = _assessment_stage(db, db.get(Conversation, conversation_id))
    # Follow-ups come before the test is scored, so that wait is not the
    # completion line and shows no bar.
    if follow_up:
        assert any(text == "请稍候。" for text in shown_now)
        assert ALL_DONE_GUIDE not in shown_now
        assert SUMMARIZER_LINE not in shown_now
        assert stage == "preparing"
    else:
        assert ALL_DONE_GUIDE in shown_now
        assert SUMMARIZER_LINE in shown_now
        assert stage == "scoring"
    from app.modules.learning import finalizer

    finalizer.drive_assessment(database.session_factory, settings, conversation_id)

    assert wires[leader.id] == []
    assert len(wires[evaluator.id]) >= 1
    if follow_up:
        with database.session() as db:
            assert all(
                result.state == "ready"
                for result in db.scalars(
                    select(TeamTurnResult).where(TeamTurnResult.conversation_id == conversation_id)
                )
            )
            shown = db.scalars(
                select(TeamTurnResult.assistant_text).where(
                    TeamTurnResult.conversation_id == conversation_id
                )
            ).all()
            assert any(
                "Next, a follow-up question." in (text or "")
                and "Why question one?" in (text or "")
                for text in shown
            )
            waiting = get_assessment_runtime_context(db, actor, conversation_id)
            assert waiting is not None and waiting.current_question is not None
            assert waiting.current_question.prompt == "Why question one?"
        assert wires[boundary.id] == []
        return
    assert len(wires[boundary.id]) == 1
    assert (
        "edit_assessment",
        {"ok": True, "result": {"saved": True}},
    ) in tool_results
    assert (
        "update_learning_boundary",
        {"ok": True, "result": {"saved": True}},
    ) in tool_results
    assert any(b"Internal only" in wire for wire in wires[evaluator.id])
    assert all(
        b"EVALUATOR_RAW_CANARY" not in wire
        and b"BOUNDARY_RAW_CANARY" not in wire
        and b"Internal only" not in wire
        for wire in wires[leader.id]
    )
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None and turn.state == "ready"
        shown = db.scalars(
            select(TeamTurnResult.assistant_text).where(
                TeamTurnResult.conversation_id == conversation_id
            )
        ).all()
        assert all(
            "EVALUATOR_RAW_CANARY" not in (text or "") and "BOUNDARY_RAW_CANARY" not in (text or "")
            for text in shown
        )
        # Every server turn settles cleanly; a failed one showed as "could not reply".
        assert all(
            result.state == "ready"
            for result in db.scalars(
                select(TeamTurnResult).where(TeamTurnResult.conversation_id == conversation_id)
            )
        )
        assert any("This round's answers have been reviewed." in (text or "") for text in shown)
        assert any("Congratulations" in (text or "") for text in shown)
        from app.modules.workspace.formal_assessment import SUMMARIZER_LINE
        from app.modules.workspace.team_conversation import team_session_view

        session = team_session_view(
            db, db.get(Conversation, conversation_id), actor, [], runtime_available=True
        )
        visible = [
            result.assistant_text or "" for turn in session.turns for result in turn.member_results
        ]
        assert visible[-1].strip() == SUMMARIZER_LINE
        assert all("This round's answers have been reviewed." not in text for text in visible)
        assert all("本轮回答已评估" not in text for text in visible)
        assert all(turn.state != "partial" for turn in session.turns)
        assert all(
            result.safe_error_code != "assessment_executor_write_required"
            for turn in session.turns
            for result in turn.member_results
        )
        assert get_assessment_runtime_context(db, actor, conversation_id) is None
        attempt = db.get(AssessmentAttempt, str(context.attempt.id))
        assert attempt is not None and attempt.status == "completed"
        assert attempt_has_final_evidence(db, attempt)
        # The student sent one message; the server's own turns carry no text.
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(
                    ConversationTurn.conversation_id == conversation_id,
                    ConversationTurn.user_text != "",
                )
            )
            == 1
        )


def test_real_sdk_paused_queries_do_not_resume_but_natural_resume_replays_same_attempt(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    app, _database, base_settings = app_bundle
    teacher_token, teacher_csrf = _login(client, "maya")
    del teacher_token
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
        _source_conversation_id, team_id, *_rest = _create_formal_conversation(
            db, visibility="private"
        )

    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="assessment-paused-natural-language",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("assessment-paused-natural-language-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)

    student_token, student_csrf = _login(client, "bowen")
    session = _create(
        client,
        student_csrf,
        {"kind": "maya_team", "team_id": team_id},
    )
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, settings, student_token)
        assert actor is not None
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        first_attempt_id = str(started.attempt.id)
        row = db.get(Conversation, conversation_id)
        assert row is not None and row.team_version_id is not None
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        assert leader is not None
        routing = TeamRouting(mode="selected", participant_ids=[UUID(leader.id)])
        from app.modules.workspace.team_conversation import frozen_team_selection

        frozen = frozen_team_selection(db, row)
        assert (
            current_standing_grant(
                db,
                actor.user.id,
                frozen,
                {leader.team_member_id},
                policy.policy_hash,
                "llm_agent_chat",
            )
            is not None
        )
        old_query_id = str(uuid4())
        old_query = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=old_query_id,
            expected_revision=row.revision,
            message="Original paused progress request.",
            routing=routing,
            actor_context=actor,
        )
        runtime.pause_team_turn(
            db,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            turn_id=old_query.turn_id,
            actor_context=actor,
        )

    responses_by_message = {
        "Please show my progress and submitted answers.": "progress_request",
        "Please abandon this assessment.": "abandon_request",
        "Original paused progress request.": "progress_request",
        "Continue the same assessment.": "resume_request",
    }

    def tool_body(call_id: str, classification: str) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": "assessment_action",
                                        "arguments": json.dumps(
                                            {"arguments": {"classification": classification}}
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ).encode()

    def text_body() -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Untrusted prose."},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()

    class SyntheticResponse:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class SyntheticTransport:
        def __init__(self, response: bytes) -> None:
            self.response = response
            self.wires: list[bytes] = []

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            self.wires.append(content)
            return SyntheticResponse(self.response)

    calls_by_turn: dict[str, int] = defaultdict(int)
    wires_by_turn: dict[str, list[bytes]] = defaultdict(list)

    def synthetic_dispatch(
        db: Any,
        _call_settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        choice: Any,
        **kwargs: Any,
    ) -> TeamProviderDispatch:
        live_row = db.get(Conversation, request.conversation_id)
        assert live_row is not None
        live_selection = frozen_team_selection(db, live_row)
        assert (
            current_standing_grant(
                db,
                request.actor_id,
                live_selection,
                kwargs["selected_binding_ids"],
                policy.policy_hash,
                "llm_agent_chat",
            )
            is not None
        )
        ordinal = calls_by_turn[request.turn_id]
        calls_by_turn[request.turn_id] += 1
        response = (
            tool_body(
                f"assessment-action-{request.turn_id}",
                responses_by_message[request.message],
            )
            if ordinal == 0
            else text_body()
        )
        transport = SyntheticTransport(response)
        result = real_dispatch_team_model(
            db,
            settings,
            request,
            messages,
            tools,
            choice,
            transport=transport,
            **kwargs,
        )
        assert len(transport.wires) == 1
        wires_by_turn[request.turn_id].append(transport.wires[0])
        return result

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )

    def send(message: str, request_id: str) -> dict[str, Any]:
        current = client.get(f"/api/v1/conversations/{conversation_id}").json()
        response = post_message(
            client,
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=_headers(student_csrf),
            json={
                "request_id": request_id,
                "expected_revision": current["revision"],
                "message": message,
                "routing": routing.model_dump(mode="json"),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    progress_id = str(uuid4())
    progress_session = send("Please show my progress and submitted answers.", progress_id)
    with database.session() as db:
        progress_turn = db.get(ConversationTurn, progress_id)
        old_turn = db.get(ConversationTurn, old_query_id)
        attempt = db.get(AssessmentAttempt, first_attempt_id)
        assert progress_turn is not None and old_turn is not None and attempt is not None
        assert progress_turn.state == "ready"
        assert old_turn.state == "paused"
        assert attempt.status == "paused"
        progress_result = db.scalar(
            select(TeamTurnResult).where(TeamTurnResult.turn_id == progress_id)
        )
        assert progress_result is not None and progress_result.assistant_text is not None
        assert "Progress:" in progress_result.assistant_text
        assert progress_result.assistant_text.endswith("Question 1: Question one")
        assert "Rubric" not in progress_result.assistant_text
        assert progress_session["turns"][-1]["id"] == progress_id

    abandon_id = str(uuid4())
    send("Please abandon this assessment.", abandon_id)
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, first_attempt_id)
        old_turn = db.get(ConversationTurn, old_query_id)
        assert attempt is not None and attempt.status == "abandoned"
        assert old_turn is not None and old_turn.state == "paused"

        actor = get_auth_context(db, settings, student_token)
        assert actor is not None
        replacement = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert replacement is not None and replacement.attempt.id != first_attempt_id
        replacement_attempt_id = str(replacement.attempt.id)
        row = db.get(Conversation, conversation_id)
        assert row is not None
        resumed_source_id = str(uuid4())
        source_claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=resumed_source_id,
            expected_revision=row.revision,
            message="Original paused progress request.",
            routing=routing,
            actor_context=actor,
        )
        runtime.pause_team_turn(
            db,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            turn_id=source_claim.turn_id,
            actor_context=actor,
        )

    resume_id = str(uuid4())
    real_resume_wrapper = runtime.execute_team_turn_with_natural_assessment_resume
    monkeypatch.setattr(
        runtime,
        "execute_team_turn_with_natural_assessment_resume",
        runtime.execute_team_turn,
    )
    resumed_session = send("Continue the same assessment.", resume_id)
    monkeypatch.setattr(
        runtime,
        "execute_team_turn_with_natural_assessment_resume",
        real_resume_wrapper,
    )
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, replacement_attempt_id)
        old_turn = db.get(ConversationTurn, resumed_source_id)
        abandoned_turn = db.get(ConversationTurn, old_query_id)
        assert attempt is not None and attempt.status == "in_progress"
        assert old_turn is not None and old_turn.state == "paused"
        assert abandoned_turn is not None and abandoned_turn.state == "paused"
        assert resumed_session["turns"][-1]["id"] == resume_id
        assert calls_by_turn[resume_id] == 1  # one model call per answer turn (2026-10-13)
        assert calls_by_turn[resumed_source_id] == 0
        assert calls_by_turn[old_query_id] == 0

    # The durable resume receipt remains actionable if the process dies after
    # the user command commits but before the old turn is claimed.
    original_execute_team_turn = runtime.execute_team_turn

    def crash_after_resume_claim(
        factory: Any, claim: runtime.TeamClaim, write_slot: Any = None
    ) -> None:
        if claim.turn_id != resumed_source_id:
            original_execute_team_turn(factory, claim, write_slot)

    monkeypatch.setattr(runtime, "execute_team_turn", crash_after_resume_claim)
    send("Continue the same assessment.", resume_id)
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        old_turn = db.get(ConversationTurn, resumed_source_id)
        assert row is not None and old_turn is not None
        assert row.active_request_id == resumed_source_id
        assert old_turn.state == "pending"

    # Restart recovery invalidates that claim, leaves accepted stages intact,
    # and permits the same persisted resume receipt to claim the exact old turn.
    with database.session() as db:
        assert runtime.recover_team_runs(db) == 1
        db.commit()
        row = db.get(Conversation, conversation_id)
        old_turn = db.get(ConversationTurn, resumed_source_id)
        assert row is not None and old_turn is not None
        assert row.active_request_id is None
        assert old_turn.state == "paused"
        assert old_turn.safe_error_code == "chat_interrupted"
    monkeypatch.setattr(runtime, "execute_team_turn", original_execute_team_turn)
    recovered_session = send("Continue the same assessment.", resume_id)
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, replacement_attempt_id)
        old_turn = db.get(ConversationTurn, resumed_source_id)
        assert attempt is not None and attempt.status == "in_progress"
        assert old_turn is not None and old_turn.state == "ready"
        assert recovered_session["turns"][-1]["id"] == resume_id
        assert calls_by_turn[resume_id] == 1
        # The paused source was claimed before any question was presented, so
        # it is the Guide's server opening and does not call the model.
        assert calls_by_turn[resumed_source_id] == 0
        assert calls_by_turn[old_query_id] == 0
        assert all(
            b"Internal only" not in wire and b"Internal answer" not in wire
            for turn_wires in wires_by_turn.values()
            for wire in turn_wires
        )


def test_revoked_question_source_allows_natural_chat_abandon_without_disclosing_material(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    app, _database, base_settings = app_bundle
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="assessment-source-revoked-abandon",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("assessment-source-revoked-abandon-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)
    token, csrf = _login(client, "bowen")

    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            source_set_id,
            _questions,
        ) = _create_formal_conversation(db, visibility="private")
        shared_binding = db.get(ConversationSharedSet, (conversation_id, source_set_id))
        assert shared_binding is not None and shared_binding.position == 0
        actor = get_auth_context(db, settings, token)
        assert actor is not None and actor.csrf_token == csrf
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt_id = str(started.attempt.id)
        question = started.current_question
        assert question is not None
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=question.question_version_id,
        )
        saved_answer = "VISIBLE_OWNER_ANSWER_CANARY"
        recorded = apply_assessment_decision(
            db,
            actor,
            conversation_id,
            user_message=f"My answer is {saved_answer}.",
            decision=AssessmentRuntimeDecision(
                client_event_id=uuid4(),
                classification="answer_only",
                answer_span=saved_answer,
                question_version_id=question.question_version_id,
            ),
        )
        assert recorded is not None
        row = db.get(Conversation, conversation_id)
        assert row is not None and row.team_version_id is not None
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        assert leader is not None
        routing = TeamRouting(mode="selected", participant_ids=[UUID(leader.id)])
        plan = prepare_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
        )
        confirm_team_standing_grant(
            db,
            MAYA_ID,
            team_version_id=row.team_version_id,
            policy_hash=policy.policy_hash,
            provider_operation="llm_agent_chat",
            expected_resource_hash=plan.resource_hash,
            expected_team_epoch=plan.team_epoch,
            expected_publication_epoch=plan.publication_epoch,
        )
        db.commit()
        old_claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=row.revision,
            message="A pending turn that can be safely paused.",
            routing=routing,
            actor_context=actor,
        )
        source = db.get(KnowledgeSet, source_set_id)
        assert source is not None
        source.deleted_at = datetime.now(UTC)
        db.commit()

    assert client.cookies.get("maya_session") == token
    pause_headers = _headers(csrf)
    pause_headers["Origin"] = settings.classroom_public_base_url or "http://testserver"
    pause = client.post(
        f"/api/v1/conversations/{conversation_id}/turns/{old_claim.turn_id}:pause",
        headers=pause_headers,
    )
    assert pause.status_code == 200, pause.text
    paused_turn = next(item for item in pause.json()["turns"] if item["id"] == old_claim.turn_id)
    assert paused_turn["state"] == "paused"

    from app.modules.workspace.team_conversation import frozen_team_selection

    calls = 0
    wires: list[bytes] = []

    def tool_body(classification: str, call_id: str) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": "assessment_action",
                                        "arguments": json.dumps(
                                            {"arguments": {"classification": classification}}
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ).encode()

    def text_body() -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Untrusted prose."},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode()

    class SyntheticResponse:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class SyntheticTransport:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            wires.append(content)
            return SyntheticResponse(self.content)

    def synthetic_dispatch(
        db: Any,
        _call_settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        choice: Any,
        **kwargs: Any,
    ) -> TeamProviderDispatch:
        nonlocal calls
        assert request.assessment_active is True
        assert request.assessment_source_revoked is True
        assert request.assessment_purpose is None
        assert request.system_message == ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL
        live_row = db.get(Conversation, request.conversation_id)
        assert live_row is not None
        frozen = frozen_team_selection(db, live_row)
        assert frozen.team_version_id == live_row.team_version_id
        classification = {
            "Please show my submitted answers and progress.": "answers_request",
            "Please abandon this assessment.": "abandon_request",
        }.get(request.message)
        response = (
            tool_body(classification, f"source-revoked-action-{calls}")
            if classification is not None
            else text_body()
        )
        calls += 1
        transport = SyntheticTransport(response)
        dispatch = real_dispatch_team_model(
            db,
            settings,
            request,
            messages,
            tools,
            choice,
            transport=transport,
            **kwargs,
        )
        return dispatch

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    current = client.get(f"/api/v1/conversations/{conversation_id}")
    assert current.status_code == 200, current.text
    assert current.json()["can_send"] is True
    assert all(
        participant["available"] is (participant["id"] == str(leader.id))
        for participant in current.json()["team"]["members"]
    )
    answers_request_id = str(uuid4())
    answers_response = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=pause_headers,
        json={
            "request_id": answers_request_id,
            "expected_revision": current.json()["revision"],
            "message": "Please show my submitted answers and progress.",
            "routing": routing.model_dump(mode="json"),
        },
    )
    assert answers_response.status_code == 200, answers_response.text
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        answer_turn = db.get(ConversationTurn, answers_request_id)
        assert attempt is not None and attempt.status == "paused"
        assert answer_turn is not None and answer_turn.state == "ready"
        answer_result = db.scalar(
            select(TeamTurnResult).where(TeamTurnResult.turn_id == answers_request_id)
        )
        assert answer_result is not None
        assert saved_answer in (answer_result.assistant_text or "")
        assert "Resolved 1/2" in (answer_result.assistant_text or "")
        assert "Question one" not in (answer_result.assistant_text or "")
        answer_receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == answers_request_id,
                RuntimeToolReceipt.tool_name == "assessment_action",
            )
        )
        assert answer_receipt is not None
        answer_result_json = json.loads(answer_receipt.result_json)["result"]
        assert answer_result_json["response_key"] == "assessment.answers"
        assert answer_result_json["answers"] == [
            {
                "answer_text": saved_answer,
                "created_at": answer_result_json["answers"][0]["created_at"],
            }
        ]
        assert "question_ordinal" not in answer_result_json["answers"][0]
        assert "question_version_id" not in answer_result_json["answers"][0]

    current = client.get(f"/api/v1/conversations/{conversation_id}")
    continue_request_id = str(uuid4())
    continue_response = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=pause_headers,
        json={
            "request_id": continue_request_id,
            "expected_revision": current.json()["revision"],
            "message": "Please continue this assessment.",
            "routing": routing.model_dump(mode="json"),
        },
    )
    assert continue_response.status_code == 200, continue_response.text
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        old_turn = db.get(ConversationTurn, old_claim.turn_id)
        continue_turn = db.get(ConversationTurn, continue_request_id)
        answer_rows = db.scalars(
            select(LearningRecord).where(
                LearningRecord.attempt_id == attempt_id,
                LearningRecord.record_kind == "answer",
            )
        ).all()
        assert attempt is not None and attempt.status == "paused"
        assert old_turn is not None and old_turn.state == "paused"
        assert continue_turn is not None and continue_turn.state == "failed"
        assert len(answer_rows) == 1

    current = client.get(f"/api/v1/conversations/{conversation_id}")
    request_id = str(uuid4())
    response = post_message(
        client,
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=pause_headers,
        json={
            "request_id": request_id,
            "expected_revision": current.json()["revision"],
            "message": "Please abandon this assessment.",
            "routing": routing.model_dump(mode="json"),
        },
    )
    assert response.status_code == 200, response.text
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        old_turn = db.get(ConversationTurn, old_claim.turn_id)
        action_turn = db.get(ConversationTurn, request_id)
        assert attempt is not None and attempt.status == "abandoned"
        assert old_turn is not None and old_turn.state == "paused"
        assert action_turn is not None and action_turn.state == "ready"
        result = db.scalar(select(TeamTurnResult).where(TeamTurnResult.turn_id == request_id))
        assert (
            result is not None
            and result.assistant_text == "Test abandoned. Its answers were not kept."
        )
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == request_id,
                RuntimeToolReceipt.tool_name == "assessment_action",
            )
        )
        assert receipt is not None
    assert calls == 3
    assert len(wires) == 3
    from app.modules.provider_disclosure.team_standing import (
        REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION,
        REVOKED_ASSESSMENT_ACTIONS,
    )

    for wire, user_message in zip(
        wires,
        (
            "Please show my submitted answers and progress.",
            "Please continue this assessment.",
            "Please abandon this assessment.",
        ),
        strict=True,
    ):
        provider_wire = json.loads(wire)
        # max_tokens (2026-10-13): every Team call states its output cap.
        base_keys = {"model", "messages", "stream", "enable_thinking", "tools", "max_tokens"}
        assert set(provider_wire) in {frozenset(base_keys), frozenset(base_keys | {"tool_choice"})}
        assert provider_wire.get("tool_choice", "auto") == "auto"
        assert provider_wire["messages"] == [
            {"role": "system", "content": ASSESSMENT_SOURCE_REVOKED_OWNER_ACTIONS_PROTOCOL},
            {"role": "user", "content": user_message},
        ]
        assert len(provider_wire["tools"]) == 1
        tool = provider_wire["tools"][0]["function"]
        assert tool["name"] == "assessment_action"
        assert tool["description"] == REVOKED_ASSESSMENT_ACTION_TOOL_DESCRIPTION
        arguments = tool["parameters"]["properties"]["arguments"]
        assert arguments["properties"] == {
            "classification": {"enum": list(REVOKED_ASSESSMENT_ACTIONS), "type": "string"}
        }
        assert arguments["required"] == ["classification"]
        assert arguments["additionalProperties"] is False
    assert all(
        b"Question one" not in wire
        and b"Internal answer" not in wire
        and b"Internal only" not in wire
        for wire in wires
    )


def test_last_answer_starts_the_scorer_once_without_a_student_message(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    # After the last answer the student sends nothing more. The server must
    # ask the scorer itself, and must not retry a step that saved nothing.
    from app.modules.learning import finalizer

    _app, _database, settings = app_bundle
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        _recipe_id, team_id, *_rest = _create_formal_conversation(db, visibility="private")
    conversation_id = _create(client, csrf, {"kind": "maya_team", "team_id": team_id})["id"]
    claims: list[str] = []

    def run_without_saving(factory: Any, claim: runtime.TeamClaim, write_slot: Any = None) -> None:
        if write_slot is not None:
            write_slot.release()
        from app.modules.runtime_tools.builtin import runtime_registry
        from app.modules.runtime_tools.registry import exposed_tools

        with factory() as db:
            turn = db.get(ConversationTurn, claim.turn_id)
            assert turn is not None and turn.user_text == ""
            # Every Tool call re-checks a live sign-in; a session-less actor
            # failed here before the scorer reached the model.
            assert claim.actor_context is not None
            mounted = {
                spec.name
                for spec in exposed_tools(
                    db, claim.actor_context, turn.conversation_id, runtime_registry()
                )
            }
            assert "edit_assessment" in mounted
            result = db.scalar(select(TeamTurnResult).where(TeamTurnResult.turn_id == turn.id))
            assert result is not None
            claims.append(result.participant_id)
            result.state = "failed"
            turn.state = "failed"
            row = db.get(Conversation, turn.conversation_id)
            assert row is not None
            row.active_request_id = None
            db.commit()

    monkeypatch.setattr(runtime, "execute_team_turn", run_without_saving)
    with database.session() as db:
        actor = get_auth_context(db, settings, token)
        assert actor is not None
        context = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert context is not None
        while context.current_question is not None:
            question = context.current_question
            # Questions remain: nothing is run yet.
            finalizer.drive_assessment(database.session_factory, settings, conversation_id)
            assert claims == []
            mark_attempt_question_presented(
                db, actor, conversation_id, question_version_id=question.question_version_id
            )
            recorded = apply_assessment_decision(
                db,
                actor,
                conversation_id,
                user_message="我不知道",
                decision=AssessmentRuntimeDecision(
                    client_event_id=uuid4(),
                    classification="answer_only",
                    answer_span="我不知道",
                    question_version_id=question.question_version_id,
                ),
            )
            assert recorded is not None
            context = recorded.context
        db.commit()
        activity = db.scalar(
            select(AssessmentActivity).where(AssessmentActivity.team_id == team_id)
        )
        assert activity is not None
        evaluator = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.team_member_id == activity.evaluator_team_member_id,
            )
        )
        assert evaluator is not None

    # Signed out everywhere: the attempt waits for the student's next message.
    with database.session() as db:
        for record in db.scalars(
            select(SessionRecord).where(SessionRecord.user_id == actor.user.id)
        ):
            record.revoked_at = datetime.now(UTC)
        db.commit()
    finalizer.drive_assessment(database.session_factory, settings, conversation_id)
    assert claims == []
    _login(client, "bowen")
    # The scorer ran and saved nothing: the chain reports the stall.
    assert finalizer.drive_assessment(database.session_factory, settings, conversation_id)
    assert claims == [evaluator.id]
    from app.modules.workspace.team_conversation import _assessment_stage

    # #121: nothing runs now, so the chat stops showing scoring and waiting.
    with database.session() as db:
        assert _assessment_stage(db, db.get(Conversation, conversation_id)) is None
        turns_before = db.scalar(
            select(func.count())
            .select_from(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation_id)
        )

    # The write guard is full: the finalizer claims nothing, so no executor
    # turn is left holding the conversation, and the refusal surfaces.
    from app.core import write_guard

    def refuse(_settings: Any = None) -> Any:
        raise write_guard.write_pressure_error(
            reason="queue_full", limit=8, retry_after_seconds=5, in_flight=8, waiters=100
        )

    monkeypatch.setattr(write_guard, "reserve_write_slot", refuse)
    with pytest.raises(PlatformError) as refused:
        finalizer.drive_assessment(database.session_factory, settings, conversation_id)
    assert refused.value.code == "write_pressure"
    assert claims == [evaluator.id]
    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None and row.active_request_id is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
            )
            == turns_before
        )


def test_teacher_reads_a_private_test_window_but_not_chat_around_it(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    # Owner decision (2026-10-12): the course teacher may read the raw messages
    # of a formal test, Private Chats included; chat outside the test is not.
    from app.modules.learning.reports import read_attempt_transcripts

    _app, _database, settings = app_bundle
    token, csrf = _login(client, "bowen")
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        _recipe_id, team_id, *_rest = _create_formal_conversation(db, visibility="private")
    conversation_id = _create(client, csrf, {"kind": "maya_team", "team_id": team_id})["id"]

    def add_turn(db: Any, text: str, reply: str, when: datetime) -> None:
        row = db.get(Conversation, conversation_id)
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        turn_id = str(uuid4())
        row.revision += 1
        db.add(
            ConversationTurn(
                id=turn_id,
                conversation_id=conversation_id,
                position=row.revision,
                user_text=text,
                assistant_text=None,
                sources_json="[]",
                mode="mock",
                state="ready",
                routing_json="{}",
                request_hash="c" * 64,
                claim_token=str(uuid4()),
                created_at=when,
            )
        )
        db.flush()
        db.add(
            TeamTurnResult(
                id=str(uuid4()),
                turn_id=turn_id,
                conversation_id=conversation_id,
                participant_id=leader.id,
                ordinal=0,
                state="ready",
                assistant_text=reply,
                sources_json="[]",
                created_at=when,
                completed_at=when,
            )
        )
        db.flush()

    with database.session() as db:
        add_turn(db, "随便聊聊", "好的", datetime(2026, 1, 1, tzinfo=UTC))
        actor = get_auth_context(db, settings, token)
        assert actor is not None
        assert start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        add_turn(db, "我不知道", "已记录你的回答。", datetime.now(UTC))
        db.commit()
        activity = db.scalar(
            select(AssessmentActivity).where(AssessmentActivity.team_id == team_id)
        )
        assert activity is not None
        activity_id = activity.id

    teacher_token, _teacher_csrf = _login(client, "maya")
    with database.session() as db:
        teacher = get_auth_context(db, settings, teacher_token)
        assert teacher is not None
        transcripts = read_attempt_transcripts(
            db, teacher, course_id=COURSE_ID, activity_id=activity_id
        )
        assert len(transcripts) == 1
        assert transcripts[0]["chat_visibility"] == "private"
        texts = [message["text"] for message in transcripts[0]["messages"]]  # type: ignore[index]
        assert "我不知道" in texts and "已记录你的回答。" in texts
        assert "随便聊聊" not in texts
        # An abandoned attempt is its own record and stays out unless asked for.
        attempt = db.get(AssessmentAttempt, transcripts[0]["attempt_id"])
        assert attempt is not None
        attempt.status = "abandoned"
        attempt.abandoned_at = datetime.now(UTC)
        db.flush()
        assert (
            read_attempt_transcripts(db, teacher, course_id=COURSE_ID, activity_id=activity_id)
            == []
        )
        kept = read_attempt_transcripts(
            db, teacher, course_id=COURSE_ID, activity_id=activity_id, include_abandoned=True
        )
        assert [item["attempt_status"] for item in kept] == ["abandoned"]
        db.rollback()
    # Signing the teacher in rotated this client's session; sign the student back in.
    student_token, _student_csrf = _login(client, "bowen")
    with database.session() as db:
        student = get_auth_context(db, settings, student_token)
        assert student is not None
        try:
            read_attempt_transcripts(db, student, course_id=COURSE_ID, activity_id=activity_id)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        else:
            raise AssertionError("A student must not read test transcripts.")
