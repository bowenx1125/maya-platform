"""The Knowledge welcome spoken once, before the first question."""

from __future__ import annotations

from app.modules.knowledge_sets.service import knowledge_opening
from app.modules.workspace.formal_assessment import opening_line, with_spoken_opening

WELCOME_ZH = "约 8 分钟 · 没有对错"
WELCOME_EN = "About 8 minutes. No right or wrong answers."
RUBRIC = "RUBRIC_CANARY_DO_NOT_SHOW"
ANSWER = "ANSWER_KEY_CANARY_DO_NOT_SHOW"
CONCEPT = "CONCEPT_CANARY_NOT_A_WELCOME"


def _bank(preamble: str) -> str:
    return (
        "# 认识论小测\n\n"
        f"{preamble}"
        "## Questions\n\n"
        "### Question 1\n\n"
        "甲题\n\n"
        "#### Rubric\n\n"
        f"- **Reasoning** (2): {RUBRIC}\n\n"
        "Total: 2 points\n\n"
        "#### Reference answer\n\n"
        f"{ANSWER}\n"
    )


def test_explicit_opening_is_spoken_and_the_answer_key_is_not() -> None:
    markdown = _bank(
        "## Opening\n\n"
        f"{WELCOME_ZH}\n\n"
        f"{WELCOME_EN}\n\n"
        "先读说明，再作答。\n\n"
        "#### Reference answer\n\n"
        f"{ANSWER}\n\n"
        "#### Rubric\n\n"
        f"{RUBRIC}\n\n"
    )
    opening = knowledge_opening(markdown)
    assert opening == f"{WELCOME_ZH}\n\n{WELCOME_EN}\n\n先读说明，再作答。"
    assert RUBRIC not in opening
    assert ANSWER not in opening
    assert "甲题" not in opening
    assert "Questions" not in opening


def test_chinese_opening_heading_passes_authored_text_through() -> None:
    markdown = _bank(f"## 开场白\n\n{WELCOME_ZH}\n\n{WELCOME_EN}\n\n")
    assert knowledge_opening(markdown) == f"{WELCOME_ZH}\n\n{WELCOME_EN}"


def test_opening_between_concepts_and_questions_is_spoken() -> None:
    markdown = (
        "# 起点\n\n"
        "## Concepts\n\n"
        f"{CONCEPT}\n\n"
        "## Opening\n\n"
        f"{WELCOME_ZH}\n\n"
        f"{WELCOME_EN}\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "甲题\n\n"
        "#### Rubric\n\n"
        f"- **Reasoning** (2): {RUBRIC}\n\n"
        "#### Reference answer\n\n"
        f"{ANSWER}\n\n"
        "## Notes\n\n"
        "NOTE_CANARY\n"
    )
    opening = knowledge_opening(markdown)
    assert opening == f"{WELCOME_ZH}\n\n{WELCOME_EN}"
    assert CONCEPT not in opening
    assert RUBRIC not in opening
    assert ANSWER not in opening
    assert "甲题" not in opening
    assert "NOTE_CANARY" not in opening


def test_opening_heading_wins_over_loose_prose() -> None:
    markdown = _bank(f"这段不算开场。\n\n## Opening\n\n{WELCOME_ZH}\n\n")
    assert knowledge_opening(markdown) == WELCOME_ZH


def test_fallback_is_prose_before_questions_and_skips_concept_sections() -> None:
    markdown = _bank(
        f"{WELCOME_ZH}\n\n\n\n{WELCOME_EN}\n\n"
        "## Concepts\n\n"
        f"{CONCEPT}\n\n"
        "## Notes\n\n"
        "NOTE_CANARY\n\n"
    )
    assert knowledge_opening(markdown) == f"{WELCOME_ZH}\n\n{WELCOME_EN}"
    assert CONCEPT not in knowledge_opening(markdown)


def test_missing_opening_is_empty_so_the_question_line_stays_unchanged() -> None:
    generated = (
        "# 认识论小测\n\n"
        "## Concepts\n\n"
        f"{CONCEPT}\n\n"
        "## Graph\n\n"
        "- 甲 → 乙\n\n"
        "## Questions\n\n"
        "### Question 1\n\n"
        "甲题\n\n"
        "#### Rubric\n\n"
        f"{RUBRIC}\n\n"
        "#### Reference answer\n\n"
        f"{ANSWER}\n"
    )
    assert knowledge_opening(generated) == ""
    assert knowledge_opening(_bank("")) == ""
    assert knowledge_opening("# 只有标题\n\n没有题目。") == ""
    assert with_spoken_opening(opening_line("甲题"), "") == "收到，第一题是甲题"
    assert with_spoken_opening(opening_line("甲题"), " \n") == "收到，第一题是甲题"
    spoken = with_spoken_opening(opening_line("甲题\nA. 甲\nB. 乙"), WELCOME_ZH)
    assert spoken == f"{WELCOME_ZH}\n\n收到，第一题是甲题\nA. 甲\nB. 乙"
