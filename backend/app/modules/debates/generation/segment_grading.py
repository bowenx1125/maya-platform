"""Deterministic structural grading for the optional paragraph support mode.

The provider chooses a mode and local source aliases, but the server owns the
closed consistency rules and the point mapping.  This module therefore grades
only a persisted association shape: it does not inspect source prose and never
claims that a model-selected source is semantically correct.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from .segments import SegmentSupportMode

SegmentGrade = Literal["direct", "contextual", "no_match", "ungraded"]

SEGMENT_GRADE_POINTS: Mapping[SegmentGrade, int] = {
    "direct": 5,
    "contextual": 2,
    "no_match": 0,
    "ungraded": 0,
}
_SUPPORT_MODES = frozenset(("direct", "contextual", "no_match"))


class SegmentGradingError(ValueError):
    """A saved paragraph cannot be safely converted into a grade."""

    def __init__(self, message: str = "segment grading input is invalid", *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _source_ids(value: object) -> tuple[str, ...]:
    raw = _field(value, "source_ids")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise SegmentGradingError(code="source_reference_invalid")
    source_ids = tuple(raw)
    if any(not isinstance(item, str) or not item.strip() for item in source_ids):
        raise SegmentGradingError(code="source_reference_invalid")
    if len(source_ids) != len(set(source_ids)):
        raise SegmentGradingError(code="source_reference_invalid")
    return cast(tuple[str, ...], source_ids)


def _mode(value: object) -> SegmentSupportMode | None:
    raw = _field(value, "support_mode")
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in _SUPPORT_MODES:
        raise SegmentGradingError(code="support_mode_invalid")
    return cast(SegmentSupportMode, raw)


@dataclass(frozen=True, slots=True)
class GradedSegment:
    """One paragraph's structural grade and its immutable source aliases."""

    support_mode: SegmentSupportMode | None
    grade: SegmentGrade
    points: int
    source_ids: tuple[str, ...]

    @property
    def is_graded(self) -> bool:
        return self.grade != "ungraded"


def grade_segment(
    value: object,
    *,
    valid_source_ids: Collection[str] | None = None,
) -> GradedSegment:
    """Grade one paragraph after checking mode/source consistency.

    ``valid_source_ids`` is the immutable source set for the turn.  Passing it
    makes the report path fail closed for a stale or forged canonical source
    ID; omitting it is useful for the already-bound local protocol path, whose
    reference validation has happened in ``validate_segment_output``.
    """

    source_ids = _source_ids(value)
    mode = _mode(value)
    if valid_source_ids is not None and any(item not in valid_source_ids for item in source_ids):
        raise SegmentGradingError(code="source_reference_invalid")
    if mode in {"direct", "contextual"} and not source_ids:
        raise SegmentGradingError(code="support_mode_source_mismatch")
    if mode == "no_match" and source_ids:
        raise SegmentGradingError(code="support_mode_source_mismatch")
    if mode is None:
        return GradedSegment(None, "ungraded", SEGMENT_GRADE_POINTS["ungraded"], source_ids)
    return GradedSegment(mode, mode, SEGMENT_GRADE_POINTS[mode], source_ids)


@dataclass(frozen=True, slots=True)
class SegmentGradeSummary:
    """Deterministic counts and points for one set of paragraphs."""

    direct_count: int = 0
    contextual_count: int = 0
    no_match_count: int = 0
    ungraded_count: int = 0

    @property
    def paragraph_count(self) -> int:
        return self.direct_count + self.contextual_count + self.no_match_count + self.ungraded_count

    @property
    def graded_count(self) -> int:
        return self.direct_count + self.contextual_count + self.no_match_count

    @property
    def total_points(self) -> int:
        return self.direct_count * 5 + self.contextual_count * 2

    @property
    def score(self) -> int:
        """Readable alias for the same deterministic point total."""

        return self.total_points

    def as_payload(self) -> dict[str, int]:
        return {
            "direct_count": self.direct_count,
            "contextual_count": self.contextual_count,
            "no_match_count": self.no_match_count,
            "ungraded_count": self.ungraded_count,
            "graded_count": self.graded_count,
            "paragraph_count": self.paragraph_count,
            "total_points": self.total_points,
        }


def summarize_segments(
    values: Sequence[object],
    *,
    valid_source_ids: Collection[str] | None = None,
) -> SegmentGradeSummary:
    """Aggregate paragraphs without inferring a missing mode."""

    counts = {
        "direct": 0,
        "contextual": 0,
        "no_match": 0,
        "ungraded": 0,
    }
    for value in values:
        counts[grade_segment(value, valid_source_ids=valid_source_ids).grade] += 1
    return SegmentGradeSummary(
        direct_count=counts["direct"],
        contextual_count=counts["contextual"],
        no_match_count=counts["no_match"],
        ungraded_count=counts["ungraded"],
    )


@dataclass(frozen=True, slots=True)
class AgentGradeSummary:
    """One Agent's score derived from its saved public paragraphs."""

    participant_id: str
    direct_count: int
    contextual_count: int
    no_match_count: int
    ungraded_count: int

    @property
    def paragraph_count(self) -> int:
        return self.direct_count + self.contextual_count + self.no_match_count + self.ungraded_count

    @property
    def graded_count(self) -> int:
        return self.direct_count + self.contextual_count + self.no_match_count

    @property
    def total_points(self) -> int:
        return self.direct_count * 5 + self.contextual_count * 2

    @property
    def score(self) -> int:
        return self.total_points

    def as_payload(self) -> dict[str, object]:
        return {
            "participant_id": self.participant_id,
            "direct_count": self.direct_count,
            "contextual_count": self.contextual_count,
            "no_match_count": self.no_match_count,
            "ungraded_count": self.ungraded_count,
            "graded_count": self.graded_count,
            "paragraph_count": self.paragraph_count,
            "total_points": self.total_points,
        }


def _turn_identity(value: object) -> tuple[str, str, tuple[object, ...]]:
    turn_id = _field(value, "turn_id")
    participant_id = _field(value, "participant_id")
    segments = _field(value, "segments")
    if not isinstance(turn_id, str) or not turn_id:
        raise SegmentGradingError(code="turn_identity_invalid")
    if not isinstance(participant_id, str) or not participant_id:
        raise SegmentGradingError(code="turn_identity_invalid")
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes, bytearray)):
        raise SegmentGradingError(code="segment_result_invalid")
    return turn_id, participant_id, tuple(segments)


def _turn_fingerprint(participant_id: str, segments: Sequence[object]) -> str:
    rows: list[dict[str, object]] = []
    for segment in segments:
        source_ids = _source_ids(segment)
        mode = _mode(segment)
        rows.append(
            {"source_ids": list(source_ids), "support_mode": mode, "text": _field(segment, "text")}
        )
    try:
        return json.dumps(
            {"participant_id": participant_id, "segments": rows},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SegmentGradingError(code="segment_result_invalid") from exc


def aggregate_agent_scores(
    turns: Sequence[object],
    *,
    valid_source_ids_by_turn: Mapping[str, Collection[str]] | None = None,
) -> tuple[AgentGradeSummary, ...]:
    """Aggregate one score per Agent from unique saved turn IDs.

    Exact duplicate turn rows are treated as replay projections and counted
    once.  A duplicate ID with different public content is rejected because a
    report must never choose between two immutable interpretations.
    """

    seen_turns: dict[str, str] = {}
    by_participant: dict[str, SegmentGradeSummary] = {}
    for value in turns:
        turn_id, participant_id, segments = _turn_identity(value)
        fingerprint = _turn_fingerprint(participant_id, segments)
        previous = seen_turns.get(turn_id)
        if previous is not None:
            if previous != fingerprint:
                raise SegmentGradingError(code="duplicate_turn_conflict")
            continue
        seen_turns[turn_id] = fingerprint
        source_ids = (
            valid_source_ids_by_turn.get(turn_id) if valid_source_ids_by_turn is not None else None
        )
        summary = summarize_segments(segments, valid_source_ids=source_ids)
        prior = by_participant.get(participant_id)
        if prior is None:
            by_participant[participant_id] = summary
        else:
            by_participant[participant_id] = SegmentGradeSummary(
                direct_count=prior.direct_count + summary.direct_count,
                contextual_count=prior.contextual_count + summary.contextual_count,
                no_match_count=prior.no_match_count + summary.no_match_count,
                ungraded_count=prior.ungraded_count + summary.ungraded_count,
            )
    return tuple(
        AgentGradeSummary(
            participant_id=participant_id,
            direct_count=summary.direct_count,
            contextual_count=summary.contextual_count,
            no_match_count=summary.no_match_count,
            ungraded_count=summary.ungraded_count,
        )
        for participant_id, summary in by_participant.items()
    )


# Short aliases keep call sites readable while the explicit names remain the
# stable public helpers for focused tests and future report projections.
grade_segments = summarize_segments
aggregate_segment_grades = summarize_segments


__all__ = [
    "AgentGradeSummary",
    "GradedSegment",
    "SEGMENT_GRADE_POINTS",
    "SegmentGrade",
    "SegmentGradeSummary",
    "SegmentGradingError",
    "aggregate_agent_scores",
    "aggregate_segment_grades",
    "grade_segment",
    "grade_segments",
    "summarize_segments",
]
