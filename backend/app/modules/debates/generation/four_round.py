"""Versioned classroom tasks and deterministic, non-generative discussion metadata."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from .types import FinalReadyTurn, GenerationContext

TEACHING_PROTOCOL = "four_round_v1"
ENGLISH_WORD = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")


def body_count(text: str, language: str) -> int:
    return (
        sum(not char.isspace() for char in text)
        if language == "zh"
        else len(ENGLISH_WORD.findall(text))
    )


def visible_predecessors(context: GenerationContext) -> tuple[FinalReadyTurn, ...]:
    if context.teaching_protocol == TEACHING_PROTOCOL:
        visible = (
            item
            for item in context.predecessors
            if context.turn.round_no > 1 and item.turn_index < context.turn.turn_index
        )
    else:
        visible = (item for item in context.predecessors if item.round_no < context.turn.round_no)
    return tuple(sorted(visible, key=lambda item: (item.round_no, item.turn_index, item.turn_id)))


def received_questions(context: GenerationContext) -> list[dict[str, str]]:
    rows = []
    for item in visible_predecessors(context):
        question = getattr(item.structured, "question", None)
        if (
            item.round_no == 2
            and isinstance(question, Mapping)
            and question.get("target_agent_id") == context.participant.participant_id
        ):
            rows.append({"from_id": item.participant_id, "text": str(question["text"])})
    return rows


def discussion_context(context: GenerationContext) -> dict[str, object]:
    agents = sorted(context.participants, key=lambda item: item.order_index)
    ids = [item.participant_id for item in agents]
    own = context.participant.participant_id
    target = ids[(ids.index(own) + 1) % len(ids)] if context.turn.round_no == 2 else None
    memories = []
    for item in visible_predecessors(context):
        memory = getattr(item.structured, "discussion_memory", None)
        if item.round_no == 3 and isinstance(memory, Mapping):
            memories.append({"agent_id": item.participant_id, "memory": dict(memory)})
    return {
        "protocol": TEACHING_PROTOCOL,
        "self_id": own,
        "agents": [{"id": item.participant_id, "name": item.agent_name} for item in agents],
        "question_target_id": target,
        "received_questions": received_questions(context),
        "memories": memories,
    }


def validate_discussion(value: object) -> dict[str, object]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {"protocol", "self_id", "agents", "question_target_id", "received_questions", "memories"}
        or value.get("protocol") != TEACHING_PROTOCOL
    ):
        raise ValueError("invalid discussion context")
    # Round-trip prevents caller mutations from changing a frozen input.
    result = json.loads(json.dumps(dict(value), ensure_ascii=False))
    agents = result["agents"]
    if (
        not isinstance(agents, list)
        or not 2 <= len(agents) <= 5
        or any(
            not isinstance(a, dict)
            or set(a) != {"id", "name"}
            or not all(isinstance(v, str) and v.strip() for v in a.values())
            for a in agents
        )
    ):
        raise ValueError("invalid discussion agents")
    ids = {a["id"] for a in agents}
    if (
        len(ids) != len(agents)
        or result["self_id"] not in ids
        or result["question_target_id"] not in ids | {None}
    ):
        raise ValueError("invalid discussion identity")
    if not isinstance(result["received_questions"], list) or not isinstance(
        result["memories"], list
    ):
        raise ValueError("invalid discussion arrays")
    for question in result["received_questions"]:
        if (
            not isinstance(question, dict)
            or set(question) != {"from_id", "text"}
            or question["from_id"] not in ids
            or not isinstance(question["text"], str)
            or not question["text"].strip()
        ):
            raise ValueError("invalid received question")
    for memory in result["memories"]:
        if (
            not isinstance(memory, dict)
            or set(memory) != {"agent_id", "memory"}
            or memory["agent_id"] not in ids
        ):
            raise ValueError("invalid discussion memory owner")
        validate_memory(memory["memory"], ids)
    return cast(dict[str, object], result)


def validate_memory(value: object, agent_ids: set[str] | None = None) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "position",
        "change",
        "reason",
        "influence",
        "unresolved_question",
    }:
        raise ValueError("invalid discussion memory")
    if value["change"] not in {"retained", "qualified", "revised"}:
        raise ValueError("invalid position change")
    for key in ("position", "reason", "unresolved_question"):
        if not isinstance(value[key], str) or (
            key != "unresolved_question" and not value[key].strip()
        ):
            raise ValueError("invalid discussion memory text")
    influence = value["influence"]
    if influence is not None and (
        not isinstance(influence, Mapping)
        or set(influence) != {"agent_id", "point"}
        or not isinstance(influence["point"], str)
        or not influence["point"].strip()
        or (agent_ids is not None and influence["agent_id"] not in agent_ids)
    ):
        raise ValueError("invalid discussion influence")
    return cast(dict[str, object], json.loads(json.dumps(dict(value), ensure_ascii=False)))


def usable_question(value: object, agent_ids: set[str] | None = None) -> dict[str, str] | None:
    """Unusable routing metadata must never discard a classroom speech."""
    if not isinstance(value, Mapping):
        return None
    target, text = value.get("target_agent_id"), value.get("text")
    if not isinstance(target, str) or not isinstance(text, str) or not text.strip():
        return None
    if not target or (agent_ids is not None and target not in agent_ids):
        return None
    return {"target_agent_id": target, "text": text}


def usable_memory(value: object, agent_ids: set[str] | None = None) -> dict[str, object] | None:
    try:
        return validate_memory(value, agent_ids)
    except (ValueError, TypeError, KeyError):
        return None


def system_prompt(round_number: int, language: str) -> str:
    from app.modules.debates.teaching_rules import compile_system_prompt, default_teaching_prompts

    return compile_system_prompt(default_teaching_prompts()[language], round_number, language)
