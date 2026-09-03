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
from typing import Any

# The RuleSet accepts these bounds; a value outside them is not a shape the
# product would have accepted, so it falls back rather than sizing from it.
MIN_ROUND_COUNT = 2
MAX_ROUND_COUNT = 5
DEFAULT_ROUND_COUNT = 2


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


__all__ = [
    "DEFAULT_ROUND_COUNT",
    "MAX_ROUND_COUNT",
    "MIN_ROUND_COUNT",
    "debate_round_count",
    "expected_turn_count",
]
