"""Wave 2 playback, private media and SQL generation integration checks."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from threading import Barrier
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
from app.modules.debates.setup.audio_swap import (
    AudioSwapRequest,
    AudioSwapState,
    prepare_audio_swap_journal,
    transition_audio_swap,
)
from app.modules.debates.topic_language import TOPIC_LANGUAGE_ERROR_DETAILS
from app.modules.knowledge.markdown import EMBEDDING_DIMENSION, EMBEDDING_KEY, mock_embedding
from app.modules.knowledge.recovery import recover_file_operations
from app.modules.knowledge.services import claim_idempotency
from app.providers.llm import MockLLMProvider
from app.providers.tts import MockTTSProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from starlette.websockets import WebSocketDisconnect

from tests.conftest import login
from tests.persona_fixtures import confirmed_persona_fields

COURSE_ID = "b1ae79ed-e4a6-5b02-9abd-3a3ae944284b"
GROUP_BOWEN_ID = "66ee37fb-5772-5c8f-bb63-46d1783c53ae"
GROUP_KAIKAI_ID = "699112be-780b-5ffd-9a87-3762f596c558"
TOPIC = "Should the United States ban TikTok's recommendation algorithm?"
ACCENTED_NFD_TOPIC = "Should Māori and Cafe\u0301/C\u0327 perspectives shape platform policy?"


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
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                voice_profile_id=None,
                knowledge_snapshot_id=snapshot_id,
                published_at=now,
                created_at=now,
                updated_at=now,
                **confirmed_persona_fields(name, now),
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


def _insert_sql_retained_debate(
    database: Database,
    *,
    agent_id: str,
    status: str = "debate_finished",
) -> tuple[str, str, str, str]:
    """Create one minimal final/public SQL turn with a durable audio row."""

    now = datetime.now(UTC)
    debate_id, participant_id, turn_id, file_id = (str(uuid4()) for _ in range(4))
    with database.session() as db:
        version = db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent_id))
        assert version is not None and version.knowledge_snapshot_id is not None
        agent = db.get(Agent, agent_id)
        assert agent is not None
        snapshot_id = str(version.knowledge_snapshot_id)
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic=TOPIC,
                rule_set_id="ordered_multi_agent_rounds_demo_v1",
                rule_snapshot_json='{"round_count":2}',
                status=status,
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by="98644172-6bbb-5383-8198-3b78dcd5b9ab",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            DebateParticipant(
                id=participant_id,
                debate_id=debate_id,
                course_id=COURSE_ID,
                group_id=str(agent.group_id),
                agent_id=agent_id,
                agent_version_id=str(version.id),
                knowledge_snapshot_id=snapshot_id,
                slot="A",
                order_index=0,
                agent_name=str(agent.name),
                version_label="V1.0",
                avatar_config_json=DEFAULT_AVATAR_CONFIG.model_dump_json(),
                requested_voice_profile_id=None,
                effective_voice_kind="mock_sentinel",
                effective_voice_profile_id=None,
                voice_fallback_active=True,
                stance_mode="assigned",
                initial_stance="support",
                current_stance="support",
                teacher_note="",
                initial_position_summary="A retained position.",
                current_position_summary="A retained position.",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        store = AudioStore(database.data_root or Path("/tmp"))
        relative_path = store.relative_path(COURSE_ID, debate_id, turn_id)
        raw = _wav_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        metadata = store.store_bytes(
            course_id=COURSE_ID,
            debate_id=debate_id,
            turn_id=turn_id,
            raw=raw,
        )
        db.add(
            StoredFile(
                id=file_id,
                kind="debate_audio",
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
            DebateTurn(
                id=turn_id,
                debate_id=debate_id,
                participant_id=participant_id,
                knowledge_snapshot_id=snapshot_id,
                round_no=1,
                turn_index=0,
                generation_status="final_ready",
                publication_status="public",
                preparation_stage="ready",
                speech=_valid_speech(),
                structured_json='{"position_summary":"A retained position."}',
                predecessor_turn_ids_json="[]",
                transcript_hash="a" * 64,
                cutoff_turn_index=-1,
                retrieval_status="no_match",
                grounding_mode="general_reasoning",
                retrieval_receipts_json="[]",
                word_count=80,
                attempt=1,
                audio_file_id=file_id,
                audio_duration_ms=metadata.duration_ms,
                actual_tts_voice_kind="mock_sentinel",
                actual_tts_voice_profile_id=None,
                safe_error_code=None,
                created_at=now,
                updated_at=now,
                public_at=now,
            )
        )
        db.flush()
        db.add(
            DebatePlaybackState(
                id=str(uuid4()),
                debate_id=debate_id,
                status="completed",
                mode="live",
                current_turn_id=None,
                cursor_ms=0,
                playback_rate=1.0,
                control_version=7,
                controller_epoch=None,
                controller_owner_connection=None,
                server_started_at=None,
                replay_scope=None,
                replay_index=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.execute(
            text("UPDATE courses SET current_audio_debate_id=:debate_id WHERE id=:course_id"),
            {"debate_id": debate_id, "course_id": COURSE_ID},
        )
    return debate_id, turn_id, file_id, relative_path


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


def test_start_rejects_legacy_invalid_draft_before_any_plan_job_audio_or_claim(
    app_factory: Any,
) -> None:
    app, database, _settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Legacy Bowen",
            evidence="TikTok transparency, privacy, safeguards, and accountable review.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Legacy KaiKai",
            evidence="Competition, expression, proportional regulation, and user choice.",
        )
        _session, csrf = login(client)
        participants = [
            {"agent_id": bowen_id, "stance_mode": "open"},
            {"agent_id": kaikai_id, "stance_mode": "open"},
        ]
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "legacy-topic-create-001"}),
            json={
                "topic": "A valid English topic",
                "participants": participants,
                "round_count": 2,
            },
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]

        # Simulate a pre-gate draft persisted by an earlier build.  This is a
        # direct fixture mutation, not a product write path.
        with database.session() as db:
            db.execute(
                text("UPDATE debates SET topic=:topic WHERE id=:debate_id"),
                {"topic": "中文议题", "debate_id": debate_id},
            )

        rejected = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "legacy-topic-start-001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["code"] == "topic_language_invalid"
        assert rejected.json()["details"] == TOPIC_LANGUAGE_ERROR_DETAILS
        assert "中文议题" not in rejected.text

        with database.session() as db:
            debate = db.get(Debate, debate_id)
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert debate is not None and debate.status == "draft" and debate.topic == "中文议题"
            assert playback is not None
            assert playback.status == "preparing"
            assert playback.control_version == 0
            assert db.scalar(select(DebateTurn).where(DebateTurn.debate_id == debate_id)) is None
            assert db.scalar(select(Job).where(Job.debate_id == debate_id)) is None
            assert (
                db.scalar(
                    select(StoredFile).where(
                        StoredFile.kind == "debate_audio",
                        StoredFile.relative_path.like(f"%{debate_id}%"),
                    )
                )
                is None
            )
            assert (
                db.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.key == "legacy-topic-start-001"
                    )
                )
                is None
            )

        repaired = client.patch(
            f"/api/v1/debates/{debate_id}",
            headers=_headers(csrf),
            json={
                "topic": TOPIC,
                "participants": participants,
                "round_count": 2,
                "expected_revision": 0,
            },
        )
        assert repaired.status_code == 200, repaired.text
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "legacy-topic-start-fixed-001"}),
            json={
                "expected_revision": repaired.json()["revision"],
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "running"


def test_sql_next_cross_session_claim_has_one_winner_and_stable_stale_loser(
    app_factory: Any,
) -> None:
    """Two independent request sessions cannot promote the same successor twice.

    The barrier is deliberately placed after each service has read the same
    waiting state and immediately before its repository claim.  This reproduces
    the SQLite WAL race that used to turn the second request into
    ``SQLITE_BUSY_SNAPSHOT``/503; the fresh ``BEGIN IMMEDIATE`` claim must make
    one request win and the other return the normal stale-control 409.
    """

    app, database, settings = app_factory()
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Cross Session Bowen",
            evidence="TikTok transparency privacy safeguards and accountable review.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="Cross Session KaiKai",
            evidence="Competition expression proportional policy and user choice.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "cross-session-next-create-001"}),
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
            headers=_headers(csrf, **{"Idempotency-Key": "cross-session-next-start-001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        ready = _wait_for_ready(client, debate_id)
        current_turn_id = str(ready["playback"]["current_turn_id"])

        # Wait until the on-demand successor has a durable final/audio/job
        # result.  The app's normal generation worker remains Mock-only here.
        deadline = time.monotonic() + 5
        successor_turn_id: str | None = None
        while time.monotonic() < deadline:
            with database.session() as db:
                rows = list(
                    db.scalars(
                        select(DebateTurn)
                        .where(DebateTurn.debate_id == debate_id)
                        .order_by(DebateTurn.turn_index)
                    ).all()
                )
                if len(rows) >= 2:
                    successor = rows[1]
                    job_state = db.execute(
                        text("SELECT state FROM jobs WHERE turn_id=:turn_id"),
                        {"turn_id": successor.id},
                    ).scalar_one_or_none()
                    if (
                        successor.generation_status == "final_ready"
                        and successor.preparation_stage == "ready"
                        and successor.audio_file_id is not None
                        and job_state == "completed"
                    ):
                        successor_turn_id = successor.id
                        break
            time.sleep(0.02)
        assert successor_turn_id is not None

        # Establish the exact waiting boundary without involving a websocket;
        # this leaves both service sessions with the same expected control and
        # current turn while retaining the generated audio and job fence.
        with database.session() as db:
            db.execute(
                text(
                    "UPDATE debate_turns SET publication_status='public', "
                    "public_at=:public_at, updated_at=:updated_at "
                    "WHERE id=:turn_id AND debate_id=:debate_id"
                ),
                {
                    "turn_id": current_turn_id,
                    "debate_id": debate_id,
                    "public_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                },
            )
            playback = db.execute(
                text("SELECT control_version FROM playback_states WHERE debate_id=:debate_id"),
                {"debate_id": debate_id},
            ).scalar_one()
            expected_control_version = int(playback) + 1
            db.execute(
                text(
                    "UPDATE playback_states SET status='waiting_next', mode='live', "
                    "current_turn_id=:turn_id, cursor_ms=0, "
                    "control_version=:control_version, replay_scope=NULL, "
                    "replay_index=NULL, updated_at=:updated_at "
                    "WHERE debate_id=:debate_id"
                ),
                {
                    "turn_id": current_turn_id,
                    "control_version": expected_control_version,
                    "updated_at": datetime.now(UTC),
                    "debate_id": debate_id,
                },
            )

        repository_a = SqlPlaybackRepository(session_factory=database.session_factory)
        repository_b = SqlPlaybackRepository(session_factory=database.session_factory)
        service_a = PlaybackService(
            repository_a,
            audio_store=AudioStore(settings.resolved_data_root),
            event_hub=DebateEventHub(),
            task_manager=TaskManager(),
            session_factory=database.session_factory,
            settings=settings,
        )
        service_b = PlaybackService(
            repository_b,
            audio_store=AudioStore(settings.resolved_data_root),
            event_hub=DebateEventHub(),
            task_manager=TaskManager(),
            session_factory=database.session_factory,
            settings=settings,
        )
        claim_barrier = Barrier(2)

        def synchronized_claim(repository: SqlPlaybackRepository) -> Any:
            original = repository.claim_next_playback

            def claim(**kwargs: Any) -> bool:
                claim_barrier.wait(timeout=5)
                return original(**kwargs)

            return claim

        repository_a.claim_next_playback = synchronized_claim(repository_a)  # type: ignore[method-assign]
        repository_b.claim_next_playback = synchronized_claim(repository_b)  # type: ignore[method-assign]

        teacher_context = SimpleNamespace(
            user=SimpleNamespace(id="98644172-6bbb-5383-8198-3b78dcd5b9ab")
        )

        def invoke(service: PlaybackService) -> Any:
            db = database.session_factory()
            try:
                return asyncio.run(
                    service.next(
                        db,
                        debate_id,
                        expected_control_version=expected_control_version,
                        expected_current_turn_id=current_turn_id,
                        context=teacher_context,
                    )
                )
            except Exception as exc:  # assert the exact exception below
                return exc
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = tuple(pool.map(invoke, (service_a, service_b)))

        successes = [item for item in outcomes if not isinstance(item, Exception)]
        stale = [
            item
            for item in outcomes
            if isinstance(item, PlatformError) and item.code == "stale_control_version"
        ]
        unexpected = [
            item
            for item in outcomes
            if isinstance(item, Exception)
            and not (isinstance(item, PlatformError) and item.code == "stale_control_version")
        ]
        assert len(successes) == 1, outcomes
        assert len(stale) == 1, outcomes
        assert not unexpected, unexpected
        advanced = cast(Any, successes[0])
        assert advanced.status == "ready"
        assert str(advanced.current_turn_id) == successor_turn_id
        assert advanced.control_version == expected_control_version + 1

        with database.session() as db:
            status, current, control = db.execute(
                text(
                    "SELECT status,current_turn_id,control_version FROM playback_states "
                    "WHERE debate_id=:debate_id"
                ),
                {"debate_id": debate_id},
            ).one()
            assert (status, current, control) == (
                "ready",
                successor_turn_id,
                expected_control_version + 1,
            )


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
            settings.embedding_provider = "dashscope"
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


@pytest.mark.parametrize("topic", [TOPIC, ACCENTED_NFD_TOPIC], ids=["plain", "accented-nfd"])
def test_websocket_drives_four_public_turns_and_replay_without_regeneration(
    app_factory: Any,
    topic: str,
) -> None:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://testserver"
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence=(
                (
                    "TikTok recommendation algorithm transparency, privacy, user choice, "
                    "national security, safeguards, and accountable independent review."
                )
                if topic == TOPIC
                else (
                    "Māori and Café perspectives can shape platform policy through "
                    "transparent safeguards and accountable review."
                )
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
                "topic": topic,
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
                if turn_number == 0:
                    # A live turn is still unpublished until its first
                    # started acknowledgement.  A stale resume action must
                    # be rejected without issuing a ticket or changing the
                    # authoritative SQL playback state.
                    wrong_resume_id = str(uuid4())
                    socket.send_json(
                        {
                            "command_id": wrong_resume_id,
                            "command_type": "playback.media.prepare",
                            "command_version": 1,
                            "debate_id": debate_id,
                            "expected_control_version": control_version,
                            "controller_epoch": epoch,
                            "turn_id": turn_id,
                            "playback_action": "resume",
                        }
                    )
                    rejected = _receive_until(socket, "message_type", "command.rejected")
                    assert rejected["command_id"] == wrong_resume_id
                    assert rejected["code"] == "invalid_state"
                    assert rejected["current_control_version"] == control_version
                    unchanged = client.get(f"/api/v1/debates/{debate_id}")
                    assert unchanged.status_code == 200
                    assert unchanged.json()["playback"]["control_version"] == control_version
                    assert unchanged.json()["playback"]["status"] == "ready"
                prepare_id = str(uuid4())
                playback_action = "start" if turn_number == 0 else "next"
                socket.send_json(
                    {
                        "command_id": prepare_id,
                        "command_type": "playback.media.prepare",
                        "command_version": 1,
                        "debate_id": debate_id,
                        "expected_control_version": control_version,
                        "controller_epoch": epoch,
                        "turn_id": turn_id,
                        "playback_action": playback_action,
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
                        "playback_action": playback_action,
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
                if turn_number == 3:
                    completed = None
                    terminal_revoked = None
                    for _index in range(16):
                        message = socket.receive_json()
                        if message.get("event_type") == "playback.completed":
                            completed = message
                        elif message.get("message_type") == "controller.revoked":
                            terminal_revoked = message
                        if completed is not None and terminal_revoked is not None:
                            break
                    assert completed is not None
                    assert terminal_revoked is not None
                    assert terminal_revoked["controller_epoch"] == epoch
                    assert terminal_revoked["reason"] == "debate_terminal"
                else:
                    completed = _receive_until(socket, "event_type", "playback.completed")
                assert completed["payload"]["turn_id"] == turn_id
                control_version = completed["payload"]["control_version"]
                if turn_number < 3:
                    waiting = _receive_until(socket, "event_type", "playback.waiting_next")
                    assert waiting["payload"]["completed_turn_id"] == turn_id
                    assert waiting["payload"]["mode"] == "live"
                    control_version = waiting["payload"]["control_version"]
                    advanced = client.post(
                        f"/api/v1/debates/{debate_id}/next",
                        headers=_headers(csrf),
                        json={
                            "expected_control_version": control_version,
                            "expected_current_turn_id": turn_id,
                        },
                    )
                    assert advanced.status_code == 200, advanced.text
                    assert advanced.json()["status"] == "ready"
                    assert advanced.json()["current_turn_id"] != turn_id
                    control_version = advanced.json()["control_version"]
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
                assert all(row.generation_status == "final_ready" for row in rows)
                assert all(row.publication_status == "public" for row in rows)
                assert all(row.generation_status != "failed" for row in rows)
                assert topic in rows[2].speech
                structured = [json.loads(row.structured_json or "{}") for row in rows]
                assert structured[2]["rebuttal_target_turn_id"] in {rows[0].id, rows[1].id}
                assert structured[2]["question"]["type"] == "agent"
                assert structured[2]["question"]["target_participant_id"] == rows[3].participant_id
                assert structured[3]["question"]["type"] == "audience_reflection"
                assert structured[3]["question"]["target_participant_id"] is None

            assert llm.call_count == 4
            assert tts.synthesize_calls == 4
            replay_acquire_id = str(uuid4())
            socket.send_json(
                {
                    "command_id": replay_acquire_id,
                    "command_type": "playback.controller.acquire",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": control_version,
                }
            )
            replay_controller = _receive_until(socket, "message_type", "controller.acquired")
            assert replay_controller["command_id"] == replay_acquire_id
            assert replay_controller["controller_epoch"] != epoch
            epoch = replay_controller["controller_epoch"]
            control_version = replay_controller["control_version"]
            replay = client.post(
                f"/api/v1/debates/{debate_id}/replay",
                headers=_headers(csrf),
                json={"expected_control_version": control_version},
            )
            assert replay.status_code == 200, replay.text
            control_version = replay.json()["control_version"]
            for replay_index, replay_turn_id in enumerate(published_turn_ids):
                socket.send_json(
                    {
                        "command_id": str(uuid4()),
                        "command_type": "playback.media.prepare",
                        "command_version": 1,
                        "debate_id": debate_id,
                        "expected_control_version": control_version,
                        "controller_epoch": epoch,
                        "turn_id": replay_turn_id,
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
                        "turn_id": replay_turn_id,
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
                        "turn_id": replay_turn_id,
                    }
                )
                if replay_index == len(published_turn_ids) - 1:
                    completed_replay = _receive_until(socket, "event_type", "replay.completed")
                    control_version = completed_replay["payload"]["control_version"]
                else:
                    waiting_replay = _receive_until(socket, "event_type", "playback.waiting_next")
                    assert waiting_replay["payload"]["mode"] == "replay"
                    control_version = waiting_replay["payload"]["control_version"]
                    advanced_replay = client.post(
                        f"/api/v1/debates/{debate_id}/next",
                        headers=_headers(csrf),
                        json={
                            "expected_control_version": control_version,
                            "expected_current_turn_id": replay_turn_id,
                        },
                    )
                    assert advanced_replay.status_code == 200, advanced_replay.text
                    assert advanced_replay.json()["status"] == "ready"
                    control_version = advanced_replay.json()["control_version"]
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


def test_websocket_sessions_release_small_sqlite_pool_for_http_requests(
    app_factory: Any,
) -> None:
    """Multiple observation tabs must not pin the file-SQLite QueuePool."""

    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://testserver"
    pool = cast(Any, database.engine.pool)
    # Keep the regression deterministic and fast if the route accidentally
    # holds a connection for the lifetime of a socket.  The production
    # default remains unchanged; this only constrains this isolated database.
    pool._pool.maxsize = 2
    pool._max_overflow = 0
    pool._overflow = -2
    pool._timeout = 0.2

    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence="TikTok recommendation transparency and user choice.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="KaiKai",
            evidence="Quartz orchid mineral lattice basalt geometry.",
        )
        _session, csrf = login(client)
        body = {
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
        }
        create_headers = _headers(csrf, **{"Idempotency-Key": "wave2-pool-create-0001"})
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=create_headers,
            json=body,
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        started = client.post(
            f"/api/v1/debates/{debate_id}/start",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-pool-start-0001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        _wait_for_ready(client, debate_id)
        baseline_checked_out = pool.checkedout()

        with ExitStack() as sockets:
            opened: list[Any] = []
            for _index in range(5):
                socket = sockets.enter_context(
                    client.websocket_connect(
                        f"/api/v1/debates/{debate_id}/events",
                        headers={"origin": "http://testserver"},
                    )
                )
                opened.append(socket)
                snapshot = _receive_until(socket, "event_type", "snapshot")
                assert snapshot["payload"]["debate_status"] == "running"
                assert snapshot["payload"]["playback"]["status"] == "ready"

            # Each handshake and snapshot has completed and returned its
            # connection, even though all five WebSockets remain open.
            assert pool.checkedout() == baseline_checked_out

            command_id = str(uuid4())
            opened[0].send_json(
                {
                    "command_id": command_id,
                    "command_type": "playback.controller.acquire",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": 0,
                }
            )
            acquired = _receive_until(opened[0], "message_type", "controller.acquired")
            assert acquired["command_id"] == command_id
            assert pool.checkedout() == baseline_checked_out

            fetched = client.get(f"/api/v1/debates/{debate_id}")
            assert fetched.status_code == 200, fetched.text

            replay = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=create_headers,
                json=body,
            )
            assert replay.status_code == 201, replay.text
            assert replay.json() == created.json()
            assert pool.checkedout() == baseline_checked_out

        # Closing the sockets runs disconnect cleanup (if a tab had acquired
        # control) and still leaves the QueuePool at its pre-WebSocket level.
        assert pool.checkedout() == baseline_checked_out


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
    assert sum(event.event_type == "playback.resumed" for event in events) == 1
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
    assert str(advanced.current_turn_id) == first_turn_id
    assert advanced.status == "waiting_next"
    assert advanced.next_turn_ready is True
    waiting_state = service._state(None, debate)
    assert waiting_state.controller_epoch == epoch
    assert waiting_state.controller_session_hash == "session-hash"
    assert waiting_state.controller_connection_id == "teacher-tab"
    assert service._controller_sessions[debate.id] == "session-hash"
    assert service.take_revocation(epoch) is None
    next_state = await service.next(
        None,
        debate.id,
        expected_control_version=advanced.control_version,
        expected_current_turn_id=first_turn_id,
    )
    assert str(next_state.current_turn_id) == debate.turns[1].id
    assert next_state.status == "ready"
    assert next_state.next_turn_ready is False
    await tasks.close()


@pytest.mark.asyncio
async def test_manual_next_cas_preserves_waiting_boundary_and_ack_publishes_only_then(
    tmp_path: Path,
) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    first_turn = debate.turns[0]
    successor = debate.turns[1]
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="next-session",
        connection_id="next-tab",
    )
    epoch = str(controller.controller_epoch)
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="next-session",
        turn_id=first_turn.id,
        action="start",
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="next-session",
        turn_id=first_turn.id,
        action="start",
    )
    waiting = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=playing.control_version,
        epoch=epoch,
        session_hash="next-session",
        turn_id=first_turn.id,
    )
    assert waiting.status == "waiting_next"
    assert str(waiting.current_turn_id) == first_turn.id
    assert waiting.next_turn_ready is True
    assert successor.publication_status == "unpublished"
    waiting_events = [
        event
        for event in service.event_hub.store.events_after(debate.id, 0)
        if event.event_type == "playback.waiting_next"
    ]
    assert len(waiting_events) == 1
    assert set(waiting_events[0].payload) == {
        "mode",
        "completed_turn_id",
        "control_version",
        "next_turn_ready",
    }
    assert waiting_events[0].payload["mode"] == "live"
    assert successor.id not in str(waiting_events[0].payload)

    with pytest.raises(PlatformError) as hidden_media:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=waiting.control_version,
            epoch=epoch,
            session_hash="next-session",
            turn_id=successor.id,
            action="next",
        )
    assert hidden_media.value.code == "not_found"

    outcomes = await asyncio.gather(
        *(
            service.next(
                None,
                debate.id,
                expected_control_version=waiting.control_version,
                expected_current_turn_id=first_turn.id,
            )
            for _index in range(2)
        ),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if not isinstance(item, Exception)]
    failures = [item for item in outcomes if isinstance(item, PlatformError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code == "stale_control_version"
    advanced = cast(Any, successes[0])
    assert advanced.status == "ready"
    assert str(advanced.current_turn_id) == successor.id
    assert advanced.control_version == waiting.control_version + 1
    assert advanced.next_turn_ready is False
    assert successor.publication_status == "unpublished"

    prepared, _private = await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=advanced.control_version,
        epoch=epoch,
        session_hash="next-session",
        turn_id=successor.id,
        action="next",
    )
    assert prepared.binding.action == "next"
    assert successor.publication_status == "unpublished"
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=advanced.control_version,
        epoch=epoch,
        session_hash="next-session",
        turn_id=successor.id,
        action="next",
    )
    assert successor.publication_status == "public"
    await tasks.close()


@pytest.mark.asyncio
async def test_slow_successor_emits_false_then_true_readiness_change_without_leak(
    tmp_path: Path,
) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()))
    release = asyncio.Event()
    successor_started = asyncio.Event()

    async def preparer(_db: Any, _debate: Any, turn: Any, **_kwargs: Any) -> Any:
        if int(turn.turn_index) == 1:
            successor_started.set()
            await release.wait()
        return {"speech": _valid_speech()}

    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=AudioStore(tmp_path),
        task_manager=tasks,
        turn_preparer=preparer,
    )
    await service.start(
        None,
        debate.id,
        expected_revision=0,
        expected_current_audio_debate_id=None,
        confirm_previous_audio_cleanup=False,
    )
    await asyncio.wait_for(successor_started.wait(), timeout=1)
    first_turn = debate.turns[0]
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="slow-session",
        connection_id="slow-tab",
    )
    epoch = str(controller.controller_epoch)
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="slow-session",
        turn_id=first_turn.id,
        action="start",
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="slow-session",
        turn_id=first_turn.id,
        action="start",
    )
    waiting = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=playing.control_version,
        epoch=epoch,
        session_hash="slow-session",
        turn_id=first_turn.id,
    )
    assert waiting.status == "waiting_next"
    assert waiting.next_turn_ready is False
    events = [
        event
        for event in service.event_hub.store.events_after(debate.id, 0)
        if event.event_type == "playback.waiting_next"
    ]
    assert [event.payload["next_turn_ready"] for event in events] == [False]
    assert events[0].payload["completed_turn_id"] == first_turn.id

    release.set()
    await tasks.wait_debate(debate.id)
    events = [
        event
        for event in service.event_hub.store.events_after(debate.id, 0)
        if event.event_type == "playback.waiting_next"
    ]
    assert [event.payload["next_turn_ready"] for event in events] == [False, True]
    assert all(
        event.payload["completed_turn_id"] == first_turn.id
        and event.payload["control_version"] == waiting.control_version
        and event.payload["mode"] == "live"
        and set(event.payload)
        == {"mode", "completed_turn_id", "control_version", "next_turn_ready"}
        for event in events
    )
    assert service._state(None, debate).status == "waiting_next"
    assert service._state_dto(service._state(None, debate), None, debate).next_turn_ready is True
    await tasks.close()


@pytest.mark.asyncio
async def test_next_rejects_not_ready_and_never_changes_state(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    await tasks.close()
    first_turn = debate.turns[0]
    successor = debate.turns[1]
    successor.generation_status = "pending"
    successor.audio_relative_path = None
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="not-ready-session",
        connection_id="not-ready-tab",
    )
    epoch = str(controller.controller_epoch)
    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="not-ready-session",
        turn_id=first_turn.id,
        action="start",
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="not-ready-session",
        turn_id=first_turn.id,
        action="start",
    )
    waiting = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=playing.control_version,
        epoch=epoch,
        session_hash="not-ready-session",
        turn_id=first_turn.id,
    )
    before = (waiting.status, str(waiting.current_turn_id), waiting.control_version)
    events_before = list(service.event_hub.store.events_after(debate.id, 0))
    with pytest.raises(PlatformError) as rejected:
        await service.next(
            None,
            debate.id,
            expected_control_version=waiting.control_version,
            expected_current_turn_id=first_turn.id,
        )
    assert rejected.value.code == "next_not_ready"
    after = service._state(None, debate)
    assert (after.status, str(after.current_turn_id), after.control_version) == before
    assert list(service.event_hub.store.events_after(debate.id, 0)) == events_before
    await tasks.close()


@pytest.mark.asyncio
async def test_final_live_end_is_completed_and_not_waiting_next(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    await tasks.close()
    debate.turns = debate.turns[:1]
    first_turn = debate.turns[0]
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="final-session",
        connection_id="final-tab",
    )
    epoch = str(controller.controller_epoch)
    media_command_id = str(uuid4())
    prepared, _private = await service.media_prepare(
        None,
        debate.id,
        command_id=media_command_id,
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="final-session",
        turn_id=first_turn.id,
        action="start",
    )
    assert (debate.id, media_command_id) in service._media_command_results
    debate_scoped_token, _binding = service.ticket_store.issue(
        session_hash="final-session",
        controller_epoch=epoch,
        debate_id=debate.id,
        turn_id=str(uuid4()),
        action="start",
        control_version=controller.control_version,
    )
    playing = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="final-session",
        turn_id=first_turn.id,
        action="start",
    )
    completed = await service.ended_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=playing.control_version,
        epoch=epoch,
        session_hash="final-session",
        turn_id=first_turn.id,
    )
    assert completed.status == "completed"
    assert completed.next_turn_ready is False
    assert str(completed.current_turn_id) == first_turn.id
    assert debate.status == "debate_finished"
    state = service._state(None, debate)
    assert state.controller_epoch is None
    assert state.controller_session_hash is None
    assert state.controller_connection_id is None
    assert state.pending_action is None
    assert state.pending_ticket_hash is None
    assert state.pending_media_command_id is None
    assert state.audio_duration_ms == 0
    assert debate.id not in service._controller_sessions
    assert not any(key[0] == debate.id for key in service._media_command_results)
    assert service.ticket_store.get(prepared.token) is None
    assert service.ticket_store.get(debate_scoped_token) is None
    revoked = service.take_revocation(epoch)
    assert revoked is not None
    assert revoked["reason"] == "debate_terminal"
    assert not any(
        event.event_type == "playback.waiting_next"
        for event in service.event_hub.store.events_after(debate.id, 0)
    )

    with pytest.raises(PlatformError) as stale_before_reacquire:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=completed.control_version,
            epoch=epoch,
            session_hash="final-session",
            turn_id=first_turn.id,
            action="start",
        )
    assert stale_before_reacquire.value.code == "stale_control_version"

    fresh = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=completed.control_version,
        session_hash="replay-session",
        connection_id="replay-tab",
    )
    assert str(fresh.controller_epoch) != epoch
    assert state.controller_epoch == str(fresh.controller_epoch)
    assert state.controller_session_hash == "replay-session"
    assert state.controller_connection_id == "replay-tab"

    with pytest.raises(PlatformError) as stale_after_reacquire:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=fresh.control_version,
            epoch=epoch,
            session_hash="final-session",
            turn_id=first_turn.id,
            action="start",
        )
    assert stale_after_reacquire.value.code == "stale_control_version"
    await tasks.close()


@pytest.mark.asyncio
async def test_next_fence_readiness_rejects_malformed_persisted_prefix(tmp_path: Path) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    await tasks.close()
    first_turn, successor = debate.turns[:2]
    successor.predecessor_turn_ids_json = json.dumps([str(uuid4())])
    successor.transcript_hash = "committed-fence"
    successor.cutoff_turn_index = 0
    state = service._state(None, debate)
    state.status = "waiting_next"
    state.mode = "live"
    state.current_turn_id = first_turn.id
    assert service._state_dto(state, None, debate).next_turn_ready is False
    await tasks.close()


@pytest.mark.asyncio
async def test_skip_next_turn_uses_start_and_unpublished_predecessor_cannot_publish(
    tmp_path: Path,
) -> None:
    service, debate, tasks = await _memory_ready_service(tmp_path)
    first_turn = debate.turns[0]
    next_turn = debate.turns[1]
    controller = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=0,
        session_hash="skip-session",
        connection_id="skip-tab",
    )
    epoch = str(controller.controller_epoch)

    before = service._state(None, debate)
    with pytest.raises(PlatformError) as wrong_resume:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=controller.control_version,
            epoch=epoch,
            session_hash="skip-session",
            turn_id=first_turn.id,
            action="resume",
        )
    assert wrong_resume.value.code == "invalid_state"
    assert (before.status, before.current_turn_id, before.control_version) == (
        "ready",
        first_turn.id,
        controller.control_version,
    )
    assert before.pending_action is None
    assert (
        service.ticket_store.find(
            session_hash="skip-session",
            controller_epoch=epoch,
            debate_id=debate.id,
            turn_id=first_turn.id,
            action="resume",
        )
        is None
    )

    await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="skip-session",
        turn_id=first_turn.id,
        action="start",
    )
    started = await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=controller.control_version,
        epoch=epoch,
        session_hash="skip-session",
        turn_id=first_turn.id,
        action="start",
    )
    skipped = await service.skip(
        None,
        debate.id,
        expected_control_version=started.control_version,
    )
    assert str(skipped.current_turn_id) == first_turn.id
    assert skipped.status == "waiting_next"
    assert skipped.next_turn_ready is True
    assert first_turn.publication_status == "public"
    assert next_turn.publication_status == "unpublished"

    with pytest.raises(PlatformError) as waiting_media:
        await service.media_prepare(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=skipped.control_version,
            epoch=epoch,
            session_hash="skip-session",
            turn_id=first_turn.id,
            action="resume",
        )
    assert waiting_media.value.code == "not_found"
    advanced = await service.next(
        None,
        debate.id,
        expected_control_version=skipped.control_version,
        expected_current_turn_id=first_turn.id,
    )
    assert str(advanced.current_turn_id) == next_turn.id
    assert advanced.status == "ready"
    prepared_next, _private = await service.media_prepare(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=advanced.control_version,
        epoch=epoch,
        session_hash="skip-session",
        turn_id=next_turn.id,
        action="next",
    )
    await service.started_ack(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=advanced.control_version,
        epoch=epoch,
        session_hash="skip-session",
        turn_id=next_turn.id,
        action="next",
    )
    assert prepared_next.binding.action == "next"
    assert next_turn.publication_status == "public"

    # A successor that is made current while an earlier turn is unpublished
    # must still fail closed at both media preparation and started ack.
    next_turn.publication_status = "unpublished"
    first_turn.publication_status = "unpublished"
    state = service._state(None, debate)
    state.status = "ready"
    state.mode = "live"
    state.current_turn_id = next_turn.id
    state.pending_action = "start"
    state.control_version += 1
    with pytest.raises(PlatformError) as missing_prefix:
        await service.started_ack(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=state.control_version,
            epoch=epoch,
            session_hash="skip-session",
            turn_id=next_turn.id,
            action="start",
        )
    assert missing_prefix.value.code == "invalid_state"
    assert state.status == "ready"
    assert state.current_turn_id == next_turn.id
    assert state.control_version > skipped.control_version
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
    replay_state = repository.playback_state(None, debate)
    replay_state.status = "completed"
    replay_state.mode = "live"
    replay_state.current_turn_id = None
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
@pytest.mark.parametrize("status", ["failed", "stopped"])
async def test_terminal_controller_acquire_does_not_mutate_playback(
    tmp_path: Path,
    status: str,
) -> None:
    repository = MemoryPlaybackRepository()
    debate = _memory_debate(repository, course_id=str(uuid4()), status=status)
    state = repository.playback_state(None, debate)
    state.status = "stopped"
    state.mode = "live"
    state.current_turn_id = str(uuid4())
    state.control_version = 7
    state.controller_epoch = None
    state.controller_session_hash = None
    state.controller_connection_id = None
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=AudioStore(tmp_path), task_manager=tasks)
    events_before = list(service.event_hub.store.events_after(debate.id, 0))

    with pytest.raises(PlatformError) as rejected:
        await service.controller_acquire(
            None,
            debate.id,
            command_id=str(uuid4()),
            expected_control_version=7,
            session_hash="terminal-session",
            connection_id="terminal-tab",
        )

    assert rejected.value.code == "invalid_state"
    assert state.status == "stopped"
    assert state.mode == "live"
    assert state.control_version == 7
    assert state.controller_epoch is None
    assert state.controller_session_hash is None
    assert state.controller_connection_id is None
    assert debate.id not in service._controller_sessions
    assert list(service.event_hub.store.events_after(debate.id, 0)) == events_before
    await tasks.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["debate_finished", "completed"])
async def test_finished_live_controller_acquire_then_explicit_replay(
    tmp_path: Path,
    status: str,
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
    state = repository.playback_state(None, debate)
    state.status = "completed"
    state.mode = "live"
    state.current_turn_id = turn.id
    state.control_version = 4
    state.replay_scope = None
    state.replay_turn_ids = []
    state.replay_index = 0
    tasks = TaskManager()
    service = PlaybackService(repository, audio_store=None, task_manager=tasks)
    events_before = list(service.event_hub.store.events_after(debate.id, 0))

    acquired = await service.controller_acquire(
        None,
        debate.id,
        command_id=str(uuid4()),
        expected_control_version=4,
        session_hash="finished-session",
        connection_id="finished-tab",
    )

    assert acquired.control_version == 5
    assert state.status == "completed"
    assert state.mode == "live"
    assert state.current_turn_id == turn.id
    assert state.replay_scope is None
    assert state.replay_turn_ids == []
    assert state.replay_index == 0
    assert state.controller_epoch == str(acquired.controller_epoch)
    assert state.controller_session_hash == "finished-session"
    assert state.controller_connection_id == "finished-tab"
    assert debate.status == status
    assert list(service.event_hub.store.events_after(debate.id, 0)) == events_before

    replay = await service.replay_all(
        None,
        debate.id,
        expected_control_version=acquired.control_version,
    )
    assert replay.status == "ready"
    assert replay.mode == "replay"
    assert str(replay.current_turn_id) == turn.id
    await tasks.close()


@pytest.mark.parametrize("status", ["failed", "stopped"])
def test_websocket_terminal_controller_acquire_is_private_stable_rejection(
    app_factory: Any,
    status: str,
) -> None:
    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://testserver"
    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence="TikTok recommendation transparency and user choice.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="KaiKai",
            evidence="Quartz orchid mineral lattice basalt geometry.",
        )
        _session, csrf = login(client)
        body = {
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
        }
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": f"wave2-{status}-create-0001"}),
            json=body,
        )
        assert created.status_code == 201, created.text
        debate_id = created.json()["id"]
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert debate is not None and playback is not None
            debate.status = status
            playback.status = "stopped"
            playback.mode = "live"
            playback.control_version = 7
            playback.controller_epoch = None
            playback.controller_owner_connection = None

        event_sequence_before = app.state.playback_service.event_hub.store.last_sequence(debate_id)
        with client.websocket_connect(
            f"/api/v1/debates/{debate_id}/events",
            headers={"origin": "http://testserver"},
        ) as socket:
            snapshot = _receive_until(socket, "event_type", "snapshot")
            assert snapshot["payload"]["debate_status"] == status
            assert snapshot["payload"]["playback"]["status"] == "stopped"
            assert snapshot["payload"]["playback"]["control_version"] == 7
            command_id = str(uuid4())
            socket.send_json(
                {
                    "command_id": command_id,
                    "command_type": "playback.controller.acquire",
                    "command_version": 1,
                    "debate_id": debate_id,
                    "expected_control_version": 7,
                }
            )
            rejected = _receive_until(socket, "message_type", "command.rejected")
            assert rejected["command_id"] == command_id
            assert rejected["code"] == "invalid_state"
            assert rejected["current_control_version"] == 7
            assert "controller_epoch" not in rejected

        with database.session() as db:
            playback = db.scalar(
                select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
            )
            assert playback is not None
            assert playback.status == "stopped"
            assert playback.mode == "live"
            assert playback.control_version == 7
            assert playback.controller_epoch is None
            assert playback.controller_owner_connection is None
        assert app.state.playback_service.event_hub.store.last_sequence(debate_id) == (
            event_sequence_before
        )


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
    assert retained_state.status == "paused"
    assert retained_state.current_turn_id == retained_turn.id
    assert retained_state.cursor_ms == 321
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
            "next_turn_ready": False,
        },
        "interaction": {
            "status": "closed",
            "votes": [],
            "barrage_count": 0,
            "total_votes": 0,
        },
        "report": {
            "generation_status": "not_started",
            "latest_attempt_status": "not_started",
            "insight": {
                "status": "not_started",
                "included_count": 0,
                "filtered_count": 0,
                "snapshot_id": None,
                "revision": None,
            },
            "active_revision_id": None,
            "current_success_revision_id": None,
            "current_success_word_count": None,
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


def _assert_websocket_handshake_close(
    client: TestClient,
    *,
    origin: str,
    expected_code: int,
) -> None:
    upgraded = False
    with pytest.raises(WebSocketDisconnect) as raised:
        with client.websocket_connect(
            f"/api/v1/debates/{uuid4()}/events",
            headers={"origin": origin},
        ) as socket:
            upgraded = True
            # The route accepts the ASGI upgrade before it sends a private
            # close code, otherwise Uvicorn/Caddy collapse every reason into
            # an HTTP 403.  Read once so TestClient observes that close frame.
            socket.receive_json()
    assert upgraded, "the application must upgrade before sending a private close code"
    assert raised.value.code == expected_code
    assert raised.value.reason == ""


def test_websocket_origin_mismatch_closes_4403_without_configuration_leak(
    app_factory: Any,
) -> None:
    app, _database, settings = app_factory()
    configured_origin = "http://classroom.example:8080"
    settings.classroom_public_base_url = configured_origin

    with TestClient(app) as client:
        _assert_websocket_handshake_close(
            client,
            origin="http://other.example:8080",
            expected_code=4403,
        )


@pytest.mark.parametrize("raw_token", [None, "forged-session-token"], ids=["missing", "invalid"])
def test_websocket_missing_or_invalid_session_closes_4401(
    app_factory: Any,
    raw_token: str | None,
) -> None:
    app, _database, settings = app_factory()
    configured_origin = "http://classroom.example:8080"
    settings.classroom_public_base_url = configured_origin

    with TestClient(app) as client:
        if raw_token is not None:
            client.cookies.set("maya_session", raw_token)
        _assert_websocket_handshake_close(
            client,
            origin=configured_origin,
            expected_code=4401,
        )


@pytest.mark.parametrize("missing_state", ["settings", "database"])
def test_websocket_internal_handshake_unavailable_closes_1011(
    app_factory: Any,
    missing_state: str,
) -> None:
    app, _database, _settings = app_factory()

    with TestClient(app) as client:
        setattr(app.state, missing_state, None)
        _assert_websocket_handshake_close(
            client,
            origin="http://testserver",
            expected_code=1011,
        )


def test_websocket_exact_configured_origin_delivers_authorized_snapshot(
    app_factory: Any,
) -> None:
    app, database, settings = app_factory()
    configured_origin = "http://testserver"
    settings.classroom_public_base_url = configured_origin

    with TestClient(app) as client:
        bowen_id = _insert_published_agent(
            database,
            group_id=GROUP_BOWEN_ID,
            name="Bowen",
            evidence="TikTok recommendation transparency and user choice.",
        )
        kaikai_id = _insert_published_agent(
            database,
            group_id=GROUP_KAIKAI_ID,
            name="KaiKai",
            evidence="Quartz orchid mineral lattice basalt geometry.",
        )
        _session, csrf = login(client)
        created = client.post(
            f"/api/v1/courses/{COURSE_ID}/debates",
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-ws-origin-create-0001"}),
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
            headers=_headers(csrf, **{"Idempotency-Key": "wave2-ws-origin-start-0001"}),
            json={
                "expected_revision": 0,
                "expected_current_audio_debate_id": None,
                "confirm_previous_audio_cleanup": False,
            },
        )
        assert started.status_code == 200, started.text
        _wait_for_ready(client, debate_id)

        with client.websocket_connect(
            f"/api/v1/debates/{debate_id}/events",
            headers={"origin": configured_origin},
        ) as socket:
            snapshot = _receive_until(socket, "event_type", "snapshot")
            assert snapshot["payload"]["debate_status"] == "running"


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


def test_audio_response_uses_the_validated_bytes_snapshot_on_same_size_replace(
    tmp_path: Path,
) -> None:
    """A replacement between validation and the old read cannot leak bytes."""

    course_id, debate_id, turn_id = (str(uuid4()) for _ in range(3))
    store = AudioStore(tmp_path, tts_provider=MockTTSProvider())
    raw = _wav_bytes()
    metadata = store.store_bytes(
        course_id=course_id,
        debate_id=debate_id,
        turn_id=turn_id,
        raw=raw,
    )
    path = store.path_for(metadata.relative_path)
    replacement = raw[:44] + bytes([raw[44] ^ 1]) + raw[45:]
    original_snapshot = store._validated_file_snapshot

    def validate_then_replace(**kwargs: Any) -> Any:
        validated = original_snapshot(**kwargs)
        path.write_bytes(replacement)
        return validated

    store._validated_file_snapshot = validate_then_replace  # type: ignore[method-assign]
    response = store.response(debate_id, turn_id)
    assert response.status_code == 200
    assert response.body == raw
    assert response.body != replacement
    assert response.etag == f'"{metadata.sha256}"'


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
    replay_state = repository.playback_state(None, debate)
    replay_state.status = "completed"
    replay_state.mode = "live"
    replay_state.current_turn_id = None
    tts = MockTTSProvider()
    store = AudioStore(tmp_path, tts_provider=tts)
    for _turn_index, turn in enumerate(turns):
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
    for turn_index, turn in enumerate(turns):
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
        if turn_index < len(turns) - 1:
            assert completed.status == "waiting_next"
            advanced = await service.next(
                None,
                debate.id,
                expected_control_version=completed.control_version,
                expected_current_turn_id=turn.id,
            )
            assert advanced.status == "ready"
            control_version = advanced.control_version
    assert service._state(None, debate).status == "completed"
    assert provider_calls == 0
    assert tts.synthesize_calls == 0
    await tasks.close()


@pytest.mark.asyncio
async def test_sql_replay_rehydrates_empty_audio_cache_from_stored_file(
    app_factory: Any,
) -> None:
    """A fresh service must validate and rehydrate persisted current audio."""

    _app, database, settings = app_factory()
    with TestClient(_app):
        pass
    agent_id = _insert_published_agent(
        database,
        group_id=GROUP_BOWEN_ID,
        name="Retained Bowen",
        evidence="TikTok transparency, privacy, safeguards, and accountable review.",
    )
    debate_id, turn_id, _file_id, _relative_path = _insert_sql_retained_debate(
        database, agent_id=agent_id
    )
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    tts = MockTTSProvider()
    store = AudioStore(settings.resolved_data_root, tts_provider=tts)
    # The constructor may scan the tree, but this test proves the DB facts are
    # sufficient even when a restarted process begins with an empty cache.
    store._metadata.clear()
    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=store,
        task_manager=tasks,
        tts_provider=tts,
        session_factory=database.session_factory,
        settings=settings,
    )

    with database.session() as db:
        replay = await service.replay_all(db, debate_id, expected_control_version=7)

    assert replay.mode == "replay"
    assert replay.status == "ready"
    assert str(replay.current_turn_id) == turn_id
    assert service.audio_store.metadata(debate_id, turn_id) is not None
    assert tts.synthesize_calls == 0
    await tasks.close()


@pytest.mark.asyncio
async def test_sql_replay_pointer_change_rejects_all_and_turn_without_mutation(
    app_factory: Any,
) -> None:
    _app, database, settings = app_factory()
    with TestClient(_app):
        pass
    agent_id = _insert_published_agent(
        database,
        group_id=GROUP_BOWEN_ID,
        name="Pointer Bowen",
        evidence="TikTok transparency, privacy, safeguards, and accountable review.",
    )
    debate_id, turn_id, _file_id, _relative_path = _insert_sql_retained_debate(
        database, agent_id=agent_id
    )
    replacement_id, _replacement_turn_id, _replacement_file_id, _replacement_path = (
        _insert_sql_retained_debate(database, agent_id=agent_id)
    )

    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    store = AudioStore(settings.resolved_data_root)
    store._metadata.clear()
    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=store,
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    for replay_call in (
        lambda db: service.replay_all(db, debate_id, expected_control_version=7),
        lambda db: service.replay_turn(db, debate_id, turn_id, expected_control_version=7),
    ):
        with database.session() as db:
            with pytest.raises(PlatformError) as rejected:
                await replay_call(db)
        assert rejected.value.code == "audio_not_retained"

    with database.session() as db:
        state = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert state is not None
        assert state.control_version == 7
        assert state.status == "completed"
        assert state.mode == "live"
        assert state.current_turn_id is None
    await tasks.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tamper",
    ["missing", "bad_wav", "symlink", "path", "hash", "size", "state", "kind"],
)
async def test_sql_replay_rejects_invalid_persisted_audio_facts(
    app_factory: Any,
    tamper: str,
) -> None:
    _app, database, settings = app_factory()
    with TestClient(_app):
        pass
    agent_id = _insert_published_agent(
        database,
        group_id=GROUP_BOWEN_ID,
        name="Integrity Bowen",
        evidence="TikTok transparency, privacy, safeguards, and accountable review.",
    )
    debate_id, _turn_id, file_id, relative_path = _insert_sql_retained_debate(
        database, agent_id=agent_id
    )
    path = settings.resolved_data_root / relative_path
    if tamper == "missing":
        path.unlink()
    elif tamper == "bad_wav":
        bad = b"x" * path.stat().st_size
        path.write_bytes(bad)
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.sha256 = hashlib.sha256(bad).hexdigest()
            stored.size_bytes = len(bad)
    elif tamper == "symlink":
        target = path.with_name("other.wav")
        target.write_bytes(_wav_bytes())
        path.unlink()
        path.symlink_to(target.name)
    elif tamper == "path":
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.relative_path = f"courses/{COURSE_ID}/wrong/{file_id}.wav"
    elif tamper == "hash":
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.sha256 = "0" * 64
    elif tamper == "size":
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.size_bytes += 1
    elif tamper == "state":
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.state = "deleted"
    else:
        with database.session() as db:
            stored = db.get(StoredFile, file_id)
            assert stored is not None
            stored.kind = "markdown"

    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    store = AudioStore(settings.resolved_data_root)
    store._metadata.clear()
    tasks = TaskManager()
    service = PlaybackService(
        repository,
        audio_store=store,
        task_manager=tasks,
        session_factory=database.session_factory,
        settings=settings,
    )
    with database.session() as db:
        with pytest.raises(PlatformError) as rejected:
            await service.replay_all(db, debate_id, expected_control_version=7)
    assert rejected.value.code == "audio_not_retained"
    with database.session() as db:
        state = db.scalar(
            select(DebatePlaybackState).where(DebatePlaybackState.debate_id == debate_id)
        )
        assert state is not None and state.control_version == 7 and state.status == "completed"
    await tasks.close()


def _insert_sql_draft_debate(database: Database, *, debate_id: str) -> None:
    now = datetime.now(UTC)
    with database.session() as db:
        db.add(
            Debate(
                id=debate_id,
                course_id=COURSE_ID,
                topic=TOPIC,
                rule_set_id="ordered_multi_agent_rounds_demo_v1",
                rule_snapshot_json='{"round_count":2}',
                status="draft",
                revision=0,
                last_sequence=0,
                cancellation_generation=0,
                created_by="98644172-6bbb-5383-8198-3b78dcd5b9ab",
                created_at=now,
                updated_at=now,
            )
        )


def _prepare_committed_sql_audio_swap(
    database: Database,
    settings: Any,
    *,
    old_debate_id: str,
    new_debate_id: str,
    old_relative_path: str,
    request_id: str,
) -> tuple[str, Path]:
    store = AudioStore(settings.resolved_data_root)
    staging = f"staging/audio-swap/{COURSE_ID}/{request_id}/{old_debate_id}"
    source = f"courses/{COURSE_ID}/current-debate-audio/{old_debate_id}"
    with database.session() as db:
        journal = prepare_audio_swap_journal(
            db,
            AudioSwapRequest(
                course_id=COURSE_ID,
                request_id=request_id,
                old_debate_id=old_debate_id,
                source_relative_path=source,
                staging_relative_path=staging,
                new_debate_id=new_debate_id,
                expected_old_debate_id=old_debate_id,
            ),
        )
    assert store.stage_debate_directory(
        course_id=COURSE_ID,
        debate_id=old_debate_id,
        staging_relative_path=staging,
    )
    with database.session() as db:
        transition_audio_swap(
            db,
            str(journal.id),
            expected_state=AudioSwapState.PREPARED,
            target_state=AudioSwapState.STAGED,
        )
        transition_audio_swap(
            db,
            str(journal.id),
            expected_state=AudioSwapState.STAGED,
            target_state=AudioSwapState.COMMITTED,
        )
        db.execute(
            text("UPDATE courses SET current_audio_debate_id=:new WHERE id=:course_id"),
            {"new": new_debate_id, "course_id": COURSE_ID},
        )
    return staging, settings.resolved_data_root / old_relative_path


@pytest.mark.asyncio
async def test_sql_audio_swap_cleanup_marks_old_files_deleted_and_keeps_turn_audit(
    app_factory: Any,
) -> None:
    _app, database, settings = app_factory()
    with TestClient(_app):
        pass
    agent_id = _insert_published_agent(
        database,
        group_id=GROUP_BOWEN_ID,
        name="Cleanup Bowen",
        evidence="TikTok transparency, privacy, safeguards, and accountable review.",
    )
    old_id, _turn_id, file_id, relative_path = _insert_sql_retained_debate(
        database, agent_id=agent_id
    )
    new_id = str(uuid4())
    _insert_sql_draft_debate(database, debate_id=new_id)
    request_id = str(uuid4())
    _staging, old_path = _prepare_committed_sql_audio_swap(
        database,
        settings,
        old_debate_id=old_id,
        new_debate_id=new_id,
        old_relative_path=relative_path,
        request_id=request_id,
    )
    repository = SqlPlaybackRepository(session_factory=database.session_factory)
    service = PlaybackService(
        repository,
        audio_store=AudioStore(settings.resolved_data_root),
        task_manager=TaskManager(),
        session_factory=database.session_factory,
        settings=settings,
    )
    with database.session() as db:
        journal = db.scalar(
            select(FileOperation).where(
                FileOperation.operation_kind == "debate_audio_swap",
                FileOperation.new_debate_id == new_id,
            )
        )
        assert journal is not None
        swap = (journal, str(journal.staging_relative_path))
        service._commit_audio_swap(
            db,
            swap,
            course_id=COURSE_ID,
            old_debate_id=old_id,
        )
    assert not old_path.exists()
    with database.session() as db:
        stored = db.get(StoredFile, file_id)
        turn = db.scalar(select(DebateTurn).where(DebateTurn.debate_id == old_id))
        journal = db.scalar(
            select(FileOperation).where(
                FileOperation.operation_kind == "debate_audio_swap",
                FileOperation.new_debate_id == new_id,
            )
        )
        assert stored is not None and stored.state == "deleted"
        assert turn is not None and turn.audio_file_id == file_id and turn.speech == _valid_speech()
        assert journal is not None and journal.state == "recovered"
    await service.task_manager.close()


@pytest.mark.asyncio
async def test_sql_audio_swap_recovery_marks_old_files_deleted(
    app_factory: Any,
) -> None:
    _app, database, settings = app_factory()
    with TestClient(_app):
        pass
    agent_id = _insert_published_agent(
        database,
        group_id=GROUP_BOWEN_ID,
        name="Recovery Bowen",
        evidence="TikTok transparency, privacy, safeguards, and accountable review.",
    )
    old_id, _turn_id, file_id, relative_path = _insert_sql_retained_debate(
        database, agent_id=agent_id
    )
    new_id = str(uuid4())
    _insert_sql_draft_debate(database, debate_id=new_id)
    request_id = str(uuid4())
    staging, old_path = _prepare_committed_sql_audio_swap(
        database,
        settings,
        old_debate_id=old_id,
        new_debate_id=new_id,
        old_relative_path=relative_path,
        request_id=request_id,
    )
    assert not old_path.exists()
    service = PlaybackService(
        SqlPlaybackRepository(session_factory=database.session_factory),
        audio_store=AudioStore(settings.resolved_data_root),
        task_manager=TaskManager(),
        session_factory=database.session_factory,
        settings=settings,
    )
    with database.session() as db:
        await service.recover_startup(db)
    assert not (settings.resolved_data_root / staging).exists()
    with database.session() as db:
        stored = db.get(StoredFile, file_id)
        journal = db.scalar(
            select(FileOperation).where(
                FileOperation.operation_kind == "debate_audio_swap",
                FileOperation.new_debate_id == new_id,
            )
        )
        assert stored is not None and stored.state == "deleted"
        assert journal is not None and journal.state == "recovered"
    await service.task_manager.close()


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
