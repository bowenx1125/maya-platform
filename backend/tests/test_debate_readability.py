"""Debate speeches a classroom can follow (2026-11-02).

The English default Ruleset told the model to say "The RAG evidence confirms"
and "I feel" aloud and taught it the +5/+2 scoring, while the Chinese one (made
concise and spoken on 2026-10-25) forbids exactly that. Both now teach the same
spoken style. A copied sentence cut out of the middle of a paragraph left an
argument with a step missing, so such a turn is rewritten instead.
"""

from __future__ import annotations

import re

import pytest
from app.modules.debates.generation.segments import (
    SegmentProtocolError,
    _copy_key,
    history_copy_leaves_a_hole,
    validate_segment_output,
)
from app.modules.debates.teaching_rules import default_teaching_prompts

from tests.test_debate_final_report_fixes import HISTORY, ROUND3_ZHAOYAO, _snapshot

CONTRACT_HEADING = {"zh": "# 执行约定", "en": "# Execution contract"}


def _rules(language: str) -> tuple[str, str]:
    teaching, contract = default_teaching_prompts()[language].split(CONTRACT_HEADING[language], 1)
    return teaching, contract


def test_english_rules_no_longer_script_labels_or_scores() -> None:
    teaching, contract = _rules("en")
    whole = teaching + contract
    for label in ("The RAG evidence confirms", "RAG evidence", "I feel"):
        assert label not in whole, label
    assert not re.search(r"\(\+\d\)", whole)
    assert len(whole.encode()) < 6000


# 2026-11-03: a capable model follows stated goals; lists of prohibitions
# made it withhold correct context. The rules say what to do, and the
# contract keeps only the formats the server checks.
DEFENSIVE = {
    "zh": ("绝不", "不要", "不能", "不用", "不是指令", "不是命令", "不是台词"),
    "en": ("Never", "never", "Do not", "Don't", "not instructions", "must not", "not commands"),
}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_default_rules_state_goals_not_prohibitions(language: str) -> None:
    whole = default_teaching_prompts()[language]
    found = [word for word in DEFENSIVE[language] if word in whole]
    assert found == [], found


@pytest.mark.parametrize(
    ("language", "audience", "naming"),
    [
        ("zh", "普通高中生", "回应谁就先点名"),
        ("en", "ordinary high-school listener", "name them and say in half a sentence"),
    ],
)
def test_both_languages_speak_to_a_listener_who_missed_the_start(
    language: str, audience: str, naming: str
) -> None:
    teaching, _contract = _rules(language)
    assert audience in teaching
    assert naming in teaching


def test_both_contracts_state_the_same_machine_rules() -> None:
    _zh_teaching, zh = _rules("zh")
    _en_teaching, en = _rules("en")
    for token in (
        "{round}",
        "discussion.self_id",
        "participant_id",
        "segments",
        "discussion_memory",
        "{text,source_ids,reply_to,support_mode}",
        "direct",
        "contextual",
        "no_match",
        "discussion.question_target_id",
        "{target_agent_id,text}",
        "{position,change,reason,influence,unresolved_question}",
        "retained",
        "qualified",
        "revised",
        "{agent_id,point}",
        "JSON null",
    ):
        assert token in zh, token
        assert token in en, token
    # The server now also sends a mid-paragraph copy back; both say so.
    assert "退回重写" in zh
    assert "sends the speech back to be rewritten" in en


FRESH_A = "我先回答你的问题：高分只有在学生能把证据迁移到新题时才说明学会。"
FRESH_B = "所以我给出的条件是迁移，而不是背诵，这是我这一轮新增的判断。"
COPIED = "背诵精简事实确实违背了验证逻辑。"


def _output(*texts: str) -> dict[str, object]:
    return {
        "segments": [
            {"text": text, "source_ids": [], "reply_to": None, "support_mode": "no_match"}
            for text in texts
        ]
    }


def test_a_copy_between_new_sentences_is_rewritten_not_cut_out() -> None:
    keys = tuple(_copy_key(item["text"]) for item in HISTORY)
    middle = FRESH_A + COPIED + FRESH_B
    assert COPIED in ROUND3_ZHAOYAO
    assert history_copy_leaves_a_hole(middle, keys)
    with pytest.raises(SegmentProtocolError) as caught:
        validate_segment_output(_output(middle), _snapshot(HISTORY))
    assert caught.value.code == "segment_history_copy"
    # The repair attempt never loses the turn: the copy is cut as before.
    kept = validate_segment_output(_output(middle), _snapshot(HISTORY), allow_history_copy=True)
    assert COPIED not in kept.speech
    assert FRESH_A in kept.speech and FRESH_B in kept.speech


@pytest.mark.parametrize(
    "text",
    [
        COPIED + FRESH_A + FRESH_B,  # a copied opening is cut cleanly
        FRESH_A + FRESH_B + COPIED,  # so is a copied ending
        FRESH_A + "\n" + COPIED + "\n" + FRESH_B,  # its own line: a paragraph of its own
        FRESH_A + FRESH_B,  # nothing copied
    ],
)
def test_a_copy_that_leaves_whole_thoughts_is_still_just_removed(text: str) -> None:
    keys = tuple(_copy_key(item["text"]) for item in HISTORY)
    assert not history_copy_leaves_a_hole(text, keys)
    result = validate_segment_output(_output(text), _snapshot(HISTORY))
    assert COPIED not in result.speech
    assert FRESH_A in result.speech and FRESH_B in result.speech
