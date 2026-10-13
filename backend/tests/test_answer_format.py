"""A Question's answer format, read from its own text (owner decision 2026-10-13)."""

from __future__ import annotations

from app.modules.learning.answer_format import answer_format, fits, format_hint

CHOICE = (
    "下列哪一种情况，最接近朱熹所说的“穷理”？\n\n"
    "- A. 一个 AI 读遍了文献\n- B. 一位学生背下了全文\n"
    "- C. 一位农人种了几十年竹子\n- D. 一位学生能说清道理\n\n请回复你选择的选项（A、B、C 或 D）。"
)
SCALE = (
    "今天被认为正确的知识，将来可能会被修正。\n\n请选择你同意的程度，回复数字即可：\n\n"
    "1 = 非常不同意　2 = 不同意　3 = 不确定　4 = 同意　5 = 非常同意"
)
CONFIDENCE = "关于第 3 题：你对这个选择有多确定？请打 1–5 分（1 = 完全是猜的，5 = 非常确定）。"
OPEN = "你认为“知道”一件事，意味着什么？请用一两句话回答，没有标准答案。"
MULTI = "你主要用 AI 做什么？（可多选，回复所有适用的字母）\n\n- A. 查资料\n- B. 写作业\n- C. 编程"


def test_a_choice_question_takes_only_its_own_letters() -> None:
    form = answer_format(CHOICE)
    assert (form.kind, form.letters, form.multiple) == ("choice", ("A", "B", "C", "D"), False)
    for reply in ("b", "B", "我选C", "B，因为农人有经验", "I pick D"):
        assert fits(form, reply), reply
    for reply in ("E", "3", "不知道", ""):
        assert not fits(form, reply), reply
    assert format_hint(form, True) == "请回复 A、B、C、D 中的一个字母。"


def test_a_scale_question_takes_only_a_number_in_range() -> None:
    form = answer_format(SCALE)
    assert (form.kind, form.low, form.high) == ("scale", 1, 5)
    assert fits(form, "4") and fits(form, "3，说不清")
    for reply in ("6", "0", "B", "同意"):
        assert not fits(form, reply), reply
    confidence = answer_format(CONFIDENCE)
    assert (confidence.kind, confidence.low, confidence.high) == ("scale", 1, 5)
    assert not fits(confidence, "6")
    assert format_hint(confidence, False) == "Reply with one number from 1 to 5."


def test_an_open_question_takes_words_but_not_requests() -> None:
    form = answer_format(OPEN)
    assert form.kind == "free"
    for reply in ("知道意味着用在行动上", "心", "Knowing means acting on it"):
        assert fits(form, reply), reply
    for reply in ("我回答了 为什么没有记录", "答案是什么？", "跳过", "what is this"):
        assert not fits(form, reply), reply


def test_a_multiple_choice_question_says_so() -> None:
    form = answer_format(MULTI)
    assert form.multiple and fits(form, "A C") and not fits(form, "A E")
    assert format_hint(form, True) == "请回复 A、B、C 中所有适用的字母。"
