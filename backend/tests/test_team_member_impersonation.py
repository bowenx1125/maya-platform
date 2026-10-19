"""A Team member speaks only as itself (bug 2026-10-19, chat 9689e727).

Every teammate's earlier reply went to the model as role=assistant with a
`名字: ` prefix (Chinese names cannot ride in the name field). The model read
them as its own writing: the leader 小爱鉴定师 opened with `小爱鉴定师:` and
then wrote as 读心师 and the others until it stopped mid-sentence. Now only
the member's own replies are assistant messages; teammates' replies are
labeled system-role narration, the system line says to write only as itself,
and a reply is stripped of lines written as a teammate before it is saved.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.learning.attempts import start_or_resume_attempt
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.formal_assessment import ALL_DONE_GUIDE, RECORDED_FACT
from app.modules.workspace.models import ConversationParticipant, TeamTurnResult
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.conftest import post_message
from tests.test_formal_assessment_micro_rounds import (
    _dashscope,
    _grant,
    _run,
    _texts,
)
from tests.test_mayaform_assessment_attempts import (
    STUDENT_ID,
    _create_formal_conversation,
    _service_actor,
)
from tests.test_mayaform_team_conversations import _headers
from tests.test_mayaform_team_turns import _body, _chat

TEAM = ["小爱鉴定师", "读心师", "预警官", "军师", "报告官"]


def _names(database: Any, conversation_id: str) -> dict[str, str]:
    with database.session() as db:
        return {
            row.id: row.display_name
            for row in db.scalars(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id
                )
            )
        }


def _strip(text: str, own: str = "小爱鉴定师") -> str:
    return runtime.strip_impersonation(text, own, TEAM)


def test_strip_keeps_a_clean_reply_byte_for_byte() -> None:
    text = "先说结论：这段关系值得继续。\n\n- 读心师会补充细节 @读心师\n\n军师说过的话不是行首。"
    assert _strip(text) == text


def test_strip_drops_the_prod_shape_written_as_every_member() -> None:
    text = (
        "小爱鉴定师: 记录我读完了。先说第一印象。\n"
        "- 想要一份报告 → @报告官\n"
        "读心师: 我把镜头对准「人」——先看你自己。\n"
        "依恋类型：回避型。\n\n"
        "预警官：我来看风险。\n"
        "**军师**：下一步这样做。\n"
        "【报告官】: 报告见下。"
    )
    assert _strip(text) == "记录我读完了。先说第一印象。\n- 想要一份报告 → @报告官"


def test_strip_resumes_at_the_members_own_name_and_handles_full_width_and_bold() -> None:
    text = "读心师：我替读心师说一句。\n**小爱鉴定师**：回到我自己。\n我的第二行。"
    assert _strip(text) == "回到我自己。\n我的第二行。"
    assert _strip("小爱鉴定师：你好") == "你好"
    assert _strip("Scorer: hi", own="Scorer") == "hi"
    # Only teammates count: a name outside the Team is ordinary text.
    assert _strip("老师: 这是引用") == "老师: 这是引用"


def test_strip_of_only_teammate_lines_is_empty() -> None:
    assert _strip("读心师: 全是别人的话\n第二行") == ""


def test_identity_line_says_to_write_only_as_itself() -> None:
    system = runtime._member_system("# Member\n\nSpeak.", "{}", speaker_name="读心师")
    assert "Write only 读心师's own reply" in system
    assert "never start a line with another member's name and a colon" in system
    assert "[队友 … 的发言]" in system


def test_history_sends_only_own_replies_as_assistant(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    names = _names(database, session["id"])
    seen: list[runtime.MemberRequest] = []

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        seen.append(request)
        return runtime.MemberReply(f"answer of {request.participant_id}")

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    first = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=ids[1:])
    )
    assert first.status_code == 200, first.text
    followup = {**_body(first.json(), "selected", ids=[ids[1]]), "message": "Again"}
    second = post_message(client, url, headers=_headers(csrf), json=followup)
    assert second.status_code == 200, second.text

    history = seen[-1].history
    assert seen[-1].participant_id == ids[1]
    assistant = [item for item in history if item["role"] == "assistant"]
    assert assistant == [
        {
            "role": "assistant",
            "name": runtime.history_speaker_name(names[ids[1]], ids[1]),
            "content": f"answer of {ids[1]}",
        }
    ]
    assert {
        "role": "system",
        "content": f"[队友 {names[ids[2]]} 的发言]\nanswer of {ids[2]}",
    } in history
    # The student's own words stay the only user messages.
    assert [item["content"] for item in history if item["role"] == "user"] == [
        _body(session, "selected")["message"]
    ]
    # No prefixed copy of anyone's reply is left in the model's own voice.
    assert not any(item["content"].startswith(f"{names[ids[2]]}:") for item in history)

    with database.session() as db:
        audit = runtime.team_history(db, session["id"], 10**6)
    assert all(item["role"] != "assistant" for item in audit)


def test_a_reply_written_as_a_teammate_is_stripped_before_saving(
    client: TestClient, database: Any, monkeypatch: Any
) -> None:
    session, csrf, _actor = _chat(client, database)
    ids = [member["id"] for member in session["team"]["members"]]
    names = _names(database, session["id"])

    def reply(request: runtime.MemberRequest) -> runtime.MemberReply:
        return runtime.MemberReply(
            f"{names[ids[1]]}: my part\n{names[ids[2]]}：their part\nmore of theirs"
        )

    monkeypatch.setattr(runtime, "invoke_mock_member", reply)
    url = f"/api/v1/conversations/{session['id']}/messages"
    sent = post_message(
        client, url, headers=_headers(csrf), json=_body(session, "selected", ids=[ids[1]])
    )
    assert sent.status_code == 200, sent.text
    with database.session() as db:
        text = db.scalar(
            select(TeamTurnResult.assistant_text).where(TeamTurnResult.participant_id == ids[1])
        )
    assert text == "my part"


def test_assessment_scorer_sees_the_guide_as_narration_and_scoring_completes(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any
) -> None:
    """The formal flow is unchanged; the Scorer reads the Guide as a teammate."""

    del client
    _app, _database, settings = app_bundle
    with database.session() as db:
        ensure_demo_baseline(db, settings.resolved_data_root)
        conversation_id, *_rest = _create_formal_conversation(
            db, visibility="private", prompts=("甲题", "乙题")
        )
        db.commit()
        actor = _service_actor(db, settings, STUDENT_ID)
        assert start_or_resume_attempt(db, actor, conversation_id, client_event_id=uuid4())
        db.commit()
        names = {
            row.id: row.display_name
            for row in db.scalars(
                select(ConversationParticipant).where(
                    ConversationParticipant.conversation_id == conversation_id
                )
            )
        }
    settings, policy = _dashscope(app_bundle, database, "impersonation-formal")
    _grant(database, conversation_id, policy)

    histories: list[tuple[str, tuple[dict[str, str], ...]]] = []
    original = runtime._start_member

    def recording_start(*args: Any, **kwargs: Any) -> Any:
        request = original(*args, **kwargs)
        if request is not None:
            histories.append((request.participant_id, request.history))
        return request

    monkeypatch.setattr(runtime, "_start_member", recording_start)

    opening = _run(database, settings, actor, conversation_id, "开始", monkeypatch, [])
    assert _texts(database, opening) == ["收到，第一题是甲题"]
    first = _run(
        database,
        settings,
        actor,
        conversation_id,
        "甲题的回答",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "甲题的回答"},
            ),
            ("text", "已记录你的回答。"),
        ],
    )
    first_text = _texts(database, first)
    assert first_text[0] == RECORDED_FACT
    assert "乙题" in (first_text[1] or "")
    done = _run(
        database,
        settings,
        actor,
        conversation_id,
        "乙题的回答",
        monkeypatch,
        [
            (
                "tool",
                "assessment_action",
                {"classification": "answer_only", "relevant": True, "answer_span": "乙题的回答"},
            ),
            ("text", "已记录。"),
        ],
    )
    done_text = _texts(database, done)
    assert done_text[0] == RECORDED_FACT
    assert done_text[1] == ALL_DONE_GUIDE

    # Every member saw only its own replies as assistant; the Guide's
    # question reached the others as labeled narration.
    assert histories
    for participant_id, history in histories:
        for item in history:
            if item["role"] == "assistant":
                assert item["name"] == runtime.history_speaker_name(
                    names[participant_id], participant_id
                )
            assert not item["content"].startswith(
                tuple(f"{name}: " for pid, name in names.items() if pid != participant_id)
            )
    narrated = [
        item["content"]
        for _pid, history in histories
        for item in history
        if item["role"] == "system" and item["content"].startswith("[队友 ")
    ]
    assert any("收到，第一题是甲题" in content for content in narrated)
