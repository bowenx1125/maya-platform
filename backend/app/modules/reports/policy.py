"""Deterministic, provider-neutral M14 Mock policies and validators."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from .schemas import (
    BarrageInsightInput,
    InsightAssignmentCandidate,
    InsightItemCandidate,
    MockBarrageInsightResult,
    ReportInputManifestV1,
)

MOCK_BARRAGE_INSIGHT_POLICY_KEY = "mock_barrage_insight_v1"
MOCK_MAYA_REPORT_POLICY_KEY = "mock_maya_report_v1"
MOCK_MAYA_REPORT_VALIDATOR_KEY = "mock_maya_report_validator_v1"

_LATIN_QUESTION_MARKERS = frozenset(
    {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "can",
        "could",
        "would",
        "should",
        "do",
        "does",
        "did",
        "is",
        "are",
        "was",
        "were",
    }
)
_CJK_QUESTION_MARKERS = (
    "谁",
    "什么",
    "何时",
    "哪里",
    "为什么",
    "怎么",
    "如何",
    "是否",
    "能否",
    "应否",
)
_LATIN_CHALLENGE_MARKERS = frozenset(
    {
        "disagree",
        "oppose",
        "challenge",
        "doubt",
        "concern",
        "however",
        "but",
        "not",
        "no",
    }
)
_CJK_CHALLENGE_MARKERS = (
    "反对",
    "不同意",
    "质疑",
    "怀疑",
    "担心",
    "但是",
    "然而",
    "不",
)
_FORBIDDEN_BOUNDARY_KEYS = frozenset(
    {
        "nickname",
        "author",
        "author_id",
        "user_id",
        "participant_id",
        "vote",
        "vote_id",
        "device_id",
        "device",
        "session_id",
        "student_id",
        "username",
    }
)
_WORD_RUN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_barrage_text(value: str) -> str:
    """Return the exact v1 grouping key (NFKC, casefold, Unicode whitespace)."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized, flags=re.UNICODE).strip()


def has_unicode_letter_or_number(value: str) -> bool:
    return any(unicodedata.category(char)[0] in {"L", "N"} for char in value)


def _tokens(value: str) -> set[str]:
    # ``[^\W_]`` is the Unicode letter/number run equivalent for the Python
    # runtime, and unlike ``\w`` excludes underscore.  It keeps CJK runs
    # available for the direct-substring marker checks below.
    return {token.casefold() for token in _WORD_RUN_RE.findall(value)}


def classify_barrage_text(value: str) -> str:
    """Classify with the frozen question > challenge > support priority."""

    folded = value.casefold()
    tokens = _tokens(folded)
    if "?" in value or tokens.intersection(_LATIN_QUESTION_MARKERS):
        return "question"
    if any(marker in folded for marker in _CJK_QUESTION_MARKERS):
        return "question"
    if tokens.intersection(_LATIN_CHALLENGE_MARKERS):
        return "challenge"
    if any(marker in folded for marker in _CJK_CHALLENGE_MARKERS):
        return "challenge"
    return "support"


def _boundary_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, BarrageInsightInput):
        return {"message_id": value.message_id, "raw_text": value.raw_text}
    if isinstance(value, Mapping):
        keys = {str(key) for key in value}
        forbidden = {key for key in keys if key.casefold() in _FORBIDDEN_BOUNDARY_KEYS}
        if forbidden:
            raise ValueError(
                f"de-identified insight input contains forbidden keys: {sorted(forbidden)}"
            )
        if keys != {"message_id", "raw_text"}:
            raise ValueError("insight input must contain exactly message_id and raw_text")
        return value
    attributes = vars(value) if hasattr(value, "__dict__") else {}
    forbidden = {str(key) for key in attributes if str(key).casefold() in _FORBIDDEN_BOUNDARY_KEYS}
    if forbidden:
        raise ValueError(
            f"de-identified insight input contains forbidden keys: {sorted(forbidden)}"
        )
    raise TypeError("insight input must be BarrageInsightInput or a closed mapping")


def validate_deidentified_input(
    messages: Iterable[BarrageInsightInput | Mapping[str, Any]],
) -> list[BarrageInsightInput]:
    """Validate and materialize the structural nickname-free boundary."""

    result: list[BarrageInsightInput] = []
    for value in messages:
        mapping = _boundary_mapping(value)
        result.append(BarrageInsightInput.model_validate(mapping))
    message_ids = [row.message_id for row in result]
    if len(set(message_ids)) != len(message_ids):
        raise ValueError("insight input message IDs must be unique")
    return result


def mock_barrage_insight_v1(
    messages: Iterable[BarrageInsightInput | Mapping[str, Any]],
) -> MockBarrageInsightResult:
    """Produce the exact deterministic M14 Mock insight partition.

    The input order is the frozen BarrageMessage sequence.  A normalized
    duplicate group receives one item and one included assignment per source
    message.  Only messages with no Unicode letter/number are filtered.
    """

    typed = validate_deidentified_input(messages)
    grouped: dict[str, InsightItemCandidate] = {}
    assignments: list[InsightAssignmentCandidate] = []
    for order, message in enumerate(typed):
        normalized = normalize_barrage_text(message.raw_text)
        if not has_unicode_letter_or_number(normalized):
            assignments.append(
                InsightAssignmentCandidate(
                    message_id=message.message_id,
                    disposition="filtered",
                    item_key=None,
                    filter_reason=f"{MOCK_BARRAGE_INSIGHT_POLICY_KEY}:no_letter_or_number",
                )
            )
            continue
        item = grouped.get(normalized)
        if item is None:
            item = InsightItemCandidate(
                item_key=normalized,
                category=cast(Any, classify_barrage_text(normalized)),
                summary=message.raw_text,
                first_order=order,
            )
            grouped[normalized] = item
        assignments.append(
            InsightAssignmentCandidate(
                message_id=message.message_id,
                disposition="included",
                item_key=normalized,
                filter_reason=None,
            )
        )
    items = sorted(grouped.values(), key=lambda item: (item.first_order, item.item_key))
    included_count = sum(item.disposition == "included" for item in assignments)
    filtered_count = sum(item.disposition == "filtered" for item in assignments)
    result = MockBarrageInsightResult(
        items=items,
        assignments=assignments,
        included_count=included_count,
        filtered_count=filtered_count,
    )
    validate_insight_partition(
        frozen_message_ids=[row.message_id for row in typed],
        result=result,
    )
    return result


def validate_insight_partition(
    frozen_message_ids: Sequence[UUID | str],
    result: MockBarrageInsightResult | Mapping[str, Any],
) -> MockBarrageInsightResult:
    """Prove the exact include/filter partition and code-derived counts."""

    parsed = (
        result
        if isinstance(result, MockBarrageInsightResult)
        else MockBarrageInsightResult.model_validate(result)
    )
    frozen = [UUID(str(value)) for value in frozen_message_ids]
    frozen_set = set(frozen)
    item_keys = {item.item_key for item in parsed.items}
    if len(item_keys) != len(parsed.items):
        raise ValueError("insight output contains duplicate item keys")
    assigned: list[UUID] = []
    included_counts: dict[str, int] = {key: 0 for key in item_keys}
    for assignment in parsed.assignments:
        if assignment.message_id in assigned:
            raise ValueError("a frozen message is assigned more than once")
        if assignment.message_id not in frozen_set:
            raise ValueError("insight output contains an unknown message ID")
        assigned.append(assignment.message_id)
        if assignment.disposition == "included":
            if assignment.item_key not in item_keys or assignment.filter_reason is not None:
                raise ValueError("included assignment has invalid item/reason")
            included_counts[assignment.item_key] += 1
        else:
            if assignment.item_key is not None:
                raise ValueError("filtered assignment must not reference an item")
            expected = f"{MOCK_BARRAGE_INSIGHT_POLICY_KEY}:"
            if not assignment.filter_reason or not assignment.filter_reason.startswith(expected):
                raise ValueError("filtered assignment needs a versioned reason")
    if set(assigned) != frozen_set or len(assigned) != len(frozen):
        raise ValueError("insight assignments do not form an exact frozen partition")
    if parsed.included_count != sum(included_counts.values()):
        raise ValueError("included_count is not derived from assignments")
    if parsed.filtered_count != len(frozen) - parsed.included_count:
        raise ValueError("filtered_count is not derived from assignments")
    for item in parsed.items:
        if included_counts[item.item_key] != sum(
            1
            for assignment in parsed.assignments
            if assignment.disposition == "included" and assignment.item_key == item.item_key
        ):
            raise ValueError("item count does not match assignment rows")
    return parsed


def canonical_insight_output_json(result: MockBarrageInsightResult) -> str:
    """Serialize policy output for deterministic equality tests."""

    return json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def report_input_hash(manifest: ReportInputManifestV1) -> str:
    return manifest.input_hash()


__all__ = [
    "MOCK_BARRAGE_INSIGHT_POLICY_KEY",
    "MOCK_MAYA_REPORT_POLICY_KEY",
    "MOCK_MAYA_REPORT_VALIDATOR_KEY",
    "canonical_insight_output_json",
    "classify_barrage_text",
    "has_unicode_letter_or_number",
    "mock_barrage_insight_v1",
    "normalize_barrage_text",
    "report_input_hash",
    "validate_deidentified_input",
    "validate_insight_partition",
]
