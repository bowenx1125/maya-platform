"""Durable event envelopes and the snapshot-first WebSocket hub."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter, ValidationError

from .schemas import (
    ClosedModel,
    DebateStartedPayload,
    DebateTerminalPayload,
    ErrorPayload,
    PlaybackCursorPayload,
    PlaybackStartedPayload,
    PlaybackWaitingNextPayload,
    PrivateResult,
    ReplayPayload,
    RoundStartedPayload,
    SnapshotPayload,
    TurnPreparingPayload,
    TurnReadyPayload,
)


class EventRecordProtocol(Protocol):
    event_id: str
    debate_id: str
    sequence: int
    event_type: str
    event_version: int
    occurred_at: datetime
    payload: Mapping[str, Any]


class EventEnvelope(ClosedModel):
    event_id: UUID
    event_type: str
    event_version: int
    debate_id: UUID
    sequence: int
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    debate_id: str
    sequence: int
    event_type: str
    event_version: int
    occurred_at: datetime
    payload: dict[str, Any]


_PAYLOAD_TYPES: dict[str, type[BaseModel]] = {
    "snapshot": SnapshotPayload,
    "debate.started": DebateStartedPayload,
    "round.started": RoundStartedPayload,
    "turn.preparing": TurnPreparingPayload,
    "turn.ready": TurnReadyPayload,
    "playback.started": PlaybackStartedPayload,
    "playback.paused": PlaybackCursorPayload,
    "playback.resumed": PlaybackCursorPayload,
    "playback.skipped": PlaybackCursorPayload,
    "playback.waiting_next": PlaybackWaitingNextPayload,
    "playback.completed": PlaybackCursorPayload,
    "replay.started": ReplayPayload,
    "replay.completed": ReplayPayload,
    "error": ErrorPayload,
    "debate.failed": DebateTerminalPayload,
    "debate.stopped": DebateTerminalPayload,
}


def validate_event_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a closed persistent event payload and return JSON-safe data."""

    model_type = _PAYLOAD_TYPES.get(event_type)
    if model_type is None:
        # Events owned by later waves are intentionally not accepted by this
        # package.  A new payload must first be added to the reviewed contract.
        raise ValueError(f"unsupported playback event type: {event_type}")
    try:
        return model_type.model_validate(dict(payload)).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError(f"invalid {event_type} payload") from exc


def event_to_wire(
    event_type: str,
    debate_id: str | UUID,
    sequence: int,
    payload: Mapping[str, Any],
    *,
    event_id: str | UUID | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the exact envelope used for a public event.

    This function is deliberately the only route from internal event values to
    WebSocket JSON.  It drops no validation errors and therefore cannot
    accidentally leak a prepared speech or provider field.
    """

    if sequence < 0:
        raise ValueError("event sequence must be non-negative")
    validated = validate_event_payload(event_type, payload)
    envelope = EventEnvelope(
        event_id=UUID(str(event_id)) if event_id is not None else uuid4(),
        event_type=event_type,
        event_version=1,
        debate_id=UUID(str(debate_id)),
        sequence=sequence,
        occurred_at=occurred_at or datetime.now(UTC),
        payload=validated,
    )
    return envelope.model_dump(mode="json")


class EventStore(Protocol):
    """Small persistence seam implemented by the M10 database adapter."""

    def append_event(self, event: EventRecord) -> None: ...

    def events_after(self, debate_id: str, sequence: int) -> Iterable[EventRecord]: ...

    def last_sequence(self, debate_id: str) -> int: ...


class MemoryEventStore:
    """Deterministic store used by unit tests and isolated local controllers."""

    def __init__(self) -> None:
        self._events: dict[str, list[EventRecord]] = defaultdict(list)

    def append_event(self, event: EventRecord) -> None:
        current = self._events[event.debate_id]
        expected = len(current) + 1
        if event.sequence != expected:
            raise ValueError("event sequence is not monotonic")
        current.append(event)

    def events_after(self, debate_id: str, sequence: int) -> Iterable[EventRecord]:
        return tuple(
            event for event in self._events.get(debate_id, ()) if event.sequence > sequence
        )

    def last_sequence(self, debate_id: str) -> int:
        return len(self._events.get(debate_id, ()))


class DebateEventHub:
    """In-process fan-out with subscribe-before-snapshot semantics.

    The caller subscribes first, reads its DB snapshot/watermark, and then
    drains only events newer than that watermark.  A queue buffers commits
    racing the snapshot read, preventing a double-delivery or sequence gap.
    """

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or MemoryEventStore()
        self._subscribers: dict[str, set[asyncio.Queue[EventRecord]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, debate_id: str) -> asyncio.Queue[EventRecord]:
        queue: asyncio.Queue[EventRecord] = asyncio.Queue()
        async with self._lock:
            self._subscribers[debate_id].add(queue)
        return queue

    async def unsubscribe(self, debate_id: str, queue: asyncio.Queue[EventRecord]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(debate_id)
            if subscribers is None:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(debate_id, None)

    async def publish(self, event: EventRecord) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(event.debate_id, ()))
        for queue in subscribers:
            queue.put_nowait(event)

    def append_committed(
        self,
        debate_id: str,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        sequence: int | None = None,
    ) -> EventRecord:
        next_sequence = (
            sequence if sequence is not None else self.store.last_sequence(debate_id) + 1
        )
        validated = validate_event_payload(event_type, payload)
        event = EventRecord(
            event_id=str(uuid4()),
            debate_id=debate_id,
            sequence=next_sequence,
            event_type=event_type,
            event_version=1,
            occurred_at=datetime.now(UTC),
            payload=validated,
        )
        self.store.append_event(event)
        # ``publish`` is awaited by the service after its transaction commits.
        return event

    async def stream(
        self,
        debate_id: str,
        snapshot_factory: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield one snapshot and then only events with sequence greater than N."""

        queue = await self.subscribe(debate_id)
        try:
            # The subscription already exists before the factory reads its
            # transaction-consistent snapshot and watermark.
            snapshot_value = snapshot_factory()
            if asyncio.iscoroutine(snapshot_value) or isinstance(snapshot_value, Awaitable):
                snapshot_value = await snapshot_value
            snapshot_payload, watermark = snapshot_value
            snapshot_wire = event_to_wire(
                "snapshot",
                debate_id,
                watermark,
                {**snapshot_payload, "latest_sequence": watermark},
            )
            yield snapshot_wire
            for event in self.store.events_after(debate_id, watermark):
                if event.sequence != watermark + 1:
                    raise RuntimeError("debate event sequence gap")
                watermark = event.sequence
                yield event_to_wire(
                    event.event_type,
                    event.debate_id,
                    event.sequence,
                    event.payload,
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                )
            while True:
                event = await queue.get()
                if event.sequence <= watermark:
                    continue
                if event.sequence != watermark + 1:
                    raise RuntimeError("debate event sequence gap")
                watermark = event.sequence
                yield event_to_wire(
                    event.event_type,
                    event.debate_id,
                    event.sequence,
                    event.payload,
                    event_id=event.event_id,
                    occurred_at=event.occurred_at,
                )
        finally:
            await self.unsubscribe(debate_id, queue)


def private_result_to_wire(result: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    """Validate private command results without assigning a Debate sequence."""

    if isinstance(result, BaseModel):
        data = result.model_dump(mode="json")
    else:
        data = dict(result)
    # TypeAdapter performs the discriminated union check and rejects unknown
    # private result types/fields before they reach a socket.
    return TypeAdapter(PrivateResult).validate_python(data).model_dump(mode="json")
