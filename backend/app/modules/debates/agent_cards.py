"""Freeze Agent-owned cards into Debate participants without Debate-scoped calls."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.models import Agent, AgentDebateCard
from app.modules.agents.debate_cards import ensure_agent_card
from app.modules.agents.markdown import markdown_hash
from app.modules.debates.cards import stored_card
from app.modules.debates.models import DebateParticipant
from app.modules.debates.owned_copies import frozen_owner

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CardSnapshot:
    card_status: str
    card_json: str | None
    card_safe_error_code: str | None


def _fallback(row: DebateParticipant, code: str) -> _CardSnapshot:
    LOGGER.warning("debate_agent_card_fallback participant_id=%s code=%s", row.id, code)
    return _CardSnapshot("fallback", None, code)


def _checked_snapshot(row: DebateParticipant, card: _CardSnapshot) -> _CardSnapshot:
    try:
        stored_card(card)
    except ValueError:
        return _fallback(row, "debate_card_invalid")
    return card


def _matching_card(db: Session, row: DebateParticipant, markdown: str) -> _CardSnapshot | None:
    values = db.execute(
        select(
            AgentDebateCard.card_status,
            AgentDebateCard.card_json,
            AgentDebateCard.card_safe_error_code,
        ).where(
            AgentDebateCard.agent_id == row.agent_id,
            AgentDebateCard.agent_md_hash == markdown_hash(markdown),
            AgentDebateCard.card_status.in_(("ready", "fallback")),
        )
    ).first()
    return _checked_snapshot(row, _CardSnapshot(*values)) if values is not None else None


def copy_stored_agent_card(db: Session, row: DebateParticipant) -> None:
    if row.card_status != "compiling":
        return
    card = _matching_card(db, row, str(row.agent_md_snapshot or ""))
    if card is not None:
        row.card_status, row.card_json, row.card_safe_error_code = (
            card.card_status,
            card.card_json,
            card.card_safe_error_code,
        )


def ensure_participant_agent_card(db: Session, row: DebateParticipant, settings: Settings) -> None:
    if row.card_status != "compiling":
        return
    try:
        owner = frozen_owner(db, row)
        # The Agent service commits its claim and ledger independently. Never
        # let those commits publish unrelated preparation state in this Session.
        with Session(db.get_bind().engine, expire_on_commit=False) as agent_db:
            card = _matching_card(agent_db, row, owner.agent_md)
            if card is None:
                agent = agent_db.get(Agent, row.agent_id) if row.agent_id else None
                if (
                    agent is None
                    or agent.deleted_at is not None
                    or agent.course_id != owner.course_id
                    or agent.group_id != owner.group_id
                    or owner.version_id is None
                ):
                    card = _fallback(row, "debate_card_preflight_blocked")
                else:
                    compiled = ensure_agent_card(
                        agent_db,
                        agent.id,
                        settings,
                        version_id=owner.version_id,
                        markdown=owner.agent_md,
                        wait=True,
                    )
                    if (
                        compiled is None
                        or compiled.agent_md_hash != markdown_hash(owner.agent_md)
                        or compiled.card_status not in {"ready", "fallback"}
                    ):
                        card = _fallback(row, "debate_card_preflight_blocked")
                    else:
                        card = _checked_snapshot(
                            row,
                            _CardSnapshot(
                                compiled.card_status,
                                compiled.card_json,
                                compiled.card_safe_error_code,
                            ),
                        )
    except Exception as exc:
        LOGGER.warning(
            "debate_agent_card_failed participant_id=%s code=debate_card_failed error=%s",
            row.id,
            type(exc).__name__,
        )
        card = _CardSnapshot("fallback", None, "debate_card_failed")
    db.execute(
        update(DebateParticipant)
        .where(DebateParticipant.id == row.id, DebateParticipant.card_status == "compiling")
        .values(**asdict(card), updated_at=datetime.now(UTC))
    )
    db.commit()
    db.refresh(row)
