"""Display labels for Agent and Team versions.

The nth saved version reads ``1.0 + (n - 1) * 0.1`` with one decimal:
1st ``V1.0``, 6th ``V1.5``, 10th ``V1.9``, 11th ``V2.0``, 12th ``V2.1``.
Integer arithmetic keeps it exact (no ``0.1`` float drift).

Only the label is derived; stored ``version_seq`` values are unchanged.
Agents count ``version_seq`` from 0 (the first draft) and Teams from 1, so
each has a small adapter that turns its sequence into the ordinal ``n``.
"""

from __future__ import annotations


def version_label(ordinal: int) -> str:
    """Label for the ``ordinal``-th version (1-based); below 1 reads V1.0."""

    index = max(0, int(ordinal) - 1)
    return f"V{1 + index // 10}.{index % 10}"


def agent_version_label(version_seq: int) -> str:
    """Agent versions start at ``version_seq`` 0, so seq 0 is the 1st."""

    return version_label(int(version_seq) + 1)


def team_version_label(version_seq: int) -> str:
    """Team versions start at ``version_seq`` 1, so seq 1 is the 1st."""

    return version_label(int(version_seq))
