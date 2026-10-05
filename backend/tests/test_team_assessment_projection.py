from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from agno.models.response import ModelResponse
from app.core.models import AgentVersion
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
from sqlalchemy import func, select

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
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team_id}, visibility="private")
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
            expected_revision=0,
            message="Please explain the answer to this question.",
            routing=TeamRouting(mode="selected", participant_ids=[leader.id]),
            actor_context=actor,
        )
    result_id = runtime.result_ids(database.session_factory, claim.turn_id)[0]
    request = runtime._start_member(
        database.session_factory,
        claim.turn_id,
        claim.token,
        result_id,
        settings=settings,
        actor_context=actor,
    )
    assert request is not None
    assert request.assessment_active is True
    assert request.assessment_purpose is None
    assert "<active_assessment_action_protocol>" in request.system_message
    assert "assessment_action" in request.system_message
    assert "Internal answer" not in request.system_message
    assert request.knowledge_json == "{}"
    assert request.sources == ()
    assert runtime.settle_member(
        database.session_factory,
        claim.turn_id,
        claim.token,
        result_id,
        reply=runtime.MemberReply("This free-form answer must never reach the student."),
    )
    with database.session() as db:
        result = db.get(TeamTurnResult, result_id)
        turn = db.get(ConversationTurn, claim.turn_id)
        assert result is not None and turn is not None
        assert result.state == "failed"
        assert result.assistant_text is None
        assert result.sources_json == "[]"
        assert result.safe_error_code == "assessment_action_required"
        assert turn.state == "failed"
        assert "free-form answer" not in (result.assistant_text or "")
        assert (
            db.scalar(
                select(TeamTurnResult.id).where(
                    TeamTurnResult.turn_id == turn.id,
                    TeamTurnResult.assistant_text.is_not(None),
                )
            )
            is None
        )


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
    session = _create(client, csrf, {"kind": "maya_team", "team_id": team_id}, visibility="private")
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

    def dispatch_provider(
        _db: Any,
        _settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        _tool_choice: Any,
        **_kwargs: Any,
    ) -> TeamProviderDispatch:
        requests.append(request)
        calls.append((request.participant_id, messages, tools))
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
            claim = runtime.claim_team_turn(
                db,
                app_settings,
                conversation_id=conversation_id,
                actor_id=actor.user.id,
                request_id=str(uuid4()),
                expected_revision=row.revision,
                message="Please continue this saved assessment action.",
                routing=TeamRouting(mode="selected", participant_ids=[UUID(participant.id)]),
                actor_context=actor,
            )
        result_id = runtime.result_ids(database.session_factory, claim.turn_id)[0]
        runtime.execute_real_member(database.session_factory, claim, result_id)
        assert requests[-1].knowledge_json == "{}"
        assert requests[-1].sources == ()
        participant_id, messages, tools = calls[-1]
        assert participant_id == participant.id
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


def test_real_coordinate_keeps_evaluator_and_boundary_canaries_out_of_leader_wire(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
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
        ) = _create_formal_conversation(db, visibility="private")

    names = ("Bowen", "Jade", "Kaikai", "Maya")
    version_ids: list[str] = []
    for name in names:
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="private"
        )
        version_ids.append(version_id)
        instructions = [f"# {name}"]
        if name == "Bowen":
            instructions.extend(
                (
                    f"MAYA-ASSESSMENT-RECIPE: {SUPPORTED_RECIPE_ID}",
                    QUESTION_SCOPE_DECLARATION,
                    COMPLETION_DECLARATION,
                )
            )
        elif name == "Jade":
            instructions.append("MAYA-ASSESSMENT-ROLE: evaluator")
        elif name == "Kaikai":
            instructions.append("MAYA-ASSESSMENT-ROLE: boundary_summarizer")
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
        visibility="private",
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
        if request.participant_id == leader.id:
            if request.message.startswith("My final answer"):
                if ordinal == 0:
                    return tool_body(
                        f"answer-{request.turn_id}",
                        "assessment_action",
                        {
                            "classification": "answer_only",
                            "answer_span": "FINAL_ANSWER_CANARY",
                        },
                    )
                if ordinal == 1:
                    return tool_body(
                        f"delegate-evaluator-{request.turn_id}",
                        "delegate_task_to_member",
                        {
                            "member_id": evaluator.id,
                            "task": "Evaluate the saved responses using the assigned task.",
                        },
                    )
                if ordinal == 2:
                    return tool_body(
                        f"delegate-boundary-{request.turn_id}",
                        "delegate_task_to_member",
                        {
                            "member_id": boundary.id,
                            "task": "Summarize the saved evaluation using the assigned task.",
                        },
                    )
                return text_body("Untrusted coordinator prose after formal work.")
            raise AssertionError("Assessment completion must not require a second student turn.")
        if request.participant_id == evaluator.id:
            if ordinal == 0:
                return tool_body(
                    f"edit-assessment-{request.turn_id}",
                    "edit_assessment",
                    {"content": assessment_content},
                )
            return text_body("EVALUATOR_RAW_CANARY includes private rubric and internal task JSON.")
        if request.participant_id == boundary.id:
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
        raise AssertionError(f"Unexpected participant dispatch: {request.participant_id}")

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
    runtime.execute_team_turn(database.session_factory, claim)

    assert len(wires[leader.id]) >= 4
    assert len(wires[evaluator.id]) >= 2
    assert len(wires[boundary.id]) == 1
    assert (
        "edit_assessment",
        {"ok": True, "result": {"saved": True}},
    ) in tool_results
    assert (
        "update_learning_boundary",
        {"ok": True, "result": {"saved": True}},
    ) in tool_results
    assert ("edit_assessment", False) in function_flags[evaluator.id]
    assert ("update_learning_boundary", True) in function_flags[boundary.id]
    assert any(b"Internal only" in wire for wire in wires[evaluator.id])
    assert all(
        b"EVALUATOR_RAW_CANARY" not in wire
        and b"BOUNDARY_RAW_CANARY" not in wire
        and b"Internal only" not in wire
        for wire in wires[leader.id][1:]
    )
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None and turn.state == "ready"
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == turn.id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        assert [result.state for result in results] == ["ready", "ready", "ready"]
        assert all(
            "EVALUATOR_RAW_CANARY" not in (result.assistant_text or "")
            and "BOUNDARY_RAW_CANARY" not in (result.assistant_text or "")
            for result in results
        )
        child_stages = list(
            db.scalars(
                select(TeamProviderCall).where(
                    TeamProviderCall.result_id.in_([results[1].id, results[2].id])
                )
            )
        )
        assert any("EVALUATOR_RAW_CANARY" in stage.accepted_response_json for stage in child_stages)
        assert not any(
            "BOUNDARY_RAW_CANARY" in stage.accepted_response_json for stage in child_stages
        )
        assert sum(stage.result_id == results[2].id for stage in child_stages) == 1
        attempt_context = get_assessment_runtime_context(db, actor, conversation_id)
        assert attempt_context is None
        attempt_id = str(context.attempt.id)
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None and attempt.status == "completed"
        assert attempt_has_final_evidence(db, attempt)
        owner_projection = runtime.project_team_turn(db, turn, read_only=False).assessment_result
        assert owner_projection is not None
        assert owner_projection.response_key == "assessment.completed"
        assert owner_projection.context.attempt.status == "completed"
        assert owner_projection.context.current_question is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(ConversationTurn)
                .where(ConversationTurn.conversation_id == conversation_id)
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
        visibility="private",
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
        response = client.post(
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
        assert "Assessment progress" in progress_result.assistant_text
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
    from app.modules.workspace import chat as chat_module

    real_resume_wrapper = chat_module.execute_team_turn_with_natural_assessment_resume
    monkeypatch.setattr(
        chat_module,
        "execute_team_turn_with_natural_assessment_resume",
        runtime.execute_team_turn,
    )
    resumed_session = send("Continue the same assessment.", resume_id)
    monkeypatch.setattr(
        chat_module,
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
        assert calls_by_turn[resume_id] == 2
        assert calls_by_turn[resumed_source_id] == 0
        assert calls_by_turn[old_query_id] == 0

    # The durable resume receipt remains actionable if the process dies after
    # the user command commits but before the old turn is claimed.
    original_execute_team_turn = runtime.execute_team_turn

    def crash_after_resume_claim(factory: Any, claim: runtime.TeamClaim) -> None:
        if claim.turn_id != resumed_source_id:
            original_execute_team_turn(factory, claim)

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
        assert calls_by_turn[resume_id] == 2
        assert calls_by_turn[resumed_source_id] == 2
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
    token, csrf = _login(client, "bowen")
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
        db.add(
            ConversationSharedSet(
                conversation_id=conversation_id,
                knowledge_set_id=source_set_id,
                position=0,
            )
        )
        actor = get_auth_context(db, settings, token)
        assert actor is not None
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

    pause = client.post(
        f"/api/v1/conversations/{conversation_id}/turns/{old_claim.turn_id}:pause",
        headers=_headers(csrf),
    )
    assert pause.status_code == 200, pause.text
    assert pause.json()["turns"][0]["state"] == "paused"

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
    answers_response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
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
        assert "resolved 1/2" in (answer_result.assistant_text or "")
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
    continue_response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
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
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=_headers(csrf),
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
        assert result is not None and result.assistant_text == "This assessment attempt has ended."
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
        base_keys = {"model", "messages", "stream", "enable_thinking", "tools"}
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
