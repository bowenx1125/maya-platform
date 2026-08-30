"""Wave 4 Persona compiler, confirmation seam and Mock causal acceptance."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.modules.agents.persona import (
    PERSONA_COMPILER_VERSION,
    PersonaCompileError,
    PersonaProviderIdentityError,
    canonical_json,
    compile_persona,
    compile_persona_or_raise,
    persona_spec_hash,
    provider_view,
    raw_agent_md_hash,
)
from app.modules.agents.persona_mock import (
    TEACHING_DIMENSIONS,
    bounded_teaching_dimensions_for_persona,
    compare_contrasting_personas,
    contrasting_persona_fixtures,
)
from app.modules.agents.persona_service import (
    PERSONA_CONFIRMATION_REQUIRED,
    PersonaCompilationWrite,
    PersonaConfirmationRequest,
    PersonaDomainError,
    PersonaService,
    PersonaVersionState,
    debate_eligibility,
    is_persona_confirmed,
    persona_publication_blocker,
    publication_eligibility,
)

VALID_MD = """# River Keeper

## Identity

- Role: Watershed steward
- Historical or cultural context: A fictional community keeper of shared water memory.

## Cultural lens

- Intergenerational responsibility
- Place-based memory

## Core values

- Reciprocity
- Patience

## Initial position

Protect shared resources through careful, long-term stewardship.

It accepts practical trade-offs when the evidence is incomplete.

## Speaking style

- Tone: Calm and reflective
- Argument pattern: Start with context, then weigh consequences
- Concession style: Acknowledge valid concerns before qualifying them
- Question style: Ask one open question about long-term effects

## Debate strategy

- Connect present choices to future stewardship

## Boundaries

- Do not claim evidence outside the snapshot
"""


def test_compile_is_strict_and_canonical() -> None:
    result = compile_persona(VALID_MD, expected_name="River Keeper")
    assert result.compiled
    assert result.spec is not None
    assert result.spec.source_agent_md_hash == raw_agent_md_hash(VALID_MD)
    assert result.persona_spec_hash == persona_spec_hash(result.spec)
    assert result.canonical_json == canonical_json(result.spec)
    assert json.loads(result.canonical_json or "{}") == result.spec.model_dump(mode="json")
    assert result.spec.identity.name == "River Keeper"
    assert result.spec.cultural_lens == ("Intergenerational responsibility", "Place-based memory")
    assert "source_agent_md_hash" not in provider_view(result.spec).model_dump()
    assert "compiler_version" not in provider_view(result.spec).model_dump()
    with pytest.raises(PersonaProviderIdentityError) as identity_error:
        provider_view(result.spec, student_identity_tokens=("fictional community",))
    assert identity_error.value.code == "persona_personal_identity_forbidden"


def test_hash_normalizes_line_endings_but_not_semantics() -> None:
    crlf = VALID_MD.replace("\n", "\r\n")
    assert raw_agent_md_hash(crlf) == raw_agent_md_hash(VALID_MD)
    assert (
        compile_persona(crlf, expected_name="River Keeper").canonical_json
        == compile_persona(VALID_MD, expected_name="River Keeper").canonical_json
    )


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        ("# Unknown\n\n" + VALID_MD, "unexpected_heading"),
        (VALID_MD.replace("## Core values", "## Extra\n\n## Core values"), "section_order"),
        (VALID_MD.replace("- Patience", "  - Patience"), "flat_list_required"),
        (VALID_MD.replace("- Reciprocity", "- Reciprocity\n- reciprocity"), "duplicate_item"),
        (
            VALID_MD.replace("- Role: Watershed steward", "- role: Watershed steward"),
            "unknown_field",
        ),
        (VALID_MD.replace("Protect shared", "- Protect shared"), "plain_paragraph_required"),
        (
            VALID_MD.replace(
                "shared water memory.", "shared [water](https://example.test) memory."
            ),
            "unsupported_markup",
        ),
        (VALID_MD + "\nUnexpected prose", "flat_list_required"),
        (VALID_MD.replace("- Tone: Calm and reflective", "- Tone:"), "value_missing"),
    ],
)
def test_compiler_rejects_unknown_or_unsafe_content(edit: str, code: str) -> None:
    result = compile_persona(edit, expected_name="River Keeper")
    assert not result.compiled
    assert code in {item.code for item in result.diagnostics}
    # Diagnostics are safe and never echo authored content.
    assert all("https://" not in item.message for item in result.diagnostics)


def test_inline_emphasis_and_code_are_visible_text_only() -> None:
    result = compile_persona(
        VALID_MD.replace("Calm and reflective", "**Calm** and `reflective`").replace(
            "Watershed steward", "*Watershed* steward"
        ),
        expected_name="River Keeper",
    )
    assert result.compiled
    assert result.spec is not None
    assert result.spec.speaking_style.tone == "Calm and reflective"
    assert result.spec.identity.role == "Watershed steward"


def test_compile_or_raise_exposes_only_safe_diagnostic() -> None:
    with pytest.raises(PersonaCompileError) as raised:
        compile_persona_or_raise("# River Keeper")
    assert raised.value.result.diagnostics
    assert "River Keeper" not in raised.value.result.diagnostics[0].message


class FakePersonaStore:
    def __init__(self, state: PersonaVersionState) -> None:
        self.state = state
        self.members: set[str] = {"student-1"}
        self.compilations: list[PersonaCompilationWrite] = []
        self.confirmations: list[tuple[PersonaConfirmationRequest, str]] = []

    def get_persona_version(self, version_id: str) -> PersonaVersionState | None:
        return self.state if self.state.version_id == version_id else None

    def is_current_group_member(self, user_id: str, group_id: str) -> bool:
        return user_id in self.members and group_id == self.state.group_id

    def save_persona_compilation(self, payload: PersonaCompilationWrite) -> PersonaVersionState:
        if payload.expected_revision != self.state.revision:
            raise PersonaDomainError(
                "stale_revision", "stale", {"current_revision": self.state.revision}
            )
        self.compilations.append(payload)
        self.state = self.state.model_copy(
            update={
                "raw_agent_md_hash": payload.raw_agent_md_hash,
                "persona_spec_json": payload.persona_spec_json,
                "persona_spec_hash": payload.persona_spec_hash,
                "persona_compiler_version": payload.compiler_version,
                "persona_confirmation_revision": None,
                "student_confirmed_at": None,
                "confirming_user_id": None,
            }
        )
        return self.state

    def confirm_persona(
        self,
        request: PersonaConfirmationRequest,
        confirming_user_id: str,
    ) -> PersonaVersionState:
        if request.expected_revision != self.state.revision:
            raise PersonaDomainError(
                "stale_revision", "stale", {"current_revision": self.state.revision}
            )
        self.confirmations.append((request, confirming_user_id))
        self.state = self.state.model_copy(
            update={
                "persona_confirmation_revision": self.state.revision,
                "student_confirmed_at": datetime.now(UTC),
                "confirming_user_id": confirming_user_id,
            }
        )
        return self.state


def _state() -> PersonaVersionState:
    return PersonaVersionState(
        version_id="version-1",
        agent_id="agent-1",
        group_id="group-1",
        agent_name="River Keeper",
        state="draft",
        revision=3,
        agent_md=VALID_MD,
    )


def test_compile_confirmation_service_uses_exact_revision_and_hash_cas() -> None:
    store = FakePersonaStore(_state())
    service = PersonaService(store)
    compiled = service.compile_draft("version-1", expected_revision=3)
    assert compiled.compiled
    assert len(store.compilations) == 1
    write = store.compilations[-1]
    assert "agent_md" not in write.model_dump()
    request = PersonaConfirmationRequest(
        version_id="version-1",
        expected_revision=3,
        raw_agent_md_hash=write.raw_agent_md_hash,
        persona_spec_hash=write.persona_spec_hash or "0" * 64,
        compiler_version=PERSONA_COMPILER_VERSION,
    )
    confirmed = service.confirm(request, confirming_user_id="student-1")
    assert confirmed.persona_confirmation_revision == 3
    assert is_persona_confirmed(confirmed)


def test_confirmation_rejects_nonmember_or_stale_hash_without_store_write() -> None:
    store = FakePersonaStore(_state())
    service = PersonaService(store)
    compiled = service.compile_draft("version-1", expected_revision=3)
    assert compiled.persona_spec_hash
    request = PersonaConfirmationRequest(
        version_id="version-1",
        expected_revision=3,
        raw_agent_md_hash=compiled.source_agent_md_hash,
        persona_spec_hash=compiled.persona_spec_hash,
    )
    with pytest.raises(PersonaDomainError) as forbidden:
        service.confirm(request, confirming_user_id="student-2")
    assert forbidden.value.code == "forbidden"
    before = len(store.confirmations)
    stale = request.model_copy(update={"raw_agent_md_hash": "sha256:" + "f" * 64})
    with pytest.raises(PersonaDomainError) as required:
        service.confirm(stale, confirming_user_id="student-1")
    assert required.value.code == PERSONA_CONFIRMATION_REQUIRED
    assert len(store.confirmations) == before


def test_failure_clears_prior_compilation_through_same_write_port() -> None:
    store = FakePersonaStore(_state())
    service = PersonaService(store)
    first = service.compile_draft("version-1", expected_revision=3)
    assert first.compiled
    store.state = store.state.model_copy(update={"agent_md": "# River Keeper\ninvalid"})
    failed = service.compile_draft("version-1", expected_revision=3)
    assert not failed.compiled
    assert store.compilations[-1].persona_spec_json is None
    assert store.state.persona_spec_json is None


def test_publication_and_debate_eligibility_have_stable_legacy_blocker() -> None:
    legacy = _state().model_copy(update={"state": "published"})
    assert publication_eligibility(legacy).code == PERSONA_CONFIRMATION_REQUIRED
    eligibility = debate_eligibility([legacy])
    assert not eligibility.eligible
    assert eligibility.code == PERSONA_CONFIRMATION_REQUIRED
    assert eligibility.agent_version_ids == ("version-1",)

    store = FakePersonaStore(_state())
    service = PersonaService(store)
    compiled = service.compile_draft("version-1", expected_revision=3)
    assert compiled.persona_spec_hash
    service.confirm(
        PersonaConfirmationRequest(
            version_id="version-1",
            expected_revision=3,
            raw_agent_md_hash=compiled.source_agent_md_hash,
            persona_spec_hash=compiled.persona_spec_hash,
        ),
        confirming_user_id="student-1",
    )
    published = store.state.model_copy(update={"state": "published"})
    assert publication_eligibility(published).eligible
    assert debate_eligibility([published]).eligible


def test_publication_scope_uses_server_marker_not_raw_markdown_shape() -> None:
    # A pre-activation published row may remain readable as legacy history,
    # but its marker must be the only reason it is outside the new publish
    # gate.  Raw text shape is deliberately irrelevant.
    legacy = _state().model_copy(
        update={
            "state": "published",
            "agent_md": "arbitrary legacy text",
            "persona_required": False,
        }
    )
    assert persona_publication_blocker(legacy) is None
    assert publication_eligibility(legacy).eligible

    post_activation = legacy.model_copy(update={"state": "draft", "persona_required": True})
    assert persona_publication_blocker(post_activation) == PERSONA_CONFIRMATION_REQUIRED

    malformed = post_activation.model_copy(update={"agent_md": "not a Persona template"})
    assert persona_publication_blocker(malformed) == PERSONA_CONFIRMATION_REQUIRED


def test_contrasting_mock_changes_all_allowed_dimensions_only() -> None:
    comparison = compare_contrasting_personas(
        topic="How should a community share a scarce resource?",
        evidence_ids=("receipt-a", "receipt-b"),
        stance="support",
        seed=7,
    )
    assert comparison.changed_dimensions == TEACHING_DIMENSIONS
    assert comparison.all_invariants_equal
    assert comparison.first.evidence_ids == ("receipt-a", "receipt-b")
    assert comparison.second.evidence_ids == comparison.first.evidence_ids
    assert comparison.first.stance == comparison.second.stance == "support"
    assert "general reasoning" not in comparison.first.speech.lower()


def test_mock_without_evidence_never_invents_a_source() -> None:
    comparison = compare_contrasting_personas(evidence_ids=())
    assert comparison.first.evidence_ids == ()
    assert comparison.second.evidence_ids == ()
    assert "general reasoning" in comparison.first.speech.lower()
    assert "receipt" not in comparison.first.speech.lower()


def test_actual_provider_prompt_mock_uses_six_persona_dimensions_only() -> None:
    from app.modules.debates.generation import (
        GenerationContext,
        MutualLearningPolicy,
        ParticipantContext,
        SnapshotRetrievalReceipt,
        build_provider_prompt,
    )
    from app.providers.llm import MockLLMProvider

    first, second = contrasting_persona_fixtures()
    people = tuple(
        ParticipantContext(
            participant_id=f"participant-{index}",
            agent_id=f"agent-{index}",
            agent_name=f"Agent {index}",
            slot=chr(65 + index),
            order_index=index,
            snapshot_id="snapshot-shared",
            persona=persona,
            persona_spec_hash=persona_spec_hash(persona),
        )
        for index, persona in enumerate((first, second))
    )
    plans = MutualLearningPolicy().plan(people, round_count=2)
    receipt = SnapshotRetrievalReceipt(
        snapshot_id="snapshot-shared",
        query_kind="viewpoint",
        query_hash="query-hash",
        threshold_key="strict",
        rank=1,
        score=1.0,
        chunk_id="chunk-shared",
        source_filename="source.md",
        text="A bounded current snapshot passage.",
        evidence_id="receipt-shared",
    )
    prompts = []
    results = []
    for index, persona in enumerate((first, second)):
        prompt = build_provider_prompt(
            GenerationContext(
                "mock-persona-debate",
                "How should a community share a scarce resource?",
                plans[index],
                people[index],
                people,
            ),
            persona=persona,
            receipts=(receipt,),
            queries=(),
        )
        prompts.append(prompt)
        results.append(MockLLMProvider().generate_turn(prompt))

    assert results[0].speech != results[1].speech
    assert results[0].used_evidence_id == results[1].used_evidence_id == ["receipt-shared"]
    assert prompts[0].request.rule_set_id == prompts[1].request.rule_set_id
    assert prompts[0].request.output_schema_id == prompts[1].request.output_schema_id
    for persona, result in zip((first, second), results, strict=True):
        projection = bounded_teaching_dimensions_for_persona(persona)
        assert all(sentence in result.speech for sentence in projection.model_dump().values())
