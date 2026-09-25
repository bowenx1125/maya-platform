"""Citation markers stay in displayed text and leave the spoken text."""

from __future__ import annotations

import pytest
from app.modules.workspace.chat_stream import synthesis_language
from app.providers.tts import spoken_text


def test_spoken_text_removes_citation_markers_and_tidies_punctuation() -> None:
    assert (
        spoken_text("The jars stay on the east terrace [S1]. See also [S2].")
        == "The jars stay on the east terrace. See also."
    )
    assert spoken_text("东边的陶罐还在 [S1]。另见［S2］。") == "东边的陶罐还在。另见。"
    assert spoken_text("See [S1], [S2].") == "See."
    assert spoken_text("Both [S1] and [S2] agree.") == "Both and agree."
    assert spoken_text("[S1] 你好 [S2]") == "你好"
    assert spoken_text("end [S1]\n\nNext [S2].") == "end\n\nNext."
    assert spoken_text("word[S1].") == "word."
    assert spoken_text("[S1, S2]") == ""
    assert spoken_text("[ S1 ]") == ""
    assert spoken_text("见【S1】。") == "见。"
    assert spoken_text("See [S1、S2].") == "See."
    assert spoken_text("Range [S1-S3] holds.") == "Range holds."
    assert spoken_text("Note (S1).") == "Note (S1)."
    assert spoken_text("Section (S2)") == "Section (S2)"
    assert spoken_text("See (S1, S2).") == "See."
    assert spoken_text("Range (S1-S3) holds.") == "Range holds."
    assert spoken_text("(S1) starts.") == "starts."
    assert spoken_text("word(S1).") == "word."
    assert spoken_text("lower [s1].") == "lower."
    assert spoken_text("（S1）结束") == "结束"


def test_spoken_text_leaves_speech_without_markers_unchanged() -> None:
    plain = "Keep  the double space.\n\nAnd this paragraph."
    assert spoken_text(plain) == plain
    assert spoken_text("A source named S1 is not a marker.") == "A source named S1 is not a marker."
    assert spoken_text("See (Socrates) on S1.") == "See (Socrates) on S1."


def test_synthesis_language_uses_han_to_latin_ratio() -> None:
    assert synthesis_language("en", "The jars stay on the east terrace.") == "en"
    assert synthesis_language("en", "The Tao (道)") == "en"
    assert synthesis_language("en", "东边的陶罐还在。") == "zh"
    assert synthesis_language("en", "你好 Hi") == "zh"
    assert synthesis_language("zh-CN", "Hello.") == "zh"
    assert synthesis_language("zh-CN", "The Tao (道)") == "zh"
    assert synthesis_language("zh-CN", "你好。") == "zh"
    with pytest.raises(ValueError, match="unsupported chat language"):
        synthesis_language("fr", "Hello.")
