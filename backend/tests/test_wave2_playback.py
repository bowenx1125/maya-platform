"""Wave 2 playback, private media and SQL generation integration checks."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from app.core.db import Database
from app.core.errors import PlatformError
from app.core.models import (
    Agent,
    AgentVersion,
    FileOperation,
    IdempotencyRecord,
    Job,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSnapshot,
    SnapshotDocument,
    StoredFile,
    VoiceProfile,
)
from app.modules.auth.service import get_auth_context
from app.modules.avatars import DEFAULT_AVATAR_CONFIG
from app.modules.debates.models import (
    Debate,
    DebateParticipant,
    DebatePlaybackState,
    DebateTurn,
)
from app.modules.debates.playback.audio import AudioStore
from app.modules.debates.playback.events import DebateEventHub
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.protocols import (
    MemoryDebate,
    MemoryParticipant,
    MemoryPlaybackRepository,
    MemoryTurn,
)
from app.modules.debates.playback.router import _websocket_origin_allowed
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.sql_repository import SqlPlaybackRepository, SqlRow
from app.modules.debates.playback.task_manager import TaskManager
from app.modules.debates.setup.audio_swap import AudioSwapRequest, prepare_audio_swap_journal
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge.recovery import recover_file_operations
from app.modules.knowledge.services import claim_idempotency
from app.providers.llm import MockLLMProvider
from app.providers.tts import MockTTSProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_BOWEN_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"
GROUP_KAIKAI_ID = "699112be-780b-5ffd-9a87-3762f596c558"
TOPIC = "Should the United States ban TikTok's recommendation algorithm?"


def _headers(csrf: str, **extra: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf, **extra}


def _insert_published_agent(
    database: Database,
    *,
    group_id: str,
    name: str,
    evidence: str,
) -> str:
    now = datetime.now(UTC)
    agent_id, version_id, snapshot_id, document_id, file_id, snapshot_document_id = (
        str(uuid4()) for _ in range(6)
    )
    chunk_id = str(uuid4())
    relative_path = f"groups/{group_id}/knowledge/{document_id}/{name.lower()}.md"
    path = (database.data_root or Path("/tmp")) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = evidence.encode("utf-8")
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    with database.session() as db:
        db.add(
            StoredFile(
                id=file_id,
                kind="markdown",
                relative_path=relative_path,
                sha256=digest,
                size_bytes=len(raw),
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            KnowledgeDocument(
                id=document_id,
                group_id=group_id,
                source_filename=f"{name.lower()}-evidence.md",
                stored_file_id=file_id,
                char_count=len(evidence),
                index_status="ready",
                index_revision=1,
                workspace_state="active",
                content_hash=digest,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            Agent(
                id=agent_id,
                group_id=group_id,
                name=name,
                description=f"{name} classroom perspective",
                status="active",
                current_published_version_id=version_id,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            AgentVersion(
                id=version_id,
                agent_id=agent_id,
                version_seq=0,
                state="published",
                revision=1,
                agent_md=(
                    f"# Identity\n{name} represents a careful classroom perspective.\n\n"
                    "# Debate Strategy\nRespond civilly, distinguish evidence from opinion, "
                    "and revise the position when another participant makes a valid point."
                ),
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            KnowledgeSnapshot(
                id=snapshot_id,
                agent_version_id=version_id,
                stored_file_id=file_id,
                content_hash=digest,
                total_char_count=len(evidence),
                embedding_key=EMBEDDING_KEY,
                chunking_json='{"kind":"test"}',
                created_at=now,
            )
        )
        db.flush()
        db.add(
            SnapshotDocument(
                id=snapshot_document_id,
                snapshot_id=snapshot_id,
                document_id=document_id,
                stored_file_id=file_id,
                source_filename=f"{name.lower()}-evidence.md",
                char_count=len(evidence),
                order_index=0,
            )
        )
        db.flush()
        db.add(
            KnowledgeChunk(
                id=chunk_id,
                snapshot_id=snapshot_id,
                snapshot_document_id=snapshot_document_id,
                document_id=document_id,
                chunk_index=0,
                chunk_text=evidence,
                start_offset=0,
                end_offset=len(evidence),
                embedding_blob=mock_embedding(evidence),
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_key=EMBEDDING_KEY,
            )
        )
    return agent_id


def _wait_for_ready(client: TestClient, debate_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 3
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/debates/{debate_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last["playback"]["status"] == "ready":
            return last
        time.sleep(0.02)
    raise AssertionError(f"playback did not become ready: {last}")


def _receive_until(socket: Any, field: str, value: str) -> dict[str, Any]:
    seen: list[tuple[str | None, str | None]] = []
    for _index in range(16):
        message = socket.receive_json()
        seen.append((message.get("message_type"), message.get("event_type")))
        if message.get(field) == value:
            return cast(dict[str, Any], message)
    raise AssertionError(f"did not receive {field}={value}; seen={seen}")


def _valid_speech() -> str:
    """Return a deterministic 80-word text accepted by the playback DTO."""

    return " ".join(f"classroom-word-{index}" for index in range(80))


def _wav_bytes() -> bytes:
    """Create a tiny valid WAV without invoking a provider."""

    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8_000)
        wav.writeframes(b"\x00\x00" * 80)
    return stream.getvalue()


def _memory_debate(
    repository: MemoryPlaybackRepository,
    *,
    course_id: str,
    status: str = "draft",
) -> MemoryDebate:
    """Build a two-participant memory debate for state-machine probes."""

    return repository.add_debate(
        MemoryDebate(
            course_id=course_id,
            topic=TOPIC,
            status=status,
            participants=[
                MemoryParticipant(slot="A", order_index=0, name="Bowen"),
                MemoryParticipant(slot="B", order_index=1, name="KaiKai"),
            ],
        )
    )


def test_sql_start_prepares_only_current_and_successor_without_public_leak(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence=(
                "TikTok recommendation algorithm policy should address privacy, national "
                "security, transparency, user choice, and measurable safeguards before a ban."
            ),
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="KaiKai",
            evidence="Quartz orchids mineral lattice thermodynamics basalt geometry.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-playback-create-001"}),
            json={
                "topic": TOPIC,
                "participants": [
                    {
                        "agent_id": bowen_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "support",
                    },
                    {
                        "agent_id": kaikai_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "oppose",
                    },
                ],
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]

        def start_same_key() -> Any:
            return client.post(
                f"/api/v1/debates/{debate_id}/start",
                headers=_headers(csrf, **{"Idempotency-Key": "wave2-playback-start-001"}),
                json={
                    "expected_revision": 0,
                    "expected_current_audio_debate_id": None,
                    "confirm_previous_audio_cleanup": False,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            started, concurrent_replay = tuple(pool.map(lambda _index: start_same_key(), range(2)))
        assert started.status_code == 200, started.text
        assert concurrent_replay.status_code == 200, concurrent_replay.text
        assert started.json()["id"] == concurrent_replay.json()["id"] == debate_id
        assert started.json()["status"] == concurrent_replay.json()["status"] == "running"
        ready = _wait_for_ready(client, debate_id)
        assert ready["public_turns"] == []
        assert ready["playback"]["current_turn_id"] is not None

        with database.session() as db:
            turns = list(
                db.scalars(
                    select(DebateTurn)
                    .where(DebateTurn.debate_id == debate_id)
                    .order_by(DebateTurn.turn_index)
                ).all()
            )
            assert len(turns) == 4
            assert turns[0].generation_status == "final_ready"
            assert sum(turn.generation_status in {"running", "final_ready"} for turn in turns) <= 2
            assert turns[0].publication_status == "unpublished"
            assert turns[0].predecessor_turn_ids_json == "[]"
            assert turns[0].transcript_hash
            assert turns[0].word_count is not None and 80 <= turns[0].word_count <= 200
            assert turns[0].retrieval_status == "matched"
            assert turns[1].retrieval_status in {None, "no_match"}

        current_turn_id = ready["playback"]["current_turn_id"]
        denied = client.get(f"/api/v1/debates/{debate_id}/audio/{current_turn_id}")
        assert denied.status_code == 403
        transcript = client.get(f"/api/v1/debates/{debate_id}/transcript")
        assert transcript.status_code == 200
        assert transcript.json()["turns"] == []
        assert transcript.json()["audio_retained"] is True

        replay = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-playback-start-001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert replay.status_code == 200
        assert replay.json()["id"] == debate_id


def test_main_composes_playback_service(app_factory: Any) -> None:
    app, _database, _settings = app_factory()
    assert isinstance(app, FastAPI)
    assert app.state.playback_service.turn_preparer is not None


def test_sql_shared_attempt_two_commits_under_the_original_claim(app_factory: Any) -> None:
    app, database, settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Repair Bowen",
            evidence="TikTok transparency privacy safeguards independent review and user choice.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Repair KaiKai",
            evidence=(
                "Competition expression proportional regulation privacy and security safeguards."
            ),
        )
        llm = MockLLMProvider(["technical"])
        app.state.playback_service.turn_preparer = SqlTurnPreparer(settings=settings, llm=llm)
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "attempt-two-create-001"}),
            json={
                "topic": TOPIC,
                "participants": [
                    {
                        "agent_id": bowen_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "support",
                    },
                    {
                        "agent_id": kaikai_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "oppose",
                    },
                ],
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "attempt-two-start-001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        ready = _wait_for_ready(client, debate_id)
        assert ready["playback"]["status"] == "ready"
        with database.session() as db:
            turn = db.scalar(
                select(DebateTurn)
                .where(DebateTurn.debate_id == debate_id)
                .order_by(DebateTurn.turn_index)
            )
            assert turn is not None
            assert (turn.generation_status, turn.attempt) == ("final_ready", 2)
            job_attempt, job_state = db.execute(
                text("SELECT attempt,state FROM jobs WHERE turn_id=:turn_id"),
                {"turn_id": turn.id},
            ).one()
            assert (job_attempt, job_state) == (2, "completed")
        assert llm.calls in {2, 3}
        assert [item.turn_id for item in llm.call_log[:2]] == [turn.id, turn.id]


def test_sql_concurrent_different_starts_leave_one_running_debate(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Concurrent Bowen",
            evidence="TikTok transparency privacy safeguards and accountable review.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Concurrent KaiKai",
            evidence="Competition expression proportional policy and user choice.",
        )
        _session, csrf = login(client)
        debate_ids: list[str] = []
        for index in range(2):
            created = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=_headers(
                    csrf,
                    **{"Idempotency-Key": f"different-start-create-{index:04d}"},
                ),
                json={
                    "topic": f"{TOPIC} #{index}",
                    "participants": [
                        {
                            "agent_id": bowen_id,
                            "stance_mode": "assigned",
                            "assigned_stance": "support",
                        },
                        {
                            "agent_id": kaikai_id,
                            "stance_mode": "assigned",
                            "assigned_stance": "oppose",
                        },
                    ],
                    "round_count": 2,
                },
            )
            assert created.status_code == 201, created.text
            debate_ids.append(created.json()["id"])

        def start(index: int) -> Any:
            return client.post(
                f"/api/v1/debates/{debate_ids[index]}/start",
                headers=_headers(
                    csrf,
                    **{"Idempotency-Key": f"different-start-run-{index:04d}"},
                ),
                json={
                    "expected_revision": 0,
                    "expected_current_audio_debate_id": None,
                    "confirm_previous_audio_cleanup": False,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = tuple(pool.map(start, range(2)))
        assert sorted(response.status_code for response in responses) == [200, 409]
        rejected = next(response for response in responses if response.status_code == 409)
        assert rejected.json()["code"] in {
            "debate_already_running",
            "stale_control_version",
            "stale_revision",
            "file_operation_failed",
        }
        with database.session() as db:
            running = list(
                db.scalars(
                    select(Debate).where(
                        Debate.course_id == COURSE_ID,
                        Debate.status == "running",
                    )
                ).all()
            )
            assert len(running) == 1


def test_sql_state_and_event_share_one_commit_or_rollback(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Atomic Bowen",
            evidence="TikTok transparency safeguards and accountable independent review.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Atomic KaiKai",
            evidence="Algorithmic speech, competition, proportional policy, and user choice.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "atomic-event-create-001"}),
            json={
                "topic": TOPIC,
                "participants": [
                    {
                        "agent_id": bowen_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "support",
                    },
                    {
                        "agent_id": kaikai_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "oppose",
                    },
                ],
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        participant_ids = [item["id"] for item in created.json()["participants"]]
        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        payload = {
            "rule_set_id": "ordered_multi_agent_rounds_demo_v1",
            "participants": [
                {
                    "participant_id": participant_id,
                    "slot": chr(65 + index),
                    "order_index": index,
                    "name": f"Agent {index + 1}",
                }
                for index, participant_id in enumerate(participant_ids)
            ],
        }

        with database.session() as db:
            db.execute(
                text("UPDATE debates SET status='running' WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            repository.append_event_tx(
                db,
                debate_id=debate_id,
                event_type="debate.started",
                payload=payload,
            )
            db.rollback()
        with database.session() as db:
            status, sequence = db.execute(
                text("SELECT status,last_sequence FROM debates WHERE id=:debate_id"),
                {"debate_id": debate_id},
            ).one()
            event_count = db.execute(
                text("SELECT COUNT(*) FROM debate_events WHERE debate_id=:debate_id"),
                {"debate_id": debate_id},
            ).scalar_one()
            assert (status, sequence, event_count) == ("draft", 0, 0)

        with database.session() as db:
            db.execute(
                text("UPDATE debates SET status='running' WHERE id=:debate_id"),
                {"debate_id": debate_id},
            )
            repository.append_event_tx(
                db,
                debate_id=debate_id,
                event_type="debate.started",
                payload=payload,
            )
        with database.session() as db:
            status, sequence = db.execute(
                text("SELECT status,last_sequence FROM debates WHERE id=:debate_id"),
                {"debate_id": debate_id},
            ).one()
            event_count = db.execute(
                text("SELECT COUNT(*) FROM debate_events WHERE debate_id=:debate_id"),
                {"debate_id": debate_id},
            ).scalar_one()
            assert (status, sequence, event_count) == ("running", 1, 1)


def test_tts_voice_is_revalidated_custom_then_system_then_mock(app_factory: Any) -> None:
    app, database, settings = app_factory()
    custom_id, fallback_id = str(uuid4()), str(uuid4())
    timestamp = datetime.now(UTC)
    with TestClient(app):
        with database.session() as db:
            db.add_all(
                [
                    VoiceProfile(
                        id=custom_id,
                        scope="group",
                        group_id=GROUP_BOWEN_ID,
                        display_name="Custom ready voice",
                        status="ready",
                        provider_key="mock",
                        target_model_key="mock-tts",
                        external_id_encrypted=None,
                        recovery_name=f"custom-{custom_id}",
                        provenance_json="{}",
                        created_at=timestamp,
                        updated_at=timestamp,
                    ),
                    VoiceProfile(
                        id=fallback_id,
                        scope="system",
                        group_id=None,
                        display_name="System English Fallback",
                        status="ready",
                        provider_key="mock",
                        target_model_key="mock-tts",
                        external_id_encrypted=None,
                        recovery_name=f"system-{fallback_id}",
                        provenance_json="{}",
                        created_at=timestamp,
                        updated_at=timestamp,
                    ),
                ]
            )
        settings.fallback_voice_profile_id = fallback_id
        frozen_participant = SqlRow(
            {
                "effective_voice_kind": "platform_profile",
                "effective_voice_profile_id": custom_id,
            }
        )
        with database.session() as db:
            custom = SqlPlaybackRepository.resolve_effective_voice(db, frozen_participant, settings)
            assert (custom.kind, custom.profile_id) == ("platform_profile", custom_id)
            custom_row = db.get(VoiceProfile, custom_id)
            assert custom_row is not None
            custom_row.status = "deleted"
        with database.session() as db:
            fallback = SqlPlaybackRepository.resolve_effective_voice(
                db, frozen_participant, settings
            )
            assert (fallback.kind, fallback.profile_id) == ("platform_profile", fallback_id)
            fallback_row = db.get(VoiceProfile, fallback_id)
            assert fallback_row is not None
            fallback_row.status = "deleted"
        with database.session() as db:
            sentinel = SqlPlaybackRepository.resolve_effective_voice(
                db, frozen_participant, settings
            )
            assert (sentinel.kind, sentinel.profile_id, sentinel.voice_token) == (
                "mock_sentinel",
                None,
                "mock",
            )
        assert frozen_participant.effective_voice_profile_id == custom_id


def test_expired_start_claim_recovers_typed_audio_before_token_takeover(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    old_debate_id, new_debate_id, record_id = (str(uuid4()) for _ in range(3))
    timestamp = datetime.now(UTC)
    key = "expired-start-audio-takeover-001"
    body_hash = "c" * 64
    request_id = str(uuid4())
    source = f"courses/{COURSE_ID}/current-debate-audio/{old_debate_id}"
    staging = f"staging/audio-swap/{COURSE_ID}/{request_id}/{old_debate_id}"
    with TestClient(app) as client:
        with database.session() as db:
            for debate_id, status in (
                (old_debate_id, "debate_finished"),
                (new_debate_id, "draft"),
            ):
                db.add(
                    Debate(
                        id=debate_id,
                        course_id=COURSE_ID,
                        topic=f"Audio takeover {debate_id}",
                        rule_set_id="ordered_multi_agent_rounds_demo_v1",
                        rule_snapshot_json="{}",
                        status=status,
                        revision=0,
                        last_sequence=0,
                        cancellation_generation=0,
                        created_by="98644172-6bbb-5383-8198-3b78dcd5b9ab",
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
            db.flush()
            db.execute(
                text("UPDATE courses SET current_audio_debate_id=:old WHERE id=:course"),
                {"old": old_debate_id, "course": COURSE_ID},
            )
            db.add(
                IdempotencyRecord(
                    id=record_id,
                    actor_user_id="98644172-6bbb-5383-8198-3b78dcd5b9ab",
                    operation="startDebate",
                    key=key,
                    request_hash=body_hash,
                    state="pending",
                    claim_token="expired-token",
                    lease_expires_at=timestamp.replace(year=timestamp.year - 1),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            db.flush()
            prepare_audio_swap_journal(
                db,
                AudioSwapRequest(
                    course_id=COURSE_ID,
                    request_id=request_id,
                    old_debate_id=old_debate_id,
                    source_relative_path=source,
                    staging_relative_path=staging,
                    new_debate_id=new_debate_id,
                    expected_old_debate_id=old_debate_id,
                    idempotency_record_id=record_id,
                ),
            )
        staging_path = settings.resolved_data_root / staging
        staging_path.mkdir(parents=True)
        staging_path.joinpath("turn.wav").write_bytes(b"retained-audio")
        _login, _csrf = login(client)
        raw_token = client.cookies.get("maya_session")
        assert raw_token
        with database.session() as db:
            context = get_auth_context(db, settings, raw_token)
            assert context is not None
            claimed, replay = claim_idempotency(
                db,
                context,
                "startDebate",
                key,
                body_hash,
                data_root=settings.resolved_data_root,
                takeover_recovery=app.state.playback_service._recover_claim_audio_swaps,
            )
            assert replay is None
            assert claimed.claim_token != "expired-token"
        with database.session() as db:
            journal = db.scalar(
                select(FileOperation).where(FileOperation.idempotency_record_id == record_id)
            )
            assert journal is not None and journal.state == "recovered"
        assert not staging_path.exists()
        assert (settings.resolved_data_root / source / "turn.wav").read_bytes() == b"retained-audio"


def test_wave1_generic_recovery_never_consumes_typed_audio_swap(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    with TestClient(app):
        source = settings.resolved_data_root / "courses" / str(uuid4()) / "retained"
        source.mkdir(parents=True)
        marker = source / "turn.wav"
        marker.write_bytes(b"retained")
        operation_id = str(uuid4())
        with database.session() as db:
            db.add(
                FileOperation(
                    id=operation_id,
                    operation_kind="debate_audio_swap",
                    entity_id=str(uuid4()),
                    request_id=str(uuid4()),
                    source_relative_path=str(source.relative_to(settings.resolved_data_root)),
                    target_relative_path=None,
                    expected_sha256=None,
                    old_audio_debate_id=None,
                    staging_relative_path=f"staging/audio-swap/{uuid4()}",
                    new_debate_id=None,
                    expected_old_debate_id=None,
                    state="prepared",
                    safe_error_code=None,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        with database.session() as db:
            recover_file_operations(db, settings.resolved_data_root)
            operation = db.get(FileOperation, operation_id)
            assert operation is not None and operation.state == "prepared"
        assert marker.read_bytes() == b"retained"


async def _memory_ready_service(
    tmp_path: Path,
) -> tuple[PlaybackService, MemoryDebate, TaskManager]:
    repository = MemoryPlaybackRepository()
    debate = repository.add_debate(
        MemoryDebate(
            topic=TOPIC,
            participants=[
                MemoryParticipant(slot="A", order_index=0, name="Bowen"),
                MemoryParticipant(slot="B", order_index=1, name="KaiKai"),
            ],
        )
    )
    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=AudioStore(tmp_path),
        task_manager=tasks,
    )
    await service.start(
        None,
        debate.id,
        expected_revision=0,
        expected_current_audio_debate_id=None,
        confirm_previous_audio_cleanup=False,
    )
    await tasks.wait_debate(debate.id)
    assert service._state(None, debate).status == "ready"
    return service, debate, tasks


def test_websocket_drives_four_public_turns_and_replay_without_regeneration(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence=(
                "TikTok recommendation algorithm transparency, privacy, user choice, "
                "national security, safeguards, and accountable independent review."
            ),
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="KaiKai",
            evidence="Quartz orchid mineral lattice basalt geometry thermodynamics.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-ws-create-0001"}),
            json={
                "topic": TOPIC,
                "participants": [
                    {
                        "agent_id": bowen_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "support",
                    },
                    {
                        "agent_id": kaikai_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "oppose",
                    },
                ],
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-ws-start-0001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        _wait_for_ready(client, debate_id)

        service = app.state.playback_service
        llm = service.turn_preparer.llm
        tts = service.audio_store.tts_provider
        with client.websocket_connect(
            f"/api/v1/debates/{debate_id}/events",
            headers={"origin": "http://testserver"},
        ) as socket:
            snapshot = _receive_until(socket, "event_type", "snapshot")
            assert snapshot["payload"]["public_turns"] == []
            control_version = snapshot["payload"]["playback"]["control_version"]
            acquire_id = str(uuid4())
            socket.send_json(
                {
                    "command_id": acquire_id,
                    "command_type": "playback.controller.acquire",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": control_version,
                }
            )
            acquired = _receive_until(socket, "message_type", "controller.acquired")
            epoch = acquired["controller_epoch"]
            control_version = acquired["control_version"]
            published_turn_ids: list[str] = []

            for turn_number in range(4):
                detail = _wait_for_ready(client, debate_id)
                turn_id = detail["playback"]["current_turn_id"]
                assert turn_id is not None
                prepare_id = str(uuid4())
                socket.send_json(
                    {
                        "command_id": prepare_id,
                        "command_type": "playback.media.prepare",
                        "command_version": 1,
                        "debate_id": debate_id,
                        "expected_control_version": control_version,
                        "controller_epoch": epoch,
                        "turn_id": turn_id,
                        "playback_action": "start",
                    }
                )
                media = _receive_until(socket, "message_type", "media.prepared")
                assert media["media_url"].startswith(
                    f"/api/v1/debates/{debate_id}/audio/{turn_id}?media_ticket="
                )
                audio = client.get(media["media_url"])
                assert audio.status_code == 200
                ranged = client.get(media["media_url"], headers={"Range": "bytes=0-63"})
                assert ranged.status_code == 206
                unsatisfied = client.get(media["media_url"], headers={"Range": "bytes=999999-"})
                assert unsatisfied.status_code == 416
                assert unsatisfied.json()["code"] == "range_not_satisfiable"
                socket.send_json(
                    {
                        "command_id": str(uuid4()),
                        "command_type": "playback.started_ack",
                        "command_version": 1,
                        "debate_id": debate_id,
                        "expected_control_version": control_version,
                        "controller_epoch": epoch,
                        "turn_id": turn_id,
                        "playback_action": "start",
                    }
                )
                public = _receive_until(socket, "event_type", "playback.started")
                assert public["payload"]["turn_id"] == turn_id
                assert public["payload"]["speech"]
                assert "provider" not in str(public).lower()
                published_turn_ids.append(turn_id)
                socket.send_json(
                    {
                        "command_id": str(uuid4()),
                        "command_type": "playback.ended_ack",
                        "command_version": 1,
                        "debate_id": debate_id,
                        "expected_control_version": control_version,
                        "controller_epoch": epoch,
                        "turn_id": turn_id,
                    }
                )
                completed = _receive_until(socket, "event_type", "playback.completed")
                assert completed["payload"]["turn_id"] == turn_id
                control_version = completed["payload"]["control_version"]
                if turn_number < 3:
                    _wait_for_ready(client, debate_id)

            final = client.get(f"/api/v1/debates/{debate_id}")
            assert final.status_code == 200
            final_body = final.json()
            assert final_body["status"] == "debate_finished"
            assert [item["id"] for item in final_body["public_turns"]] == published_turn_ids
            assert len(final_body["public_turns"]) == 4
            assert any(item["retrieval_status"] == "matched" for item in final_body["public_turns"])
            assert any(
                item["retrieval_status"] == "no_match" for item in final_body["public_turns"]
            )

            with database.session() as db:
                rows = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    ).all()
                )
                assert [row.predecessor_turn_ids_json for row in rows] == [
                    "[]",
                    f'["{rows[0].id}"]',
                    f'["{rows[0].id}","{rows[1].id}"]',
                    f'["{rows[0].id}","{rows[1].id}","{rows[2].id}"]',
                ]
                structured = [json.loads(row.structured_json or "{}") for row in rows]
                assert structured[2]["rebuttal_target_turn_id"] in {rows[0].id, rows[1].id}
                assert structured[2]["question"]["type"] == "agent"
                assert structured[2]["question"]["target_participant_id"] == rows[3].participant_id
                assert structured[3]["question"]["type"] == "audience_reflection"
                assert structured[3]["question"]["target_participant_id"] is None

            assert llm.call_count == 4
            assert tts.synthesize_calls == 4
            replay = client.post(
                f"/api/v1/debates/{debate_id}/turns/{published_turn_ids[0]}/replay",
                headers=_headers(csrf),
                json={"expected_control_version": control_version},
            )
            assert replay.status_code == 200, replay.text
            control_version = replay.json()["control_version"]
            socket.send_json(
                {
                    "command_id": str(uuid4()),
                    "command_type": "playback.media.prepare",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": control_version,
                    "controller_epoch": epoch,
                    "turn_id": published_turn_ids[0],
                    "playback_action": "replay",
                }
            )
            _receive_until(socket, "message_type", "media.prepared")
            socket.send_json(
                {
                    "command_id": str(uuid4()),
                    "command_type": "playback.started_ack",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": control_version,
                    "controller_epoch": epoch,
                    "turn_id": published_turn_ids[0],
                    "playback_action": "replay",
                }
            )
            _receive_until(socket, "event_type", "replay.started")
            socket.send_json(
                {
                    "command_id": str(uuid4()),
                    "command_type": "playback.ended_ack",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": control_version,
                    "controller_epoch": epoch,
                    "turn_id": published_turn_ids[0],
                }
            )
            _receive_until(socket, "event_type", "replay.completed")
            assert llm.call_count == 4
            assert tts.synthesize_calls == 4

            # The socket was upgraded with this Session, but logout from a
            # concurrent request must revoke its authority before the next
            # command.  The rejection is private and terminal; it is not a
            # Debate event and must not advance the public sequence.
            logged_out = client.post(
                "/api/v1/auth/logout",
                headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
            )
            assert logged_out.status_code == 204, logged_out.text
            socket.send_json(
                {
                    "command_id": str(uuid4()),
                    "command_type": "playback.controller.acquire",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": 0,
                }
            )
            revoked = _receive_until(socket, "code", "session_revoked")
            assert revoked["recoverable"] is False


@pytest.mark.asyncio
async def test_controller_ticket_pause_resume_and_current_only_audio(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    state = service._state(None, debate)
    assert state.status == "ready"
    first_turn_id = state.current_turn_id
    assert first_turn_id is not None

    acquired = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="session-hash",
        connection_id="teacher-tab",
    )
    epoch = str(acquired.controller_epoch)
    prepared, _result = await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=acquired.control_version,
        epoch=epoch,
        session_hash="session-hash",
        turn_id=first_turn_id,
        action="start",
    )
    authorization = await service.authorize_audio(
        None,
        debate.id,
        first_turn_id,
        session_hash="session-hash",
        media_ticket=prepared.token,
    )
    assert authorization.metadata.turn_id == first_turn_id
    with pytest.raises(PlatformError) as missing_ticket:
        await service.authorize_audio(
            None,
            debate.id,
            first_turn_id,
            session_hash="session-hash",
            media_ticket=None,
        )
    assert missing_ticket.value.code == "forbidden"

    partial = service.audio_store.response(  # type: ignore[union-attr]
        debate.id,
        first_turn_id,
        range_header="bytes=0-31",
    )
    assert partial.status_code == 206
    assert partial.headers["Content-Range"].startswith("bytes 0-31/")
    unsatisfied = service.audio_store.response(  # type: ignore[union-attr]
        debate.id,
        first_turn_id,
        range_header="bytes=999999-",
    )
    assert unsatisfied.status_code == 416

    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=acquired.control_version,
        epoch=epoch,
        session_hash="session-hash",
        turn_id=first_turn_id,
        action="start",
    )
    assert playing.status == "playing"
    assert debate.turns[0].publication_status == "public"
    paused = await service.pause(
        None,
        debate.id,
        expected_control_version=playing.control_version,
    )
    assert paused.status == "paused"
    resumed = await service.resume(
        None,
        debate.id,
        expected_control_version=paused.control_version,
    )
    assert resumed.status == "ready"
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=resumed.control_version,
        epoch=epoch,
        session_hash="session-hash",
        turn_id=first_turn_id,
        action="resume",
    )
    playing_again = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=resumed.control_version,
        epoch=epoch,
        session_hash="session-hash",
        turn_id=first_turn_id,
        action="resume",
    )
    events = list(service.event_hub.store.events_after(debate.id, 0))
    assert events[-1].event_type == "playback.resumed"
    assert sum(event.event_type == "playback.started" for event in events) == 1
    advanced = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=playing_again.control_version,
        epoch=epoch,
        session_hash="session-hash",
        turn_id=first_turn_id,
    )
    assert advanced.current_turn_id is not None
    assert str(advanced.current_turn_id) != first_turn_id
    assert advanced.status == "ready"
    await tasks.close()


@pytest.mark.asyncio
async def test_controller_takeover_parks_playing_once_and_revokes_old_epoch(
    tmp_path: Path,
) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    turn_id = service._state(None, debate).current_turn_id
    assert turn_id is not None
    first = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="session-one",
        connection_id="tab-one",
    )
    prepared, _result = await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=first.control_version,
        epoch=str(first.controller_epoch),
        session_hash="session-one",
        turn_id=turn_id,
        action="start",
    )
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=first.control_version,
        epoch=str(first.controller_epoch),
        session_hash="session-one",
        turn_id=turn_id,
        action="start",
    )
    second = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=first.control_version,
        session_hash="session-two",
        connection_id="tab-two",
    )
    state = service._state(None, debate)
    assert state.status == "paused"
    assert second.control_version == first.control_version + 1
    assert service.take_revocation(str(first.controller_epoch)) is not None
    assert service.ticket_store.get(prepared.token) is None
    await tasks.close()


@pytest.mark.asyncio
async def test_play_failure_is_recoverable_but_stop_is_terminal(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    turn_id = service._state(None, debate).current_turn_id
    assert turn_id is not None
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="session",
        connection_id="tab",
    )
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=turn_id,
        action="start",
    )
    pre_ack = await service.play_failed(
        None,
        debate.id,
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=turn_id,
        failure_phase="pre_ack",
        cursor_ms=0,
        safe_client_code="autoplay_blocked",
    )
    assert pre_ack.status == "ready"
    assert debate.turns[0].publication_status == "unpublished"
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=turn_id,
        action="start",
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=turn_id,
        action="start",
    )
    recovered = await service.play_failed(
        None,
        debate.id,
        expected_control_version=playing.control_version,
        epoch=str(controller.controller_epoch),
        session_hash="session",
        turn_id=turn_id,
        failure_phase="post_ack",
        cursor_ms=10,
        safe_client_code="decode_error",
    )
    assert recovered.status == "ready"
    stopped = await service.stop(
        None,
        debate.id,
        expected_control_version=recovered.control_version,
    )
    assert stopped.status == "stopped"
    assert debate.status == "stopped"
    with pytest.raises(PlatformError):
        await service.resume(
            None,
            debate.id,
            expected_control_version=stopped.control_version,
        )
    await tasks.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "allowed"),
    [
        ("draft", False),
        ("running", False),
        ("failed", False),
        ("stopped", False),
        ("debate_finished", True),
        ("completed", True),
    ],
)
async def test_replay_is_closed_over_the_full_debate_status_matrix(
    tmp_path: Path,
    status: str,
    allowed: bool,
) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()), status=status)
    turn = MemoryTurn(
        participant_id=debate.participants[0].id,
        generation_status="final_ready",
        publication_status="public",
        speech=_valid_speech(),
        audio_relative_path="retained.wav",
    )
    debate.turns = [turn]
    repository.playback_state(None, debate).current_turn_id = turn.id
    tasks = TaskManager()
    # This matrix isolates the status gate; retained-byte checks are covered
    # by the dedicated replay/audio tests below.
    service = PlaybackService(repository, audio_store=None, task_manager=tasks)
    if allowed:
        state = await service.replay_all(None, debate.id, expected_control_version=0)
        assert state.mode == "replay"
        assert state.current_turn_id is not None
    else:
        with pytest.raises(PlatformError) as rejected:
            await service.replay_all(None, debate.id, expected_control_version=0)
        assert rejected.value.code == "invalid_state"
    await tasks.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "failed", "stopped", "debate_finished", "completed"])
async def test_stop_accepts_only_a_running_debate(status: str, tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()), status=status)
    state = repository.playback_state(None, debate)
    state.status = "ready"
    state.current_turn_id = str(uuid4())
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)
    with pytest.raises(PlatformError) as rejected:
        await service.stop(None, debate.id, expected_control_version=0)
    assert rejected.value.code == "invalid_state"
    assert debate.status == status
    await tasks.close()


@pytest.mark.asyncio
async def test_draft_controller_acquire_is_rejected_until_start(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()), status="draft")
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)
    with pytest.raises(PlatformError) as rejected:
        await service.controller_acquire(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=0,
            session_hash="draft-session",
            connection_id="draft-tab",
        )
    assert rejected.value.code == "invalid_state"
    await tasks.close()


@pytest.mark.asyncio
async def test_restart_matrix_fences_generation_and_resets_ready_playback(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    interrupted = _memory_debate(repository, course_id=str(uuid4()), status="running")
    interrupted_turn = MemoryTurn(participant_id=interrupted.participants[0].id)
    interrupted.turns = [interrupted_turn]
    interrupted_turn.generation_status = "running"
    interrupted_state = repository.playback_state(None, interrupted)
    interrupted_state.status = "playing"
    interrupted_state.current_turn_id = interrupted_turn.id
    interrupted_state.controller_epoch = str(uuid4())

    retained = _memory_debate(repository, course_id=str(uuid4()), status="running")
    retained_turn = MemoryTurn(
        participant_id=retained.participants[0].id,
        generation_status="final_ready",
        speech=_valid_speech(),
        audio_relative_path="retained.wav",
    )
    retained.turns = [retained_turn]
    retained_state = repository.playback_state(None, retained)
    retained_state.status = "paused"
    retained_state.current_turn_id = retained_turn.id
    retained_state.cursor_ms = 321
    retained_state.controller_epoch = str(uuid4())
    retained_control_before = retained_state.control_version

    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)
    affected = await service.recover_startup(None)

    assert interrupted.id in affected
    assert interrupted.status == "failed"
    assert interrupted_turn.generation_status == "failed"
    assert interrupted_turn.failed_code == "process_restarted"
    assert interrupted_state.status == "stopped"
    assert interrupted_state.controller_epoch is None

    assert retained.id not in affected
    assert retained.status == "running"
    assert retained_state.status == "ready"
    assert retained_state.current_turn_id == retained_turn.id
    assert retained_state.cursor_ms == 0
    assert retained_state.control_version == retained_control_before + 1
    assert retained_state.controller_epoch is None
    await tasks.close()


def test_sql_restart_fails_the_turn_owned_by_an_interrupted_job(app_factory: Any) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Restart Bowen",
            evidence="Transparent safeguards require accountable review and user choice.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Restart KaiKai",
            evidence="Proportional regulation should preserve expression and competition.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "sql-restart-create-001"}),
            json={
                "topic": TOPIC,
                "participants": [
                    {
                        "agent_id": bowen_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "support",
                    },
                    {
                        "agent_id": kaikai_id,
                        "stance_mode": "assigned",
                        "assigned_stance": "oppose",
                    },
                ],
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        turn_id = str(uuid4())
        timestamp = datetime.now(UTC)
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            assert debate is not None
            participant = db.scalar(
                select(DebateParticipant)
                .where(DebateParticipant.debate_id == debate_id)
                .order_by(DebateParticipant.order_index)
            )
            assert participant is not None
            debate.status = "running"
            db.add(
                DebateTurn(
                    id=turn_id,
                    debate_id=debate_id,
                    participant_id=participant.id,
                    knowledge_snapshot_id=participant.knowledge_snapshot_id,
                    round_no=1,
                    turn_index=0,
                    generation_status="running",
                    publication_status="unpublished",
                    preparation_stage="generation",
                    predecessor_turn_ids_json="[]",
                    retrieval_receipts_json="[]",
                    attempt=1,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
            db.flush()
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            playback.status = "playing"
            playback.mode = "live"
            playback.current_turn_id = turn_id
            playback.cursor_ms = 420
            playback.playback_rate = 1.0
            playback.control_version = 3
            playback.controller_epoch = str(uuid4())
            playback.controller_owner_connection = "restart-tab"
            db.add(
                Job(
                    id=str(uuid4()),
                    document_id=None,
                    debate_id=debate_id,
                    turn_id=turn_id,
                    idempotency_key=f"{debate_id}:{turn_id}",
                    claim_token=str(uuid4()),
                    cancellation_generation=0,
                    operation="debate_turn_prepare",
                    state="running",
                    safe_error_code=None,
                    attempt=1,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )

        repository = SqlPlaybackRepository(session_factory=database.session_factory)
        with database.session() as db:
            assert repository.recover_startup(db) == (debate_id,)

        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            debate = db.get(Debate, debate_id)
            job = db.scalar(select(Job).where(Job.turn_id == turn_id))
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert turn is not None
            assert (turn.generation_status, turn.preparation_stage, turn.safe_error_code) == (
                "failed",
                "failed",
                "process_restarted",
            )
            assert debate is not None and debate.status == "failed"
            assert job is not None and (job.state, job.safe_error_code) == (
                "interrupted",
                "process_restarted",
            )
            assert playback is not None
            assert (playback.status, playback.cursor_ms, playback.controller_epoch) == (
                "stopped",
                0,
                None,
            )


@pytest.mark.asyncio
async def test_snapshot_stream_race_delivers_one_committed_event_after_watermark() -> None:
    debate_id = str(uuid4())
    turn_id = str(uuid4())
    hub = DebateEventHub()
    snapshot = {
        "debate_status": "draft",
        "playback_status": "ready",
        "interaction_status": "closed",
        "insight_status": "not_started",
        "report_status": "not_started",
        "public_turns": [],
        "playback": {
            "status": "ready",
            "mode": "live",
            "current_turn_id": None,
            "cursor_ms": 0,
            "playback_rate": 1.0,
            "control_version": 0,
        },
        "interaction": {
            "status": "closed",
            "votes": [],
            "barrage_count": 0,
            "total_votes": 0,
            "public_url": None,
        },
        "report": {
            "generation_status": "not_started",
            "latest_attempt_status": "not_started",
            "insight": {
                "status": "not_started",
                "included_count": 0,
                "filtered_count": 0,
                "items": [],
            },
            "active_revision_id": None,
            "current_success_revision": None,
        },
    }

    async def snapshot_factory() -> tuple[dict[str, Any], int]:
        event = hub.append_committed(
            debate_id,
            "playback.paused",
            {
                "turn_id": turn_id,
                "cursor_ms": 0,
                "control_version": 1,
                "playback_rate": 1.0,
            },
        )
        await hub.publish(event)
        return snapshot, 0

    stream = hub.stream(debate_id, snapshot_factory)
    snapshot_wire = await anext(stream)
    raced_event = await anext(stream)
    assert snapshot_wire["event_type"] == "snapshot"
    assert snapshot_wire["sequence"] == 0
    assert raced_event["event_type"] == "playback.paused"
    assert raced_event["sequence"] == 1
    # The event was both persisted before the snapshot watermark and queued by
    # the publisher; the second copy must be discarded as a duplicate.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.02)
    await cast(Any, stream).aclose()


def test_websocket_origin_requires_the_exact_configured_gateway(app_factory: Any) -> None:
    _app, _database, settings = app_factory()
    settings.classroom_public_base_url = "https://classroom.example"

    def websocket(origin: str | None) -> Any:
        return SimpleNamespace(
            headers={"origin": origin} if origin is not None else {},
            url=SimpleNamespace(scheme="wss", netloc="classroom.example"),
        )

    assert _websocket_origin_allowed(websocket("https://classroom.example"), settings)
    assert not _websocket_origin_allowed(websocket("https://classroom.example.evil"), settings)
    assert not _websocket_origin_allowed(websocket("http://classroom.example"), settings)
    assert not _websocket_origin_allowed(websocket(None), settings)


@pytest.mark.asyncio
async def test_if_range_returns_range_only_for_matching_current_bytes(tmp_path: Path) -> None:
    course_id, debate_id, turn_id = (str(uuid4()) for _ in range(3))
    store = AudioStore(tmp_path, tts_provider=MockTTSProvider())
    raw = _wav_bytes()
    metadata = store.store_bytes(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        raw=raw,
    )
    etag = f'"{metadata.sha256}"'

    matching = store.response(
        debate_id,
        turn_id,
        range_header="bytes=0-7",
        if_range=etag,
    )
    assert matching.status_code == 206
    assert matching.body == raw[:8]

    stale = store.response(
        debate_id,
        turn_id,
        range_header="bytes=0-7",
        if_range='"' + "0" * 64 + '"',
    )
    assert stale.status_code == 200
    assert stale.body == raw

    matching_date = store.response(
        debate_id,
        turn_id,
        range_header="bytes=0-7",
        if_range=format_datetime(metadata.modified_at, usegmt=True),
    )
    assert matching_date.status_code == 206
    stale_date = store.response(
        debate_id,
        turn_id,
        range_header="bytes=0-7",
        if_range="Wed, 21 Oct 2015 07:28:00 GMT",
    )
    assert stale_date.status_code == 200


@pytest.mark.asyncio
async def test_full_replay_uses_retained_audio_without_provider_calls(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()), status="debate_finished")
    turns = [
        MemoryTurn(
            participant_id=debate.participants[index % 2].id,
            turn_index=index,
            generation_status="final_ready",
            publication_status="public",
            speech=_valid_speech(),
        )
        for index in range(4)
    ]
    debate.turns = turns
    tts = MockTTSProvider()
    store = AudioStore(tmp_path, tts_provider=tts)
    for turn in turns:
        metadata = store.store_bytes(
            course_id=debate.course_id,
            debate_id=debate.id,
            turn_id=turn.id,
            raw=_wav_bytes(),
        )
        turn.audio_relative_path = metadata.relative_path
        turn.audio_duration_ms = metadata.duration_ms
        turn.audio_sha256 = metadata.sha256
    repository.course_audio[debate.course_id] = debate.id
    provider_calls = 0

    async def preparer(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("full replay must not prepare a turn")

    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=store,
        task_manager=tasks,
        turn_preparer=preparer,
        tts_provider=tts,
    )
    replay = await service.replay_all(None, debate.id, expected_control_version=0)
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=replay.control_version,
        session_hash="replay-session",
        connection_id="replay-tab",
    )
    control_version = controller.control_version
    epoch = str(controller.controller_epoch)
    for turn in turns:
        current = service._state(None, debate)
        assert current.current_turn_id == turn.id
        _prepared, _private = await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=control_version,
            epoch=epoch,
            session_hash="replay-session",
            turn_id=turn.id,
            action="replay",
        )
        playing = await service.started_ack(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=control_version,
            epoch=epoch,
            session_hash="replay-session",
            turn_id=turn.id,
            action="replay",
        )
        completed = await service.ended_ack(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=playing.control_version,
            epoch=epoch,
            session_hash="replay-session",
            turn_id=turn.id,
        )
        control_version = completed.control_version
    assert service._state(None, debate).status == "completed"
    assert provider_calls == 0
    assert tts.synthesize_calls == 0
    await tasks.close()


@pytest.mark.asyncio
async def test_concurrent_same_debate_start_is_serialized(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()))
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)

    outcomes = await asyncio.gather(
        *(
            service.start(
                None,
                debate.id,
                expected_revision=0,
                expected_current_audio_debate_id=None,
                confirm_previous_audio_cleanup=False,
                request_id="same-start-key",
            )
            for _ in range(2)
        ),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if not isinstance(item, Exception)]
    failures = [item for item in outcomes if isinstance(item, PlatformError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "invalid_state"
    assert debate.status == "running"
    await tasks.close()


@pytest.mark.asyncio
async def test_concurrent_different_debates_leave_one_running_per_course(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    course_id = str(uuid4())
    first = _memory_debate(repository, course_id=course_id)
    second = _memory_debate(repository, course_id=course_id)
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)

    outcomes = await asyncio.gather(
        *(
            service.start(
                None,
                debate.id,
                expected_revision=0,
                expected_current_audio_debate_id=None,
                confirm_previous_audio_cleanup=False,
                request_id=f"different-start-{index}",
            )
            for index, debate in enumerate((first, second))
        ),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if not isinstance(item, Exception)]
    failures = [item for item in outcomes if isinstance(item, PlatformError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code in {"debate_already_running", "stale_control_version"}
    assert {debate.status for debate in (first, second)} == {"draft", "running"}
    assert sum(debate.status == "running" for debate in (first, second)) == 1
    await tasks.close()


@pytest.mark.asyncio
async def test_start_rejects_stale_retained_audio_pointer_without_mutation(tmp_path: Path) -> None:
    repository = MemoryPlaybackRepository()
    course_id = str(uuid4())
    debate = _memory_debate(repository, course_id=course_id)
    retained_id = str(uuid4())
    repository.course_audio[course_id] = retained_id
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)
    with pytest.raises(PlatformError) as rejected:
        await service.start(
            None,
            debate.id,
            expected_revision=0,
            expected_current_audio_debate_id=None,
            confirm_previous_audio_cleanup=True,
            request_id="stale-pointer",
        )
    assert rejected.value.code == "stale_control_version"
    assert debate.status == "draft"
    assert repository.course_audio[course_id] == retained_id
    await tasks.close()


@pytest.mark.asyncio
async def test_start_next_terminates_old_replay_and_old_audio_becomes_gone(
    tmp_path: Path,
) -> None:
    repository = MemoryPlaybackRepository()
    course_id = str(uuid4())
    old = _memory_debate(repository, course_id=course_id, status="debate_finished")
    old_turn = MemoryTurn(
        participant_id=old.participants[0].id,
        generation_status="final_ready",
        publication_status="public",
        speech=_valid_speech(),
        audio_relative_path="retained.wav",
    )
    old.turns = [old_turn]
    old_state = repository.playback_state(None, old)
    old_epoch = str(uuid4())
    old_state.mode = "replay"
    old_state.status = "playing"
    old_state.current_turn_id = old_turn.id
    old_state.controller_epoch = old_epoch
    old_state.controller_session_hash = "old-session"
    old_state.controller_connection_id = "old-tab"
    old_state.replay_scope = "all"
    old_state.replay_turn_ids = [old_turn.id]
    old_state.replay_index = 0
    # Use the service-owned store so start-next can prove the old ticket is
    # revoked as part of the committed swap boundary.
    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=AudioStore(tmp_path),
        task_manager=tasks,
    )
    # Reissue on the actual store after construction.
    token, _binding = service.ticket_store.issue(
        session_hash="old-session",
        controller_epoch=old_epoch,
        debate_id=old.id,
        turn_id=old_turn.id,
        action="replay",
    )
    repository.course_audio[course_id] = old.id
    new = _memory_debate(repository, course_id=course_id, status="draft")

    await service.start(
        None,
        new.id,
        expected_revision=0,
        expected_current_audio_debate_id=old.id,
        confirm_previous_audio_cleanup=True,
        request_id="start-next-old-replay",
    )
    assert old_state.status == "completed"
    assert old_state.mode == "live"
    assert old_state.controller_epoch is None
    assert service.ticket_store.get(token) is None
    revoked = service.take_revocation(old_epoch)
    assert revoked is not None and revoked["reason"] == "start_next"
    old_events = list(service.event_hub.store.events_after(old.id, 0))
    assert [event.event_type for event in old_events] == ["playback.completed"]
    with pytest.raises(PlatformError) as gone:
        await service.authorize_audio(
            None,
            old.id,
            old_turn.id,
            session_hash="old-session",
            media_ticket=None,
        )
    assert gone.value.status_code == 410
    await tasks.close()
