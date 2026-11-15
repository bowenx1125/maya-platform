"""Versioned classroom tasks and deterministic, non-generative discussion metadata."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import TYPE_CHECKING, cast

from app.modules.debates.generation_params import uses_code_contract

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


# v4 length (owner decision 2026-11-10): a whole Debate targets a few minutes
# of audio. Units are Han characters (zh) or words (en) at a spoken pace,
# scaled by the frozen voice rate, with 10% headroom for pauses. zh is measured
# production audio (median 224 Han chars/min at rate 1.0, 310 at 1.25); en has
# no measurement yet and uses a common speaking pace.
UNITS_PER_MINUTE = {"zh": 230, "en": 150}
MIN_TURN_UNITS = {"zh": 40, "en": 25}
ROUND_WEIGHTS = {1: Fraction(11, 10), 2: Fraction(9, 10), 3: Fraction(9, 10), 4: Fraction(11, 10)}
# A speech this far over its cap is sent back once, then trimmed.
OVER_LENGTH_RATIO = Fraction(5, 4)
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]")


def speech_units(text: str, language: str) -> int:
    """Units the v4 length rule counts: Han characters (zh) or words (en)."""

    return len(_HAN.findall(text)) if language == "zh" else len(ENGLISH_WORD.findall(text))


def turn_unit_cap(
    language: str, *, minutes: int, voice_rate: float, participants: int, round_number: int
) -> int:
    budget = minutes * UNITS_PER_MINUTE[language] * Fraction(str(voice_rate)) * Fraction(9, 10)
    share = budget / (participants * 4) * ROUND_WEIGHTS[round_number]
    return max(MIN_TURN_UNITS[language], math.floor(share / 5) * 5)


# Hard ceiling accepted on a new Debate's four caps; lower bound is MIN_TURN_UNITS.
ROUND_UNIT_CAP_MAX = 2000


def over_length_limit(cap: int, ratio: Fraction | None = None) -> int:
    return math.floor(cap * (OVER_LENGTH_RATIO if ratio is None else ratio))


def default_round_unit_caps(
    language: str, *, participants: int, voice_rate: float = 1.0, minutes: int = 5
) -> list[int]:
    """The four default caps the create form starts from (same formula as v4)."""

    return [
        turn_unit_cap(
            language,
            minutes=minutes,
            voice_rate=voice_rate,
            participants=participants,
            round_number=round_number,
        )
        for round_number in range(1, 5)
    ]


def estimated_duration_minutes(
    caps: Sequence[int],
    *,
    language: str,
    participants: int,
    voice_rate: float = 1.0,
) -> float:
    """Read-only full-debate estimate from §3.2; not a runtime cap."""

    total_units = sum(int(item) for item in caps) * participants
    assumed_rate = 1.0 if voice_rate <= 0 else float(voice_rate)
    denominator = UNITS_PER_MINUTE[language] * assumed_rate * Fraction(9, 10)
    return float(total_units / denominator)


def speech_language_mismatch(text: str, language: str) -> bool:
    """Conservative language-deviation heuristic for a v5 rewrite.

    Target zh with zero Han characters, or target en with more Han than
    English words. Anything less clear does not trigger a rewrite.
    """

    han = speech_units(text, "zh")
    words = speech_units(text, "en")
    if language == "zh":
        return han == 0
    if language == "en":
        return han > words
    return False


_STANCES = {
    "zh": {
        "support": "支持题目中的主张",
        "oppose": "反对题目中的主张",
        "neutral": "保持中立，权衡双方",
    },
    "en": {
        "support": "support the Topic's claim",
        "oppose": "oppose the Topic's claim",
        "neutral": "stay neutral and weigh both sides",
    },
}


def stance_text(language: str, stance: str | None) -> str:
    return _STANCES["zh" if language == "zh" else "en"].get(stance or "", "")


def _round_task(language: str, round_number: int, other: str, sentences: int) -> str:
    zh = language == "zh"
    # A model keeps to a sentence count far better than to a character count:
    # the first v4 Debate overshot its cap in a quarter of its speeches. An
    # upper bound alone then gave speeches as short as 23 characters and a
    # Debate a third under its target, hence a range and the cap as the aim.
    limit = (
        f"写{sentences - 1}到{sentences}句话，总字数接近 max_units。"
        if zh
        else f" Use {sentences - 1} to {sentences} sentences and come close to max_units."
    )
    if round_number == 1:
        task = (
            "独立陈述你对题目的判断和理由。"
            if zh
            else "State your own judgment on the Topic and your reason."
        )
    elif round_number == 2:
        task = (
            f"反驳{other}的开场发言，并在发言的最后一句向{other}提一个问题。"
            if zh
            else f"Rebut {other}'s opening and end the speech by asking {other} one question."
        )
    elif round_number == 3:
        task = (
            f"回答{other}向你提的问题，再就一个观点提出反驳。"
            if zh
            else f"Answer {other}'s question, then push back on one point."
        )
    else:
        # Round 4 kept re-answering the round-3 question when told only to conclude.
        task = (
            "给出你的最终判断：说出谁的哪个观点说服了你，或你仍然不同意什么。前面回答过的问题不再重答。"
            if zh
            else "Give your final judgment: name whose point persuaded you, or what you still "
            "reject. Do not answer an earlier question again."
        )
    return task + limit


def sentence_limit(language: str, cap: int) -> int:
    """How many sentences fit the cap at a spoken sentence length."""

    # Spoken sentences in the two v4 Debates ran about 22 Han characters.
    return max(3, math.ceil(cap / (22 if language == "zh" else 18)))


def turn_task(
    context: GenerationContext, *, minutes: int, unit_cap: int | None = None
) -> dict[str, object]:
    """The code-written task group for this speaker's turn.

    Names follow the same cyclic order as ``question_target_id``: round 2
    questions the next Agent, so round 3 answers the previous one unless a
    question actually arrived from someone else.
    """

    language = "zh" if context.output_language == "zh" else "en"
    agents = sorted(context.participants, key=lambda item: item.order_index)
    ids = [item.participant_id for item in agents]
    names = {item.participant_id: item.agent_name for item in agents}
    index = ids.index(context.participant.participant_id)
    round_number = context.turn.round_no
    other = ""
    if round_number == 2:
        other = names[ids[(index + 1) % len(ids)]]
    elif round_number == 3:
        received = received_questions(context)
        asker = received[0]["from_id"] if received else ids[(index - 1) % len(ids)]
        other = names.get(asker, names[ids[(index - 1) % len(ids)]])
    cap = (
        unit_cap
        if unit_cap is not None
        else turn_unit_cap(
            language,
            minutes=minutes,
            voice_rate=context.voice_rate or 1.0,
            participants=len(ids),
            round_number=round_number,
        )
    )
    task: dict[str, object] = {
        "round_task": _round_task(language, round_number, other, sentence_limit(language, cap)),
        "max_units": cap,
    }
    if context.participant.stance_mode == "assigned":
        stance = stance_text(language, context.participant.initial_stance)
        if stance:
            task["stance"] = stance
    return task


def validate_task(value: object) -> dict[str, object]:
    if (
        not isinstance(value, Mapping)
        or not {"round_task", "max_units"} <= set(value) <= {"round_task", "max_units", "stance"}
        or isinstance(value["max_units"], bool)
        or not isinstance(value["max_units"], int)
        or value["max_units"] < 1
        or any(
            not isinstance(value[key], str) or not value[key].strip()
            for key in ("round_task", "stance")
            if key in value
        )
    ):
        raise ValueError("invalid task group")
    return cast(dict[str, object], json.loads(json.dumps(dict(value), ensure_ascii=False)))


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
        # A question asked earlier in round 2 is answered in round 3. Shown to
        # its target during round 2, it was copied out as that Agent's own question.
        "received_questions": []
        if context.turn.round_no == 2 and uses_code_contract(context.frozen_llm)
        else received_questions(context),
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
    """The prompt of a Debate frozen before Rulesets carried their own contract."""

    from app.modules.debates.teaching_rules import (
        legacy_compile_system_prompt,
        legacy_teaching_prompts,
    )

    return legacy_compile_system_prompt(legacy_teaching_prompts()[language], round_number, language)
