from dataclasses import replace

import pytest
from app.modules.reports.real_prompt import build_report_request
from app.modules.reports.real_schema import ReportBoundaryError, validate_report_request
from app.modules.reports.schemas import ReportDiscussionMemory
from app.modules.reports.service import build_real_report_request
from app.providers.llm_adapter import DashScopeLLMConfig

from tests.test_next_wave_report_support import _context, _price_card, _Tokenizer


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
        price_card=_price_card(),
    )
    assert "not as independent factual evidence" in wire.system_message.content
    assert "A local record cannot establish a universal rule." in wire.user_message.content


def test_memory_projection_rejects_unknown_agents_and_private_text():
    request = build_real_report_request(replace(_context(), discussion_memories=(_memory(),)))
    payload = request.canonical_payload()
    payload["discussion_memories"][0]["reason"] = "student email: student@example.com"
    with pytest.raises(ReportBoundaryError):
        validate_report_request(payload)
    payload = request.canonical_payload()
    payload["discussion_memories"].append(payload["discussion_memories"][0])
    with pytest.raises(ReportBoundaryError, match="report_memory_projection"):
        validate_report_request(payload)


def test_report_manifest_hash_binds_memory_and_keeps_absent_memory_compatible():
    manifest = _context().manifest
    original = manifest.canonical_payload()
    assert "discussion_memories" not in original
    with_memory = type(manifest).model_validate({**original, "discussion_memories": [_memory()]})
    assert with_memory.input_hash() != manifest.input_hash()
    assert with_memory.canonical_payload()["discussion_memories"][0]["slot"] == "A"
