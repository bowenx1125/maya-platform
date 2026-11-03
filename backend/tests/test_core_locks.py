"""Named locks hold across connections, so across processes and machines."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.locks import held_lock, try_xact_lock, xact_lock


def test_a_transaction_lock_keeps_others_out_until_commit(database: Any) -> None:
    with database.session_factory() as first, database.session_factory() as second:
        xact_lock(first, "unit:a")
        assert try_xact_lock(second, "unit:a") is False
        assert try_xact_lock(second, "unit:b") is True
        second.rollback()
        first.commit()
        assert try_xact_lock(second, "unit:a") is True
        second.rollback()


def test_xact_lock_waits_for_the_holder(database: Any) -> None:
    entered = threading.Event()
    order: list[str] = []

    def waiter() -> None:
        with database.session_factory() as session:
            entered.set()
            xact_lock(session, "unit:wait")
            order.append("waiter")
            session.rollback()

    with database.session_factory() as holder:
        xact_lock(holder, "unit:wait")
        thread = threading.Thread(target=waiter)
        thread.start()
        assert entered.wait(5)
        time.sleep(0.3)
        order.append("holder")
        holder.commit()
    thread.join(5)
    assert order == ["holder", "waiter"]


def test_held_lock_spans_commits_and_skips_a_second_holder(database: Any) -> None:
    with held_lock(database.engine, "unit:held") as first:
        assert first is True
        with database.session_factory() as session:
            session.commit()  # the holder's own work commits; the lock stays
            assert try_xact_lock(session, "unit:held") is False
            session.rollback()
        with held_lock(database.engine, "unit:held") as second:
            assert second is False
    with database.session_factory() as session:
        assert try_xact_lock(session, "unit:held") is True
        session.rollback()


def test_held_lock_can_wait_and_is_released_after_an_error(database: Any) -> None:
    try:
        with held_lock(database.engine, "unit:error", wait=True) as acquired:
            assert acquired is True
            raise RuntimeError("work failed")
    except RuntimeError:
        pass
    with held_lock(database.engine, "unit:error") as again:
        assert again is True
