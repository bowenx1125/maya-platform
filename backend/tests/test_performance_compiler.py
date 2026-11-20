from __future__ import annotations

from app.modules.debates.performance import (
    anchor_to_time,
    assemble_viseme_windows,
    char_to_viseme,
    compile_performance,
    estimate_duration,
    flatten_sentences,
    rule_based_performance,
    syllable_to_viseme,
    validate_performance,
)
from app.providers.tts import WordTimestamp

WORDS: list[WordTimestamp] = [
    {"text": "我", "begin_index": 0, "end_index": 1, "begin_ms": 1000, "end_ms": 1400},
    {"text": "方", "begin_index": 1, "end_index": 2, "begin_ms": 1400, "end_ms": 1560},
    {"text": "认", "begin_index": 2, "end_index": 3, "begin_ms": 1560, "end_ms": 1760},
    {"text": "为", "begin_index": 3, "end_index": 4, "begin_ms": 1760, "end_ms": 1960},
    {"text": "啊", "begin_index": 4, "end_index": 5, "begin_ms": 1960, "end_ms": 2240},
]


def test_estimate_duration_has_a_floor_and_scales() -> None:
    assert estimate_duration("短") == 2.0
    assert abs(estimate_duration("一" * 43) - 10.0) < 0.01


def test_rule_based_labels_cover_debate_markers_and_cap_at_five() -> None:
    text = "请问对方辩友，我方认为诚信是立身之本？"
    beats = rule_based_performance(text)["beats"]
    kinds = [b["kind"] for b in beats]
    assert "invite_present" in kinds
    assert "chin_stroke" in kinds
    chin = next(b for b in beats if b["kind"] == "chin_stroke")
    assert chin["anchor"] == len(text) - 1
    invite = next(b for b in beats if b["kind"] == "invite_present")
    assert invite["anchor"] == 0
    flooded = rule_based_performance("请问" + "恰恰相反" * 20 + "难道" * 20)
    assert len(flooded["beats"]) <= 5


def test_validate_performance_whitelists_labels() -> None:
    validated = validate_performance(
        {
            "emotion": "angry",
            "posture": "fly",
            "beats": [
                {"kind": "nod", "anchor": "认为"},
                {"kind": "dance", "anchor": 3},
                {"kind": "nod", "anchor": 999},
            ],
        },
        "我方认为啊",
    )
    assert validated["emotion"] == "calm"
    assert validated["posture"] is None
    beats = validated["beats"]
    assert beats[0]["anchor"] == 2
    assert all(b["kind"] != "dance" for b in beats)
    assert beats[1]["anchor"] == 4


def test_compile_schedules_within_gap_and_tail() -> None:
    compiled = compile_performance("请问" + "中" * 40, audio_duration_sec=11.0)
    assert compiled["version"] == 2
    assert compiled["duration"] == 11.0
    assert compiled["posture"] == "open_palm_listening"
    assert compiled["viseme"] == "energy"
    assert "visemes" not in compiled
    times = [e["t"] for e in compiled["events"]]
    assert times[0] >= 0.1
    assert all(b - a >= 0.9 for a, b in zip(times, times[1:], strict=False))
    assert all(t <= 11.0 - 0.4 for t in times)
    assert len(times) <= 5


def test_explicit_labels_skip_rule_fallback_and_keep_posture() -> None:
    compiled = compile_performance("综上所述", performance={"emotion": "skeptical"})
    assert compiled["posture"] == "hand_behind_back"
    assert compiled["events"] == []
    ruled = compile_performance("综上所述，我方观点成立")
    assert any(e["clip"] == "settle_calm" for e in ruled["events"])


def test_pinyin_to_viseme_mapping() -> None:
    assert syllable_to_viseme("ba") == ("PP", 0.12)
    assert syllable_to_viseme("fang") == ("FF", 0.3)
    assert syllable_to_viseme("a") == ("aa", 0.85)
    assert syllable_to_viseme("zhong") == ("O", 0.8)
    assert syllable_to_viseme("zhi") == ("RR", 0.4)
    assert syllable_to_viseme("si") == ("SS", 0.4)
    assert syllable_to_viseme("lü") == ("U", 0.6)
    assert syllable_to_viseme("chen") == ("E", 0.5)
    assert char_to_viseme("中") == ("O", 0.8)
    assert char_to_viseme("，") is None


def test_assemble_viseme_windows_skips_punctuation() -> None:
    windows = assemble_viseme_windows(WORDS)
    assert len(windows) == 5
    assert windows[0] == {"t0": 1.0, "t1": 1.4, "viseme": "viseme_O", "jaw": 0.8}
    assert all(w["viseme"].startswith("viseme_") for w in windows)
    punct = [{"text": "！", "begin_index": 0, "end_index": 1, "begin_ms": 0, "end_ms": 200}]
    assert assemble_viseme_windows(punct) == []


def test_flatten_sentences_accumulates_offsets() -> None:
    sentences = [
        {
            "words": [
                {"text": "我", "begin_index": 0, "end_index": 1, "begin_time": 0, "end_time": 200}
            ]
        },
        {
            "words": [
                {"text": "好", "begin_index": 2, "end_index": 3, "begin_time": 0, "end_time": 200}
            ],
            "duration_ms": 500,
        },
        {
            "words": [
                {"text": "吗", "begin_index": 4, "end_index": 5, "begin_time": 0, "end_time": 200}
            ]
        },
    ]
    flat = flatten_sentences(sentences)
    assert flat[1]["begin_ms"] == 260
    assert flat[2]["begin_ms"] == 760


def test_anchor_to_time_prefers_word_timestamps() -> None:
    assert anchor_to_time(1, WORDS, 3.0, 5) == 1.4
    assert anchor_to_time(2, [], 4.0, 8) == 1.0
    beyond = anchor_to_time(4, WORDS[:2], 3.0, 5)
    assert 0 < beyond <= 3.0


def test_compile_with_timestamps_emits_timed_visemes() -> None:
    compiled = compile_performance(
        "我方认为啊",
        audio_duration_sec=3.0,
        words=WORDS,
        performance={"beats": [{"kind": "nod", "anchor": 1}]},
    )
    assert compiled["viseme"] == "timed"
    assert len(compiled["visemes"]) == 5
    nod = next(e for e in compiled["events"] if e["clip"] == "nod")
    assert nod["t"] == 1.4  # anchor char 1 (方) begins at 1400 ms
    assert compiled["duration"] == 3.0


def test_expanded_gesture_rules_cover_new_clips() -> None:
    cases = {
        "换句话说，我方再解释一次": "both_hands_open",
        "关键在于定义": "point_raise",
        "试想另一种情况": "head_tilt_think",
        "显然这不成立": "hand_chop",
        "另一方面还有证据": "weight_shift",
    }
    for text, kind in cases.items():
        beats = rule_based_performance(text)["beats"]
        assert kind in [b["kind"] for b in beats]
        compiled = compile_performance(text)
        events = [e for e in compiled["events"] if e["clip"] == kind]
        assert events and events[0]["dur"] > 0
