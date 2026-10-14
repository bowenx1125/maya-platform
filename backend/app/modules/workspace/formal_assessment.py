"""Formal assessment roles live in the Guide's `# Team Ruleset`, not in member tags.

`assessment_active` is a server ledger flag. Nothing in this module is a Tool,
and the model cannot set that flag.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from app.core.errors import conflict

# The Guide's opening, completion, and abandon lines are server text.
OPENING_PREFIX = "收到，第一题是"
ALL_DONE_GUIDE = "答题全部结束"
SUMMARIZER_LINE = "正在总结答案"
ABANDON_SCORER = "做题者放弃作答，已保存记录已删除。"
ABANDON_GUIDE = "已放弃作答，你要重新开始吗，或者和我随便聊聊"
# Emitted only when an assessment_action receipt exists for this reply.
RECORDED_FACT = "已记录你的回答。"

WRITE_TOOLS = frozenset({"assessment_action", "edit_assessment", "update_learning_boundary"})
_ROLE_FIELDS = ("answer_recorder", "question_guide", "scorer", "summarizer")
_TEAM_RULESET_HEADING = re.compile(r"(?m)^#\s+Team Ruleset\s*$")
# The next h1 ends the section. `## Formal assessment` stays inside it.
_NEXT_H1 = re.compile(r"(?m)^#\s+\S")
_FORMAL_HEADING = re.compile(r"(?m)^##\s+Formal assessment\s*$")
_INFORMAL_HEADING = re.compile(r"(?m)^##\s+Informal\s*$")
_NEXT_HEADING = re.compile(r"(?m)^#{1,6}\s+\S")
_FIELD_LINE = re.compile(
    r"^(answer_recorder|question_guide|scorer|summarizer|student_round_order)\s*:\s*(.*?)\s*$"
)


@dataclass(frozen=True)
class FormalRoles:
    """Roster member ids named by a complete `## Formal assessment` section."""

    answer_recorder_id: str
    question_guide_id: str
    scorer_id: str
    summarizer_id: str
    student_round_order_ids: tuple[str, ...]


def formal_ruleset_markdown(
    *,
    answer_recorder: str,
    question_guide: str,
    scorer: str,
    summarizer: str,
    student_round_order: Sequence[str],
) -> str:
    order = ", ".join(student_round_order)
    return (
        "# Team Ruleset\n\n"
        "## Formal assessment\n"
        f"answer_recorder: {answer_recorder}\n"
        f"question_guide: {question_guide}\n"
        f"scorer: {scorer}\n"
        f"summarizer: {summarizer}\n"
        f"student_round_order: {order}\n"
    )


def extract_team_ruleset(agent_md: str) -> str | None:
    """Return the Guide Agent.md `# Team Ruleset` body when that section exists.

    Missing heading means framework defaults apply. Subsections such as
    `## Formal assessment` and `## Informal` stay inside the body; the next
    h1 ends it.
    """

    match = _TEAM_RULESET_HEADING.search(agent_md)
    if match is None:
        return None
    rest = agent_md[match.end() :]
    next_heading = _NEXT_H1.search(rest)
    body = rest[: next_heading.start()] if next_heading is not None else rest
    return body.strip()


def extract_informal_section(ruleset_body: str) -> str | None:
    """Return `## Informal` inside a Team Ruleset, when that subsection exists."""

    match = _INFORMAL_HEADING.search(ruleset_body)
    if match is None:
        return None
    rest = ruleset_body[match.end() :]
    nxt = _NEXT_HEADING.search(rest)
    body = rest[: nxt.start()] if nxt is not None else rest
    return body.strip()


def _formal_body(ruleset_body: str) -> str | None:
    match = _FORMAL_HEADING.search(ruleset_body)
    if match is None:
        return None
    rest = ruleset_body[match.end() :]
    nxt = _NEXT_HEADING.search(rest)
    body = rest[: nxt.start()] if nxt is not None else rest
    return body.strip()


def _incomplete() -> NoReturn:
    raise conflict(
        "assessment_ruleset_incomplete",
        "Formal assessment needs a complete # Team Ruleset section naming the roster.",
    )


def _unique_member(roster: dict[str, list[str]], name: str) -> str:
    matches = roster.get(name, [])
    if len(matches) != 1:
        _incomplete()
    return matches[0]


def resolve_formal_assessment(
    agent_md: str, roster: Sequence[tuple[str, str]]
) -> FormalRoles | None:
    """Resolve Formal assessment roles from the Guide Agent.md.

    Returns None when `# Team Ruleset` has no `## Formal assessment` subsection.
    A present subsection that does not name each field to exactly one roster
    display name raises `assessment_ruleset_incomplete` and must not start an
    attempt. `student_round_order` is exactly the scorer and question_guide, in
    the order they speak on a student message. `answer_recorder` must be that
    same scorer: the write Tool, `已记录你的回答。`, and the abandon recorder
    line are one slot, so the protocol does not split them.
    """

    ruleset = extract_team_ruleset(agent_md)
    if ruleset is None:
        return None
    body = _formal_body(ruleset)
    if body is None:
        return None
    found: dict[str, str] = {}
    for line in body.splitlines():
        match = _FIELD_LINE.match(line.strip())
        if match is None:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in found or not value:
            _incomplete()
        found[key] = value
    if set(found) != {*_ROLE_FIELDS, "student_round_order"}:
        _incomplete()
    by_name: dict[str, list[str]] = {}
    for member_id, display_name in roster:
        by_name.setdefault(display_name, []).append(member_id)
    order_names = [part.strip() for part in re.split(r"[,，]", found["student_round_order"])]
    if (
        not order_names
        or any(not part for part in order_names)
        or len(order_names) != len(set(order_names))
    ):
        _incomplete()
    recorder_id = _unique_member(by_name, found["answer_recorder"])
    guide_id = _unique_member(by_name, found["question_guide"])
    scorer_id = _unique_member(by_name, found["scorer"])
    order_ids = tuple(_unique_member(by_name, name) for name in order_names)
    # The student-turn write and the fact sentence are the scorer's spoken slot.
    # A different recorder would need a third speaker the script does not have.
    if recorder_id != scorer_id or len(order_ids) != 2 or set(order_ids) != {scorer_id, guide_id}:
        _incomplete()
    return FormalRoles(
        answer_recorder_id=recorder_id,
        question_guide_id=guide_id,
        scorer_id=scorer_id,
        summarizer_id=_unique_member(by_name, found["summarizer"]),
        student_round_order_ids=order_ids,
    )


def opening_line(prompt: str | None) -> str:
    if prompt:
        return f"{OPENING_PREFIX}{prompt}"
    return f"{OPENING_PREFIX}…"
