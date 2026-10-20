"""Deterministic guards around the Scorer's assessment_action on free questions.

Owner decisions (2026-10-20, after class):

* A question that only collects a fact (student ID, major, name, class) takes
  any plain statement as its answer. The model must not bounce "2330034002",
  "我的学号是：2330034002" or "人工智能" as off-topic.
* An explicit skip word on its own is a skip, whatever the model said.
* When the model is unsure (it called the reply an answer but did not mark
  it relevant) the student is asked once to confirm. "确认"/"confirm" on the
  next message records the previous message, with no second model judgment;
  anything else is simply the next reply. The pending answer is the previous
  user turn itself, so it survives a refresh without new storage.
* "修改第N题：新答案" / "change my answer to question N: ..." replaces that
  question's answer while the attempt is still in progress (the old record
  stays as history; scoring uses the question's effective answer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CJK = re.compile(r"[\u3400-\u9fff]")
_INFO_PROMPT = re.compile(
    r"学号|专业|姓名|名字|班级|年级|学院|院系|邮箱|手机号|"
    r"student\s*(?:id|number)|\bmajor\b|your\s+name|\bclass\b|\bgrade\b|"
    r"\bdepartment\b|\bemail\b",
    re.IGNORECASE,
)
_SKIP_ONLY = re.compile(
    r"^\s*(?:请|我想|我要)?\s*(?:跳过|略过|下一题|跳过这题|跳过此题|跳过这道题|pass|skip"
    r"(?:\s+(?:this|it|this one|this question))?|next(?:\s+question)?)\s*(?:吧|了|一下)?"
    r"\s*[。.!！~]*\s*$",
    re.IGNORECASE,
)
_CONFIRM_ONLY = re.compile(
    r"^\s*(?:是的?[，,\s]*)?(?:确认|确定|confirm(?:ed)?|yes,?\s*confirm)\s*[。.!！]*\s*$",
    re.IGNORECASE,
)
CONFIRM_MARKERS = ("输入“确认”", 'typing "confirm"')
_EDIT = re.compile(
    r"^\s*(?:我(?:想|要))?(?:修改|更改|改)(?:一下)?第\s*(\d{1,3})\s*题(?:的?(?:答案|回答))?"
    r"\s*(?:[:：,，]|为|成)?\s*(?P<zh>.*)$"
    r"|^\s*(?:please\s+)?change\s+my\s+answer\s+(?:to|for)\s+question\s*(\d{1,3})"
    r"\s*(?:[:：,，]|to)?\s*(?P<en>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def chinese(prompt: str) -> bool:
    return bool(_CJK.search(prompt))


def collects_info(prompt: str) -> bool:
    """Whether a free question just collects a fact about the student."""

    return bool(_INFO_PROMPT.search(prompt))


def is_skip_only(text: str) -> bool:
    return bool(_SKIP_ONLY.match(text))


def is_confirm_only(text: str) -> bool:
    return bool(_CONFIRM_ONLY.match(text))


def confirm_prompt(is_chinese: bool) -> str:
    return (
        "请确认这是你的回答，输入“确认”；如果不是，请重新输入。"
        if is_chinese
        else 'Please confirm this is your answer by typing "confirm"; if not, please re-enter it.'
    )


def asked_to_confirm(texts: list[str | None]) -> bool:
    return any(text and any(marker in text for marker in CONFIRM_MARKERS) for text in texts)


@dataclass(frozen=True)
class EditRequest:
    number: int  # as shown to the student (第 N 题)
    answer: str  # may be empty: the student named the question but no answer


def edit_request(text: str) -> EditRequest | None:
    match = _EDIT.match(text)
    if match is None:
        return None
    number = match.group(1) or match.group(3)
    answer = (match.group("zh") if match.group(1) else match.group("en")) or ""
    return EditRequest(number=int(number), answer=answer.strip())


def edit_hint(is_chinese: bool, number: int | None = None) -> str:
    n = str(number) if number is not None else "N"
    return (
        f"要修改答案，请在一条消息里发送「修改第{n}题：新答案」。"
        if is_chinese
        else f'To change an answer, send "change my answer to question {n}: <new answer>".'
    )


__all__ = [
    "CONFIRM_MARKERS",
    "EditRequest",
    "asked_to_confirm",
    "chinese",
    "collects_info",
    "confirm_prompt",
    "edit_hint",
    "edit_request",
    "is_confirm_only",
    "is_skip_only",
]
