"""Missing voice configuration preserves prepared text without synthesizing audio."""

import json

import pytest
from app.modules.debates.models import Debate, DebateTurn
from app.modules.debates.playback.generation_adapter import SqlTurnPreparer
from app.modules.debates.playback.protocols import ResolvedTurnVoice
from app.modules.debates.playback.task_manager import TaskManager
from app.providers.llm import MockLLMProvider
from app.providers.tts import MockTTSProvider

from tests.test_wave4_llm_p1_product import _product_service, _seed_running_product_debate


@pytest.mark.asyncio
async def test_missing_voice_completes_draft_text_without_audio_or_repeat_generation(
    app_factory, monkeypatch
):
    _, database, settings, debate_id, turn_id = _seed_running_product_debate(app_factory)
    with database.session() as db:
        debate = db.get(Debate, debate_id)
        debate.status = "draft"
        rule = json.loads(debate.rule_snapshot_json)
        rule["turn_protocol"] = "segments_v2"
        debate.rule_snapshot_json = json.dumps(rule)
    tasks = TaskManager()
    service = _product_service(
        database,
        settings,
        preparer=SqlTurnPreparer(settings=settings, llm=MockLLMProvider()),
        tts_provider=MockTTSProvider(),
        tasks=tasks,
    )
    monkeypatch.setattr(
        service, "_resolve_voice", lambda *_args: ResolvedTurnVoice("mock_sentinel", None, "")
    )

    def forbidden_audio(*_args, **_kwargs):
        pytest.fail("missing voice must not synthesize placeholder audio")

    monkeypatch.setattr(service.audio_store, "stage_synthesis", forbidden_audio)
    try:
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
        with database.session() as db:
            turn = db.get(DebateTurn, turn_id)
            assert turn.generation_status == "final_ready"
            assert turn.speech and turn.speech.strip()
            assert turn.audio_file_id is None
            assert turn.audio_duration_ms == 0
            assert turn.safe_error_code == "tts_voice_unavailable"
            saved_speech = turn.speech
        monkeypatch.setattr(service, "_call_preparer", forbidden_audio)
        with database.session() as db:
            await service.prepare_turn(db, debate_id, turn_id)
            assert db.get(DebateTurn, turn_id).speech == saved_speech
    finally:
        await tasks.close()
        database.dispose()
