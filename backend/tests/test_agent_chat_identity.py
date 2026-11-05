"""An Agent or Team member speaks only from its own AGENT.md.

Prod (2026-11-05): a teacher said 你好 to a plain "Nikola Tesla" Agent and
got "你好！我是你的教学助手……查看课程中的测验、作业或学习记录". The one-to-one
Chat prompt opened with a fixed "selected educational Agent" identity, added a
teacher-tools paragraph for teachers, and offered every course test and
record Tool. The model took that role instead of its AGENT.md. These tests
read the exact bytes sent to the model.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from app.core.db import Database
from app.core.models import AgentVersion
from app.modules.runtime_tools.builtin import ASSESSMENT_TOOL_NAMES
from fastapi.testclient import TestClient

from tests.conftest import login
from tests.test_agent_chat_attachments_reports import _real_provider, _reply, _send, _wire
from tests.test_mayaform_team_conversations import (
    BOWEN_ID,
    MAYA_ID,
    _create,
    _make_agent_version,
)
from tests.test_team_no_assessment_prompt import ASSESSMENT_WORDS, INFORMAL_RULESET, _team_chat
from tests.test_team_no_assessment_prompt import _send as _send_team

TESLA_MD = (
    "# Nikola Tesla\n\nI am Nikola Tesla, inventor of alternating current systems. "
    "I speak in the first person about electricity, invention and my own life."
)
OTHER_MD = "# Marie Curie\n\nI am Marie Curie. I talk about radioactivity."
# A generic role or course-tool framing in place of the Agent's own identity.
ROLE_TEMPLATE = re.compile(
    r"educational Agent|teaching assistant|tutor\b(?! or course tool)|teacher tools|"
    r"教学助手|助教|quiz|homework|assignment|测验|作业",
    re.IGNORECASE,
)
# The Team regex less "question": the language rule speaks of "the actual question".
COURSE_TOOL_WORDS = re.compile(ASSESSMENT_WORDS.pattern.removesuffix("|question"), re.IGNORECASE)


def _tesla_chat(database: Database, client: TestClient, username: str) -> tuple[str, str]:
    owner = MAYA_ID if username == "maya" else BOWEN_ID
    _, version_id = _make_agent_version(database, owner_id=owner, name="Nikola Tesla")
    _, other_version_id = _make_agent_version(database, owner_id=owner, name="Marie Curie")
    with database.session() as db:
        for key, markdown in ((version_id, TESLA_MD), (other_version_id, OTHER_MD)):
            version = db.get(AgentVersion, key)
            assert version is not None
            version.agent_md = markdown
    _, csrf = login(client, username)
    session = _create(client, csrf, {"kind": "agent", "version_id": version_id})
    assert session["entry_kind"] == "agent"
    return session["id"], csrf


@pytest.mark.parametrize("username", ["maya", "bowen"])
def test_agent_chat_sends_only_the_agents_own_identity(
    client: TestClient, database: Database, app_bundle: Any, monkeypatch: Any, username: str
) -> None:
    client.headers["Origin"] = "http://testserver"
    transport = _real_provider(app_bundle, monkeypatch, [_reply("你好，我是特斯拉。")])
    conversation_id, csrf = _tesla_chat(database, client, username)

    response = _send(client, csrf, conversation_id, "你好")

    assert response.status_code == 200, response.text
    assert response.json()["turns"][-1]["state"] == "ready"
    assert transport.call_count == 1
    body = _wire(transport.call_args)
    system = body["messages"][0]
    assert system["role"] == "system"
    text = system["content"]
    assert text.startswith("You are Nikola Tesla, the Agent defined by agent_markdown")
    rules, context = text.split("\n", 1)
    assert json.loads(context)["agent_markdown"] == TESLA_MD
    assert ROLE_TEMPLATE.search(text) is None, ROLE_TEMPLATE.search(text)
    assert COURSE_TOOL_WORDS.search(rules) is None, COURSE_TOOL_WORDS.search(rules)
    assert "course teacher" not in text
    # Nothing from another Agent reaches this one.
    wire = json.dumps(body, ensure_ascii=False)
    assert "Marie Curie" not in wire and "radioactivity" not in wire
    assert [item["role"] for item in body["messages"]] == ["system", "user"]
    assert body["messages"][1]["content"] == "你好"
    offered = {tool["function"]["name"] for tool in body.get("tools", [])}
    assert not offered & ASSESSMENT_TOOL_NAMES
    assert {"read_agent_memory", "write_agent_memory"} <= offered
    assert ("generate_agent_knowledge" in offered) is (username == "maya")


@pytest.mark.parametrize("as_student", [False, True])
def test_team_member_prompt_holds_only_its_own_agent_md(
    app_bundle: Any, client: TestClient, database: Any, monkeypatch: Any, as_student: bool
) -> None:
    session, csrf = _team_chat(
        client,
        database,
        "# Leader\n\nGive the big picture.\n\n" + INFORMAL_RULESET,
        as_student=as_student,
    )
    seen, _turn_id = _send_team(client, session, csrf, monkeypatch)
    assert len(seen) == 2
    with database.session() as db:
        markdown = {
            request.speaker_name: db.get(AgentVersion, request.agent_version_id).agent_md
            for request in seen
        }
    for request in seen:
        others = [name for name in markdown if name != request.speaker_name]
        assert f"<agent_instructions>\n{markdown[request.speaker_name]}\n" in (
            request.system_message
        )
        for name in others:
            assert markdown[name] not in request.system_message
            assert f"You are {name}." not in request.system_message
        assert ROLE_TEMPLATE.search(request.system_message) is None, request.speaker_name
        assert ASSESSMENT_WORDS.search(request.system_message) is None
