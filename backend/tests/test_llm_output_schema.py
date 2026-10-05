"""Cross-platform checks for the pinned LLM output schema asset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.providers import llm_output


def _canonical_schema_bytes() -> bytes:
    return llm_output._schema_path().read_bytes().replace(b"\r\n", b"\n")


def test_pinned_schema_accepts_windows_crlf_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "llm-turn-output.v1.schema.json"
    schema_path.write_bytes(_canonical_schema_bytes().replace(b"\n", b"\r\n"))
    monkeypatch.setattr(llm_output, "_schema_path", lambda: schema_path)

    assert llm_output.load_llm_turn_output_schema() == json.loads(
        _canonical_schema_bytes().decode("utf-8")
    )


def test_pinned_schema_still_rejects_content_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_path = tmp_path / "llm-turn-output.v1.schema.json"
    schema_path.write_bytes(_canonical_schema_bytes() + b" ")
    monkeypatch.setattr(llm_output, "_schema_path", lambda: schema_path)

    with pytest.raises(llm_output.LLMOutputError) as error:
        llm_output.load_llm_turn_output_schema()

    assert error.value.code == "schema_hash_changed"
