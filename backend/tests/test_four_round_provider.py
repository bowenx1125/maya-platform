"""Offline provider boundaries and the single shared four-round repair budget."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.modules.debates.generation.segments import SegmentInputSnapshot
from app.modules.debates.generation.segments_runtime import SegmentLLMRuntime
from app.providers.control import InMemoryProviderOperationRepository, ProviderScopeBudgetV1
from app.providers.llm_adapter import LLMAdapterError, LLMUsageV1
from app.providers.llm_price_card import LLMPriceCardV1
from app.providers.llm_privacy import (
    LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS,
    LLMOutboundManifestV1,
    LLMOutboundPrivacyError,
    scan_segment_outbound_messages,
)
from app.providers.llm_segments import (
    FOUR_ROUND_SEGMENT_PROMPT_VERSION,
    SEGMENT_PROMPT_VERSION,
    SegmentAcceptedCandidateV2,
    SegmentLLMAdapter,
    SegmentLLMRequestV2,
    SegmentMessageV2,
    segment_prompt_version,
)

from tests.test_segments_protocol import _context, _persona, _snapshot

PUBLIC_ID = "00000000-0000-4000-8000-a13800138000"
OTHER_ID = "00000000-0000-4000-8000-b13800138000"


def snapshot() -> SegmentInputSnapshot:
    return SegmentInputSnapshot.from_groups(
        topic="How can classroom evidence improve a shared decision?",
        language="en",
        round_number=1,
        round_total=4,
        persona=_persona(),
        snapshot_id="snapshot-0",
        discussion={
            "protocol": "four_round_v1",
            "self_id": PUBLIC_ID,
            "agents": [{"id": PUBLIC_ID, "name": "River"}, {"id": OTHER_ID, "name": "Forest"}],
            "question_target_id": None,
            "received_questions": [],
            "memories": [],
        },
    )


def manifest() -> LLMOutboundManifestV1:
    return LLMOutboundManifestV1(
        field_classes=(
            *LLMOutboundManifestV1().field_classes,
            LLM_SESSION_DISCUSSION_MEMORY_FIELD_CLASS,
        )
    )


def adapter() -> SegmentLLMAdapter:
    return SegmentLLMAdapter(
        SimpleNamespace(resolved_endpoint="https://offline.invalid/segments"),
        outbound_manifest=manifest(),
        price_card=price_card(),
    )


def price_card() -> LLMPriceCardV1:
    return LLMPriceCardV1(
        input_price_per_million="1",
        cached_input_price_per_million="1",
        output_price_per_million="1",
        retrieved_at="2026-09-08T00:00:00Z",
        source_content_sha256="d" * 64,
    )


def scan(payload: dict[str, object], *, classes: tuple[str, ...] | None = None) -> None:
    scan_segment_outbound_messages(
        (
            SegmentMessageV2("system", "Use only the provided data."),
            SegmentMessageV2("user", json.dumps(payload)),
        ),
        field_classes=classes if classes is not None else manifest().field_classes,
    )


def test_discussion_text_is_authored_data_but_unlisted_fields_stay_closed():
    payload = snapshot().to_user_payload()
    scan(payload)
    authored = {
        **payload,
        "discussion": {
            **payload["discussion"],
            "received_questions": [{"from_id": OTHER_ID, "text": PUBLIC_ID}],
            "agents": [
                {"id": PUBLIC_ID, "name": PUBLIC_ID},
                {"id": OTHER_ID, "name": "Forest"},
            ],
        },
    }
    scan(authored)
    unknown = {
        **payload,
        "discussion": {**payload["discussion"], "student_id": PUBLIC_ID},
    }
    with pytest.raises(LLMOutboundPrivacyError):
        scan(unknown)
    with pytest.raises(LLMOutboundPrivacyError) as error:
        scan(payload, classes=LLMOutboundManifestV1().field_classes)
    assert error.value.code == "llm_discussion_manifest_missing"


def test_four_round_wire_requires_explicit_field_consent_and_versions_recovery():
    frozen = snapshot()
    blocked = SegmentLLMAdapter(
        SimpleNamespace(resolved_endpoint="https://offline.invalid/segments"),
        outbound_manifest=LLMOutboundManifestV1(),
    )
    with pytest.raises(LLMAdapterError) as error:
        blocked.build_request(frozen)
    assert error.value.code == "llm_discussion_manifest_missing"
    request = adapter().build_request(frozen)
    assert request.prompt_contract_version == FOUR_ROUND_SEGMENT_PROMPT_VERSION
    assert segment_prompt_version(_snapshot()) == SEGMENT_PROMPT_VERSION
    assert json.loads(request.user_message.content)["discussion"]["self_id"] == PUBLIC_ID
    assert "320 words" in request.system_message.content
    assert set(request.body["response_format"]["json_schema"]["schema"]["properties"]) == {
        "segments",
        "question",
        "discussion_memory",
    }


def output(words: int) -> dict[str, object]:
    return {
        "segments": [
            {
                "text": " ".join(["evidence"] * words),
                "source_ids": [],
                "reply_to": None,
                "support_mode": "no_match",
            }
        ],
        "question": None,
        "discussion_memory": None,
    }


def opening_context():
    previous = _context()
    return replace(
        previous,
        turn=replace(previous.turn, round_no=1, turn_index=0),
        predecessors=(),
        round_count=4,
        turn_protocol="segments_v2",
        teaching_protocol="four_round_v1",
    )


class OfflineAdapter(SegmentLLMAdapter):
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        super().__init__(
            SimpleNamespace(resolved_endpoint="https://offline.invalid/segments"),
            outbound_manifest=manifest(),
            price_card=price_card(),
        )
        self.outputs = outputs
        self.requests: list[SegmentLLMRequestV2] = []

    def send_accepted(self, request: SegmentLLMRequestV2) -> SegmentAcceptedCandidateV2:
        value = self.outputs[len(self.requests)]
        self.requests.append(request)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return SegmentAcceptedCandidateV2(
            request=request,
            http_status=200,
            finish_reason="stop",
            usage=LLMUsageV1(1, 0, 1, 2),
            output_json=raw,
            output_hash=hashlib.sha256(raw.encode()).hexdigest(),
            provider_output=value,
        )


@pytest.mark.parametrize("repair_success", [True, False])
def test_structure_repair_uses_frozen_rules_and_completed_output_is_reused(
    repair_success,
):
    from dataclasses import replace

    from app.modules.debates.teaching_rules import compile_system_prompt

    frozen = replace(
        snapshot(), frozen_system_prompt=compile_system_prompt("# Per-lesson repair rule", 1, "en")
    )
    second = output(65) if repair_success else {"segments": []}
    provider = OfflineAdapter([{"segments": []}, second])
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=4,
            max_total_tokens=200_000,
            max_cost_cny=5,
            budget_bucket="llm_debate_turn",
        )
    )
    runtime = SegmentLLMRuntime(ledger=ledger, adapter=provider)
    prepared = runtime.prepare(
        frozen,
        debate_id="debate-1",
        turn_id="turn-1",
        policy_hash="a" * 64,
        manifest_hash="b" * 64,
        build_manifest_hash="c" * 64,
    )
    context = opening_context()
    result = runtime.run(prepared, context=context, confirmed=True)
    assert len(provider.requests) == 2
    assert [request.attempt_no for request in provider.requests] == [1, 2]
    assert provider.requests[1].retrieval_reused
    assert provider.requests[1].system_message.content.startswith(
        provider.requests[0].system_message.content
    )
    assert "# Per-lesson repair rule" in provider.requests[0].system_message.content
    assert provider.requests[0].user_message.content == provider.requests[1].user_message.content
    assert '"code":"segment_count_invalid"' in provider.requests[1].system_message.content
    assert result.status == ("succeeded" if repair_success else "failed")
    if repair_success:
        resumed = runtime.resume_accepted_stage(result.stage, snapshot=frozen, context=context)
        assert resumed.status == "succeeded"
        assert len(provider.requests) == 2


def test_one_attempt_manifest_accepts_long_speech_without_length_repair():
    frozen = snapshot()
    provider = OfflineAdapter([output(101)])
    provider.outbound_manifest = LLMOutboundManifestV1(
        field_classes=manifest().field_classes,
        max_attempts=1,
        repair_policy_version=None,
        repair_policy_hash=None,
    )
    ledger = InMemoryProviderOperationRepository(
        default_budget=ProviderScopeBudgetV1(
            max_requests=1,
            max_total_tokens=100_000,
            max_cost_cny=5,
            budget_bucket="llm_debate_turn",
        )
    )
    runtime = SegmentLLMRuntime(ledger=ledger, adapter=provider)
    prepared = runtime.prepare(
        frozen,
        debate_id="debate-1",
        turn_id="turn-1",
        policy_hash="a" * 64,
        manifest_hash="b" * 64,
        build_manifest_hash="c" * 64,
    )
    context = opening_context()
    result = runtime.run(prepared, context=context, confirmed=True)
    assert result.status == "succeeded"
    assert result.safe_error_code is None
    assert len(provider.requests) == 1
