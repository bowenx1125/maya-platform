"""A Team member's unreadable Tool arguments end in one or three calls, not twelve.

Bug (2026-10-18, prod turn cbda99bb): "@报告官 按聊天记录生成完整的HTML鉴定报告"
took 171 s, 12 sequential model calls and 239 write statements and still
produced no report. Every create_chat_html_report call was cut at the
1,510-token output cap mid-string; DashScope still said
``finish_reason: "tool_calls"``, the SDK replied "Error while decoding function
arguments … retry", and the model sent the same long call again, the prompt
growing each time (9.5k -> 24k tokens).
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from agno.models.message import Message
from app.core.models import AgentVersion
from app.modules.auth.service import get_auth_context
from app.modules.demo_baseline.service import ensure_demo_baseline
from app.modules.provider_disclosure.team_standing import (
    confirm_team_standing_grant,
    prepare_team_standing_grant,
)
from app.modules.workspace import team_runtime as runtime
from app.modules.workspace.chat_reports import CHAT_REPORT_TOOL
from app.modules.workspace.chat_team_provider import (
    tool_arguments_decode,
    without_repeatedly_malformed_tool,
)
from app.modules.workspace.models import (
    ChatReport,
    Conversation,
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from tests.test_mayaform_assessment_attempts import _login
from tests.test_mayaform_team_conversations import _create
from tests.test_mayaform_teams import COURSE_ID, MAYA_ID, _headers, _make_agent_version
from tests.test_wave4_provider_preflight import _digest, _policy

REPORT = {
    "title": "她爱我吗？· 关系鉴定报告",
    "summary": "友好但不推进。",
    "sections": [{"heading": "整体", "body": "她主动开话题 2 次。"}],
}
# Exactly how prod's arguments ended: an open string, no closing braces.
CUT = (
    '{"arguments": {"title": "她爱我吗？· 关系鉴定报告", "summary": "28 天里你发起 11 条、她发 6 条'
)
# Prod: one simulated provider call; the real ones took 15-24 s each.
CALL_DELAY_S = 0.02


def _tool_body(call_id: str, arguments: str, completion_tokens: int) -> bytes:
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
                                "function": {"name": CHAT_REPORT_TOOL, "arguments": arguments},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 9000, "completion_tokens": completion_tokens},
        }
    ).encode()


def _text_body(content: str) -> bytes:
    return json.dumps(
        {
            "choices": [
                {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 9000, "completion_tokens": 40},
        }
    ).encode()


def _report_member_turn(client: TestClient, database: Any, app_bundle: Any) -> tuple[Any, Any, str]:
    app, _database, base_settings = app_bundle
    _teacher_token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
    version_ids: list[str] = []
    for name in ("小爱鉴定师", "报告官"):
        _agent_id, version_id = _make_agent_version(
            database, owner_id=MAYA_ID, name=name, visibility="public"
        )
        with database.session() as db:
            version = db.get(AgentVersion, version_id)
            version.agent_md = f"# {name}\n\n只说自己的模块。"
            version.avatar_config_json = json.dumps(
                {
                    "template_id": "synthetic",
                    "material_theme": "default",
                    "default_expression": "neutral",
                    "expression_strength": "low",
                    "motion_style": "calm",
                }
            )
        version_ids.append(version_id)
    team = client.post(
        f"/api/v1/courses/{COURSE_ID}/teams",
        headers=_headers(teacher_csrf, f"slm-{uuid4()}"),
        json={
            "display_name": "issheloveme",
            "visibility": "public",
            "members": [
                {"agent_version_id": v, "is_leader": i == 0, "position": i}
                for i, v in enumerate(version_ids)
            ],
        },
    )
    assert team.status_code == 201, team.text
    student_token, student_csrf = _login(client, "bowen")
    session = _create(client, student_csrf, {"kind": "maya_team", "team_id": team.json()["id"]})
    conversation_id = session["id"]
    with database.session() as db:
        actor = get_auth_context(db, base_settings, student_token)
    settings = base_settings.model_copy(
        update={
            "llm_provider": "dashscope",
            "dashscope_api_key": "synthetic-key",
            "dashscope_workspace_id": "synthetic-workspace",
            "dashscope_region": "cn-beijing",
        }
    )
    policy = _policy(
        policy_id="slm-report",
        endpoint=DashScopeLLMConfig(
            api_key="synthetic-key",
            workspace_id="synthetic-workspace",
            region="cn-beijing",
            model_key=settings.llm_model,
            policy_hash=_digest("slm-report-policy"),
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
        reporter = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(False),
            )
        )
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="@报告官 按聊天记录生成完整的HTML鉴定报告",
            routing=TeamRouting(mode="selected", participant_ids=[UUID(reporter.id)]),
            actor_context=actor,
        )
    return claim, settings, conversation_id


@pytest.mark.parametrize("scenario", ["cut_at_cap", "unreadable", "one_correction"])
def test_unreadable_report_arguments_do_not_loop(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any, scenario: str
) -> None:
    claim, _settings, conversation_id = _report_member_turn(client, database, app_bundle)
    requests: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        def __init__(self, content: bytes) -> None:
            self.content = content

    class Transport:
        @staticmethod
        def timeout() -> float:
            return 30.0

        def post_bytes(self, _endpoint: str, *, content: bytes, **_kwargs: Any) -> Any:
            body = json.loads(content)
            requests.append(body)
            time.sleep(CALL_DELAY_S)
            index = len(requests) - 1
            offered = {
                tool["function"]["name"] for tool in body.get("tools") or [] if "function" in tool
            }
            cap = body.get("max_tokens")
            if CHAT_REPORT_TOOL not in offered or index >= 11:
                return Response(_text_body("报告没生成成功，我如实说明情况。"))
            if scenario == "one_correction" and index == 1:
                return Response(_tool_body(f"call-{index}", json.dumps({"arguments": REPORT}), 120))
            if scenario == "one_correction" and index >= 2:
                return Response(_text_body("报告已生成。"))
            # cut_at_cap: completion tokens == the cap the request sent.
            tokens = cap if scenario == "cut_at_cap" and isinstance(cap, int) else 60
            return Response(_tool_body(f"call-{index}", CUT, tokens))

    monkeypatch.setattr("app.modules.workspace.chat_team_provider.HttpxLLMTransport", Transport)
    # Same rule as message_timing's db_writes (every non-SELECT statement),
    # plus the INSERT/UPDATE/DELETE subset.
    writes = {"statements": 0, "dml": 0}

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        head = statement.lstrip()[:6].upper()
        if not head.startswith("SELECT"):
            writes["statements"] += 1
        if head in {"INSERT", "UPDATE", "DELETE"}:
            writes["dml"] += 1

    event.listen(database.engine, "before_cursor_execute", count)
    started = time.perf_counter()
    try:
        runtime.execute_team_turn(database.session_factory, claim)
    finally:
        event.remove(database.engine, "before_cursor_execute", count)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(
        f"MEASURE scenario={scenario} model_calls={len(requests)} "
        f"write_statements={writes['statements']} dml={writes['dml']} wall_ms={elapsed_ms:.0f} "
        f"last_prompt_chars={len(json.dumps(requests[-1]['messages'], ensure_ascii=False))}"
    )
    with database.session() as db:
        turn = db.get(ConversationTurn, claim.turn_id)
        [result] = db.scalars(select(TeamTurnResult).where(TeamTurnResult.turn_id == turn.id))
        reports = db.scalar(
            select(func.count())
            .select_from(ChatReport)
            .where(ChatReport.conversation_id == conversation_id)
        )
    if scenario == "cut_at_cap":
        if not isinstance(requests[0].get("max_tokens"), int):
            pytest.skip("Team requests send no output cap; nothing can be cut at one")
        # A cut call is a truncation, failed visibly like a cut reply.
        assert len(requests) == 1
        assert (result.state, result.safe_error_code) == ("failed", "team_response_truncated")
        assert reports == 0
    elif scenario == "unreadable":
        # Two unreadable calls, then the Tool is gone and the member replies.
        assert len(requests) == 3
        assert CHAT_REPORT_TOOL in {t["function"]["name"] for t in requests[1]["tools"]}
        assert CHAT_REPORT_TOOL not in {
            t["function"]["name"] for t in requests[2].get("tools") or []
        }
        assert result.state == "ready"
        assert "报告没生成成功" in (result.assistant_text or "")
        assert reports == 0
    else:
        # One correction is still allowed and the report is saved.
        assert len(requests) == 3
        assert result.state == "ready"
        assert reports == 1


def _assistant_call(arguments: str, name: str = CHAT_REPORT_TOOL) -> Message:
    return Message(
        role="assistant",
        tool_calls=[
            {
                "id": str(uuid4()),
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


TOOLS = [
    {"type": "function", "function": {"name": CHAT_REPORT_TOOL}},
    {"type": "function", "function": {"name": "read_session"}},
]


def test_the_guard_counts_only_unreadable_calls_in_a_row() -> None:
    assert not tool_arguments_decode(CUT)
    assert tool_arguments_decode(json.dumps({"arguments": REPORT}))
    assert tool_arguments_decode("{'a': 1}")  # the SDK reads Python literals too
    error = Message(role="tool", tool_call_id="x", content="Error while decoding")
    once = [Message(role="user", content="hi"), _assistant_call(CUT), error]
    assert without_repeatedly_malformed_tool(once, TOOLS) == TOOLS
    twice = [*once, _assistant_call(CUT), error]
    assert without_repeatedly_malformed_tool(twice, TOOLS) == [TOOLS[1]]
    # A forced Tool (assessment executor) keeps its own retry rule.
    assert without_repeatedly_malformed_tool(twice, TOOLS, keep=CHAT_REPORT_TOOL) == TOOLS
    # A readable call in between resets the streak.
    broken = [*once, _assistant_call(json.dumps({"arguments": REPORT})), error]
    assert without_repeatedly_malformed_tool([*broken, _assistant_call(CUT)], TOOLS) == TOOLS
    # Different Tools do not add up.
    mixed = [*once, _assistant_call("{", name="read_session"), error]
    assert without_repeatedly_malformed_tool(mixed, TOOLS) == TOOLS
    # Withdrawing the last Tool sends no Tools at all, not an empty list.
    only = [TOOLS[0]]
    assert without_repeatedly_malformed_tool(twice, only) is None
