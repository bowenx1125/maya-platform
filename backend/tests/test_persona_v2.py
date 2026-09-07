"""Offline checks for the current five-section Persona version boundary."""

from __future__ import annotations

import json

import pytest
from app.modules.agents.persona import (
    DEFAULT_PERSONA_COMPILER_VERSION,
    PERSONA_COMPILER_VERSION_V1,
    PERSONA_COMPILER_VERSION_V2,
    PersonaCompiler,
    PersonaProviderIdentityError,
    PersonaProviderViewV1,
    PersonaProviderViewV2,
    PersonaSpecV1,
    PersonaSpecV2,
    canonical_json,
    compile_persona,
    compile_persona_v1_or_raise,
    compile_persona_v2,
    parse_persona_spec,
    persona_spec_hash,
    provider_view,
    provider_view_v1,
    provider_view_v2,
)
from app.modules.agents.persona_service import (
    PersonaService,
    PersonaVersionState,
    is_persona_confirmed,
)

from tests.persona_v2_fixtures import persona_v2_markdown
from tests.test_wave4_persona import VALID_MD


def test_new_template_defaults_to_v2_and_omits_removed_fields() -> None:
    result = compile_persona(persona_v2_markdown(), expected_name="River Keeper")

    assert result.compiled
    assert (
        result.compiler_version == DEFAULT_PERSONA_COMPILER_VERSION == PERSONA_COMPILER_VERSION_V2
    )
    assert isinstance(result.spec, PersonaSpecV2)
    assert result.spec.schema_version == "persona_spec_v2"
    payload = json.loads(result.canonical_json or "{}")
    assert "debate_strategy" not in payload
    assert "boundaries" not in payload


def test_compiler_object_defaults_to_current_v2_template() -> None:
    result = PersonaCompiler().compile(persona_v2_markdown(), expected_name="River Keeper")

    assert result.compiled
    assert result.compiler_version == PERSONA_COMPILER_VERSION_V2
    assert isinstance(result.spec, PersonaSpecV2)


def test_v2_accepts_unicode_authorship_without_language_gate() -> None:
    result = compile_persona_v2(persona_v2_markdown(), expected_name="River Keeper")

    assert result.compiled
    assert result.spec is not None
    assert result.spec.initial_position.startswith("保护共享资源")
    assert result.spec.speaking_style.argument_pattern.startswith("先说明背景")


def test_v2_removed_sections_are_rejected_without_synthetic_values() -> None:
    source = persona_v2_markdown() + "\n## Debate strategy\n\n- fake strategy\n"
    result = compile_persona_v2(source, expected_name="River Keeper")

    assert not result.compiled
    assert result.spec is None
    assert "unknown_section" in {diagnostic.code for diagnostic in result.diagnostics}


def test_v2_name_binding_is_strict() -> None:
    result = compile_persona_v2(persona_v2_markdown(), expected_name="Other Name")

    assert not result.compiled
    assert any(item.code == "name_mismatch" for item in result.diagnostics)


def test_v1_is_still_readable_with_the_same_canonical_shape_and_hash() -> None:
    result = compile_persona(VALID_MD, expected_name="River Keeper")
    explicit = compile_persona_v1_or_raise(VALID_MD, expected_name="River Keeper")

    assert result.compiled
    assert result.compiler_version == PERSONA_COMPILER_VERSION_V1
    assert isinstance(result.spec, PersonaSpecV1)
    assert result.canonical_json == canonical_json(explicit)

    parsed = parse_persona_spec(result.canonical_json or "")
    assert isinstance(parsed, PersonaSpecV1)
    assert persona_spec_hash(parsed) == result.persona_spec_hash
    assert parsed.debate_strategy and parsed.boundaries


def test_provider_projection_preserves_version_and_drops_audit_fields() -> None:
    v1 = compile_persona_v1_or_raise(VALID_MD, expected_name="River Keeper")
    v2_result = compile_persona_v2(persona_v2_markdown(), expected_name="River Keeper")
    assert v2_result.spec is not None
    v2 = v2_result.spec

    v1_view = provider_view(v1)
    v2_view = provider_view(v2)
    assert isinstance(v1_view, PersonaProviderViewV1)
    assert isinstance(v2_view, PersonaProviderViewV2)
    assert provider_view_v1(v1).model_dump() == v1_view.model_dump()
    assert provider_view_v2(v2).model_dump() == v2_view.model_dump()
    assert "source_agent_md_hash" not in v2_view.model_dump()
    assert "compiler_version" not in v2_view.model_dump()
    assert "debate_strategy" not in v2_view.model_dump()
    assert "boundaries" not in v2_view.model_dump()


def test_confirmation_service_round_trips_v2_storage() -> None:
    from datetime import UTC, datetime

    from tests.test_wave4_persona import FakePersonaStore

    source = persona_v2_markdown()
    store = FakePersonaStore(
        PersonaVersionState(
            version_id="v2-version",
            agent_id="v2-agent",
            group_id="v2-group",
            agent_name="River Keeper",
            state="draft",
            revision=4,
            agent_md=source,
        )
    )
    store.members.add("v2-student")
    service = PersonaService(store)
    result = service.compile_draft("v2-version", expected_revision=4)

    assert result.compiled and result.persona_spec_hash
    assert result.compiler_version == PERSONA_COMPILER_VERSION_V2
    request = {
        "version_id": "v2-version",
        "expected_revision": 4,
        "raw_agent_md_hash": result.source_agent_md_hash,
        "persona_spec_hash": result.persona_spec_hash,
        "compiler_version": PERSONA_COMPILER_VERSION_V2,
    }
    from app.modules.agents.persona_service import PersonaConfirmationRequest

    confirmed = service.confirm(
        PersonaConfirmationRequest(**request), confirming_user_id="v2-student"
    )
    confirmed = confirmed.model_copy(
        update={"student_confirmed_at": confirmed.student_confirmed_at or datetime.now(UTC)}
    )
    assert is_persona_confirmed(confirmed)


@pytest.mark.parametrize("token", ("虚构", "共享", "River"))
def test_provider_projection_rejects_identity_tokens_without_echoing_them(token: str) -> None:
    result = compile_persona_v2(persona_v2_markdown(), expected_name="River Keeper")
    assert result.spec is not None
    with pytest.raises(PersonaProviderIdentityError) as error:
        provider_view(result.spec, student_identity_tokens=(token,))
    assert "persona_personal_identity_forbidden" in str(getattr(error.value, "code", ""))
    assert token not in str(error.value)
