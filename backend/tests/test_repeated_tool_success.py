"""A Leader that repeats a successful Tool call is not answered with a refusal."""

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
    ConversationParticipant,
    ConversationTurn,
    TeamTurnResult,
)
from app.modules.workspace.schemas import TeamRouting
from app.providers.control_repository import ProviderRepository
from app.providers.llm_adapter import DashScopeLLMConfig
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_mayaform_assessment_attempts import _login
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


MARKDOWN = """# Pre-class Form A

## Questions

### Question 1

Socrates said, "I do not know, and do not think I know." Which reading fits?

- A. Doubt only
- B. Testing views by questioning

#### Rubric

- **Correct choice** (1): 1 point for B.
Total: 1 points

#### Reference answer

B.

### Question 2

About question 1: why did you choose your answer?

#### Rubric

- **Follow-up for Question 1; at most 3** (0): Record the reasoning.
Total: 0 points
"""


@pytest.mark.parametrize("scenario", ["read_twice", "read_twice_then_start", "cut_off", "practice"])
# Bug (2026-10-13): "Take the test" was answered "Can't." because the Leader
# read its session twice with the same successful result. A repeated success
# is not a refusal: the next step goes without that Tool.
def test_a_repeated_successful_read_does_not_refuse_the_test(
    client: TestClient, database: Any, app_bundle: Any, monkeypatch: Any, scenario: str
) -> None:
    app, _database, base_settings = app_bundle
    _teacher_token, teacher_csrf = _login(client, "maya")
    with database.session() as db:
        ensure_demo_baseline(db, base_settings.resolved_data_root)
    created_set = client.post(
        f"/api/v1/courses/{COURSE_ID}/knowledge-sets",
        headers=_headers(teacher_csrf, f"repro-set-{uuid4()}"),
        json={"display_name": "Form A"},
    )
    assert created_set.status_code == 201, created_set.text
    set_id = created_set.json()["id"]
    saved = client.put(
        f"/api/v1/knowledge-sets/{set_id}/markdown",
        headers=_headers(teacher_csrf, f"repro-save-{uuid4()}"),
        json={"expected_version_seq": 0, "markdown": MARKDOWN},
    )
    assert saved.status_code == 200, saved.text
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
        leader = db.scalar(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.is_leader.is_(True),
            )
        )
        claim = runtime.claim_team_turn(
            db,
            settings,
            conversation_id=conversation_id,
            actor_id=actor.user.id,
            request_id=str(uuid4()),
            expected_revision=conversation.revision,
            message="Take the test",
            routing=TeamRouting(mode="auto"),
            actor_context=actor,
        )

    start = {"classification": "start_request", "reply_language": "en"}
    script = (
        [("cut", "**第 6 题**\n\n1 = 非常不同意　5 =")]
        if scenario == "cut_off"
        else [("text", "Let's practise.")]
        if scenario == "practice"
        else [("tool", "read_session", {}), ("tool", "read_session", {})]
        + ([("tool", "assessment_action", start)] if scenario == "read_twice_then_start" else [])
        + [("text", "Let's begin.")]
    )
    calls: dict[str, int] = defaultdict(int)
    prompts: list[str] = []

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
        prompts.append("\n".join(str(message.content or "") for message in messages))
        ordinal = calls[request.result_id]
        calls[request.result_id] += 1
        if request.participant_id != leader.id:
            body = _text("member prose")
        elif ordinal < len(script):
            kind, *rest = script[ordinal]
            if kind == "cut":
                # The provider stopped at its output limit mid-sentence.
                payload = json.loads(_text(rest[0]))
                payload["choices"][0]["finish_reason"] = "length"
                body = json.dumps(payload).encode()
            elif kind == "text":
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
        results = db.scalars(select(TeamTurnResult).where(TeamTurnResult.turn_id == turn.id)).all()
        if scenario == "practice":
            # Bug (2026-10-13): with the question bank in its prompt, the
            # Leader faked a formal test and showed Question 1 twice. In a
            # Team that runs assessments only the server shows Questions.
            assert prompts
            assert all("Testing views by questioning" not in prompt for prompt in prompts)
            assert all("Socrates said" not in prompt for prompt in prompts)
            return
        if scenario == "cut_off":
            # Bug (2026-10-13): a cut reply showed half a question. It now
            # fails visibly, so the student sends again.
            [result] = results
            assert (result.state, result.safe_error_code) == (
                "failed",
                "team_response_truncated",
            )
            assert result.assistant_text is None
            return
        assert turn.state == "ready"
        [result] = results
        assert result.assistant_text != "Can't."
        if scenario == "read_twice_then_start":
            # The Tool start used to keep the safe "Formal test started." line
            # and would have left any delegated member prose in place. The
            # opening is the Guide's scripted line.
            assert result.assistant_text.startswith("收到，第一题是")
            assert "Formal test started." not in (result.assistant_text or "")
            assert get_assessment_runtime_context(db, actor, conversation_id) is not None
        else:
            assert result.assistant_text == "Let's begin."
