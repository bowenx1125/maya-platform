"""Shared Wave 3 durable-event to WebSocket fan-out bridge."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.sqlutil import begin_immediate
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
            begin_immediate(session)
            occurred_at = datetime.now(UTC)
            # Increment and read in one statement, like every other event
            # writer. A read-then-CAS lost (and silently dropped the event)
            # whenever a vote, barrage or playback event committed between
            # the read and the update; on PostgreSQL begin_immediate does
            # not serialize writers.
            allocated = session.execute(
                update(Debate)
                .where(Debate.id == debate_id)
                .values(last_sequence=Debate.last_sequence + 1, updated_at=occurred_at)
                .returning(Debate.last_sequence)
            ).scalar_one_or_none()
            if allocated is None:
                session.rollback()
                return False
            sequence = int(allocated)
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
