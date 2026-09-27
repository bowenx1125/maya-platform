"""Fake-transport tests for the one-shot Real report provider boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from app.modules.reports.real_provider import (
    REAL_REPORT_MODEL,
    REAL_REPORT_SCHEMA_NAME,
    RealReportProvider,
    ReportProviderError,
)
from app.modules.reports.real_schema import (
    REPORT_SECTION_FIELDS,
    ReportRequest,
)
from app.modules.reports.schemas import ReportSectionOutput as ServiceReportSectionOutput
from app.providers.llm_adapter import DashScopeLLMConfig
from app.providers.llm_tokenizer import ConservativeLLMTokenizer, PinnedLLMTokenizer
from app.providers.llm_transport import (
    LLMAcceptanceUnknown,
    LLMTransportNotSent,
    LLMTransportResponse,
)

EVIDENCE_ID = UUID("12345678-1234-4234-8234-123456789abc")


def _request() -> ReportRequest:
    return ReportRequest.model_validate(
        {
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
                    "speech": (
                        "The class can keep uncertainty visible while revising its questions."
                    ),
                    "used_evidence_ids": [],
                },
            ],
            "sources": [
                {
                    "evidence_id": str(EVIDENCE_ID),
                    "excerpt": (
                        "A public source describes context, consent, and shared responsibility."
                    ),
                }
            ],
            "votes": [{"slot": "A", "count": 2}, {"slot": "B", "count": 1}],
            "insights": [
                {"category": "support", "summary": "Participants valued careful listening."}
            ],
        }
    )


def _sections() -> dict[str, str]:
    return {
        field: f"A careful English section for {field.replace('_', ' ')}."
        for field in REPORT_SECTION_FIELDS
    }


def _response(
    content: str | None = None,
    *,
    usage: Mapping[str, object] | None = None,
    model: str = REAL_REPORT_MODEL,
    finish_reason: str = "stop",
) -> dict[str, object]:
    return {
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content if content is not None else json.dumps(_sections()),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage or {"prompt_tokens": 80, "completion_tokens": 120, "total_tokens": 200},
    }


@dataclass
class FakeTransport:
    payload: object
    status_code: int = 200

    def __post_init__(self) -> None:
        self.calls = 0
        self.last_url = ""
        self.last_headers: dict[str, str] = {}
        self.last_json: dict[str, object] = {}

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: object,
    ) -> object:
        del timeout
        self.calls += 1
        self.last_url = url
        self.last_headers = dict(headers)
        self.last_json = dict(json)
        if isinstance(self.payload, BaseException):
            raise self.payload
        return LLMTransportResponse(self.status_code, self.payload)


def _tokenizer() -> PinnedLLMTokenizer:
    return PinnedLLMTokenizer(
        "reviewed-report-tokenizer-v1",
        "a" * 64,
        lambda value: len(value.split()),
    )


def _provider(transport: object) -> RealReportProvider:
    return RealReportProvider(
        config=DashScopeLLMConfig(
            api_key="fixture-secret",
            workspace_id="workspace123",
            policy_hash="c" * 64,
        ),
        transport=cast(Any, transport),
        tokenizer=_tokenizer(),
    )


def test_valid_response_is_mapped_once_and_wire_contract_is_exact() -> None:
    transport = FakeTransport(_response())
    provider = _provider(transport)
    prepared = provider.build_request(_request())
    result = provider.execute(_request())

    assert isinstance(result, ServiceReportSectionOutput)
    assert transport.calls == 1
    assert transport.last_url == (
        "https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert transport.last_headers["Authorization"] == "Bearer fixture-secret"
    assert "fixture-secret" not in json.dumps(transport.last_json)
    assert set(transport.last_json) == {
        "model",
        "messages",
        "enable_thinking",
        "stream",
        "temperature",
        "top_p",
        "n",
        "response_format",
    }
    assert transport.last_json["model"] == REAL_REPORT_MODEL
    assert transport.last_json["enable_thinking"] is False
    assert transport.last_json["stream"] is False
    assert transport.last_json["temperature"] == 0.2
    assert transport.last_json["top_p"] == 0.8
    assert "max_completion_tokens" not in transport.last_json
    assert transport.last_json["n"] == 1
    messages = cast(list[dict[str, str]], transport.last_json["messages"])
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == prepared.system_message.content
    assert messages[1]["content"] == prepared.user_message.content
    assert "position_summary" not in messages[1]["content"]
    wrapper = cast(dict[str, object], transport.last_json["response_format"])
    schema_wrapper = cast(dict[str, object], wrapper["json_schema"])
    assert wrapper["type"] == "json_schema"
    assert schema_wrapper["name"] == REAL_REPORT_SCHEMA_NAME
    assert schema_wrapper["strict"] is True
    assert schema_wrapper["schema"]
    assert len(prepared.request_hash) == 64
    assert provider.build_request(_request()).request_hash == prepared.request_hash


def test_execute_prepared_sends_frozen_wire_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = FakeTransport(_response())
    provider = _provider(transport)
    prepared = provider.build_request(_request())

    def fail_build(_provider: RealReportProvider, _value: object) -> object:
        raise AssertionError("prepared execution must not rebuild the wire")

    monkeypatch.setattr(RealReportProvider, "build_request", fail_build)
    assert isinstance(provider.execute_prepared(prepared), ServiceReportSectionOutput)
    assert transport.calls == 1


def test_request_hash_does_not_change_with_authorization_secret() -> None:
    first = _provider(FakeTransport(_response())).build_request(_request())
    second_provider = RealReportProvider(
        config=DashScopeLLMConfig(
            api_key="another-fixture-secret",
            workspace_id="workspace123",
            policy_hash="c" * 64,
        ),
        transport=FakeTransport(_response()),
        tokenizer=_tokenizer(),
    )
    second = second_provider.build_request(_request())
    assert first.request_hash == second.request_hash


@pytest.mark.parametrize(
    ("tokenizer", "expected"),
    (
        (None, "report_tokenizer_required"),
        (
            SimpleNamespace(
                tokenizer_id="   ",
                asset_hash="b" * 64,
                count_tokens=lambda value: len(value.split()),
            ),
            "report_tokenizer_invalid",
        ),
        (
            SimpleNamespace(
                tokenizer_id="unhashed-tokenizer",
                asset_hash="not-a-sha256",
                count_tokens=lambda value: len(value.split()),
            ),
            "report_tokenizer_invalid",
        ),
    ),
)
def test_named_tokenizer_is_required_before_transport(
    tokenizer: object | None,
    expected: str,
) -> None:
    transport = FakeTransport(_response())
    provider = RealReportProvider(
        config=DashScopeLLMConfig(workspace_id="workspace123"),
        transport=transport,
        tokenizer=tokenizer,
    )
    with pytest.raises(ReportProviderError, match=expected):
        provider.execute(_request())
    assert transport.calls == 0


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("debate_overview", "课堂总结。", "report_output_language"),
        ("debate_overview", "# Heading\nEnglish prose.", "report_output_markdown"),
        ("debate_overview", "The winner is clear.", "report_output_winner_language"),
        ("debate_overview", "The final vote total is 2.", "report_output_vote_total"),
    ),
)
def test_output_content_is_preserved_without_an_extra_provider_call(
    field: str, value: str, expected: str
) -> None:
    sections = _sections()
    sections[field] = value
    transport = FakeTransport(_response(json.dumps(sections)))
    result = _provider(transport).execute(_request())
    assert result.model_dump()[field] == value
    assert transport.calls == 1


def test_output_extra_field_and_malformed_json_fail_once() -> None:
    extra = _sections()
    extra["unexpected"] = "not allowed"
    transport = FakeTransport(_response(json.dumps(extra)))
    with pytest.raises(ReportProviderError, match="report_output_schema"):
        _provider(transport).execute(_request())
    assert transport.calls == 1

    malformed = FakeTransport(_response("not-json"))
    with pytest.raises(ReportProviderError, match="report_content_json"):
        _provider(malformed).execute(_request())
    assert malformed.calls == 1


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        "unavailable",
        [],
        {"prompt_tokens": 80, "completion_tokens": 120, "total_tokens": 201},
        {"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "200"},
        {"prompt_tokens_details": {"cached_tokens": "unknown"}},
    ],
)
def test_usage_metadata_never_blocks_a_valid_report(usage: object) -> None:
    response = _response()
    response["usage"] = usage
    transport = FakeTransport(response)
    assert _provider(transport).execute(_request()).model_dump() == _sections()
    assert transport.calls == 1


def test_missing_usage_does_not_block_a_valid_report() -> None:
    response = _response()
    response.pop("usage")
    transport = FakeTransport(response)
    assert _provider(transport).execute(_request()).model_dump() == _sections()
    assert transport.calls == 1


@pytest.mark.parametrize(
    ("payload", "expected"),
    (
        (LLMTransportNotSent(), "report_transport_not_sent"),
        (LLMAcceptanceUnknown(), "report_acceptance_unknown"),
        (RuntimeError("raw transport details"), "report_transport_unknown"),
    ),
)
def test_transport_failure_is_never_retried_or_echoed(
    payload: BaseException, expected: str
) -> None:
    transport = FakeTransport(payload)
    with pytest.raises(ReportProviderError, match=expected) as error:
        _provider(transport).execute(_request())
    assert transport.calls == 1
    assert "raw transport details" not in str(error.value)


def test_http_rejection_and_finish_reason_are_one_call_terminal_failures() -> None:
    rejected = FakeTransport(_response(), status_code=429)
    with pytest.raises(ReportProviderError, match="report_http_rejected"):
        _provider(rejected).execute(_request())
    assert rejected.calls == 1

    truncated = FakeTransport(_response(finish_reason="length"))
    with pytest.raises(ReportProviderError, match="report_finish_reason"):
        _provider(truncated).execute(_request())
    assert truncated.calls == 1


def test_response_shape_and_private_or_provider_fields_fail_closed() -> None:
    """Required content remains validated; metadata is informational."""

    for missing in ("choices",):
        response = _response()
        response.pop(missing)
        transport = FakeTransport(response)
        with pytest.raises(ReportProviderError, match="report_response_shape"):
            _provider(transport).execute(_request())
        assert transport.calls == 1

    response = _response()
    message = cast(
        dict[str, object],
        cast(list[dict[str, object]], response["choices"])[0]["message"],
    )
    message.pop("content")
    transport = FakeTransport(response)
    with pytest.raises(ReportProviderError, match="report_message_shape"):
        _provider(transport).execute(_request())
    assert transport.calls == 1


def test_a_genuine_provider_envelope_is_accepted() -> None:
    """The shape a real reply actually has, extra documented fields and all."""

    response = _response()
    response["id"] = "chatcmpl-abc123"
    response["created"] = 1_759_000_000
    response["system_fingerprint"] = "fp_local"
    usage = cast(dict[str, object], response["usage"])
    usage["prompt_tokens_details"] = {"cached_tokens": 0, "text_tokens": 80}
    choice = cast(list[dict[str, object]], response["choices"])[0]
    choice["logprobs"] = None
    transport = FakeTransport(response)
    sections = _provider(transport).execute(_request())
    assert transport.calls == 1
    assert sections is not None


def test_conservative_tokenizer_backs_a_real_report_request() -> None:
    """Demo V1 removed the supplier-tokenizer authorization gate.

    The UTF-8 counter over-counts, so it can only reject an over-large request,
    never authorize an under-counted one.  The request must still record that
    counter's exact ID and asset hash so the ledger names it.
    """

    tokenizer = ConservativeLLMTokenizer()
    provider = RealReportProvider(
        config=DashScopeLLMConfig(workspace_id="workspace123"),
        transport=FakeTransport(_response()),
        tokenizer=tokenizer,
    )
    prepared = provider.build_request(_request())
    assert prepared.tokenizer_id == tokenizer.tokenizer_id
    assert prepared.tokenizer_asset_hash == tokenizer.asset_hash


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 320_001, "completion_tokens": 1, "total_tokens": 320_002},
        {"prompt_tokens": 80, "completion_tokens": 15_110, "total_tokens": 15_190},
    ],
)
def test_report_accepts_usage_above_legacy_estimates(usage: Mapping[str, object]) -> None:
    transport = FakeTransport(_response(usage=usage))
    _provider(transport).execute(_request())
    assert transport.calls == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {"object": "provider.completion", "model": "provider-model-revision"},
        {"model": "provider-model-revision"},
        {"object": "provider.completion"},
        {},
    ],
)
def test_report_resource_metadata_does_not_reject_valid_content(metadata: dict[str, str]) -> None:
    response = _response()
    response.pop("object")
    response.pop("model")
    response.update(metadata)
    transport = FakeTransport(response)
    result = _provider(transport).execute(_request())
    assert result.model_dump() == _sections()
    assert transport.calls == 1
    assert transport.last_json["model"] == REAL_REPORT_MODEL
