"""A formal answer is saved whatever shape the Leader's real model reply takes.

Reproduces the lost first answer: a final message with no text, or Tool
arguments sent flat instead of under "arguments", used to fail the whole turn.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any
from uuid import uuid4

import pytest
from app.core.models import AgentVersion
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import (
    get_assessment_runtime_context,
    mark_attempt_question_presented,
    read_attempt_answers,
    start_or_resume_attempt,
)
from app.modules.learning.recipes import (
    COMPLETION_DECLARATION,
    QUESTION_SCOPE_DECLARATION,
    SUPPORTED_RECIPE_ID,
)
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import (
    dispatch_team_model as real_dispatch_team_model,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationTurn,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_mayaform_assessment_attempts import _create_formal_conversation, _login
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_wave4_provider_preflight import _digest, _policy

ANSWER = (
    "Predictive Tasks 是根据已有数据预测结果，比如预测房价；"
    "Decision-Making Tasks 是在多个选项中做出决定，比如选择投资方案。"
)


def _tool(call_id: str, name: str, arguments: dict[str, Any], wrap: bool = True) -> bytes:
    wire = {"arguments": arguments} if wrap else arguments
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
                                "function": {"name": name, "arguments": json.dumps(wire)},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    ).encode()


def _text(content: str | None) -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ]
        }
    ).encode()


ANSWER_ACTION = {"classification": "answer_only", "answer_span": ANSWER}
MESSAGES = {
    "bare_letter_called_off_topic": "b",
    "bare_letter_with_a_wrong_span": "B",
    "bare_number_called_start": "3",
    "statement_on_open_question": "知道意味着用在行动上",
    "answer_with_a_paraphrased_span": "知道意味着用在行动上",
    "question_back_stays_unrecorded": "我回答了 为什么没有记录",
}

# scenario -> (scripted Leader replies, saved answers, Leader result state, code)
SCENARIOS: dict[str, tuple[list[Any], int, str, str | None]] = {
    "tool_then_text": (
        [("tool", "assessment_action", ANSWER_ACTION), ("text", "已记录。")],
        1,
        "ready",
        None,
    ),
    "tool_then_null": (
        [("tool", "assessment_action", ANSWER_ACTION), ("text", None)],
        1,
        "ready",
        None,
    ),
    "tool_then_empty": (
        [("tool", "assessment_action", ANSWER_ACTION), ("text", "")],
        1,
        "ready",
        None,
    ),
    "flat_arguments": (
        [("flat", "assessment_action", ANSWER_ACTION), ("text", "已记录。")],
        1,
        "ready",
        None,
    ),
    # Bug (2026-10-13): late in a long test the Leader called a bare answer
    # something else, and the same Question kept coming back.
    "bare_letter_called_off_topic": (
        [("tool", "assessment_action", {"classification": "off_topic"}), ("text", "")],
        1,
        "ready",
        None,
    ),
    "bare_letter_with_a_wrong_span": (
        [
            ("tool", "assessment_action", {"classification": "answer_only", "answer_span": "B."}),
            ("text", ""),
        ],
        1,
        "ready",
        None,
    ),
    # Bug (2026-10-13): an open question's answer called off_topic repeatedly.
    "statement_on_open_question": (
        [("tool", "assessment_action", {"classification": "off_topic"}), ("text", "")],
        1,
        "ready",
        None,
    ),
    # The model's copy of a free answer did not match the message; the
    # student's own words are saved, not "我们继续测试".
    "answer_with_a_paraphrased_span": (
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "answer_span": "知道就是行动"},
            ),
            ("text", ""),
        ],
        1,
        "ready",
        None,
    ),
    # A question back is not an answer.
    "question_back_stays_unrecorded": (
        [("tool", "assessment_action", {"classification": "off_topic"}), ("text", "")],
        0,
        "ready",
        None,
    ),
    "bare_number_called_start": (
        [("tool", "assessment_action", {"classification": "start_request"}), ("text", "")],
        1,
        "ready",
        None,
    ),
    # The action protocol requires the Tool; prose or no text alone stays a failed turn.
    "prose_only": ([("text", "很好的回答！")], 0, "failed", "assessment_action_required"),
    "empty_only": ([("text", None)], 0, "failed", "assessment_action_required"),
}


@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_first_answer_is_saved_for_each_leader_reply_shape(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any, scenario: str
) -> None:
    app, _database, base_settings = app_bundle
    _teacher_token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
        *_ignored, set_id, _questions = _create_formal_conversation(
            db, visibility="private", prompts=("Q1 Predictive vs Decision", "Q2", "Q3", "Q4")
        )
    version_ids: list[str] = []
    for name in ("Bowen", "Jade", "Kaikai"):
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="public"
        )
        version_ids.append(version_id)
        from app.modules.workspace.formal_assessment import formal_ruleset_markdown

        lines = [f"# {name}"]
        if name == "Bowen":
            lines += [
                f"MAYA-ASSESSMENT-RECIPE: {SUPPORTED_RECIPE_ID}",
                QUESTION_SCOPE_DECLARATION,
                COMPLETION_DECLARATION,
                "",
                formal_ruleset_markdown(
                    answer_recorder="Jade",
                    question_guide="Bowen",
                    scorer="Jade",
                    summarizer="Kaikai",
                    student_round_order=("Bowen", "Jade", "Kaikai"),
                ),
            ]
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            version.agent_md = "\n".join(lines)
            version.avatar_config_json = json.dumps(
                {
                    "template_id": "synthetic",
                    "material_theme": "default",
                    "default_expression": "neutral",
                    "expression_strength": "low",
                    "motion_style": "calm",
                }
            )
    team = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"repro-{uuid4()}"),
        json={
            "display_name": "introduction quiz",
            "visibility": "public",
            "members": [
                {"agent_version_id": v, "is_leader": i == 0, "position": i}
                for i, v in enumerate(version_ids)
            ],
            "shared_knowledge_set_ids": [set_id],
        },
    )
    assert team.status_code == 201, team.text
    student_token, student_csrf = _login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": team.json()["id"]})
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, base_settings, student_token)
        context = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert context is not None and context.current_question is not None
        mark_attempt_question_presented(
            db,
            actor,
            conversation_id,
            question_version_id=context.current_question.question_version_id,
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
        policy_id="repro-q1",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("repro-q1-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
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
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message=MESSAGES.get(scenario, ANSWER),
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )
        scorer_id = db.scalar(
            select(TeamTurnResult.participant_id)
            .where(TeamTurnResult.turn_id == claim.turn_id)
            .order_by(TeamTurnResult.ordinal)
        )

    script, expected_answers, expected_state, expected_code = SCENARIOS[scenario]
    calls: dict[str, int] = defaultdict(int)

    class Response:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class Transport:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            return Response(self.body)

    def synthetic_dispatch(
        db: Any,
        _settings: Any,
        request: runtime.MemberRequest,
        messages: list[Any],
        tools: list[dict[str, Any]] | None,
        choice: Any,
        **kwargs: Any,
    ) -> Any:
        ordinal = calls[request.result_id]
        calls[request.result_id] += 1
        if request.participant_id != scorer_id:
            raise AssertionError("only the scorer is dispatched on a student answer")
        if ordinal < len(script):
            kind, *rest = script[ordinal]
            if kind == "text":
                body = _text(rest[0])
            else:
                body = _tool(
                    f"call-{ordinal}-{request.turn_id}", rest[0], rest[1], wrap=kind == "tool"
                )
        else:
            body = _text("extra")
        return real_dispatch_team_model(
            db, settings, request, messages, tools, choice, transport=Transport(body), **kwargs
        )

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    runtime.execute_team_turn(database.session_factory, claim)
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        results = db.scalars(
            select(TeamTurnResult)
            .where(TeamTurnResult.turn_id == turn.id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        after = get_assessment_runtime_context(db, actor, conversation_id)
        assert after is not None
        assert len(read_attempt_answers(db, actor, conversation_id)) == expected_answers
        assert after.progress.resolved_count == expected_answers
        scorer = results[0]
        assert (scorer.state, scorer.safe_error_code) == (expected_state, expected_code)
        assert all("已记录" not in (result.assistant_text or "") for result in results[1:])
        if expected_state == "failed":
            assert all("已记录" not in (result.assistant_text or "") for result in results)
        if scenario in MESSAGES and expected_answers:
            [saved] = read_attempt_answers(db, actor, conversation_id)
            assert saved.answer_text == MESSAGES[scenario]
        elif scenario in MESSAGES:
            pass
        elif expected_state == "ready":
            assert scorer.assistant_text == "已记录你的回答。"
            assert turn.state == "ready"


def test_a_final_message_without_text_parses_as_empty_text() -> None:
    from app.modules.workspace.chat_team_provider import _model_response
    from app.modules.workspace.chat_team_sdk import TeamDispatchError

    assert _model_response(_text(None).decode()).content == ""
    assert _model_response(_text("").decode()).content == ""
    with pytest.raises(TeamDispatchError):
        _model_response(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": {"text": "x"}},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
        )
