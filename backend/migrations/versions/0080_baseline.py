"""Baseline: the schema as of 0080_drop_playback_rate (squash, 2026-10-25).

Revisions 0001-0080 were replaced by this one file once production was
confirmed at 0080_drop_playback_rate. It keeps that revision id, so a database
already at 0080 sees nothing to do. A new, empty database is created from the
models and stamped at head by ``Database.upgrade_schema``, exactly as before;
this file therefore changes nothing. A database below 0080 cannot be upgraded
by this checkout: deploy the last release before the squash first.

Revision ID: 0080_drop_playback_rate
Revises:
"""

from collections.abc import Sequence

revision: str = "0080_drop_playback_rate"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to apply: this is the starting point of the history."""


def downgrade() -> None:
    raise RuntimeError(
        "0080_drop_playback_rate is the squashed baseline; there is nothing below it."
    )
