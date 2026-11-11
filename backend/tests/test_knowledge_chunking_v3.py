"""The current structure-first chunker, and the frozen legacy chunker beside it."""

from __future__ import annotations

import hashlib
import json
import re

import pytest
from app.modules.knowledge.markdown import (
    CHUNK_MAX_TOKENS,
    CHUNK_MIN_TOKENS,
    CHUNK_TARGET_TOKENS,
    CHUNKING_VERSION,
    LEGACY_CHUNKING_VERSION,
    MAX_CHUNK_UTF8_BYTES,
    build_chunks,
    chunk_markdown,
    estimate_tokens,
)
from app.modules.knowledge.providers import prepare_snapshot_build
from app.modules.knowledge.providers.runtime import assert_snapshot_build_current
from app.modules.knowledge.providers.snapshot_build import SnapshotBuildError

SENTENCE_END = re.compile(r"[.!?。！？]$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")


def _en_paragraph(index: int, sentences: int = 8) -> str:
    return " ".join(
        f"Point {index}.{item} explains how a classroom rule shapes what students try next."
        for item in range(sentences)
    )


def _zh_paragraph(index: int, sentences: int = 10) -> str:
    return "".join(
        f"第{index}段第{item}句说明课堂规则如何影响学生下一步的尝试。" for item in range(sentences)
    )


def _assert_lossless(text: str, chunks: list[tuple[int, str, int, int]]) -> None:
    previous = 0
    for index, (chunk_index, chunk_text, start, end) in enumerate(chunks):
        assert chunk_index == index
        assert text[start:end] == chunk_text
        assert chunk_text == chunk_text.strip()
        assert not text[previous:start].strip()
        assert len(chunk_text.encode("utf-8")) <= MAX_CHUNK_UTF8_BYTES
        previous = end
    assert not text[previous:].strip()


def test_english_paragraphs_pack_to_the_target_without_splitting_a_paragraph() -> None:
    paragraphs = [_en_paragraph(index) for index in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert len(chunks) > 1
    for _, chunk_text, _, _ in chunks:
        assert CHUNK_MIN_TOKENS <= estimate_tokens(chunk_text) <= CHUNK_TARGET_TOKENS
        # Every chunk is a run of whole paragraphs.
        assert all(part in paragraphs for part in chunk_text.split("\n\n"))


def test_a_long_chinese_paragraph_is_cut_only_between_sentences() -> None:
    text = _zh_paragraph(1, sentences=120)
    assert estimate_tokens(text) > CHUNK_TARGET_TOKENS * 3
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert len(chunks) >= 4
    for _, chunk_text, _, _ in chunks:
        assert chunk_text.endswith("。")
        assert chunk_text.startswith("第1段第")
        assert CHUNK_MIN_TOKENS <= estimate_tokens(chunk_text) <= CHUNK_TARGET_TOKENS


def test_small_sections_merge_and_a_heading_never_ends_a_chunk() -> None:
    sections = [f"## Section {index}\n\n{_en_paragraph(index, sentences=2)}" for index in range(10)]
    text = "# Lesson\n\n" + "\n\n".join(sections)
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert len(chunks) < len(sections)
    for _, chunk_text, _, _ in chunks:
        assert not HEADING.match(chunk_text.splitlines()[-1])
        assert HEADING.match(chunk_text.splitlines()[0])


def test_large_sections_each_start_their_own_chunk_with_their_heading() -> None:
    sections = [f"## 第{index}节\n\n{_zh_paragraph(index, sentences=20)}" for index in range(4)]
    text = "\n\n".join(sections)
    assert all(
        CHUNK_TARGET_TOKENS // 2 < estimate_tokens(item) <= CHUNK_TARGET_TOKENS for item in sections
    )
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert [chunk_text for _, chunk_text, _, _ in chunks] == sections


def test_a_tiny_tail_joins_the_chunk_before_it() -> None:
    body = "\n\n".join(_en_paragraph(index) for index in range(5))
    text = body + "\n\nThanks."
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert len(chunks) == len(chunk_markdown(body))
    assert chunks[-1][1].endswith("Thanks.")
    assert estimate_tokens(chunks[-1][1]) <= CHUNK_MAX_TOKENS


def test_a_short_opening_is_not_left_on_its_own() -> None:
    text = "# 标题\n\n导语。\n\n" + "\n\n".join(_zh_paragraph(index) for index in range(8))
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert chunks[0][1].startswith("# 标题\n\n导语。\n\n第0段")
    assert all(estimate_tokens(chunk_text) >= CHUNK_MIN_TOKENS for _, chunk_text, _, _ in chunks)


def test_only_one_overlong_sentence_is_cut_inside_and_within_the_hard_maximum() -> None:
    sentence = "规则" * 1_500 + "，" + "学生" * 400 + "。"
    text = _zh_paragraph(1, sentences=3) + "\n\n" + sentence
    chunks = chunk_markdown(text)
    _assert_lossless(text, chunks)
    assert all(estimate_tokens(chunk_text) <= CHUNK_MAX_TOKENS for _, chunk_text, _, _ in chunks)
    whole = [chunk_text for _, chunk_text, _, _ in chunks if SENTENCE_END.search(chunk_text)]
    assert whole[0].startswith("第1段")


def test_new_mock_index_and_new_builds_use_the_current_chunker() -> None:
    text = "\n\n".join(_en_paragraph(index) for index in range(12))
    assert [(item.index, item.text) for item in build_chunks(text)] == [
        (index, chunk_text) for index, chunk_text, _, _ in chunk_markdown(text)
    ]
    build = prepare_snapshot_build(
        agent_version_id="version-1",
        knowledge_snapshot_id="snapshot-1",
        draft_revision=1,
        persona_spec_hash="persona",
        documents=[{"document_id": "document-1", "source_filename": "lesson.md", "text": text}],
    )
    assert build.chunking_version == CHUNKING_VERSION
    assert build.canonical_manifest["chunking_version"] == "markdown-structure-600t-v3"
    assert len(build.chunks) == len(chunk_markdown(text))


# Synthetic text; the digest was taken from origin/main's chunker (8b6c5ae).
LEGACY_SAMPLE = (
    "# Lesson\n\n"
    + "\n\n".join(f"Paragraph {index} " + "word " * 90 for index in range(12))
    + "\n\n## 第二部分\n\n"
    + "儒家强调仁爱。" * 300
    + "\n\n"
    + "tail " * 50
)
LEGACY_DIGEST = "e233d272d9b2c9b40d9098523275d6fb90a50e3c9af5ba8e527bacc7b21c50cf"


def test_the_legacy_chunker_is_byte_for_byte_unchanged() -> None:
    rows = chunk_markdown(LEGACY_SAMPLE, LEGACY_CHUNKING_VERSION)
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()
    assert digest == LEGACY_DIGEST


def test_a_legacy_build_still_verifies_against_its_own_sources() -> None:
    documents = [
        {"document_id": "document-1", "source_filename": "lesson.md", "text": LEGACY_SAMPLE}
    ]
    build = prepare_snapshot_build(
        agent_version_id="version-1",
        knowledge_snapshot_id="snapshot-legacy",
        draft_revision=1,
        persona_spec_hash="persona",
        documents=documents,
        chunking_version=LEGACY_CHUNKING_VERSION,
    )
    assert [chunk.text for chunk in build.chunks] == [
        text for _, text, _, _ in chunk_markdown(LEGACY_SAMPLE, LEGACY_CHUNKING_VERSION)
    ]
    # Verification re-chunks with the build's own chunker, so a frozen v2
    # build does not drift because the default chunker changed.
    assert_snapshot_build_current(build, current_documents=documents)


def test_an_unknown_chunker_is_refused() -> None:
    with pytest.raises(ValueError):
        chunk_markdown("text", "markdown-unknown-v9")
    with pytest.raises(SnapshotBuildError):
        prepare_snapshot_build(
            agent_version_id="version-1",
            knowledge_snapshot_id="snapshot-1",
            draft_revision=1,
            persona_spec_hash="persona",
            documents=[{"document_id": "d", "source_filename": "a.md", "text": "text"}],
            chunking_version="markdown-unknown-v9",
        )
