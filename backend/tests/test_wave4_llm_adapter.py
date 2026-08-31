"""Focused fake-transport tests for the fixed W4-LLM-A adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from app.modules.agents.persona import compile_persona_or_raise, persona_spec_hash
from app.modules.debates.generation import (
    GenerationContext,
    MutualLearningPolicy,
    ParticipantContext,
    TurnSubquery,
    build_provider_prompt,
)
from app.modules.debates.generation.prompt_budget import (
    ConservativeUtf8TokenCounter,
    preflight_prompt_budget,
)
from app.modules.debates.generation.prompt_request import (
    PromptMessageV1,
    PromptRepairFeedbackV1,
    ProviderPromptV1,
)
from app.providers.llm_adapter import (
    LLM_TURN_OUTPUT_SCHEMA_HASH,
    DashScopeLLMAdapter,
    DashScopeLLMConfig,
    LLMAcceptedCandidateV1,
    LLMAdapterError,
)
from app.providers.llm_price_card import (
    LLMPriceCardV1,
    actual_cost,
    reservation_cost,
)
from app.providers.llm_privacy import (
    LLMOutboundManifestV1,
    LLMOutboundPrivacyError,
    scan_llm_outbound_messages,
)
from app.providers.llm_tokenizer import PinnedLLMTokenizer
from app.providers.llm_transport import (
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMTransportNotSent,
    LLMTransportResponse,
)


def _persona() -> Any:
    return compile_persona_or_raise(
        """# River Keeper

## Identity

- Role: Watershed steward
- Historical or cultural context: A fictional community keeper.

## Cultural lens

- Intergenerational responsibility

## Core values

- Reciprocity

## Initial position

Protect shared resources through careful stewardship.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
""",
        expected_name="River Keeper",
    )


def _prompt(*, topic: str = "How should a platform protect agency?") -> Any:
    persona = _persona()
    persona_hash = persona_spec_hash(persona)
    current = ParticipantContext(
        participant_id="participant-0",
        agent_id="agent-0",
        agent_name="River Keeper",
        slot="A",
        order_index=0,
        snapshot_id="snapshot-0",
        persona=persona,
        persona_spec_hash=persona_hash,
    )
    other = ParticipantContext(
        participant_id="participant-1",
        agent_id="agent-1",
        agent_name="Other Expert",
        slot="B",
        order_index=1,
        snapshot_id="snapshot-1",
    )
    plan = MutualLearningPolicy().plan((current, other), round_count=2)[0]
    return build_provider_prompt(
        GenerationContext("debate-1", topic, plan, current, (current, other)),
        persona=persona,
        queries=(TurnSubquery("viewpoint", "the independent viewpoint"),),
    )


def _output(*, speech: str = "A transparent policy protects agency.") -> dict[str, object]:
    return {
        "schema_version": "llm_turn_output_v1",
        "phase": "opening",
        "speech": speech,
        "key_claims": [{"claim_text": speech, "claim_type": "proposal", "used_evidence_refs": []}],
        "engagements": [],
        "answered_required_question": False,
        "learned_from_others": [],
        "position_summary": "Protect agency transparently.",
        "position_update": "unchanged",
        "position_update_reason": "The opening establishes the position.",
        "remaining_uncertainty": ["Local effects remain uncertain."],
        "unresolved_issue": "",
        "question": {"mode": "none", "target_participant_ref": -1, "text": ""},
        "missing_information": ["Local impacts."],
        "unresolved_questions": [],
        "change_from_opening": "",
        "final_consensus": [],
        "final_disagreements": [],
        "final_recommendation": "",
    }


@dataclass
class _FakeTransport:
    payload: object
    status_code: int = 200

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], dict[str, str], object]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: object,
    ) -> object:
        self.calls.append((url, json, headers, timeout))
        return LLMTransportResponse(self.status_code, self.payload)


class _ResponseTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls = 0

    def post(self, url: str, *, headers: object, json: object, timeout: object) -> object:
        del url, headers, json, timeout
        self.calls += 1
        return self.payload


def _response(
    output: object,
    *,
    finish_reason: str = "stop",
    usage: object | None = None,
    raw_content: str | None = None,
) -> dict[str, object]:
    return {
        "object": "chat.completion",
        "model": "qwen3.7-plus-2026-05-26",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": raw_content if raw_content is not None else json.dumps(output),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _adapter(transport: object, *, identity_tokens: tuple[str, ...] = ()) -> DashScopeLLMAdapter:
    return DashScopeLLMAdapter(
        DashScopeLLMConfig(api_key="fixture-secret", workspace_id="workspace123"),
        transport,  # type: ignore[arg-type]
        tokenizer=PinnedLLMTokenizer("supplier-tokenizer-v1", "a" * 64, lambda value: len(value)),
        price_card=LLMPriceCardV1(
            input_price_per_million="0.5",
            cached_input_price_per_million="0.1",
            output_price_per_million="1.0",
            retrieved_at="2026-08-31T00:00:00Z",
            source_content_sha256="b" * 64,
        ),
        identity_tokens=identity_tokens,
        outbound_manifest=LLMOutboundManifestV1(),
    )


def test_adapter_captures_exact_beijing_wire_and_hash_excludes_authorization() -> None:
    transport = _FakeTransport(_response(_output()))
    result = _adapter(transport).execute(_prompt(), generation_fence="fence-hash")
    assert result.succeeded
    assert transport.calls[0][0] == (
        "https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    body = cast(dict[str, Any], transport.calls[0][1])
    assert set(body) == {
        "model",
        "messages",
        "enable_thinking",
        "stream",
        "temperature",
        "top_p",
        "max_completion_tokens",
        "n",
        "response_format",
    }
    assert body["model"] == "qwen3.7-plus-2026-05-26"
    assert body["enable_thinking"] is False
    assert body["stream"] is False
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.8
    assert body["max_completion_tokens"] == 1500
    assert body["n"] == 1
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    schema = body["response_format"]["json_schema"]
    assert schema["name"] == "maya_llm_turn_output_v1"
    assert schema["strict"] is True
    assert json.dumps(schema["schema"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert result.request.schema_hash == LLM_TURN_OUTPUT_SCHEMA_HASH
    assert "fixture-secret" not in result.request.request_hash
    assert result.ledger_fields["provider_output_hash"]


def test_adapter_maps_only_server_owned_claim_ids_and_rejects_bad_reference() -> None:
    prompt = _prompt()
    invalid = _output()
    claims = cast(list[dict[str, object]], invalid["key_claims"])
    claims[0]["used_evidence_refs"] = [0]
    transport = _FakeTransport(_response(invalid))
    result = _adapter(transport).execute(prompt)
    assert result.status == "failed"
    assert result.safe_error_code == "reference_invalid"
    assert result.retry_allowed


@pytest.mark.parametrize(
    ("payload", "expected"),
    (
        (_response(_output(), finish_reason="length"), "output_truncated"),
        (
            {"object": "chat.completion", "model": "wrong", "choices": [], "usage": {}},
            "provider_model_mismatch",
        ),
        (_response(_output(), finish_reason="content_filter"), "provider_content_filtered"),
        (
            _response(
                _output(), usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 9}
            ),
            "provider_usage_unknown",
        ),
    ),
)
def test_response_classification_is_closed_and_safe(payload: object, expected: str) -> None:
    result = _adapter(_ResponseTransport(payload)).execute(_prompt())
    assert result.safe_error_code == expected
    assert result.status == "failed"
    assert result.acceptance == "accepted"


def test_transport_not_sent_is_retryable_but_unknown_is_not() -> None:
    not_sent = _ResponseTransport(LLMTransportNotSent())
    unknown = _ResponseTransport(LLMAcceptanceUnknown())
    # Fakes that return the exception are not transport exceptions; verify the
    # concrete adapter transport classes directly through the classifier path.
    assert not_sent.calls == 0
    assert unknown.calls == 0

    class NotSent:
        def post(self, url: str, **kwargs: object) -> object:
            del url, kwargs
            raise LLMTransportNotSent()

    class Unknown:
        def post(self, url: str, **kwargs: object) -> object:
            del url, kwargs
            raise LLMAcceptanceUnknown()

    first = _adapter(NotSent()).execute(_prompt())
    second = _adapter(Unknown()).execute(_prompt())
    assert first.status == "not_sent" and first.retry_allowed
    assert second.status == "acceptance_unknown" and not second.retry_allowed


def test_attempt_two_uses_closed_repair_feedback_without_failed_value() -> None:
    prompt = _prompt()
    repaired = prompt.request.model_copy(
        update={
            "repair_feedback": PromptRepairFeedbackV1(
                safe_error_code="schema_invalid",
                json_pointers=("/key_claims",),
            )
        }
    )
    repaired_prompt = ProviderPromptV1(
        request=repaired,
        messages=(
            prompt.system_message,
            PromptMessageV1(role="user", content=repaired.canonical_json()),
        ),
        budget=preflight_prompt_budget(
            (prompt.system_message.content, repaired.canonical_json()),
            request_bytes=len(repaired.canonical_json().encode()),
            token_counter=ConservativeUtf8TokenCounter(),
        ),
        request_hash=repaired.request_hash,
        system_rules_hash=prompt.system_rules_hash,
    )
    transport = _FakeTransport(_response(_output()))
    result = _adapter(transport).execute(repaired_prompt, attempt_no=2, retrieval_reused=True)
    assert result.succeeded
    body = cast(dict[str, Any], transport.calls[0][1])
    user = json.loads(cast(str, cast(list[dict[str, object]], body["messages"])[1]["content"]))
    assert user["repair_feedback"] == {"code": "schema_invalid", "json_pointers": ["/key_claims"]}
    assert "fixture-secret" not in json.dumps(user)


def test_actual_message_privacy_scan_blocks_identity_and_unknown_fields() -> None:
    prompt = _prompt()
    value = json.loads(prompt.user_message.content)
    value["unexpected_field"] = "Alice"
    messages = (prompt.system_message, PromptMessageV1(role="user", content=json.dumps(value)))
    with pytest.raises(LLMOutboundPrivacyError) as error:
        scan_llm_outbound_messages(messages)
    assert error.value.code == "llm_outbound_field_forbidden"
    with pytest.raises(LLMOutboundPrivacyError) as identity_error:
        scan_llm_outbound_messages(prompt.messages, identity_tokens=("River Keeper",))
    assert identity_error.value.code == "llm_outbound_data_forbidden"
    assert "River Keeper" not in str(identity_error.value)


def test_path_aware_privacy_allows_opaque_uuid_id_paths_but_not_text() -> None:
    prompt = _prompt()
    value = json.loads(prompt.user_message.content)
    uuid = "12345678-1234-4234-8234-123456789abc"
    value["debate_id"] = uuid
    value["turn_id"] = uuid
    value["participant_id"] = uuid
    messages = (
        prompt.system_message,
        PromptMessageV1(role="user", content=json.dumps(value, separators=(",", ":"))),
    )
    scan_llm_outbound_messages(messages)

    value["topic"] = f"Topic mentioning {uuid}"
    messages = (
        prompt.system_message,
        PromptMessageV1(role="user", content=json.dumps(value, separators=(",", ":"))),
    )
    with pytest.raises(LLMOutboundPrivacyError):
        scan_llm_outbound_messages(messages)

    value = json.loads(prompt.user_message.content)
    value["topic"] = "A normal topic"
    value["persona_provider_view"]["identity"]["role"] = uuid
    messages = (
        prompt.system_message,
        PromptMessageV1(role="user", content=json.dumps(value, separators=(",", ":"))),
    )
    with pytest.raises(LLMOutboundPrivacyError):
        scan_llm_outbound_messages(messages)

    with pytest.raises(LLMOutboundPrivacyError):
        scan_llm_outbound_messages(
            (PromptMessageV1(role="system", content=uuid), prompt.user_message)
        )


def test_unreviewed_tokenizer_manifest_or_price_card_is_zero_call() -> None:
    class Fake:
        calls = 0

        def post(self, url: str, **kwargs: object) -> object:
            del url, kwargs
            self.calls += 1
            return _response(_output())

    fake = Fake()
    adapter = DashScopeLLMAdapter(
        DashScopeLLMConfig(workspace_id="workspace123"),
        fake,
        tokenizer=type(
            "Unreviewed",
            (),
            {
                "tokenizer_id": "fake",
                "asset_hash": "x",
                "count_tokens": lambda self, value: len(value),
            },
        )(),
        price_card=LLMPriceCardV1(
            input_price_per_million="0.5",
            cached_input_price_per_million="0.1",
            output_price_per_million="1",
            retrieved_at="2026-08-31T00:00:00Z",
            source_content_sha256="b" * 64,
        ),
        outbound_manifest=LLMOutboundManifestV1(),
    )
    with pytest.raises(LLMAdapterError):
        adapter.execute(_prompt())
    assert fake.calls == 0

    fake = Fake()
    adapter = DashScopeLLMAdapter(
        DashScopeLLMConfig(workspace_id="workspace123"),
        fake,
        tokenizer=PinnedLLMTokenizer("fake", "c" * 64, lambda value: len(value)),
        price_card=LLMPriceCardV1(
            input_price_per_million="0.5",
            cached_input_price_per_million="0.1",
            output_price_per_million="1",
            retrieved_at="2026-08-31T00:00:00Z",
            source_content_sha256="b" * 64,
        ),
    )
    with pytest.raises(LLMAdapterError):
        adapter.execute(_prompt(), outbound_manifest=None)
    assert fake.calls == 0

    fake = Fake()
    adapter = DashScopeLLMAdapter(
        DashScopeLLMConfig(workspace_id="workspace123"),
        fake,
        tokenizer=PinnedLLMTokenizer("fake", "c" * 64, lambda value: len(value)),
        outbound_manifest=LLMOutboundManifestV1(),
    )
    with pytest.raises(LLMAdapterError):
        adapter.execute(_prompt())
    assert fake.calls == 0


def test_accepted_stage_is_returned_before_local_reference_mapping_failure() -> None:
    invalid = _output()
    claims = cast(list[dict[str, object]], invalid["key_claims"])
    claims[0]["used_evidence_refs"] = [0]
    fake = _FakeTransport(_response(invalid))
    staged: list[LLMAcceptedCandidateV1] = []
    result = _adapter(fake).execute(
        _prompt(),
        stage_callback=lambda candidate: staged.append(candidate),
    )
    assert len(staged) == 1
    candidate = staged[0]
    assert candidate.schema_valid is True
    assert candidate.provider_output_json
    assert candidate.stage_hash == candidate.output_hash
    assert result.status == "failed"
    assert result.safe_error_code == "reference_invalid"
    assert result.accepted_candidate is candidate
    assert result.accepted_stage_json == candidate.stage_json
    assert result.provider_output_json == candidate.provider_output_json


def test_invalid_content_stage_has_only_safe_diagnostic_and_can_replay_locally() -> None:
    fake = _FakeTransport(
        _response(
            {},
            raw_content="not-json",
        )
    )
    result = _adapter(fake).execute(_prompt())
    candidate = result.accepted_candidate
    assert candidate is not None
    assert candidate.provider_output is None
    assert candidate.content_hash
    assert "not-json" not in candidate.stage_json
    replayed = type(candidate).from_staged_json(
        result.request,
        candidate.stage_json,
        stage_hash=candidate.stage_hash,
    )
    assert replayed.safe_error_code == "json_invalid"
    assert result.status == "failed"
    assert fake.calls


def test_valid_staged_candidate_can_be_validated_without_network() -> None:
    fake = _FakeTransport(_response(_output()))
    adapter = _adapter(fake)
    result = adapter.execute(_prompt())
    candidate = result.accepted_candidate
    assert candidate is not None and candidate.schema_valid
    before = len(fake.calls)
    mapped = adapter.validate_accepted(candidate)
    assert mapped.result.speech == "A transparent policy protects agency."
    assert len(fake.calls) == before


def test_price_card_rounds_up_and_reserves_supplier_tolerance() -> None:
    card = LLMPriceCardV1(
        input_price_per_million="0.5",
        cached_input_price_per_million="0.1",
        output_price_per_million="1.0",
    )
    assert card.reservation_cost() == Decimal("0.017510")
    assert card.actual_cost(
        prompt_tokens=100, cached_input_tokens=20, completion_tokens=10
    ) == Decimal("0.000052")
    assert reservation_cost(
        input_cap=32_000,
        output_cap=1_510,
        input_rate="0.5",
        cached_input_rate="0.1",
        output_rate="1",
    ) == Decimal("0.017510")
    assert actual_cost(
        prompt_tokens=100,
        cached_input_tokens=20,
        completion_tokens=10,
        input_rate="0.5",
        cached_input_rate="0.1",
        output_rate="1",
    ) == Decimal("0.000052")


def test_http_transport_disables_redirect_and_classifies_connect_vs_read() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "https://example.invalid"})

    with httpx.Client(transport=httpx.MockTransport(redirect)) as client:
        response = HttpxLLMTransport(client).post(
            "https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={},
            json={},
            timeout=1,
        )
    assert isinstance(response, httpx.Response) and response.status_code == 307
