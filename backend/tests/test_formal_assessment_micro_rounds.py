"""Formal assessment speaks in server micro-rounds, or it does not start."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import AgentVersion
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.knowledge_sets.models import KnowledgeSet, KnowledgeSetMarkdownVersion
from app.modules.learning.attempts import (
    get_assessment_runtime_context,
    read_attempt_answers,
    start_or_resume_attempt,
)
from app.modules.learning.models import AssessmentAttempt
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.runtime_tools.models import RuntimeToolReceipt
from app.modules.teams.models import TeamVersionMember
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_team_provider import (
    dispatch_team_model as real_dispatch_team_model,
)
from app.modules.workspace.formal_assessment import (
    ABANDON_GUIDE,
    ABANDON_SCORER,
    ALL_DONE_GUIDE,
    RECORDED_FACT,
    SUMMARIZER_LINE,
    formal_ruleset_markdown,
    is_formal_start_message,
    resolve_formal_assessment,
)
from app.modules.workspace.models import (
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from app.seed import TEACHER_ID
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _create_formal_conversation,
    _service_actor,
)
from tests.test_mayaform_teams import MAYA_ID
from tests.test_wave4_provider_preflight import _digest, _policy


def test_assessment_active_is_not_a_tool() -> None:
    assert "assessment_active" not in runtime_registry()


def test_formal_start_messages_are_explicit() -> None:
    assert is_formal_start_message("正式测评")
    assert is_formal_start_message("  我想开始测试。")
    assert is_formal_start_message("请做正式测试")
    assert is_formal_start_message("再来一轮")
    assert is_formal_start_message("Start the formal test")
    assert is_formal_start_message("formal assessment")
    assert not is_formal_start_message("你好")
    assert not is_formal_start_message("开始吧")
    assert not is_formal_start_message("Take the test")
    assert not is_formal_start_message("甲题的回答")


def test_formal_section_must_name_the_roster_uniquely() -> None:
    roster = [("guide", "Bowen"), ("scorer", "Jade"), ("sum", "Kaikai")]
    complete = formal_ruleset_markdown(
        answer_recorder="Jade",
        question_guide="Bowen",
        scorer="Jade",
        summarizer="Kaikai",
        student_round_order=("Jade", "Bowen"),
    )
    resolved = resolve_formal_assessment(complete, roster)
    assert resolved is not None
    assert resolved.scorer_id == "scorer"
    assert resolved.answer_recorder_id == "scorer"
    assert resolved.question_guide_id == "guide"
    assert resolved.student_round_order_ids == ("scorer", "guide")
    guide_first = formal_ruleset_markdown(
        answer_recorder="Jade",
        question_guide="Bowen",
        scorer="Jade",
        summarizer="Kaikai",
        student_round_order=("Bowen", "Jade"),
    )
    reversed_roles = resolve_formal_assessment(guide_first, roster)
    assert reversed_roles is not None
    assert reversed_roles.student_round_order_ids == ("guide", "scorer")
    assert resolve_formal_assessment("# Persona\n\nHello.", roster) is None
    outside = (
        "# Team Ruleset\n\nBe brief.\n\n# Notes\n\n## Formal assessment\n"
        "answer_recorder: Jade\nquestion_guide: Bowen\nscorer: Jade\n"
        "summarizer: Kaikai\nstudent_round_order: Jade, Bowen\n"
    )
    assert resolve_formal_assessment(outside, roster) is None
    for broken in (
        complete.replace("summarizer: Kaikai\n", ""),
        complete.replace("student_round_order: Jade, Bowen", "student_round_order: Bowen, Bowen"),
        complete.replace("student_round_order: Jade, Bowen", "student_round_order: Jade"),
        complete.replace(
            "student_round_order: Jade, Bowen", "student_round_order: Bowen, Jade, Kaikai"
        ),
        complete.replace("student_round_order: Jade, Bowen", "student_round_order: Jade, Kaikai"),
        complete.replace("scorer: Jade", "scorer: Nobody"),
        complete.replace("answer_recorder: Jade", "answer_recorder: Bowen"),
    ):
        with pytest.raises(PlatformError) as caught:
            resolve_formal_assessment(broken, roster)
        assert caught.value.code == "assessment_ruleset_incomplete"
    with pytest.raises(PlatformError) as caught:
        resolve_formal_assessment(
            complete, [("a", "Jade"), ("b", "Jade"), ("c", "Bowen"), ("d", "Kaikai")]
        )
    assert caught.value.code == "assessment_ruleset_incomplete"


def test_incomplete_formal_section_creates_no_attempt(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题", "乙题")
        )
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        from app.modules.teams.models import TeamVersionMember

        member = db.scalar(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == conversation.team_version_id,
                TeamVersionMember.is_leader.is_(True),
            )
        )
        assert member is not None
        version = db.get(AgentVersion, member.agent_version_id)
        assert version is not None
        version.agent_md = (
            version.agent_md.split("# Team Ruleset")[0].rstrip()
            + "\nMAYA-ASSESSMENT-ROLE: evaluator\n"
        )
        db.commit()
        before = db.scalar(select(func.count()).select_from(AssessmentAttempt))
        actor = _service_actor(db, settings, STUDENT_ID)
        with pytest.raises(PlatformError) as caught:
            start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert caught.value.code == "assessment_ruleset_incomplete"
        db.rollback()
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(AssessmentAttempt)) == before


def _dashscope(app_bundle: Any, database: Any, policy_id: str) -> Any:
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
        policy_id=policy_id,
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest(f"{policy_id}-policy"),
        ).resolved_endpoint,
    )
    settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
    app.state.settings = settings
    ProviderRepository(database).save_policy_snapshot(policy)
    return settings, policy


def _grant(database: Any, conversation_id: str, policy: Any) -> None:
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


def _tool(call_id: str, name: str, arguments: dict[str, Any]) -> bytes:
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
                                    "arguments": json.dumps({"arguments": arguments}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    ).encode()


def _text(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ]
        }
    ).encode()


class _Transport:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
        return type("Response", (), {"status_code": 200, "content": self.body})()


def _run(
    database: Any,
    settings: Any,
    actor: Any,
    conversation_id: str,
    message: str,
    monkeypatch: Any,
    script: list[tuple[Any, ...]],
) -> str:
    calls: list[str] = []

    def synthetic_dispatch(
        db: Any, _settings: Any, request: runtime.MemberRequest, messages, tools, choice, **kwargs
    ):
        calls.append(request.formal_role or "")
        ordinal = len([item for item in calls if item == (request.formal_role or "")]) - 1
        if request.formal_role != "scorer":
            raise AssertionError(f"dispatched {request.formal_role}")
        if ordinal >= len(script):
            body = _text("extra")
        else:
            kind, name, arguments = script[ordinal]
            body = (
                _text(name)
                if kind == "text"
                else _tool(f"call-{ordinal}-{request.turn_id}", name, arguments)
            )
        return real_dispatch_team_model(
            db, settings, request, messages, tools, choice, transport=_Transport(body), **kwargs
        )

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    with database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message=message,
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )
    runtime.execute_team_turn(database.session_factory, claim)
    return claim.turn_id


def _texts(database: Any, turn_id: str) -> list[str | None]:
    with database.session() as db:
        return list(
            db.scalars(
                select(TeamTurnResult.assistant_text)
                .where(TeamTurnResult.turn_id == turn_id)
                .order_by(TeamTurnResult.ordinal)
            )
        )


def test_formal_micro_round_follows_the_eight_step_script(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题", "乙题")
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-micro-round")
    _grant(database, conversation_id, policy)

    opening = _run(database, settings, actor, conversation_id, "开始", monkeypatch, [])
    opening_text = _texts(database, opening)
    assert opening_text == ["收到，第一题是甲题"]
    with database.session() as db:
        context = get_assessment_runtime_context(db, actor, conversation_id)
        assert context is not None and context.progress.presented_count == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(TeamTurnResult)
                .where(TeamTurnResult.turn_id == opening)
            )
            == 1
        )

    first = "甲题的回答"
    first_turn = _run(
        database,
        settings,
        actor,
        conversation_id,
        first,
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": first},
            ),
            ("text", "已记录你的回答。"),
        ],
    )
    first_text = _texts(database, first_turn)
    assert first_text[0] == RECORDED_FACT
    assert "乙题" in (first_text[1] or "")
    assert "已记录" not in (first_text[1] or "")
    with database.session() as db:
        receipt = db.scalar(
            select(RuntimeToolReceipt).where(
                RuntimeToolReceipt.turn_id == first_turn,
                RuntimeToolReceipt.tool_name == "assessment_action",
            )
        )
        assert receipt is not None
        assert json.loads(receipt.result_json)["ok"] is True

    second = "乙题的回答"
    done = _run(
        database,
        settings,
        actor,
        conversation_id,
        second,
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": second},
            ),
            ("text", "已记录。"),
        ],
    )
    done_text = _texts(database, done)
    assert done_text[0] == RECORDED_FACT
    assert done_text[1] == ALL_DONE_GUIDE
    assert done_text[2] == SUMMARIZER_LINE
    assert "已记录" not in done_text[1]
    with database.session() as db:
        from app.modules.workspace.team_conversation import _assessment_stage

        stage = _assessment_stage(db, db.get(Conversation, conversation_id))
        assert stage in {"scoring", "summarizing", "completed"}


def _visible_lines(database: Any, actor: Any, conversation_id: str) -> list[str]:
    from app.modules.workspace.team_conversation import team_session_view

    with database.session() as db:
        row = db.get(Conversation, conversation_id)
        assert row is not None
        session = team_session_view(db, row, actor, [], runtime_available=True)
        assert all(turn.state != "partial" for turn in session.turns)
        assert all(
            result.state != "failed" and result.safe_error_code is None
            for turn in session.turns
            for result in turn.member_results
        )
        return [
            result.assistant_text
            for turn in session.turns
            for result in turn.member_results
            if result.assistant_text
        ]


def test_finished_assessment_ends_on_the_summary_line_and_retries_the_save(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    """Choice, free answer, then scale. The student sees the summary bar and nothing after it."""

    del client
    from app.modules.learning.execution import attempt_has_final_evidence
    from app.modules.learning.finalizer import drive_assessment
    from app.modules.learning.reports import attempt_answer_sheet

    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db,
            visibility="private",
            prompts=(
                "第一题\nA. 甲\nB. 乙\nC. 丙",
                "用你自己的话说明理由。",
                "请打分\n1 = 不同意\n2 = 一般\n3 = 同意\n4 = 非常同意",
            ),
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt_id = str(started.attempt.id)
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-end-flow")
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    _run(
        database,
        settings,
        actor,
        conversation_id,
        "B",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "B"},
            ),
            ("text", "已记录你的回答。"),
        ],
    )
    _run(
        database,
        settings,
        actor,
        conversation_id,
        "我不知道",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "我不知道"},
            ),
            ("text", "已记录你的回答。"),
        ],
    )
    _run(
        database,
        settings,
        actor,
        conversation_id,
        "4",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "4"},
            ),
            ("text", "已记录你的回答。"),
        ],
    )
    before = _visible_lines(database, actor, conversation_id)
    assert before == [
        "收到，第一题是第一题\nA. 甲\nB. 乙\nC. 丙",
        RECORDED_FACT,
        "第 2 题：用你自己的话说明理由。",
        RECORDED_FACT,
        "第 3 题：请打分\n1 = 不同意\n2 = 一般\n3 = 同意\n4 = 非常同意",
        ALL_DONE_GUIDE,
        SUMMARIZER_LINE,
    ]
    assert before.count(RECORDED_FACT) == 2

    boundary_calls = {"n": 0}

    def synthetic_dispatch(
        db: Any, _settings: Any, request: runtime.MemberRequest, messages, tools, choice, **kwargs
    ):
        if request.assessment_purpose == "assessment_evaluate":
            body = _tool(
                f"edit-{request.turn_id}",
                "edit_assessment",
                {
                    "content": {
                        "overall_feedback": "Saved.",
                        "questions": [
                            {
                                "question_ordinal": ordinal,
                                "feedback": "Recorded.",
                                "points_awarded": 1,
                            }
                            for ordinal in range(3)
                        ],
                        "strengths": ["Persistence"],
                        "next_steps": ["Continue."],
                    }
                },
            )
        elif request.assessment_purpose == "boundary_summarize":
            call = boundary_calls["n"]
            boundary_calls["n"] = call + 1
            if call == 0:
                body = _text("内部总结，不要给学生看")
            else:
                body = _tool(
                    f"boundary-{request.turn_id}",
                    "update_learning_boundary",
                    {
                        "summary": "三题都有作答，总结已保存。",
                        "strengths": ["完成了三题"],
                        "areas_to_explore": ["自由回答很短"],
                        "not_yet_verified": [],
                        "next_step": "再练一次理由。",
                    },
                )
        else:
            raise AssertionError(f"unexpected dispatch {request.assessment_purpose}")
        return real_dispatch_team_model(
            db, settings, request, messages, tools, choice, transport=_Transport(body), **kwargs
        )

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    drive_assessment(database.session_factory, settings, conversation_id)
    assert boundary_calls["n"] == 2
    assert _visible_lines(database, actor, conversation_id) == before
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None and attempt.status == "completed"
        assert attempt_has_final_evidence(db, attempt)
        sheet = attempt_answer_sheet(db, attempt)
        assert sheet["phase"] == "completed"
        answers = [question["answers"] for question in sheet["questions"]]
        assert answers == [["B"], ["我不知道"], ["4"]]
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.active_request_id is None


def test_a_summary_that_still_fails_is_recorded_for_the_teacher(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    from app.modules.learning.finalizer import drive_assessment
    from app.modules.learning.reports import (
        attempt_answer_sheet,
        attempt_teacher_phase,
        render_answer_sheet,
    )

    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt_id = str(started.attempt.id)
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-summary-miss")
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    _run(
        database,
        settings,
        actor,
        conversation_id,
        "甲",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "甲"},
            ),
            ("text", "已记录。"),
        ],
    )
    before = _visible_lines(database, actor, conversation_id)
    assert before[-2:] == [ALL_DONE_GUIDE, SUMMARIZER_LINE]
    assert RECORDED_FACT not in before

    calls = {"evaluate": 0, "boundary": 0}

    def synthetic_dispatch(
        db: Any, _settings: Any, request: runtime.MemberRequest, messages, tools, choice, **kwargs
    ):
        if request.assessment_purpose == "assessment_evaluate":
            calls["evaluate"] += 1
            body = _tool(
                f"edit-{request.turn_id}-{calls['evaluate']}",
                "edit_assessment",
                {
                    "content": {
                        "overall_feedback": "Saved.",
                        "questions": [
                            {
                                "question_ordinal": 0,
                                "feedback": "Recorded.",
                                "points_awarded": 1,
                            }
                        ],
                    }
                },
            )
        elif request.assessment_purpose == "boundary_summarize":
            calls["boundary"] += 1
            body = _text("没有调用保存工具")
        else:
            raise AssertionError(request.assessment_purpose)
        return real_dispatch_team_model(
            db, settings, request, messages, tools, choice, transport=_Transport(body), **kwargs
        )

    monkeypatch.setattr(
        "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
    )
    drive_assessment(database.session_factory, settings, conversation_id)
    assert calls["boundary"] == 2
    assert _visible_lines(database, actor, conversation_id) == before
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None and attempt.status == "in_progress"
        assert attempt_teacher_phase(db, attempt) == "summary_not_saved"
        sheet = attempt_answer_sheet(db, attempt)
        assert sheet["phase"] == "summary_not_saved"
        assert "summary not saved" in render_answer_sheet(sheet)


def test_recorded_fact_requires_a_tool_receipt(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        assert (
            start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4()) is not None
        )
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-no-receipt")
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "开始", monkeypatch, [])
    turn_id = _run(
        database,
        settings,
        actor,
        conversation_id,
        "只是散文",
        monkeypatch,
        [("text", "已记录你的回答。", {})],
    )
    texts = _texts(database, turn_id)
    assert all(text is None or "已记录" not in text for text in texts)
    with database.session() as db:
        states = db.scalars(
            select(TeamTurnResult.state).where(TeamTurnResult.turn_id == turn_id)
        ).all()
        assert states
        assert all(state == "failed" for state in states)
        assert (
            db.scalar(
                select(func.count())
                .select_from(RuntimeToolReceipt)
                .where(RuntimeToolReceipt.turn_id == turn_id)
            )
            == 0
        )


def test_abandon_clears_the_ledger_after_the_scripted_lines(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        started = start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert started is not None
        attempt_id = str(started.attempt.id)
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-abandon")
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "开始", monkeypatch, [])
    abandoned = _run(
        database,
        settings,
        actor,
        conversation_id,
        "我放弃",
        monkeypatch,
        [
            ("tool", "assessment_action", {"classification": "abandon_request"}),
            ("text", "已记录你的回答。"),
        ],
    )
    texts = _texts(database, abandoned)
    assert texts[0] == ABANDON_SCORER
    assert texts[1] == ABANDON_GUIDE
    assert SUMMARIZER_LINE not in texts
    assert all("已记录" not in (text or "") for text in texts)
    with database.session() as db:
        attempt = db.get(AssessmentAttempt, attempt_id)
        assert attempt is not None and attempt.status == "abandoned"
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="随便聊聊",
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )
    request = runtime._start_member(
        database.session_factory,
        claim.turn_id,
        claim.token,
        runtime.result_ids(database.session_factory, claim.turn_id)[0],
        settings=settings,
        actor_context=actor,
    )
    assert request is not None
    assert request.assessment_active is False
    assert request.formal_role is None
    runtime.settle_member(
        database.session_factory,
        claim.turn_id,
        claim.token,
        request.result_id,
        reply=runtime.MemberReply("可以聊聊。"),
        actor_context=actor,
    )


def _guide_version(db: Any, conversation_id: str) -> AgentVersion:
    conversation = db.get(Conversation, conversation_id)
    assert conversation is not None
    guide = db.scalar(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.is_leader.is_(True),
        )
    )
    assert guide is not None
    version = db.get(AgentVersion, guide.agent_version_id)
    assert version is not None
    return version


def test_mismatched_student_round_order_creates_no_attempt(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        version = _guide_version(db, conversation_id)
        version.agent_md = re.sub(
            r"(?m)^student_round_order:.*$",
            "student_round_order: Jade, Kaikai",
            version.agent_md,
            count=1,
        )
        db.commit()
        before = db.scalar(select(func.count()).select_from(AssessmentAttempt))
        actor = _service_actor(db, settings, STUDENT_ID)
        with pytest.raises(PlatformError) as caught:
            start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        assert caught.value.code == "assessment_ruleset_incomplete"
        db.rollback()
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(AssessmentAttempt)) == before


def test_guide_then_scorer_order_speaks_the_guide_first(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题", "乙题")
        )
        version = _guide_version(db, conversation_id)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.team_version_id is not None
        members = db.scalars(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == conversation.team_version_id
            )
        ).all()
        by_name = {member.display_name: member.id for member in members}
        current = resolve_formal_assessment(
            version.agent_md, [(member.id, member.display_name) for member in members]
        )
        assert current is not None
        guide_name = next(
            name for name, member_id in by_name.items() if member_id == current.question_guide_id
        )
        scorer_name = next(
            name for name, member_id in by_name.items() if member_id == current.scorer_id
        )
        version.agent_md = re.sub(
            r"(?m)^student_round_order:.*$",
            f"student_round_order: {guide_name}, {scorer_name}",
            version.agent_md,
            count=1,
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        assert (
            start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4()) is not None
        )
        db.commit()
    settings, policy = _dashscope(app_bundle, database, "formal-guide-first")
    _grant(database, conversation_id, policy)
    opening = _run(database, settings, actor, conversation_id, "开始", monkeypatch, [])
    assert _texts(database, opening) == ["收到，第一题是甲题"]
    answer = "甲题的回答"
    turn_id = _run(
        database,
        settings,
        actor,
        conversation_id,
        answer,
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": answer},
            )
        ],
    )
    with database.session() as db:
        speakers = db.execute(
            select(ConversationParticipant.team_member_id, TeamTurnResult.assistant_text)
            .join(
                TeamTurnResult,
                TeamTurnResult.participant_id == ConversationParticipant.id,
            )
            .where(TeamTurnResult.turn_id == turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
        version = _guide_version(db, conversation_id)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.team_version_id is not None
        members = db.scalars(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == conversation.team_version_id
            )
        ).all()
        roles = resolve_formal_assessment(
            version.agent_md, [(member.id, member.display_name) for member in members]
        )
    assert roles is not None
    assert roles.answer_recorder_id == roles.scorer_id
    assert [member_id for member_id, _text in speakers] == [
        roles.question_guide_id,
        roles.answer_recorder_id,
    ]
    assert "乙题" in (speakers[0][1] or "")
    assert speakers[1][1] == RECORDED_FACT
    assert "已记录" not in (speakers[0][1] or "")


def _roles(database: Any, conversation_id: str) -> Any:
    with database.session() as db:
        version = _guide_version(db, conversation_id)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None and conversation.team_version_id is not None
        members = db.scalars(
            select(TeamVersionMember).where(
                TeamVersionMember.team_version_id == conversation.team_version_id
            )
        ).all()
        return resolve_formal_assessment(
            version.agent_md, [(member.id, member.display_name) for member in members]
        )


def test_explicit_formal_start_is_the_guide_opening_before_any_member(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题", "乙题")
        )
        version = _guide_version(db, conversation_id)
        version.agent_md += (
            "\n\n## 开场\n"
            "学生说正式测评时，由 Scorer 用 Gettier 认识论开场，然后由 Scorer 启动测试。\n"
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    settings, policy = _dashscope(app_bundle, database, "formal-explicit-start")
    _grant(database, conversation_id, policy)
    opening = _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    assert _texts(database, opening) == ["收到，第一题是甲题"]
    with database.session() as db:
        context = get_assessment_runtime_context(db, actor, conversation_id)
        assert context is not None and context.progress.presented_count == 1
        assert context.progress.resolved_count == 0
    answer = "甲题的回答"
    turn_id = _run(
        database,
        settings,
        actor,
        conversation_id,
        answer,
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": answer},
            )
        ],
    )
    with database.session() as db:
        speakers = db.execute(
            select(ConversationParticipant.team_member_id, TeamTurnResult.assistant_text)
            .join(
                TeamTurnResult,
                TeamTurnResult.participant_id == ConversationParticipant.id,
            )
            .where(TeamTurnResult.turn_id == turn_id)
            .order_by(TeamTurnResult.ordinal)
        ).all()
    roles = _roles(database, conversation_id)
    assert roles is not None
    assert [member_id for member_id, _text in speakers] == list(roles.student_round_order_ids)
    assert speakers[0][1] == RECORDED_FACT
    assert "乙题" in (speakers[1][1] or "")
    assert "Gettier" not in "".join(text or "" for _member, text in speakers)
    assert SUMMARIZER_LINE not in [text for _member, text in speakers]


_RUBRIC_CANARY = "RUBRIC_CANARY_DO_NOT_SHOW"
_ANSWER_CANARY = "ANSWER_KEY_CANARY_DO_NOT_SHOW"
_WELCOME = "约 8 分钟 · 没有对错\n\nAbout 8 minutes. No right or wrong answers."


def _question_bank(preamble: str) -> str:
    return (
        "# 认识论小测\n\n"
        f"{preamble}"
        "## Questions\n\n"
        "### Question 1\n\n"
        "甲题\n\n"
        "#### Rubric\n\n"
        f"- **Reasoning** (2): {_RUBRIC_CANARY}\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        f"{_ANSWER_CANARY}\n\n"
        "### Question 2\n\n"
        "乙题\n\n"
        "#### Rubric\n\n"
        f"- **Reasoning** (2): {_RUBRIC_CANARY}\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        f"{_ANSWER_CANARY}\n"
    )


def _attach_markdown(db: Any, set_id: str, markdown: str, version_ids: list[str]) -> None:
    set_row = db.get(KnowledgeSet, set_id)
    assert set_row is not None
    set_row.current_markdown_version_seq = 1
    set_row.content_revision += 1
    db.add(
        KnowledgeSetMarkdownVersion(
            id=str(uuid4()),
            knowledge_set_id=set_id,
            version_seq=1,
            markdown=markdown,
            student_projection_markdown=markdown,
            asset_version_ids_json=json.dumps(
                version_ids, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            content_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
            origin="manual",
            generation_run_id=None,
            generation_intent_seq=None,
            source_manifest_hash=None,
            created_by_user_id=TEACHER_ID,
            generator_agent_version_id=None,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()


def test_formal_start_speaks_the_knowledge_opening_before_question_one(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            set_id,
            questions,
        ) = _create_formal_conversation(db, visibility="private", prompts=("甲题", "乙题"))
        _attach_markdown(
            db,
            set_id,
            _question_bank(f"## Opening\n\n{_WELCOME}\n\n先读说明，再作答。\n\n"),
            [version_id for _asset_id, version_id in questions],
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    settings, policy = _dashscope(app_bundle, database, "formal-knowledge-opening")
    _grant(database, conversation_id, policy)
    opening = _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    text = _texts(database, opening)
    assert text == [
        f"{_WELCOME}\n\n先读说明，再作答。\n\n收到，第一题是甲题",
    ]
    spoken = text[0] or ""
    assert _RUBRIC_CANARY not in spoken
    assert _ANSWER_CANARY not in spoken
    assert spoken.index("约 8 分钟 · 没有对错") < spoken.index("收到，第一题是甲题")
    answer = "甲题的回答"
    answered = _run(
        database,
        settings,
        actor,
        conversation_id,
        answer,
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": answer},
            )
        ],
    )
    later = "\n".join(item or "" for item in _texts(database, answered))
    assert "约 8 分钟" not in later
    assert "About 8 minutes" not in later
    assert "乙题" in later
    assert _RUBRIC_CANARY not in later
    assert _ANSWER_CANARY not in later


def test_formal_start_without_an_opening_is_unchanged(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        (
            conversation_id,
            _team_id,
            _team_version_id,
            _publication_id,
            set_id,
            questions,
        ) = _create_formal_conversation(db, visibility="private", prompts=("甲题", "乙题"))
        _attach_markdown(
            db,
            set_id,
            _question_bank("## Concepts\n\nCONCEPT_CANARY_NOT_A_WELCOME\n\n"),
            [version_id for _asset_id, version_id in questions],
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    settings, policy = _dashscope(app_bundle, database, "formal-no-knowledge-opening")
    _grant(database, conversation_id, policy)
    opening = _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    assert _texts(database, opening) == ["收到，第一题是甲题"]


def test_invalid_scale_answer_is_one_scorer_rejection(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    prompt = "请给信心打 1-5 分"
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=(prompt, "乙题")
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    settings, policy = _dashscope(app_bundle, database, "formal-invalid-scale")
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    rejected = _run(
        database,
        settings,
        actor,
        conversation_id,
        "u",
        monkeypatch,
        [
            ("tool", "assessment_action", {"classification": "answer_only", "answer_span": "u"}),
            ("text", "第 1 题再来一次"),
        ],
    )
    with database.session() as db:
        context = get_assessment_runtime_context(db, actor, conversation_id)
        assert context is not None
        assert context.progress.resolved_count == 0
        assert context.current_question is not None
        assert context.current_question.prompt == prompt
        speakers = db.execute(
            select(
                ConversationParticipant.team_member_id,
                TeamTurnResult.assistant_text,
                TeamTurnResult.state,
            )
            .join(
                TeamTurnResult,
                TeamTurnResult.participant_id == ConversationParticipant.id,
            )
            .where(TeamTurnResult.turn_id == rejected)
            .order_by(TeamTurnResult.ordinal)
        ).all()
    roles = _roles(database, conversation_id)
    assert roles is not None
    assert [member_id for member_id, _text, _state in speakers] == list(
        roles.student_round_order_ids
    )
    assert all(state == "ready" for _member, _text, state in speakers)
    rejection, question = speakers[0][1], speakers[1][1]
    assert rejection == "这条回复不是本题的答案，没有记录。请回复 1–5 之间的一个数字。"
    assert question == f"第 1 题：{prompt}"
    assert prompt not in (rejection or "")
    assert (question or "").count(prompt) == 1
    recorded = _run(
        database,
        settings,
        actor,
        conversation_id,
        "3",
        monkeypatch,
        [("tool", "assessment_action", {"classification": "answer_only", "answer_span": "3"})],
    )
    recorded_text = [text for text in _texts(database, recorded) if text and text.strip()]
    assert recorded_text[0] == RECORDED_FACT
    assert any("乙题" in (text or "") for text in recorded_text)
    with database.session() as db:
        context = get_assessment_runtime_context(db, actor, conversation_id)
        assert context is not None and context.progress.resolved_count == 1


def test_greeting_does_not_open_formal_and_incomplete_ruleset_refuses(
    client: TestClient, database: Any, app_bundle: Any
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题",)
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        before = db.scalar(select(func.count()).select_from(AssessmentAttempt))
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="你好",
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )
        turn = db.get(ConversationTurn, claim.turn_id)
        assert turn is not None
        assert json.loads(turn.routing_json or "{}")["mode"] == "auto"
        assert db.scalar(select(func.count()).select_from(AssessmentAttempt)) == before
        version = _guide_version(db, conversation_id)
        version.agent_md = version.agent_md.split("# Team Ruleset")[0].rstrip() + "\n"
        db.commit()
        conversation = db.get(Conversation, conversation_id)
        assert conversation is not None
        before_turns = db.scalar(select(func.count()).select_from(ConversationTurn))
        with pytest.raises(PlatformError) as caught:
            runtime.claim_team_turn(
                db,
                settings,
                conversation_id=conversation_id,
                actor_id=actor.user.id,
                request_id=str(uuid4()),
                expected_revision=conversation.revision,
                message="正式测评",
                routing=TeamRouting(mode="auto"),
                actor_context=actor,
            )
        assert caught.value.code == "assessment_ruleset_incomplete"
        db.rollback()
    with database.session() as db:
        assert db.scalar(select(func.count()).select_from(AssessmentAttempt)) == before
        assert db.scalar(select(func.count()).select_from(ConversationTurn)) == before_turns


REASON = "关于第 1 题：你选了哪一项？能用一两句话说说你当时是怎么想的吗？"
HOW_TO_ANSWER = "请说出你在第 1 题选了哪项，并用一两句话说说理由"
SAD = "听起来你现在很难受。想答的时候，回复 1 到 5 里的一个数字就好。"
QUIT = "不想做的时候可以先停一下。想答时，回复 1 到 5 里的一个数字就好。"
SCALE = (
    "今天被认为正确的知识，将来可能会被修正。\n\n请选择你同意的程度，回复数字即可：\n\n"
    "1 = 非常不同意　2 = 不同意　3 = 不确定　4 = 同意　5 = 非常同意"
)


@pytest.mark.parametrize(
    ("prompt", "message", "arguments", "saved", "spoken", "repeats_question"),
    [
        (
            REASON,
            "现在进展如何",
            {"classification": "off_topic", "relevant": False, "guidance": HOW_TO_ANSWER},
            False,
            HOW_TO_ANSWER,
            False,
        ),
        (
            REASON,
            "B",
            {"classification": "off_topic", "relevant": False, "guidance": HOW_TO_ANSWER},
            False,
            HOW_TO_ANSWER,
            False,
        ),
        (
            REASON,
            "现在进展如何",
            {"classification": "answer_only", "answer_span": "现在进展如何"},
            False,
            "这条回复不是本题的答案，没有记录。请直接写出你对这道题的回答。",
            True,
        ),
        (
            SCALE,
            "我好伤心感觉好难啊",
            {"classification": "off_topic", "relevant": False, "guidance": SAD},
            False,
            SAD,
            False,
        ),
        (
            SCALE,
            "我感觉好难不想做了怎么办",
            {"classification": "off_topic", "relevant": False, "guidance": QUIT},
            False,
            QUIT,
            False,
        ),
        (
            REASON,
            "我选了 B，因为当时觉得那一项最接近。",
            {
                "classification": "answer_only",
                "relevant": True,
                "answer_span": "我选了 B，因为当时觉得那一项最接近。",
            },
            True,
            RECORDED_FACT,
            True,
        ),
    ],
)
def test_free_response_relevance_follows_the_model_judgment(
    client: TestClient,
    database: Any,
    app_bundle: Any,
    monkeypatch: Any,
    prompt: str,
    message: str,
    arguments: dict[str, Any],
    saved: bool,
    spoken: str,
    repeats_question: bool,
) -> None:
    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=(prompt, "乙题")
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
    settings, policy = _dashscope(
        app_bundle,
        database,
        f"formal-relevant-{arguments['classification']}-{len(message)}-{saved}",
    )
    _grant(database, conversation_id, policy)
    _run(database, settings, actor, conversation_id, "正式测评", monkeypatch, [])
    turn_id = _run(
        database,
        settings,
        actor,
        conversation_id,
        message,
        monkeypatch,
        [("tool", "assessment_action", arguments)],
    )
    texts = [text for text in _texts(database, turn_id) if text]
    assert texts[0] == spoken
    if saved:
        assert "乙题" in (texts[1] or "")
    elif repeats_question:
        assert prompt in (texts[1] or "")
    else:
        assert texts[1] == "还是这道题。"
        assert prompt not in "\n".join(texts)
    with database.session() as db:
        answers = read_attempt_answers(db, actor, conversation_id)
        assert bool(answers) is saved
        if saved:
            assert answers[0].answer_text == message
