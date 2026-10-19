"""Round-4 echo, raw report citations, CJK length and the detail report status."""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.modules.debates.generation.segments import (
    SegmentInputSnapshot,
    SegmentProtocolError,
    load_segment_turn_result,
    strip_history_copies,
    validate_segment_output,
)
from app.modules.debates.generation.segments_runtime import SEGMENT_REPAIR_CODES
from app.modules.reports.models import CivilizationReportRevision
from app.modules.reports.service import (
    display_report_markdown,
    download_current_report,
    list_report_revisions,
    process_insight_job,
    process_report_job,
    report_word_count,
)
from app.providers.llm_segments import SEGMENT_NO_HISTORY_COPY_RULE
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_segments_protocol import _persona, _receipt
from tests.test_wave3_reports import TEACHER_ID, _finalize_interaction

# Debate 44889ff6 on prod: 照耀's round-3 speech, then its round-4 output that
# began with that speech word for word, followed by 红樱桃's round-4 speech.
ROUND3_ZHAOYAO = (
    "我感觉：红樱桃问得好。背诵精简事实确实违背了验证逻辑。资料要求“写清出处”，"
    "意在让使用者能追溯并检验证据来源，而非单纯记忆结论。\n\n"
    "我感觉：若学生只记住“短、具体”的事实却不知其出处和适用边界，就无法判断该证据是否"
    "支持当前结论。这种高分只是应试技巧，非真学会。"
)
ROUND4_HONGYINGTAO = (
    "RAG证实，平台选用智能体看重的是公开性与Markdown源的规范性。这直接说明评价体系关注的是"
    "资源是否可被验证和调用，而非单纯的分数高低。"
)


def _snapshot(history: tuple[dict[str, Any], ...]) -> SegmentInputSnapshot:
    return SegmentInputSnapshot.from_groups(
        topic="考试得了好成绩，就说明真正学会了吗？",
        language="zh",
        round_number=3,
        round_total=3,
        persona=_persona(),
        history=history,
        receipts=(_receipt("snapshot-0", "chunk-a", "资料要短、具体，写清楚事实、数字和出处。"),),
        barrages=(),
        snapshot_id="snapshot-0",
    )


HISTORY = (
    {"speaker": "照耀", "round": 2, "text": ROUND3_ZHAOYAO},
    {"speaker": "红樱桃", "round": 2, "text": ROUND4_HONGYINGTAO},
)


def test_a_turn_that_only_re_reads_history_is_a_repairable_failure() -> None:
    assert "segment_history_copy" in SEGMENT_REPAIR_CODES
    output = {
        "segments": [
            {
                "text": ROUND3_ZHAOYAO,
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            },
            {
                "text": ROUND4_HONGYINGTAO,
                "source_ids": ["S1"],
                "reply_to": None,
                "support_mode": "direct",
            },
        ]
    }
    with pytest.raises(SegmentProtocolError) as caught:
        validate_segment_output(output, _snapshot(HISTORY))
    assert caught.value.code == "segment_history_copy"
    # The repair attempt never loses the turn over it.
    kept = validate_segment_output(output, _snapshot(HISTORY), allow_history_copy=True)
    assert kept.speech.startswith("我感觉：红樱桃问得好。")


def test_copied_sentences_are_removed_and_new_ones_kept() -> None:
    fresh = (
        "我修改了判断：高分只有在学生能把证据迁移到新题时才说明学会，这是我从首轮到现在增加的条件。"
    )
    output = {
        "segments": [
            {
                "text": ROUND3_ZHAOYAO + fresh,
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            },
            {
                "text": "RAG证实，资料要短、具体，写清楚事实、数字和出处。",
                "source_ids": ["S1"],
                "reply_to": None,
                "support_mode": "direct",
            },
        ]
    }
    result = validate_segment_output(output, _snapshot(HISTORY))
    assert result.speech == fresh + "\n\nRAG证实，资料要短、具体，写清楚事实、数字和出处。"
    assert "红樱桃问得好" not in result.speech
    assert [item.support_mode for item in result.segments] == ["no_match", "direct"]
    # Lineage offsets still point into the published speech.
    for row in result.lineage:
        assert result.speech[row.start_offset : row.end_offset] == row.text
    # A stored result reloads to the same speech.
    reloaded = load_segment_turn_result(result.as_stored_payload(), _snapshot(HISTORY))
    assert reloaded.speech == result.speech


def test_short_acknowledgements_and_first_round_text_are_untouched() -> None:
    keys = ("照耀问得好。背诵不等于理解。",)
    assert strip_history_copies("照耀问得好。我补充一个新的适用条件。", keys) == (
        "照耀问得好。我补充一个新的适用条件。"
    )
    assert strip_history_copies(ROUND3_ZHAOYAO, ()) == ROUND3_ZHAOYAO
    snapshot = _snapshot(())
    output = {
        "segments": [
            {"text": ROUND3_ZHAOYAO, "source_ids": [], "reply_to": None, "support_mode": "no_match"}
        ]
    }
    assert validate_segment_output(output, snapshot).speech == ROUND3_ZHAOYAO


def test_english_copies_are_detected_across_whitespace_changes() -> None:
    history = ("The record places the jars on the east terrace, near the old gate.",)
    from app.modules.debates.generation.segments import _copy_key

    text = "The record  places the jars on the east terrace,\nnear the old gate. I ask why."
    assert strip_history_copies(text, tuple(_copy_key(item) for item in history)) == ""
    text = (
        "The record places the jars on the east terrace, near the old gate. "
        "My new point is that the location reflects a seasonal drainage practice we have not "
        "discussed yet."
    )
    assert strip_history_copies(text, tuple(_copy_key(item) for item in history)) == (
        "My new point is that the location reflects a seasonal drainage practice we have not "
        "discussed yet."
    )


def test_the_send_time_rule_forbids_verbatim_history() -> None:
    assert "word for word" in SEGMENT_NO_HISTORY_COPY_RULE
    assert "your own earlier speeches" in SEGMENT_NO_HISTORY_COPY_RULE


def test_chinese_report_length_counts_characters_not_latin_words() -> None:
    markdown = (
        "# 文明互鉴报告\n\n## 辩论概览\n\n"
        "本场辩论围绕分数展开 [evidence:evidence-1]。RAG 资料 2 条。"
    )
    # 文明互鉴报告(6) 辩论概览(4) 本场辩论围绕分数展开(10) 资料(2) 条(1) + RAG, 2
    assert report_word_count(markdown) == 23 + 2
    assert report_word_count("Evidence supports careful reflection [evidence:x].") == 4


def _manifest(sources: list[dict[str, Any]]) -> str:
    return json.dumps({"manifest_version": "report_input_manifest_v2", "turn_sources": sources})


def test_display_numbers_citations_and_lists_sources(monkeypatch) -> None:
    from app.modules.reports import service

    class _Source:
        def __init__(self, turn_source_id: str, evidence_id: str, name: str, turn: int) -> None:
            self.turn_source_id = turn_source_id
            self.evidence_id = evidence_id
            self.source_filename = name
            self.turn_index = turn

    class _Manifest:
        turn_sources = [
            _Source("ts-1", "evidence-aaa", "guide.md", 0),
            _Source("ts-2", "evidence-bbb", "rules.md", 3),
        ]

    monkeypatch.setattr(service, "_load_report_manifest", lambda value: _Manifest())
    markdown = (
        "# 文明互鉴报告\n\n## 证据与论点\n\n引用指南 [evidence:evidence-aaa]。 "
        "第4次发言的RAG资料：[evidence:evidence-bbb] [evidence:evidence-aaa]。"
        "未知 [evidence:evidence-zzz] 来源。"
    )
    shown = display_report_markdown(markdown, "{}")
    assert "[evidence:" not in shown
    assert "引用指南 [1]。" in shown
    assert "第4次发言的RAG资料：[2][1]。" in shown
    assert "未知 来源。" in shown
    assert shown.endswith("## 资料来源\n\n1. guide.md（第1次发言）\n2. rules.md（第4次发言）\n")
    # Unreadable manifests still never show raw tokens.
    monkeypatch.setattr(
        service, "_load_report_manifest", lambda value: (_ for _ in ()).throw(ValueError())
    )
    assert "[evidence:" not in display_report_markdown(markdown, "{}")
    assert display_report_markdown("plain", None) == "plain"


def test_detail_status_history_count_and_download_follow_the_saved_report(app_factory):
    from app.modules.debates.setup.service import _classroom_statuses

    app, database, settings = app_factory()
    settings.classroom_public_base_url = "http://192.168.1.25:8080"
    with TestClient(app):
        debate_id, snapshot_id = _finalize_interaction(database, settings)
        with database.session() as db:
            process_insight_job(db, snapshot_id)
            revision = db.scalar(
                select(CivilizationReportRevision).where(
                    CivilizationReportRevision.debate_id == debate_id
                )
            )
            assert revision is not None
            revision_id = revision.id
            assert _classroom_statuses(db, debate_id)["report_status"] == "generating"
            db.commit()
        with database.session() as db:
            process_report_job(db, revision_id)
            db.commit()
        with database.session() as db:
            # The detail used to hard-code not_started next to a ready Version 1.
            assert _classroom_statuses(db, debate_id) == {
                "interaction_status": "finalized",
                "insight_status": "ready",
                "report_status": "ready",
            }
            ready = db.get(CivilizationReportRevision, revision_id)
            assert ready is not None and ready.english_markdown
            # A revision saved before CJK counting reads its real length.
            ready.english_markdown = (
                "# 文明互鉴报告\n\n本场辩论围绕分数展开 [evidence:evidence-1]。"
            )
            ready.word_count = 3
            db.commit()
        with database.session() as db:
            rows = list_report_revisions(db, actor_user_id=TEACHER_ID, debate_id=debate_id)
            assert rows[0].word_count == 16
            content, _filename = download_current_report(
                db, actor_user_id=TEACHER_ID, debate_id=debate_id
            )
            assert "[evidence:" not in content
        with database.session() as db:
            assert _classroom_statuses(db, "missing-debate") == {
                "interaction_status": "closed",
                "insight_status": "not_started",
                "report_status": "not_started",
            }


def test_debate_detail_reads_statuses_instead_of_hard_coding_them() -> None:
    import inspect

    from app.modules.debates.setup import service as setup_service

    source = inspect.getsource(setup_service)
    assert '"report_status": "not_started",' not in source


def test_the_spoken_round_two_question_is_never_stripped() -> None:
    question = "你强调资料要“短、具体”，若学生仅靠背诵得高分，这算真学会吗？"
    history = ({"speaker": "照耀", "round": 2, "text": "我先回应。" + question},)
    output = {
        "segments": [
            {
                "text": "我补充一个新的条件：能迁移到新题才算学会，这一点之前没人提出。" + question,
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ],
        "question": {"target_agent_id": "agent-x", "text": question},
    }
    result = validate_segment_output(output, _snapshot(history))
    assert question in result.speech
