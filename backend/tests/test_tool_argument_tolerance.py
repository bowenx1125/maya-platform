"""A Tool call with an argument the Tool does not take is not a failed call.

Prod (2026-10-18): a Scorer's assessment_action carried reply_language='zh'
where the strict argument model did not expect it; the whole call was
rejected and the member failed with assessment_action_required. Unknown
top-level arguments are now dropped and logged. Wrong values, missing fields
and unknown nested fields are still refused.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from app.modules.runtime_tools.builtin import runtime_registry
from app.modules.runtime_tools.registry import _validated_payload, merged_tool_arguments
from pydantic import ValidationError


def _spec(name: str) -> Any:
    return runtime_registry()[name]


def test_unknown_top_level_arguments_are_ignored_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="maya.runtime_tools")
    payload = _validated_payload(
        _spec("assessment_action"),
        {"classification": "answer_only", "answer_span": "42", "mood": "calm", "zz": 1},
    )
    assert payload.model_dump(exclude_none=True) == {
        "classification": "answer_only",
        "answer_span": "42",
    }
    assert "ignored unknown arguments tool=assessment_action arguments=mood,zz" in caplog.text


def test_known_arguments_keep_their_checks() -> None:
    with pytest.raises(ValidationError):
        _validated_payload(_spec("assessment_action"), {"classification": "not-a-class"})
    with pytest.raises(ValidationError):
        _validated_payload(_spec("assessment_action"), {"mood": "calm"})  # no classification
    with pytest.raises(ValidationError):
        _validated_payload(
            _spec("edit_assessment"),
            {"content": {"overall_feedback": "x", "questions": [], "bogus": 1}, "mood": "x"},
        )


def test_fields_sent_beside_arguments_join_the_payload() -> None:
    saved = {"arguments": {"classification": "answer_only"}, "reply_language": "zh"}
    assert merged_tool_arguments(saved) == {
        "classification": "answer_only",
        "reply_language": "zh",
    }
    # A field inside "arguments" wins over the same field beside it.
    assert merged_tool_arguments(
        {"arguments": {"reply_language": "en"}, "reply_language": "zh"}
    ) == {"reply_language": "en"}
    flat = {"classification": "answer_only"}
    assert merged_tool_arguments(flat) == flat
