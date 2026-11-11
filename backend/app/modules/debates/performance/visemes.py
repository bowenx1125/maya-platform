"""Pinyin to Oculus-viseme mapping and word-timestamp window assembly.

Client contract (stage3d): windows are absolute audio seconds
    [{t0, t1, viseme, jaw?}]  with viseme = "viseme_<name>"; jaw overrides openness.

Lip shape follows the final; an initial overrides only for lip-closed (PP) and
labiodental (FF) consonants. Apical vowels (zhi/chi/shi/ri, zi/ci/si) map by
their initial to RR/SS. Tones are ignored and punctuation produces no window,
so inter-syllable gaps stay naturally closed.
"""

from __future__ import annotations

import re
from typing import TypedDict

from pypinyin import Style, lazy_pinyin

from app.providers.tts import WordTimestamp

_HAN = re.compile(r"[一-鿿]")

# Initials that dictate lip shape before the vowel lands.
_INITIAL_OVERRIDE = {"b": "PP", "p": "PP", "m": "PP", "f": "FF"}
# pypinyin reports the apical vowel as "i"; the initial disambiguates it.
_APICAL = {"zh": "RR", "ch": "RR", "sh": "SS", "r": "RR", "z": "SS", "c": "SS", "s": "SS"}
# Finals to viseme, longest match first.
_FINALS = [
    ("iang", "aa"),
    ("uang", "aa"),
    ("uai", "aa"),
    ("uan", "aa"),
    ("ian", "aa"),
    ("iao", "O"),
    ("ua", "aa"),
    ("ang", "aa"),
    ("an", "aa"),
    ("ai", "aa"),
    ("ao", "O"),
    ("ong", "O"),
    ("ueng", "O"),
    ("iong", "O"),
    ("eng", "E"),
    ("en", "E"),
    ("ei", "E"),
    ("er", "E"),
    ("ie", "E"),
    ("ue", "E"),
    ("ve", "E"),
    ("e", "E"),
    ("ing", "I"),
    ("in", "I"),
    ("i", "I"),
    ("un", "U"),
    ("vn", "U"),
    ("v", "U"),
    ("u", "U"),
    ("a", "aa"),
    ("o", "O"),
    ("uo", "O"),
    ("ou", "O"),
]
_JAW = {
    "aa": 0.85,
    "O": 0.8,
    "U": 0.6,
    "E": 0.5,
    "I": 0.35,
    "PP": 0.12,
    "FF": 0.3,
    "DD": 0.45,
    "kk": 0.5,
    "CH": 0.45,
    "SS": 0.4,
    "RR": 0.4,
    "nn": 0.4,
    "sil": 0.0,
}
_INITIALS = (
    "zh",
    "ch",
    "sh",
    "b",
    "p",
    "m",
    "f",
    "d",
    "t",
    "n",
    "l",
    "g",
    "k",
    "h",
    "j",
    "q",
    "x",
    "r",
    "z",
    "c",
    "s",
    "y",
    "w",
)


class VisemeWindow(TypedDict):
    t0: float
    t1: float
    viseme: str
    jaw: float


def split_syllable(pinyin: str) -> tuple[str, str]:
    """Split a normalized syllable into (initial, final)."""
    p = pinyin.lower().replace("ü", "v")
    for initial in _INITIALS:
        if p.startswith(initial):
            return initial, p[len(initial) :]
    return "", p


def syllable_to_viseme(pinyin: str) -> tuple[str, float]:
    """Map one syllable to (viseme_name, default_jaw)."""
    initial, final = split_syllable(pinyin)
    if initial in _INITIAL_OVERRIDE:
        name = _INITIAL_OVERRIDE[initial]
        return name, _JAW[name]
    if final == "i" and initial in _APICAL:
        name = _APICAL[initial]
        return name, _JAW[name]
    for candidate, name in _FINALS:
        if final.startswith(candidate) or final == candidate:
            return name, _JAW[name]
    return "sil", 0.0


def char_to_viseme(ch: str) -> tuple[str, float] | None:
    """Map one Han character to (viseme, jaw); non-Han returns None."""
    if not _HAN.fullmatch(ch):
        return None
    pinyin = lazy_pinyin(ch, style=Style.NORMAL, errors="ignore")
    if not pinyin:
        return "sil", 0.0
    return syllable_to_viseme(pinyin[0])


def assemble_viseme_windows(words: list[WordTimestamp]) -> list[VisemeWindow]:
    """Compile absolute-millisecond word timestamps into client viseme windows."""
    windows: list[VisemeWindow] = []
    for word in words:
        text = (word.get("text") or "").strip()
        if len(text) != 1:
            continue
        hit = char_to_viseme(text)
        if hit is None:
            continue
        name, jaw = hit
        if name == "sil":
            continue
        t0 = word["begin_ms"] / 1000.0
        t1 = word["end_ms"] / 1000.0
        if t1 <= t0:
            continue
        windows.append(
            {"t0": round(t0, 3), "t1": round(t1, 3), "viseme": f"viseme_{name}", "jaw": jaw}
        )
    return windows


class _SentenceWord(TypedDict, total=False):
    text: str | None
    begin_index: int | None
    end_index: int | None
    begin_time: float
    end_time: float


class SentenceWords(TypedDict, total=False):
    words: list[_SentenceWord]
    duration_ms: float


def flatten_sentences(sentences: list[SentenceWords]) -> list[WordTimestamp]:
    """Fold per-sentence relative timestamps into absolute milliseconds.

    Intermediate sentences span last word end plus a fixed consonant-tail
    estimate; the final sentence absorbs the remaining audio so drift cannot
    push words past the real recording.
    """
    out: list[WordTimestamp] = []
    offset = 0.0
    for _index, sentence in enumerate(sentences):
        sentence_words = sentence.get("words") or []
        duration = sentence.get("duration_ms")
        if duration is None:
            tail = max((float(w.get("end_time") or 0.0) for w in sentence_words), default=0.0)
            duration = tail + SENTENCE_TAIL_MS
        for word in sentence_words:
            out.append(
                {
                    "text": word.get("text"),
                    "begin_index": word.get("begin_index"),
                    "end_index": word.get("end_index"),
                    "begin_ms": min(offset + float(word.get("begin_time") or 0.0), 1e12),
                    "end_ms": min(offset + float(word.get("end_time") or 0.0), 1e12),
                }
            )
        offset += float(duration)
    return out


SENTENCE_TAIL_MS = 60.0


def anchor_to_time(
    anchor_char: int,
    words: list[WordTimestamp],
    duration: float,
    text_len: int,
) -> float:
    """Resolve a gesture anchor (character offset) to audio seconds.

    Word timestamps win when they cover the anchor; otherwise fall back to the
    uniform per-character estimate so partial timestamp coverage still works.
    """
    for word in words:
        begin_index = word.get("begin_index")
        end_index = word.get("end_index")
        if begin_index is None or end_index is None:
            continue
        if int(begin_index) <= anchor_char < int(end_index):
            return word["begin_ms"] / 1000.0
    return max(0.0, (anchor_char / max(1, text_len)) * duration)
