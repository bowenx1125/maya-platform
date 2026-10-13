"""What kind of answer a Question asks for, read from its own text.

Owner decision (2026-10-13): a choice question has fixed answers, a scale
question a fixed range; fill-in and open questions are answered freely, but
a request or a question back is still not an answer. A reply that does not
fit is not recorded, and the student is told the format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_OPTION_LINE = re.compile(r"^\s*[-*]?\s*([A-H])\s*[.、．)）]\s*\S", re.MULTILINE)
_MULTIPLE = re.compile(r"可多选|多选|所有适用|select all|all that apply", re.IGNORECASE)
_SCALE_POINT = re.compile(r"(?<!\d)(\d{1,2})\s*=")
_SCALE_RANGE = re.compile(r"(?<!\d)(\d{1,2})\s*[–\-~～到至]\s*(\d{1,2})\s*分")
_LETTER = re.compile(r"(?<![A-Za-z])([A-Ha-h])(?![A-Za-z])")
_NUMBER = re.compile(r"(?<!\d)(\d+)(?!\d)")
# A request, a question back or a lifecycle word: never a free answer.
_ASKS = re.compile(
    r"[?？]|答案|提示|为什么|怎么|什么意思|是什么|能不能|可以吗|帮我|不懂|没懂|"
    r"跳过|暂停|结束|放弃|继续|没有记录|没记录|进度|"
    r"\b(?:why|how|what|hint|answer|help|skip|pause|stop|continue|progress)\b",
    re.IGNORECASE,
)
_PROGRESS = re.compile(
    r"进度|第几题|几题|多少题|还剩|还有几|progress|how many|left|remaining", re.IGNORECASE
)


@dataclass(frozen=True)
class AnswerFormat:
    kind: Literal["choice", "scale", "free"]
    letters: tuple[str, ...] = ()
    multiple: bool = False
    low: int = 0
    high: int = 0


def answer_format(prompt: str) -> AnswerFormat:
    letters = tuple(dict.fromkeys(match.upper() for match in _OPTION_LINE.findall(prompt)))
    if len(letters) >= 2:
        return AnswerFormat("choice", letters=letters, multiple=bool(_MULTIPLE.search(prompt)))
    points = [int(value) for value in _SCALE_POINT.findall(prompt)]
    if len(points) >= 2:
        return AnswerFormat("scale", low=min(points), high=max(points))
    span = _SCALE_RANGE.search(prompt)
    if span is not None:
        low, high = sorted((int(span.group(1)), int(span.group(2))))
        if low < high:
            return AnswerFormat("scale", low=low, high=high)
    return AnswerFormat("free")


def fits(form: AnswerFormat, text: str) -> bool:
    """Whether the reply is shaped like an answer to this Question."""

    if form.kind == "choice":
        chosen = [letter.upper() for letter in _LETTER.findall(text)]
        return bool(chosen) and all(letter in form.letters for letter in chosen)
    if form.kind == "scale":
        numbers = _NUMBER.findall(text)
        return bool(numbers) and form.low <= int(numbers[0]) <= form.high
    return is_statement(text)


def is_statement(text: str) -> bool:
    return 1 <= len(text.strip()) <= 2000 and not _ASKS.search(text)


def asks_progress(text: str) -> bool:
    return bool(_PROGRESS.search(text))


def format_hint(form: AnswerFormat, chinese: bool) -> str:
    if form.kind == "choice":
        joined = "、".join(form.letters) if chinese else ", ".join(form.letters)
        if form.multiple:
            return (
                f"请回复 {joined} 中所有适用的字母。"
                if chinese
                else f"Reply with every letter that applies: {joined}."
            )
        return f"请回复 {joined} 中的一个字母。" if chinese else f"Reply with one letter: {joined}."
    if form.kind == "scale":
        return (
            f"请回复 {form.low}–{form.high} 之间的一个数字。"
            if chinese
            else f"Reply with one number from {form.low} to {form.high}."
        )
    return "请直接写出你对这道题的回答。" if chinese else "Write your own answer to this question."
