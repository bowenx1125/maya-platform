"""Deterministic, extraction-only versioned Persona compiler.

The compiler deliberately has no database, provider, filesystem or network
dependency.  ``AGENT.md`` remains the only raw authored value; this module
returns a canonical structured view that a persistence adapter may store next
to the existing raw value.

The Markdown grammar is intentionally small.  It is not a general Markdown
parser: accepting an unknown construct would silently change the meaning of a
student's authorship, so unknown content is a safe compile diagnostic.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

PERSONA_SCHEMA_VERSION_V1: Literal["persona_spec_v1"] = "persona_spec_v1"
PERSONA_SCHEMA_VERSION_V2: Literal["persona_spec_v2"] = "persona_spec_v2"
PERSONA_PROVIDER_VIEW_VERSION_V1: Literal["persona_provider_view_v1"] = "persona_provider_view_v1"
PERSONA_PROVIDER_VIEW_VERSION_V2: Literal["persona_provider_view_v2"] = "persona_provider_view_v2"
PERSONA_COMPILER_VERSION_V1: Literal["persona_template_v1"] = "persona_template_v1"
PERSONA_COMPILER_VERSION_V2: Literal["persona_template_v2"] = "persona_template_v2"

# The unsuffixed constants are retained as V1 aliases.  Existing published
# rows and consumers use these names, and changing them would make their
# canonical hashes or confirmation material appear to change.
PERSONA_SCHEMA_VERSION = PERSONA_SCHEMA_VERSION_V1
PERSONA_PROVIDER_VIEW_VERSION = PERSONA_PROVIDER_VIEW_VERSION_V1
PERSONA_COMPILER_VERSION = PERSONA_COMPILER_VERSION_V1
DEFAULT_PERSONA_SCHEMA_VERSION = PERSONA_SCHEMA_VERSION_V2
DEFAULT_PERSONA_PROVIDER_VIEW_VERSION = PERSONA_PROVIDER_VIEW_VERSION_V2
DEFAULT_PERSONA_COMPILER_VERSION = PERSONA_COMPILER_VERSION_V2
CURRENT_PERSONA_SCHEMA_VERSION = DEFAULT_PERSONA_SCHEMA_VERSION
CURRENT_PERSONA_PROVIDER_VIEW_VERSION = DEFAULT_PERSONA_PROVIDER_VIEW_VERSION
CURRENT_PERSONA_COMPILER_VERSION = DEFAULT_PERSONA_COMPILER_VERSION

PersonaSchemaVersion = Literal["persona_spec_v1", "persona_spec_v2"]
PersonaProviderViewVersion = Literal["persona_provider_view_v1", "persona_provider_view_v2"]
PersonaCompilerVersion = Literal["persona_template_v1", "persona_template_v2"]
MAX_AGENT_MD_CHARS = 12_000

_SECTIONS = (
    "Identity",
    "Cultural lens",
    "Core values",
    "Initial position",
    "Speaking style",
    "Debate strategy",
    "Boundaries",
)
_V2_SECTIONS = (
    "Identity",
    "Cultural lens",
    "Core values",
    "Initial position",
    "Speaking style",
)
_LIST_SECTIONS = {"Cultural lens", "Core values", "Debate strategy", "Boundaries"}
_SCALAR_SECTIONS = {
    "Identity": {
        "Role": ("role", 120),
        "Historical or cultural context": ("historical_or_cultural_context", 1_000),
    },
    "Speaking style": {
        "Tone": ("tone", 240),
        "Argument pattern": ("argument_pattern", 240),
        "Concession style": ("concession_style", 240),
        "Question style": ("question_style", 240),
    },
}
_HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
_HTML_RE = re.compile(r"<[^>\n]*>")
_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\([^)\n]+\)")
_REFERENCE_LINK_RE = re.compile(r"!?\[[^\]\n]+\](?:\[[^\]\n]*\]|:)")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)


class PersonaClosedModel(BaseModel):
    """Closed immutable domain DTO base used by the Persona contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PersonaIdentity(PersonaClosedModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    historical_or_cultural_context: str = Field(min_length=1, max_length=1_000)


class PersonaSpeakingStyle(PersonaClosedModel):
    tone: str = Field(min_length=1, max_length=240)
    argument_pattern: str = Field(min_length=1, max_length=240)
    concession_style: str = Field(min_length=1, max_length=240)
    question_style: str = Field(min_length=1, max_length=240)


class PersonaSpecV1(PersonaClosedModel):
    """Canonical closed stored schema from PERSONA_SPEC_V1."""

    schema_version: Literal["persona_spec_v1"] = PERSONA_SCHEMA_VERSION
    identity: PersonaIdentity
    cultural_lens: tuple[str, ...] = Field(min_length=1, max_length=8)
    core_values: tuple[str, ...] = Field(min_length=1, max_length=8)
    initial_position: str = Field(min_length=1, max_length=1_000)
    speaking_style: PersonaSpeakingStyle
    debate_strategy: tuple[str, ...] = Field(min_length=1, max_length=8)
    boundaries: tuple[str, ...] = Field(min_length=1, max_length=8)
    source_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    compiler_version: Literal["persona_template_v1"] = PERSONA_COMPILER_VERSION


class PersonaSpecV2(PersonaClosedModel):
    """Canonical stored schema for the five-section Persona template.

    V2 intentionally has no ``debate_strategy`` or ``boundaries`` fields.
    Platform rules and debate scheduling remain server-owned, so retaining
    those headings as empty compatibility values would misrepresent authorship
    and make the new schema indistinguishable from a legacy V1 projection.
    """

    schema_version: Literal["persona_spec_v2"] = PERSONA_SCHEMA_VERSION_V2
    identity: PersonaIdentity
    cultural_lens: tuple[str, ...] = Field(min_length=1, max_length=8)
    core_values: tuple[str, ...] = Field(min_length=1, max_length=8)
    initial_position: str = Field(min_length=1, max_length=1_000)
    speaking_style: PersonaSpeakingStyle
    source_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    compiler_version: Literal["persona_template_v2"] = PERSONA_COMPILER_VERSION_V2


class PersonaProviderViewV1(PersonaClosedModel):
    """Provider-safe view: semantic fields only, with no audit/hash fields."""

    schema_version: Literal["persona_provider_view_v1"] = PERSONA_PROVIDER_VIEW_VERSION
    identity: PersonaIdentity
    cultural_lens: tuple[str, ...] = Field(min_length=1, max_length=8)
    core_values: tuple[str, ...] = Field(min_length=1, max_length=8)
    initial_position: str = Field(min_length=1, max_length=1_000)
    speaking_style: PersonaSpeakingStyle
    debate_strategy: tuple[str, ...] = Field(min_length=1, max_length=8)
    boundaries: tuple[str, ...] = Field(min_length=1, max_length=8)


class PersonaProviderViewV2(PersonaClosedModel):
    """Provider-safe semantic view for a five-section Persona."""

    schema_version: Literal["persona_provider_view_v2"] = PERSONA_PROVIDER_VIEW_VERSION_V2
    identity: PersonaIdentity
    cultural_lens: tuple[str, ...] = Field(min_length=1, max_length=8)
    core_values: tuple[str, ...] = Field(min_length=1, max_length=8)
    initial_position: str = Field(min_length=1, max_length=1_000)
    speaking_style: PersonaSpeakingStyle


PersonaSpecVersion = PersonaSpecV1 | PersonaSpecV2
PersonaProviderViewVersionDTO = PersonaProviderViewV1 | PersonaProviderViewV2


class PersonaDiagnostic(PersonaClosedModel):
    """Safe compile diagnostic; it never includes source text or secrets."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    message: str = Field(min_length=1, max_length=240)
    line: int | None = Field(default=None, ge=1)
    field: str | None = Field(default=None, max_length=80)


class PersonaCompileResult(PersonaClosedModel):
    """Deterministic compiler result suitable for a draft preview."""

    ok: bool
    spec: PersonaSpecVersion | None = None
    canonical_json: str | None = None
    persona_spec_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_agent_md_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    compiler_version: PersonaCompilerVersion = PERSONA_COMPILER_VERSION
    diagnostics: tuple[PersonaDiagnostic, ...] = ()

    @property
    def compiled(self) -> bool:
        """Readable alias used by adapters without duplicating state."""

        return self.ok and self.spec is not None

    @property
    def persona_spec_json(self) -> str | None:
        """Stored-column naming alias for the canonical JSON payload."""

        return self.canonical_json


class PersonaCompileError(ValueError):
    """Raised only by the explicit ``compile_persona_or_raise`` boundary."""

    def __init__(self, result: PersonaCompileResult) -> None:
        self.result = result
        message = (
            result.diagnostics[0].message if result.diagnostics else "Persona compilation failed."
        )
        super().__init__(message)


class PersonaProviderIdentityError(ValueError):
    """Raised when a caller attempts to export personal identity in Persona."""

    code = "persona_personal_identity_forbidden"

    def __init__(self) -> None:
        # Deliberately do not echo the matching token/name in the exception.
        super().__init__("Personal identity cannot be included in a Provider Persona view.")


class PersonaCompiler:
    """Small object seam for dependency injection in route/tests."""

    def __init__(
        self, *, compiler_version: PersonaCompilerVersion = DEFAULT_PERSONA_COMPILER_VERSION
    ) -> None:
        if compiler_version not in {
            PERSONA_COMPILER_VERSION_V1,
            PERSONA_COMPILER_VERSION_V2,
        }:
            raise ValueError("Unsupported Persona compiler version.")
        self.compiler_version = compiler_version

    def compile(
        self,
        source: str | bytes,
        *,
        expected_name: str | None = None,
        agent_name: str | None = None,
    ) -> PersonaCompileResult:
        return compile_persona(
            source,
            expected_name=expected_name,
            agent_name=agent_name,
            compiler_version=self.compiler_version,
        )


@dataclass(frozen=True)
class _Line:
    number: int
    text: str


def normalize_agent_md(source: str | bytes) -> str:
    """Normalize only line endings and decode bytes strictly as UTF-8.

    The source is not otherwise rewritten before hashing.  In particular, the
    compiler does not trim authored prose or normalize Unicode characters.
    """

    if isinstance(source, bytes):
        text = source.decode("utf-8", errors="strict")
    elif isinstance(source, str):
        text = source
    else:
        raise TypeError("AGENT.md must be text or UTF-8 bytes")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def raw_agent_md_hash(source: str | bytes) -> str:
    """Return the contract's tagged SHA-256 over normalized UTF-8 bytes."""

    normalized = normalize_agent_md(source)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Naming aliases make the pure hashing boundary explicit to adapters without
# creating a second implementation or a second source-text field.
hash_agent_md = raw_agent_md_hash


def canonical_json_bytes(value: BaseModel | Mapping[str, Any] | Sequence[Any] | Any) -> bytes:
    """Encode JSON canonically for all persisted Persona hashes."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def canonical_json(value: BaseModel | Mapping[str, Any] | Sequence[Any] | Any) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def parse_persona_spec(value: str | Mapping[str, Any] | PersonaSpecVersion) -> PersonaSpecVersion:
    """Parse one stored canonical Persona payload without version guessing.

    The discriminator is persisted in the JSON itself.  This keeps V1 hashes
    stable and prevents a V2 payload from being coerced into a legacy shape by
    dropping its missing sections or inventing removed fields.
    """

    if isinstance(value, (PersonaSpecV1, PersonaSpecV2)):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
    elif isinstance(value, Mapping):
        decoded = value
    else:
        raise TypeError("Stored Persona must be canonical JSON or a mapping.")
    if not isinstance(decoded, Mapping):
        raise ValueError("Stored Persona must be a JSON object.")
    version = decoded.get("schema_version")
    if version == PERSONA_SCHEMA_VERSION_V1:
        return PersonaSpecV1.model_validate(decoded)
    if version == PERSONA_SCHEMA_VERSION_V2:
        return PersonaSpecV2.model_validate(decoded)
    raise ValueError("Stored Persona schema version is unsupported.")


parse_stored_persona = parse_persona_spec


def diagnostics_json(diagnostics: Sequence[PersonaDiagnostic]) -> str:
    """Encode safe compile diagnostics for an optional persistence column."""

    return canonical_json([item.model_dump(mode="json") for item in diagnostics])


def persona_spec_hash(spec: PersonaSpecVersion | Mapping[str, Any]) -> str:
    """Hash canonical PersonaSpec JSON as an untagged lower-case SHA-256."""

    return hashlib.sha256(canonical_json_bytes(spec)).hexdigest()


hash_persona_spec = persona_spec_hash


PersonaSpec = PersonaSpecV1
ProviderPersonaView = PersonaProviderViewV1


def provider_view(
    spec: PersonaSpecVersion,
    *,
    student_identity_tokens: Sequence[str] = (),
) -> PersonaProviderViewVersionDTO:
    """Drop audit fields and reject caller-supplied personal identity tokens.

    Agent names are fictional/cultural labels and remain part of the semantic
    view.  An authenticated adapter may pass the current student's name,
    user-id, nickname and other approved identity tokens here; any occurrence
    in a Persona field blocks export without revealing which value matched.
    """

    semantic = (
        spec.identity.name,
        spec.identity.role,
        spec.identity.historical_or_cultural_context,
        *spec.cultural_lens,
        *spec.core_values,
        spec.initial_position,
        spec.speaking_style.tone,
        spec.speaking_style.argument_pattern,
        spec.speaking_style.concession_style,
        spec.speaking_style.question_style,
    )
    if isinstance(spec, PersonaSpecV1):
        semantic = (*semantic, *spec.debate_strategy, *spec.boundaries)
    for token in student_identity_tokens:
        normalized_token = token.strip().casefold()
        if normalized_token and any(normalized_token in item.casefold() for item in semantic):
            raise PersonaProviderIdentityError()

    if isinstance(spec, PersonaSpecV2):
        return PersonaProviderViewV2(
            identity=spec.identity,
            cultural_lens=spec.cultural_lens,
            core_values=spec.core_values,
            initial_position=spec.initial_position,
            speaking_style=spec.speaking_style,
        )
    return PersonaProviderViewV1(
        identity=spec.identity,
        cultural_lens=spec.cultural_lens,
        core_values=spec.core_values,
        initial_position=spec.initial_position,
        speaking_style=spec.speaking_style,
        debate_strategy=spec.debate_strategy,
        boundaries=spec.boundaries,
    )


def provider_view_v1(
    spec: PersonaSpecV1,
    *,
    student_identity_tokens: Sequence[str] = (),
) -> PersonaProviderViewV1:
    """Return the legacy V1 provider projection without changing its shape."""

    view = provider_view(spec, student_identity_tokens=student_identity_tokens)
    if not isinstance(view, PersonaProviderViewV1):  # pragma: no cover - closed DTO
        raise TypeError("V1 Persona projection returned an unexpected version.")
    return view


def provider_view_v2(
    spec: PersonaSpecV2,
    *,
    student_identity_tokens: Sequence[str] = (),
) -> PersonaProviderViewV2:
    """Return the five-section provider projection with no legacy fields."""

    view = provider_view(spec, student_identity_tokens=student_identity_tokens)
    if not isinstance(view, PersonaProviderViewV2):  # pragma: no cover - closed DTO
        raise TypeError("V2 Persona projection returned an unexpected version.")
    return view


def _compile_persona_v1(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
) -> PersonaCompileResult:
    """Compile strict Persona Markdown without invention or omission.

    ``expected_name`` (or its compatibility alias ``agent_name``) is supplied
    by the Agent aggregate when available.  For standalone previews, the H1 is
    the display name and is still validated as a single required H1.
    """

    source_hash: str
    try:
        normalized = normalize_agent_md(source)
        source_hash = raw_agent_md_hash(normalized)
    except UnicodeDecodeError:
        return _failed_result(
            "invalid_utf8", "AGENT.md must be valid UTF-8.", source_hash="sha256:" + "0" * 64
        )
    except TypeError:
        return _failed_result(
            "invalid_source",
            "AGENT.md must be text or UTF-8 bytes.",
            source_hash="sha256:" + "0" * 64,
        )
    if agent_name is not None:
        if expected_name is not None and expected_name.strip() != agent_name.strip():
            return _failed_result(
                "conflicting_expected_name",
                "The expected Agent name is ambiguous.",
                source_hash=source_hash,
            )
        expected_name = agent_name

    diagnostics: list[PersonaDiagnostic] = []
    if len(normalized) > MAX_AGENT_MD_CHARS:
        diagnostics.append(
            _diagnostic(
                "document_too_large",
                "AGENT.md exceeds the 12,000 character limit.",
            )
        )
    invalid_control = _first_disallowed_control(normalized)
    if invalid_control is not None:
        position, _character = invalid_control
        diagnostics.append(
            _diagnostic(
                "disallowed_control_character",
                "AGENT.md contains a disallowed control or format character.",
                line=normalized.count("\n", 0, position) + 1,
            )
        )
    if diagnostics:
        return _failed_result(*diagnostics, source_hash=source_hash)

    stripped = normalized.strip()
    if not stripped:
        return _failed_result(
            "empty_document", "AGENT.md must contain the Persona template.", source_hash=source_hash
        )
    lines = [_Line(index, text) for index, text in enumerate(stripped.split("\n"), start=1)]
    h1 = lines[0].text.strip()
    if not h1.startswith("# ") or h1.startswith("## "):
        return _failed_result(
            "h1_required",
            "AGENT.md must start with exactly one H1 Agent name.",
            source_hash=source_hash,
        )
    h1_text = _clean_inline(h1[2:].strip())
    if not h1_text:
        return _failed_result(
            "name_empty",
            "The Agent display name cannot be empty.",
            line=lines[0].number,
            source_hash=source_hash,
        )
    if len(h1_text) > 80:
        return _failed_result(
            "name_too_long",
            "The Agent display name exceeds 80 characters.",
            line=lines[0].number,
            source_hash=source_hash,
        )
    if _has_forbidden_markup(h1[2:].strip()):
        return _failed_result(
            "unsupported_markup",
            "Links and HTML are not allowed in Persona content.",
            line=lines[0].number,
            source_hash=source_hash,
        )
    extra_heading = next(
        (
            line
            for line in lines[1:]
            if _HEADING_RE.match(line.text.strip()) and not line.text.strip().startswith("## ")
        ),
        None,
    )
    if extra_heading is not None:
        return _failed_result(
            "unexpected_heading",
            "Only the required H1 and H2 headings are allowed.",
            line=extra_heading.number,
            source_hash=source_hash,
        )
    if expected_name is not None and _clean_inline(expected_name.strip()) != h1_text:
        return _failed_result(
            "name_mismatch",
            "The H1 must match the Agent display name.",
            line=lines[0].number,
            field="identity.name",
            source_hash=source_hash,
        )

    sections, parse_diagnostics = _parse_sections(lines[1:])
    diagnostics.extend(parse_diagnostics)
    if diagnostics:
        return _failed_result(*diagnostics, source_hash=source_hash)

    values: dict[str, Any] = {
        "identity": {"name": h1_text},
        "cultural_lens": (),
        "core_values": (),
        "initial_position": "",
        "speaking_style": {},
        "debate_strategy": (),
        "boundaries": (),
        "source_agent_md_hash": source_hash,
        "compiler_version": PERSONA_COMPILER_VERSION,
    }
    for section in _SECTIONS:
        section_lines = sections[section]
        if section in _LIST_SECTIONS:
            parsed, section_errors = _parse_list(section, section_lines)
            diagnostics.extend(section_errors)
            values[_section_field(section)] = tuple(parsed)
        elif section == "Initial position":
            initial, section_errors = _parse_initial_position(section_lines)
            diagnostics.extend(section_errors)
            values["initial_position"] = initial
        else:
            parsed_scalars, section_errors = _parse_scalar_section(section, section_lines)
            diagnostics.extend(section_errors)
            if section == "Identity":
                values["identity"].update(parsed_scalars)
            else:
                values["speaking_style"] = parsed_scalars
    if diagnostics:
        return _failed_result(*diagnostics, source_hash=source_hash)
    try:
        spec = PersonaSpecV1.model_validate(values)
    except ValueError:
        # Every user-facing grammar failure above is safe and deterministic;
        # this guard prevents a future DTO limit change from exposing internals.
        return _failed_result(
            "invalid_persona_schema",
            "The Persona content does not satisfy the closed schema.",
            source_hash=source_hash,
        )
    serialized = canonical_json(spec)
    return PersonaCompileResult(
        ok=True,
        spec=spec,
        canonical_json=serialized,
        persona_spec_hash=persona_spec_hash(spec),
        source_agent_md_hash=source_hash,
        diagnostics=(),
    )


def compile_persona_v2(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
) -> PersonaCompileResult:
    """Compile the current five-section Persona template.

    V2 is deliberately a separate compiler boundary.  It makes it impossible
    for a caller to satisfy the new template by silently filling removed V1
    fields with empty or synthetic values, while preserving the exact V1
    compiler for immutable historical rows.
    """

    source_hash: str
    try:
        normalized = normalize_agent_md(source)
        source_hash = raw_agent_md_hash(normalized)
    except UnicodeDecodeError:
        return _failed_result(
            "invalid_utf8",
            "AGENT.md must be valid UTF-8.",
            source_hash="sha256:" + "0" * 64,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    except TypeError:
        return _failed_result(
            "invalid_source",
            "AGENT.md must be text or UTF-8 bytes.",
            source_hash="sha256:" + "0" * 64,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    if agent_name is not None:
        if expected_name is not None and expected_name.strip() != agent_name.strip():
            return _failed_result(
                "conflicting_expected_name",
                "The expected Agent name is ambiguous.",
                source_hash=source_hash,
                compiler_version=PERSONA_COMPILER_VERSION_V2,
            )
        expected_name = agent_name

    diagnostics: list[PersonaDiagnostic] = []
    if len(normalized) > MAX_AGENT_MD_CHARS:
        diagnostics.append(
            _diagnostic("document_too_large", "AGENT.md exceeds the 12,000 character limit.")
        )
    invalid_control = _first_disallowed_control(normalized)
    if invalid_control is not None:
        position, _character = invalid_control
        diagnostics.append(
            _diagnostic(
                "disallowed_control_character",
                "AGENT.md contains a disallowed control or format character.",
                line=normalized.count("\n", 0, position) + 1,
            )
        )
    if diagnostics:
        return _failed_result(
            *diagnostics,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )

    stripped = normalized.strip()
    if not stripped:
        return _failed_result(
            "empty_document",
            "AGENT.md must contain the five-section Persona template.",
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    lines = [_Line(index, text) for index, text in enumerate(stripped.split("\n"), start=1)]
    h1 = lines[0].text.strip()
    if not h1.startswith("# ") or h1.startswith("## "):
        return _failed_result(
            "h1_required",
            "AGENT.md must start with exactly one H1 Agent name.",
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    h1_text = _clean_inline(h1[2:].strip())
    if not h1_text:
        return _failed_result(
            "name_empty",
            "The Agent display name cannot be empty.",
            line=lines[0].number,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    if len(h1_text) > 80:
        return _failed_result(
            "name_too_long",
            "The Agent display name exceeds 80 characters.",
            line=lines[0].number,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    if _has_forbidden_markup(h1[2:].strip()):
        return _failed_result(
            "unsupported_markup",
            "Links and HTML are not allowed in Persona content.",
            line=lines[0].number,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    extra_heading = next(
        (
            line
            for line in lines[1:]
            if _HEADING_RE.match(line.text.strip()) and not line.text.strip().startswith("## ")
        ),
        None,
    )
    if extra_heading is not None:
        return _failed_result(
            "unexpected_heading",
            "Only the required H1 and H2 headings are allowed.",
            line=extra_heading.number,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    if expected_name is not None and _clean_inline(expected_name.strip()) != h1_text:
        return _failed_result(
            "name_mismatch",
            "The H1 must match the Agent display name.",
            line=lines[0].number,
            field="identity.name",
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )

    for line in lines[1:]:
        heading = line.text.strip()
        if heading in {"## Debate strategy", "## Boundaries"}:
            field = "debate_strategy" if heading.endswith("strategy") else "boundaries"
            diagnostics.append(
                _diagnostic(
                    "removed_section",
                    "Debate strategy and Boundaries are not part of the current Persona template.",
                    line=line.number,
                    field=field,
                )
            )
    sections, parse_diagnostics = _parse_sections(lines[1:], section_names=_V2_SECTIONS)
    diagnostics.extend(parse_diagnostics)
    if diagnostics:
        return _failed_result(
            *diagnostics,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )

    values: dict[str, Any] = {
        "identity": {"name": h1_text},
        "cultural_lens": (),
        "core_values": (),
        "initial_position": "",
        "speaking_style": {},
        "source_agent_md_hash": source_hash,
        "compiler_version": PERSONA_COMPILER_VERSION_V2,
    }
    for section in _V2_SECTIONS:
        section_lines = sections[section]
        if section in {"Cultural lens", "Core values"}:
            parsed, section_errors = _parse_list(section, section_lines)
            diagnostics.extend(section_errors)
            values[_section_field(section)] = tuple(parsed)
        elif section == "Initial position":
            initial, section_errors = _parse_initial_position(section_lines)
            diagnostics.extend(section_errors)
            values["initial_position"] = initial
        else:
            parsed_scalars, section_errors = _parse_scalar_section(section, section_lines)
            diagnostics.extend(section_errors)
            if section == "Identity":
                values["identity"].update(parsed_scalars)
            else:
                values["speaking_style"] = parsed_scalars
    if diagnostics:
        return _failed_result(
            *diagnostics,
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    try:
        spec = PersonaSpecV2.model_validate(values)
    except ValueError:
        return _failed_result(
            "invalid_persona_schema",
            "The Persona content does not satisfy the closed five-section schema.",
            source_hash=source_hash,
            compiler_version=PERSONA_COMPILER_VERSION_V2,
        )
    serialized = canonical_json(spec)
    return PersonaCompileResult(
        ok=True,
        spec=spec,
        canonical_json=serialized,
        persona_spec_hash=persona_spec_hash(spec),
        source_agent_md_hash=source_hash,
        compiler_version=PERSONA_COMPILER_VERSION_V2,
        diagnostics=(),
    )


def compile_persona_v2_or_raise(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
) -> PersonaSpecV2:
    """Compile V2 and narrow the result for current-template consumers."""

    result = compile_persona_v2(source, expected_name=expected_name, agent_name=agent_name)
    if not result.compiled or not isinstance(result.spec, PersonaSpecV2):
        raise PersonaCompileError(result)
    return result.spec


def compile_persona_v1(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
) -> PersonaCompileResult:
    """Compile the immutable seven-section Persona template explicitly."""

    return _compile_persona_v1(source, expected_name=expected_name, agent_name=agent_name)


def compile_persona_v1_or_raise(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
) -> PersonaSpecV1:
    """Compile V1 and narrow the result for legacy-only consumers."""

    result = compile_persona_v1(source, expected_name=expected_name, agent_name=agent_name)
    if not result.compiled or not isinstance(result.spec, PersonaSpecV1):
        raise PersonaCompileError(result)
    return result.spec


def compile_persona(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
    schema_version: PersonaSchemaVersion | None = None,
    compiler_version: PersonaCompilerVersion | None = None,
    version: str | None = None,
) -> PersonaCompileResult:
    """Compile V2 by default while autodetecting immutable V1 Markdown.

    New five-section Markdown selects V2 without a flag.  A source containing
    either removed V2 heading is treated as legacy V1 for compatibility, so
    old raw bytes and their canonical V1 hashes remain readable.  Callers that
    need a strict V2 check can use :func:`compile_persona_v2` directly.
    """

    if agent_name is not None:
        if expected_name is not None and expected_name.strip() != agent_name.strip():
            try:
                source_hash = raw_agent_md_hash(source)
            except (TypeError, UnicodeDecodeError):
                source_hash = "sha256:" + "0" * 64
            return _failed_result(
                "conflicting_expected_name",
                "The expected Agent name is ambiguous.",
                source_hash=source_hash,
                compiler_version=_safe_compiler_version(compiler_version),
            )
        expected_name = agent_name

    requested_schema: PersonaSchemaVersion | None = schema_version
    if version is not None:
        version_map: dict[str, PersonaSchemaVersion] = {
            "v1": PERSONA_SCHEMA_VERSION_V1,
            "v2": PERSONA_SCHEMA_VERSION_V2,
            PERSONA_SCHEMA_VERSION_V1: PERSONA_SCHEMA_VERSION_V1,
            PERSONA_SCHEMA_VERSION_V2: PERSONA_SCHEMA_VERSION_V2,
            PERSONA_COMPILER_VERSION_V1: PERSONA_SCHEMA_VERSION_V1,
            PERSONA_COMPILER_VERSION_V2: PERSONA_SCHEMA_VERSION_V2,
        }
        mapped_version = version_map.get(version)
        if mapped_version is None:
            try:
                source_hash = raw_agent_md_hash(source)
            except (TypeError, UnicodeDecodeError):
                source_hash = "sha256:" + "0" * 64
            return _failed_result(
                "unsupported_persona_version",
                "The Persona schema version is not supported.",
                source_hash=source_hash,
                compiler_version=_safe_compiler_version(compiler_version),
            )
        if requested_schema is not None and requested_schema != mapped_version:
            try:
                source_hash = raw_agent_md_hash(source)
            except (TypeError, UnicodeDecodeError):
                source_hash = "sha256:" + "0" * 64
            return _failed_result(
                "conflicting_persona_version",
                "The Persona schema and requested versions do not agree.",
                source_hash=source_hash,
                compiler_version=_safe_compiler_version(compiler_version),
            )
        requested_schema = mapped_version
    if requested_schema is not None and requested_schema not in {
        PERSONA_SCHEMA_VERSION_V1,
        PERSONA_SCHEMA_VERSION_V2,
    }:
        try:
            source_hash = raw_agent_md_hash(source)
        except (TypeError, UnicodeDecodeError):
            source_hash = "sha256:" + "0" * 64
        return _failed_result(
            "unsupported_persona_version",
            "The Persona schema version is not supported.",
            source_hash=source_hash,
            compiler_version=_safe_compiler_version(compiler_version),
        )
    if compiler_version is not None:
        mapped_schema: PersonaSchemaVersion | None = (
            PERSONA_SCHEMA_VERSION_V1
            if compiler_version == PERSONA_COMPILER_VERSION_V1
            else PERSONA_SCHEMA_VERSION_V2
            if compiler_version == PERSONA_COMPILER_VERSION_V2
            else None
        )
        if mapped_schema is None:
            try:
                source_hash = raw_agent_md_hash(source)
            except (TypeError, UnicodeDecodeError):
                source_hash = "sha256:" + "0" * 64
            return _failed_result(
                "unsupported_compiler_version",
                "The Persona compiler version is not supported.",
                source_hash=source_hash,
                compiler_version=DEFAULT_PERSONA_COMPILER_VERSION,
            )
        if requested_schema is not None and requested_schema != mapped_schema:
            try:
                source_hash = raw_agent_md_hash(source)
            except (TypeError, UnicodeDecodeError):
                source_hash = "sha256:" + "0" * 64
            return _failed_result(
                "conflicting_persona_version",
                "The Persona schema and compiler versions do not agree.",
                source_hash=source_hash,
                compiler_version=compiler_version,
            )
        requested_schema = mapped_schema

    if requested_schema is not None:
        if requested_schema == PERSONA_SCHEMA_VERSION_V1:
            return _compile_persona_v1(source, expected_name=expected_name)
        return compile_persona_v2(source, expected_name=expected_name)

    try:
        normalized = normalize_agent_md(source)
    except (TypeError, UnicodeDecodeError):
        # V2 is the default for new drafts, including their safe invalid-input
        # diagnostic.  V1 callers still have the explicit version boundary.
        return compile_persona_v2(source, expected_name=expected_name)
    headings = {line.strip() for line in normalized.split("\n") if line.strip().startswith("## ")}
    if any(f"## {section}" in headings for section in ("Debate strategy", "Boundaries")):
        return _compile_persona_v1(source, expected_name=expected_name)
    if any(f"## {section}" in headings for section in _V2_SECTIONS):
        return compile_persona_v2(source, expected_name=expected_name)
    # A heading-less or otherwise unrecognizable value is ambiguous between a
    # malformed legacy draft and a malformed new draft.  Keep the public
    # compatibility entry point's V1 diagnostic shape; callers creating new
    # drafts can request the strict V2 boundary explicitly.
    return _compile_persona_v1(source, expected_name=expected_name)


def compile_agent_md(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
    schema_version: PersonaSchemaVersion | None = None,
    compiler_version: PersonaCompilerVersion | None = None,
    version: str | None = None,
) -> PersonaCompileResult:
    """Compatibility name for adapters that call the input ``agent_md``."""

    return compile_persona(
        source,
        expected_name=expected_name,
        agent_name=agent_name,
        schema_version=schema_version,
        compiler_version=compiler_version,
        version=version,
    )


def compile_persona_or_raise(
    source: str | bytes,
    *,
    expected_name: str | None = None,
    agent_name: str | None = None,
    schema_version: PersonaSchemaVersion | None = None,
    compiler_version: PersonaCompilerVersion | None = None,
    version: str | None = None,
) -> PersonaSpecVersion:
    result = compile_persona(
        source,
        expected_name=expected_name,
        agent_name=agent_name,
        schema_version=schema_version,
        compiler_version=compiler_version,
        version=version,
    )
    if not result.compiled or result.spec is None:
        raise PersonaCompileError(result)
    return result.spec


def looks_like_persona_template(source: str | bytes) -> bool:
    """Identify an authored document using the PersonaSpecV1 section vocabulary.

    This is only a compatibility/readability probe for older drafts.  It never
    accepts or compiles a document; callers must still run ``compile_persona``.
    """

    try:
        normalized = normalize_agent_md(source)
    except (TypeError, UnicodeDecodeError):
        return False
    return "## Identity" in normalized


def _parse_sections(
    lines: Sequence[_Line],
    *,
    section_names: Sequence[str] = _SECTIONS,
) -> tuple[dict[str, list[_Line]], list[PersonaDiagnostic]]:
    sections: dict[str, list[_Line]] = {section: [] for section in section_names}
    diagnostics: list[PersonaDiagnostic] = []
    index = 0
    section_set = set(section_names)
    for expected in section_names:
        while index < len(lines) and not lines[index].text.strip():
            index += 1
        if index >= len(lines):
            diagnostics.append(
                _diagnostic(
                    "section_missing", "A required Persona section is missing.", field=expected
                )
            )
            continue
        header = lines[index].text.strip()
        if header != f"## {expected}":
            if _HEADING_RE.match(header):
                diagnostics.append(
                    _diagnostic(
                        "section_order",
                        "Persona sections must appear exactly once in the required order.",
                        line=lines[index].number,
                        field=expected,
                    )
                )
            else:
                diagnostics.append(
                    _diagnostic(
                        "content_outside_section",
                        "Content outside the Persona template is not allowed.",
                        line=lines[index].number,
                        field=expected,
                    )
                )
            # Consume until the next heading so one malformed section cannot
            # turn every subsequent field into a misleading duplicate error.
            while index < len(lines) and not _HEADING_RE.match(lines[index].text.strip()):
                index += 1
            continue
        index += 1
        start = index
        while index < len(lines) and not _HEADING_RE.match(lines[index].text.strip()):
            index += 1
        sections[expected] = list(lines[start:index])
    while index < len(lines):
        if lines[index].text.strip():
            diagnostics.append(
                _diagnostic(
                    "content_outside_section",
                    "Content outside the Persona template is not allowed.",
                    line=lines[index].number,
                )
            )
        index += 1
    # A malformed order may leave a known section unconsumed.  Report only
    # headings here; body content was already reported by the owning pass.
    for line in lines:
        text = line.text.strip()
        if text.startswith("## ") and text[3:] not in section_set:
            diagnostics.append(
                _diagnostic("unknown_section", "Unknown Persona section.", line=line.number)
            )
        elif text.startswith("#") and not text.startswith("## ") and text:
            diagnostics.append(
                _diagnostic(
                    "unexpected_heading",
                    "Only the required H1 and H2 headings are allowed.",
                    line=line.number,
                )
            )
    return sections, _dedupe_diagnostics(diagnostics)


def _parse_scalar_section(
    section: str, lines: Sequence[_Line]
) -> tuple[dict[str, str], list[PersonaDiagnostic]]:
    expected = _SCALAR_SECTIONS[section]
    values: dict[str, str] = {}
    diagnostics: list[PersonaDiagnostic] = []
    for line in lines:
        raw = line.text
        if not raw.strip():
            continue
        if not raw.startswith("- "):
            code = "nested_list" if raw.lstrip().startswith(("- ", "* ", "+ ")) else "invalid_field"
            message = (
                "Nested Persona lists are not allowed."
                if code == "nested_list"
                else "Identity and Speaking style contain named flat fields only."
            )
            diagnostics.append(_diagnostic(code, message, line=line.number, field=section))
            continue
        content = raw[2:].strip()
        if ":" not in content:
            diagnostics.append(
                _diagnostic(
                    "invalid_field",
                    "Each named field must use its exact ASCII label.",
                    line=line.number,
                    field=section,
                )
            )
            continue
        label, value = content.split(":", 1)
        if label not in expected:
            diagnostics.append(
                _diagnostic(
                    "unknown_field", "Unknown Persona field.", line=line.number, field=section
                )
            )
            continue
        if label in values:
            diagnostics.append(
                _diagnostic(
                    "duplicate_field",
                    "Persona fields may appear only once.",
                    line=line.number,
                    field=label,
                )
            )
            continue
        cleaned, error = _value(
            value, max_chars=expected[label][1], line=line.number, field=expected[label][0]
        )
        if error is not None:
            diagnostics.append(error)
        elif cleaned is not None:
            values[expected[label][0]] = cleaned
    for _label, (field, _limit) in expected.items():
        if field not in values:
            diagnostics.append(
                _diagnostic("field_missing", "A required Persona field is missing.", field=field)
            )
    return values, diagnostics


def _parse_list(section: str, lines: Sequence[_Line]) -> tuple[list[str], list[PersonaDiagnostic]]:
    values: list[str] = []
    diagnostics: list[PersonaDiagnostic] = []
    seen: set[str] = set()
    for line in lines:
        raw = line.text
        if not raw.strip():
            continue
        if not raw.startswith("- "):
            diagnostics.append(
                _diagnostic(
                    "flat_list_required",
                    "This Persona section accepts flat bullet items only.",
                    line=line.number,
                    field=section,
                )
            )
            continue
        item = raw[2:].strip()
        if item.startswith(("- ", "* ", "+ ")):
            diagnostics.append(
                _diagnostic(
                    "nested_list",
                    "Nested Persona lists are not allowed.",
                    line=line.number,
                    field=section,
                )
            )
            continue
        cleaned, error = _value(
            item, max_chars=240, line=line.number, field=_section_field(section)
        )
        if error is not None:
            diagnostics.append(error)
            continue
        if cleaned is None:
            continue
        key = cleaned.casefold()
        if key in seen:
            diagnostics.append(
                _diagnostic(
                    "duplicate_item",
                    "Persona list items must be unique.",
                    line=line.number,
                    field=section,
                )
            )
            continue
        seen.add(key)
        values.append(cleaned)
    if not values:
        diagnostics.append(
            _diagnostic("list_missing", "Each Persona list must contain 1–8 items.", field=section)
        )
    elif len(values) > 8:
        diagnostics.append(
            _diagnostic("list_too_long", "Each Persona list must contain 1–8 items.", field=section)
        )
    return values, diagnostics


def _parse_initial_position(lines: Sequence[_Line]) -> tuple[str, list[PersonaDiagnostic]]:
    diagnostics: list[PersonaDiagnostic] = []
    if not any(line.text.strip() for line in lines):
        return "", [
            _diagnostic(
                "field_missing",
                "Initial position must contain one or more paragraphs.",
                field="initial_position",
            )
        ]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        raw = line.text
        if not raw.strip():
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
            continue
        if _HEADING_RE.match(raw.strip()):
            diagnostics.append(
                _diagnostic(
                    "unexpected_heading",
                    "Initial position cannot contain headings.",
                    line=line.number,
                    field="initial_position",
                )
            )
            continue
        if raw.lstrip().startswith(("- ", "* ", "+ ")) or re.match(r"^\s*\d+[.)]\s", raw):
            diagnostics.append(
                _diagnostic(
                    "plain_paragraph_required",
                    "Initial position must contain plain Markdown paragraphs.",
                    line=line.number,
                    field="initial_position",
                )
            )
            continue
        if raw.lstrip().startswith(">") or raw.strip().startswith(
            ("```", "~~~", "---", "***", "___")
        ):
            diagnostics.append(
                _diagnostic(
                    "plain_paragraph_required",
                    "Initial position must contain plain Markdown paragraphs.",
                    line=line.number,
                    field="initial_position",
                )
            )
            continue
        if _has_forbidden_markup(raw):
            diagnostics.append(
                _diagnostic(
                    "unsupported_markup",
                    "Links and HTML are not allowed in Persona content.",
                    line=line.number,
                    field="initial_position",
                )
            )
            continue
        current.append(raw.strip())
    if current:
        paragraphs.append("\n".join(current).strip())
    text = "\n\n".join(item for item in paragraphs if item)
    if not text:
        diagnostics.append(
            _diagnostic(
                "field_missing",
                "Initial position must contain one or more paragraphs.",
                field="initial_position",
            )
        )
    elif len(text) > 1_000:
        diagnostics.append(
            _diagnostic(
                "value_too_long",
                "Initial position exceeds 1,000 characters.",
                field="initial_position",
            )
        )
    return text, diagnostics


def _value(
    raw: str, *, max_chars: int, line: int, field: str
) -> tuple[str | None, PersonaDiagnostic | None]:
    if _has_forbidden_markup(raw):
        return None, _diagnostic(
            "unsupported_markup",
            "Links and HTML are not allowed in Persona content.",
            line=line,
            field=field,
        )
    cleaned = _clean_inline(raw.strip())
    if not cleaned:
        return None, _diagnostic(
            "value_missing", "Persona values cannot be empty.", line=line, field=field
        )
    if len(cleaned) > max_chars:
        return None, _diagnostic(
            "value_too_long", "A Persona value exceeds its character limit.", line=line, field=field
        )
    return cleaned, None


def _clean_inline(value: str) -> str:
    """Reduce emphasis/code delimiters to visible text without interpreting it."""

    result = value
    result = re.sub(r"`([^`\n]*)`", r"\1", result)
    # Repeatedly unwrap the finite set of Markdown emphasis pairs accepted by
    # the contract.  Unmatched punctuation remains ordinary visible text; it
    # is never executed as an instruction.
    patterns = (
        (r"\*\*(\S(?:.*?\S)?)\*\*", r"\1"),
        (r"__(\S(?:.*?\S)?)__", r"\1"),
        (r"~~(\S(?:.*?\S)?)~~", r"\1"),
        (r"(?<!\w)\*(\S(?:.*?\S)?)\*(?!\w)", r"\1"),
        (r"(?<!\w)_(\S(?:.*?\S)?)_(?!\w)", r"\1"),
    )
    for _ in range(3):
        changed = False
        for pattern, replacement in patterns:
            result, count = re.subn(pattern, replacement, result)
            changed = changed or count > 0
        if not changed:
            break
    return result.strip()


def _has_forbidden_markup(value: str) -> bool:
    return bool(
        _HTML_RE.search(value)
        or _LINK_RE.search(value)
        or _REFERENCE_LINK_RE.search(value)
        or _URL_RE.search(value)
    )


def _first_disallowed_control(value: str) -> tuple[int, str] | None:
    for position, character in enumerate(value):
        if character in {"\n", "\t"}:
            continue
        category = unicodedata.category(character)
        if category.startswith("C"):
            return position, character
    return None


def _section_field(section: str) -> str:
    return {
        "Cultural lens": "cultural_lens",
        "Core values": "core_values",
        "Debate strategy": "debate_strategy",
        "Boundaries": "boundaries",
    }[section]


def _diagnostic(
    code: str,
    message: str,
    *,
    line: int | None = None,
    field: str | None = None,
) -> PersonaDiagnostic:
    return PersonaDiagnostic(code=code, message=message, line=line, field=field)


def _failed_result(
    *diagnostics: PersonaDiagnostic | str,
    source_hash: str,
    line: int | None = None,
    field: str | None = None,
    compiler_version: PersonaCompilerVersion = PERSONA_COMPILER_VERSION,
) -> PersonaCompileResult:
    normalized: list[PersonaDiagnostic] = []
    index = 0
    while index < len(diagnostics):
        diagnostic = diagnostics[index]
        if isinstance(diagnostic, PersonaDiagnostic):
            normalized.append(diagnostic)
            index += 1
        else:
            message = "Persona compilation failed."
            if index + 1 < len(diagnostics) and isinstance(diagnostics[index + 1], str):
                message = cast(str, diagnostics[index + 1])
                index += 1
            normalized.append(_diagnostic(diagnostic, message, line=line, field=field))
            index += 1
    return PersonaCompileResult(
        ok=False,
        spec=None,
        canonical_json=None,
        persona_spec_hash=None,
        source_agent_md_hash=source_hash,
        compiler_version=compiler_version,
        diagnostics=tuple(_dedupe_diagnostics(normalized)),
    )


def _safe_compiler_version(value: object) -> PersonaCompilerVersion:
    if value == PERSONA_COMPILER_VERSION_V1:
        return PERSONA_COMPILER_VERSION_V1
    if value == PERSONA_COMPILER_VERSION_V2:
        return PERSONA_COMPILER_VERSION_V2
    return DEFAULT_PERSONA_COMPILER_VERSION


def _dedupe_diagnostics(values: Sequence[PersonaDiagnostic]) -> list[PersonaDiagnostic]:
    result: list[PersonaDiagnostic] = []
    seen: set[tuple[str, int | None, str | None]] = set()
    for item in values:
        key = (item.code, item.line, item.field)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


__all__ = [
    "CURRENT_PERSONA_COMPILER_VERSION",
    "CURRENT_PERSONA_PROVIDER_VIEW_VERSION",
    "CURRENT_PERSONA_SCHEMA_VERSION",
    "DEFAULT_PERSONA_COMPILER_VERSION",
    "DEFAULT_PERSONA_PROVIDER_VIEW_VERSION",
    "DEFAULT_PERSONA_SCHEMA_VERSION",
    "MAX_AGENT_MD_CHARS",
    "PERSONA_COMPILER_VERSION",
    "PERSONA_COMPILER_VERSION_V1",
    "PERSONA_COMPILER_VERSION_V2",
    "PERSONA_PROVIDER_VIEW_VERSION",
    "PERSONA_PROVIDER_VIEW_VERSION_V1",
    "PERSONA_PROVIDER_VIEW_VERSION_V2",
    "PERSONA_SCHEMA_VERSION",
    "PERSONA_SCHEMA_VERSION_V1",
    "PERSONA_SCHEMA_VERSION_V2",
    "PersonaCompilerVersion",
    "PersonaClosedModel",
    "PersonaCompileError",
    "PersonaCompileResult",
    "PersonaDiagnostic",
    "PersonaIdentity",
    "PersonaCompiler",
    "PersonaProviderIdentityError",
    "PersonaProviderViewVersion",
    "PersonaProviderViewVersionDTO",
    "PersonaProviderViewV1",
    "PersonaProviderViewV2",
    "ProviderPersonaView",
    "PersonaSpeakingStyle",
    "PersonaSpec",
    "PersonaSpecVersion",
    "PersonaSpecV1",
    "PersonaSpecV2",
    "PersonaSchemaVersion",
    "canonical_json",
    "canonical_json_bytes",
    "compile_agent_md",
    "compile_persona",
    "compile_persona_v1",
    "compile_persona_v1_or_raise",
    "compile_persona_or_raise",
    "compile_persona_v2",
    "compile_persona_v2_or_raise",
    "diagnostics_json",
    "hash_agent_md",
    "hash_persona_spec",
    "looks_like_persona_template",
    "normalize_agent_md",
    "parse_persona_spec",
    "parse_stored_persona",
    "persona_spec_hash",
    "provider_view",
    "provider_view_v1",
    "provider_view_v2",
    "raw_agent_md_hash",
]
