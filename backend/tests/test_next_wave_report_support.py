"""Focused v2 Report projections for full 2–5-round segment Debates."""

from __future__ import annotations

import json as jsonlib
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from app.modules.reports.real_provider import REAL_REPORT_MODEL, RealReportProvider
from app.modules.reports.real_schema import (
    REPORT_SECTION_FIELDS,
    ReportBoundaryError,
    ReportRequestV2,
    validate_report_request,
)
from app.modules.reports.schemas import (
    ManifestBarrage,
    ManifestInsight,
    ManifestParticipant,
    ManifestReply,
    ManifestTurnSourceV2,
    ManifestTurnV2,
    ManifestVote,
    ReportInputManifestV2,
    ReportSectionOutput,
)
from app.modules.reports.service import (
    ReportBarrageContext,
    ReportContext,
    ReportReplyContext,
    ReportSourceContext,
    ReportTurnContext,
    build_real_report_request,
)
from app.providers.llm_adapter import DashScopeLLMConfig
from app.providers.llm_tokenizer import PinnedLLMTokenizer
from app.providers.llm_transport import LLMTransportResponse


def _uid(number: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{number:012d}")


def _hash(letter: str) -> str:
    return letter * 64


class _Tokenizer(PinnedLLMTokenizer):
    def __init__(self) -> None:
        super().__init__("next-wave-report-tokenizer", _hash("b"), lambda value: len(value.split()))


class _Transport:
    def __init__(self) -> None:
        self.calls = 0
        self.payload: Mapping[str, object] | None = None

    def post(
        self,
        _url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: object,
    ) -> LLMTransportResponse:
        del headers, timeout
        self.calls += 1
        self.payload = json
        return LLMTransportResponse(
            200,
            {
                "object": "chat.completion",
                "model": REAL_REPORT_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": jsonlib.dumps(
                                {
                                    field: f"A careful English section about {field}."
                                    for field in REPORT_SECTION_FIELDS
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 100,
                    "total_tokens": 200,
                },
            },
        )


def _context(*, with_barrages: bool = True) -> ReportContext:
    participants = [
        ManifestParticipant(
            participant_id=_uid(100 + index),
            slot=cast(Any, chr(65 + index)),
            order_index=index,
            agent_name=f"Agent {chr(65 + index)}",
            stance_mode="open",
            initial_stance=None,
            current_stance=None,
        )
        for index in range(5)
    ]
    source_rows: list[ManifestTurnSourceV2] = []
    source_context: list[ReportSourceContext] = []
    turns: list[ManifestTurnV2] = []
    turn_context: list[ReportTurnContext] = []
    for turn_index in range(25):
        participant = participants[turn_index % 5]
        round_no = turn_index // 5 + 1
        used_ids = [f"evidence-{turn_index}-{rank}" for rank in range(6)]
        turns.append(
            ManifestTurnV2(
                turn_id=_uid(200 + turn_index),
                participant_id=participant.participant_id,
                round_no=round_no,
                turn_index=turn_index,
                text_hash=_hash("c"),
                used_evidence_ids=used_ids,
            )
        )
        speech = (
            f"Round {round_no} paragraph {turn_index} records the winner wording as quoted "
            "classroom material and keeps its uncertainty visible."
        )
        turn_context.append(
            ReportTurnContext(
                turn_id=_uid(200 + turn_index),
                participant_id=participant.participant_id,
                participant_name=participant.agent_name,
                round_no=round_no,
                turn_index=turn_index,
                speech=speech,
                used_evidence_ids=tuple(used_ids),
            )
        )
        for rank, evidence_id in enumerate(used_ids, start=1):
            source_id = _uid(1000 + turn_index * 6 + rank)
            source_rows.append(
                ManifestTurnSourceV2(
                    turn_source_id=source_id,
                    turn_id=_uid(200 + turn_index),
                    turn_index=turn_index,
                    rank=rank,
                    snapshot_id=_uid(500),
                    chunk_id=_uid(1000 + turn_index * 6 + rank),
                    chunk_content_hash=_hash("d"),
                    source_filename="teaching-source.md",
                    evidence_id=evidence_id,
                )
            )
            source_context.append(
                ReportSourceContext(
                    turn_source_id=source_id,
                    turn_id=_uid(200 + turn_index),
                    turn_index=turn_index,
                    rank=rank,
                    snapshot_id=_uid(500),
                    chunk_id=_uid(1000 + turn_index * 6 + rank),
                    source_filename="teaching-source.md",
                    chunk_text=f"Evidence for round {round_no}, turn {turn_index}, source {rank}.",
                    evidence_id=evidence_id,
                )
            )
    classroom = (
        ReportBarrageContext("B1", 0, "The winner wording is quoted for discussion.")
        if with_barrages
        else None
    )
    barrages = (classroom,) if classroom else ()
    replies = (ReportReplyContext("B1", "A", 20, 0),) if with_barrages else ()
    manifest = ReportInputManifestV2(
        debate_id=_uid(50),
        topic="A **winner** phrase can be quoted without declaring a winner.",
        participants=participants,
        turns=turns,
        turn_sources=source_rows,
        votes=[
            ManifestVote(participant_id=item.participant_id, order_index=item.order_index, count=0)
            for item in participants
        ],
        insight=ManifestInsight(
            snapshot_id=_uid(600), revision=1, included_count=0, filtered_count=0, items=[]
        ),
        classroom_barrages=[
            ManifestBarrage(barrage_id=item.barrage_id, turn_index=item.turn_index, text=item.text)
            for item in barrages
        ],
        replies=[
            ManifestReply(
                barrage_id=item.barrage_id,
                slot=cast(Any, item.slot),
                turn_index=item.turn_index,
                paragraph_index=item.paragraph_index,
            )
            for item in replies
        ],
    )
    return ReportContext(
        debate=SimpleNamespace(
            id=str(_uid(50)),
            topic=manifest.topic,
            output_language="en",
        ),
        manifest=manifest,
        turns=tuple(turn_context),
        sources=tuple(source_context),
        vote_total=0,
        barrage_total=len(barrages),
        classroom_barrages=barrages,
        replies=replies,
        protocol_version="segments_v2",
    )


def test_full_five_by_five_report_request_preserves_sources_and_reply_bindings() -> None:
    request = build_real_report_request(_context())

    assert isinstance(request, ReportRequestV2)
    assert request.protocol_version == "segments_v2"
    assert len(request.participants) == 5
    assert len(request.speeches) == 25
    assert len(request.sources) == 150
    assert len(request.classroom_barrages) == 1
    assert request.replies[0].barrage_id == "B1"
    assert request.replies[0].turn_index == 20
    assert set(request.speeches[-1].used_evidence_ids) == {
        f"evidence-24-{rank}" for rank in range(6)
    }
    payload = request.canonical_json()
    assert "nickname" not in payload.lower()
    assert "winner" in payload.lower()  # authoritative speech text is preserved


def test_v2_report_provider_accepts_actual_envelope_once() -> None:
    transport = _Transport()
    provider = RealReportProvider(
        config=DashScopeLLMConfig(
            api_key="fixture-secret",
            workspace_id="workspace123",
            policy_hash=_hash("e"),
        ),
        transport=transport,
        tokenizer=_Tokenizer(),
    )
    request = build_real_report_request(_context())
    prepared = provider.build_request(request)
    result = provider.execute_prepared(prepared)

    assert isinstance(result, ReportSectionOutput)
    assert prepared.prompt_contract_version == "real_report_prompt_v2"
    assert transport.calls == 1
    assert transport.payload is not None
    messages = cast(list[dict[str, str]], transport.payload["messages"])
    assert "segments_v2" in messages[1]["content"]
    assert "classroom_barrages" in messages[1]["content"]
    assert "replies" in messages[1]["content"]


def test_empty_v2_barrage_pool_has_no_reply_claim() -> None:
    request = build_real_report_request(_context(with_barrages=False))

    assert isinstance(request, ReportRequestV2)
    assert request.classroom_barrages == ()
    assert request.replies == ()
    canonical = cast(dict[str, object], jsonlib.loads(request.canonical_json()))
    assert canonical["classroom_barrages"] == []
    assert canonical["replies"] == []


@pytest.mark.parametrize(
    "value",
    (
        "The winner and **formatting** are quoted classroom material.",
        "A report can discuss a winner without declaring one.",
    ),
)
def test_v2_authoritative_public_text_is_allowed(value: str) -> None:
    report = build_real_report_request(_context())
    payload = report.model_dump(mode="json")
    payload["topic"] = value
    assert isinstance(validate_report_request(payload), ReportRequestV2)


def test_v2_accepts_authored_text_but_rejects_unknown_reply_input() -> None:
    report = build_real_report_request(_context()).model_dump(mode="json")
    report["classroom_barrages"][0]["text"] = "student@example.com"  # type: ignore[index]
    assert isinstance(validate_report_request(report), ReportRequestV2)

    report = build_real_report_request(_context()).model_dump(mode="json")
    report["replies"][0]["barrage_id"] = "B9"  # type: ignore[index]
    with pytest.raises(ReportBoundaryError, match="report_reply_not_available"):
        validate_report_request(report)


def test_full_report_preserves_prose_and_server_citation_projection():
    from app.modules.reports.schemas import ReportSectionOutput
    from app.modules.reports.service import render_real_report_markdown, validate_report_markdown

    context = _context(with_barrages=False)
    sections = ReportSectionOutput(
        **{
            field: "Evidence supports careful classroom reflection and respectful questions. " * 8
            for field in REPORT_SECTION_FIELDS
        }
    )
    markdown = render_real_report_markdown(context, sections)
    assert "[evidence:evidence-24-5]" in markdown
    assert (
        1
        <= validate_report_markdown(
            markdown, manifest=context.manifest, vote_total=0, barrage_total=0
        )
        <= 900
    )
    assert (
        validate_report_markdown(
            markdown + " [evidence:invented-source]",
            manifest=context.manifest,
            vote_total=0,
            barrage_total=0,
        )
        > 0
    )


def test_short_segment_report_keeps_prose_without_padding_or_internal_copy():
    from app.modules.reports.schemas import ReportSectionOutput
    from app.modules.reports.service import render_real_report_markdown, validate_report_markdown

    context = _context(with_barrages=False)
    sections = ReportSectionOutput(
        **{
            field: f"The {field.replace('_', ' ')} follows the recorded discussion."
            for field in REPORT_SECTION_FIELDS
        }
    )
    markdown = render_real_report_markdown(context, sections)
    count = validate_report_markdown(
        markdown, manifest=context.manifest, vote_total=0, barrage_total=0
    )
    assert 0 < count < 600
    for value in sections.model_dump().values():
        assert markdown.count(value) == 1
    assert "This record supports careful comparison" not in markdown
    assert "code-owned" not in markdown
    assert "persisted paragraph reply binding" not in markdown
    assert "Classroom totals: 0 votes and 0 messages." in markdown
