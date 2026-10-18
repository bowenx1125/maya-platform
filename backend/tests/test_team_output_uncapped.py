"""Team model calls send no output cap (owner decision 2026-10-18).

Since 2026-10-13 every Team call sent ``max_tokens=1510``, which cut long
member replies and HTML reports mid-answer. Omitting it lets DashScope apply
the model's own maximum output; the legacy figure stays an accounting estimate.
"""

from __future__ import annotations

import json

from agno.models.message import Message
from app.modules.workspace.chat_team_provider import (
    TEAM_PER_CALL_MAX_TOKENS,
    team_request_bytes,
)
from app.providers.llm_price_card import LLM_INPUT_TOKEN_CAP, LLM_RESERVED_OUTPUT_TOKEN_CAP


def test_team_request_sends_no_output_cap() -> None:
    messages = [Message(role="system", content="s"), Message(role="user", content="u")]
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}]
    for tool_list, choice in ((None, None), (tools, "auto")):
        body = json.loads(team_request_bytes("qwen3.8-max-2026-09-02", messages, tool_list, choice))
        assert "max_tokens" not in body
        assert "max_completion_tokens" not in body
        assert body["stream"] is False and body["enable_thinking"] is False


def test_reservation_estimate_is_unchanged() -> None:
    # Ledger reservations still size each call with the legacy estimate.
    assert TEAM_PER_CALL_MAX_TOKENS == LLM_INPUT_TOKEN_CAP + LLM_RESERVED_OUTPUT_TOKEN_CAP
