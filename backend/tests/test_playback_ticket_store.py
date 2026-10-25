"""Media tickets in PostgreSQL are honored by every replica (PR C)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.db import Database
from app.modules.debates.models import PlaybackMediaTicket
from app.modules.debates.playback.ticket_store import SqlMediaTicketStore
from sqlalchemy import select

from tests.postgres_db import new_database_url


def _two_replicas() -> tuple[Database, SqlMediaTicketStore, SqlMediaTicketStore]:
    database = Database(new_database_url())
    return (
        database,
        SqlMediaTicketStore(database.session_factory),
        SqlMediaTicketStore(database.session_factory),
    )


def _issue(store: SqlMediaTicketStore, debate_id: str, turn_id: str, action: str = "prefetch"):  # type: ignore[no-untyped-def]
    return store.issue(
        session_hash="s" * 64,
        controller_epoch=str(uuid4()),
        debate_id=debate_id,
        turn_id=turn_id,
        action=action,  # type: ignore[arg-type]
        control_version=3,
    )


def test_a_ticket_from_one_replica_is_honored_by_the_other() -> None:
    database, one, two = _two_replicas()
    try:
        debate_id, turn_id = str(uuid4()), str(uuid4())
        token, binding = _issue(one, debate_id, turn_id)
        found = two.get(token)
        assert found == binding
        assert two.find(
            session_hash="s" * 64,
            controller_epoch=binding.controller_epoch,
            debate_id=debate_id,
            turn_id=turn_id,
            action="prefetch",
        ) == (binding.token_hash, binding)
        started = two.mark_binding_started(binding, audio_duration_ms=1_000)
        assert one.get(token) == started
        assert started.started and started.expires_at <= binding.expires_at
    finally:
        database.dispose()


def test_only_the_hash_is_stored() -> None:
    database, one, _two = _two_replicas()
    try:
        token, binding = _issue(one, str(uuid4()), str(uuid4()))
        with database.session() as session:
            stored = session.scalars(select(PlaybackMediaTicket)).all()
        assert [row.token_hash for row in stored] == [binding.token_hash]
        assert all(token not in str(vars(row)) for row in stored)
    finally:
        database.dispose()


def test_revocation_and_expiry_hold_on_every_replica() -> None:
    database, one, two = _two_replicas()
    try:
        debate_id, turn_a, turn_b = str(uuid4()), str(uuid4()), str(uuid4())
        token_a, _ = _issue(one, debate_id, turn_a)
        token_b, binding_b = _issue(one, debate_id, turn_b)
        assert two.revoke_item(debate_id, turn_a) == 1
        assert one.get(token_a) is None
        assert one.get(token_b) is not None
        assert two.revoke_epoch(binding_b.controller_epoch) == 1
        assert one.get(token_b) is None

        token_c, _ = _issue(one, debate_id, turn_a)
        later = datetime.now(UTC) + timedelta(minutes=10)
        assert two.get(token_c, now=later) is None
        assert one.get(token_c) is None  # the expired row was removed

        _issue(one, debate_id, turn_a)
        _issue(one, debate_id, turn_b)
        assert two.revoke_debate(debate_id) == 2
        assert one.active_count() == 0
    finally:
        database.dispose()


def test_a_malformed_token_is_never_looked_up() -> None:
    database, one, _two = _two_replicas()
    try:
        assert one.get("short") is None
        assert one.get("!" * 43) is None
    finally:
        database.dispose()
