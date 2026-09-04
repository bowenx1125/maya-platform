"""Focused M13 lifecycle, privacy and anonymous-idempotency checks."""

from __future__ import annotations

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    Course,
    CourseMember,
    IdempotencyRecord,
    KnowledgeSnapshot,
    StoredFile,
    User,
)
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.models import (
    Debate,
    DebateParticipant,
    DebateTurn,
    PlaybackState,
)
from app.modules.interactions.models import (
    BarrageMessage,
    ClassroomInteractionWindow,
    InteractionFinalBarrage,
    InteractionFinalVoteCount,
    Vote,
)
from app.modules.interactions.schemas import BarrageRequest, VoteRequest
from app.modules.interactions.service import (
    InteractionService,
    PostCommitInteractionEvent,
    create_closed_window,
)
from app.modules.interactions.tokens import issue_token, parse_token
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, select

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"
STUDENT_ID = "60541c78-30f1-55c5-b2aa-207b6a766883"


class EventCollector:
    def __init__(self) -> None:
        self.events: list[PostCommitInteractionEvent] = []

    def publish(self, event: PostCommitInteractionEvent) -> None:
        self.events.append(event)


@pytest.fixture
def interaction_app(
    app_factory: Any,
) -> Generator[tuple[FastAPI, Database, TestClient], None, None]:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    client = TestClient(app)
    with client:
        yield app, database, client


def _seed_finished_debate(database: Database, *, rounds: int = 2) -> tuple[str, list[str]]:
    now = datetime.now(UTC)
    debate_id = str(uuid4())
    participant_specs = [
        (GROUP_DEMO_ID, "Bowen"),
        (GROUP_DEMO_ID, "Kaikai"),
    ]
    frozen: list[tuple[str, str, str, str, str]] = []
    with database.session() as session:
        for group_id, name in participant_specs:
            agent_id, version_id, snapshot_id, stored_file_id = (str(uuid4()) for _ in range(4))
            session.add(
                StoredFile(
                    id=stored_file_id,
                    kind="markdown",
                    relative_path=f"groups/{group_id}/knowledge/{stored_file_id}/source.md",
                    sha256="a" * 64,
                    size_bytes=12,
                    state="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                Agent(
                    id=agent_id,
                    group_id=group_id,
                    name=name,
                    description="",
                    status="active",
                    current_published_version_id=version_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                AgentVersion(
                    id=version_id,
                    agent_id=agent_id,
                    version_seq=0,
                    state="published",
                    revision=1,
                    agent_md=f"# {name}",
                    avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                    voice_profile_id=None,
                    knowledge_snapshot_id=snapshot_id,
                    published_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                KnowledgeSnapshot(
                    id=snapshot_id,
                    agent_version_id=version_id,
                    stored_file_id=stored_file_id,
                    content_hash="b" * 64,
                    total_char_count=12,
                    embedding_key="mock",
                    chunking_json="{}",
                    created_at=now,
                )
            )
            frozen.append((agent_id, version_id, snapshot_id, group_id, name))
        session.flush()
        debate = Debate(
            id=debate_id,
            course_id=COURSE_ID,
            topic="Should a classroom use anonymous questions?",
            rule_set_id="ordered_multi_agent_rounds_demo_v1",
            rule_snapshot_json=json.dumps({"round_count": rounds}),
            status="debate_finished",
            revision=0,
            last_sequence=0,
            cancellation_generation=0,
            created_by=TEACHER_ID,
            created_at=now,
            updated_at=now,
            finished_at=now,
        )
        session.add(debate)
        session.flush()
        participant_ids: list[str] = []
        for order_index, (agent_id, version_id, snapshot_id, group_id, name) in enumerate(frozen):
            participant_id = str(uuid4())
            participant_ids.append(participant_id)
            session.add(
                DebateParticipant(
                    id=participant_id,
                    debate_id=debate_id,
                    course_id=COURSE_ID,
                    group_id=group_id,
                    agent_id=agent_id,
                    agent_version_id=version_id,
                    knowledge_snapshot_id=snapshot_id,
                    slot=chr(65 + order_index),
                    order_index=order_index,
                    agent_name=name,
                    version_label="V1.0",
                    avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                    requested_voice_profile_id=None,
                    effective_voice_kind="mock_sentinel",
                    effective_voice_profile_id=None,
                    voice_fallback_active=True,
                    stance_mode="open",
                    initial_stance=None,
                    current_stance=None,
                    teacher_note="",
                    initial_position_summary="",
                    current_position_summary="",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.flush()
        plan = [
            participant_ids[index]
            for _round in range(rounds)
            for index in range(len(participant_ids))
        ]
        for turn_index, participant_id in enumerate(plan):
            snapshot_id = frozen[0 if participant_id == participant_ids[0] else 1][2]
            session.add(
                DebateTurn(
                    id=str(uuid4()),
                    debate_id=debate_id,
                    participant_id=participant_id,
                    knowledge_snapshot_id=snapshot_id,
                    round_no=turn_index // len(participant_ids) + 1,
                    turn_index=turn_index,
                    generation_status="final_ready",
                    publication_status="public",
                    preparation_stage="ready",
                    speech=("A complete classroom speech with evidence and reflection. " * 20),
                    structured_json="{}",
                    predecessor_turn_ids_json="[]",
                    transcript_hash="c" * 64,
                    cutoff_turn_index=turn_index - 1,
                    retrieval_status="no_match",
                    grounding_mode="general_reasoning",
                    retrieval_receipts_json="[]",
                    word_count=100,
                    attempt=1,
                    audio_file_id=None,
                    audio_duration_ms=None,
                    actual_tts_voice_kind=None,
                    actual_tts_voice_profile_id=None,
                    safe_error_code=None,
                    created_at=now,
                    updated_at=now,
                    public_at=now,
                )
            )
        session.add(
            PlaybackState(
                id=str(uuid4()),
                debate_id=debate_id,
                status="completed",
                mode="live",
                current_turn_id=None,
                cursor_ms=0,
                playback_rate=1.0,
                control_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        create_closed_window(session, debate, timestamp=now)
    return debate_id, participant_ids


def _service(database: Database, settings: Any) -> tuple[InteractionService, EventCollector]:
    collector = EventCollector()
    return (
        InteractionService(
            session_factory=database.session_factory,
            settings=settings,
            event_publisher=collector,
        ),
        collector,
    )


def _add_teacher(database: Database, *, course_id: str = COURSE_ID) -> str:
    teacher_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as session:
        if session.get(Course, course_id) is None:
            session.add(
                Course(
                    id=course_id,
                    code=f"course-{course_id}",
                    name="Other course",
                    current_audio_debate_id=None,
                    created_at=now,
                )
            )
        session.add(
            User(
                id=teacher_id,
                username=f"teacher-{teacher_id}",
                display_name="Concurrent teacher",
                status="active",
                created_at=now,
            )
        )
        session.add(
            CourseMember(
                course_id=course_id,
                user_id=teacher_id,
                role="teacher",
                created_at=now,
            )
        )
    return teacher_id


def test_token_has_fixed_stateless_shape() -> None:
    window_id = uuid4()
    nonce = b"n" * 32
    token = issue_token(window_id, nonce, b"s" * 32)
    parts = token.split(".")
    assert parts[0] == "v1"
    assert len(parts) == 3
    assert len(parts[1]) == 64
    assert len(parts[2]) == 43
    parsed = parse_token(token, b"s" * 32)
    assert parsed is not None
    assert parsed.window_id == window_id
    assert parsed.nonce == nonce
    forged = ".".join([parts[0], ("A" if parts[1][0] != "A" else "B") + parts[1][1:], parts[2]])
    assert parse_token(forged, b"s" * 32) is None


def test_m13_full_lifecycle_preserves_anonymous_boundary(interaction_app: Any) -> None:
    _app, database, _client = interaction_app
    debate_id, participant_ids = _seed_finished_debate(database)
    settings = _app.state.settings
    service, collector = _service(database, settings)

    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-open-lifecycle-01",
    )
    assert opened.status == "open"
    assert opened.public_url.startswith("http://192.168.1.25:8080/classroom/v1.")
    token = opened.public_url.rsplit("/", 1)[-1]
    with database.session() as session:
        window = session.scalar(
            select(ClassroomInteractionWindow).where(
                ClassroomInteractionWindow.debate_id == debate_id
            )
        )
        assert window is not None
        assert window.token_nonce is not None
        record = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "m13-open-lifecycle-01")
        )
        assert record is not None
        assert token not in (record.response_json or "")

    form = service.public_form(access_token=token)
    assert form.topic.startswith("Should a classroom")
    assert set(form.model_dump()) == {"topic", "participants"}
    assert set(form.participants[0].model_dump()) == {"participant_id", "slot", "name"}

    vote_key = str(uuid4())
    vote = VoteRequest(participant_id=UUID(participant_ids[0]), client_submission_id=UUID(vote_key))
    assert service.submit_vote(access_token=token, payload=vote).vote_submitted
    assert service.submit_vote(access_token=token, payload=vote).vote_submitted
    with pytest.raises(PlatformError) as conflict_error:
        service.submit_vote(
            access_token=token,
            payload=VoteRequest(
                participant_id=UUID(participant_ids[1]), client_submission_id=UUID(vote_key)
            ),
        )
    assert conflict_error.value.code == "idempotency_conflict"

    barrage_key = str(uuid4())
    barrage = BarrageRequest(
        nickname=" learner ",
        raw_text="  Keep the original text.  ",
        client_submission_id=UUID(barrage_key),
    )
    assert service.submit_barrage(access_token=token, payload=barrage).barrage_submitted
    assert service.submit_barrage(access_token=token, payload=barrage).barrage_submitted
    closed = service.close_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-close-lifecycle-01",
    )
    assert closed.status == "finalized"
    assert closed.public_url is None
    assert closed.votes[0].count == 1
    assert closed.barrages[0].nickname == " learner "
    assert closed.barrages[0].raw_text == "  Keep the original text.  "
    assert service.submit_vote(access_token=token, payload=vote).vote_submitted
    assert service.submit_barrage(access_token=token, payload=barrage).barrage_submitted
    with pytest.raises(PlatformError) as finalized_conflict:
        service.submit_vote(
            access_token=token,
            payload=VoteRequest(
                participant_id=UUID(participant_ids[1]),
                client_submission_id=UUID(vote_key),
            ),
        )
    assert finalized_conflict.value.code == "idempotency_conflict"
    assert [event.event_type for event in collector.events] == [
        "interaction.opened",
        "interaction.vote_created",
        "interaction.barrage_created",
        "interaction.closed",
    ]
    with database.session() as session:
        final_votes = session.scalars(
            select(InteractionFinalVoteCount).where(
                InteractionFinalVoteCount.window_id
                == session.scalar(
                    select(ClassroomInteractionWindow.id).where(
                        ClassroomInteractionWindow.debate_id == debate_id
                    )
                )
            )
        ).all()
        final_barrages = session.scalars(select(InteractionFinalBarrage)).all()
        assert len(final_votes) == 2
        assert len(final_barrages) == 1
        assert session.scalar(select(func_count(Vote.id))) == 1
        assert session.scalar(select(func_count(BarrageMessage.id))) == 1


def func_count(column: Any) -> Any:
    """Keep the test's aggregate expression readable without a global import."""

    from sqlalchemy import func

    return func.count(column)


def test_public_routes_never_create_or_use_user_idempotency(interaction_app: Any) -> None:
    _app, database, client = interaction_app
    canonical_origin = _app.state.settings.classroom_public_base_url
    assert canonical_origin is not None
    debate_id, participant_ids = _seed_finished_debate(database)
    session_data, csrf = login(client)
    assert session_data["user"]["id"] == TEACHER_ID
    response = client.post(
        f"/api/v1/debates/{debate_id}/interaction/open",
        headers={
            "Origin": canonical_origin,
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "m13-route-open-0001",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    token = response.json()["public_url"].rsplit("/", 1)[-1]
    vote_id = str(uuid4())
    vote_response = client.post(
        f"/api/v1/classroom-interactions/{token}/votes",
        json={"participant_id": participant_ids[0], "client_submission_id": vote_id},
    )
    assert vote_response.status_code == 201, vote_response.text
    assert vote_response.headers["cache-control"] == "no-store"
    with database.session() as session:
        assert (
            session.scalar(
                select(IdempotencyRecord.id).where(IdempotencyRecord.operation == "submitVote")
            )
            is None
        )
        vote_columns = {column["name"] for column in inspect(database.engine).get_columns("votes")}
        assert "nickname" not in vote_columns
        assert "user_id" not in vote_columns


def test_open_rejects_unfinished_or_missing_private_lan_origin(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    settings = app.state.settings
    service, _collector = _service(database, settings)
    with database.session() as session:
        row = session.get(Debate, debate_id)
        assert row is not None
        row.status = "running"
    with pytest.raises(PlatformError) as unfinished:
        service.open_interaction(
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
            idempotency_key="m13-open-unfinished-01",
        )
    assert unfinished.value.code == "invalid_state"
    settings.classroom_public_base_url = "http://127.0.0.1:8080"
    with database.session() as session:
        row = session.get(Debate, debate_id)
        assert row is not None
        row.status = "debate_finished"
    with pytest.raises(PlatformError) as no_lan:
        service.open_interaction(
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
            idempotency_key="m13-open-no-lan-0001",
        )
    assert no_lan.value.status_code == 503


def test_open_requires_the_complete_two_round_turn_plan(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    with database.session() as session:
        session.execute(
            delete(DebateTurn).where(
                DebateTurn.debate_id == debate_id,
                DebateTurn.turn_index == 3,
            )
        )
    service, _collector = _service(database, app.state.settings)

    with pytest.raises(PlatformError) as incomplete:
        service.open_interaction(
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
            idempotency_key="m13-open-incomplete-01",
        )

    assert incomplete.value.code == "invalid_state"


def test_finalized_token_returns_410_and_close_is_idempotent(interaction_app: Any) -> None:
    app, database, client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    service, _collector = _service(database, app.state.settings)
    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-open-finalized-01",
    )
    assert opened.public_url is not None
    token = opened.public_url.rsplit("/", 1)[-1]
    first = service.close_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-close-finalized-01",
    )
    replay = service.close_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-close-finalized-01",
    )
    assert first.model_dump() == replay.model_dump()
    with pytest.raises(PlatformError) as finalized:
        service.public_form(access_token=token)
    assert finalized.value.status_code == 410
    response = client.get(f"/api/v1/classroom-interactions/{token}")
    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_two_teachers_racing_open_have_exactly_one_winner(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    second_teacher_id = _add_teacher(database)
    service, _collector = _service(database, app.state.settings)
    barrier = Barrier(2)

    def attempt(actor_user_id: str, key: str) -> tuple[str, int | None]:
        barrier.wait()
        try:
            service.open_interaction(
                actor_user_id=actor_user_id,
                debate_id=debate_id,
                idempotency_key=key,
            )
        except PlatformError as error:
            return error.code, error.status_code
        return "opened", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda arguments: attempt(*arguments),
                [
                    (TEACHER_ID, "m13-race-open-teacher-01"),
                    (second_teacher_id, "m13-race-open-teacher-02"),
                ],
            )
        )

    assert outcomes.count(("opened", None)) == 1
    assert outcomes.count(("invalid_state", 409)) == 1
    with database.session() as session:
        window = session.scalar(
            select(ClassroomInteractionWindow).where(
                ClassroomInteractionWindow.debate_id == debate_id
            )
        )
        assert window is not None
        assert window.status == "open"
        assert window.revision == 1


def test_submit_close_writer_race_freezes_exact_winner(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, participant_ids = _seed_finished_debate(database)
    service, _collector = _service(database, app.state.settings)
    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-race-open-before-close",
    )
    assert opened.public_url is not None
    token = opened.public_url.rsplit("/", 1)[-1]
    submission_id = uuid4()
    barrier = Barrier(2)

    def submit() -> tuple[str, int | None]:
        barrier.wait()
        try:
            service.submit_vote(
                access_token=token,
                payload=VoteRequest(
                    participant_id=UUID(participant_ids[0]),
                    client_submission_id=submission_id,
                ),
            )
        except PlatformError as error:
            return error.code, error.status_code
        return "submitted", None

    def close() -> tuple[str, int | None]:
        barrier.wait()
        try:
            service.close_interaction(
                actor_user_id=TEACHER_ID,
                debate_id=debate_id,
                idempotency_key="m13-race-close-0001",
            )
        except PlatformError as error:
            return error.code, error.status_code
        return "finalized", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        submit_future = pool.submit(submit)
        close_future = pool.submit(close)
        submit_outcome = submit_future.result()
        close_outcome = close_future.result()

    assert close_outcome == ("finalized", None)
    assert submit_outcome in {("submitted", None), ("interaction_finalized", 410)}
    finalized = service.get_teacher_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
    )
    assert finalized.status == "finalized"
    expected_votes = 1 if submit_outcome[0] == "submitted" else 0
    assert sum(row.count for row in finalized.votes) == expected_votes
    with database.session() as session:
        assert session.scalar(select(func_count(Vote.id))) == expected_votes


def test_teacher_routes_reject_students_and_cross_course_teachers(interaction_app: Any) -> None:
    app, database, client = interaction_app
    canonical_origin = app.state.settings.classroom_public_base_url
    assert canonical_origin is not None
    debate_id, _participant_ids = _seed_finished_debate(database)
    _session, student_csrf = login(client, "bowen")

    get_response = client.get(f"/api/v1/debates/{debate_id}/interaction")
    assert get_response.status_code == 403
    open_response = client.post(
        f"/api/v1/debates/{debate_id}/interaction/open",
        headers={
            "Origin": canonical_origin,
            "X-CSRF-Token": student_csrf,
            "Idempotency-Key": "m13-student-open-denied",
        },
    )
    assert open_response.status_code == 403

    other_course_id = str(uuid4())
    other_teacher_id = _add_teacher(database, course_id=other_course_id)
    service, _collector = _service(database, app.state.settings)
    with pytest.raises(PlatformError) as cross_course:
        service.get_teacher_interaction(
            actor_user_id=other_teacher_id,
            debate_id=debate_id,
        )
    assert cross_course.value.status_code == 404


def test_open_rejects_terminal_playback_with_active_authority(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    with database.session() as session:
        playback = session.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
        assert playback is not None
        playback.controller_epoch = str(uuid4())
        playback.controller_owner_connection = "stale-controller"

    service, _collector = _service(database, app.state.settings)
    with pytest.raises(PlatformError) as active:
        service.open_interaction(
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
            idempotency_key="m13-active-playback-denied",
        )
    assert active.value.code == "invalid_state"


def test_malformed_and_unknown_tokens_are_not_found(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    service, _collector = _service(database, app.state.settings)
    with pytest.raises(PlatformError) as malformed:
        service.public_form(access_token="v1.not-a-token.invalid")
    assert malformed.value.status_code == 404

    unknown = issue_token(uuid4(), b"z" * 32, app.state.settings.secret_bytes)
    with pytest.raises(PlatformError) as unknown_error:
        service.public_form(access_token=unknown)
    assert unknown_error.value.status_code == 404


def test_finalized_snapshot_tampering_fails_closed(interaction_app: Any) -> None:
    app, database, _client = interaction_app
    debate_id, participant_ids = _seed_finished_debate(database)
    service, _collector = _service(database, app.state.settings)
    opened = service.open_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-tamper-open-0001",
    )
    assert opened.public_url is not None
    token = opened.public_url.rsplit("/", 1)[-1]
    service.submit_vote(
        access_token=token,
        payload=VoteRequest(
            participant_id=UUID(participant_ids[0]),
            client_submission_id=uuid4(),
        ),
    )
    service.close_interaction(
        actor_user_id=TEACHER_ID,
        debate_id=debate_id,
        idempotency_key="m13-tamper-close-0001",
    )
    with database.session() as session:
        final_count = session.scalar(select(InteractionFinalVoteCount))
        assert final_count is not None
        final_count.count += 1

    with pytest.raises(PlatformError) as tampered:
        service.get_teacher_interaction(
            actor_user_id=TEACHER_ID,
            debate_id=debate_id,
        )
    assert tampered.value.code == "invalid_state"


def test_downstream_eligibility_uses_the_debate_s_own_round_count() -> None:
    """A four-round debate is complete at four rounds, not at two.

    Three places sized the expected turn count as participants x 2 — the shape
    the original fixtures used. A three-Agent four-round debate therefore looked
    incomplete to all of them: classroom interaction answered 404, the report
    refused to generate, and the teacher's interaction button vanished.
    """

    import json
    from types import SimpleNamespace

    from app.modules.debates.round_count import debate_round_count, expected_turn_count

    for rounds in range(2, 6):
        debate = SimpleNamespace(
            round_count=None,
            rule_snapshot_json=json.dumps({"round_count": rounds}),
        )
        assert debate_round_count(debate) == rounds
        assert expected_turn_count(debate, 3) == 3 * rounds

    # A shape the product would never have accepted falls back rather than
    # sizing a completeness check from it.
    for bad in (0, 1, 6, "3", None, True):
        debate = SimpleNamespace(
            round_count=None, rule_snapshot_json=json.dumps({"round_count": bad})
        )
        assert debate_round_count(debate) == 2

    # The column wins when a caller supplies one, and malformed JSON never raises.
    assert debate_round_count(SimpleNamespace(round_count=4, rule_snapshot_json="{}")) == 4
    assert debate_round_count(SimpleNamespace(round_count=None, rule_snapshot_json="{")) == 2


def test_every_offered_round_count_is_eligible_for_classroom_interaction(
    interaction_app: Any,
) -> None:
    """The completeness gates accept every shape the RuleSet offers.

    A four-round debate used to fail two separate checks in the same function:
    a turn count sized as participants x 2, and a set of expected rounds built
    as (1, 2). The first made classroom interaction answer 404; fixing only it
    moved the failure to the second, which answered invalid_state instead.
    """

    from app.modules.debates.playback.eligibility import has_complete_finished_playback

    _app, database, _client = interaction_app
    for rounds in (2, 3, 4, 5):
        debate_id, _participant_ids = _seed_finished_debate(database, rounds=rounds)
        with database.session() as session:
            assert has_complete_finished_playback(session, debate_id), (
                f"a {rounds}-round debate must be eligible"
            )


def test_a_finished_debate_stays_reviewable_after_its_playback_is_stopped(
    interaction_app: Any,
) -> None:
    """Starting the next lesson must not erase this one's history.

    Publication only happens by playing a turn, so an all-public plan already
    proves the run completed. Playback status is transient: starting another
    debate revokes this one, an operator reset stops it, a restart re-fences
    it. The gate used to require ``completed`` there, so a lesson that ran
    perfectly lost its classroom-interaction entry as soon as the teacher
    started the next debate.
    """

    from app.modules.debates.playback.eligibility import has_complete_finished_playback

    _app, database, _client = interaction_app
    debate_id, _participant_ids = _seed_finished_debate(database)
    with database.session() as session:
        assert has_complete_finished_playback(session, debate_id)
        playback = session.scalar(select(PlaybackState).where(PlaybackState.debate_id == debate_id))
        assert playback is not None
        playback.status = "stopped"
        session.commit()
    with database.session() as session:
        assert has_complete_finished_playback(session, debate_id), (
            "a completed run stays reviewable once its playback is stopped"
        )


def test_a_complete_finish_releases_its_audio_and_a_partial_one_keeps_it(
    interaction_app: Any,
) -> None:
    """Audio is the largest thing a finished lesson holds and the least re-read.

    Only a run that reached the end qualifies. A partial Finish, a failure and
    a stop keep theirs, because those are the runs a teacher goes back to.
    """

    from app.modules.debates.playback._control import PlaybackControlMixin
    from app.modules.debates.playback.eligibility import has_complete_finished_playback

    _app, database, _client = interaction_app
    complete_id, _ = _seed_finished_debate(database)
    partial_id, _ = _seed_finished_debate(database)
    with database.session() as session:
        # Make the second one a partial finish by unpublishing its last turn.
        last = session.scalars(
            select(DebateTurn)
            .where(DebateTurn.debate_id == partial_id)
            .order_by(DebateTurn.turn_index.desc())
        ).first()
        assert last is not None
        last.publication_status = "unpublished"
        session.commit()
        assert has_complete_finished_playback(session, complete_id)
        assert not has_complete_finished_playback(session, partial_id)

    released: list[str] = []

    class _Store:
        def remove_debate(self, debate_id: str) -> None:
            released.append(debate_id)

    class _Repository:
        def mark_debate_audio_deleted(self, _db: Any, debate_id: str) -> int:
            released.append(f"marked:{debate_id}")
            return 1

    service = PlaybackControlMixin.__new__(PlaybackControlMixin)
    service.audio_store = _Store()  # type: ignore[attr-defined]
    service.repository = _Repository()  # type: ignore[attr-defined]
    service._commit = lambda _db: None  # type: ignore[attr-defined]

    with database.session() as session:
        service._release_completed_audio(session, partial_id)
        assert released == [], "a partial finish keeps its audio"
        service._release_completed_audio(session, complete_id)
        assert released == [complete_id, f"marked:{complete_id}"]
