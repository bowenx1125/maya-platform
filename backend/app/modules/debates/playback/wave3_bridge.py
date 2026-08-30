"""Shared Wave 3 durable-event to WebSocket fan-out bridge."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.modules.debates.models import Debate, DebateEvent

from .events import DebateEventHub, EventRecord, validate_event_payload


class Wave3EventPublisher:
    """Persist summary events and safely wake the process-local event hub.

    M13 already commits its DebateEvent in the interaction writer transaction,
    so ``publish_interaction`` only fans out that exact record. M14/M15 workers
    finish after their own transaction and call ``publish_summary``; that path
    allocates one durable Debate sequence under a short SQLite writer lock.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        event_hub: DebateEventHub,
    ) -> None:
        self.session_factory = session_factory
        self.event_hub = event_hub
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_running_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def _fan_out(self, record: EventRecord) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            asyncio.create_task(self.event_hub.publish(record))

        loop.call_soon_threadsafe(schedule)

    def publish_interaction(self, event: Any) -> None:
        record = EventRecord(
            event_id=str(event.event_id),
            debate_id=str(event.debate_id),
            sequence=int(event.sequence),
            event_type=str(event.event_type),
            event_version=int(event.event_version),
            occurred_at=event.occurred_at,
            payload=validate_event_payload(str(event.event_type), event.payload),
        )
        self._fan_out(record)

    def publish_summary(
        self,
        debate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> bool:
        validated = validate_event_payload(event_type, payload)
        session = self.session_factory()
        try:
            session.execute(text("BEGIN IMMEDIATE"))
            debate = session.scalar(select(Debate).where(Debate.id == debate_id))
            if debate is None:
                session.rollback()
                return False
            previous = int(debate.last_sequence)
            sequence = previous + 1
            occurred_at = datetime.now(UTC)
            changed = session.execute(
                update(Debate)
                .where(Debate.id == debate_id, Debate.last_sequence == previous)
                .values(last_sequence=sequence, updated_at=occurred_at)
            )
            if int(getattr(changed, "rowcount", 0)) != 1:
                session.rollback()
                return False
            event_id = str(uuid4())
            session.add(
                DebateEvent(
                    id=event_id,
                    debate_id=debate_id,
                    sequence=sequence,
                    event_type=event_type,
                    event_version=1,
                    payload_json=json.dumps(
                        validated,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    occurred_at=occurred_at,
                )
            )
            session.commit()
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()
        self._fan_out(
            EventRecord(
                event_id=event_id,
                debate_id=debate_id,
                sequence=sequence,
                event_type=event_type,
                event_version=1,
                occurred_at=occurred_at,
                payload=validated,
            )
        )
        return True


__all__ = ["Wave3EventPublisher"]
