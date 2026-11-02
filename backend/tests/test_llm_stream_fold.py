"""Streamed chat completions: one HTTP call, text handed on as it arrives,
and a body the ledger stores exactly like a non-stream response."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import pytest
from app.providers.llm_transport import (
    STREAM_INVALID_BODY,
    HttpxLLMTransport,
    LLMAcceptanceUnknown,
    LLMStreamedResponse,
    fold_chat_stream,
)


def _sse(*chunks: object) -> list[str]:
    lines: list[str] = []
    for chunk in chunks:
        data = chunk if isinstance(chunk, str) else json.dumps(chunk, ensure_ascii=False)
        lines.extend([f"data: {data}", ""])
    return lines


def _chunk(delta: dict[str, object], finish: str | None = None) -> dict[str, object]:
    return {
        "id": "chatcmpl-1",
        "model": "fixture-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def test_fold_hands_on_each_text_piece_and_rebuilds_the_completion() -> None:
    pieces: list[str] = []
    body, first = fold_chat_stream(
        _sse(
            _chunk({"role": "assistant", "content": ""}),
            _chunk({"content": "你好，"}),
            _chunk({"content": "我是 Maya。"}),
            _chunk({}, "stop"),
            {"id": "chatcmpl-1", "choices": [], "usage": {"prompt_tokens": 9}},
            "[DONE]",
        ),
        pieces.append,
    )
    assert pieces == ["你好，", "我是 Maya。"]
    assert first is not None
    folded = json.loads(body)
    assert folded["choices"] == [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "你好，我是 Maya。"},
            "finish_reason": "stop",
        }
    ]
    assert folded["usage"] == {"prompt_tokens": 9}
    assert folded["model"] == "fixture-model"


def test_fold_joins_split_tool_calls_the_way_the_supplier_sends_them() -> None:
    body, first = fold_chat_stream(
        _sse(
            _chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_a",
                            "type": "function",
                            "function": {"name": "assessment_action", "arguments": '{"act'},
                        }
                    ]
                }
            ),
            _chunk(
                {"tool_calls": [{"index": 0, "id": "", "function": {"arguments": 'ion":"start"}'}}]}
            ),
            _chunk({}, "tool_calls"),
            "[DONE]",
        )
    )
    assert first is None
    message = json.loads(body)["choices"][0]["message"]
    assert message["content"] is None
    assert message["tool_calls"] == [
        {
            "id": "call_a",
            "type": "function",
            "function": {"name": "assessment_action", "arguments": '{"action":"start"}'},
        }
    ]
    assert json.loads(body)["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.parametrize(
    "lines",
    [
        ["data: {not json"],
        _sse(["a list, not a chunk"]),
        _sse({"choices": [{"index": 1, "delta": {"content": "x"}}]}),
        _sse(_chunk({"content": 7})),
        _sse(_chunk({"tool_calls": [{"function": {"name": "x"}}]})),
    ],
)
def test_fold_stores_an_unreadable_stream_as_an_invalid_body(lines: list[str]) -> None:
    body, _first = fold_chat_stream(lines)
    assert body == STREAM_INVALID_BODY


def test_fold_past_the_total_deadline_is_acceptance_unknown() -> None:
    ticks = iter([0.0, 1.0, 999.0, 999.0])
    with pytest.raises(LLMAcceptanceUnknown):
        fold_chat_stream(
            _sse(_chunk({"content": "a"}), _chunk({"content": "b"}), _chunk({}, "stop")),
            deadline=10.0,
            clock=lambda: next(ticks),
        )


def test_a_listener_that_fails_never_fails_the_call() -> None:
    def broken(_piece: str) -> None:
        raise RuntimeError("the browser left")

    body, _first = fold_chat_stream(_sse(_chunk({"content": "kept"}), _chunk({}, "stop")), broken)
    assert json.loads(body)["choices"][0]["message"]["content"] == "kept"


def _stream_body(*chunks: object) -> bytes:
    return ("\n".join(_sse(*chunks)) + "\n").encode()


def test_post_bytes_streams_one_request_and_returns_the_folded_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)

        def body() -> Iterator[bytes]:
            yield _stream_body(_chunk({"content": "Hel"}))
            yield _stream_body(_chunk({"content": "lo"}), _chunk({}, "stop"), "[DONE]")

        return httpx.Response(
            200, headers={"content-type": "text/event-stream; charset=utf-8"}, content=body()
        )

    pieces: list[str] = []
    request_body = b'{"model":"m","stream":true}'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = HttpxLLMTransport(client).post_bytes(
            "https://example.invalid/v1/chat/completions",
            headers={"Authorization": "Bearer fixture"},
            content=request_body,
            timeout=HttpxLLMTransport.timeout(),
            on_delta=pieces.append,
        )
    assert len(seen) == 1
    assert seen[0].content == request_body
    assert isinstance(response, LLMStreamedResponse)
    assert response.status_code == 200
    assert pieces == ["Hel", "lo"]
    assert json.loads(response.content)["choices"][0]["message"]["content"] == "Hello"


@pytest.mark.parametrize(
    ("status", "content_type", "payload"),
    [
        (429, "application/json", b'{"error":{"code":"rate_limit"}}'),
        (200, "application/json", b'{"choices":[]}'),
    ],
)
def test_post_bytes_returns_a_non_stream_answer_unchanged(
    status: int, content_type: str, payload: bytes
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": content_type}, content=payload)

    pieces: list[str] = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = HttpxLLMTransport(client).post_bytes(
            "https://example.invalid/v1/chat/completions",
            headers={},
            content=b"{}",
            timeout=HttpxLLMTransport.timeout(),
            on_delta=pieces.append,
        )
    assert isinstance(response, LLMStreamedResponse)
    assert (response.status_code, response.content) == (status, payload)
    assert pieces == []


def test_a_read_failure_mid_stream_is_acceptance_unknown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        def body() -> Iterator[bytes]:
            yield _stream_body(_chunk({"content": "half"}))
            raise httpx.ReadError("connection dropped", request=request)

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LLMAcceptanceUnknown):
            HttpxLLMTransport(client).post_bytes(
                "https://example.invalid/v1/chat/completions",
                headers={},
                content=b"{}",
                timeout=HttpxLLMTransport.timeout(),
                on_delta=lambda _piece: None,
            )
