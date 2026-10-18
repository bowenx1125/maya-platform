"""Report and insight status events always get a durable sequence (#141)."""

from __future__ import annotations

import threading
from typing import Any

from app.modules.debates.models import Debate, DebateEvent
from app.modules.debates.playback import wave3_bridge
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tests.test_interaction_barrage_concurrency import postgres_interaction  # noqa: F401
from tests.test_wave3_interactions import _seed_finished_debate

_REPORT_STARTED = {
    "revision_id": "00000000-0000-4000-8000-000000000000",
    "status": "generating",
}


class _NoHub:
    pass


def _report_events(database: Any, debate_id: str) -> list[int]:
    with database.session() as session:
        return list(
            session.scalars(
                select(DebateEvent.sequence)
                .where(
                    DebateEvent.debate_id == debate_id,
                    DebateEvent.event_type == "report.started",
                )
                .order_by(DebateEvent.sequence)
            ).all()
        )


def test_summary_events_take_the_next_sequences(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app):
        debate_id, _participants = _seed_finished_debate(database)
    with database.session() as session:
        before = session.scalar(select(Debate.last_sequence).where(Debate.id == debate_id))
    publisher = wave3_bridge.Wave3EventPublisher(database.session_factory, _NoHub())  # type: ignore[arg-type]

    assert publisher.publish_summary(debate_id, "report.started", _REPORT_STARTED)
    assert publisher.publish_summary(debate_id, "report.started", _REPORT_STARTED)

    assert _report_events(database, debate_id) == [before + 1, before + 2]
    assert not publisher.publish_summary("missing-debate", "report.started", _REPORT_STARTED)


def test_postgres_summary_event_survives_a_concurrent_event_writer(
    postgres_interaction: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """A vote/barrage/playback event committing meanwhile used to drop the summary."""

    database, _settings = postgres_interaction
    debate_id, _participants = _seed_finished_debate(database)
    reached, release = threading.Event(), threading.Event()
    real_update = wave3_bridge.update

    def paused_update(*args: Any, **kwargs: Any) -> Any:
        if threading.current_thread().name == "summary":
            reached.set()
            release.wait(10)
        return real_update(*args, **kwargs)

    monkeypatch.setattr(wave3_bridge, "update", paused_update)
    publisher = wave3_bridge.Wave3EventPublisher(database.session_factory, _NoHub())  # type: ignore[arg-type]
    outcome: dict[str, bool] = {}
    worker = threading.Thread(
        target=lambda: outcome.setdefault(
            "published",
            publisher.publish_summary(debate_id, "report.started", _REPORT_STARTED),
        ),
        name="summary",
    )
    worker.start()
    assert reached.wait(10)
    # Another event writer allocates a sequence the way _event does.
    with database.session() as session:
        session.execute(
            update(Debate)
            .where(Debate.id == debate_id)
            .values(last_sequence=Debate.last_sequence + 1)
        )
    release.set()
    worker.join(20)

    assert outcome["published"] is True
    assert len(_report_events(database, debate_id)) == 1
