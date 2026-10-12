from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.modules.learning.schemas import AssessmentRuntimeResult
from app.modules.workspace.chat_provider import assessment_safe_reply_text, prefers_chinese


def _result(response_key: str, disposition: str, **context: Any) -> AssessmentRuntimeResult:
    attempt_id = uuid4()
    return AssessmentRuntimeResult.model_validate(
        {
            "disposition": disposition,
            "response_key": response_key,
            "context": {
                "attempt": {
                    "id": attempt_id,
                    "activity_id": uuid4(),
                    "conversation_id": uuid4(),
                    "chat_visibility": "private",
                    "status": context.get("status", "in_progress"),
                    "revision": 1,
                },
                "progress": {
                    "attempt_id": attempt_id,
                    "status": context.get("status", "in_progress"),
                    "question_count": 3,
                    "presented_count": 2,
                    "resolved_count": 1,
                    "answered_count": 1,
                    "skipped_count": 0,
                },
                "current_question": {
                    "ordinal": 1,
                    "question_version_id": uuid4(),
                    "prompt": "What is aporia?",
                },
                "canonical_conversation_id": uuid4(),
                "redirect_to_original_conversation": context.get("redirect", False),
            },
        }
    )


def test_reply_language_follows_the_conversation_not_one_command() -> None:
    assert prefers_chinese(["hello", "开始测试"]) is False
    assert prefers_chinese(["你好", "start test"]) is True
    assert prefers_chinese(["hello", "开始测试", "答案是苏格拉底"]) is True
    assert prefers_chinese(["?", "👍"]) is False


def test_progress_reply_keeps_member_help_then_restates_the_current_question() -> None:
    text = assessment_safe_reply_text(
        _result("assessment.progress", "read"),
        ["hello", "How should I format my answer?"],
        prose="One or two sentences is enough.",
    )
    assert text == (
        "One or two sentences is enough.\n\nProgress:\n\n"
        "Resolved 1/3; answered 1, skipped 0.\n\nQuestion 2: What is aporia?"
    )


def test_restricted_request_is_refused_and_ordinary_redirect_continues() -> None:
    refused = assessment_safe_reply_text(_result("assessment.redirect", "read"), ["你好"])
    assert refused.startswith("测试进行中，不能提供答案、提示或评判。")
    assert refused.endswith("第 2 题：What is aporia?")
    resumed = assessment_safe_reply_text(_result("assessment.redirect", "redirected"), ["hi"])
    assert resumed.startswith("Let's continue the test.")
    moved = assessment_safe_reply_text(
        _result("assessment.redirect", "redirected", redirect=True), ["hi"]
    )
    assert moved.startswith("Continue this test in its original chat.")


def test_completion_and_follow_up_wording() -> None:
    done = assessment_safe_reply_text(
        _result("assessment.completed", "transitioned", status="completed").model_copy(
            update={
                "context": _result("assessment.completed", "transitioned").context.model_copy(
                    update={"current_question": None}
                )
            }
        ),
        ["开始测试"],
    )
    assert (
        done == "测试结束，恭喜完成！作答记录已保存。你可以继续聊天，之后的对话不会计入这次测试。"
    )
    follow_up = assessment_safe_reply_text(
        _result("assessment.answer_recorded", "recorded"), ["hello"], follow_up=True
    )
    assert follow_up == (
        "Answer saved.\n\nNext, a follow-up question.\n\nQuestion 2: What is aporia?"
    )
