"""Debate audience pressure protection, event relay and replica recovery (2026-10-19)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import pytest
from app.core import debate_gate
from app.core.config import Settings
from app.core.debate_gate import PublicCopy, interaction_slot, reset_debate_gate
from app.core.errors import PlatformError
from app.modules.debates.playback.events import (
    DebateEventHub,
    EventRecord,
    MemoryEventStore,
    SharedSnapshots,
)

from tests.postgres_db import named_url


def _settings(**values: Any) -> Settings:
    return Settings(**values)


def _event(debate_id: str, sequence: int) -> EventRecord:
    return EventRecord(
        f"e{sequence}",
        debate_id,
        sequence,
        "interaction.vote_recorded",
        1,
        datetime.now(UTC),
        {"sequence": sequence},
    )


def _cap(value):
    return lambda settings=None, reserve=1: value(reserve) if callable(value) else value


def test_gate_full_answers_503_only_after_the_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_debate_gate()
    monkeypatch.setattr(debate_gate, "debate_audience_cap", _cap(None))
    monkeypatch.setattr(debate_gate, "admission_waiting", lambda: 0)
    settings = _settings(
        DEBATE_INTERACTION_GATE_LIMIT=1,
        DEBATE_INTERACTION_GATE_WAIT_SECONDS=0.2,
        DEBATE_INTERACTION_RETRY_SECONDS=3,
    )

    async def scenario() -> tuple[PlatformError, float]:
        held = asyncio.Event()
        release = asyncio.Event()

        async def holder() -> None:
            async with interaction_slot(settings):
                held.set()
                await release.wait()

        task = asyncio.create_task(holder())
        await held.wait()
        t = time.monotonic()
        try:
            async with interaction_slot(settings):
                raise AssertionError("second slot must not be granted")
        except PlatformError as exc:
            error = exc
        waited = time.monotonic() - t
        release.set()
        await task
        return error, waited

    error, waited = asyncio.run(scenario())
    assert waited >= 0.15
    assert error.status_code == 503 and error.details["retry_after_seconds"] == 3
    assert error.details["reason"] == "wait_timeout"


def test_latched_vote_queues_on_the_reserve_and_is_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_debate_gate()
    monkeypatch.setattr(debate_gate, "debate_audience_cap", _cap(lambda reserve: reserve))
    monkeypatch.setattr(debate_gate, "admission_waiting", lambda: 5)  # scoring queued
    settings = _settings(DEBATE_INTERACTION_GATE_LIMIT=4, DEBATE_INTERACTION_GATE_WAIT_SECONDS=5)
    peak = {"n": 0}

    async def one(done: list[int]) -> None:
        async with interaction_slot(settings):
            peak["n"] = max(peak["n"], debate_gate.debate_gate_snapshot()["in_flight"])
            await asyncio.sleep(0.05)
            done.append(1)

    async def scenario() -> int:
        done: list[int] = []
        await asyncio.gather(*(one(done) for _ in range(5)))
        return len(done)

    assert asyncio.run(scenario()) == 5  # every queued vote eventually lands
    assert peak["n"] == 1  # one at a time through the latched reserve


def test_ramp_after_release_caps_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import adaptive_admission as aa

    settings = _settings()
    monkeypatch.setattr(aa, "_refresh_locked", lambda s: None)
    monkeypatch.setattr(aa, "_ramp_cap_locked", lambda s, now: 2)
    monkeypatch.setattr(aa._state, "danger", False)
    assert aa.debate_audience_cap(settings) == 2
    monkeypatch.setattr(aa._state, "danger", True)
    assert aa.debate_audience_cap(settings, reserve=1) == 1
    monkeypatch.setattr(aa._state, "danger", False)
    monkeypatch.setattr(aa, "_ramp_cap_locked", lambda s, now: None)
    assert aa.debate_audience_cap(settings) is None
    reset_debate_gate()
    monkeypatch.setattr(debate_gate, "debate_audience_cap", _cap(2))
    monkeypatch.setattr(debate_gate, "admission_waiting", lambda: 0)
    gate = _settings(DEBATE_INTERACTION_GATE_LIMIT=4, DEBATE_INTERACTION_GATE_WAIT_SECONDS=5)
    peak = {"n": 0}

    async def one() -> None:
        async with interaction_slot(gate):
            peak["n"] = max(peak["n"], debate_gate.debate_gate_snapshot()["in_flight"])
            await asyncio.sleep(0.05)

    async def scenario() -> None:
        await asyncio.gather(*(one() for _ in range(6)))

    asyncio.run(scenario())
    assert peak["n"] == 2


def test_debate_turn_is_served_by_the_danger_reserve_in_the_write_class() -> None:
    from app.core import adaptive_admission as aa

    # The reserve serves priority (scoring/finalize) first, then "write",
    # where Debate turns/TTS/reports queue (debate_llm_slot), before login and llm.
    order = aa.DANGER_RESERVE_CLASSES
    assert order.index("write") < order.index("login") < order.index("llm")


def test_public_copy_version_and_pressure(monkeypatch: pytest.MonkeyPatch) -> None:
    copy = PublicCopy()
    settings = _settings(DEBATE_PUBLIC_CACHE_SECONDS=60, DEBATE_PUBLIC_STALE_SECONDS=600)
    loads: list[int] = []

    def load() -> int:
        loads.append(1)
        return len(loads)

    monkeypatch.setattr(debate_gate, "polling_pressure", lambda settings=None: False)
    assert copy.read("k", settings, load, what="x", version=1) == 1
    assert copy.read("k", settings, load, what="x", version=1) == 1
    # A new event retires the fresh copy.
    assert copy.read("k", settings, load, what="x", version=2) == 2
    monkeypatch.setattr(debate_gate, "polling_pressure", lambda settings=None: True)
    # Under pressure the older copy answers whatever its version.
    assert copy.read("k", settings, load, what="x", version=3) == 2
    # No copy at all: one read, never an instant 503.
    assert copy.read("other", settings, load, what="x") == 3
    assert len(loads) == 3


def test_shared_snapshot_single_build_and_same_version() -> None:
    snapshots = SharedSnapshots()
    builds: list[int] = []

    async def build() -> int:
        builds.append(1)
        await asyncio.sleep(0.01)
        return len(builds)

    async def scenario() -> None:
        values = await asyncio.gather(*(snapshots.get("k", 30, 1, build) for _ in range(20)))
        assert {value for value, _ in values} == {1}
        assert len(builds) == 1
        # Plain TTL copy survives a version bump; a strict one does not.
        assert (await snapshots.get("k", 30, 2, build))[0] == 1
        assert (await snapshots.get("k", 30, 2, build, same_version=True))[0] == 2

    asyncio.run(scenario())


def test_gap_is_filled_from_the_store_instead_of_closing() -> None:
    store = MemoryEventStore()
    hub = DebateEventHub(store)

    async def scenario() -> list[int]:
        store.append_event(_event("d1", 1))  # committed by the other backend
        store.append_event(_event("d1", 2))
        filled = await hub._fill_gap("d1", 0, 2)
        return [item.sequence for item in filled]

    assert asyncio.run(scenario()) == [1, 2]


def test_gap_that_never_appears_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.debates.playback import events

    monkeypatch.setattr(events, "GAP_FILL_SECONDS", 0.05)
    monkeypatch.setattr(events, "GAP_FILL_RETRY_SECONDS", 0.01)

    class _Holed(MemoryEventStore):
        def events_after(self, debate_id: str, sequence: int) -> Any:
            return (_event(debate_id, 2),)  # sequence 1 never arrives

    hub = DebateEventHub(_Holed())
    with pytest.raises(RuntimeError, match="sequence gap"):
        asyncio.run(hub._fill_gap("d3", 0, 2))


class _SqlLikeStore:
    """A durable-looking store (not MemoryEventStore) so the hub runs its relay."""

    def __init__(self) -> None:
        self.inner = MemoryEventStore()

    def append_event(self, event: EventRecord) -> None:
        self.inner.append_event(event)

    def events_after(self, debate_id: str, sequence: int) -> Any:
        return self.inner.events_after(debate_id, sequence)

    def last_sequence(self, debate_id: str) -> int:
        return self.inner.last_sequence(debate_id)


def test_relay_delivers_another_backends_event_once() -> None:
    store = _SqlLikeStore()
    hub = DebateEventHub(store, relay_poll_seconds=0.05)  # type: ignore[arg-type]
    debate_id = "d2"

    async def scenario() -> list[int]:
        queue = await hub.subscribe(debate_id)
        assert hub.relay_count() == 1
        await asyncio.sleep(0.08)
        store.append_event(_event(debate_id, 1))  # other backend
        event = _event(debate_id, 2)
        store.append_event(event)
        await hub.publish(event)  # local publish, also seen by the relay
        await asyncio.sleep(0.3)
        seen = []
        while not queue.empty():
            seen.append(queue.get_nowait().sequence)
        await hub.unsubscribe(debate_id, queue)
        assert hub.relay_count() == 0
        return seen

    assert sorted(asyncio.run(scenario())) == [1, 2]


def test_debate_llm_slot_queues_in_the_write_class(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import llm_admission

    classes: list[str] = []
    real = llm_admission.adaptive_slot

    def spy(cls: str, settings: Any = None) -> Any:
        classes.append(cls)
        return real(cls, settings)

    monkeypatch.setattr(llm_admission, "adaptive_slot", spy)
    llm_admission.reset_llm_admission_state()
    with llm_admission.debate_llm_slot():
        assert llm_admission.llm_admission_held()
        with llm_admission.llm_admission_slot():
            pass
    # Queues once in "write"; the inner "llm" layer is a nested charge that
    # never queues behind it.
    assert classes == ["write", "llm"]
    assert not llm_admission.llm_admission_held()


def test_replica_touch_and_untouched(tmp_path: Any) -> None:
    from app.core import replica
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(named_url(f"{tmp_path / 'r.sqlite3'}", schema=False))
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE jobs (id TEXT PRIMARY KEY, debate_id TEXT, state TEXT, "
                "claim_token TEXT, updated_at TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO jobs VALUES ('live','d','running','tok-live','2026-01-01'),"
                "('dead','d','running','tok-dead','2026-01-01'),"
                "('done','d','succeeded','tok-done','2026-01-01')"
            )
        )
    factory = sessionmaker(bind=engine)
    with factory() as db:
        snapshot = replica.running_debate_jobs(db)
    assert set(snapshot) == {"live", "dead"}
    replica.hold_claim("tok-live")
    replica.hold_claim("tok-done")
    assert replica.touch_held_jobs(factory) == 1
    assert "tok-done" not in replica.held_claims()
    with factory() as db:
        assert replica.untouched(db, snapshot) == {"dead"}
    replica.release_claim("tok-live")
    presence = replica.ReplicaPresence(engine, factory)
    assert presence.peers_alive() is False
