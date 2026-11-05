"""Ordinary single-Agent chat must not carry assessment prompt text or Tools.

Owner report (2026-11-04 JST): chatting with a free persona Agent "Nikola Tesla"
answered 你好 as「我是你的教学助手…查看课程中的测验、作业或学习记录」. The
single-Agent system prompt always used ACCOUNT_MEMORY_RULE (formal test /
assessment tools wording) and exposed every assessment Tool, including the
teacher course-assessment Tools when the viewer was a teacher. The same class
of leak was fixed for ordinary Teams in #181; this applies that rule to
single-Agent chats whose agent_md does not declare an assessment and that hold
no open attempt.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import pytest
from app.modules.runtime_tools.builtin import ASSESSMENT_TOOL_NAMES
from app.modules.workspace.chat_provider import (
    ACCOUNT_MEMORY_RULE,
    ACCOUNT_MEMORY_RULE_NO_ASSESSMENT,
    chat_messages,
)
from app.modules.workspace.formal_assessment import declares_assessment

ASSESSMENT_WORDS = re.compile(
    r"assess|\btests?\b|attempt|score|rubric|ledger|\bformal\b|boundary|正式测评|测评|"
    r"read_memory|read_session|formal test",
    re.IGNORECASE,
)

TESLA_MD = """# Agent: Nikola Tesla

## Basic Information
- **Full Name**: Nikola Tesla
- **Role**: Inventor and electrical engineer

## Personality
- Poetic, dramatic, almost paranoid perfectionist
"""

RECIPE_MD = "# Guide\nMAYA-ASSESSMENT-RECIPE: mayaform.diagnostic.v1\n"


def test_free_agent_markdown_does_not_declare_assessment() -> None:
    assert not declares_assessment(TESLA_MD)
    assert declares_assessment(RECIPE_MD)


@pytest.mark.parametrize("audience", ["student", "teacher"])
def test_ordinary_single_agent_prompt_has_no_assessment_wording(audience: str) -> None:
    version = SimpleNamespace(agent_md=TESLA_MD)
    messages, _ = chat_messages(
        version,  # type: ignore[arg-type]
        [{"role": "user", "content": "你好"}],
        [],
        audience=audience,  # type: ignore[arg-type]
        assessment_capable=False,
    )
    system = messages[0]["content"]
    match = ASSESSMENT_WORDS.search(system)
    assert match is None, match.group(0)
    assert "selected Agent" in system
    assert "educational Agent" not in system
    assert ACCOUNT_MEMORY_RULE_NO_ASSESSMENT in system
    assert ACCOUNT_MEMORY_RULE not in system
    assert "teacher tools" not in system
    assert "formal activity action" not in system
    packed = json.loads(system.split("\n", 1)[1])
    assert packed["agent_markdown"] == TESLA_MD


def test_assessment_capable_single_agent_keeps_assessment_wording() -> None:
    version = SimpleNamespace(agent_md=RECIPE_MD)
    messages, _ = chat_messages(
        version,  # type: ignore[arg-type]
        [{"role": "user", "content": "你好"}],
        [],
        audience="teacher",
        assessment_capable=True,
    )
    system = messages[0]["content"]
    assert ACCOUNT_MEMORY_RULE in system
    assert "teacher tools" in system
    assert "formal activity action" in system


def test_assessment_tool_names_still_classified() -> None:
    # Guard: the single-Agent filter relies on this set remaining non-empty.
    assert "assessment_action" in ASSESSMENT_TOOL_NAMES
    assert "list_course_assessments" in ASSESSMENT_TOOL_NAMES
