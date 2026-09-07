"""Hand back a turn claim that no live preparation is holding.

Preparing a turn claims its Job first, so two workers cannot generate the same
turn twice. The claim is only correct while something is actually preparing:
a warm that stopped without finishing leaves a turn marked ``running`` with a
claim nobody owns, and that claim is what every later attempt asks for. The
Debate then cannot be started, has no ready turn to play, offers no Next, and
raises no failure to retry -- it simply stops, with nothing on screen to press.

Startup already fences these, because a restart is the case the original
design had in mind. This is the same fence for a stop that does not restart
the process.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

LOGGER = logging.getLogger(__name__)

# A turn that reached these is finished work and is never reset.
_SETTLED = ("final_ready", "ready", "completed", "failed")


def release_stalled_turn_claim(db: Any, debate_id: str, turn_id: str) -> bool:
    """Return an unfinished turn and its Job to pending. Returns whether it did.

    Deliberately narrow: it touches one turn, only while that turn is still
    ``running`` or ``pending``, and it never moves finished work. A turn that
    generated successfully keeps everything it produced.
    """

    try:
        row = db.execute(
            text(
                "SELECT generation_status FROM debate_turns "
                "WHERE id=:turn_id AND debate_id=:debate_id"
            ),
            {"turn_id": turn_id, "debate_id": debate_id},
        ).first()
        if row is None or str(row[0]) in _SETTLED:
            return False
        # transcript_hash has to go with it. mark_turn_running only claims a
        # turn whose hash is still null -- that is how it refuses to prepare
        # the same turn twice -- so a turn returned to pending with a hash
        # left on it can never be prepared again by anything. It reads as
        # pending, claims cleanly, and then silently refuses at the last CAS.
        db.execute(
            text(
                "UPDATE debate_turns SET generation_status='pending', "
                "preparation_stage='generation', safe_error_code=NULL, "
                "transcript_hash=NULL "
                "WHERE id=:turn_id AND generation_status='running'"
            ),
            {"turn_id": turn_id},
        )
        db.execute(
            text(
                "UPDATE jobs SET state='pending', claim_token=NULL "
                "WHERE turn_id=:turn_id AND state='running'"
            ),
            {"turn_id": turn_id},
        )
    except Exception:
        # Releasing a claim is a repair, so it must never become the reason a
        # caller fails. The startup fence still covers what this misses.
        LOGGER.exception("Could not release the turn claim for %s", turn_id)
        return False
    return True


__all__ = ["release_stalled_turn_claim"]
