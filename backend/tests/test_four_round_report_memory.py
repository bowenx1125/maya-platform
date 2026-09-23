import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest
from app.core.errors import PlatformError
from app.modules.debates.final_input import read_final_input
from app.modules.debates.models import Debate
from app.modules.reports.real_prompt import build_report_request
from app.modules.reports.real_schema import ReportBoundaryError, validate_report_request
from app.modules.reports.schemas import ReportDiscussionMemory
from app.modules.reports.service import build_real_report_request
from app.providers.llm_adapter import DashScopeLLMConfig

from tests.test_next_wave_report_support import _context, _Tokenizer


def _memory() -> ReportDiscussionMemory:
    return ReportDiscussionMemory(
        slot="A",
        position="I retain the claim with an explicit boundary.",
        change="qualified",
        reason="The dated record covers only one case.",
        influence={"slot": "B", "point": "A local record cannot establish a universal rule."},
        unresolved_question="Does another independent record support this boundary?",
    )


def test_discussion_memory_reaches_report_prompt_without_changing_public_speech():
    context = _context()
    enriched = replace(context, discussion_memories=(_memory(),))
    request = build_real_report_request(enriched)
    assert request.speeches == build_real_report_request(context).speeches
    assert request.discussion_memories == (_memory(),)
    assert "discussion_memories" in request.canonical_payload()
    assert "discussion_memories" not in build_real_report_request(context).canonical_payload()
    wire = build_report_request(
        request,
        config=DashScopeLLMConfig(api_key="fixture", workspace_id="fixture-workspace"),
        tokenizer=_Tokenizer(),
    )
    assert "not as independent factual evidence" in wire.system_message.content
    assert "A local record cannot establish a universal rule." in wire.user_message.content


def test_memory_projection_accepts_authored_text_but_rejects_unknown_agents():
    request = build_real_report_request(replace(_context(), discussion_memories=(_memory(),)))
    payload = request.canonical_payload()
    payload["discussion_memories"][0]["reason"] = "student email: student@example.com"
    assert (
        validate_report_request(payload)
        .discussion_memories[0]
        .reason.endswith("student@example.com")
    )
    payload = request.canonical_payload()
    payload["discussion_memories"].append(payload["discussion_memories"][0])
    with pytest.raises(ReportBoundaryError, match="report_memory_projection"):
        validate_report_request(payload)


def test_report_preserves_source_urls_evidence_and_classroom_text():
    context = _context()
    source = replace(
        context.sources[0],
        chunk_text="A dated record supports this point. https://example.org/research",
    )
    enriched = replace(context, sources=(source, *context.sources[1:]))
    request = build_real_report_request(enriched)
    assert request.sources[0].excerpt == source.chunk_text
    assert (
        request.sources[0].evidence_id == build_real_report_request(context).sources[0].evidence_id
    )
    assert request.speeches == build_real_report_request(context).speeches
    assert enriched.sources[0].chunk_text.endswith("https://example.org/research")


def test_report_manifest_hash_binds_memory_and_keeps_absent_memory_compatible():
    manifest = _context().manifest
    original = manifest.canonical_payload()
    assert "discussion_memories" not in original
    with_memory = type(manifest).model_validate({**original, "discussion_memories": [_memory()]})
    assert with_memory.input_hash() != manifest.input_hash()
    assert with_memory.canonical_payload()["discussion_memories"][0]["slot"] == "A"


def test_report_keeps_frozen_final_input_after_replay_release_but_live_fence_stays_strict():
    frozen = json.dumps({"version": "final_input_v1", "generation": 0, "language": "en"})
    debate = SimpleNamespace(
        final_input_json=frozen,
        final_input_hash=hashlib.sha256(frozen.encode()).hexdigest(),
        cancellation_generation=1,
        output_language="en",
        status="completed",
    )
    assert read_final_input(cast(Debate, debate))["generation"] == 0
    debate.status = "running"
    with pytest.raises(PlatformError):
        read_final_input(cast(Debate, debate))


def test_report_keeps_long_rag_evidence_intact_in_actual_provider_input():
    context = _context()
    long_evidence = "Evidence about the shared classroom record. " * 110
    assert len(long_evidence) > 4400
    enriched = replace(
        context,
        sources=tuple(
            replace(source, chunk_text=long_evidence) if index < 6 else source
            for index, source in enumerate(context.sources)
        ),
    )
    request = build_real_report_request(enriched)
    assert all(source.excerpt == long_evidence for source in request.sources[:6])
    wire = build_report_request(
        request,
        config=DashScopeLLMConfig(api_key="offline-test", workspace_id="offline-workspace"),
        tokenizer=_Tokenizer(),
    )
    assert long_evidence in wire.user_message.content
