"""Authored fields share one Markdown budget through the model-input seam."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.modules.agents.persona import compile_persona, compile_persona_v2, provider_view
from app.modules.agents.persona_service import PersonaVersionState
from app.modules.debates.generation.segments import coerce_persona

from tests.persona_fixtures import confirmed_persona_fields
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
    assert expanded.strip() in source
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
def test_whole_document_size_is_not_a_compile_gate(extra: int) -> None:
    source = persona_v2_markdown().replace("Watershed steward", "")
    role = "界" * (12_000 - len(source) + extra)
    source = source.replace("- Role: \n", f"- Role: {role}\n")
    assert len(source) >= 12_000
    result = compile_persona_v2(source)
    assert result.compiled, result.diagnostics
    assert result.spec is not None
    assert coerce_persona(provider_view(result.spec)).identity["role"] == role


def test_v1_compiler_and_legacy_projection_accept_long_saved_markdown() -> None:
    source = confirmed_persona_fields("River Keeper", datetime(2026, 9, 27, tzinfo=UTC))["agent_md"]
    long_source = source.replace("Classroom technology ethics expert", "R" * 12_001)
    result = compile_persona(long_source, expected_name="River Keeper")
    assert len(long_source) > 12_000
    assert result.compiled, result.diagnostics

    projected = PersonaVersionState.model_validate(
        {
            "version_id": "legacy-version",
            "agent_id": "legacy-agent",
            "group_id": "legacy-group",
            "agent_name": "River Keeper",
            "state": "published",
            "revision": 1,
            "agent_md": long_source,
            "persona_required": False,
        }
    )
    assert projected.agent_md == long_source
