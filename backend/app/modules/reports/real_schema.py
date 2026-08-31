"""Closed provider boundary types for the fixed Real Maya report path.

The report service owns the durable manifest and Markdown rendering.  This
module is deliberately smaller: it accepts only public report projections and
returns six prose fields.  No authored Persona/AGENT text, row identity or
provider metadata is part of these types.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .schemas import ReportSectionOutput

REPORT_SECTION_FIELDS: Final[tuple[str, ...]] = (
    "debate_overview",
    "evidence_and_arguments",
    "areas_of_convergence",
    "continuing_tensions_and_questions",
    "classroom_perspectives",
    "mutual_learning_reflection",
)
REPORT_SCHEMA_NAME: Final = "maya_report_sections_v1"
REPORT_SCHEMA_VERSION: Final = "report_sections_v1"
REPORT_SECTION_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(REPORT_SECTION_FIELDS),
    "properties": {
        field: {"type": "string", "minLength": 1, "maxLength": 4000}
        for field in REPORT_SECTION_FIELDS
    },
}


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


REPORT_SECTION_SCHEMA_HASH: Final = hashlib.sha256(
    _canonical(REPORT_SECTION_SCHEMA).encode("utf-8")
).hexdigest()
# A descriptive alias keeps tests and a future runtime free to use either name.
REPORT_OUTPUT_SCHEMA_HASH: Final = REPORT_SECTION_SCHEMA_HASH

Slot = Literal["A", "B", "C", "D", "E"]
InsightCategory = Literal["support", "challenge", "question"]


class ReportBoundaryError(ValueError):
    """A safe, value-free report boundary failure."""

    def __init__(self, code: str = "report_boundary_invalid") -> None:
        super().__init__(code)
        self.code = code


# These patterns are applied to text fields only. Opaque evidence keys are
# typed separately and are the one permitted identifier in the provider input.
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_RE = re.compile(r"(?<!\w)\+?[0-9][0-9 ()-]{7,}[0-9](?!\w)")
_SECRET_RE = re.compile(
    r"(?i)(?:api[_ -]?key|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]+|"
    r"password\s*[:=]|secret\s*[:=]|(?:^|\W)sk-[A-Za-z0-9])"
)
_PRIVATE_ID_RE = re.compile(
    r"(?i)\b(?:user|student|member|author|nickname)[ _-]?(?:id|uuid|email|phone|name)\b"
)
_PROVIDER_INTERNAL_RE = re.compile(
    r"(?i)(?:https?://|(?:^|\W)(?:dashscope|qwen|provider|endpoint|workspace|model)"
    r"(?:$|\W))"
)
_ABSOLUTE_PATH_RE = re.compile(
    r"(?:^|\s)/(?:Users|private|var|tmp|home|etc|opt|workspace)(?:/|\s|$)|"
    r"(?<!\w)[A-Za-z]:[\\/]"
)
_MARKDOWN_RE = re.compile(
    r"(?m)(?:^\s{0,3}#{1,6}\s|```|\*\*|__|~~|^\s*[-*+]\s|"
    r"^\s*[0-9]+\.\s|\[[^\]]*\]\([^)]*\)|<[^>]+>)"
)
_CITATION_RE = re.compile(r"\[\s*(?:evidence|citation)\s*:[^\]]+\]", re.IGNORECASE)
_UNSAFE_WINNER_RE = re.compile(
    r"(?i)\b(?:winner|winners|winning|won|loser|champion|victor|"
    r"vote\s+for\s+me|please\s+vote|most\s+popular|ranked\s+first)\b"
)
_VOTE_TOTAL_RE = re.compile(
    r"(?i)(?:\b(?:vote|votes|voting)\b[^.\n]{0,48}\b[0-9]+\b|"
    r"\b[0-9]+\b[^.\n]{0,48}\b(?:vote|votes)\b)"
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportParticipant(_ClosedModel):
    """A public Agent projection, intentionally without Agent/Persona IDs."""

    slot: Slot
    agent_name: str = Field(min_length=1, max_length=160)
    position_summary: str = Field(min_length=1, max_length=1600)


class ReportSpeech(_ClosedModel):
    """One public final-ready speech and only the evidence it actually used."""

    slot: Slot
    round_no: int = Field(ge=1, le=2)
    turn_index: int = Field(ge=0, le=999)
    speech: str = Field(min_length=1, max_length=8000)
    used_evidence_ids: tuple[str, ...] = ()


class ReportSource(_ClosedModel):
    """A used TurnSource projection with no filename, path or full chunk."""

    # Retrieval receipts use opaque ``evidence-*`` keys in addition to UUID
    # fixtures.  The provider never authors or resolves this key; the service
    # maps it back to the immutable TurnSource row when rendering citations.
    evidence_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    excerpt: str = Field(min_length=1, max_length=2400)


class ReportVote(_ClosedModel):
    """An aggregate count keyed only by the public participant slot."""

    slot: Slot
    count: int = Field(ge=0, le=1_000_000)


class ReportInsight(_ClosedModel):
    """An anonymous, already-summarized classroom insight."""

    category: InsightCategory
    summary: str = Field(min_length=1, max_length=1600)


class ReportRequest(_ClosedModel):
    """The complete allowlisted input for one report-section generation."""

    topic: str = Field(min_length=1, max_length=1200)
    participants: tuple[ReportParticipant, ...] = Field(min_length=2, max_length=5)
    speeches: tuple[ReportSpeech, ...] = Field(min_length=1, max_length=10)
    sources: tuple[ReportSource, ...] = Field(default=(), max_length=64)
    votes: tuple[ReportVote, ...] = Field(default=(), max_length=5)
    insights: tuple[ReportInsight, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def validate_closed_boundary(self) -> ReportRequest:
        _validate_request_semantics(self)
        return self

    def canonical_payload(self) -> dict[str, object]:
        """Return deterministic provider-visible data, excluding private IDs."""

        payload = cast(dict[str, object], self.model_dump(mode="json"))
        payload["participants"] = sorted(
            cast(list[dict[str, object]], payload["participants"]),
            key=lambda row: str(row["slot"]),
        )
        payload["speeches"] = sorted(
            cast(list[dict[str, object]], payload["speeches"]),
            key=lambda row: (
                int(cast(int, row["turn_index"])),
                int(cast(int, row["round_no"])),
                str(row["slot"]),
            ),
        )
        payload["sources"] = sorted(
            cast(list[dict[str, object]], payload["sources"]),
            key=lambda row: str(row["evidence_id"]),
        )
        payload["votes"] = sorted(
            cast(list[dict[str, object]], payload["votes"]),
            key=lambda row: str(row["slot"]),
        )
        payload["insights"] = sorted(
            cast(list[dict[str, object]], payload["insights"]),
            key=lambda row: (str(row["category"]), str(row["summary"])),
        )
        return payload

    def canonical_json(self) -> str:
        return _canonical(self.canonical_payload())

    def input_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _text_error(value: str, *, output: bool = False) -> str | None:
    if not value.strip() or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        return "report_output_text" if output else "report_input_text"
    if _CJK_RE.search(value):
        return "report_output_language" if output else "report_input_language"
    if _SECRET_RE.search(value) or _EMAIL_RE.search(value) or _PHONE_RE.search(value):
        return "report_output_private" if output else "report_input_private"
    if _UUID_RE.search(value) or _PRIVATE_ID_RE.search(value):
        return "report_output_identity" if output else "report_input_identity"
    if _ABSOLUTE_PATH_RE.search(value) or _PROVIDER_INTERNAL_RE.search(value):
        return "report_output_internal" if output else "report_input_internal"
    if _MARKDOWN_RE.search(value) or _CITATION_RE.search(value):
        return "report_output_markdown" if output else "report_input_markdown"
    if _UNSAFE_WINNER_RE.search(value):
        return "report_output_winner_language" if output else "report_input_winner_language"
    return None


def _validate_request_semantics(request: ReportRequest) -> None:
    text_values = [request.topic]
    text_values.extend(
        value
        for participant in request.participants
        for value in (participant.agent_name, participant.position_summary)
    )
    text_values.extend(speech.speech for speech in request.speeches)
    text_values.extend(source.excerpt for source in request.sources)
    text_values.extend(insight.summary for insight in request.insights)
    for value in text_values:
        error = _text_error(value)
        if error is not None:
            raise ReportBoundaryError(error)

    slots = [participant.slot for participant in request.participants]
    if len(set(slots)) != len(slots):
        raise ReportBoundaryError("report_duplicate_slot")
    known_slots = set(slots)
    speech_keys = {(speech.round_no, speech.turn_index) for speech in request.speeches}
    if len(speech_keys) != len(request.speeches):
        raise ReportBoundaryError("report_duplicate_turn")
    if any(speech.slot not in known_slots for speech in request.speeches):
        raise ReportBoundaryError("report_unknown_speech_slot")
    source_ids = [str(source.evidence_id) for source in request.sources]
    if len(set(source_ids)) != len(source_ids):
        raise ReportBoundaryError("report_duplicate_evidence")
    used_ids = [
        str(evidence_id)
        for speech in request.speeches
        for evidence_id in speech.used_evidence_ids
    ]
    if any(used_id not in set(source_ids) for used_id in used_ids):
        raise ReportBoundaryError("report_evidence_not_available")
    if set(used_ids) != set(source_ids):
        raise ReportBoundaryError("report_unused_evidence")
    vote_slots = [vote.slot for vote in request.votes]
    if len(set(vote_slots)) != len(vote_slots) or any(
        slot not in known_slots for slot in vote_slots
    ):
        raise ReportBoundaryError("report_vote_projection")


def validate_report_request(value: ReportRequest | Mapping[str, object]) -> ReportRequest:
    """Validate a request while exposing only a safe boundary code."""

    if isinstance(value, ReportRequest):
        return value
    try:
        return ReportRequest.model_validate(value)
    except ValidationError as exc:
        # Pydantic wraps model-validator errors.  Recover only our closed
        # machine code, never the offending value or validator message.
        for item in exc.errors():
            context = item.get("ctx")
            wrapped = context.get("error") if isinstance(context, Mapping) else None
            match = re.search(r"\breport_[a-z0-9_]+\b", str(wrapped))
            if match:
                raise ReportBoundaryError(match.group(0)) from None
        raise ReportBoundaryError("report_input_invalid") from None
    except ReportBoundaryError:
        raise
    except (TypeError, ValueError):
        raise ReportBoundaryError("report_input_invalid") from None


def validate_report_sections(value: object) -> ReportSectionOutput:
    """Validate six English prose sections before the service renders Markdown."""

    if isinstance(value, ReportSectionOutput):
        sections = value
    elif isinstance(value, Mapping):
        if set(value) != set(REPORT_SECTION_FIELDS):
            raise ReportBoundaryError("report_output_schema")
        try:
            sections = ReportSectionOutput.model_validate(value)
        except ValidationError:
            raise ReportBoundaryError("report_output_schema") from None
    else:
        raise ReportBoundaryError("report_output_schema")
    values = sections.model_dump()
    for field in REPORT_SECTION_FIELDS:
        text_value = values.get(field)
        if not isinstance(text_value, str) or len(text_value) > 4000:
            raise ReportBoundaryError("report_output_schema")
        error = _text_error(text_value, output=True)
        if error is not None:
            raise ReportBoundaryError(error)
        if _VOTE_TOTAL_RE.search(text_value):
            raise ReportBoundaryError("report_output_vote_total")
    return sections


# Public aliases make the narrow contract convenient for tests and a future
# service worker without introducing another report DTO family.
ReportEvidence = ReportSource
ReportSpeechInput = ReportSpeech
ReportParticipantInput = ReportParticipant
AnonymousInsightSummary = ReportInsight


__all__ = [
    "AnonymousInsightSummary",
    "InsightCategory",
    "REPORT_OUTPUT_SCHEMA_HASH",
    "REPORT_SCHEMA_NAME",
    "REPORT_SCHEMA_VERSION",
    "REPORT_SECTION_FIELDS",
    "REPORT_SECTION_SCHEMA",
    "REPORT_SECTION_SCHEMA_HASH",
    "ReportBoundaryError",
    "ReportEvidence",
    "ReportInsight",
    "ReportParticipant",
    "ReportParticipantInput",
    "ReportRequest",
    "ReportSource",
    "ReportSpeech",
    "ReportSpeechInput",
    "ReportVote",
    "Slot",
    "validate_report_request",
    "validate_report_sections",
]
