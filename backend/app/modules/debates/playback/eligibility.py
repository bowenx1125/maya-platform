"""Shared downstream eligibility for a complete finished classroom debate.

An early teacher Finish intentionally uses ``Debate.status=debate_finished``
while its playback remains ``stopped``.  Downstream modules must therefore
check the complete public plan for the Debate's own round count and the
terminal playback state, not the Debate status alone.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.debates.models import Debate, DebateParticipant, DebateTurn, PlaybackState
from app.modules.debates.round_count import expected_turn_count


def has_complete_finished_playback(db: Session, debate_id: str) -> bool:
    """Return whether a Debate is eligible for downstream classroom history.

    This is deliberately a pure read helper.  It recognizes both the normal
    ``debate_finished`` state and the later ``completed`` report state, while
    rejecting partial Finish, failed/stopped runs, incomplete plans and any
    playback that still has active authority.
    """

    debate = db.get(Debate, debate_id)
    if debate is None or debate.status not in {"debate_finished", "completed"}:
        return False
    participants = list(
        db.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == debate_id)
            .order_by(DebateParticipant.order_index, DebateParticipant.id)
        ).all()
    )
    if len(participants) < 2:
        return False
    turns = list(
        db.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == debate_id)
            .order_by(DebateTurn.turn_index, DebateTurn.id)
        ).all()
    )
    expected_count = expected_turn_count(debate, len(participants))
    if len(turns) != expected_count or [row.turn_index for row in turns] != list(
        range(expected_count)
    ):
        return False
    if any(
        row.generation_status != "final_ready"
        or row.publication_status != "public"
        or not isinstance(row.speech, str)
        or not row.speech
        for row in turns
    ):
        return False
    playback = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
    if playback is None:
        return False
    # Deliberately not ``playback.status == "completed"``.  A turn only becomes
    # public by being played, so the loop above already proves this debate ran
    # its whole plan.  Playback status is transient and later, unrelated
    # actions legitimately move it: starting the next debate revokes this one,
    # an operator reset stops it, a restart re-fences it.  Reading it here made
    # a finished lesson lose its classroom-interaction entry because a
    # different debate had since been started -- history stopped being
    # reviewable for a reason that had nothing to do with this debate.
    if playback.mode != "live":
        return False
    return not any(
        getattr(playback, field, None) is not None
        for field in (
            "controller_epoch",
            "controller_owner_connection",
            "pending_action",
            "pending_ticket_hash",
            "pending_media_command_id",
        )
    )
