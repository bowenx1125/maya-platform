"""Short factual answers, skips, unsure-confirm and answer edits (2026-10-20).

CHENShaoyan's student-ID question looped: the Scorer marked "2330034002" and
"人工智能" not relevant, so the server never saved them. These run the real
Team turn path with a scripted Scorer and check what the server records.
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
from app.modules.learning.answer_guard import (
    collects_info,
    edit_request,
    is_confirm_only,
    is_skip_only,
)
from app.modules.learning.attempts import (
    get_assessment_runtime_context,
    mark_attempt_question_presented,
    read_attempt_answers,
    start_or_resume_attempt,
)
from app.modules.learning.models import AssessmentAttemptQuestion, LearningRecord
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
from app.modules.workspace.models import Conversation, ConversationTurn, TeamTurnResult
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_assessment_answer_reply_shapes import _text, _tool
from tests.test_mayaform_assessment_attempts import _create_formal_conversation, _login
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_wave4_provider_preflight import _digest, _policy

UNSURE = {"classification": "answer_only", "relevant": False}
OFF = {"classification": "off_topic", "relevant": False}


def test_guard_words() -> None:
    assert collects_info("请写下你的学号和专业")
    assert collects_info("What is your major?")
    assert not collects_info("为什么知行合一？")
    for word in ("跳过", "跳过吧", "skip", "下一题", "Skip this question"):
        assert is_skip_only(word), word
    assert not is_skip_only("跳过这题因为太难，我觉得是A")
    assert is_confirm_only("确认") and is_confirm_only("confirm") and is_confirm_only("是的，确认")
    assert not is_confirm_only("我确认这个说法是错的")
    assert edit_request("修改第2题：人工智能").answer == "人工智能"  # type: ignore[union-attr]
    assert edit_request("change my answer to question 1: AI").number == 1  # type: ignore[union-attr]
    assert edit_request("第2题我不会") is None


class _Harness:
    def __init__(
        self, client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any, prompts: Any
    ) -> None:
        app, _database, base_settings = app_bundle
        self.database = database
        self.monkeypatch = monkeypatch
        _teacher_token, teacher_csrf = _login(client, "maya")
        with database.session() as db:
            ensure_demo_baseline(db, base_settings.resolved_data_root)
            *_ignored, set_id, _questions = _create_formal_conversation(
                db, visibility="private", prompts=prompts
            )
        version_ids: list[str] = []
        from app.modules.workspace.formal_assessment import formal_ruleset_markdown

        for name in ("Bowen", "Jade", "Kaikai"):
            _agent_id, version_id = _make_agent_version(
                database, owner_id=MAYA_ID, name=name, visibility="public"
            )
            version_ids.append(version_id)
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
                        student_round_order=("Jade", "Bowen"),
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
            headers=_headers(teacher_csrf, f"guard-{uuid4()}"),
            json={
                "display_name": "guard quiz",
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
        self.conversation_id = session["id"]
        with database.session() as db:
            self.actor = get_auth_context(db, base_settings, student_token)
            context = start_or_resume_attempt(
                db, self.actor, self.conversation_id, client_event_id=uuid4()
            )
            assert context is not None and context.current_question is not None
            mark_attempt_question_presented(
                db,
                self.actor,
                self.conversation_id,
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
            policy_id="guard-q1",
            endpoint=DashScopeLLMConfig(
                api_key="synthetic-key",
                workspace_id="synthetic-workspace",
                region="cn-beijing",
                model_key=settings.llm_model,
                policy_hash=_digest("guard-q1-policy"),
            ).resolved_endpoint,
        )
        settings = settings.model_copy(update={"llm_provider_policy_hash": policy.policy_hash})
        app.state.settings = settings
        self.settings = settings
        ProviderRepository(database).save_policy_snapshot(policy)
        with database.session() as db:
            conversation = db.get(Conversation, self.conversation_id)
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

    def send(self, message: str, action: dict[str, Any]) -> str:
        """Run one student turn with a scripted Scorer; return all reply text."""

        settings = self.settings
        with self.database.session() as db:
            conversation = db.get(Conversation, self.conversation_id)
            claim = runtime.claim_team_turn(
                db,
                settings,
                conversation_id=self.conversation_id,
                actor_id=self.actor.user.id,
                request_id=str(uuid4()),
                expected_revision=conversation.revision,
                message=message,
                routing=TeamRouting(mode="auto"),
                actor_context=self.actor,
            )
        calls: dict[str, int] = defaultdict(int)
        script = [("tool", action), ("text", "")]

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
            if ordinal < len(script):
                kind, payload = script[ordinal]
                body = (
                    _tool(f"call-{ordinal}-{request.result_id}", "assessment_action", payload)
                    if kind == "tool"
                    else _text(str(payload))
                )
            else:
                body = _text("")
            return real_dispatch_team_model(
                db, settings, request, messages, tools, choice, transport=Transport(body), **kwargs
            )

        self.monkeypatch.setattr(
            "app.modules.workspace.chat_team_provider.dispatch_team_model", synthetic_dispatch
        )
        runtime.execute_team_turn(self.database.session_factory, claim)
        with self.database.session() as db:
            turn = db.get(ConversationTurn, claim.turn_id)
            texts = [turn.assistant_text or ""] + [
                row.assistant_text or ""
                for row in db.scalars(
                    select(TeamTurnResult)
                    .where(TeamTurnResult.turn_id == turn.id)
                    .order_by(TeamTurnResult.ordinal)
                )
            ]
        return "\n".join(texts)

    def answers(self) -> list[str]:
        with self.database.session() as db:
            return [
                a.answer_text for a in read_attempt_answers(db, self.actor, self.conversation_id)
            ]

    def context(self) -> Any:
        with self.database.session() as db:
            return get_assessment_runtime_context(db, self.actor, self.conversation_id)


PROMPTS = ("请写下你的学号", "请写下你的专业", "你如何理解知行合一", "Q4")


@pytest.fixture()
def quiz(client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any) -> _Harness:
    return _Harness(client, database, app_bundle, monkeypatch, PROMPTS)


@pytest.mark.parametrize("message", ["2330034002", "我的学号是：2330034002"])
def test_student_id_is_recorded_even_when_the_model_says_off_topic(
    quiz: _Harness, message: str
) -> None:
    quiz.send(message, OFF)
    assert quiz.answers() == [message]
    assert quiz.context().progress.resolved_count == 1


def test_major_ai_is_recorded_when_the_model_is_unsure(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    quiz.send("AI", UNSURE)
    assert quiz.answers() == ["2330034002", "AI"]


def test_skip_word_is_a_skip_whatever_the_model_said(quiz: _Harness) -> None:
    quiz.send("跳过", OFF)
    ctx = quiz.context()
    assert ctx.progress.skipped_count == 1 and quiz.answers() == []


def test_unsure_answer_asks_to_confirm_then_records_it(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    quiz.send("人工智能", OFF)
    reply = quiz.send("知行合一就是边做边想", UNSURE)
    assert "输入“确认”" in reply
    assert quiz.answers() == ["2330034002", "人工智能"]
    quiz.send("确认", OFF)
    assert quiz.answers()[-1] == "知行合一就是边做边想"
    assert quiz.context().progress.resolved_count == 3


def test_unsure_then_a_new_reply_is_taken_without_asking_again(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    quiz.send("人工智能", OFF)
    assert "输入“确认”" in quiz.send("边做边想", UNSURE)
    # The student re-enters; the model is unsure again, but we never loop.
    quiz.send("知道了就要去做，做了才算真知道", UNSURE)
    assert quiz.answers()[-1] == "知道了就要去做，做了才算真知道"


def test_clear_answer_is_recorded_directly(quiz: _Harness) -> None:
    quiz.send("2330034002", {"classification": "answer_only", "relevant": True})
    assert quiz.answers() == ["2330034002"]


def test_confirm_without_a_pending_answer_records_nothing(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    quiz.send("人工智能", OFF)
    quiz.send("确认", OFF)
    assert quiz.answers() == ["2330034002", "人工智能"]


def test_student_changes_an_earlier_answer_and_history_is_kept(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    quiz.send("AI", OFF)
    quiz.send("修改第2题：人工智能", OFF)
    ctx = quiz.context()
    assert ctx.progress.resolved_count == 2
    with quiz.database.session() as db:
        rows = db.scalars(
            select(AssessmentAttemptQuestion)
            .where(AssessmentAttemptQuestion.attempt_id == str(ctx.attempt.id))
            .order_by(AssessmentAttemptQuestion.ordinal)
        ).all()
        effective = db.get(LearningRecord, rows[1].effective_answer_record_id)
        assert json.loads(effective.payload_json)["answer_text"] == "人工智能"
    # Old answer kept as history.
    assert "AI" in quiz.answers() and "人工智能" in quiz.answers()
    # The current question is still the third one.
    assert ctx.current_question is not None and "知行合一" in ctx.current_question.prompt


def test_change_request_without_an_answer_says_how(quiz: _Harness) -> None:
    quiz.send("2330034002", OFF)
    reply = quiz.send("修改第1题", OFF)
    assert "修改第1题：新答案" in reply
    assert quiz.answers() == ["2330034002"]


# --- Relevance guard v2 (owner design 2026-10-20 evening) -------------------
# The model only reports category + confidence; the program decides.

SURE_OFF = {"classification": "off_topic", "category": "off_topic", "confidence": 0.95}
WEAK_OFF = {"classification": "off_topic", "category": "off_topic", "confidence": 0.7}
SURE_ANSWER = {"classification": "answer_only", "category": "answer", "confidence": 0.9}
OTHER = {"classification": "off_topic", "category": "other", "confidence": 0.8}


def _to_q3(quiz: _Harness) -> None:
    quiz.send("2330034002", SURE_OFF)
    quiz.send("人工智能", SURE_OFF)
    assert quiz.answers() == ["2330034002", "人工智能"]


def _guard_state(quiz: _Harness) -> dict[str, Any]:
    ctx = quiz.context()
    with quiz.database.session() as db:
        row = db.scalar(
            select(AssessmentAttemptQuestion).where(
                AssessmentAttemptQuestion.attempt_id == str(ctx.attempt.id),
                AssessmentAttemptQuestion.question_version_id
                == str(ctx.current_question.question_version_id),
            )
        )
        return json.loads(row.guard_state_json or "{}")


def test_chenshaoyan_id_and_major_recorded_even_when_model_is_sure_off_topic(
    quiz: _Harness,
) -> None:
    _to_q3(quiz)
    assert quiz.context().progress.resolved_count == 2


def test_rule1_only_sure_off_topic_is_judged_directly(quiz: _Harness) -> None:
    _to_q3(quiz)
    reply = quiz.send("今天中午吃什么", SURE_OFF)
    assert "输入“确认”" not in reply
    assert quiz.answers() == ["2330034002", "人工智能"]
    assert _guard_state(quiz)["off_topic_judged"] is True


def test_rule1_unsure_off_topic_asks_to_confirm(quiz: _Harness) -> None:
    _to_q3(quiz)
    assert "输入“确认”" in quiz.send("心里有数才能做好", WEAK_OFF)
    assert quiz.answers() == ["2330034002", "人工智能"]
    state = _guard_state(quiz)
    assert state["pending_text"] == "心里有数才能做好" and state["off_topic_judged"] is False


def test_rule2_after_off_topic_a_statement_cannot_be_off_topic_again(quiz: _Harness) -> None:
    _to_q3(quiz)
    quiz.send("今天中午吃什么", SURE_OFF)
    # The model insists off_topic with high confidence; the program refuses.
    quiz.send("知行合一就是知道和做到要统一", SURE_OFF)
    assert quiz.answers()[-1] == "知行合一就是知道和做到要统一"
    assert quiz.context().progress.resolved_count == 3


def test_rule2_after_off_topic_a_question_back_asks_to_confirm_then_records(
    quiz: _Harness,
) -> None:
    _to_q3(quiz)
    quiz.send("今天中午吃什么", SURE_OFF)
    reply = quiz.send("是不是说要边学边做？", SURE_OFF)
    assert "输入“确认”" in reply
    assert len(quiz.answers()) == 2
    quiz.send("确认", SURE_OFF)
    assert quiz.answers()[-1] == "是不是说要边学边做？"


def test_rule3_same_reply_again_is_recorded_whatever_the_model_says(quiz: _Harness) -> None:
    _to_q3(quiz)
    quiz.send("今天中午吃什么", SURE_OFF)
    quiz.send("今天中午吃什么。", SURE_OFF)
    assert quiz.answers()[-1] == "今天中午吃什么。"


def test_rule3_near_duplicate_after_a_question_back(quiz: _Harness) -> None:
    _to_q3(quiz)
    quiz.send("这是什么意思？", OTHER)
    quiz.send("这是什么意思?", OTHER)
    assert quiz.answers()[-1] == "这是什么意思?"


def test_rule4_confirm_records_the_pending_reply_from_server_state(quiz: _Harness) -> None:
    _to_q3(quiz)
    quiz.send("边做边想", WEAK_OFF)
    assert _guard_state(quiz)["pending_text"] == "边做边想"
    quiz.send("确认", SURE_OFF)
    assert quiz.answers()[-1] == "边做边想"


def test_rule5_never_stuck_on_one_question(quiz: _Harness) -> None:
    _to_q3(quiz)
    replies = ["吃饭了吗", "我觉得是实践", "反正就是要做"]
    for message in replies:
        quiz.send(message, SURE_OFF)
    # Two inputs at most before the question is recorded.
    assert quiz.answers()[2] == "我觉得是实践"
    assert quiz.context().progress.resolved_count >= 3


def test_sure_answer_is_recorded_directly(quiz: _Harness) -> None:
    _to_q3(quiz)
    reply = quiz.send("知行合一是王阳明的主张", SURE_ANSWER)
    assert "输入“确认”" not in reply
    assert quiz.answers()[-1] == "知行合一是王阳明的主张"


def test_guard_rule_units() -> None:
    from app.modules.learning.answer_guard import GuardState, decide, nearly_same

    assert nearly_same("2330034002", " 2330034002。")
    assert nearly_same("知行合一就是边做边想", "知行合一就是边做边想吧")
    assert not nearly_same("A", "B")
    fresh = GuardState()
    assert decide(fresh, "吃饭", category="off_topic", confidence=0.95, statement=True) == (
        "off_topic"
    )
    assert decide(fresh, "吃饭", category="off_topic", confidence=0.89, statement=True) == (
        "confirm"
    )
    judged = GuardState(off_topic_judged=True)
    assert decide(judged, "吃饭", category="off_topic", confidence=1.0, statement=True) == (
        "record"
    )
    assert decide(judged, "为什么？", category="off_topic", confidence=1.0, statement=False) == (
        "other_confirm"
    )
    assert GuardState.load("not json") == GuardState()
    assert GuardState.load(GuardState(pending_text="x").dump()).pending_text == "x"


def test_completed_attempt_answers_are_not_rescored(quiz: _Harness) -> None:
    _to_q3(quiz)
    quiz.send("结束测试", {"classification": "complete_request"})
    before = quiz.answers()
    reply = quiz.send("修改第1题：2330034003", SURE_OFF)
    assert quiz.answers() == before
    assert "2330034003" not in quiz.answers()
    assert reply
