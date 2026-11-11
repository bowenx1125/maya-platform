"""The teacher-facing grounding measure on constructed zh and en paragraphs."""

from __future__ import annotations

import pytest
from app.modules.debates.grounding import (
    PARAPHRASED_MIN_COVERAGE,
    QUOTED_MIN_RUN,
    measure_grounding,
)

ZH_SOURCE = (
    "孔子认为，为政以德，譬如北辰，居其所而众星共之。"
    "他主张统治者先修养自身的品德，用礼来约束行为，而不是只依靠刑罚。"
    "在家庭中孝顺父母、尊敬兄长，是仁的根本。"
)
EN_SOURCE = (
    "Confucius held that a ruler who governs by virtue is like the pole star, "
    "which keeps its place while the other stars turn around it. He argued that "
    "rulers should cultivate their own character first and guide people with ritual "
    "rather than relying only on punishment."
)


@pytest.mark.parametrize(
    ("language", "source", "paragraph"),
    (
        (
            "zh",
            ZH_SOURCE,
            "我的看法很明确：他主张统治者先修养自身的品德，用礼来约束行为，而不是只依靠刑罚。",
        ),
        (
            "en",
            EN_SOURCE,
            "As my source puts it, rulers should cultivate their own character first and "
            "guide people with ritual rather than relying only on punishment.",
        ),
    ),
)
def test_a_verbatim_quote_is_quoted(language: str, source: str, paragraph: str) -> None:
    result = measure_grounding(paragraph, [source], language)
    assert result.grounding_class == "quoted"
    assert result.longest_run >= QUOTED_MIN_RUN[language]


@pytest.mark.parametrize(
    ("language", "source", "paragraph"),
    (
        (
            "zh",
            ZH_SOURCE,
            "统治者应当先修养自身，再用礼来约束百姓；只依靠刑罚是不够的，孝顺父母才是仁的根本。",
        ),
        (
            "en",
            EN_SOURCE,
            "A ruler must cultivate their own character first. Guiding people with ritual, "
            "not only punishment, keeps order, the way the pole star keeps its place.",
        ),
    ),
)
def test_a_close_paraphrase_is_paraphrased(language: str, source: str, paragraph: str) -> None:
    result = measure_grounding(paragraph, [source], language)
    assert result.grounding_class == "paraphrased"
    assert result.coverage >= PARAPHRASED_MIN_COVERAGE
    assert result.longest_run < QUOTED_MIN_RUN[language]


@pytest.mark.parametrize(
    ("language", "source", "paragraph"),
    (
        (
            "zh",
            ZH_SOURCE,
            "短视频平台的推荐算法会放大极端内容，因此需要公开审查和用户选择权。",
        ),
        (
            "en",
            EN_SOURCE,
            "Recommendation algorithms on video platforms amplify extreme content, so they "
            "need public review and meaningful user choice.",
        ),
    ),
)
def test_unrelated_text_is_not_found(language: str, source: str, paragraph: str) -> None:
    result = measure_grounding(paragraph, [source], language)
    assert result.grounding_class == "not_found"
    assert result.coverage < PARAPHRASED_MIN_COVERAGE


def test_case_width_and_punctuation_do_not_change_the_measure() -> None:
    plain = measure_grounding(
        "Rulers should cultivate their own character first", [EN_SOURCE], "en"
    )
    shouted = measure_grounding(
        "RULERS, should cultivate — their OWN character first!", [EN_SOURCE], "en"
    )
    assert plain == shouted


def test_several_cited_chunks_are_measured_together() -> None:
    paragraph = "孝顺父母、尊敬兄长是仁的根本，而推荐算法需要公开审查。"
    other = "推荐算法需要公开审查和用户选择权。"
    alone = measure_grounding(paragraph, [ZH_SOURCE], "zh")
    together = measure_grounding(paragraph, [ZH_SOURCE, other], "zh")
    assert together.coverage > alone.coverage
    assert together.total_grams == alone.total_grams


def test_an_empty_or_too_short_paragraph_measures_nothing() -> None:
    result = measure_grounding("好。", [ZH_SOURCE], "zh")
    assert (result.grounding_class, result.coverage, result.total_grams) == ("not_found", 0.0, 0)


def test_a_source_in_another_language_is_reported_as_unmeasured() -> None:
    english = "The imitation game replaces the question of whether machines can think."
    chinese = "模仿游戏用一个可以检验的问题，替换了机器能不能思考这个问题。"
    measured = measure_grounding(chinese, [english], "zh")
    assert measured.grounding_class == "other_language"
    assert measured.total_grams == 0
    assert measure_grounding(english, [chinese], "en").grounding_class == "other_language"
    # A mixed source that is mostly the speech's language is still measured.
    assert measure_grounding(chinese, [chinese + " imitation game"], "zh").grounding_class in {
        "quoted",
        "paraphrased",
    }
