"""A classroom submission reaches a persisted Conclusion reply through the SQL product path."""

from __future__ import annotations

import json
from uuid import uuid4

from app.modules.debates.final_input import read_final_input
from app.modules.debates.models import Debate, DebateTurn, PlaybackState
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.interactions.models import BarrageMessage
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.test_four_round_generation import RecordingMock
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent


def test_http_barrage_freezes_anonymously_then_survives_mock_generation_and_public_projection(
    app_factory,
):
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    assert settings.llm_provider == settings.tts_provider == settings.embedding_provider == "mock"
    llm = RecordingMock()
    playback_service = app.state.playback_service
    playback_service.turn_preparer = SqlTurnPreparer(settings=settings, llm=llm)
    try:
        with TestClient(app) as client:
            people = [
                _insert_published_agent(
                    database,
                    group_id=GROUP_DEMO_ID,
                    name=f"Barrage scholar {index}",
                    evidence=(
                        "Classroom evidence supports transparent criteria and revision "
                        "when a perspective is excluded."
                    ),
                )
                for index in range(2)
            ]
            _, csrf = login(client)
            headers = _headers(
                csrf,
                **{"Idempotency-Key": str(uuid4()), "Origin": settings.classroom_public_base_url},
            )
            created = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=headers,
                json={
                    "topic": "How should a classroom evaluate evidence and include quiet students?",
                    "participants": [
                        {"agent_id": person, "stance_mode": "open"} for person in people
                    ],
                    "round_count": 4,
                    "output_language": "en",
                },
            )
            assert created.status_code == 201, created.text
            debate_id = created.json()["id"]
            scheduler = app.state.prewarm_scheduler
            for turn_id, ready in scheduler._plan(debate_id):
                if not ready:
                    client.portal.call(scheduler._prepare, debate_id, turn_id)
            assert len(llm.snapshots) == 6
            assert all(not snapshot.barrages for snapshot in llm.snapshots)
            started = client.post(
                f"/api/v1/debates/{debate_id}/start",
                headers={**headers, "Idempotency-Key": str(uuid4())},
                json={
                    "expected_revision": 0,
                    "expected_current_audio_debate_id": None,
                    "confirm_previous_audio_cleanup": False,
                },
            )
            assert started.status_code == 200, started.text
            with database.session() as db:
                turns = db.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
                turn_ids = [turn.id for turn in turns]
            opened = client.post(
                f"/api/v1/debates/{debate_id}/interaction/open",
                headers={**headers, "Idempotency-Key": str(uuid4())},
            )
            assert opened.status_code == 200, opened.text
            token = opened.json()["public_url"].rsplit("/", 1)[-1]
            url = f"/api/v1/classroom-interactions/{token}/barrages"
            first = {
                "nickname": "VisitorNameUnique",
                "raw_text": (
                    "VisitorNameUnique asks: How can quiet students challenge the criterion? "
                    "Contact visitor@example.com."
                ),
                "client_submission_id": str(uuid4()),
                "turn_id": turn_ids[0],
            }
            assert client.post(url, json=first).status_code == 201
            assert client.post(url, json=first).status_code == 201
            stale = client.post(
                url, json={**first, "client_submission_id": str(uuid4()), "turn_id": turn_ids[2]}
            )
            assert stale.status_code == 409 and stale.json()["code"] == "barrage_turn_changed"
            with database.session() as db:
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.current_turn_id = turn_ids[2]
            second = {
                "nickname": "Another visitor",
                "raw_text": "When should the class revise its trial?",
                "client_submission_id": str(uuid4()),
                "turn_id": turn_ids[2],
            }
            assert client.post(url, json=second).status_code == 201
            history = client.get(f"/api/v1/debates/{debate_id}/interaction").json()["barrages"]
            assert [message["raw_text"] for message in history] == [
                first["raw_text"],
                second["raw_text"],
            ]
            with database.session() as db:
                messages = db.scalars(
                    select(BarrageMessage)
                    .where(BarrageMessage.debate_id == debate_id)
                    .order_by(BarrageMessage.sequence)
                ).all()
                message_ids = [message.id for message in messages]
                assert [message.turn_id for message in messages] == [turn_ids[0], turn_ids[2]]
                events = (
                    db.execute(
                        text(
                            "SELECT payload_json FROM debate_events WHERE debate_id=:id "
                            "AND event_type='interaction.barrage_created' ORDER BY sequence"
                        ),
                        {"id": debate_id},
                    )
                    .scalars()
                    .all()
                )
                assert [json.loads(event)["message_id"] for event in events] == message_ids
                assert [json.loads(event)["raw_text"] for event in events] == [
                    first["raw_text"],
                    second["raw_text"],
                ]
                # Publish the already generated Preview speeches with the product adapter.
                repository = playback_service.repository
                debate = repository.get_debate(db, debate_id)
                for turn in repository.turns(db, debate)[:6]:
                    assert repository.publish_turn(db, turn)
                state = db.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
                state.current_turn_id = turn_ids[5]
                state.status = "waiting_next"
                control_version = state.control_version
            frozen = client.post(
                f"/api/v1/debates/{debate_id}/final-input",
                headers=headers,
                json={"expected_control_version": control_version},
            )
            assert frozen.status_code == 200, frozen.text
            assert frozen.json()["barrage_count"] == 2
            client.portal.call(playback_service.task_manager.wait_debate, debate_id)
            late = client.post(url, json={**second, "client_submission_id": str(uuid4())})
            assert late.status_code == 410 and late.json()["code"] == "barrage_collection_closed"
            assert client.post(url, json=first).status_code == 201
            final_snapshots = [snapshot for snapshot in llm.snapshots if snapshot.round.number == 4]
            assert len(final_snapshots) == 1
            snapshot = final_snapshots[0]
            with database.session() as db:
                frozen_input = read_final_input(db.get(Debate, debate_id))
                assert frozen_input["message_ids"] == message_ids
                assert [barrage.as_payload() for barrage in snapshot.barrages] == frozen_input[
                    "barrages"
                ]
                outbound = json.dumps([barrage.as_payload() for barrage in snapshot.barrages])
                assert "VisitorNameUnique" not in outbound and "visitor@example.com" not in outbound
                assert "How can quiet students challenge the criterion?" in outbound
                assert all(set(item) == {"id", "text"} for item in frozen_input["barrages"])
                turn = db.get(DebateTurn, turn_ids[6])
                assert turn.generation_status == "final_ready"
                stored = json.loads(turn.structured_json)
                replies = [
                    segment["reply_to"] for segment in stored["segments"] if segment["reply_to"]
                ]
                assert replies == ["B1"]
                assert "To answer the classroom question" in turn.speech
                replied_index = int(replies[0][1:]) - 1
                assert frozen_input["message_ids"][replied_index] == message_ids[0]
                debate = playback_service.repository.get_debate(db, debate_id)
                final_turn = next(
                    row
                    for row in playback_service.repository.turns(db, debate)
                    if row.id == turn.id
                )
                assert playback_service.repository.publish_turn(db, final_turn)
                ws_segment = playback_service._segment_payload(db, final_turn)["segment_turn"][
                    "segments"
                ][0]
                assert ws_segment["reply_text"] == frozen_input["barrages"][0]["text"]
                assert "VisitorNameUnique" not in ws_segment["reply_text"]
                assert "visitor@example.com" not in ws_segment["reply_text"]
            public = client.get(f"/api/v1/debates/{debate_id}")
            assert public.status_code == 200, public.text
            final = next(
                turn for turn in public.json()["public_turns"] if turn["id"] == turn_ids[6]
            )
            assert [segment["reply_to"] for segment in final["segment_turn"]["segments"]] == ["B1"]
            assert final["speech"] == "\n\n".join(
                segment["text"] for segment in final["segment_turn"]["segments"]
            )
            assert (
                final["segment_turn"]["segments"][0]["reply_text"]
                == frozen_input["barrages"][0]["text"]
            )
            assert final["segment_turn"]["segments"][0]["reply_text"] not in final["speech"]
            assert len(llm.snapshots) == 7
    finally:
        database.dispose()
