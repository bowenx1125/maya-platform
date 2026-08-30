"""Persistence seams and eligibility rules for confirmed Personas.

This module intentionally does not import SQLAlchemy models.  The main window
can implement :class:`PersonaStore` against the current AgentVersion table and
the Wave 4 migration without making this domain service aware of a particular
ORM shape.  A store must update Persona columns with one revision CAS; it must
never create another raw ``agent_md`` value.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.modules.agents.persona import (
    PERSONA_COMPILER_VERSION,
    PersonaCompileResult,
    PersonaDiagnostic,
    PersonaSpecV1,
    canonical_json,
    compile_persona,
    persona_spec_hash,
    raw_agent_md_hash,
)

PERSONA_CONFIRMATION_REQUIRED = "persona_confirmation_required"
PERSONA_COMPILE_REQUIRED = "persona_compile_required"
PERSONA_COMPILE_FAILED = "persona_compile_failed"
PERSONA_INTEGRITY_MISMATCH = "persona_integrity_mismatch"
PERSONA_STORE_NOT_FOUND = "persona_version_not_found"


class PersonaDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonaVersionState(PersonaDomainModel):
    """Read-only port projection; raw text is borrowed, never persisted here."""

    version_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    state: Literal["draft", "published", "superseded"]
    revision: int = Field(ge=0)
    agent_md: str = Field(max_length=12_000)
    raw_agent_md_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec_json: str | None = None
    persona_spec_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    persona_compiler_version: str | None = None
    persona_confirmation_revision: int | None = Field(default=None, ge=0)
    student_confirmed_at: datetime | None = None
    # Internal only.  This field is never part of a provider/browser DTO.
    confirming_user_id: str | None = None
    # Server-only activation marker.  A missing value in an adapter projection
    # fails closed (the default is True); the SQL adapter supplies ``False``
    # explicitly for immutable pre-activation legacy rows.
    persona_required: bool = True


class PersonaConfirmationRequest(PersonaDomainModel):
    """Exact CAS material a student confirms in the current draft."""

    version_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    raw_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    compiler_version: Literal["persona_template_v1"] = PERSONA_COMPILER_VERSION


class PersonaCompilationWrite(PersonaDomainModel):
    """Store payload for success or failure; never includes raw Markdown."""

    version_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    raw_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    persona_spec_json: str | None = None
    persona_spec_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiler_version: Literal["persona_template_v1"] = PERSONA_COMPILER_VERSION
    diagnostics: tuple[PersonaDiagnostic, ...] = ()


class PersonaEligibility(PersonaDomainModel):
    """Safe publication/debate eligibility projection."""

    eligible: bool
    code: str | None = None
    agent_version_ids: tuple[str, ...] = ()


class PersonaDomainError(Exception):
    """Typed safe error for a route/service adapter to map to platform errors."""

    def __init__(
        self, code: str, message: str, details: Mapping[str, object] | None = None
    ) -> None:
        self.code = code
        self.message = message
        self.details = dict(details or {})
        super().__init__(message)


@runtime_checkable
class PersonaStore(Protocol):
    """Minimal persistence/membership port for the Persona state machine."""

    def get_persona_version(self, version_id: str) -> PersonaVersionState | None: ...

    def is_current_group_member(self, user_id: str, group_id: str) -> bool: ...

    def save_persona_compilation(self, payload: PersonaCompilationWrite) -> PersonaVersionState:
        """CAS by ``version_id`` + ``expected_revision``; clears old confirmation."""

        ...

    def confirm_persona(
        self,
        request: PersonaConfirmationRequest,
        confirming_user_id: str,
    ) -> PersonaVersionState:
        """CAS all request hashes/revision and records internal confirmer ID."""

        ...


class PersonaService:
    """Compile, confirm and gate Persona versions through a typed store port."""

    def __init__(self, store: PersonaStore) -> None:
        self.store = store

    def compile_draft(self, version_id: str, *, expected_revision: int) -> PersonaCompileResult:
        state = self._version(version_id)
        if state.state != "draft":
            raise PersonaDomainError(
                "version_immutable",
                "Published and superseded versions are immutable.",
            )
        if state.revision != expected_revision:
            raise _stale_revision(state.revision)
        result = compile_persona(state.agent_md, expected_name=state.agent_name)
        write = PersonaCompilationWrite(
            version_id=state.version_id,
            expected_revision=expected_revision,
            raw_agent_md_hash=result.source_agent_md_hash,
            persona_spec_json=result.canonical_json if result.compiled else None,
            persona_spec_hash=result.persona_spec_hash if result.compiled else None,
            compiler_version=PERSONA_COMPILER_VERSION,
            diagnostics=result.diagnostics,
        )
        # The store must clear any prior active Persona on failure.  It may
        # retain safe diagnostics in its own JSON column, but not the old spec.
        self.store.save_persona_compilation(write)
        return result

    def confirm(
        self,
        request: PersonaConfirmationRequest,
        *,
        confirming_user_id: str,
    ) -> PersonaVersionState:
        state = self._version(request.version_id)
        if state.state != "draft":
            raise PersonaDomainError(
                "version_immutable",
                "Published and superseded versions are immutable.",
            )
        if not self.store.is_current_group_member(confirming_user_id, state.group_id):
            raise PersonaDomainError(
                "forbidden",
                "A current group member must confirm the Persona.",
            )
        if state.revision != request.expected_revision:
            raise _stale_revision(state.revision)
        _assert_compiled_and_exact(state, request)
        return self.store.confirm_persona(request, confirming_user_id)

    def publication_eligibility(self, version_id: str) -> PersonaEligibility:
        return publication_eligibility(self._version(version_id))

    def debate_eligibility(self, versions: Iterable[PersonaVersionState]) -> PersonaEligibility:
        return debate_eligibility(versions)

    def _version(self, version_id: str) -> PersonaVersionState:
        state = self.store.get_persona_version(version_id)
        if state is None:
            raise PersonaDomainError(PERSONA_STORE_NOT_FOUND, "The Agent version was not found.")
        return state


def _assert_compiled_and_exact(
    state: PersonaVersionState,
    request: PersonaConfirmationRequest,
) -> None:
    if not state.persona_spec_json or not state.persona_spec_hash:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "Compile the current Persona before confirming it.",
        )
    if state.raw_agent_md_hash != request.raw_agent_md_hash:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "The Persona source changed; compile the current draft again.",
        )
    if state.persona_spec_hash != request.persona_spec_hash:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "The Persona preview changed; review the current draft again.",
        )
    if state.persona_compiler_version != request.compiler_version:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "The Persona compiler version is no longer current.",
        )
    try:
        parsed = PersonaSpecV1.model_validate(json.loads(state.persona_spec_json))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PersonaDomainError(
            PERSONA_INTEGRITY_MISMATCH,
            "The stored Persona preview is invalid.",
        ) from exc
    if (
        canonical_json(parsed) != state.persona_spec_json
        or persona_spec_hash(parsed) != state.persona_spec_hash
    ):
        raise PersonaDomainError(
            PERSONA_INTEGRITY_MISMATCH,
            "The stored Persona preview failed its integrity check.",
        )
    if raw_agent_md_hash(state.agent_md) != request.raw_agent_md_hash:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "The Persona source hash is stale; compile the current draft again.",
        )


def is_persona_confirmed(version: PersonaVersionState | Mapping[str, object] | object) -> bool:
    """Return true only when every confirmation binding is present and exact."""

    state = _as_mapping(version)
    raw = state.get("agent_md", "")
    raw_hash = state.get("raw_agent_md_hash")
    spec_json = state.get("persona_spec_json")
    spec_hash = state.get("persona_spec_hash")
    compiler_version = state.get("persona_compiler_version")
    revision = state.get("revision")
    confirmed_revision = state.get("persona_confirmation_revision")
    confirmed_at = state.get("student_confirmed_at")
    confirming_user_id = (
        state.get("confirming_user_id")
        or state.get("persona_confirming_user_id")
        or state.get("persona_confirmed_by_user_id")
    )
    if not isinstance(raw, str) or not isinstance(raw_hash, str) or not isinstance(spec_json, str):
        return False
    if not isinstance(spec_hash, str) or compiler_version != PERSONA_COMPILER_VERSION:
        return False
    if (
        not isinstance(revision, int)
        or confirmed_revision != revision
        or confirmed_at is None
        or not confirming_user_id
    ):
        return False
    if raw_agent_md_hash(raw) != raw_hash:
        return False
    try:
        parsed = PersonaSpecV1.model_validate(json.loads(spec_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return canonical_json(parsed) == spec_json and persona_spec_hash(parsed) == spec_hash


def publication_eligibility(
    version: PersonaVersionState | Mapping[str, object] | object,
) -> PersonaEligibility:
    """New Persona publications require a confirmed extraction."""

    state = _as_mapping(version)
    if not is_persona_required(version):
        return PersonaEligibility(eligible=True)
    if is_persona_confirmed(version):
        return PersonaEligibility(eligible=True)
    # Empty drafts still report the existing ``agent_md_missing`` blocker in
    # the Agent domain.  This function adds only the Persona-specific rule.
    if isinstance(state.get("agent_md"), str) and not str(state["agent_md"]).strip():
        return PersonaEligibility(eligible=False, code=PERSONA_COMPILE_REQUIRED)
    return PersonaEligibility(eligible=False, code=PERSONA_CONFIRMATION_REQUIRED)


def is_persona_required(
    version: PersonaVersionState | Mapping[str, object] | object,
) -> bool:
    """Read the server-only activation marker with a fail-closed default."""

    # ``None`` is what an older ORM projection returns before the migration
    # adds the non-null marker.  Treat it as required; only an explicit False
    # may identify an activation-before legacy row.
    return _as_mapping(version).get("persona_required") is not False


def persona_publication_blocker(
    version: PersonaVersionState | Mapping[str, object] | object,
) -> str | None:
    """Return the Persona-specific publish blocker.

    Once PersonaSpecV1 is active, every draft is in scope regardless of the
    shape of its raw AGENT.md.  In particular, this function must never infer
    legacy eligibility from Markdown headings or other authored text: that
    would let a malformed post-activation version bypass confirmation.
    """

    state = _as_mapping(version)
    raw = state.get("agent_md")
    # The activation marker is authoritative.  Never infer this boundary from
    # raw Markdown shape, diagnostics or nullable Persona columns.
    if not is_persona_required(version):
        return None
    if is_persona_confirmed(version):
        return None
    if not isinstance(raw, str) or not raw.strip():
        return PERSONA_COMPILE_REQUIRED
    diagnostics = state.get("persona_diagnostics_json") or state.get("persona_diagnostics")
    if diagnostics:
        return PERSONA_COMPILE_FAILED
    return PERSONA_CONFIRMATION_REQUIRED


def legacy_persona_version_ids(
    versions: Iterable[PersonaVersionState | Mapping[str, object] | object],
) -> tuple[str, ...]:
    """Return selected published IDs that cannot enter a new debate."""

    blocked: list[str] = []
    for version in versions:
        state = _as_mapping(version)
        if state.get("state") in {"published", "superseded"} and not is_persona_confirmed(version):
            version_id = state.get("version_id", state.get("id"))
            if isinstance(version_id, str) and version_id:
                blocked.append(version_id)
    return tuple(blocked)


def debate_eligibility(
    versions: Iterable[PersonaVersionState | Mapping[str, object] | object],
) -> PersonaEligibility:
    blocked = legacy_persona_version_ids(versions)
    if blocked:
        return PersonaEligibility(
            eligible=False,
            code=PERSONA_CONFIRMATION_REQUIRED,
            agent_version_ids=blocked,
        )
    return PersonaEligibility(eligible=True)


def require_debate_personas(
    versions: Iterable[PersonaVersionState | Mapping[str, object] | object],
) -> None:
    eligibility = debate_eligibility(versions)
    if not eligibility.eligible:
        raise PersonaDomainError(
            PERSONA_CONFIRMATION_REQUIRED,
            "Every selected Agent version must have a confirmed Persona.",
            {"agent_version_ids": list(eligibility.agent_version_ids)},
        )


def _as_mapping(value: PersonaVersionState | Mapping[str, object] | object) -> Mapping[str, object]:
    if isinstance(value, PersonaVersionState):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return value
    # Duck-typed ORM adapters are intentionally read-only.  Only known fields
    # are copied; a raw AGENT.md value is never written by this helper.
    names = (
        "version_id",
        "id",
        "state",
        "agent_md",
        "raw_agent_md_hash",
        "persona_spec_json",
        "persona_spec_hash",
        "persona_compiler_version",
        "persona_confirmation_revision",
        "student_confirmed_at",
        "confirming_user_id",
        "persona_confirming_user_id",
        "persona_confirmed_by_user_id",
        "persona_diagnostics_json",
        "persona_diagnostics",
        "revision",
        "persona_required",
    )
    return {name: getattr(value, name, None) for name in names}


def _stale_revision(current_revision: int) -> PersonaDomainError:
    return PersonaDomainError(
        "stale_revision",
        "The Agent draft revision is stale.",
        {"current_revision": current_revision},
    )


__all__ = [
    "PERSONA_COMPILE_FAILED",
    "PERSONA_COMPILE_REQUIRED",
    "PERSONA_CONFIRMATION_REQUIRED",
    "PERSONA_INTEGRITY_MISMATCH",
    "PersonaCompilationWrite",
    "PersonaConfirmationRequest",
    "PersonaDomainError",
    "PersonaEligibility",
    "PersonaService",
    "PersonaStore",
    "PersonaVersionState",
    "debate_eligibility",
    "is_persona_confirmed",
    "is_persona_required",
    "legacy_persona_version_ids",
    "publication_eligibility",
    "persona_publication_blocker",
    "require_debate_personas",
]
