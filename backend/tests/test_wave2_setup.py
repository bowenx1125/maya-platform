"""Deterministic M10 setup, ordering, snapshot and permission checks."""

from __future__ import annotations

import json
import shutil
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    FileOperation,
    IdempotencyRecord,
    KnowledgeSnapshot,
    StoredFile,
)
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.schemas import DebateDraftRequest, DebateParticipantInput
from app.modules.debates.setup import service as setup_service
from app.modules.debates.setup.audio_swap import (
    AudioSwapRequest,
    AudioSwapState,
    audio_swap_journals_for_idempotency,
    prepare_audio_swap_journal,
    recover_audio_swap,
    transition_audio_swap,
)
from app.modules.debates.setup.router import router as debate_setup_router
from app.modules.debates.setup.rules import RuleViolation, build_turn_plan
from app.modules.debates.setup.service import (
    commit_start_plan,
    create_debate_draft,
    update_debate_draft,
)
from app.modules.debates.topic_language import (
    TOPIC_LANGUAGE_ERROR_CODE,
    TOPIC_LANGUAGE_ERROR_DETAILS,
    validate_english_topic,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select, update

from tests.conftest import login
from tests.persona_fixtures import confirmed_persona_fields

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
GROUP_DEMO_ID = "7813f937-902c-5534-bfb2-ad773a43aeda"
TEACHER_ID = "08b9de2d-bb75-5c71-a64b-231b48f9eb25"


def headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def test_turn_plan_is_exact_for_two_three_and_five_participants() -> None:
    for count in (2, 3, 5):
        ids = [uuid4() for _ in range(count)]
        plan = build_turn_plan(ids, round_count=4, teaching_protocol="four_round_v1")
        assert len(plan) == count * 4
        assert [(entry.round_no, entry.turn_index) for entry in plan] == [
            (round_no, (round_no - 1) * count + speaking_index)
            for round_no in (1, 2, 3, 4)
            for speaking_index in range(count)
        ]
        # Speaking order rotates one seat per round while slot identity follows
        # the teacher's click order, so routing stays stable across rounds.
        for round_no in range(1, 5):
            offset = (round_no - 1) % count
            expected = [(offset + step) % count for step in range(count)]
            entries = plan[(round_no - 1) * count : round_no * count]
            assert [entry.order_index for entry in entries] == expected
            assert [entry.slot for entry in entries] == [chr(65 + item) for item in expected]
        # Openings are independent; later rounds see the exact lower-index prefix.
        assert all(entry.predecessor_turn_indexes == () for entry in plan[:count])
        assert all(
            entry.predecessor_turn_indexes == tuple(range(entry.turn_index))
            for entry in plan[count:]
        )
        # Only the discussion round routes a question, and it targets the next
        # click-order Agent rather than the next speaker.
        assert [entry.question_type for entry in plan] == (
            ["none"] * count + ["agent"] * count + ["none"] * (count * 2)
        )
        for entry in plan[count : count * 2]:
            assert entry.question_target_participant_id == ids[(entry.order_index + 1) % count]


def test_rule_planner_rejects_invalid_count_rounds_and_duplicates() -> None:
    with pytest.raises(RuleViolation) as count_error:
        build_turn_plan([uuid4()])
    assert count_error.value.code == "participant_count_invalid"

    ids = [uuid4(), uuid4()]
    with pytest.raises(RuleViolation) as round_error:
        build_turn_plan(ids, round_count=6)
    assert round_error.value.code == "mutual_learning_round_count_invalid"

    with pytest.raises(RuleViolation) as duplicate_error:
        build_turn_plan([ids[0], ids[0]])
    assert duplicate_error.value.code == "participant_duplicate"


def test_request_validates_assigned_open_and_fixed_round_shapes() -> None:
    agent_id = uuid4()
    with pytest.raises(ValidationError):
        DebateParticipantInput(agent_id=agent_id, stance_mode="assigned")
    with pytest.raises(ValidationError):
        DebateParticipantInput(
            agent_id=agent_id,
            stance_mode="open",
            assigned_stance="support",
        )
    request = DebateDraftRequest(
        topic="A topic",
        round_count=4,
        participants=[
            DebateParticipantInput(
                agent_id=agent_id,
                stance_mode="assigned",
                assigned_stance="support",
            ),
            DebateParticipantInput(agent_id=uuid4(), stance_mode="open"),
        ],
    )
    assert request.round_count == 4


@pytest.mark.parametrize(
    "value",
    [
        "中文议题",
        "TikTok 推荐算法",
        "Запрет TikTok",
        "حظر TikTok",
        "12345?!",
        "English\nline",
        "English\tline",
        "English\u202eline",
        "English😀",
        "English+policy",
        "English\u20dd",
        "\u0301English",
        "\u0327English",
        "English\u2c2e",
        "English\u2c5e",
        "English\u2028line",
    ],
)
def test_topic_accepts_scripts_and_symbols_independently_of_output_language(value: str) -> None:
    assert validate_english_topic(value) == value.strip()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "  Should the United States ban TikTok's recommendation algorithm?  ",
            "Should the United States ban TikTok's recommendation algorithm?",
        ),
        ("Māori perspectives on digital sovereignty", "Māori perspectives on digital sovereignty"),
        ("São Paulo and José's classroom debate", "São Paulo and José's classroom debate"),
        (
            "Cafe\u0301, C\u0327edar, and A\u030angström",
            "Cafe\u0301, C\u0327edar, and A\u030angström",
        ),
        ("naïve policy", "naïve policy"),
        ("\u0149 and \u2132 perspectives", "\u0149 and \u2132 perspectives"),
        ("\ua7cb compatibility letter", "\ua7cb compatibility letter"),
        ("TikTok—should it be banned in 2026?", "TikTok—should it be banned in 2026?"),
        ("A\u00a0normal\u2003space topic", "A\u00a0normal\u2003space topic"),
    ],
)
def test_validate_english_topic_accepts_latin_diacritics_numbers_punctuation_and_spaces(
    value: str, expected: str
) -> None:
    assert validate_english_topic(value) == expected


def _insert_published_agent(
    database: Database,
    *,
    group_id: str,
    name: str,
) -> tuple[str, str, str]:
    agent_id, version_id, snapshot_id, file_id = (str(uuid4()) for _ in range(4))
    now = datetime.now(UTC)
    relative_path = f"groups/{group_id}/knowledge/{file_id}/source.md"
    source_path = (database.data_root or Path("/tmp")) / relative_path
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(f"# {name}\n\nEvidence.", encoding="utf-8")
    with database.session() as session:
        session.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256="a" * 64,
                size_bytes=10,
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
                description=f"{name} perspective",
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
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
                **confirmed_persona_fields(name, now),
            )
        )
        session.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=file_id,
                content_hash="b" * 64,
                total_char_count=10,
                embedding_key="mock",
                chunking_json="{}",
                created_at=now,
            )
        )
    return agent_id, version_id, snapshot_id


def _insert_debate_row(database: Database, *, debate_id: str | None = None) -> str:
    debate_id = debate_id or str(uuid4())
    now = datetime.now(UTC)
    with database.session() as session:
        session.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic="Audio swap boundary",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json="{}",
                status="draft",
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by=TEACHER_ID,
                created_at=now,
                updated_at=now,
            )
        )
    return debate_id


def _create_payload(first_agent_id: str, second_agent_id: str, *, topic: str) -> DebateDraftRequest:
    return DebateDraftRequest(
        topic=topic,
        round_count=4,
        participants=[
            DebateParticipantInput(agent_id=UUID(first_agent_id), stance_mode="open"),
            DebateParticipantInput(agent_id=UUID(second_agent_id), stance_mode="open"),
        ],
    )


@pytest.fixture
def debate_app(app_factory: Any) -> Generator[tuple[FastAPI, Database, TestClient], None, None]:
    app, database, _settings = app_factory()
    # Main owns composition-root registration; this fixture mounts only the
    # M10 setup router so the worker test remains independent of M12 routes.
    app.include_router(debate_setup_router, prefix="/api/v1")
    client = TestClient(app)
    with client:
        yield app, database, client


def test_create_list_get_update_freezes_current_versions_and_click_order(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, client = debate_app
    bowen_id, bowen_version, bowen_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, kaikai_version, kaikai_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    _session, csrf = login(client)
    body = {
        "topic": "Should the United States ban TikTok's recommendation algorithm?",
        "participants": [
            {"agent_id": bowen_id, "stance_mode": "assigned", "assigned_stance": "support"},
            {"agent_id": kaikai_id, "stance_mode": "assigned", "assigned_stance": "oppose"},
        ],
        "round_count": 4,
        "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
    }
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "wave2-create-debate-001"}),
        json=body,
    )
    assert response.status_code == 201, response.text
    created = response.json()
    debate_id = created["id"]
    assert created["revision"] == 0
    assert created["rule_set_id"] == "ordered_multi_expert_mutual_learning_v1"
    with database.session() as db:
        persisted = db.get(Debate, debate_id)
        assert persisted is not None
        persisted_rule = json.loads(persisted.rule_snapshot_json)
        assert persisted_rule["rule_set_id"] == "ordered_multi_expert_mutual_learning_v1"
        assert persisted_rule["retrieval_policy_id"] == "mock_lexical_anchor_v2"
    assert [item["slot"] for item in created["participants"]] == ["A", "B"]
    assert [item["agent_id"] for item in created["participants"]] == [bowen_id, kaikai_id]
    assert [item["agent_version_id"] for item in created["participants"]] == [
        bowen_version,
        kaikai_version,
    ]
    assert [item["knowledge_snapshot_id"] for item in created["participants"]] == [
        bowen_snapshot,
        kaikai_snapshot,
    ]
    assert all(item["voice_fallback_active"] for item in created["participants"])
    assert all(item["effective_voice_profile_id"] is None for item in created["participants"])

    replay = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "wave2-create-debate-001"}),
        json=body,
    )
    assert replay.status_code == 201
    assert replay.json() == created
    conflict_response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "wave2-create-debate-001"}),
        json={**body, "topic": "different"},
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "idempotency_conflict"

    listed = client.get(f"/api/v1/courses/{COURSE_ID}/debates")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [debate_id]
    fetched = client.get(f"/api/v1/debates/{debate_id}")
    assert fetched.status_code == 200
    assert fetched.json()["participants"][0]["agent_name"] == "Bowen"

    update_body = {
        "topic": body["topic"],
        "participants": [
            {"agent_id": kaikai_id, "stance_mode": "open", "assigned_stance": None},
            {"agent_id": bowen_id, "stance_mode": "assigned", "assigned_stance": "neutral"},
        ],
        "round_count": 4,
        "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        "expected_revision": 0,
    }
    updated = client.patch(f"/api/v1/debates/{debate_id}", headers=headers(csrf), json=update_body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 1
    assert [item["slot"] for item in updated.json()["participants"]] == ["A", "B"]
    assert [item["agent_id"] for item in updated.json()["participants"]] == [kaikai_id, bowen_id]
    assert updated.json()["participants"][0]["current_stance"] is None
    assert updated.json()["participants"][1]["current_stance"] == "neutral"

    stale = client.patch(f"/api/v1/debates/{debate_id}", headers=headers(csrf), json=update_body)
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"


def test_embedding_only_slice_keeps_mock_voice_fallback(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    app, database, client = debate_app
    app.state.settings.embedding_provider = "dashscope"
    bowen_id, _bowen_version, _bowen_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Embedding Bowen"
    )
    kaikai_id, _kaikai_version, _kaikai_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Embedding Kaikai"
    )
    _session, csrf = login(client)
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "embed-only-mock-voice-001"}),
        json={
            "topic": "Should platforms explain their recommendation systems?",
            "participants": [
                {"agent_id": bowen_id, "stance_mode": "open"},
                {"agent_id": kaikai_id, "stance_mode": "open"},
            ],
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )
    assert response.status_code == 201, response.text
    assert all(item["voice_fallback_active"] for item in response.json()["participants"])
    assert all(
        item["effective_voice_profile_id"] is None for item in response.json()["participants"]
    )


def test_invalid_topic_is_a_stable_422_before_create_claim_or_update_cas(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, client = debate_app
    bowen_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    _session, csrf = login(client)
    participants = [
        {"agent_id": bowen_id, "stance_mode": "open"},
        {"agent_id": kaikai_id, "stance_mode": "open"},
    ]
    invalid_topic = "\u200b"
    rejected = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "invalid-topic-create-001"}),
        json={"topic": invalid_topic, "participants": participants, "round_count": 4},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == TOPIC_LANGUAGE_ERROR_CODE
    assert rejected.json()["details"] == TOPIC_LANGUAGE_ERROR_DETAILS
    assert invalid_topic not in rejected.text
    with database.session() as db:
        assert db.scalar(select(Debate).where(Debate.topic == invalid_topic)) is None
        assert (
            db.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.key == "invalid-topic-create-001")
            )
            is None
        )

    created = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "invalid-topic-update-seed"}),
        json={
            "topic": "A valid English topic",
            "participants": participants,
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
        },
    )
    assert created.status_code == 201, created.text
    debate_id = created.json()["id"]
    before = client.get(f"/api/v1/debates/{debate_id}").json()
    rejected_update = client.patch(
        f"/api/v1/debates/{debate_id}",
        headers=headers(csrf),
        json={
            "topic": "\u200b",
            "participants": participants,
            "round_count": 4,
            "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
            "expected_revision": before["revision"],
        },
    )
    assert rejected_update.status_code == 422, rejected_update.text
    assert rejected_update.json()["code"] == TOPIC_LANGUAGE_ERROR_CODE
    assert rejected_update.json()["details"] == TOPIC_LANGUAGE_ERROR_DETAILS
    after = client.get(f"/api/v1/debates/{debate_id}").json()
    assert after["revision"] == before["revision"]
    assert after["topic"] == before["topic"]
    assert after["participants"] == before["participants"]


def test_each_participant_uses_one_bounded_agent_version_snapshot_join(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, _client = debate_app
    bowen_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    statements: list[str] = []

    def capture_join(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if (
            "join groups" in normalized
            and "join agent_versions" in normalized
            and "join knowledge_snapshots" in normalized
        ):
            statements.append(normalized)

    event.listen(database.engine, "before_cursor_execute", capture_join)
    try:
        with database.session() as session:
            detail = create_debate_draft(
                session,
                actor_user_id=TEACHER_ID,
                course_id=COURSE_ID,
                payload=_create_payload(bowen_id, kaikai_id, topic="Bounded join"),
            )
            detail = update_debate_draft(
                session,
                actor_user_id=TEACHER_ID,
                debate_id=str(detail.id),
                payload=_create_payload(bowen_id, kaikai_id, topic="Bounded join update"),
                expected_revision=0,
            )
    finally:
        event.remove(database.engine, "before_cursor_execute", capture_join)

    assert len(detail.participants) == 2
    assert len(statements) == len(detail.participants) * 2
    for statement in statements:
        assert "agent_versions.id = agents.current_published_version_id" in statement
        assert "knowledge_snapshots.id = agent_versions.knowledge_snapshot_id" in statement
        assert "agent_versions.agent_id = agents.id" in statement
        assert "knowledge_snapshots.agent_version_id = agent_versions.id" in statement


@pytest.mark.parametrize(
    ("drift_kind", "expected_code"),
    [
        ("agent_pointer", "agent_not_current"),
        ("version_state", "agent_not_current"),
        ("version_snapshot_pointer", "agent_not_current"),
        ("snapshot_content", "rag_missing"),
    ],
)
def test_create_pointer_state_snapshot_drift_rolls_back_everything(
    debate_app: tuple[FastAPI, Database, TestClient],
    monkeypatch: pytest.MonkeyPatch,
    drift_kind: str,
    expected_code: str,
) -> None:
    _app, database, _client = debate_app
    bowen_id, bowen_version, bowen_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    original = setup_service._resolve_agent_version
    drifted = False

    def resolve_then_drift(*args: Any, **kwargs: Any) -> Any:
        nonlocal drifted
        resolved = original(*args, **kwargs)
        if not drifted:
            drifted = True
            session = args[0]
            agent, _group, version, snapshot = resolved[:4]
            if drift_kind == "agent_pointer":
                session.execute(
                    update(Agent)
                    .where(Agent.id == agent.id)
                    .values(current_published_version_id=None)
                )
            elif drift_kind == "version_state":
                session.execute(
                    update(AgentVersion)
                    .where(AgentVersion.id == version.id)
                    .values(state="superseded")
                )
            elif drift_kind == "version_snapshot_pointer":
                session.execute(
                    update(AgentVersion)
                    .where(AgentVersion.id == version.id)
                    .values(knowledge_snapshot_id=None)
                )
            else:
                session.execute(
                    update(KnowledgeSnapshot)
                    .where(KnowledgeSnapshot.id == snapshot.id)
                    .execution_options(synchronize_session=False)
                    .values(content_hash="c" * 64)
                )
        return resolved

    monkeypatch.setattr(setup_service, "_resolve_agent_version", resolve_then_drift)
    with pytest.raises(PlatformError) as error:
        with database.session() as session:
            create_debate_draft(
                session,
                actor_user_id=TEACHER_ID,
                course_id=COURSE_ID,
                payload=_create_payload(bowen_id, kaikai_id, topic="Rollback create"),
            )
    assert error.value.code == expected_code

    with database.session() as session:
        assert session.scalars(select(Debate)).all() == []
        assert session.scalars(select(DebateParticipant)).all() == []
        agent = session.get(Agent, bowen_id)
        version = session.get(AgentVersion, bowen_version)
        snapshot = session.get(KnowledgeSnapshot, bowen_snapshot)
        assert agent is not None and agent.current_published_version_id == bowen_version
        assert version is not None
        assert version.state == "published"
        assert version.knowledge_snapshot_id == bowen_snapshot
        assert snapshot is not None and snapshot.content_hash == "b" * 64


def test_update_pointer_drift_rolls_back_revision_and_participants(
    debate_app: tuple[FastAPI, Database, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app, database, _client = debate_app
    bowen_id, bowen_version, bowen_snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    with database.session() as session:
        created = create_debate_draft(
            session,
            actor_user_id=TEACHER_ID,
            course_id=COURSE_ID,
            payload=_create_payload(bowen_id, kaikai_id, topic="Before update"),
        )
    before_participants = [
        (str(item.agent_id), str(item.agent_version_id)) for item in created.participants
    ]
    original = setup_service._resolve_agent_version
    drifted = False

    def resolve_then_state_drift(*args: Any, **kwargs: Any) -> Any:
        nonlocal drifted
        resolved = original(*args, **kwargs)
        if not drifted:
            drifted = True
            session = args[0]
            version = resolved[2]
            session.execute(
                update(AgentVersion).where(AgentVersion.id == version.id).values(state="superseded")
            )
        return resolved

    monkeypatch.setattr(setup_service, "_resolve_agent_version", resolve_then_state_drift)
    with pytest.raises(PlatformError) as error:
        with database.session() as session:
            update_debate_draft(
                session,
                actor_user_id=TEACHER_ID,
                debate_id=str(created.id),
                payload=_create_payload(bowen_id, kaikai_id, topic="After update"),
                expected_revision=0,
            )
    assert error.value.code == "agent_not_current"

    with database.session() as session:
        debate = session.get(Debate, str(created.id))
        participants = session.scalars(
            select(DebateParticipant)
            .where(DebateParticipant.debate_id == str(created.id))
            .order_by(DebateParticipant.order_index)
        ).all()
        version = session.get(AgentVersion, bowen_version)
        snapshot = session.get(KnowledgeSnapshot, bowen_snapshot)
        assert debate is not None and debate.revision == 0 and debate.topic == "Before update"
        assert [
            (item.agent_id, item.agent_version_id) for item in participants
        ] == before_participants
        assert version is not None and version.state == "published"
        assert version.knowledge_snapshot_id == bowen_snapshot
        assert snapshot is not None and snapshot.content_hash == "b" * 64


def test_create_same_key_concurrency_replays_and_different_hash_conflicts(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, _client = debate_app
    bowen_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    payload = _create_payload(bowen_id, kaikai_id, topic="Concurrent create")
    barrier = Barrier(2)

    def create_once(request_payload: DebateDraftRequest) -> str:
        barrier.wait(timeout=5)
        with database.session() as session:
            return str(
                create_debate_draft(
                    session,
                    actor_user_id=TEACHER_ID,
                    course_id=COURSE_ID,
                    payload=request_payload,
                    idempotency_key="wave2-concurrent-create-001",
                ).id
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_once, payload) for _ in range(2)]
        ids = [future.result(timeout=15) for future in futures]
    assert ids[0] == ids[1]
    with database.session() as session:
        assert session.scalar(select(Debate).where(Debate.topic == "Concurrent create")) is not None
        assert len(session.scalars(select(Debate)).all()) == 1

    different_payload = _create_payload(bowen_id, kaikai_id, topic="Different hash")
    with pytest.raises(PlatformError) as conflict_error:
        with database.session() as session:
            create_debate_draft(
                session,
                actor_user_id=TEACHER_ID,
                course_id=COURSE_ID,
                payload=different_payload,
                idempotency_key="wave2-concurrent-create-001",
            )
    assert conflict_error.value.code == "idempotency_conflict"

    different_barrier = Barrier(2)
    different_key = "wave2-concurrent-different-hash-001"
    different_payloads = (
        _create_payload(bowen_id, kaikai_id, topic="Different hash A"),
        _create_payload(bowen_id, kaikai_id, topic="Different hash B"),
    )

    def create_different_hash(request_payload: DebateDraftRequest) -> tuple[str, str]:
        different_barrier.wait(timeout=5)
        try:
            with database.session() as session:
                result = create_debate_draft(
                    session,
                    actor_user_id=TEACHER_ID,
                    course_id=COURSE_ID,
                    payload=request_payload,
                    idempotency_key=different_key,
                )
            return "created", str(result.id)
        except PlatformError as exc:
            return "error", exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        raced = list(executor.map(create_different_hash, different_payloads))
    assert sorted(item[0] for item in raced) == ["created", "error"]
    assert next(value for kind, value in raced if kind == "error") == "idempotency_conflict"


def test_teacher_student_and_outside_course_boundaries(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, client = debate_app
    bowen_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Bowen"
    )
    kaikai_id, _version, _snapshot = _insert_published_agent(
        database, group_id=GROUP_DEMO_ID, name="Kaikai"
    )
    _session, csrf = login(client)
    body = {
        "topic": "Boundary topic",
        "participants": [
            {"agent_id": bowen_id, "stance_mode": "open"},
            {"agent_id": kaikai_id, "stance_mode": "open"},
        ],
        "round_count": 4,
        "rule_set_id": "ordered_multi_expert_mutual_learning_v1",
    }
    student_session, student_csrf = login(client, "bowen")
    del student_session
    student_create = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(student_csrf, **{"Idempotency-Key": "student-debate-create-001"}),
        json=body,
    )
    assert student_create.status_code == 403
    assert student_create.json()["code"] == "forbidden"

    _session, csrf = login(client)
    teacher_create = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "teacher-debate-create-001"}),
        json=body,
    )
    assert teacher_create.status_code == 201
    debate_id = teacher_create.json()["id"]
    _student_session, _student_csrf = login(client, "bowen")
    student_get = client.get(f"/api/v1/debates/{debate_id}")
    assert student_get.status_code == 403
    outside_course = client.get(f"/api/v1/courses/{uuid4()}/debates")
    assert outside_course.status_code == 404
    unknown = client.get(f"/api/v1/debates/{uuid4()}")
    assert unknown.status_code == 404


def test_commit_start_plan_writes_full_predecessor_prefix_without_public_start_side_effect(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, _client = debate_app
    ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Bowen")[0],
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Kaikai")[0],
    ]
    payload = DebateDraftRequest(
        topic="Ordering",
        round_count=4,
        participants=[
            DebateParticipantInput(agent_id=UUID(ids[0]), stance_mode="open"),
            DebateParticipantInput(agent_id=UUID(ids[1]), stance_mode="open"),
        ],
    )
    with database.session() as session:
        detail = create_debate_draft(
            session,
            actor_user_id=TEACHER_ID,
            course_id=COURSE_ID,
            payload=payload,
        )
        debate = session.get(Debate, str(detail.id))
        assert debate is not None and debate.status == "draft"
        turns = commit_start_plan(session, debate_id=str(detail.id))
        assert debate.status == "draft"
        assert len(turns) == 8
        # Round one is independent; every later turn keeps the exact prefix.
        for turn in turns[:2]:
            assert json.loads(turn.predecessor_turn_ids_json) == []
        for index, turn in enumerate(turns[2:], start=2):
            assert json.loads(turn.predecessor_turn_ids_json) == [item.id for item in turns[:index]]
        assert session.scalar(select(DebateTurn).where(DebateTurn.debate_id == str(detail.id)))


def test_typed_audio_swap_journal_transitions_and_recovery(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, _client = debate_app
    new_debate_id = str(uuid4())
    with database.session() as session:
        now = datetime.now(UTC)
        session.add(
            Debate(
                id=new_debate_id,
                course_id=COURSE_ID,
                topic="Audio swap",
                rule_set_id="ordered_multi_expert_mutual_learning_v1",
                rule_snapshot_json="{}",
                status="draft",
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by=TEACHER_ID,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        # The journal identity is intentionally independent of audio bytes;
        # M12 will perform rename/fsync around these durable transitions.
        journal = prepare_audio_swap_journal(
            session,
            AudioSwapRequest(
                course_id=COURSE_ID,
                request_id=str(uuid4()),
                old_debate_id=None,
                source_relative_path=None,
                staging_relative_path=f"staging/audio-swap/{COURSE_ID}/request/old",
                new_debate_id=new_debate_id,
                expected_old_debate_id=None,
            ),
        )
        assert journal.operation_kind == "debate_audio_swap"
        assert journal.state == "prepared"
        transition_audio_swap(
            session,
            journal.id,
            expected_state=AudioSwapState.PREPARED,
            target_state=AudioSwapState.STAGED,
        )
        transition_audio_swap(
            session,
            journal.id,
            expected_state=AudioSwapState.STAGED,
            target_state=AudioSwapState.COMMITTED,
        )
        outcome = recover_audio_swap(session, journal.id, current_audio_debate_id=new_debate_id)
        assert outcome.action == "delete_staging"
        assert journal.state == "recovered"


@pytest.mark.parametrize(
    ("boundary", "renamed", "staged", "db_committed"),
    [
        ("prepared", False, False, False),
        ("rename_before_staged", True, False, False),
        ("staged", True, True, False),
        ("db_commit", True, True, True),
        ("cleanup", True, True, True),
    ],
)
def test_audio_swap_lease_takeover_covers_each_crash_boundary(
    debate_app: tuple[FastAPI, Database, TestClient],
    boundary: str,
    renamed: bool,
    staged: bool,
    db_committed: bool,
) -> None:
    _app, database, _client = debate_app
    old_debate_id = _insert_debate_row(database)
    new_debate_id = _insert_debate_row(database)
    request_id = f"{boundary}-{uuid4()}"
    record_id = str(uuid4())
    now = datetime.now(UTC)
    with database.session() as session:
        session.add(
            IdempotencyRecord(
                id=record_id,
                actor_user_id=TEACHER_ID,
                operation="startDebate",
                key=f"wave2-audio-{boundary}-{uuid4()}",
                request_hash="c" * 64,
                state="pending",
                claim_token="takeover-claim-token",
                lease_expires_at=now - timedelta(seconds=1),
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        source_relative_path = f"courses/{COURSE_ID}/current-debate-audio/{old_debate_id}"
        staging_relative_path = f"staging/audio-swap/{COURSE_ID}/{request_id}/{old_debate_id}"
        journal = prepare_audio_swap_journal(
            session,
            AudioSwapRequest(
                course_id=COURSE_ID,
                request_id=request_id,
                old_debate_id=old_debate_id,
                source_relative_path=source_relative_path,
                staging_relative_path=staging_relative_path,
                new_debate_id=new_debate_id,
                expected_old_debate_id=old_debate_id,
                idempotency_record_id=record_id,
            ),
        )
        assert journal.idempotency_record_id == record_id
        assert {row.id for row in audio_swap_journals_for_idempotency(session, record_id)} == {
            journal.id
        }
        if staged:
            transition_audio_swap(
                session,
                journal.id,
                expected_state=AudioSwapState.PREPARED,
                target_state=AudioSwapState.STAGED,
            )
        if db_committed:
            transition_audio_swap(
                session,
                journal.id,
                expected_state=AudioSwapState.STAGED,
                target_state=AudioSwapState.COMMITTED,
            )
        if boundary == "cleanup":
            transition_audio_swap(
                session,
                journal.id,
                expected_state=AudioSwapState.COMMITTED,
                target_state=AudioSwapState.CLEANUP_REQUIRED,
            )
        assert journal.state == (
            AudioSwapState.CLEANUP_REQUIRED.value
            if boundary == "cleanup"
            else AudioSwapState.COMMITTED.value
            if db_committed
            else AudioSwapState.STAGED.value
            if staged
            else AudioSwapState.PREPARED.value
        )

    data_root = database.data_root
    assert data_root is not None
    source_path = data_root / source_relative_path
    staging_path = data_root / staging_relative_path
    source_path.mkdir(parents=True)
    (source_path / "turn.wav").write_bytes(b"old-audio")
    if renamed:
        staging_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.replace(staging_path)

    with database.session() as session:
        current_pointer = new_debate_id if db_committed else old_debate_id
        outcome = recover_audio_swap(
            session,
            journal.id,
            current_audio_debate_id=current_pointer,
        )
        assert outcome.staging_relative_path == staging_relative_path
        recovered = session.get(FileOperation, journal.id)
        assert recovered is not None
        assert recovered.state == AudioSwapState.RECOVERED.value

    if db_committed:
        assert outcome.action == "delete_staging"
        if staging_path.exists():
            shutil.rmtree(staging_path)
        assert not staging_path.exists()
        assert not source_path.exists()
    else:
        assert outcome.action == "restore_old"
        if staging_path.exists():
            staging_path.replace(source_path)
        assert source_path.joinpath("turn.wav").read_bytes() == b"old-audio"
        assert not staging_path.exists()


def test_audio_swap_rejects_absolute_and_parent_paths(
    debate_app: tuple[FastAPI, Database, TestClient],
) -> None:
    _app, database, _client = debate_app
    with database.session() as session:
        with pytest.raises(PlatformError):
            prepare_audio_swap_journal(
                session,
                AudioSwapRequest(
                    course_id=COURSE_ID,
                    request_id=str(uuid4()),
                    old_debate_id=None,
                    source_relative_path="/tmp/audio.wav",
                    staging_relative_path="staging/audio.wav",
                    new_debate_id=str(uuid4()),
                    expected_old_debate_id=None,
                ),
            )


def test_topic_background_saved_separately_and_normalized_only_for_model(debate_app):
    from app.modules.debates.topic_language import model_topic

    _app, database, client = debate_app
    agent_ids = [
        _insert_published_agent(database, group_id=GROUP_DEMO_ID, name=name)[0]
        for name in ("Context One", "Context Two")
    ]
    _session, csrf = login(client)
    body = {
        "topic": "中文 + English?\n  🙂",
        "background": "Two students.\n\tOne asks:\u202e ‘为什么？’",
        "output_language": "en",
        "participants": [{"agent_id": agent_id, "stance_mode": "open"} for agent_id in agent_ids],
    }
    response = client.post(
        f"/api/v1/courses/{COURSE_ID}/debates",
        headers=headers(csrf, **{"Idempotency-Key": "background-create-001"}),
        json=body,
    )
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved["background"] == body["background"]
    assert saved["topic"] == body["topic"]
    assert client.get(f"/api/v1/debates/{saved['id']}").json()["background"] == body["background"]
    with database.session() as db:
        debate = db.get(Debate, saved["id"])
        assert debate.background == body["background"]
        assert model_topic(debate.topic, debate.background) == (
            "Topic: 中文 + English? 🙂\n"
            "Background (teacher-provided context): Two students. One asks: ‘为什么？’"
        )
    updated = client.patch(
        f"/api/v1/debates/{saved['id']}",
        headers=headers(csrf),
        json={**body, "background": "Updated scenario", "expected_revision": saved["revision"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["background"] == "Updated scenario"


def test_published_agents_sort_by_creation_and_include_group_name(debate_app):
    from app.core.models import Group

    _app, database, client = debate_app
    old_id = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Alpha Old")[0]
    new_id = _insert_published_agent(database, group_id=GROUP_DEMO_ID, name="Zulu New")[0]
    with database.session() as db:
        db.get(Agent, old_id).created_at = datetime(2024, 1, 1, tzinfo=UTC)
        db.get(Agent, new_id).created_at = datetime(2025, 1, 1, tzinfo=UTC)
        group_name = db.get(Group, GROUP_DEMO_ID).name
    login(client)
    response = client.get(f"/api/v1/courses/{COURSE_ID}/published-agents")
    assert response.status_code == 200, response.text
    rows = [row for row in response.json() if row["agent"]["id"] in {old_id, new_id}]
    assert [row["agent"]["id"] for row in rows] == [new_id, old_id]
    assert all(row["group_name"] == group_name for row in rows)
