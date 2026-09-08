"""Authored fields share one Markdown budget through the model-input seam."""

from __future__ import annotations

import pytest
from app.modules.agents.persona import MAX_AGENT_MD_CHARS, compile_persona_v2, provider_view
from app.modules.debates.generation.segments import coerce_persona

from tests.persona_v2_fixtures import persona_v2_markdown


@pytest.mark.parametrize(
    "original",
    [
        "River Keeper",
        "Watershed steward",
        "一个虚构的社区守护者，记录共享水域的记忆。",
        "代际责任",
        "Reciprocity",
        "保护共享资源，通过谨慎的长期照护面对不完整的证据。",
        "Calm and reflective",
        "先说明背景，再权衡后果",
        "Acknowledge valid concerns before qualifying them",
        "Ask one open question about long-term effects",
    ],
)
def test_long_field_survives_compilation_and_provider_projection(original: str) -> None:
    expanded = "Detailed perspective " * 70
    source = persona_v2_markdown().replace(original, expanded.strip())
    assert len(source) < MAX_AGENT_MD_CHARS
    result = compile_persona_v2(source)
    assert result.compiled, result.diagnostics
    assert result.spec is not None
    payload = coerce_persona(provider_view(result.spec)).as_payload()
    assert expanded.strip() in str(payload)


def test_list_length_is_bounded_by_document_instead_of_eight_items() -> None:
    source = persona_v2_markdown().replace(
        "- Reciprocity", "\n".join(f"- Distinct value {index}" for index in range(12))
    )
    result = compile_persona_v2(source)
    assert result.compiled, result.diagnostics
    assert result.spec is not None
    assert len(coerce_persona(provider_view(result.spec)).core_values) == 13


@pytest.mark.parametrize("extra", [0, 1])
def test_whole_document_character_boundary(extra: int) -> None:
    source = persona_v2_markdown().replace("Watershed steward", "")
    role = "界" * (MAX_AGENT_MD_CHARS - len(source) + extra)
    source = source.replace("- Role: \n", f"- Role: {role}\n")
    assert len(source) == MAX_AGENT_MD_CHARS + extra
    result = compile_persona_v2(source)
    assert result.compiled is (extra == 0)
    if extra == 0:
        assert result.spec is not None
        assert coerce_persona(provider_view(result.spec)).identity["role"] == role
    else:
        assert result.diagnostics
        assert result.spec is None
