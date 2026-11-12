"""Performance compiler: turn text + optional LLM labels + optional word
timestamps -> the animation timeline consumed by the 3D stage.

Pure rule-based scheduling, O(n); the only gesture vocabulary allowed is the
stage's clip catalog. Mirrors viewer/performance-compiler.mjs (prototype),
differential-tested against it before this port landed.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from app.modules.debates.performance.visemes import (
    VisemeWindow,
    anchor_to_time,
    assemble_viseme_windows,
)
from app.providers.tts import WordTimestamp

# Clip catalog must match the stage's pose mixer exactly.
GESTURE_DUR = {
    "emphasis": 0.9,
    "palm_open_sweep": 1.4,
    "chin_stroke": 1.8,
    "nod": 0.7,
    "headshake": 1.0,
    "lean_in": 1.2,
    "invite_present": 1.1,
    "object_raise": 0.9,
    "doubt_shrug": 1.0,
    "settle_calm": 1.6,
    "turn_ack": 0.8,
}
POSTURES = ("hand_behind_back", "open_palm_listening", "hand_on_chest")
EMOTIONS = ("calm", "firm", "thoughtful", "friendly", "skeptical")

_CHARS_PER_SEC = 4.3
_MIN_DURATION = 2.0
_MAX_BEATS = 5
_MIN_BEAT_GAP = 0.9
_FADE_MS = 250
_TAIL_PAD = 0.4

# Fallback labeling when the LLM provides no performance block; LLM labels go
# through the same validation exit.
_RULES: list[tuple[re.Pattern[str], str, int]] = [
    (re.compile(r"(恰恰相反|绝不是|绝不|毫无疑问|必须|肯定)"), "emphasis", 3),
    (re.compile(r"(请问|请对方|您方|敢问|请教)"), "invite_present", 2),
    (re.compile(r"(难道|岂不是|何尝|岂非)"), "headshake", 2),
    (re.compile(r"(综上所述|总而言之|总的来说|所以|可见)"), "settle_calm", 2),
    (re.compile(r"(首先|第一|其次|第二|最后)"), "emphasis", 1),
    (re.compile(r"(遗憾|无奈|可惜|说不通|站不住)"), "doubt_shrug", 2),
    (re.compile(r"(谢谢|感谢|承让)"), "turn_ack", 2),
    (re.compile(r"(我认为|我觉得|相信|坚信)"), "nod", 1),
    (re.compile(r"[?？]$"), "chin_stroke", 1),
    (re.compile(r"[!！]$"), "emphasis", 1),
]


class PerformanceEvent(TypedDict):
    t: float
    type: Literal["gesture"]
    clip: str
    dur: float
    fade_ms: int


class CompiledPerformance(TypedDict, total=False):
    version: int
    duration: float
    emotion: str
    posture: str
    viseme: str
    events: list[PerformanceEvent]
    visemes: list[VisemeWindow]


class _Beat(TypedDict):
    anchor: int
    kind: str
    prio: int


class _PerformanceLabels(TypedDict, total=False):
    emotion: str
    posture: str
    beats: list[dict[str, object]]


def estimate_duration(text: str) -> float:
    chars = len(re.sub(r"\s", "", text))
    return max(_MIN_DURATION, chars / _CHARS_PER_SEC)


def rule_based_performance(text: str) -> dict[str, object]:
    beats: list[_Beat] = []
    for pattern, kind, prio in _RULES:
        match = pattern.search(text)
        if match:
            # Sentence-final rules anchor on the last character so the clip
            # fires at the closing beat instead of the punctuation mark.
            if kind == "chin_stroke" or (kind == "emphasis" and len(match.group(0)) <= 1):
                anchor = max(0, len(text) - 1)
            else:
                anchor = match.start()
            beats.append({"anchor": anchor, "kind": kind, "prio": prio})
    beats.sort(key=lambda b: (b["anchor"], -b["prio"]))
    return {"emotion": "calm", "beats": beats[:_MAX_BEATS], "posture": None}


def validate_performance(perf: dict[str, object] | None, text: str) -> dict[str, object]:
    """Whitelist LLM labels: unknown clips drop, anchors clamp, closed enums."""
    out: dict[str, object] = {"emotion": "calm", "beats": [], "posture": None}
    if not isinstance(perf, dict):
        return out
    if perf.get("emotion") in EMOTIONS:
        out["emotion"] = str(perf["emotion"])
    beats = perf.get("beats")
    if isinstance(beats, list):
        validated: list[_Beat] = []
        for raw in beats[:_MAX_BEATS]:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "")
            if kind not in GESTURE_DUR:
                continue  # hallucinated clip names never reach the stage
            anchor = raw.get("anchor")
            if not isinstance(anchor, (int, float)):
                found = text.find(str(anchor or ""))  # allow a substring anchor
                if found < 0:
                    continue
                anchor = found
            validated.append(
                {"anchor": max(0, min(int(anchor), len(text) - 1)), "kind": kind, "prio": 2}
            )
        out["beats"] = validated
    if perf.get("posture") in POSTURES:
        out["posture"] = str(perf["posture"])
    return out


def compile_performance(
    text: str,
    audio_duration_sec: float | None = None,
    performance: dict[str, object] | None = None,
    words: list[WordTimestamp] | None = None,
) -> CompiledPerformance:
    duration = (
        audio_duration_sec
        if audio_duration_sec is not None and audio_duration_sec > 0
        else estimate_duration(text)
    )
    perf = validate_performance(performance, text) if performance else rule_based_performance(text)
    text_len = max(1, len(text))
    limit = duration - _TAIL_PAD

    events: list[PerformanceEvent] = []
    last_t = float("-inf")
    beats = perf["beats"]
    assert isinstance(beats, list)
    for beat in sorted(beats, key=lambda b: b["anchor"]):
        if words:
            t = anchor_to_time(beat["anchor"], words, duration, text_len)
        else:
            t = (beat["anchor"] / text_len) * duration
        t = min(max(t, 0.1), limit)  # openings may gesture immediately
        if t - last_t < _MIN_BEAT_GAP:
            continue  # drop the later beat when clips would collide
        last_t = t
        events.append(
            {
                "t": round(t, 2),
                "type": "gesture",
                "clip": beat["kind"],
                "dur": GESTURE_DUR[beat["kind"]],
                "fade_ms": _FADE_MS,
            }
        )

    posture = perf["posture"]
    if not posture:
        posture = (
            "hand_behind_back"
            if perf["emotion"] in ("skeptical", "firm")
            else "hand_on_chest"
            if perf["emotion"] in ("thoughtful", "friendly")
            else "open_palm_listening"
        )

    compiled: CompiledPerformance = {
        "version": 2,
        "duration": round(duration, 2),
        "emotion": str(perf["emotion"]),
        "posture": str(posture),
        "viseme": "timed" if words else "energy",
        "events": events,
    }
    if words:
        compiled["visemes"] = assemble_viseme_windows(words)
    return compiled
