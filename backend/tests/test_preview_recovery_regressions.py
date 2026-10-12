"""Exercise publication and visible Preview failures through the SQL product path."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.errors import PlatformError
from app.core.models import KnowledgeChunk, SnapshotDocument
from app.modules.debates.models import Debate, DebateParticipant, DebateTurn
from app.modules.debates.playback._preparation import _raise_site
from app.modules.debates.playback.generation_adapter import (
    SqlSnapshotRetriever,
    SqlTurnPreparer,
    generation_fence,
)
from app.modules.debates.playback.protocols import PreparedTurn
from app.modules.debates.playback.service import PlaybackService
from app.modules.debates.playback.task_manager import TaskManager
from app.modules.debates.setup.segment_projection import segment_projection
from app.modules.debates.topic_language import model_topic, validate_topic
from app.providers.llm import LLMUsageV1, MockLLMProvider
from app.providers.llm_segments import SegmentAcceptedCandidateV2, SegmentLLMAdapter
from app.providers.tts import MockTTSProvider
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from tests.conftest import login
from tests.test_wave2_playback import COURSE_ID, GROUP_DEMO_ID, _headers, _insert_published_agent
from tests.test_wave4_llm_p1_product import (
    _FakeDashScopeAdapter,
    _install_fake_dashscope_product_path,
    _patch_local_confirmation,
    _product_preparer,
    _product_service,
    _seed_running_product_debate,
)


@pytest.mark.asyncio
async def test_cancelled_preparation_waits_for_thread_to_release_session(monkeypatch):
    started, release, finished = Event(), Event(), Event()

    def prepare(*_args, **_kwargs):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return PreparedTurn(speech="A saved result.")

    service = PlaybackService(turn_preparer=prepare)
    monkeypatch.setattr(service, "_participants", lambda *_args: [])
    task = asyncio.create_task(
        service._call_preparer(
            object(),
            SimpleNamespace(cancellation_generation=0),
            SimpleNamespace(participant_id="p"),
            1,
        )
    )
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()
    finally:
        release.set()
        if not task.done():
            await asyncio.gather(task, return_exceptions=True)


def test_claim_cleanup_logs_only_server_pointer_and_error_type(caplog):
    def fail_cleanup(*_args, **_kwargs):
        raise ValueError("private provider reply and SQL parameter")

    db = SimpleNamespace(rollback=lambda: None)
    service = PlaybackService(repository=SimpleNamespace(reset_prewarm_turn=fail_cleanup))
    service._release_claim(
        db,
        SimpleNamespace(id="debate-server-id"),
        SimpleNamespace(id="turn-server-id"),
        "owner-token",
        cancellation_generation=0,
    )
    assert "turn_id=turn-server-id error_type=ValueError" in caplog.text
    assert "private provider reply" not in caplog.text
    assert "owner-token" not in caplog.text


@pytest.mark.parametrize(
    "filename", [r"C:\secret-fixture-directory\worker.py", "/secret-fixture-directory/worker.py"]
)
def test_preparation_error_site_omits_private_paths(filename):
    try:
        exec(compile("raise ValueError('private response')", filename, "exec"))
    except ValueError as exc:
        site = _raise_site(exc)
    assert "worker.py:1:<module>" in site
    assert "secret-fixture-directory" not in site
    assert "private response" not in site
    assert "C:" not in site
    assert "/" not in site and "\\" not in site


@pytest.mark.asyncio
async def test_cancelled_draft_resumes_accepted_reply_without_another_send(
    app_factory, monkeypatch
):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)
    sends = 0

    def send_segments(_self, request):
        nonlocal sends
        sends += 1
        output = {
            "question": None,
            "discussion_memory": None,
            "segments": [
                {
                    "text": "A stored paragraph grounded in the frozen snapshot.",
                    "source_ids": ["S1"],
                    "reply_to": None,
                    "support_mode": "direct",
                }
            ],
        }
        canonical = json.dumps(output, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return SegmentAcceptedCandidateV2(
            request=request,
            http_status=200,
            finish_reason="stop",
            usage=LLMUsageV1(1, 0, 1, 2),
            output_json=canonical,
            output_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            provider_output=output,
        )

    monkeypatch.setattr(SegmentLLMAdapter, "send_accepted", send_segments)
    tasks = TaskManager()
    tts = MockTTSProvider()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=adapter),
        tts_provider=tts,
        tasks=tasks,
    )
    mark_ready = service.repository.mark_turn_ready

    def cancel_before_ready(*_args, **_kwargs):
        raise asyncio.CancelledError

    def snapshot():
        with database.session() as db:
            saved = db.execute(
                text(
                    "SELECT speech,structured_json,transcript_hash,predecessor_turn_ids_json,"
                    "cutoff_turn_index,retrieval_receipts_json,evidence_trace_json "
                    "FROM debate_turns WHERE id=:id"
                ),
                {"id": turn_id},
            ).one()
            state = db.execute(
                text(
                    "SELECT t.generation_status,j.state,j.claim_token,p.state "
                    "FROM debate_turns AS t JOIN jobs AS j ON j.turn_id=t.id "
                    "JOIN provider_operations AS p ON p.logical_item_id=t.id WHERE t.id=:id"
                ),
                {"id": turn_id},
            ).one()
            return tuple(saved), tuple(state)

    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            debate.status = "draft"
            rule = json.loads(debate.rule_snapshot_json)
            rule["turn_protocol"] = "segments_v2"
            debate.rule_snapshot_json = json.dumps(rule)
            turn = db.get(DebateTurn, turn_id)
            turn.generation_status, turn.speech, turn.structured_json = "pending", None, None
            turn.retrieval_receipts_json = "[]"
        monkeypatch.setattr(service.repository, "mark_turn_ready", cancel_before_ready)
        with database.session() as db:
            with pytest.raises(asyncio.CancelledError):
                await service.prepare_turn(db, debate_id, turn_id)
        saved, state = snapshot()
        assert state == ("pending", "pending", None, "accepted")
        assert saved[0] == "A stored paragraph grounded in the frozen snapshot."
        assert saved[2] and json.loads(saved[5])
        assert sends == 1
        audio_path = Path(settings.resolved_data_root) / service.audio_store.relative_path(
            COURSE_ID, debate_id, turn_id
        )
        assert not audio_path.exists()
        monkeypatch.setattr(service.repository, "mark_turn_ready", mark_ready)
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        resumed_saved, state = snapshot()
        assert state[:2] == ("final_ready", "completed")
        assert state[3] == "succeeded"
        assert resumed_saved == saved
        assert sends == 1 and tts.synthesize_calls == 2
        assert audio_path.is_file()
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_cancellation_after_ready_commit_retains_audio(app_factory, monkeypatch):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    tasks = TaskManager()
    tts = MockTTSProvider()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=tts,
        tasks=tasks,
    )

    publish_events = service._publish_events

    async def cancel_publication(events):
        with database.session() as db:
            ready = db.get(DebateTurn, turn_id).generation_status == "final_ready"
        if ready:
            raise asyncio.CancelledError
        await publish_events(events)

    monkeypatch.setattr(service, "_publish_events", cancel_publication)
    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            rule = json.loads(debate.rule_snapshot_json)
            rule["turn_protocol"] = "segments_v2"
            debate.rule_snapshot_json = json.dumps(rule)
        with database.session() as db:
            with pytest.raises(asyncio.CancelledError):
                await service.prepare_turn(db, debate_id, turn_id)
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            assert turn.generation_status == "final_ready"
            assert turn.audio_file_id
            assert (
                db.execute(
                    text("SELECT state FROM jobs WHERE turn_id=:id"), {"id": turn_id}
                ).scalar_one()
                == "completed"
            )
        audio_path = Path(settings.resolved_data_root) / service.audio_store.relative_path(
            COURSE_ID, debate_id, turn_id
        )
        assert audio_path.is_file() and audio_path.stat().st_size > 0
        assert tts.synthesize_calls == 1
    finally:
        await tasks.close()
        database.dispose()


def test_saved_paragraph_text_is_reused_without_embedding_or_llm(app_factory, monkeypatch):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    preparer = SqlTurnPreparer(settings=settings, llm=MockLLMProvider())

    def forbidden_call(*_args, **_kwargs):
        pytest.fail("saved text must not generate or embed again")

    monkeypatch.setattr(preparer, "_query_embedding_service", forbidden_call)
    monkeypatch.setattr(preparer.llm, "generate_turn", forbidden_call)
    try:
        with database.session() as db:
            debate = db.get(Debate, debate_id)
            turn = db.get(DebateTurn, turn_id)
            rule = json.loads(debate.rule_snapshot_json)
            rule["turn_protocol"] = "segments_v2"
            debate.rule_snapshot_json = json.dumps(rule)
            fence = generation_fence(db, debate, turn)
            turn.speech = "Saved classroom text."
            turn.structured_json = json.dumps(
                {
                    "schema_version": "segment_turn_v2",
                    "segments": [{"text": turn.speech, "source_ids": [], "reply_to": None}],
                }
            )
            turn.transcript_hash = fence.transcript_hash
            turn.cutoff_turn_index = fence.cutoff_turn_index
            turn.retrieval_status = "no_match"
            turn.grounding_mode = "general_reasoning"
            db.flush()
            prepared = preparer(db, debate, turn, attempt=1, cancellation_generation=0)
            assert prepared.speech == turn.speech
            assert prepared.structured["schema_version"] == "segment_turn_v2"
            assert prepared.llm_publication is None
            assert prepared.transcript_hash == fence.transcript_hash
    finally:
        database.dispose()


def test_paragraph_source_projection_keeps_saved_reference_and_rejects_wrong_document(app_factory):
    _, database, _, debate_id, turn_id = _seed_running_product_debate(app_factory)
    try:
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            participant = db.get(DebateParticipant, turn.participant_id)
            chunk = db.scalar(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.snapshot_id == turn.knowledge_snapshot_id
                )
            )
            document = db.get(SnapshotDocument, chunk.snapshot_document_id)
            turn.speech = "This paragraph cites the second candidate only."
            turn.structured_json = json.dumps(
                {
                    "schema_version": "segment_turn_v2",
                    "segments": [
                        {
                            "text": turn.speech,
                            "source_ids": ["frozen-evidence-two"],
                            "reply_to": None,
                        }
                    ],
                }
            )
            receipt = {
                "evidence_id": "frozen-evidence-two",
                "snapshot_id": turn.knowledge_snapshot_id,
                "chunk_id": chunk.id,
                "text": chunk.text,
                "source_filename": document.source_filename,
                "query_hash": "a" * 64,
            }
            turn.retrieval_receipts_json = json.dumps([receipt])
            result, sources = segment_projection(db, turn, participant)
            assert result.segments[0].source_ids == ["frozen-evidence-two"]
            assert sources[0].source_id == "frozen-evidence-two"
            assert sources[0].excerpt == chunk.text
            assert sources[0].version_label == participant.version_label
            receipt["source_filename"] = "wrong-document.md"
            turn.retrieval_receipts_json = json.dumps([receipt])
            with pytest.raises(PlatformError):
                segment_projection(db, turn, participant)
    finally:
        database.dispose()


@pytest.mark.asyncio
@pytest.mark.skip(reason="obsolete pre-segments real-LLM adapter fixture")
async def test_accepted_turn_publishes_when_only_subset_of_candidate_receipts_is_used(
    app_factory, monkeypatch
):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    adapter = _FakeDashScopeAdapter()
    _install_fake_dashscope_product_path(database, settings, adapter)
    _patch_local_confirmation(monkeypatch)
    original = SqlSnapshotRetriever.retrieve

    def repeated_candidate(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        assert result.receipts
        first = result.receipts[0]
        duplicate = replace(first, evidence_id=first.resolved_evidence_id() + "-alternate")
        return replace(result, receipts=(*result.receipts, duplicate))

    monkeypatch.setattr(SqlSnapshotRetriever, "retrieve", repeated_candidate)
    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=_product_preparer(settings, adapter),
        tts_provider=MockTTSProvider(),
        tasks=tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            assert turn.generation_status == "final_ready"
            assert turn.safe_error_code is None
            assert turn.speech and turn.audio_file_id
            assert (
                db.execute(
                    text("SELECT state FROM provider_operations WHERE logical_item_id=:id"),
                    {"id": turn_id},
                ).scalar_one()
                == "succeeded"
            )
        assert adapter.call_count == 1
    finally:
        await tasks.close()
        database.dispose()


def test_chinese_draft_locks_language_before_preview_and_start(app_factory):
    app, database, _settings = app_factory()
    try:
        with TestClient(app) as client:
            agents = [
                _insert_published_agent(
                    database,
                    group_id=GROUP_DEMO_ID,
                    name=f"Language {i}",
                    evidence=(
                        "A synthetic community balances shared resources and individual choice."
                    ),
                )
                for i in range(2)
            ]
            _, csrf = login(client)
            created = client.post(
                f"/api/v1/courses/{COURSE_ID}/debates",
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
                json={
                    "topic": "社区如何平衡公共资源与个人选择？",
                    "output_language": "zh",
                    "round_count": 4,
                    "participants": [{"agent_id": item, "stance_mode": "open"} for item in agents],
                },
            )
            assert created.status_code == 201, created.text
            detail = created.json()
            assert detail["output_language"] == "zh"
            with database.session() as db:
                assert db.get(Debate, detail["id"]).output_language == "zh"
            started = client.post(
                f"/api/v1/debates/{detail['id']}/start",
                headers=_headers(csrf, **{"Idempotency-Key": str(uuid4())}),
                json={
                    "expected_revision": 0,
                    "expected_current_audio_debate_id": None,
                    "confirm_previous_audio_cleanup": False,
                    "output_language": "en",
                },
            )
            assert started.status_code == 409
            assert started.json()["code"] == "output_language_locked"
            with database.session() as db:
                assert db.get(Debate, detail["id"]).status == "draft"
                assert db.get(Debate, detail["id"]).output_language == "zh"
    finally:
        database.dispose()


@pytest.mark.parametrize("topic", ["中文讨论", "中文 AI 与 café", "社区的选择？"])
def test_chinese_topic_preserves_authored_text(topic):
    assert validate_topic(topic, "zh") == topic


@pytest.mark.parametrize("topic", ["中文\u202e讨论", "中文\n讨论", "中文\t讨论", "123？"])
def test_topic_accepts_authored_characters_and_normalizes_only_for_provider(topic):
    assert validate_topic(topic, "zh") == topic.strip()
    assert "\u202e" not in model_topic(topic)
    assert "\n" not in model_topic(topic)
    assert "\t" not in model_topic(topic)


@pytest.mark.asyncio
async def test_failed_preview_retains_error_and_failed_job_instead_of_infinite_pending(app_factory):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    with database.session() as db:
        db.get(Debate, debate_id).status = "draft"

    class FailedPreparer(SqlTurnPreparer):
        def __call__(self, *args, **kwargs):
            raise PlatformError("turn_generation_failed", "Generation failed.", 503)

    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=FailedPreparer(settings=settings),
        tts_provider=MockTTSProvider(),
        tasks=tasks,
    )
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        with database.session() as db:
            assert db.get(Debate, debate_id).status == "draft"
            turn = db.get(DebateTurn, turn_id)
            assert (turn.generation_status, turn.safe_error_code) == (
                "failed",
                "turn_generation_failed",
            )
            job = db.execute(
                text("SELECT state,safe_error_code FROM jobs WHERE turn_id=:id"),
                {"id": turn_id},
            ).one()
            assert tuple(job) == ("failed", "turn_generation_failed")
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_preview_does_not_enqueue_live_successor_or_change_playback(app_factory, monkeypatch):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        debate.status = "draft"
        rule = json.loads(debate.rule_snapshot_json)
        rule["turn_protocol"] = "segments_v2"
        debate.rule_snapshot_json = json.dumps(rule)
        before = tuple(
            db.execute(
                text(
                    "SELECT status,current_turn_id,control_version "
                    "FROM playback_states WHERE debate_id=:id"
                ),
                {"id": debate_id},
            ).one()
        )
    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=MockTTSProvider(),
        tasks=tasks,
    )

    async def forbidden_enqueue(*_args, **_kwargs):
        pytest.fail("Preview scheduler owns the next draft turn")

    monkeypatch.setattr(service, "_enqueue", forbidden_enqueue)
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        with database.session() as db:
            assert db.get(DebateTurn, turn_id).generation_status == "final_ready"
            after = tuple(
                db.execute(
                    text(
                        "SELECT status,current_turn_id,control_version "
                        "FROM playback_states WHERE debate_id=:id"
                    ),
                    {"id": debate_id},
                ).one()
            )
            assert after == before
    finally:
        await tasks.close()
        database.dispose()


@pytest.mark.asyncio
async def test_public_segment_snapshot_accepts_actual_audio_readiness(app_factory, monkeypatch):
    from app.modules.debates.playback.schemas import SnapshotPayload

    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        tasks=tasks,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=MockTTSProvider(),
    )
    monkeypatch.setattr(service, "_assert_teacher", lambda *_args: None)
    try:
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            turn.speech = "Saved paragraph."
            turn.structured_json = json.dumps(
                {
                    "schema_version": "segment_turn_v2",
                    "segments": [{"text": turn.speech, "source_ids": [], "reply_to": None}],
                }
            )
            turn.generation_status = "final_ready"
            turn.publication_status = "public"
            turn.preparation_stage = "ready"
            turn.transcript_hash = "a" * 64
            turn.cutoff_turn_index = 0
            turn.retrieval_status = "no_match"
            turn.grounding_mode = "general_reasoning"
            turn.word_count = 2
            turn.audio_file_id = None
        with database.session() as db:
            payload, _ = await service.snapshot(db, debate_id)
            decoded = SnapshotPayload.model_validate(payload)
            assert len(decoded.public_turns) == 1
            assert decoded.public_turns[0].audio_ready is False
            assert decoded.public_turns[0].segment_turn.segments[0].text == "Saved paragraph."
    finally:
        await tasks.close()
        database.dispose()
