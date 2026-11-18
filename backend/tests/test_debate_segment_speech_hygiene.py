"""Segment speech hygiene: reject garbled Unicode/JSON residue; never voice it."""

from __future__ import annotations

import pytest
from app.modules.debates.generation.segments import (
    SEGMENT_OUTPUT_SALVAGED,
    SEGMENT_SPEECH_INVALID,
    SegmentProtocolError,
    prepare_segment_speech,
    salvage_segment_output,
    sanitize_segment_text,
    segment_speech_needs_regeneration,
    segment_text_is_garbled,
    validate_segment_output,
)
from app.modules.debates.playback.audio import AudioStore
from app.providers.tts import TTSProviderError

from tests.test_debate_prompt_v4 import _output
from tests.test_debate_segment_salvage import _v5_snapshot

# Exact production samples (debate b03a2b4f, repair attempt 2 before #466).
JSON_FRAGMENT_SPEECH = (
    ',source_ids: ["S2","supportmode": "no_match", replyto: null }]]}] }]} } } }}...'
)
GARBLED_ZH_SPEECH = (
    "我认为课堂讨论需要更清楚的证据"
    + ("\ufeff" * 6)
    + "，否则学生无法判断立场"
    + "\uf898\uf497\uf5b5"
    + "。"
)


def test_sanitize_strips_bom_and_zero_width() -> None:
    cleaned = sanitize_segment_text("\ufeffhello\u200b world\ufeff")
    assert cleaned == "hello world"
    assert "\ufeff" not in cleaned


def test_json_fragment_speech_is_rejected() -> None:
    assert segment_text_is_garbled(JSON_FRAGMENT_SPEECH)
    assert segment_speech_needs_regeneration(JSON_FRAGMENT_SPEECH)
    with pytest.raises(SegmentProtocolError) as raised:
        prepare_segment_speech(JSON_FRAGMENT_SPEECH)
    assert raised.value.code == "segment_text_invalid"


def test_private_use_and_bom_speech_is_rejected() -> None:
    cleaned = sanitize_segment_text(GARBLED_ZH_SPEECH)
    assert "\ufeff" not in cleaned
    assert segment_text_is_garbled(cleaned)
    assert segment_speech_needs_regeneration(GARBLED_ZH_SPEECH)
    with pytest.raises(SegmentProtocolError) as raised:
        prepare_segment_speech(GARBLED_ZH_SPEECH)
    assert raised.value.code == "segment_text_invalid"


def test_validate_rejects_exact_production_samples() -> None:
    snapshot = _v5_snapshot(language="zh")
    for sample in (JSON_FRAGMENT_SPEECH, GARBLED_ZH_SPEECH):
        with pytest.raises(SegmentProtocolError) as raised:
            validate_segment_output(_output(sample), snapshot)
        assert raised.value.code == "segment_text_invalid"


def test_salvage_never_keeps_garbled_speech() -> None:
    snapshot = _v5_snapshot(language="zh")
    for sample in (JSON_FRAGMENT_SPEECH, GARBLED_ZH_SPEECH):
        result = salvage_segment_output(_output(sample), snapshot)
        assert result.speech.strip()
        assert not segment_speech_needs_regeneration(result.speech)
        assert result.salvage_warning == SEGMENT_OUTPUT_SALVAGED
        assert "source_ids" not in result.speech
        assert "\uf898" not in result.speech


def test_clean_speech_still_passes() -> None:
    text = "我认为开场发言忽略了课堂注意力的代价，因此我不同意那个立场。"
    assert prepare_segment_speech(text) == text
    assert not segment_speech_needs_regeneration(text)
    snapshot = _v5_snapshot(language="zh")
    accepted = validate_segment_output(_output(text), snapshot, repairable=False)
    assert accepted.speech == text


def test_tts_refuses_garbled_speech(tmp_path) -> None:
    store = AudioStore(tmp_path)
    with pytest.raises(TTSProviderError, match="unreadable"):
        store.synthesize_and_store(
            course_id="course",
            debate_id="debate",
            turn_id="turn",
            speech=JSON_FRAGMENT_SPEECH,
            voice_token="mock-voice",
            language="zh",
        )
    with pytest.raises(TTSProviderError, match="unreadable"):
        store.stage_synthesis(
            course_id="course",
            debate_id="debate",
            turn_id="turn",
            speech=GARBLED_ZH_SPEECH,
            voice_token="mock-voice",
            language="zh",
        )


def test_segment_speech_invalid_constant() -> None:
    assert SEGMENT_SPEECH_INVALID == "segment_speech_invalid"
