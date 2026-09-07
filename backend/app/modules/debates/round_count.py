"""The one place a Debate's round count is read.

``round_count`` is not a column on ``debates``: it is a field of the frozen
``rule_snapshot_json``. Reading it as an attribute silently yields nothing, and
four separate places had instead hard-coded two rounds — the shape the original
fixtures used. A three-Agent four-round debate therefore looked incomplete to
every one of them: classroom interaction answered 404, the report refused to
generate, and the teacher's interaction button disappeared.

Anything that needs to know how many turns a Debate plans should call
``debate_round_count`` and multiply, never assume.
"""

from __future__ import annotations

import json
from typing import Any, Literal

# The RuleSet accepts these bounds; a value outside them is not a shape the
# product would have accepted, so it falls back rather than sizing from it.
MIN_ROUND_COUNT = 2
MAX_ROUND_COUNT = 5
DEFAULT_ROUND_COUNT = 2
FOUR_ROUND_TEACHING_PROTOCOL: Literal["four_round_v1"] = "four_round_v1"


def _valid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if MIN_ROUND_COUNT <= value <= MAX_ROUND_COUNT else None


def debate_round_count(debate: Any) -> int:
    """How many rounds this Debate plans, from its own frozen rule snapshot."""

    direct = _valid(getattr(debate, "round_count", None))
    if direct is not None:
        return direct
    try:
        snapshot = json.loads(str(getattr(debate, "rule_snapshot_json", "{}") or "{}"))
    except (TypeError, ValueError):
        return DEFAULT_ROUND_COUNT
    if not isinstance(snapshot, dict):
        return DEFAULT_ROUND_COUNT
    return _valid(snapshot.get("round_count")) or DEFAULT_ROUND_COUNT


def expected_turn_count(debate: Any, participant_count: int) -> int:
    """Every participant speaks once per round."""

    return participant_count * debate_round_count(debate)


def uses_segment_protocol(debate: Any) -> bool:
    """Old immutable snapshots retain their original generation protocol."""

    try:
        snapshot = json.loads(str(getattr(debate, "rule_snapshot_json", "{}") or "{}"))
    except (TypeError, ValueError):
        return False
    return isinstance(snapshot, dict) and snapshot.get("turn_protocol") == "segments_v2"


def debate_teaching_protocol(debate: Any) -> Literal["four_round_v1"] | None:
    """Only an explicit immutable marker enables the new classroom rules."""

    direct = getattr(debate, "teaching_protocol", None)
    if direct == FOUR_ROUND_TEACHING_PROTOCOL:
        return FOUR_ROUND_TEACHING_PROTOCOL
    try:
        snapshot = json.loads(str(getattr(debate, "rule_snapshot_json", "{}") or "{}"))
    except (TypeError, ValueError):
        return None
    if (
        isinstance(snapshot, dict)
        and snapshot.get("teaching_protocol") == FOUR_ROUND_TEACHING_PROTOCOL
    ):
        return FOUR_ROUND_TEACHING_PROTOCOL
    return None


def uses_four_round_protocol(debate: Any) -> bool:
    return debate_teaching_protocol(debate) == FOUR_ROUND_TEACHING_PROTOCOL


def visible_turn_predecessors(debate: Any, turn: Any, turns: list[Any]) -> list[Any]:
    """Resolve the exact persisted input dependency without changing old plans."""

    if uses_four_round_protocol(debate):
        if int(turn.round_no) == 1:
            return []
        return [row for row in turns if int(row.turn_index) < int(turn.turn_index)]
    if str(getattr(debate, "rule_set_id", "")) == "ordered_multi_expert_mutual_learning_v1":
        return [row for row in turns if int(row.round_no) < int(turn.round_no)]
    return [row for row in turns if int(row.turn_index) < int(turn.turn_index)]


def preview_turn_count(debate: Any, participant_count: int) -> int:
    rounds = debate_round_count(debate) - int(uses_segment_protocol(debate))
    return participant_count * rounds


__all__ = [
    "DEFAULT_ROUND_COUNT",
    "MAX_ROUND_COUNT",
    "MIN_ROUND_COUNT",
    "debate_round_count",
    "expected_turn_count",
    "FOUR_ROUND_TEACHING_PROTOCOL",
    "debate_teaching_protocol",
    "uses_four_round_protocol",
    "visible_turn_predecessors",
]
