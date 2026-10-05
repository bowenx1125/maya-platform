"""The container layout loads the same pinned output contract as a checkout."""

import pytest
from app.providers import llm_segments
from app.providers.llm_adapter import LLMAdapterError


def test_segment_schema_uses_container_mount_and_rejects_drift(tmp_path, monkeypatch):
    raw = llm_segments._schema_bytes()
    mounted = tmp_path / "mounted" / "llm-turn-output.v2.schema.json"
    mounted.parent.mkdir()
    mounted.write_bytes(raw.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(llm_segments, "_schema_candidates", lambda: (tmp_path / "missing", mounted))
    assert llm_segments._schema_bytes() == raw
    assert llm_segments.segment_output_schema_hash() == llm_segments.SEGMENT_SCHEMA_SHA256
    assert llm_segments._schema()["type"] == "object"
    mounted.write_bytes(raw.replace(b"\n", b"\r\n") + b"\r\n")
    with pytest.raises(LLMAdapterError) as error:
        llm_segments._schema()
    assert error.value.code == "llm_schema_invalid"
