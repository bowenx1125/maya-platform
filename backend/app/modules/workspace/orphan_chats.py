"""Free Chats whose running turn lost its process (see core/chat_turn_locks).

Every backend process sweeps. A claimed turn that no live process holds is
only a suspect the first time it is seen: a runner takes its lock just after
its claim commits, so one sighting can be that gap. The same claim (same turn,
same revision) unheld again on the next sweep is an orphan, and it is settled
exactly as startup recovery settles it, one Chat per transaction.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.chat_turn_locks import turn_is_held
from app.core.db import Database
from app.core.models import ProviderOperation

from .models import Conversation

LOGGER = logging.getLogger("maya.chat_turns")

SWEEP_SECONDS = 60.0

Claim = tuple[str, int]


class OrphanChatSweeper:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._suspects: dict[str, Claim] = {}

    def sweep(self) -> int:
        """One pass; returns how many Chats were freed."""

        unheld: dict[str, Claim] = {}
        with self.database.session_factory() as db:
            claims = db.execute(
                select(
                    Conversation.id, Conversation.active_request_id, Conversation.revision
                ).where(Conversation.active_request_id.is_not(None))
            ).all()
            db.rollback()
            for conversation_id, turn_id, revision in claims:
                held = turn_is_held(db.connection(), str(turn_id))
                db.rollback()  # ends the probe's transaction, releasing it
                if not held:
                    unheld[str(conversation_id)] = (str(turn_id), int(revision))
        orphans = {
            conversation_id: claim
            for conversation_id, claim in unheld.items()
            if self._suspects.get(conversation_id) == claim
        }
        self._suspects = {
            conversation_id: claim
            for conversation_id, claim in unheld.items()
            if conversation_id not in orphans
        }
        freed = 0
        for conversation_id, claim in orphans.items():
            try:
                freed += recover_orphaned_chat(self.database, conversation_id, claim)
            except Exception:
                LOGGER.exception(
                    "Orphaned chat recovery failed conversation_id=%s", conversation_id
                )
        return freed


def recover_orphaned_chat(database: Database, conversation_id: str, claim: Claim) -> int:
    """Settle one Chat if it still has exactly ``claim`` and nobody holds it."""

    from app.modules.runtime_tools.recovery import (
        accepted_chat_stage_complete,
        recover_single_chat_runs,
    )
    from app.providers.control_repository import ProviderRepository

    from .team_runtime import recover_team_runs

    turn_id, revision = claim
    with database.session_factory() as db:
        row = db.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update(skip_locked=True)
        )
        if row is None or (row.active_request_id, row.revision) != (turn_id, revision):
            return 0
        # Held for the rest of this transaction: no runner can pick the turn
        # up between this check and the commit.
        if turn_is_held(db.connection(), turn_id):
            return 0
        single = row.entry_kind == "agent"
        if single:
            recover_single_chat_runs(db, {conversation_id})
        else:
            recover_team_runs(db, {conversation_id})
        db.commit()
    if single:
        # Startup settles a Single Chat's own ledger rows after the Chat, the
        # same order here: an operation left "sending" becomes unknown.
        with database.session_factory() as db:
            stranded = [
                (operation.id, accepted_chat_stage_complete(db, operation))
                for operation in db.scalars(
                    select(ProviderOperation).where(
                        ProviderOperation.provider_operation == "llm_agent_chat",
                        ProviderOperation.scope_id == conversation_id,
                        ProviderOperation.logical_item_id == turn_id,
                        ProviderOperation.state.in_(("reserved", "sending", "accepted")),
                    )
                )
            ]
        for operation_id, stage_complete in stranded:
            ProviderRepository(database).recover_one(
                operation_id, staged_response_complete=stage_complete
            )
    LOGGER.warning(
        "Recovered orphaned chat turn conversation_id=%s turn_id=%s", conversation_id, turn_id
    )
    return 1
