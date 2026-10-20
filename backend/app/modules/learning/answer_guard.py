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

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Literal

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


# ---------------------------------------------------------------------------
# Relevance guard (owner design, 2026-10-20 evening). The model only gives a
# category (answer / off_topic / other) and a confidence; these rules decide.
#
# 1. off_topic directly only when confidence >= OFF_TOPIC_CONFIDENCE and the
#    question has not been judged off-topic before; anything else that is not
#    a sure answer asks the student to confirm.
# 2. After one off_topic judgment on a question, the next input can never be
#    off_topic again: only answer or other.
# 3. An input equal or nearly equal to the last unrecorded one is recorded
#    without the model.
# 4. 确认 records the pending reply.
# 5. With off_topic excluded and other excluded (a plain statement, not a
#    question/help request), the reply is the answer and is recorded.
# State lives on the attempt question row (guard_state_json), not the model.
# ---------------------------------------------------------------------------

OFF_TOPIC_CONFIDENCE = 0.9
ANSWER_CONFIDENCE = 0.6
SIMILARITY = 0.85

Verdict = Literal["record", "off_topic", "confirm", "other_confirm"]


@dataclass
class GuardState:
    off_topic_judged: bool = False
    pending_text: str | None = None
    last_text: str | None = None
    rejections: int = 0
    history: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, raw: str | None) -> GuardState:
        if not raw:
            return cls()
        try:
            data = json.loads(raw)
        except ValueError:
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        try:
            return cls(**known)
        except TypeError:
            return cls()

    def dump(self) -> str:
        data = asdict(self)
        data["history"] = data["history"][-5:]
        return json.dumps(data, ensure_ascii=False)


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


def nearly_same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return a.strip() == b.strip()
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= SIMILARITY


_QUESTION_LIKE = re.compile(
    r"[?？]\s*$|吗\s*[。.!！]*$|^\s*(?:什么|怎么|为什么|如何|能不能|可以|请问|帮我|提示|"
    r"what|how|why|can you|could you|help|hint)\b",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    """A question back or help request: the one kind of 'other' a statement is not."""

    return bool(_QUESTION_LIKE.search(text.strip()))


def model_category(
    classification: str, category: str | None, relevant: bool | None
) -> Literal["answer", "off_topic", "other"]:
    if category in ("answer", "off_topic", "other"):
        return category  # type: ignore[return-value]
    if classification in ("answer_only", "answer_with_restricted_request"):
        return "answer" if relevant is not False else "other"
    if classification == "off_topic":
        return "off_topic"
    return "other"


def decide(
    state: GuardState,
    text: str,
    *,
    category: Literal["answer", "off_topic", "other"],
    confidence: float | None,
    statement: bool,
) -> Verdict:
    """The program's rules; the model's output is only an input here."""

    # Rule 3: the same reply again means the earlier judgment was wrong.
    if nearly_same(text, state.last_text):
        return "record"
    sure = confidence if confidence is not None else 0.5
    if category == "answer" and sure >= ANSWER_CONFIDENCE:
        return "record"
    if state.off_topic_judged or state.rejections > 0:
        # Rule 2: off_topic is excluded. Rule 5: a plain statement also
        # excludes other, so it must be the answer.
        if statement and not looks_like_question(text):
            return "record"
        return "other_confirm"
    if category == "off_topic" and sure >= OFF_TOPIC_CONFIDENCE:
        return "off_topic"
    if category == "other" and not statement:
        return "other_confirm"
    return "confirm"


__all__ = [
    "ANSWER_CONFIDENCE",
    "OFF_TOPIC_CONFIDENCE",
    "GuardState",
    "decide",
    "looks_like_question",
    "model_category",
    "nearly_same",
    "normalize",
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
