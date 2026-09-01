"""Fake-only tests for the closed Real report request boundary."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from app.modules.reports.real_prompt import (
    REPORT_PROMPT_CONTRACT_VERSION,
    REPORT_SYSTEM_PROMPT,
    build_report_request,
)
from app.modules.reports.real_schema import (
    REPORT_SCHEMA_NAME,
    REPORT_SECTION_FIELDS,
    REPORT_SECTION_SCHEMA_HASH,
    ReportBoundaryError,
    ReportRequest,
    validate_report_request,
    validate_report_sections,
)
from app.modules.reports.schemas import ReportSectionOutput
from app.providers.llm_adapter import DashScopeLLMConfig
from app.providers.llm_price_card import LLMPriceCardV1
from app.providers.llm_tokenizer import PinnedLLMTokenizer
from pydantic import ValidationError

EVIDENCE_ID = UUID("12345678-1234-4234-8234-123456789abc")


def _raw_request() -> dict[str, object]:
    return {
        "topic": "How can classrooms share cultural knowledge responsibly?",
        "participants": [
            {
                "slot": "A",
                "agent_name": "River Keeper",
            },
            {
                "slot": "B",
                "agent_name": "Community Gardener",
            },
        ],
        "speeches": [
            {
                "slot": "A",
                "round_no": 1,
                "turn_index": 0,
                "speech": (
                    "A classroom should preserve context and distinguish evidence from "
                    "interpretation."
                ),
                "used_evidence_ids": [str(EVIDENCE_ID)],
            },
            {
                "slot": "B",
                "round_no": 1,
                "turn_index": 1,
                "speech": (
                    "Learners can compare perspectives when a community helps define what is "
                    "shared."
                ),
                "used_evidence_ids": [],
            },
            {
                "slot": "A",
                "round_no": 2,
                "turn_index": 2,
                "speech": "Careful listening makes a responsible exchange possible.",
                "used_evidence_ids": [],
            },
            {
                "slot": "B",
                "round_no": 2,
                "turn_index": 3,
                "speech": "The class can keep uncertainty visible while revising its questions.",
                "used_evidence_ids": [],
            },
        ],
        "sources": [
            {
                "evidence_id": str(EVIDENCE_ID),
                "excerpt": "A public source describes context, consent, and shared responsibility.",
            }
        ],
        "votes": [{"slot": "A", "count": 2}, {"slot": "B", "count": 1}],
        "insights": [
            {"category": "support", "summary": "Participants valued careful listening."},
            {"category": "question", "summary": "The class should ask who decides what is shared."},
        ],
    }


def _request() -> ReportRequest:
    return ReportRequest.model_validate(_raw_request())


def _tokenizer() -> PinnedLLMTokenizer:
    return PinnedLLMTokenizer(
        "reviewed-report-tokenizer-v1",
        "a" * 64,
        lambda value: len(value.split()),
    )


def _price_card() -> LLMPriceCardV1:
    return LLMPriceCardV1(
        input_price_per_million="0.5",
        cached_input_price_per_million="0.1",
        output_price_per_million="1.0",
        retrieved_at="2026-08-31T00:00:00Z",
        source_content_sha256="b" * 64,
    )


def _config() -> DashScopeLLMConfig:
    return DashScopeLLMConfig(
        api_key="fixture-secret",
        workspace_id="workspace123",
        policy_hash="c" * 64,
    )


def _sections() -> dict[str, str]:
    return {
        field: f"A careful English section for {field.replace('_', ' ')}."
        for field in REPORT_SECTION_FIELDS
    }


def test_request_is_exact_two_message_canonical_and_hash_excludes_secret() -> None:
    request = build_report_request(
        _request(),
        config=_config(),
        tokenizer=_tokenizer(),
        price_card=_price_card(),
    )
    assert request.method == "POST"
    assert request.endpoint.endswith("/compatible-mode/v1/chat/completions")
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.system_message.content == REPORT_SYSTEM_PROMPT
    assert request.user_message.content == request.report.canonical_json()
    assert request.input_hash == request.report.input_hash()
    assert len(request.request_hash) == 64
    assert "fixture-secret" not in request.request_hash
    assert "fixture-secret" not in request.user_message.content
    assert request.schema_hash == REPORT_SECTION_SCHEMA_HASH
    body = cast(dict[str, object], request.body)
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
    assert body["n"] == 1
    schema_wrapper = cast(dict[str, object], body["response_format"])
    schema = cast(dict[str, object], schema_wrapper["json_schema"])
    assert schema["name"] == REPORT_SCHEMA_NAME
    assert schema["strict"] is True
    required = cast(dict[str, object], schema["schema"])["required"]
    assert set(cast(list[str], required)) == set(REPORT_SECTION_FIELDS)
    assert request.budget.input_tokens > 0
    assert request.estimated_cost_cny == Decimal("0.017510")


def test_request_hash_is_stable_when_allowlisted_arrays_are_reordered() -> None:
    first = build_report_request(
        _request(), config=_config(), tokenizer=_tokenizer(), price_card=_price_card()
    )
    value = _raw_request()
    for field in ("participants", "speeches", "sources", "votes", "insights"):
        items = cast(list[object], value[field])
        items.reverse()
    second = build_report_request(
        value, config=_config(), tokenizer=_tokenizer(), price_card=_price_card()
    )
    assert second.request_hash == first.request_hash
    assert second.user_message.content == first.user_message.content
    assert REPORT_PROMPT_CONTRACT_VERSION not in json.dumps(
        {
            "request_hash": first.request_hash,
            "schema_hash": first.schema_hash,
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("topic", "课堂如何分享文化知识？"),
        ("topic", "# hidden heading"),
        ("topic", "The winner should decide."),
    ),
)
def test_request_rejects_cjk_markdown_and_unsafe_winner_language(field: str, value: str) -> None:
    payload = _raw_request()
    payload[field] = value
    with pytest.raises(ReportBoundaryError):
        validate_report_request(payload)


def test_request_rejects_raw_private_fields_and_unused_rag() -> None:
    payload = _raw_request()
    payload["teacher_note"] = "private"  # type: ignore[assignment]
    with pytest.raises(ReportBoundaryError):
        validate_report_request(payload)

    payload = _raw_request()
    sources = cast(list[dict[str, object]], payload["sources"])
    sources.append(
        {
            "evidence_id": "12345678-1234-4234-8234-123456789abd",
            "excerpt": "An unused public excerpt.",
        }
    )
    with pytest.raises(ReportBoundaryError, match="report_unused_evidence"):
        validate_report_request(payload)


def test_request_rejects_private_text_and_identity_shaped_values() -> None:
    for forbidden in (
        "api_key=secret-value",
        "student_id=42",
        "/Users/private/report.txt",
        "https://provider.invalid/report",
    ):
        payload = _raw_request()
        participant = cast(list[dict[str, object]], payload["participants"])[0]
        participant["agent_name"] = forbidden
        with pytest.raises(ReportBoundaryError):
            validate_report_request(payload)


def test_output_maps_to_existing_closed_report_section_dto() -> None:
    result = validate_report_sections(_sections())
    assert isinstance(result, ReportSectionOutput)
    assert set(result.model_dump()) == set(REPORT_SECTION_FIELDS)


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value.update({"debate_overview": "课堂总结。"}),
        lambda value: value.update({"debate_overview": "# Heading\nEnglish text."}),
        lambda value: value.update({"debate_overview": "The winner is clear."}),
        lambda value: value.update({"debate_overview": "The code-owned final vote total is 2."}),
        lambda value: value.update({"extra": "not allowed"}),
    ),
)
def test_output_rejects_cjk_markdown_winner_vote_total_and_extra(mutator: Any) -> None:
    value = _sections()
    mutator(value)
    with pytest.raises(ReportBoundaryError):
        validate_report_sections(value)


def test_output_rejects_non_mapping_or_pydantic_validation_error() -> None:
    with pytest.raises(ReportBoundaryError, match="report_output_schema"):
        validate_report_sections(["not", "an", "object"])
    with pytest.raises(ValidationError):
        ReportSectionOutput.model_validate({"debate_overview": "only one field"})


def test_request_models_have_no_persona_or_identifier_slots() -> None:
    with pytest.raises(ReportBoundaryError):
        validate_report_request(
            {
                **_raw_request(),
                "persona": "raw authored persona",
            }
        )
    payload = _raw_request()
    speech = cast(list[dict[str, object]], payload["speeches"])[0]
    speech["turn_id"] = "12345678-1234-4234-8234-123456789abd"
    with pytest.raises(ReportBoundaryError):
        validate_report_request(payload)


def test_canonical_payload_does_not_add_private_or_provider_fields() -> None:
    payload = _request().canonical_payload()
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert set(payload) == {"topic", "participants", "speeches", "sources", "votes", "insights"}
    assert "fixture-secret" not in serialized
    assert "workspace123" not in serialized
    assert "provider" not in serialized.lower()
